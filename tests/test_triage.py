"""End-to-end test for the nightly triage job. Hits the real Claude API —
skipped automatically if ANTHROPIC_API_KEY isn't set (see conftest.py)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.batch.triage import run
from app.config import Settings
from app.integrations.monday.stub import StubCrmClient
from app.integrations.quo.stub import StubQuoClient
from app.logging_.conversation_log import ConversationLogStore
from app.logging_.triage_store import TriageStore
from app.models.lead import LeadStatus

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="requires a real ANTHROPIC_API_KEY to exercise the live triage job",
)


@pytest.fixture()
def env(tmp_path):
    settings = Settings(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        crm_store_path=str(tmp_path / "crm_store.json"),
        conversations_dir=str(tmp_path / "conversations"),
        triage_store_dir=str(tmp_path / "triage"),
        # Reuse the project's real fixture — it's read-only and its
        # timestamps are relative ("hours_ago"), so this is safe to share.
        stub_calls_path="data/stub_calls.json",
    )
    crm = StubCrmClient(settings.crm_store_path)
    quo = StubQuoClient(settings.stub_calls_path)
    log_store = ConversationLogStore(settings.conversations_dir)
    triage_store = TriageStore(settings.triage_store_dir)
    return {"settings": settings, "crm": crm, "quo": quo, "log_store": log_store, "triage_store": triage_store}


def test_triage_classifies_a_real_prospect_call(env):
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    run(env["settings"], env["crm"], env["quo"], env["log_store"], env["triage_store"], since)

    lead = env["crm"].get_or_create_lead("+15552223333")
    assert lead.status in {LeadStatus.CONTACTED, LeadStatus.QUALIFIED}
    assert lead.name == "Priya"
    assert lead.unit_interest and "2" in lead.unit_interest

    record = env["triage_store"].load(lead.id)
    assert record is not None
    assert record.result.confidence > 0.5


def test_triage_recognizes_a_wrong_number_call_as_not_a_lead(env):
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    run(env["settings"], env["crm"], env["quo"], env["log_store"], env["triage_store"], since)

    lead = env["crm"].get_or_create_lead("+15554445566")
    assert lead.status == LeadStatus.NOT_A_LEAD
