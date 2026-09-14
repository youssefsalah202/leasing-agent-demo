from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

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
    # QC fills this in on its next pass; None means QC hasn't reviewed this
    # triage run yet. A fresh triage run always resets it to None, so if
    # triage reclassifies a lead, QC picks it up again automatically.
    qc_reviewed_at: datetime | None = None


class QcFinding(BaseModel):
    severity: Literal["info", "warning", "error"] = Field(
        description="info: FYI, no action needed. warning/error: worth a human's attention."
    )
    issue: str = Field(description="What's wrong or missing")
    suggested_fix: str | None = None


class QcResult(BaseModel):
    """Structured output of the nightly QC pass over one lead's triage
    result. An independent re-read of the raw conversation, checked against
    what triage concluded."""

    triage_status_correct: bool
    corrected_status: LeadStatus | None = Field(
        default=None, description="Only set when triage_status_correct is false and you're confident in this instead"
    )
    confidence: float = Field(description="0-1 confidence in this QC verdict")
    reasoning: str = Field(description="Why you agree or disagree with triage's classification")
    findings: list[QcFinding] = Field(default_factory=list)
