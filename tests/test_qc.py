"""End-to-end tests for the nightly QC job. Hits the real Claude API —
skipped automatically if ANTHROPIC_API_KEY isn't set (see conftest.py)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.batch import qc, triage
from app.config import Settings
from app.integrations.monday.stub import StubCrmClient
from app.integrations.quo.stub import StubQuoClient
from app.logging_.conversation_log import ConversationLogStore
from app.logging_.triage_store import TriageStore
from app.models.conversation import Message
from app.models.lead import LeadStatus
from app.models.triage import TriageRecord, TriageResult

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="requires a real ANTHROPIC_API_KEY to exercise the live QC job",
)


@pytest.fixture()
def env(tmp_path):
    settings = Settings(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        crm_store_path=str(tmp_path / "crm_store.json"),
        conversations_dir=str(tmp_path / "conversations"),
        triage_store_dir=str(tmp_path / "triage"),
        stub_calls_path="data/stub_calls.json",  # read-only, relative timestamps
    )
    crm = StubCrmClient(settings.crm_store_path)
    quo = StubQuoClient(settings.stub_calls_path)
    log_store = ConversationLogStore(settings.conversations_dir)
    triage_store = TriageStore(settings.triage_store_dir)
    return {"settings": settings, "crm": crm, "quo": quo, "log_store": log_store, "triage_store": triage_store}


def test_qc_does_not_flag_a_lead_solely_for_lacking_a_next_step(env):
    """QC's job is checking classification accuracy, not suggesting next
    steps — a lead that just hasn't been toured/followed-up-with yet is
    normal, not an error. (A previous version of the QC prompt got this
    wrong and flagged every early-stage lead for exactly this reason.)

    This intentionally doesn't assert "never flagged" — reasonable graders
    can disagree at the margin on e.g. contacted vs. qualified, and that's
    QC doing its job, not a bug. It asserts the *specific* bug is gone: if
    QC does flag something, the reason isn't "no tour/follow-up yet"."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    triage.run(env["settings"], env["crm"], env["quo"], env["log_store"], env["triage_store"], since)

    qc.run(env["settings"], env["crm"], env["log_store"], env["triage_store"])

    lead = env["crm"].get_or_create_lead("+15552223333")  # Priya, a genuine prospect
    if lead.needs_review:
        combined = " ".join(lead.review_notes).lower()
        for phrase in ("no tour", "hasn't toured", "follow-up needed", "follow up needed", "needs follow-up"):
            assert phrase not in combined, f"QC flagged lack-of-progression again: {lead.review_notes}"

    record = env["triage_store"].load(lead.id)
    assert record.qc_reviewed_at is not None


def test_qc_catches_a_wrong_triage_classification(env):
    """The actual value-add: seed a deliberately wrong triage result against
    a conversation that clearly contradicts it, and confirm QC does
    something about it — corrects the status, flags it for review, or both."""
    phone = "+15559998877"
    env["crm"].get_or_create_lead(phone)
    env["log_store"].append_message(
        phone,
        Message(
            direction="inbound",
            body=(
                "Hi, I was interested in a 1 bedroom but I actually just signed "
                "a lease at another complex. Please stop texting me, thanks."
            ),
        ),
    )
    bad_result = TriageResult(
        status=LeadStatus.QUALIFIED,
        unit_interest="1 bedroom",
        summary="Prospect is qualified and interested in a 1 bedroom unit.",
        confidence=0.9,
    )
    env["triage_store"].save(TriageRecord(lead_id=phone, result=bad_result))

    qc.run(env["settings"], env["crm"], env["log_store"], env["triage_store"])

    lead = env["crm"].get_or_create_lead(phone)
    # QC should not leave an obviously-wrong "qualified" standing unquestioned.
    assert lead.status == LeadStatus.LOST or lead.needs_review is True

    record = env["triage_store"].load(phone)
    assert record.qc_reviewed_at is not None
