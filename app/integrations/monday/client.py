from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.models.lead import Lead, LeadStatus, TourSlot

API_URL = "https://api.monday.com/v2"

# Column ids on the leads board. scripts/setup_monday_board.py creates the
# board with exactly these ids, so nothing needs to be looked up by hand.
COL_PHONE = "lead_phone"
COL_STATUS = "lead_status"
COL_UNIT = "unit_interest"
COL_TOUR_PROPERTY = "tour_property"
COL_TOUR_UNIT = "tour_unit"
COL_TOUR_TIME = "tour_time"
COL_TOUR_STATUS = "tour_status"
COL_NOTES = "lead_notes"
COL_LAST_CONTACT = "last_contact"
COL_NEXT_FOLLOW_UP = "next_follow_up"
COL_NEEDS_REVIEW = "needs_review"
COL_REVIEW_NOTES = "review_notes"

# (id, title, monday column type) — the status column is created separately
# because it carries its labels.
BOARD_COLUMNS: list[tuple[str, str, str]] = [
    (COL_PHONE, "Phone", "text"),
    (COL_UNIT, "Unit interest", "text"),
    (COL_TOUR_PROPERTY, "Tour property", "text"),
    (COL_TOUR_UNIT, "Tour unit", "text"),
    (COL_TOUR_TIME, "Tour time", "text"),
    (COL_TOUR_STATUS, "Tour status", "text"),
    (COL_NOTES, "Notes", "long_text"),
    (COL_LAST_CONTACT, "Last contact", "date"),
    (COL_NEXT_FOLLOW_UP, "Next follow-up", "date"),
    (COL_NEEDS_REVIEW, "Needs review", "checkbox"),
    (COL_REVIEW_NOTES, "Review notes", "long_text"),
]

_ITEM_FIELDS = "id name created_at updated_at column_values { id text value }"


class MondayError(RuntimeError):
    """The Monday API rejected a request or returned GraphQL errors."""


