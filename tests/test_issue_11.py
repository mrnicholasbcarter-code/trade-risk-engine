import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from trade_risk_engine import (
    ConsecutiveLossGate,
    KillSwitch,
    PaperExecutionAdapter,
    RiskAuthority,
    RiskContext,
    RiskDecision,
    RiskState,
    TimedCircuitBreaker,
    TradeOutcome,
)
from trade_risk_engine.benchmark import BenchmarkReport, run_latency_benchmark
from trade_risk_engine.gates import (
    evaluate_consecutive_losses,
    evaluate_drawdown,
    evaluate_expected_value,
)
from trade_risk_engine.webhook import ProposedTradeInfo, RiskEvent, WebhookEmitter


class TestRiskStateSerialization:
    def test_risk_state_round_trip_and_restore_authority(self):
        ctx = RiskContext()
        trip_at = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)

        kill_switch = KillSwitch()
        kill_switch.trip(at=trip_at)

        timed_breaker = TimedCircuitBreaker(consecutive_loss_threshold=2, cooldown_hours=1.5)
        timed_breaker.record(-10.0, at=trip_at)
        timed_breaker.record(-20.0, at=trip_at)

        consecutive_loss_gate = ConsecutiveLossGate(max_losses=2, window_trades=3)
        consecutive_loss_gate.record(-1.0)
        consecutive_loss_gate.record(-2.0)
        consecutive_loss_gate.record(1.0)

        authority = RiskAuthority(
            kill_switch=kill_switch,
            timed_breaker=timed_breaker,
            consecutive_loss_gate=consecutive_loss_gate,
        )
        state = authority.snapshot_state(ctx)
        payload = state.to_json()
        restored_state = RiskState.from_json(payload)
        restored_authority = RiskAuthority.from_state(restored_state)

        assert restored_state == state
        assert restored_state.context == ctx
        assert restored_authority.kill_switch is not None
        assert restored_authority.kill_switch.tripped is True
        assert restored_authority.timed_breaker is not None
        assert restored_authority.timed_breaker.tripped is True
        assert restored_authority.timed_breaker.loss_streak == 2
        assert restored_authority.consecutive_loss_gate is not None
        assert restored_authority.consecutive_loss_gate.history == [True, True, False]

    def test_risk_state_rejects_malformed_payload(self):
        ctx_payload = json.loads(RiskContext().to_json())
        base_payload = {
            "schema_version": 1,
            "context": ctx_payload,
            "kill_switch": None,
            "timed_breaker": None,
            "consecutive_loss_gate": None,
        }

        with pytest.raises(ValueError, match="missing keys"):
            RiskState.from_json(
                json.dumps({k: v for k, v in base_payload.items() if k != "schema_version"})
            )

        with pytest.raises(ValueError, match="Unexpected RiskState keys"):
            RiskState.from_json(json.dumps({**base_payload, "extra": 1}))

        with pytest.raises(ValueError, match="Unsupported risk state schema_version"):
            RiskState.from_json(json.dumps({**base_payload, "schema_version": 2}))

    def test_state_rejects_non_finite_floats(self):
        with pytest.raises(ValueError):
            RiskContext(max_daily_drawdown_pct=float("nan"))

        with pytest.raises(ValueError):
            RiskDecision(approved=True, reason_code="OK", suggested_size=float("inf"))

        with pytest.raises(ValidationError):
            TradeOutcome(timestamp=datetime.now(timezone.utc), pnl=float("nan"))


