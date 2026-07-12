import math
from datetime import datetime, timedelta
from typing import final

from .state import Position, RiskContext, RiskDecision, TradeOutcome


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


def evaluate_consecutive_losses(
    ctx: RiskContext,
    trade_outcomes: list[TradeOutcome] | None,
    current_time: datetime | None,
    decision: RiskDecision
) -> bool:
    """
    Blocks trades after N consecutive losses within Y minutes.
    """
    if ctx.consecutive_loss_limit <= 0:
        return True

    if not trade_outcomes:
        return True

    if current_time is None:
        if trade_outcomes[0].timestamp.tzinfo is not None:
            from datetime import timezone
            current_time = datetime.now(timezone.utc)
        else:
            current_time = datetime.utcnow()

    # Sort outcomes chronologically (oldest to newest)
    sorted_outcomes = sorted(trade_outcomes, key=lambda x: x.timestamp)

    consecutive_losses_in_window = 0
    limit_seconds = ctx.consecutive_loss_window_minutes * 60.0

    for outcome in reversed(sorted_outcomes):
        if outcome.pnl < 0:
            time_diff = current_time - outcome.timestamp
            diff_seconds = time_diff.total_seconds()
            if 0 <= diff_seconds <= limit_seconds:
                consecutive_losses_in_window += 1
                if consecutive_losses_in_window >= ctx.consecutive_loss_limit:
                    decision.approved = False
                    decision.reason_code = f"ERR_CONSECUTIVE_LOSS_LIMIT: {consecutive_losses_in_window} consecutive losses within {ctx.consecutive_loss_window_minutes} minutes"
                    return False
            else:
                # Outside the time window. Since outcomes are sorted chronologically,
                # any outcome before this will also be outside the window.
                break
        else:
            # A win breaks the consecutive losses streak.
            break

    return True


@final
class KillSwitch:
    """Manual kill switch: once tripped, every subsequent trade is blocked.

    This is the original "dead-man's switch" gate that the engine already had
    in latent form via the latency budget. Promoting it to an explicit class
    gives the trading desk a single button to flip (e.g. on a market-wide
    circuit break) and lets the ``RiskAuthority`` fire an ``on_trip`` callback
    the first time the switch goes from clear to tripped.

    The switch is intentionally not a gate *function* — it carries mutable state
    (the trip flag and the timestamp at which it was pulled) and so must live
    on an object rather than in a pure function. Equality-and-repr conventions
    make it safe to share a single instance across many ``evaluate_trade``
    calls within one trading session.
    """

    __slots__ = ("tripped", "tripped_at", "reason")

    def __init__(self, reason: str = "ERR_KILL_SWITCH_MANUAL") -> None:
        self.tripped: bool = False
        self.tripped_at: datetime | None = None
        self.reason: str = reason

    def trip(self, at: datetime | None = None) -> None:
        """Hard-trip the switch. Subsequent ``check`` calls will reject."""
        if not self.tripped:
            self.tripped = True
            self.tripped_at = at

    def reset(self) -> None:
        """Clear the switch so trades can flow again."""
        self.tripped = False
        self.tripped_at = None

    def check(self, decision: RiskDecision, at: datetime | None = None) -> bool:
        """Return True if the trade may proceed past this switch."""
        if self.tripped:
            decision.approved = False
            decision.reason_code = self.reason
            return False
        return True


