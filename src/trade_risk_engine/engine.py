import time

from .gates import evaluate_concentration, evaluate_drawdown, evaluate_expected_value
from .state import Position, RiskContext, RiskDecision


class RiskAuthority:
    """Stateless coordinator for deterministic trade risk evaluation.

    ``RiskAuthority`` is intentionally side-effect free: every decision is
    derived from the supplied ``RiskContext``, current PnL/equity inputs, target
    family, proposed cost, and open positions. The class owns no mutable state
    and exposes a static entry point so callers can evaluate trades without
    constructing service objects or performing I/O.
    """

    @staticmethod
    def evaluate_trade(
        ctx: RiskContext,
        daily_realized_pnl: float,
        equity: float,
        target_family: str,
        proposed_cost: float,
        open_positions: list[Position],
        expected_value: float = 0.0
    ) -> RiskDecision:
        """Evaluate whether a proposed trade satisfies every configured gate.

        Gates short-circuit in capital-protection order. Drawdown is evaluated
        before concentration so catastrophic loss limits always dominate sizing
        decisions. The returned ``RiskDecision`` contains the first rejection
        reason, or ``OK`` with the original proposed size when all gates pass.
        """

        start_ns = time.perf_counter_ns()

        # Pre-allocate response
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=proposed_cost)

        # 0. Expected Value Gate
        if not evaluate_expected_value(ctx, expected_value, decision):
            return decision

        # 1. Drawdown Gate
        if not evaluate_drawdown(ctx, daily_realized_pnl, equity, decision):
            return decision

        # 2. Concentration / Correlation Gate
        if not evaluate_concentration(ctx, target_family, proposed_cost, open_positions, decision):
            return decision

        # 3. Latency Circuit Breaker (Dead-man's switch)
        elapsed_us = (time.perf_counter_ns() - start_ns) // 1000
        if elapsed_us > ctx.latency_budget_us:
            decision.approved = False
            decision.reason_code = f"ERR_LATENCY_BUDGET: evaluation took {elapsed_us}us (limit {ctx.latency_budget_us}us)"

        return decision
