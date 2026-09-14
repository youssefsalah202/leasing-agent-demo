from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models.conversation import CallTranscript

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

    def __init__(self, stub_calls_path: str | Path = "data/stub_calls.json") -> None:
        self.sent_messages: list[dict] = []
        self._stub_calls_path = Path(stub_calls_path)

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

    def fetch_call_transcripts(self, since: datetime) -> list[CallTranscript]:
        """Reads sample call transcripts from a local JSON fixture, standing
        in for a real Quo call-history/transcription API. See data/stub_calls.json.

        Fixture entries use "hours_ago" rather than a fixed timestamp, so the
        demo behaves the same regardless of what day/time you run it — a
        fixed absolute timestamp would eventually fall outside any lookback
        window (or, worse, sit in the future relative to "now" on the same
        day and never age out, which is what happened during testing)."""
        if not self._stub_calls_path.exists():
            return []
        raw = json.loads(self._stub_calls_path.read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc)
        calls = [
            CallTranscript(
                lead_phone=c["lead_phone"],
                call_id=c["call_id"],
                occurred_at=now - timedelta(hours=c["hours_ago"]),
                transcript=c["transcript"],
            )
            for c in raw
        ]
        return [c for c in calls if c.occurred_at >= since]
