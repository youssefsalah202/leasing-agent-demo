from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.models.lead import Lead, LeadStatus, TourSlot


class StubCrmClient:
    """Stand-in for the Monday.com board. Persists leads to a JSON file
    (keyed by phone number) so state survives across demo runs, and prints
    every write so you can watch the CRM update while demoing.

    Swap this for a real client — Monday GraphQL mutations against a real
    board/column IDs — once we have board access. Nothing outside this file
    needs to change: everything downstream depends only on CrmClient's
    interface (app/integrations/monday/base.py).
    """

    def __init__(self, store_path: str | Path) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self._path.exists():
            self._write({})

    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        content = self._path.read_text(encoding="utf-8").strip()
        return json.loads(content) if content else {}

    def _write(self, data: dict) -> None:
        self._path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def get_or_create_lead(self, phone: str) -> Lead:
        with self._lock:
            data = self._read()
            if phone in data:
                return Lead.model_validate(data[phone])
            lead = Lead(id=phone, phone=phone)
            data[phone] = json.loads(lead.model_dump_json())
            self._write(data)
            print(f"[StubCrmClient] created new lead {phone}")
            return lead

    def update_lead(self, lead_id: str, **fields) -> Lead:
        with self._lock:
            data = self._read()
            if lead_id not in data:
                raise KeyError(f"No lead {lead_id}")
            lead = Lead.model_validate(data[lead_id])
            updated = lead.model_copy(update={**fields, "updated_at": datetime.now(timezone.utc)})
            data[lead_id] = json.loads(updated.model_dump_json())
            self._write(data)
            print(f"[StubCrmClient] updated lead {lead_id}: {fields}")
            return updated

    def book_tour(self, lead_id: str, slot: TourSlot) -> Lead:
        return self.update_lead(lead_id, tour=slot, status=LeadStatus.TOUR_SCHEDULED)
