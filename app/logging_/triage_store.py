from __future__ import annotations

from pathlib import Path

from app.models.triage import TriageRecord


class TriageStore:
    """The latest triage output per lead, one JSON file each — kept separate
    from the raw conversation log so QC can compare "what triage concluded"
    against "what was actually said" without them being the same document."""

    def __init__(self, base_dir: str | Path):
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, lead_id: str) -> Path:
        safe_id = lead_id.replace("/", "_")
        return self._base_dir / f"{safe_id}.json"

    def list_lead_ids(self) -> list[str]:
        return [p.stem for p in self._base_dir.glob("*.json")]

    def save(self, record: TriageRecord) -> None:
        self._path(record.lead_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def load(self, lead_id: str) -> TriageRecord | None:
        path = self._path(lead_id)
        if not path.exists():
            return None
        return TriageRecord.model_validate_json(path.read_text(encoding="utf-8"))
