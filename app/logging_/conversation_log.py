from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models.conversation import ConversationLog, Message


class ConversationLogStore:
    """Append-only JSONL conversation logs, one file per lead. This is the
    artifact a phase-2 nightly QC job would read to check the agent's
    behavior against the raw conversation."""

    def __init__(self, base_dir: str | Path):
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, lead_id: str) -> Path:
        safe_id = lead_id.replace("/", "_")
        return self._base_dir / f"{safe_id}.jsonl"

    def list_lead_ids(self) -> list[str]:
        """All leads that have a conversation log on disk. File names are
        the sanitized lead_id, which for phone numbers ("+1555...") is
        reversible since '/' is the only character we ever replace."""
        return [p.stem for p in self._base_dir.glob("*.jsonl")]

    def load(self, lead_id: str) -> ConversationLog:
        path = self._path(lead_id)
        log = ConversationLog(lead_id=lead_id)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    log.messages.append(Message.model_validate_json(line))
        return log

    def append_message(self, lead_id: str, message: Message) -> None:
        path = self._path(lead_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(message.model_dump_json() + "\n")

    def append_turn(
        self,
        lead_id: str,
        inbound_body: str,
        outbound_body: str,
        ai_meta: dict[str, Any] | None = None,
    ) -> None:
        self.append_message(lead_id, Message(direction="inbound", body=inbound_body))
        self.append_message(lead_id, Message(direction="outbound", body=outbound_body, ai_meta=ai_meta))
        print(f"[ConversationLogStore] logged turn for {lead_id}")
