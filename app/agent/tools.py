from __future__ import annotations

from datetime import datetime
from typing import Any

from app.integrations.monday.base import CrmClient
from app.models.lead import LeadStatus, TourSlot

BOOK_TOUR_TOOL = {
    "name": "book_tour",
    "description": (
        "Book a property tour for the prospect and record it on their CRM "
        "record. Only call this once the prospect has confirmed a specific "
        "date and time — don't call it while you're still negotiating times."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "property_name": {"type": "string", "description": "Name of the property/community"},
            "unit": {"type": "string", "description": "Unit number or type, if known"},
            "scheduled_for": {
                "type": "string",
                "description": "ISO 8601 datetime the tour is confirmed for, e.g. 2026-09-16T15:00:00",
            },
        },
        "required": ["property_name", "scheduled_for"],
    },
}

UPDATE_CRM_FIELD_TOOL = {
    "name": "update_crm_field",
    "description": (
        "Update a single field on the prospect's CRM record based on "
        "something they told you — e.g. their name, which unit they're "
        "interested in, or a status change."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "field": {
                "type": "string",
                "enum": ["status", "unit_interest", "name"],
            },
            "value": {
                "type": "string",
                "description": (
                    "The new value. If field is 'status', this must be exactly one of: "
                    + ", ".join(s.value for s in LeadStatus)
                ),
            },
        },
        "required": ["field", "value"],
    },
}

TOOLS = [BOOK_TOUR_TOOL, UPDATE_CRM_FIELD_TOOL]


def execute_tool(name: str, tool_input: dict[str, Any], crm: CrmClient, lead_id: str) -> str:
    """Run a tool call against the CRM and return a short string result to
    feed back to the model as the tool_result."""
    if name == "book_tour":
        slot = TourSlot(
            property_name=tool_input["property_name"],
            unit=tool_input.get("unit"),
            scheduled_for=datetime.fromisoformat(tool_input["scheduled_for"]),
        )
        lead = crm.book_tour(lead_id, slot)
        return (
            f"Tour booked for {lead.tour.scheduled_for.isoformat()} at "
            f"{lead.tour.property_name}. Lead status is now {lead.status.value}."
        )

    if name == "update_crm_field":
        field, value = tool_input["field"], tool_input["value"]
        if field == "status":
            # Normalize minor formatting drift ("tour scheduled" -> "tour_scheduled")
            # in case the model doesn't send the exact enum spelling.
            normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
            try:
                value = LeadStatus(normalized)
            except ValueError:
                valid = ", ".join(s.value for s in LeadStatus)
                raise ValueError(f"{value!r} is not a valid status. Valid values: {valid}") from None
        lead = crm.update_lead(lead_id, **{field: value})
        return f"Updated {field} to {value!r}."

    raise ValueError(f"Unknown tool: {name}")
