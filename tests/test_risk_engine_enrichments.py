import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

# Add src to path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from trade_risk_engine.engine import RiskAuthority
from trade_risk_engine.gates import evaluate_consecutive_losses
from trade_risk_engine.state import RiskContext, RiskDecision, TradeOutcome
from trade_risk_engine.webhook import ProposedTradeInfo, RiskEvent, WebhookEmitter


class TestConsecutiveLossGating:
    """Tests for consecutive-loss gating logic."""

    def test_consecutive_losses_under_limit(self):
        ctx = RiskContext(consecutive_loss_limit=3, consecutive_loss_window_minutes=15.0)
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=100.0)
        now = datetime(2026, 7, 12, 12, 0, 0)

        # Only 2 losses, limit is 3
        outcomes = [
            TradeOutcome(timestamp=now - timedelta(minutes=10), pnl=-50.0),
            TradeOutcome(timestamp=now - timedelta(minutes=5), pnl=-20.0),
        ]

        res = evaluate_consecutive_losses(ctx, outcomes, now, decision)
        assert res is True
        assert decision.approved is True
        assert decision.reason_code == "OK"

    def test_consecutive_losses_at_limit_blocked(self):
        ctx = RiskContext(consecutive_loss_limit=3, consecutive_loss_window_minutes=15.0)
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=100.0)
        now = datetime(2026, 7, 12, 12, 0, 0)

        # 3 losses within Y minutes
        outcomes = [
            TradeOutcome(timestamp=now - timedelta(minutes=12), pnl=-10.0),
            TradeOutcome(timestamp=now - timedelta(minutes=10), pnl=-50.0),
            TradeOutcome(timestamp=now - timedelta(minutes=5), pnl=-20.0),
        ]

        res = evaluate_consecutive_losses(ctx, outcomes, now, decision)
        assert res is False
        assert decision.approved is False
        assert "ERR_CONSECUTIVE_LOSS_LIMIT" in decision.reason_code

    def test_consecutive_losses_outside_window_not_blocked(self):
        ctx = RiskContext(consecutive_loss_limit=3, consecutive_loss_window_minutes=15.0)
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=100.0)
        now = datetime(2026, 7, 12, 12, 0, 0)

        # 3 losses, but the first is 20 minutes ago (outside the 15-minute window)
        outcomes = [
            TradeOutcome(timestamp=now - timedelta(minutes=20), pnl=-10.0),
            TradeOutcome(timestamp=now - timedelta(minutes=10), pnl=-50.0),
            TradeOutcome(timestamp=now - timedelta(minutes=5), pnl=-20.0),
        ]

        res = evaluate_consecutive_losses(ctx, outcomes, now, decision)
        assert res is True
        assert decision.approved is True

    def test_consecutive_losses_reset_by_win(self):
        ctx = RiskContext(consecutive_loss_limit=2, consecutive_loss_window_minutes=15.0)
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=100.0)
        now = datetime(2026, 7, 12, 12, 0, 0)

        # 2 losses but split by a win (PnL = 0.0 or > 0.0)
        outcomes = [
            TradeOutcome(timestamp=now - timedelta(minutes=10), pnl=-50.0),
            TradeOutcome(timestamp=now - timedelta(minutes=8), pnl=10.0),  # win!
            TradeOutcome(timestamp=now - timedelta(minutes=5), pnl=-20.0),
        ]

        res = evaluate_consecutive_losses(ctx, outcomes, now, decision)
        assert res is True
        assert decision.approved is True

    def test_gate_disabled_when_limit_is_zero(self):
        ctx = RiskContext(consecutive_loss_limit=0, consecutive_loss_window_minutes=15.0)
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=100.0)
        now = datetime(2026, 7, 12, 12, 0, 0)

        outcomes = [
            TradeOutcome(timestamp=now - timedelta(minutes=10), pnl=-50.0),
            TradeOutcome(timestamp=now - timedelta(minutes=8), pnl=-10.0),
            TradeOutcome(timestamp=now - timedelta(minutes=5), pnl=-20.0),
        ]

        res = evaluate_consecutive_losses(ctx, outcomes, now, decision)
        assert res is True
        assert decision.approved is True

    def test_risk_authority_integrates_gating(self):
        ctx = RiskContext(consecutive_loss_limit=2, consecutive_loss_window_minutes=10.0)
        now = datetime(2026, 7, 12, 12, 0, 0)

        outcomes = [
            TradeOutcome(timestamp=now - timedelta(minutes=6), pnl=-50.0),
            TradeOutcome(timestamp=now - timedelta(minutes=2), pnl=-20.0),
        ]

        decision = RiskAuthority.evaluate_trade(
            ctx=ctx,
            daily_realized_pnl=0.0,
            equity=10000.0,
            target_family="AAPL",
            proposed_cost=100.0,
            open_positions=[],
            expected_value=1.5,
            trade_outcomes=outcomes,
            current_time=now,
        )

        assert decision.approved is False
        assert "ERR_CONSECUTIVE_LOSS_LIMIT" in decision.reason_code


