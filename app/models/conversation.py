from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    direction: Literal["inbound", "outbound"]
    body: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    channel_message_id: str | None = None
    # What the agent used to produce this turn (retrieved doc sources, tool
    # calls made) — this is what a phase-2 nightly QC job would read to spot
    # bad classifications or missed info.
    ai_meta: dict[str, Any] | None = None


class ConversationLog(BaseModel):
    lead_id: str
    channel: Literal["sms"] = "sms"
    messages: list[Message] = Field(default_factory=list)
