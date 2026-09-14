from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from app.models.conversation import CallTranscript


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

    def fetch_call_transcripts(self, since: datetime) -> list[CallTranscript]:
        """Fetch transcribed calls that occurred at or after `since`. Used by
        the nightly triage job — calls have no live handler like SMS does,
        so this is the only place call content ever reaches the system."""
