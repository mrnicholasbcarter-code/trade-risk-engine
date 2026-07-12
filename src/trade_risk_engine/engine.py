"""Risk evaluation entry points.

The public hot path is ``RiskAuthority.evaluate_trade(...)``. It is intentionally
stateless and performs no I/O so it can run inside order-routing loops without
allocating service objects or touching the network. Optional stateful desk-level
gates live behind ``RiskAuthority(...).evaluate_with_state(...)``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span

from .gates import (
    ConsecutiveLossGate,
    KillSwitch,
    TimedCircuitBreaker,
    evaluate_concentration,
    evaluate_consecutive_losses,
    evaluate_drawdown,
    evaluate_expected_value,
)
from .state import Position, RiskContext, RiskDecision, TradeOutcome

TRACER_NAME = "trade-risk-engine"
logger = logging.getLogger(TRACER_NAME)


class RiskAuthority:
    """Coordinator for deterministic trade risk evaluation.

    ``evaluate_trade`` is the compatibility-preserving, stateless API used by
    existing callers. ``evaluate_with_state`` is opt-in for session objects that
    need manual kill switches, timed cooldown breakers, or rolling trade-window
    gates.
    """

    __slots__ = (
        "_last_trip_reason",
        "consecutive_loss_gate",
        "kill_switch",
        "on_trip",
        "timed_breaker",
    )

    def __init__(
        self,
        kill_switch: KillSwitch | None = None,
        timed_breaker: TimedCircuitBreaker | None = None,
        consecutive_loss_gate: ConsecutiveLossGate | None = None,
        on_trip: Callable[[RiskDecision], None] | None = None,
    ) -> None:
        """Create an optional stateful authority for desk/session gates.

        Args:
            kill_switch: Manual override gate checked before all other gates.
            timed_breaker: Cooldown breaker fed by ``record_resolved_trade``.
            consecutive_loss_gate: Rolling trade-window loss counter.
            on_trip: Callback fired once per unique stateful rejection reason.
        """
        self.kill_switch = kill_switch
        self.timed_breaker = timed_breaker
        self.consecutive_loss_gate = consecutive_loss_gate
        self.on_trip = on_trip
        self._last_trip_reason: str | None = None

    @staticmethod
    def evaluate_trade(
        ctx: RiskContext,
        daily_realized_pnl: float,
        equity: float,
        target_family: str,
        proposed_cost: float,
        open_positions: list[Position],
        expected_value: float = 0.0,
        trade_outcomes: list[TradeOutcome] | None = None,
        current_time: datetime | None = None,
    ) -> RiskDecision:
        """Evaluate a proposed trade using only supplied inputs.

        The gate order is EV, drawdown, consecutive loss window, concentration,
        and latency budget. This order rejects mathematically bad trades before
        spending time aggregating exposure, and keeps the method pure: no I/O,
        no mutation outside the returned ``RiskDecision``.
        """
        return _evaluate_stateless(
            ctx=ctx,
            daily_realized_pnl=daily_realized_pnl,
            equity=equity,
            target_family=target_family,
            proposed_cost=proposed_cost,
            open_positions=open_positions,
            expected_value=expected_value,
            trade_outcomes=trade_outcomes,
            current_time=current_time,
        )

    def evaluate_with_state(
        self,
        ctx: RiskContext,
        daily_realized_pnl: float,
        equity: float,
        target_family: str,
        proposed_cost: float,
        open_positions: list[Position],
        expected_value: float = 0.0,
        trade_outcomes: list[TradeOutcome] | None = None,
        current_time: datetime | None = None,
    ) -> RiskDecision:
        """Evaluate a trade after checking opt-in stateful gates.

        Stateful gates are checked first because a desk-level halt must override
        a locally attractive EV/drawdown/concentration result. If no stateful
        gates are configured this delegates to the stateless hot path.
        """
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=proposed_cost)

        if self.kill_switch is not None and not self.kill_switch.check(decision, at=current_time):
            self._maybe_fire_trip(decision)
            return decision

        if self.timed_breaker is not None and not self.timed_breaker.check(
            decision,
            now=current_time,
        ):
            self._maybe_fire_trip(decision)
            return decision

        if self.consecutive_loss_gate is not None and not self.consecutive_loss_gate.check(
            decision
        ):
            self._maybe_fire_trip(decision)
            return decision

        return _evaluate_stateless(
            ctx=ctx,
            daily_realized_pnl=daily_realized_pnl,
            equity=equity,
            target_family=target_family,
            proposed_cost=proposed_cost,
            open_positions=open_positions,
            expected_value=expected_value,
            trade_outcomes=trade_outcomes,
            current_time=current_time,
        )

    def record_resolved_trade(self, pnl: float, at: datetime | None = None) -> None:
        """Feed settled-trade PnL into configured stateful gates.

        Callers should invoke this after a fill, expiry, or manual close. The
        stateless ``evaluate_trade`` path does not consume this state; it remains
        fully replayable from explicit inputs.
        """
        if self.timed_breaker is not None:
            self.timed_breaker.record(pnl, at=at)
        if self.consecutive_loss_gate is not None:
            self.consecutive_loss_gate.record(pnl)

    def _maybe_fire_trip(self, decision: RiskDecision) -> None:
        """Invoke ``on_trip`` once per distinct stateful rejection reason."""
        if self.on_trip is None or decision.reason_code == self._last_trip_reason:
            return
        self._last_trip_reason = decision.reason_code
        try:
            self.on_trip(decision)
        except Exception:  # pragma: no cover - callbacks must not crash risk evaluation
            logger.exception("on_trip callback raised")


def _evaluate_stateless(
    ctx: RiskContext,
    daily_realized_pnl: float,
    equity: float,
    target_family: str,
    proposed_cost: float,
    open_positions: list[Position],
    expected_value: float,
    trade_outcomes: list[TradeOutcome] | None,
    current_time: datetime | None,
) -> RiskDecision:
    """Run the pure gate chain, with tracing only when an SDK tracer is installed."""
    start_ns = time.perf_counter_ns()
    tracer = trace.get_tracer(TRACER_NAME)

    with _maybe_span(tracer, "evaluate_trade") as span:
        _set_attrs(
            span,
            {
                "trade_risk_engine.target_family": target_family,
                "trade_risk_engine.proposed_cost": proposed_cost,
                "trade_risk_engine.expected_value": expected_value,
                "trade_risk_engine.daily_realized_pnl": daily_realized_pnl,
                "trade_risk_engine.equity": equity,
            },
        )
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=proposed_cost)

        if not _run_gate(
            tracer,
            "evaluate_expected_value",
            evaluate_expected_value,
            ctx,
            expected_value,
            decision,
        ):
            _mark_rejected(span, decision)
            return decision

        if not _run_gate(
            tracer,
            "evaluate_drawdown",
            evaluate_drawdown,
            ctx,
            daily_realized_pnl,
            equity,
            decision,
        ):
            _mark_rejected(span, decision)
            return decision

        if not _run_gate(
            tracer,
            "evaluate_consecutive_losses",
            evaluate_consecutive_losses,
            ctx,
            trade_outcomes,
            current_time,
            decision,
        ):
            _mark_rejected(span, decision)
            return decision

        if not _run_gate(
            tracer,
            "evaluate_concentration",
            evaluate_concentration,
            ctx,
            target_family,
            proposed_cost,
            open_positions,
            decision,
        ):
            _mark_rejected(span, decision)
            return decision

        elapsed_us = (time.perf_counter_ns() - start_ns) // 1000
        if elapsed_us > ctx.latency_budget_us:
            decision.approved = False
            decision.reason_code = (
                f"ERR_LATENCY_BUDGET: evaluation took {elapsed_us}us "
                f"(limit {ctx.latency_budget_us}us)"
            )
            _mark_rejected(span, decision)
            return decision

        _set_attrs(span, {"approved": True, "suggested_size": decision.suggested_size})
        return decision


def _run_gate(tracer: trace.Tracer, name: str, gate: Callable[..., bool], *args: Any) -> bool:
    """Execute a gate and annotate a child span when tracing is active."""
    with _maybe_span(tracer, name) as span:
        result = gate(*args)
        _set_attrs(span, {"approved": result})
        if not result:
            decision = args[-1]
            if isinstance(decision, RiskDecision):
                _set_attrs(span, {"reason_code": decision.reason_code})
        return result


def _tracing_enabled() -> bool:
    """Return True when OpenTelemetry SDK tracing has been configured."""
    provider = trace.get_tracer_provider()
    return provider.__class__.__module__.startswith("opentelemetry.sdk")


def _maybe_span(tracer: trace.Tracer, name: str) -> Any:
    """Start a span only when SDK tracing is active; otherwise use no-op context."""
    if not _tracing_enabled():
        return nullcontext(None)
    return tracer.start_as_current_span(name)


def _set_attrs(span: Span | None, attrs: dict[str, bool | float | str]) -> None:
    """Set span attributes when a real span exists."""
    if span is None:
        return
    for key, value in attrs.items():
        span.set_attribute(key, value)


def _mark_rejected(span: Span | None, decision: RiskDecision) -> None:
    """Annotate a root span with the rejection result."""
    _set_attrs(span, {"approved": False, "reason_code": decision.reason_code})