@final
class TimedCircuitBreaker:
    """Time-based circuit breaker gate.

    After ``consecutive_loss_threshold`` losses in a row (default 3), the
    breaker halts all trading for ``cooldown_hours`` (default 24h). The breaker
    is fed each resolved trade's PnL via :meth:`record`; the engine calls
    :meth:`check` before evaluating *any* other gate so a tripped breaker
    overrides drawdown/EV/concentration decisions.

    The state machine has three transitions of interest:

    * ``loss`` while below threshold -> streak += 1
    * ``loss`` reaching threshold -> trip, start cooldown
    * ``win`` at any point -> streak = 0 (a single win resets the run)

    Once tripped, the breaker stays tripped until ``cooldown_hours`` elapses,
    at which point the streak is cleared and trading resumes automatically.
    This models a desk-level "take a breath" rule: don't keep firing after a
    cluster of losses even if individual trades still look attractive.
    """

    __slots__ = (
        "consecutive_loss_threshold",
        "cooldown_hours",
        "loss_streak",
        "tripped_at",
        "tripped",
    )

    def __init__(
        self,
        consecutive_loss_threshold: int = 3,
        cooldown_hours: float = 24.0,
    ) -> None:
        if consecutive_loss_threshold < 1:
            raise ValueError("consecutive_loss_threshold must be >= 1")
        if cooldown_hours <= 0:
            raise ValueError("cooldown_hours must be > 0")
        self.consecutive_loss_threshold = int(consecutive_loss_threshold)
        self.cooldown_hours = float(cooldown_hours)
        self.loss_streak: int = 0
        self.tripped_at: datetime | None = None
        self.tripped: bool = False

    def record(self, pnl: float, at: datetime | None = None) -> None:
        """Feed a resolved trade's PnL into the breaker.

        A loss (``pnl < 0``) advances the streak and may trip; a win or a
        break-even resets the streak. NaN/inf PnL inputs are ignored — they
        cannot meaningfully be classified as a win or a loss, and silently
        swallowing them is safer than letting a broken upstream corrupt the
        breaker state.
        """
        if not _is_finite(pnl):
            return
        if self.tripped:
            # While tripped we do not accumulate losses — the cooldown is an
            # absolute timeout, not a "until N wins" rule.
            return
        if pnl < 0:
            self.loss_streak += 1
            if self.loss_streak >= self.consecutive_loss_threshold:
                self.tripped = True
                self.tripped_at = at
        else:
            self.loss_streak = 0

    def check(self, decision: RiskDecision, now: datetime | None = None) -> bool:
        """Return True if the trade may proceed past this breaker.

        If the cooldown has expired since the last trip, the breaker auto-clears
        and clears the streak so the desk can resume with a clean slate.
        """
        if self.tripped and self.tripped_at is not None and now is not None:
            elapsed = now - self.tripped_at
            if elapsed >= timedelta(hours=self.cooldown_hours):
                # Cooldown elapsed: clear and allow trading.
                self.tripped = False
                self.tripped_at = None
                self.loss_streak = 0
                return True
        if self.tripped:
            decision.approved = False
            decision.reason_code = (
                f"ERR_TIMED_CIRCUIT_BREAKER: tripped after {self.loss_streak} "
                f"consecutive losses, cooldown {self.cooldown_hours}h"
            )
            return False
        return True

    def reset(self) -> None:
        """Manually clear the breaker (e.g. after desk-level review)."""
        self.loss_streak = 0
        self.tripped = False
        self.tripped_at = None


@final
class ConsecutiveLossGate:
    """Rolling-window consecutive-loss gate.

    Triggers if more than ``max_losses`` losses occur in any rolling window of
    ``window_trades`` resolved trades. Unlike :class:`TimedCircuitBreaker` this
    gate is *timeless* — it counts trades, not wall-clock minutes — so it
    catches a "death by a thousand cuts" pattern that a wall-clock window
    would miss on a slow day.

    A single win between losses does NOT reset the window (contrast with the
    time-windowed gate above): the question this gate answers is "did more than
    N of the last M trades lose money?", regardless of how the wins and losses
    are interleaved. This matches how a risk officer looks at a blotter.
    """

    __slots__ = ("max_losses", "window_trades", "history")

    def __init__(self, max_losses: int, window_trades: int) -> None:
        if max_losses < 1:
            raise ValueError("max_losses must be >= 1")
        if window_trades < 1:
            raise ValueError("window_trades must be >= 1")
        if max_losses > window_trades:
            raise ValueError("max_losses cannot exceed window_trades")
        self.max_losses = int(max_losses)
        self.window_trades = int(window_trades)
        self.history: list[bool] = []  # True = loss, False = win/breakeven

    def record(self, pnl: float) -> None:
        """Feed a resolved trade's PnL. NaN/inf inputs are ignored."""
        if not _is_finite(pnl):
            return
        self.history.append(pnl < 0)
        # Trim to the rolling window.
        if len(self.history) > self.window_trades:
            self.history = self.history[-self.window_trades:]

    def check(self, decision: RiskDecision) -> bool:
        """Return True if the trade may proceed past this gate."""
        if len(self.history) < self.window_trades:
            # Not enough history to evaluate — fail open. This avoids blocking
            # the first M-1 trades of a session.
            return True
        losses_in_window = sum(self.history)
        if losses_in_window > self.max_losses:
            decision.approved = False
            decision.reason_code = (
                f"ERR_CONSECUTIVE_LOSS_GATE: {losses_in_window} losses in last "
                f"{self.window_trades} trades (limit {self.max_losses})"
            )
            return False
        return True

    def reset(self) -> None:
        """Clear the rolling history."""
        self.history = []


def _is_finite(x: float) -> bool:
    """Local finite-check so gates don't import state-level helpers transitively."""
    return isinstance(x, float) and not (math.isnan(x) or math.isinf(x))


