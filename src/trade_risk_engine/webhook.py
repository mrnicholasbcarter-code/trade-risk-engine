import logging
from datetime import datetime

import httpx
from opentelemetry import trace
from pydantic import BaseModel, Field

logger = logging.getLogger("trade_risk_engine.webhook")
tracer = trace.get_tracer("trade-risk-engine")


class ProposedTradeInfo(BaseModel):
    target_family: str
    proposed_cost: float
    expected_value: float


class RiskEvent(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    decision_approved: bool
    reason_code: str
    suggested_size: float
    proposed_trade: ProposedTradeInfo


class WebhookEmitter:
    """Asynchronous emitter to broadcast trade risk events.

    Provides both wait-for-response async evaluation and non-blocking background dispatch.
    """

    def __init__(self, endpoint_url: str, client: httpx.AsyncClient | None = None):
        self.endpoint_url = endpoint_url
        self.client = client

    async def emit(self, event: RiskEvent) -> bool:
        """Asynchronously send the risk event to the configured webhook endpoint URL.

        Returns True if successful, False otherwise. Traced using OpenTelemetry.
        """
        with tracer.start_as_current_span("emit_webhook") as span:
            span.set_attribute("webhook.url", self.endpoint_url)
            span.set_attribute("webhook.event.approved", event.decision_approved)
            span.set_attribute("webhook.event.reason_code", event.reason_code)

            try:
                if self.client is not None:
                    response = await self.client.post(
                        self.endpoint_url,
                        json=event.model_dump(mode="json"),
                        headers={"Content-Type": "application/json"},
                        timeout=5.0,
                    )
                else:
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            self.endpoint_url,
                            json=event.model_dump(mode="json"),
                            headers={"Content-Type": "application/json"},
                            timeout=5.0,
                        )
                response.raise_for_status()
                span.set_attribute("webhook.status_code", response.status_code)
                span.set_attribute("webhook.success", True)
                return True
            except Exception as e:
                logger.error(f"Failed to broadcast webhook event to {self.endpoint_url}: {e}")
                span.record_exception(e)
                span.set_attribute("webhook.success", False)
                return False
