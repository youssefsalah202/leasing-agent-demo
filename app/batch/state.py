from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class BatchStateStore:
    """Tracks the last-run timestamp for each nightly job, so a job only
    processes activity since it last ran. One small JSON file, keyed by job
    name (e.g. "triage", "qc", "follow_up") — a real deployment would likely
    keep this in whatever job scheduler/database already tracks run history."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        content = self._path.read_text(encoding="utf-8").strip()
        return json.loads(content) if content else {}

    def get_last_run(self, job_name: str) -> datetime | None:
        raw = self._read().get(job_name)
        return datetime.fromisoformat(raw) if raw else None

    def set_last_run(self, job_name: str, when: datetime | None = None) -> None:
        when = when or datetime.now(timezone.utc)
        data = self._read()
        data[job_name] = when.isoformat()
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
