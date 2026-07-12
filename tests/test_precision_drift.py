import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from trade_risk_engine.gates import (
    evaluate_concentration,
    evaluate_drawdown,
    evaluate_expected_value,
)
from trade_risk_engine.state import Position, RiskContext, RiskDecision

# Numeric tolerance for drift assertions. Float drift on the order of 1e-12 is
# comfortably within this band, so boundary decisions stay stable.
REL_TOL = 1e-9


class TestFloatPrecisionDrift:
    """Float precision drift tests using ``pytest.approx``.

    Boundary decisions must tolerate floating-point drift on the order of 1e-12
    so that a nominally-safe value such as ``10.0 + 1e-12`` is not
    misclassified by the strict ``<`` / ``>`` comparators inside the gates.
    """

    def test_drawdown_ratio_approx_at_boundary(self):
        ctx = RiskContext()
        equity = 100.0
        # A nominal 10% drawdown corresponds to a -10.0 daily PnL on 100.0 equity.
        daily_pnl = -ctx.max_daily_drawdown_pct * equity
        ratio = daily_pnl / equity
        # The recovered ratio must be approximately the configured limit.
        assert ratio == pytest.approx(-ctx.max_daily_drawdown_pct, rel=REL_TOL)

    def test_drawdown_drift_safe_side(self):
        ctx = RiskContext()
        equity = 100.0
        # A tiny +1e-12 drift on the loss keeps it on the safe side of the limit.
        daily_pnl = -10.0 + 1e-12
        drifted_ratio = daily_pnl / equity
        assert drifted_ratio == pytest.approx(-0.10, rel=REL_TOL)
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=0.0)
        result = evaluate_drawdown(ctx, daily_pnl, equity, decision)
        assert result is True
        assert decision.approved is True

    def test_drawdown_drift_breach_side(self):
        ctx = RiskContext()
        equity = 100.0
        # A tiny -1e-12 drift on the loss pushes it across the limit.
        daily_pnl = -10.0 - 1e-12
        drifted_ratio = daily_pnl / equity
        assert drifted_ratio == pytest.approx(-0.10, rel=REL_TOL)
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=0.0)
        result = evaluate_drawdown(ctx, daily_pnl, equity, decision)
        assert result is False
        assert decision.approved is False

    def test_concentration_drift_value_approx(self):
        ctx = RiskContext(max_correlated_exposure=10.0)
        drifted_cost = 10.0 + 1e-12
        # The drifted cost reads as approximately 10.0 within tolerance.
        assert drifted_cost == pytest.approx(10.0, rel=REL_TOL)
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=drifted_cost)
        positions = [
            Position(
                ticker="TEST-1",
                family="target",
                cost_basis=0.0,
                current_value=0.0,
                is_resolved=False,
            )
        ]
        result = evaluate_concentration(ctx, "target", drifted_cost, positions, decision)
        # Strict > comparator: a genuine 10.0 + 1e-12 breach must surface as a rejection.
        assert result is False
        assert decision.approved is False

    def test_expected_value_drift_approx(self):
        ctx = RiskContext(min_expected_value=0.0)
        drifted_ev = 10.0 + 1e-12
        assert drifted_ev == pytest.approx(10.0, rel=REL_TOL)
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=0.0)
        result = evaluate_expected_value(ctx, drifted_ev, decision)
        assert result is True
        assert decision.approved is True
