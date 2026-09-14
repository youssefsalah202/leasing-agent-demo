from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.models.lead import LeadStatus


class TriageResult(BaseModel):
    """Structured output of the nightly triage classification for one lead's
    conversation. This is Claude's assessment — it gets written onto the
    Lead record, and stored alongside the raw conversation for QC to check."""

    status: LeadStatus
    unit_interest: str | None = Field(
        default=None, description="Unit type/size they're interested in, if mentioned"
    )
    name: str | None = Field(default=None, description="The prospect's name, if mentioned")
    summary: str = Field(description="1-2 sentence summary of the conversation so far")
    confidence: float = Field(description="0-1 confidence in this classification")


class TriageRecord(BaseModel):
    """A TriageResult plus the bookkeeping needed to store/retrieve it and
    for QC to reference it later."""

    lead_id: str
    result: TriageResult
    run_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # QC fills these in on its next pass; None until QC has run.
    qc_reviewed_at: datetime | None = None