class TestWebhookEmitter:
    """Tests for the webhook emitter integration."""

    @pytest.mark.anyio
    async def test_webhook_emit_success(self):
        def handle_request(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/webhook"
            assert request.headers["content-type"] == "application/json"
            return httpx.Response(200, json={"status": "ok"})

        transport = httpx.MockTransport(handle_request)

        async with httpx.AsyncClient(transport=transport) as client:
            emitter = WebhookEmitter("http://testserver/webhook", client=client)

            event = RiskEvent(
                timestamp=datetime(2026, 7, 12, 12, 0, 0),
                decision_approved=False,
                reason_code="ERR_CONSECUTIVE_LOSS_LIMIT",
                suggested_size=0.0,
                proposed_trade=ProposedTradeInfo(
                    target_family="AAPL", proposed_cost=100.0, expected_value=1.5
                ),
            )

            success = await emitter.emit(event)
            assert success is True

    @pytest.mark.anyio
    async def test_webhook_emit_server_error(self):
        def handle_request(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        transport = httpx.MockTransport(handle_request)

        async with httpx.AsyncClient(transport=transport) as client:
            emitter = WebhookEmitter("http://testserver/webhook", client=client)

            event = RiskEvent(
                timestamp=datetime(2026, 7, 12, 12, 0, 0),
                decision_approved=True,
                reason_code="OK",
                suggested_size=100.0,
                proposed_trade=ProposedTradeInfo(
                    target_family="AAPL", proposed_cost=100.0, expected_value=1.5
                ),
            )

            success = await emitter.emit(event)
            assert success is False


class TestOpenTelemetryTracing:
    """Tests for OpenTelemetry tracing integration."""

    def test_opentelemetry_traces_evaluation_pipeline(self):
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        # Configure real OpenTelemetry for the test
        provider = TracerProvider()
        exporter = InMemorySpanExporter()
        processor = SimpleSpanProcessor(exporter)
        provider.add_span_processor(processor)

        old_provider = trace.get_tracer_provider()
        trace.set_tracer_provider(provider)

        try:
            ctx = RiskContext(consecutive_loss_limit=2)
            now = datetime(2026, 7, 12, 12, 0, 0)
            outcomes = [
                TradeOutcome(timestamp=now - timedelta(minutes=1), pnl=-10.0),
                TradeOutcome(timestamp=now - timedelta(minutes=2), pnl=-20.0),
            ]

            decision = RiskAuthority.evaluate_trade(
                ctx=ctx,
                daily_realized_pnl=0.0,
                equity=5000.0,
                target_family="GOOG",
                proposed_cost=500.0,
                open_positions=[],
                expected_value=2.0,
                trade_outcomes=outcomes,
                current_time=now,
            )

            assert decision.approved is False  # Rejected by consecutive loss limit

            spans = exporter.get_finished_spans()
            span_names = [span.name for span in spans]

            # Spans should include the main evaluate_trade call and sub-span gates
            assert "evaluate_trade" in span_names
            assert "evaluate_expected_value" in span_names
            assert "evaluate_drawdown" in span_names
            assert "evaluate_consecutive_losses" in span_names

            # Find the root span
            root_span = next(s for s in spans if s.name == "evaluate_trade")
            attributes = root_span.attributes
            assert attributes is not None
            assert attributes.get("trade_risk_engine.target_family") == "GOOG"
            assert attributes.get("trade_risk_engine.proposed_cost") == 500.0
            assert attributes.get("approved") is False
            reason_code = attributes.get("reason_code")
            assert reason_code is not None
            assert "ERR_CONSECUTIVE_LOSS_LIMIT" in str(reason_code)

        finally:
            trace.set_tracer_provider(old_provider)

    def test_consecutive_losses_current_time_none_naive(self):
        ctx = RiskContext(consecutive_loss_limit=3, consecutive_loss_window_minutes=15.0)
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=100.0)

        # Passing no current_time, outcomes are naive
        outcomes = [
            TradeOutcome(timestamp=datetime.utcnow() - timedelta(minutes=5), pnl=-10.0),
        ]

        res = evaluate_consecutive_losses(ctx, outcomes, None, decision)
        assert res is True
        assert decision.approved is True

    def test_consecutive_losses_current_time_none_aware(self):
        from datetime import timezone

        ctx = RiskContext(consecutive_loss_limit=3, consecutive_loss_window_minutes=15.0)
        decision = RiskDecision(approved=True, reason_code="OK", suggested_size=100.0)

        # Passing no current_time, outcomes are aware
        outcomes = [
            TradeOutcome(timestamp=datetime.now(timezone.utc) - timedelta(minutes=5), pnl=-10.0),
        ]

        res = evaluate_consecutive_losses(ctx, outcomes, None, decision)
        assert res is True
        assert decision.approved is True


class TestWebhookEmitterIntegration:
    """Additional integration checks for WebhookEmitter without client context."""

    @pytest.mark.anyio
    async def test_webhook_emit_no_client_default(self):
        from unittest.mock import AsyncMock, patch

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = AsyncMock()

        with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
            emitter = WebhookEmitter("http://testserver/webhook")
            event = RiskEvent(
                timestamp=datetime(2026, 7, 12, 12, 0, 0),
                decision_approved=True,
                reason_code="OK",
                suggested_size=100.0,
                proposed_trade=ProposedTradeInfo(
                    target_family="AAPL", proposed_cost=100.0, expected_value=1.5
                ),
            )
            success = await emitter.emit(event)
            assert success is True
            mock_post.assert_called_once()