class MondayCrmClient:
    """The real Monday.com CRM: one board item per lead, one column per Lead
    field. Implements the same CrmClient interface as StubCrmClient, so the
    agent and the nightly jobs don't know which one they're talking to.

    The phone number stays the lead id (as in the stub) — item ids are looked
    up by the Phone column and cached, so the conversation logs and triage
    records keyed by phone keep working unchanged.
    """

    def __init__(
        self,
        api_token: str,
        board_id: str,
        api_version: str = "2026-07",
        *,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
    ) -> None:
        if not api_token or not board_id:
            raise ValueError("MONDAY_API_TOKEN and MONDAY_BOARD_ID are required for the Monday CRM")
        self._board_id = str(board_id)
        self._http = httpx.Client(
            base_url=API_URL,
            headers={
                "Authorization": api_token,
                "API-Version": api_version,
                "Content-Type": "application/json",
            },
            timeout=30.0,
            transport=transport,
        )
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._lock = threading.Lock()
        self._item_ids: dict[str, str] = {}  # phone -> monday item id

    # ------------------------------------------------------------------ API

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST one GraphQL request; retries rate limits (429) and 5xx."""
        for attempt in range(self._max_retries + 1):
            response = self._http.post("", json={"query": query, "variables": variables or {}})
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self._max_retries:
                    time.sleep(self._backoff * (2**attempt))
                    continue
                raise MondayError(f"Monday API returned HTTP {response.status_code}")
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                messages = "; ".join(e.get("message", str(e)) for e in payload["errors"])
                raise MondayError(messages)
            if payload.get("error_message"):  # older-style error envelope
                raise MondayError(payload["error_message"])
            return payload["data"]
        raise MondayError("unreachable")  # pragma: no cover

    # ------------------------------------------------------------ CrmClient

    def get_or_create_lead(self, phone: str) -> Lead:
        with self._lock:
            item = self._find_item(phone)
            if item is not None:
                return self._to_lead(item)
            data = self.graphql(
                f"""
                mutation ($board: ID!, $name: String!, $vals: JSON!) {{
                  create_item(board_id: $board, item_name: $name, column_values: $vals,
                              create_labels_if_missing: true) {{ {_ITEM_FIELDS} }}
                }}
                """,
                {
                    "board": self._board_id,
                    "name": phone,
                    "vals": json.dumps({COL_PHONE: phone, COL_STATUS: {"label": LeadStatus.NEW.value}}),
                },
            )
            item = data["create_item"]
            self._item_ids[phone] = str(item["id"])
            print(f"[MondayCrmClient] created new lead {phone} (item {item['id']})")
            return self._to_lead(item)

    def update_lead(self, lead_id: str, **fields) -> Lead:
        with self._lock:
            item_id = self._item_ids.get(lead_id)
            if item_id is None:
                found = self._find_item(lead_id)
                if found is None:
                    raise KeyError(f"No lead {lead_id}")
                item_id = str(found["id"])
            column_values = self._to_column_values(fields)
            try:
                data = self.graphql(
                    f"""
                    mutation ($board: ID!, $item: ID!, $vals: JSON!) {{
                      change_multiple_column_values(board_id: $board, item_id: $item,
                          column_values: $vals, create_labels_if_missing: true) {{ {_ITEM_FIELDS} }}
                    }}
                    """,
                    {"board": self._board_id, "item": item_id, "vals": json.dumps(column_values)},
                )
            except MondayError:
                self._item_ids.pop(lead_id, None)  # item may have been deleted in Monday
                raise
            print(f"[MondayCrmClient] updated lead {lead_id}: {fields}")
            return self._to_lead(data["change_multiple_column_values"])

    def book_tour(self, lead_id: str, slot: TourSlot) -> Lead:
        return self.update_lead(lead_id, tour=slot, status=LeadStatus.TOUR_SCHEDULED)

    def list_leads(self) -> list[Lead]:
        with self._lock:
            data = self.graphql(
                f"""
                query ($board: ID!) {{
                  boards(ids: [$board]) {{
                    items_page(limit: 500) {{ cursor items {{ {_ITEM_FIELDS} }} }}
                  }}
                }}
                """,
                {"board": self._board_id},
            )
            boards = data["boards"]
            if not boards:
                raise MondayError(f"Board {self._board_id} not found — check MONDAY_BOARD_ID and token access")
            page = boards[0]["items_page"]
            items = list(page["items"])
            while page["cursor"]:
                data = self.graphql(
                    f"""
                    query ($cursor: String!) {{
                      next_items_page(limit: 500, cursor: $cursor) {{ cursor items {{ {_ITEM_FIELDS} }} }}
                    }}
                    """,
                    {"cursor": page["cursor"]},
                )
                page = data["next_items_page"]
                items.extend(page["items"])

            leads = []
            for item in items:
                lead = self._to_lead(item, skip_if_no_phone=True)
                if lead is not None:
                    self._item_ids[lead.phone] = str(item["id"])
                    leads.append(lead)
            return leads

    # -------------------------------------------------------------- helpers

    def _find_item(self, phone: str) -> dict | None:
        data = self.graphql(
            f"""
            query ($board: ID!, $cols: [ItemsPageByColumnValuesQuery!]) {{
              items_page_by_column_values(board_id: $board, columns: $cols, limit: 1) {{
                items {{ {_ITEM_FIELDS} }}
              }}
            }}
            """,
            {"board": self._board_id, "cols": [{"column_id": COL_PHONE, "column_values": [phone]}]},
        )
        items = data["items_page_by_column_values"]["items"]
        if not items:
            return None
        self._item_ids[phone] = str(items[0]["id"])
        return items[0]

    @staticmethod
    def _date_value(dt: datetime | None) -> dict:
        if dt is None:
            return {"date": ""}
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return {"date": dt.strftime("%Y-%m-%d"), "time": dt.strftime("%H:%M:%S")}

    @classmethod
    def _to_column_values(cls, fields: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, value in fields.items():
            if key == "name":
                if value:
                    values["name"] = value
            elif key == "status":
                values[COL_STATUS] = {"label": LeadStatus(value).value}
            elif key == "unit_interest":
                values[COL_UNIT] = value or ""
            elif key == "tour":
                slot: TourSlot | None = value
                values[COL_TOUR_PROPERTY] = slot.property_name if slot else ""
                values[COL_TOUR_UNIT] = (slot.unit or "") if slot else ""
                # ISO text (not a date column) so a naive local time like
                # "15:00" isn't silently reinterpreted as UTC by Monday.
                values[COL_TOUR_TIME] = slot.scheduled_for.isoformat() if slot else ""
                values[COL_TOUR_STATUS] = slot.status if slot else ""
            elif key == "notes":
                text = "\n".join(" ".join(n.split()) for n in value)
                values[COL_NOTES] = {"text": text} if text else None
            elif key == "last_contact_at":
                values[COL_LAST_CONTACT] = cls._date_value(value)
            elif key == "next_follow_up_at":
                values[COL_NEXT_FOLLOW_UP] = cls._date_value(value)
            elif key == "needs_review":
                values[COL_NEEDS_REVIEW] = {"checked": "true"} if value else None
            elif key == "review_notes":
                text = "\n".join(" ".join(n.split()) for n in value)
                values[COL_REVIEW_NOTES] = {"text": text} if text else None
            else:
                raise ValueError(f"Unsupported lead field for the Monday CRM: {key!r}")
        return values

    @staticmethod
    def _parse_date(column: dict | None) -> datetime | None:
        if not column or not column.get("value"):
            return None
        raw = json.loads(column["value"])
        if not raw.get("date"):
            return None
        return datetime.fromisoformat(f"{raw['date']}T{raw.get('time') or '00:00:00'}").replace(tzinfo=timezone.utc)

    @staticmethod
    def _parse_iso(value: str | None) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else datetime.now(timezone.utc)

    def _to_lead(self, item: dict, skip_if_no_phone: bool = False) -> Lead | None:
        cols = {c["id"]: c for c in item["column_values"]}

        def text(col_id: str) -> str:
            return (cols.get(col_id, {}).get("text") or "").strip()

        phone = text(COL_PHONE)
        if not phone:
            if skip_if_no_phone:
                print(f"[MondayCrmClient] skipping item {item['id']} ({item['name']!r}): no phone")
                return None
            phone = item["name"]

        try:
            status = LeadStatus(text(COL_STATUS)) if text(COL_STATUS) else LeadStatus.NEW
        except ValueError:
            status = LeadStatus.NEW

        tour = None
        if text(COL_TOUR_PROPERTY) and text(COL_TOUR_TIME):
            tour = TourSlot(
                property_name=text(COL_TOUR_PROPERTY),
                unit=text(COL_TOUR_UNIT) or None,
                scheduled_for=datetime.fromisoformat(text(COL_TOUR_TIME)),
                status=text(COL_TOUR_STATUS) or "scheduled",
            )

        return Lead(
            id=phone,
            phone=phone,
            name=item["name"] if item["name"] != phone else None,
            status=status,
            unit_interest=text(COL_UNIT) or None,
            tour=tour,
            notes=[n for n in text(COL_NOTES).split("\n") if n],
            created_at=self._parse_iso(item.get("created_at")),
            updated_at=self._parse_iso(item.get("updated_at")),
            last_contact_at=self._parse_date(cols.get(COL_LAST_CONTACT)),
            next_follow_up_at=self._parse_date(cols.get(COL_NEXT_FOLLOW_UP)),
            needs_review=text(COL_NEEDS_REVIEW) == "v",
            review_notes=[n for n in text(COL_REVIEW_NOTES).split("\n") if n],
        )