class TestTimezoneAndConsecutiveLossHandling:
    def test_consecutive_losses_reject_mixed_timezones(self):
        ctx = RiskContext(consecutive_loss_limit=2, consecutive_loss_window_minutes=10.0)
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=1.0)
        aware_time = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
        outcomes = [
            TradeOutcome(timestamp=aware_time - timedelta(minutes=1), pnl=-1.0),
            TradeOutcome(
                timestamp=(aware_time - timedelta(minutes=2)).replace(tzinfo=None), pnl=-1.0
            ),
        ]

        result = evaluate_consecutive_losses(ctx, outcomes, aware_time, decision)

        assert result is False
        assert decision.reason_code == "ERR_INVALID_TIMEZONE_MIXED"

    def test_consecutive_losses_deterministic_without_current_time(self):
        ctx = RiskContext(consecutive_loss_limit=2, consecutive_loss_window_minutes=10.0)
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=1.0)
        now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
        outcomes = [
            TradeOutcome(timestamp=now - timedelta(minutes=2), pnl=-1.0),
            TradeOutcome(timestamp=now - timedelta(minutes=1), pnl=-2.0),
        ]

        result = evaluate_consecutive_losses(ctx, outcomes, None, decision)

        assert result is False
        assert decision.approved is False
        assert "ERR_CONSECUTIVE_LOSS_LIMIT" in decision.reason_code


class TestFloatBoundaryCoverage:
    def test_subnormal_values_remain_finite(self):
        subnormal = 5e-324

        ev_decision = RiskDecision(approved=True, reason_code="OK", suggested_size=0.0)
        assert evaluate_expected_value(RiskContext(), subnormal, ev_decision) is True
        assert ev_decision.approved is True

        dd_decision = RiskDecision(approved=True, reason_code="OK", suggested_size=0.0)
        assert evaluate_drawdown(RiskContext(), -subnormal, 1.0, dd_decision) is True
        assert dd_decision.approved is True


class TestAlertBoundaryAndPaperGuardrails:
    @pytest.mark.anyio
    async def test_webhook_retry_bounds_are_enforced(self):
        attempts = 0

        def handle_request(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(500, text="retry me")

        transport = httpx.MockTransport(handle_request)
        async with httpx.AsyncClient(transport=transport) as client:
            emitter = WebhookEmitter(
                "http://testserver/webhook",
                client=client,
                max_attempts=2,
                timeout_seconds=0.1,
            )
            event = RiskEvent(
                decision_approved=False,
                reason_code="ERR_DAILY_DRAWDOWN",
                suggested_size=0.0,
                proposed_trade=ProposedTradeInfo(
                    target_family="AAPL",
                    proposed_cost=100.0,
                    expected_value=1.5,
                ),
            )

            success = await emitter.emit(event)

        assert success is False
        assert attempts == 2

    def test_webhook_event_rejects_non_finite_payloads(self):
        with pytest.raises(ValidationError):
            RiskEvent(
                decision_approved=False,
                reason_code="ERR_INVALID_FLOAT",
                suggested_size=float("nan"),
                proposed_trade=ProposedTradeInfo(
                    target_family="AAPL",
                    proposed_cost=100.0,
                    expected_value=1.5,
                ),
            )

    def test_paper_execution_adapter_blocks_live_orders(self):
        adapter = PaperExecutionAdapter()
        event = RiskEvent(
            decision_approved=False,
            reason_code="ERR_DAILY_DRAWDOWN",
            suggested_size=0.0,
            proposed_trade=ProposedTradeInfo(
                target_family="AAPL",
                proposed_cost=100.0,
                expected_value=1.5,
            ),
        )

        adapter.handle_alert(event)
        with pytest.raises(RuntimeError, match="disabled"):
            adapter.submit_order(symbol="AAPL", quantity=1)


class TestBenchmarkReport:
    def test_percentile_report_and_caveats(self):
        report = BenchmarkReport.from_samples(
            [10, 20, 30, 40, 50], iterations=5, warmup_iterations=1
        )

        assert report.p50_ns == 30
        assert report.p95_ns == 50
        assert report.p99_ns == 50
        assert report.mean_ns == pytest.approx(30.0)
        assert "Rust/C benchmarks" in report.to_markdown()
        assert "native systems" in report.to_markdown()

    def test_latency_benchmark_runs_and_reports(self):
        report = run_latency_benchmark(iterations=3, warmup_iterations=1)

        assert len(report.samples_ns) == 3
        assert report.min_ns <= report.p50_ns <= report.p95_ns <= report.p99_ns <= report.max_ns
        assert report.caveats
