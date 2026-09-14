from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    direction: Literal["inbound", "outbound"]
    body: str
    # "call" messages are ingested by the nightly triage job from Quo call
    # transcripts — the live phase-1 agent only ever produces "sms" messages.
    channel: Literal["sms", "call"] = "sms"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    channel_message_id: str | None = None
    # What the agent used to produce this turn (retrieved doc sources, tool
    # calls made) — this is what the nightly QC job reads to spot bad
    # classifications or missed info.
    ai_meta: dict[str, Any] | None = None


class ConversationLog(BaseModel):
    lead_id: str
    messages: list[Message] = Field(default_factory=list)


class CallTranscript(BaseModel):
    """A single transcribed call, as fetched from Quo. We assume Quo (or a
    transcription layer in front of it) hands us call text, not audio —
    flagged as an assumption to confirm once we have real Quo API access."""

    lead_phone: str
    call_id: str
    occurred_at: datetime
    transcript: str
