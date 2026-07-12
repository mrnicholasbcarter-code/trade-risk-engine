import math
import sys
from pathlib import Path
import time

from hypothesis import given, settings, strategies as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from trade_risk_engine.engine import RiskAuthority
from trade_risk_engine.gates import evaluate_concentration, evaluate_drawdown, evaluate_expected_value
from trade_risk_engine.state import Position, RiskContext, RiskDecision

EDGE_FLOATS = st.one_of(
    st.sampled_from(
        [
            float("nan"),
            float("inf"),
            float("-inf"),
            0.0,
            -0.0,
            1e-12,
            -1e-12,
            1.0,
            -1.0,
            1e12,
            -1e12,
        ]
    ),
    st.floats(allow_nan=True, allow_infinity=True, width=64),
)
FINITE_MONEY = st.floats(
    min_value=-1e12,
    max_value=1e12,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)
POSITIVE_EQUITY = st.floats(
    min_value=1e-12,
    max_value=1e12,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)
SAFE_PROPOSED = st.floats(
    min_value=0.0,
    max_value=2500.0,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)
VALID_EXPECTED_VALUE = st.floats(
    min_value=1e-12,
    max_value=1e12,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)

class TestRiskAuthorityProperties:

    @settings(max_examples=1000)
    @given(daily_pnl=EDGE_FLOATS, equity=EDGE_FLOATS, proposed=EDGE_FLOATS, expected_value=EDGE_FLOATS)
    def test_engine_never_crashes_on_edge_floats(self, daily_pnl, equity, proposed, expected_value):
        decision = RiskAuthority.evaluate_trade(
            ctx=RiskContext(),
            daily_realized_pnl=daily_pnl,
            equity=equity,
            target_family="test",
            proposed_cost=proposed,
            open_positions=[],
            expected_value=expected_value
        )
        assert isinstance(decision, RiskDecision)
        assert isinstance(decision.approved, bool)
        assert isinstance(decision.reason_code, str)

    @settings(max_examples=1000)
    @given(daily_pnl=FINITE_MONEY, equity=POSITIVE_EQUITY, proposed=SAFE_PROPOSED, expected_value=VALID_EXPECTED_VALUE)
    def test_engine_decisions(self, daily_pnl, equity, proposed, expected_value):
        ctx = RiskContext(latency_budget_us=1000000) # give a massive budget to avoid latency flakes
        decision = RiskAuthority.evaluate_trade(
            ctx=ctx,
            daily_realized_pnl=daily_pnl,
            equity=equity,
            target_family="test",
            proposed_cost=proposed,
            open_positions=[],
            expected_value=expected_value
        )

        expected_drawdown_breach = (daily_pnl / equity) < -ctx.max_daily_drawdown_pct
        
        if expected_drawdown_breach:
            assert decision.approved is False
            assert decision.reason_code.startswith("ERR_DAILY_DRAWDOWN")
        else:
            assert decision.approved is True
            assert decision.reason_code == "OK"


class TestDrawdownGateProperties:

    @settings(max_examples=1000)
    @given(daily_pnl=EDGE_FLOATS, equity=EDGE_FLOATS)
    def test_drawdown_gate_edge_floats(self, daily_pnl, equity):
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=0.0)
        result = evaluate_drawdown(RiskContext(), daily_pnl, equity, decision)
        assert isinstance(result, bool)

    @settings(max_examples=1000)
    @given(daily_pnl=FINITE_MONEY, equity=POSITIVE_EQUITY)
    def test_drawdown_gate_threshold(self, daily_pnl, equity):
        ctx = RiskContext()
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=0.0)
        result = evaluate_drawdown(ctx, daily_pnl, equity, decision)
        expected_safe = (daily_pnl / equity) >= -ctx.max_daily_drawdown_pct
        assert result is expected_safe
        assert decision.approved is expected_safe

    def test_drawdown_epsilon_boundary(self):
        ctx = RiskContext()
        equity = 100.0
        
        # 1e-6 drift bounds per the prompt request, replacing 1e-12 with 1e-6 as a drift edge case
        just_safe = RiskDecision(approved=True, reason_code="OK", suggested_size=0.0)
        assert evaluate_drawdown(ctx, -10.0 + 1e-6, equity, just_safe) is True
        
        just_breached = RiskDecision(approved=True, reason_code="OK", suggested_size=0.0)
        assert evaluate_drawdown(ctx, -10.0 - 1e-6, equity, just_breached) is False


class TestConcentrationGateProperties:

    @settings(max_examples=1000)
    @given(existing_cost=EDGE_FLOATS, proposed=EDGE_FLOATS)
    def test_concentration_gate_edge_floats(self, existing_cost, proposed):
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=proposed)
        positions = [Position(ticker="TEST-1", family="target", cost_basis=existing_cost, current_value=existing_cost, is_resolved=False)]
        result = evaluate_concentration(RiskContext(), "target", proposed, positions, decision)
        assert isinstance(result, bool)

    @settings(max_examples=1000)
    @given(existing_cost=SAFE_PROPOSED, proposed=SAFE_PROPOSED)
    def test_concentration_gate_threshold(self, existing_cost, proposed):
        ctx = RiskContext()
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=proposed)
        positions = [Position(ticker="TEST-1", family="target", cost_basis=existing_cost, current_value=existing_cost, is_resolved=False)]
        result = evaluate_concentration(ctx, "target", proposed, positions, decision)
        expected_safe = (existing_cost + proposed) <= ctx.max_correlated_exposure
        assert result is expected_safe
        assert decision.approved is expected_safe


class TestExpectedValueGateProperties:

    @settings(max_examples=1000)
    @given(expected_value=EDGE_FLOATS)
    def test_expected_value_gate_edge_floats(self, expected_value):
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=0.0)
        result = evaluate_expected_value(RiskContext(), expected_value, decision)
        assert isinstance(result, bool)

    @settings(max_examples=1000)
    @given(expected_value=FINITE_MONEY)
    def test_expected_value_gate_threshold(self, expected_value):
        ctx = RiskContext()
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=0.0)
        result = evaluate_expected_value(ctx, expected_value, decision)
        expected_safe = expected_value >= ctx.min_expected_value
        assert result is expected_safe
        assert decision.approved is expected_safe

    def test_expected_value_epsilon_boundary(self):
        ctx = RiskContext(min_expected_value=0.0)
        just_safe = RiskDecision(approved=True, reason_code="OK", suggested_size=0.0)
        # 1e-6 drift bounds per the prompt request
        assert evaluate_expected_value(ctx, 1e-6, just_safe) is True
        
        just_breached = RiskDecision(approved=True, reason_code="OK", suggested_size=0.0)
        assert evaluate_expected_value(ctx, -1e-6, just_breached) is False

def test_latency_budget():
    decision = RiskAuthority.evaluate_trade(
        ctx=RiskContext(latency_budget_us=-1),
        daily_realized_pnl=0.0,
        equity=1.0,
        target_family="test",
        proposed_cost=0.0,
        open_positions=[],
        expected_value=1.0
    )
    assert decision.approved is False
    assert decision.reason_code.startswith("ERR_LATENCY_BUDGET")
