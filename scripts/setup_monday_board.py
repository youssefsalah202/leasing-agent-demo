"""Create the Monday.com leads board (columns included) and print the board id.

Usage:
    1. Put your token in .env:  MONDAY_API_TOKEN=...   (monday.com -> avatar ->
       Developers -> My access tokens)
    2. python scripts/setup_monday_board.py
    3. Copy the printed MONDAY_BOARD_ID into .env and set CRM_BACKEND=monday

    python scripts/setup_monday_board.py --check   # round-trip test on the board from .env
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.integrations.monday.client import (
    BOARD_COLUMNS,
    COL_STATUS,
    MondayCrmClient,
    MondayError,
)
from app.models.lead import LeadStatus, TourSlot

BOARD_NAME = "Leasing Leads"

# Status label -> Monday color (shown as the colored pill on the board).
STATUS_COLORS = {
    LeadStatus.NEW: "bright_blue",
    LeadStatus.CONTACTED: "purple",
    LeadStatus.QUALIFIED: "egg_yellow",
    LeadStatus.TOUR_SCHEDULED: "working_orange",
    LeadStatus.TOURED: "dark_blue",
    LeadStatus.APPLIED: "sofia_pink",
    LeadStatus.LEASED: "done_green",
    LeadStatus.LOST: "stuck_red",
    LeadStatus.UNRESPONSIVE: "american_gray",
    LeadStatus.NOT_A_LEAD: "blackish",
}


def _client() -> MondayCrmClient:
    settings = get_settings()
    if not settings.monday_api_token:
        sys.exit("Set MONDAY_API_TOKEN in .env first.")
    return MondayCrmClient(settings.monday_api_token, settings.monday_board_id or "0", settings.monday_api_version)


def setup() -> None:
    client = _client()

    board = client.graphql(
        "mutation ($name: String!) { create_board(board_name: $name, board_kind: private) { id } }",
        {"name": BOARD_NAME},
    )["create_board"]
    board_id = board["id"]
    print(f"created board '{BOARD_NAME}' (id {board_id})")

    labels = ", ".join(
        f'{{ color: {color}, label: "{status.value}", index: {i} }}'
        for i, (status, color) in enumerate(STATUS_COLORS.items())
    )
    try:
        client.graphql(
            f'mutation ($board: ID!) {{ create_status_column(board_id: $board, id: "{COL_STATUS}", '
            f'title: "Status", defaults: {{ labels: [{labels}] }}) {{ id }} }}',
            {"board": board_id},
        )
    except MondayError as exc:
        # Fall back to a plain status column; the client creates labels on demand.
        print(f"  (custom status labels failed: {exc} — using a plain status column instead)")
        client.graphql(
            "mutation ($board: ID!) { create_column(board_id: $board, id: \"%s\", title: \"Status\", "
            "column_type: status) { id } }" % COL_STATUS,
            {"board": board_id},
        )
    print("  + Status")

    for col_id, title, col_type in BOARD_COLUMNS:
        client.graphql(
            "mutation ($board: ID!, $id: String!, $title: String!, $type: ColumnType!) "
            "{ create_column(board_id: $board, id: $id, title: $title, column_type: $type) { id } }",
            {"board": board_id, "id": col_id, "title": title, "type": col_type},
        )
        print(f"  + {title}")

    # New boards come with starter columns (Person, Status, Date ...) — drop them.
    keep = {"name", COL_STATUS, *(c[0] for c in BOARD_COLUMNS)}
    existing = client.graphql(
        "query ($board: ID!) { boards(ids: [$board]) { columns { id title } } }", {"board": board_id}
    )["boards"][0]["columns"]
    for col in existing:
        if col["id"] in keep:
            continue
        try:
            client.graphql(
                "mutation ($board: ID!, $col: String!) { delete_column(board_id: $board, column_id: $col) { id } }",
                {"board": board_id, "col": col["id"]},
            )
            print(f"  - removed starter column '{col['title']}'")
        except MondayError as exc:
            print(f"  (kept starter column '{col['title']}': {exc})")

    print("\nDone. Add these to .env:\n")
    print(f"MONDAY_BOARD_ID={board_id}")
    print("CRM_BACKEND=monday")


def check() -> None:
    """Write, update and read back one throwaway lead, then delete it."""
    settings = get_settings()
    client = _client()
    if not settings.monday_board_id:
        sys.exit("Set MONDAY_BOARD_ID in .env first.")
    from datetime import datetime, timezone

    phone = "+10000000000"
    lead = client.get_or_create_lead(phone)
    assert lead.status == LeadStatus.NEW, lead
    lead = client.update_lead(
        phone,
        name="Setup Check",
        unit_interest="2BR",
        notes=["created by setup_monday_board.py --check"],
        last_contact_at=datetime.now(timezone.utc),
        needs_review=True,
        review_notes=["test"],
    )
    lead = client.book_tour(phone, TourSlot(property_name="Test Property", scheduled_for=datetime(2030, 1, 1, 15, 0)))
    assert lead.status == LeadStatus.TOUR_SCHEDULED and lead.tour and lead.tour.property_name == "Test Property", lead
    assert lead.name == "Setup Check" and lead.needs_review and lead.last_contact_at, lead
    assert any(x.phone == phone for x in client.list_leads())

    item_id = client._item_ids[phone]
    client.graphql("mutation ($id: ID!) { delete_item(item_id: $id) { id } }", {"id": item_id})
    print("OK — create, update, tour booking and list all work against your board (test lead removed).")


if __name__ == "__main__":
    check() if "--check" in sys.argv else setup()
