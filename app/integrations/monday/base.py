from __future__ import annotations

from typing import Protocol

from app.models.lead import Lead, TourSlot


class CrmClient(Protocol):
    """The CRM operations the agent needs. Backed by a JSON file for the
    demo (StubCrmClient); a real implementation would map these onto
    Monday.com board items/columns via their GraphQL API."""

    def get_or_create_lead(self, phone: str) -> Lead: ...

    def update_lead(self, lead_id: str, **fields) -> Lead: ...

    def book_tour(self, lead_id: str, slot: TourSlot) -> Lead: ...
