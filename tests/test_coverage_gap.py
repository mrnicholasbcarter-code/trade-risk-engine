import pytest
from trade_risk_engine.state import (
    RiskContext, Position, RiskDecision, TimedCircuitBreakerState,
    ConsecutiveLossGateState, RiskState, _ensure_finite
)

def test_missing_exceptions_state():
    with pytest.raises(ValueError):
        _ensure_finite(float('inf'), "val")
    with pytest.raises(ValueError):
        _ensure_finite(True, "val")
        
    with pytest.raises(ValueError):
        RiskContext(latency_budget_us=1.5)
        
    with pytest.raises(ValueError):
        Position(ticker=1, family="FAM", cost_basis=1.0, current_value=1.0, is_resolved=False)
    with pytest.raises(ValueError):
        Position(ticker="T", family=1, cost_basis=1.0, current_value=1.0, is_resolved=False)
    with pytest.raises(ValueError):
        Position(ticker="T", family="FAM", cost_basis=1.0, current_value=1.0, is_resolved=1)

    with pytest.raises(ValueError):
        RiskDecision(approved=1, reason_code="A", suggested_size=1.0)
    with pytest.raises(ValueError):
        RiskDecision(approved=True, reason_code=1, suggested_size=1.0)

    with pytest.raises(ValueError):
        TimedCircuitBreakerState(consecutive_loss_threshold=1.5)
    with pytest.raises(ValueError):
        TimedCircuitBreakerState(loss_streak=1.5)
    with pytest.raises(ValueError):
        TimedCircuitBreakerState(consecutive_loss_threshold=0)
    with pytest.raises(ValueError):
        TimedCircuitBreakerState(cooldown_hours=-1.0)
    with pytest.raises(ValueError):
        TimedCircuitBreakerState(loss_streak=-1)

    with pytest.raises(ValueError):
        ConsecutiveLossGateState(max_losses=1.5, window_trades=1)
    with pytest.raises(ValueError):
        ConsecutiveLossGateState(max_losses=1, window_trades=1.5)
    with pytest.raises(ValueError):
        ConsecutiveLossGateState(max_losses=0, window_trades=1)
    with pytest.raises(ValueError):
        ConsecutiveLossGateState(max_losses=1, window_trades=0)
    with pytest.raises(ValueError):
        ConsecutiveLossGateState(max_losses=2, window_trades=1)
    with pytest.raises(ValueError):
        ConsecutiveLossGateState(max_losses=1, window_trades=1, history=(True, True))

    with pytest.raises(ValueError):
        RiskState(schema_version=1.5)
    
    with pytest.raises(ValueError):
        RiskState.from_json("[]") # Not a dict
    with pytest.raises(ValueError):
        RiskState.from_json('{"bad": 1}') # Unexpected
    with pytest.raises(ValueError):
        RiskState.from_json('{"schema_version": 1}') # Missing
    with pytest.raises(ValueError):
        RiskState.from_json('{"schema_version": 2, "context": {}, "kill_switch": null, "timed_breaker": null, "consecutive_loss_gate": null}')

