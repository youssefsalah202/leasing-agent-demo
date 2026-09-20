"""Unit tests for the agent's CRM tools (no Claude call)."""

from __future__ import annotations

import pytest

from app.agent.tools import execute_tool
from app.integrations.monday.stub import StubCrmClient
from app.models.lead import LeadStatus

PHONE = "+15551230000"


@pytest.fixture()
def crm(tmp_path):
    client = StubCrmClient(tmp_path / "crm.json")
    client.get_or_create_lead(PHONE)
    return client


def test_status_update_result_is_readable_and_normalized(crm):
    result = execute_tool("update_crm_field", {"field": "status", "value": "Tour Scheduled"}, crm, PHONE)
    assert result == "Updated status to 'tour_scheduled'."
    assert crm.get_or_create_lead(PHONE).status == LeadStatus.TOUR_SCHEDULED


def test_invalid_status_lists_the_valid_values(crm):
    with pytest.raises(ValueError, match="Valid values"):
        execute_tool("update_crm_field", {"field": "status", "value": "hot"}, crm, PHONE)


def test_book_tour_records_the_slot_and_status(crm):
    result = execute_tool(
        "book_tour",
        {"property_name": "Maple Grove Apartments", "scheduled_for": "2026-09-24T14:00:00", "unit": "2BR"},
        crm,
        PHONE,
    )
    assert "Maple Grove Apartments" in result
    lead = crm.get_or_create_lead(PHONE)
    assert lead.status == LeadStatus.TOUR_SCHEDULED and lead.tour.unit == "2BR"
