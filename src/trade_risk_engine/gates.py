import math

from .state import Position, RiskContext, RiskDecision


def evaluate_drawdown(
    ctx: RiskContext,
    daily_realized_pnl: float,
    equity: float,
    decision: RiskDecision
) -> bool:
    """
    Pessimistic drawdown gate.
    If daily losses exceed the max subset, immediately short-circuit.
    """
    if math.isnan(equity) or math.isnan(daily_realized_pnl) or math.isinf(equity) or math.isinf(daily_realized_pnl):
        decision.approved = False
        decision.reason_code = "ERR_INVALID_FLOAT_DRAWDOWN"
        return False

    if equity <= 0:
        decision.approved = False
        decision.reason_code = "ERR_ZERO_OR_NEGATIVE_EQUITY"
        return False

    drawdown_pct = daily_realized_pnl / equity
    if drawdown_pct < -ctx.max_daily_drawdown_pct:
        decision.approved = False
        decision.reason_code = f"ERR_DAILY_DRAWDOWN: {drawdown_pct:.2%} exceeds limit {-ctx.max_daily_drawdown_pct:.2%}"
        return False
    return True

def evaluate_concentration(
    ctx: RiskContext,
    target_family: str,
    proposed_cost: float,
    open_positions: list[Position],
    decision: RiskDecision
) -> bool:
    """
    Blocks trades that concentrate capital into a single event resolution or asset family.
    """
    if math.isnan(proposed_cost) or math.isinf(proposed_cost):
        decision.approved = False
        decision.reason_code = "ERR_INVALID_FLOAT_CONCENTRATION"
        return False

    current_exposure = 0.0
    for pos in open_positions:
        if not pos.is_resolved and pos.family == target_family:
            if math.isnan(pos.cost_basis) or math.isinf(pos.cost_basis):
                decision.approved = False
                decision.reason_code = "ERR_INVALID_FLOAT_CONCENTRATION"
                return False
            current_exposure += pos.cost_basis

    if (current_exposure + proposed_cost) > ctx.max_correlated_exposure:
        decision.approved = False
        decision.reason_code = f"ERR_CONCENTRATION: {target_family} exposure would exceed {ctx.max_correlated_exposure}"
        return False

    return True

def evaluate_expected_value(
    ctx: RiskContext,
    expected_value: float,
    decision: RiskDecision
) -> bool:
    """
    Blocks trades that do not meet the minimum expected value threshold (e.g. EV <= 0).
    """
    if math.isnan(expected_value) or math.isinf(expected_value):
        decision.approved = False
        decision.reason_code = "ERR_INVALID_FLOAT_EXPECTED_VALUE"
        return False

    if expected_value < ctx.min_expected_value:
        decision.approved = False
        decision.reason_code = f"ERR_EXPECTED_VALUE: {expected_value} is below minimum {ctx.min_expected_value}"
        return False

    return True
