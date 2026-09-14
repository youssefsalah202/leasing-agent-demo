from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class LeadStatus(str, Enum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    TOUR_SCHEDULED = "tour_scheduled"
    TOURED = "toured"
    APPLIED = "applied"
    LEASED = "leased"
    LOST = "lost"
    UNRESPONSIVE = "unresponsive"
    # Distinct from LOST: this was never a genuine leasing prospect at all
    # (wrong number, spam, unrelated call/text) — added after the nightly QC
    # job independently flagged, twice, that forcing these into "lost"
    # mischaracterizes them as a prospect who dropped out of the funnel.
    NOT_A_LEAD = "not_a_lead"


class TourSlot(BaseModel):
    property_name: str
    unit: str | None = None
    scheduled_for: datetime
    status: str = "scheduled"  # scheduled | completed | canceled | no_show


class Lead(BaseModel):
    """A prospect record. In phase 1 this is backed by a JSON file
    (StubCrmClient); it's shaped to map cleanly onto a Monday.com board later
    (one field per column) and to feed the phase-2 triage/QC/follow-up jobs.
    """

    id: str  # phone number (E.164) doubles as the id for the demo
    phone: str
    name: str | None = None
    status: LeadStatus = LeadStatus.NEW
    unit_interest: str | None = None
    tour: TourSlot | None = None
    notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_contact_at: datetime | None = None
    next_follow_up_at: datetime | None = None
    # Set by the nightly QC job when it disagrees with (or isn't confident
    # about) triage's classification — a human should look before it's acted on.
    needs_review: bool = False
    review_notes: list[str] = Field(default_factory=list)
