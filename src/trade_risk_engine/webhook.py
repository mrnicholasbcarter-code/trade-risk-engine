import asyncio
import logging
from datetime import datetime, timezone

import httpx
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("trade_risk_engine.webhook")
tracer = trace.get_tracer("trade-risk-engine")


def _utc_now() -> datetime:
    """Return an aware UTC timestamp for serialized risk events."""
    return datetime.now(timezone.utc)


class ProposedTradeInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    target_family: str
    proposed_cost: float
    expected_value: float


class RiskEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    timestamp: datetime = Field(default_factory=_utc_now)
    decision_approved: bool
    reason_code: str
    suggested_size: float
    proposed_trade: ProposedTradeInfo


class WebhookEmitter:
    """Asynchronous emitter to broadcast trade risk events.

    Provides both wait-for-response async evaluation and non-blocking background dispatch.
    """

    def __init__(
        self,
        endpoint_url: str,
        client: httpx.AsyncClient | None = None,
        *,
        max_attempts: int = 3,
        timeout_seconds: float = 5.0,
        retry_delay_seconds: float = 0.0,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must be >= 0")
        self.endpoint_url = endpoint_url
        self.client = client
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.retry_delay_seconds = retry_delay_seconds

    async def emit(self, event: RiskEvent) -> bool:
        """Asynchronously send the risk event to the configured webhook endpoint URL.

        Returns True if successful, False otherwise. Traced using OpenTelemetry.
        """
        with tracer.start_as_current_span("emit_webhook") as span:
            span.set_attribute("webhook.url", self.endpoint_url)
            span.set_attribute("webhook.event.approved", event.decision_approved)
            span.set_attribute("webhook.event.reason_code", event.reason_code)

            payload = event.model_dump(mode="json")
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = await self._post_once(payload)
                    response.raise_for_status()
                    span.set_attribute("webhook.status_code", response.status_code)
                    span.set_attribute("webhook.attempts", attempt)
                    span.set_attribute("webhook.success", True)
                    return True
                except Exception as exc:
                    logger.error(
                        "Failed to broadcast webhook event to %s on attempt %s/%s: %s",
                        self.endpoint_url,
                        attempt,
                        self.max_attempts,
                        exc,
                    )
                    span.record_exception(exc)
                    span.set_attribute("webhook.attempts", attempt)
                    if attempt >= self.max_attempts:
                        span.set_attribute("webhook.success", False)
                        return False
                    if self.retry_delay_seconds > 0:
                        await asyncio.sleep(self.retry_delay_seconds)
            return False

    async def _post_once(self, payload: dict[str, object]) -> httpx.Response:
        if self.client is not None:
            return await self.client.post(
                self.endpoint_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout_seconds,
            )
        async with httpx.AsyncClient() as client:
            return await client.post(
                self.endpoint_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout_seconds,
            )
