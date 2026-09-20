"""Tests for the real Monday CRM client against a small in-memory fake of the
Monday GraphQL API (httpx MockTransport) — no network, no token needed."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from app.integrations.monday.client import (
    COL_NEEDS_REVIEW,
    COL_PHONE,
    COL_STATUS,
    MondayCrmClient,
    MondayError,
)
from app.models.lead import LeadStatus, TourSlot


class FakeMonday:
    """Just enough of Monday: items with text/value columns, keyed by item id."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.calls = 0
        self.fail_next: list[int] = []  # HTTP statuses to return before behaving

    def _render(self, item: dict) -> dict:
        cols = []
        for cid, raw in item["cols"].items():
            if isinstance(raw, dict) and "label" in raw:
                cols.append({"id": cid, "text": raw["label"], "value": json.dumps(raw)})
            elif isinstance(raw, dict) and "checked" in raw:
                cols.append({"id": cid, "text": "v", "value": json.dumps(raw)})
            elif isinstance(raw, dict) and "date" in raw:
                cols.append({"id": cid, "text": raw["date"], "value": json.dumps(raw) if raw["date"] else None})
            elif isinstance(raw, dict) and "text" in raw:
                cols.append({"id": cid, "text": raw["text"], "value": json.dumps(raw)})
            else:
                cols.append({"id": cid, "text": raw or "", "value": None})
        return {
            "id": item["id"],
            "name": item["name"],
            "created_at": "2026-09-01T10:00:00Z",
            "updated_at": "2026-09-02T10:00:00Z",
            "column_values": cols,
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0))
        body = json.loads(request.content)
        q, v = body["query"], body["variables"]

        if "items_page_by_column_values" in q:
            wanted = v["cols"][0]["column_values"][0]
            hit = [i for i in self.items.values() if i["cols"].get(COL_PHONE) == wanted]
            return self._ok({"items_page_by_column_values": {"items": [self._render(i) for i in hit[:1]]}})

        if "create_item" in q:
            item = {"id": str(1000 + len(self.items)), "name": v["name"], "cols": {}}
            item["cols"].update(json.loads(v["vals"]))
            self.items[item["id"]] = item
            return self._ok({"create_item": self._render(item)})

        if "change_multiple_column_values" in q:
            item = self.items.get(v["item"])
            if item is None:
                return httpx.Response(200, json={"errors": [{"message": "Item not found"}]})
            for cid, val in json.loads(v["vals"]).items():
                if cid == "name":
                    item["name"] = val
                else:
                    item["cols"][cid] = val
            return self._ok({"change_multiple_column_values": self._render(item)})

        if "next_items_page" in q:
            rest = list(self.items.values())[1:]
            return self._ok({"next_items_page": {"cursor": None, "items": [self._render(i) for i in rest]}})

        if "items_page" in q:
            first = list(self.items.values())[:1]
            more = len(self.items) > 1
            return self._ok(
                {"boards": [{"items_page": {"cursor": "abc" if more else None, "items": [self._render(i) for i in first]}}]}
            )

        raise AssertionError(f"unexpected query: {q}")

    @staticmethod
    def _ok(data: dict) -> httpx.Response:
        return httpx.Response(200, json={"data": data})


@pytest.fixture()
def monday():
    fake = FakeMonday()
    client = MondayCrmClient(
        "token", "42", transport=httpx.MockTransport(fake.handler), backoff_seconds=0
    )
    return fake, client


def test_get_or_create_is_idempotent(monday):
    fake, client = monday
    a = client.get_or_create_lead("+15551110000")
    b = client.get_or_create_lead("+15551110000")
    assert a.id == b.id == "+15551110000"
    assert a.status == LeadStatus.NEW and a.name is None
    assert len(fake.items) == 1


def test_update_round_trips_every_field(monday):
    _, client = monday
    client.get_or_create_lead("+15551110000")
    now = datetime(2026, 9, 20, 14, 30, tzinfo=timezone.utc)
    lead = client.update_lead(
        "+15551110000",
        name="Priya",
        status=LeadStatus.QUALIFIED,
        unit_interest="2BR",
        notes=["likes pets", "budget 2k"],
        last_contact_at=now,
        next_follow_up_at=now,
        needs_review=True,
        review_notes=["QC: check status"],
    )
    assert lead.name == "Priya"
    assert lead.status == LeadStatus.QUALIFIED
    assert lead.unit_interest == "2BR"
    assert lead.notes == ["likes pets", "budget 2k"]
    assert lead.last_contact_at == now and lead.next_follow_up_at == now
    assert lead.needs_review is True and lead.review_notes == ["QC: check status"]


def test_book_tour_keeps_naive_local_time_and_sets_status(monday):
    _, client = monday
    client.get_or_create_lead("+15551110000")
    slot = TourSlot(property_name="Maple Court", unit="3B", scheduled_for=datetime(2026, 9, 25, 15, 0))
    lead = client.book_tour("+15551110000", slot)
    assert lead.status == LeadStatus.TOUR_SCHEDULED
    assert lead.tour.property_name == "Maple Court" and lead.tour.unit == "3B"
    assert lead.tour.scheduled_for == datetime(2026, 9, 25, 15, 0)  # not shifted to another zone


def test_update_can_clear_needs_review(monday):
    fake, client = monday
    client.get_or_create_lead("+15551110000")
    client.update_lead("+15551110000", needs_review=True)
    lead = client.update_lead("+15551110000", needs_review=False)
    assert lead.needs_review is False or fake.items["1000"]["cols"][COL_NEEDS_REVIEW] is None


def test_status_is_sent_as_a_label(monday):
    fake, client = monday
    client.get_or_create_lead("+15551110000")
    client.update_lead("+15551110000", status="lost")
    assert fake.items["1000"]["cols"][COL_STATUS] == {"label": "lost"}


def test_update_unknown_lead_raises_keyerror(monday):
    _, client = monday
    with pytest.raises(KeyError):
        client.update_lead("+19998887777", status=LeadStatus.LOST)


def test_unsupported_field_is_rejected(monday):
    _, client = monday
    client.get_or_create_lead("+15551110000")
    with pytest.raises(ValueError):
        client.update_lead("+15551110000", favorite_color="blue")


def test_list_leads_follows_the_pagination_cursor(monday):
    _, client = monday
    for n in range(3):
        client.get_or_create_lead(f"+1555000000{n}")
    assert sorted(lead.phone for lead in client.list_leads()) == [
        "+15550000000",
        "+15550000001",
        "+15550000002",
    ]


def test_item_ids_are_cached_after_first_lookup(monday):
    fake, client = monday
    client.get_or_create_lead("+15551110000")  # lookup + create
    before = fake.calls
    client.update_lead("+15551110000", unit_interest="1BR")  # cached -> one call
    assert fake.calls == before + 1


def test_graphql_errors_raise_monday_error(monday):
    fake, client = monday
    client.get_or_create_lead("+15551110000")
    fake.items.clear()  # item deleted in Monday behind our back
    with pytest.raises(MondayError, match="Item not found"):
        client.update_lead("+15551110000", unit_interest="1BR")


def test_retries_transient_server_errors(monday):
    fake, client = monday
    fake.fail_next = [503, 429]
    lead = client.get_or_create_lead("+15551110000")
    assert lead.phone == "+15551110000"


def test_gives_up_after_max_retries(monday):
    fake, client = monday
    fake.fail_next = [500, 500, 500]
    with pytest.raises(MondayError, match="HTTP 500"):
        client.get_or_create_lead("+15551110000")


def test_requires_token_and_board():
    with pytest.raises(ValueError):
        MondayCrmClient("", "")
