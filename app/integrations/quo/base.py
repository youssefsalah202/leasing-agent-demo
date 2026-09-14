from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class InboundMessage(BaseModel):
    """Normalized shape of an inbound SMS, regardless of Quo's raw payload
    format. Everything downstream (the agent graph) works with this, not
    with Quo's wire format directly."""

    from_phone: str
    body: str
    message_id: str
    timestamp: str


class QuoClient(Protocol):
    def send_sms(self, to: str, body: str) -> None:
        """Send an outbound SMS through Quo."""

    def parse_inbound_webhook(self, payload: dict) -> InboundMessage:
        """Turn a raw Quo webhook payload into a normalized InboundMessage."""
