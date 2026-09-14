from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .base import InboundMessage


class StubQuoClient:
    """Stand-in for the real Quo API.

    Instead of calling out to Quo, it records what would have been sent so
    tests/demos can inspect it, and prints outbound messages to the console
    so you can watch the conversation happen while demoing.

    The webhook payload shape below is a reasonable guess (from/body/id/
    timestamp) — swap this for real field names once we have Quo's webhook
    docs, and swap send_sms for a real HTTP call once we have API access.
    Nothing outside this file needs to change when that happens: everything
    downstream depends only on QuoClient's interface (app/integrations/quo/base.py).
    """

    def __init__(self) -> None:
        self.sent_messages: list[dict] = []

    def send_sms(self, to: str, body: str) -> None:
        self.sent_messages.append(
            {"to": to, "body": body, "sent_at": datetime.now(timezone.utc).isoformat()}
        )
        print(f"[StubQuoClient] -> {to}: {body}")

    def parse_inbound_webhook(self, payload: dict) -> InboundMessage:
        return InboundMessage(
            from_phone=payload["from"],
            body=payload["body"],
            message_id=payload.get("id", str(uuid.uuid4())),
            timestamp=payload.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )
