"""Core state structures for the trade risk engine.

All structures are immutable (or immutable-in-practice via ``gc=False``) so
that the evaluator is deterministic across multiple gates and a decision can
be replayed from its inputs alone. JSON round-trip helpers are provided on
``RiskDecision`` and ``RiskContext`` so that a crashed evaluation can be
persisted, audited, and reloaded.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

import msgspec
from pydantic import BaseModel


class RiskContext(msgspec.Struct, frozen=True):
    """Immutable configuration for all risk gates.

    The context captures capital protection thresholds and latency budgets that
    should remain stable for a single evaluation pass. It is frozen to make the
    evaluator deterministic and prevent gates from mutating policy while a trade
    is being reviewed.
    """

    max_daily_drawdown_pct: float = 0.10
    max_weekly_drawdown_pct: float = 0.20
    max_correlated_exposure: float = 2500.0
    min_expected_value: float = 0.0
    latency_budget_us: int = 500
    consecutive_loss_limit: int = 0
    consecutive_loss_window_minutes: float = 15.0

    def to_json(self) -> str:
        """Serialize the context to a JSON string for persistence/audit.

        Floats are serialized losslessly via ``json.dumps``'s native repr.
        ``NaN``/``Infinity`` are intentionally rejected by the ``allow_nan=False``
        flag: a context configured with non-finite policy thresholds is not a
        valid context and round-tripping it would be meaningless.
        """
        data: dict[str, Any] = {
            "max_daily_drawdown_pct": self.max_daily_drawdown_pct,
            "max_weekly_drawdown_pct": self.max_weekly_drawdown_pct,
            "max_correlated_exposure": self.max_correlated_exposure,
            "min_expected_value": self.min_expected_value,
            "latency_budget_us": int(self.latency_budget_us),
            "consecutive_loss_limit": int(self.consecutive_loss_limit),
            "consecutive_loss_window_minutes": float(self.consecutive_loss_window_minutes),
        }
        return json.dumps(data, allow_nan=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str | bytes) -> RiskContext:
        """Reconstruct a ``RiskContext`` from a JSON string.

        Unknown keys are ignored so that older payloads remain loadable after
        the context grows new fields. Used for crash-recovery: the persisted
        context that produced a (possibly un-flushed) decision is restored
        exactly before the audit log is written.
        """
        data = json.loads(payload)
        known = {
            "max_daily_drawdown_pct",
            "max_weekly_drawdown_pct",
            "max_correlated_exposure",
            "min_expected_value",
            "latency_budget_us",
            "consecutive_loss_limit",
            "consecutive_loss_window_minutes",
        }
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(**kwargs)


class Position(msgspec.Struct, gc=False):
    """Memory-efficient representation of an open or resolved market position.

    Positions are grouped by ``family`` so the concentration gate can aggregate
    related exposure across contracts that share an event, market theme, or
    correlated payoff. Resolved positions stay representable but are ignored for
    active exposure limits.
    """

    ticker: str
    family: str
    cost_basis: float
    current_value: float
    is_resolved: bool


class RiskDecision(msgspec.Struct, gc=False):
    """Outcome returned by the risk engine for a proposed trade.

    ``approved`` is the final allow/deny flag, ``reason_code`` identifies the
    first gate that rejected the trade or ``OK``, and ``suggested_size`` carries
    the proposed or adjusted notional amount for downstream execution code.
    """

    approved: bool
    reason_code: str
    suggested_size: float

    def to_json(self) -> str:
        """Serialize the decision to a JSON string for crash recovery / audit.

        Non-finite ``suggested_size`` values (``NaN``/``Infinity``) are
        rejected: a decision cannot meaningfully be persisted with a
        non-executable size, and the strict ``allow_nan=False`` flag enforces
        that the recovery path can never rehydrate an unsound decision.
        """
        data: dict[str, Any] = {
            "approved": bool(self.approved),
            "reason_code": str(self.reason_code),
            "suggested_size": float(self.suggested_size),
        }
        return json.dumps(data, allow_nan=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str | bytes) -> RiskDecision:
        """Reconstruct a ``RiskDecision`` from a JSON string."""
        data = json.loads(payload)
        return cls(
            approved=bool(data["approved"]),
            reason_code=str(data["reason_code"]),
            suggested_size=float(data["suggested_size"]),
        )


class TradeOutcome(BaseModel):
    """Representation of a past trade outcome for consecutive loss gating.

    PnL is negative for a loss and positive / zero for a win. ``timestamp`` is
    kept timezone-agnostic intentionally: callers may use naive UTC or
    timezone-aware datetimes, but mixing the two in a single outcome list is
    a caller bug (and the gate surfaces it via the underlying timedelta
    comparison rather than silently coercing).
    """

    timestamp: datetime
    pnl: float


def is_safe_float(x: float) -> bool:
    """True iff ``x`` is finite and not a NaN/inf.

    Shared by gates and JSON helpers so that the definition of "safe" never
    drifts between evaluation boundaries and persistence boundaries.
    """
    return isinstance(x, float) and math.isfinite(x)
