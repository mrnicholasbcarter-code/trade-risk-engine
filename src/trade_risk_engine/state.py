"""Core state structures for the trade risk engine.

The public state objects are immutable and versioned so that a crash-recovered
risk session can be serialized, audited, and restored deterministically.
"""

from __future__ import annotations

import math
from datetime import datetime

import msgspec
from pydantic import BaseModel, ConfigDict

RISK_STATE_SCHEMA_VERSION = 1


def _ensure_finite(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")


class RiskContext(msgspec.Struct, frozen=True):
    """Immutable configuration for all risk gates."""

    max_daily_drawdown_pct: float = 0.10
    max_weekly_drawdown_pct: float = 0.20
    max_correlated_exposure: float = 2500.0
    min_expected_value: float = 0.0
    latency_budget_us: int = 500
    consecutive_loss_limit: int = 0
    consecutive_loss_window_minutes: float = 15.0

    def __post_init__(self) -> None:
        if type(self.latency_budget_us) is not int:
            raise ValueError("latency_budget_us must be an int")
        if type(self.consecutive_loss_limit) is not int:
            raise ValueError("consecutive_loss_limit must be an int")
        _ensure_finite(self.max_daily_drawdown_pct, "max_daily_drawdown_pct")
        _ensure_finite(self.max_weekly_drawdown_pct, "max_weekly_drawdown_pct")
        _ensure_finite(self.max_correlated_exposure, "max_correlated_exposure")
        _ensure_finite(self.min_expected_value, "min_expected_value")
        _ensure_finite(self.consecutive_loss_window_minutes, "consecutive_loss_window_minutes")

    def to_json(self) -> str:
        """Serialize the context to a JSON string for persistence/audit."""
        return msgspec.json.encode(self).decode("utf-8")

    @classmethod
    def from_json(cls, payload: str | bytes) -> RiskContext:
        """Reconstruct a ``RiskContext`` from a JSON string."""
        try:
            return msgspec.json.decode(payload, type=cls)
        except Exception as exc:  # pragma: no cover - surfaced as ValueError to callers
            raise ValueError(f"Invalid RiskContext payload: {exc}") from exc


class Position(msgspec.Struct, gc=False):
    """Memory-efficient representation of an open or resolved market position."""

    ticker: str
    family: str
    cost_basis: float
    current_value: float
    is_resolved: bool

    def __post_init__(self) -> None:
        if type(self.ticker) is not str:
            raise ValueError("ticker must be a string")
        if type(self.family) is not str:
            raise ValueError("family must be a string")
        if type(self.is_resolved) is not bool:
            raise ValueError("is_resolved must be a bool")
        _ensure_finite(self.cost_basis, "cost_basis")
        _ensure_finite(self.current_value, "current_value")


class RiskDecision(msgspec.Struct, gc=False):
    """Outcome returned by the risk engine for a proposed trade."""

    approved: bool
    reason_code: str
    suggested_size: float

    def __post_init__(self) -> None:
        if type(self.approved) is not bool:
            raise ValueError("approved must be a bool")
        if type(self.reason_code) is not str:
            raise ValueError("reason_code must be a string")
        _ensure_finite(self.suggested_size, "suggested_size")

    def to_json(self) -> str:
        """Serialize the decision to a JSON string for crash recovery / audit."""
        return msgspec.json.encode(self).decode("utf-8")

    @classmethod
    def from_json(cls, payload: str | bytes) -> RiskDecision:
        """Reconstruct a ``RiskDecision`` from a JSON string."""
        try:
            return msgspec.json.decode(payload, type=cls)
        except Exception as exc:  # pragma: no cover - surfaced as ValueError to callers
            raise ValueError(f"Invalid RiskDecision payload: {exc}") from exc


class KillSwitchState(msgspec.Struct, frozen=True):
    """Serializable snapshot of a manual kill switch."""

    tripped: bool = False
    reason: str = "ERR_KILL_SWITCH_MANUAL"
    tripped_at: datetime | None = None


class TimedCircuitBreakerState(msgspec.Struct, frozen=True):
    """Serializable snapshot of the time-based circuit breaker."""

    consecutive_loss_threshold: int = 3
    cooldown_hours: float = 24.0
    loss_streak: int = 0
    tripped: bool = False
    tripped_at: datetime | None = None

    def __post_init__(self) -> None:
        if type(self.consecutive_loss_threshold) is not int:
            raise ValueError("consecutive_loss_threshold must be an int")
        if type(self.loss_streak) is not int:
            raise ValueError("loss_streak must be an int")
        if self.consecutive_loss_threshold < 1:
            raise ValueError("consecutive_loss_threshold must be >= 1")
        if self.cooldown_hours <= 0:
            raise ValueError("cooldown_hours must be > 0")
        if self.loss_streak < 0:
            raise ValueError("loss_streak must be >= 0")


class ConsecutiveLossGateState(msgspec.Struct, frozen=True):
    """Serializable snapshot of the rolling consecutive-loss gate."""

    max_losses: int
    window_trades: int
    history: tuple[bool, ...] = ()

    def __post_init__(self) -> None:
        if type(self.max_losses) is not int:
            raise ValueError("max_losses must be an int")
        if type(self.window_trades) is not int:
            raise ValueError("window_trades must be an int")
        if self.max_losses < 1:
            raise ValueError("max_losses must be >= 1")
        if self.window_trades < 1:
            raise ValueError("window_trades must be >= 1")
        if self.max_losses > self.window_trades:
            raise ValueError("max_losses cannot exceed window_trades")
        if len(self.history) > self.window_trades:
            raise ValueError("history cannot exceed window_trades")


class RiskState(msgspec.Struct, frozen=True):
    """Schema-versioned serializable risk state."""

    schema_version: int = RISK_STATE_SCHEMA_VERSION
    context: RiskContext = RiskContext()
    kill_switch: KillSwitchState | None = None
    timed_breaker: TimedCircuitBreakerState | None = None
    consecutive_loss_gate: ConsecutiveLossGateState | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != RISK_STATE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported risk state schema_version={self.schema_version}; "
                f"expected {RISK_STATE_SCHEMA_VERSION}"
            )

    def to_json(self) -> str:
        """Serialize the full state snapshot to JSON."""
        return msgspec.json.encode(self).decode("utf-8")

    @classmethod
    def from_json(cls, payload: str | bytes) -> RiskState:
        """Restore a state snapshot from JSON, rejecting malformed payloads."""
        try:
            raw = msgspec.json.decode(payload)
        except Exception as exc:  # pragma: no cover - surfaced as ValueError to callers
            raise ValueError(f"Invalid RiskState payload: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("RiskState payload must be a JSON object")
        allowed_keys = {
            "schema_version",
            "context",
            "kill_switch",
            "timed_breaker",
            "consecutive_loss_gate",
        }
        required_keys = allowed_keys
        unexpected = set(raw) - allowed_keys
        if unexpected:
            raise ValueError(f"Unexpected RiskState keys: {sorted(unexpected)}")
        missing = required_keys - set(raw)
        if missing:
            raise ValueError(f"RiskState payload missing keys: {sorted(missing)}")
        if (
            type(raw["schema_version"]) is not int
            or raw["schema_version"] != RISK_STATE_SCHEMA_VERSION
        ):
            raise ValueError(
                f"Unsupported risk state schema_version={raw['schema_version']}; "
                f"expected {RISK_STATE_SCHEMA_VERSION}"
            )
        try:
            return msgspec.json.decode(msgspec.json.encode(raw), type=cls)
        except Exception as exc:  # pragma: no cover - surfaced as ValueError to callers
            raise ValueError(f"Invalid RiskState payload: {exc}") from exc


class TradeOutcome(BaseModel):
    """Representation of a past trade outcome for consecutive loss gating."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    timestamp: datetime
    pnl: float


__all__ = [
    "RISK_STATE_SCHEMA_VERSION",
    "ConsecutiveLossGateState",
    "KillSwitchState",
    "Position",
    "RiskContext",
    "RiskDecision",
    "RiskState",
    "TimedCircuitBreakerState",
    "TradeOutcome",
]
