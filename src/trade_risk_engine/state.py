import msgspec


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
