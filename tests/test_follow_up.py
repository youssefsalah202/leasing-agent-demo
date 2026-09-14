"""End-to-end tests for automated follow-up. Hits the real Claude API —
skipped automatically if ANTHROPIC_API_KEY isn't set (see conftest.py)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.batch.follow_up import run
from app.config import Settings
from app.integrations.monday.stub import StubCrmClient
from app.integrations.quo.stub import StubQuoClient
from app.logging_.conversation_log import ConversationLogStore
from app.models.conversation import Message
from app.models.lead import LeadStatus

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="requires a real ANTHROPIC_API_KEY to exercise the live follow-up job",
)


@pytest.fixture()
def env(tmp_path):
    settings = Settings(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        crm_store_path=str(tmp_path / "crm_store.json"),
        conversations_dir=str(tmp_path / "conversations"),
    )
    crm = StubCrmClient(settings.crm_store_path)
    quo = StubQuoClient(str(tmp_path / "no_calls.json"))  # no stub calls needed here
    log_store = ConversationLogStore(settings.conversations_dir)
    return {"settings": settings, "crm": crm, "quo": quo, "log_store": log_store}


def _seed_stale_lead(env, phone: str, status: LeadStatus, hours_since_contact: float) -> None:
    crm = env["crm"]
    crm.get_or_create_lead(phone)
    env["log_store"].append_message(
        phone, Message(direction="inbound", body="Hi, is a 2 bedroom available? My name is Sam.")
    )
    crm.update_lead(
        phone,
        status=status,
        name="Sam",
        unit_interest="2 bedroom",
        last_contact_at=datetime.now(timezone.utc) - timedelta(hours=hours_since_contact),
    )


def test_stale_eligible_lead_gets_a_follow_up(env):
    phone = "+15551110001"
    _seed_stale_lead(env, phone, LeadStatus.CONTACTED, hours_since_contact=72)

    sent = run(env["settings"], env["crm"], env["quo"], env["log_store"], after=timedelta(hours=48))

    assert len(sent) == 1
    assert sent[0]["lead_id"] == phone
    assert sent[0]["body"].strip() != ""
    assert env["quo"].sent_messages and env["quo"].sent_messages[-1]["to"] == phone

    lead = env["crm"].get_or_create_lead(phone)
    assert lead.next_follow_up_at is not None and lead.next_follow_up_at > datetime.now(timezone.utc)


def test_recently_contacted_lead_is_not_followed_up(env):
    phone = "+15551110002"
    _seed_stale_lead(env, phone, LeadStatus.CONTACTED, hours_since_contact=1)

    sent = run(env["settings"], env["crm"], env["quo"], env["log_store"], after=timedelta(hours=48))

    assert sent == []
    assert env["quo"].sent_messages == []


def test_terminal_status_lead_is_never_followed_up_even_if_stale(env):
    """The exclusion rule matters more than the inclusion rule here — a
    lead that already leased or was never real shouldn't get spammed just
    because it's been a while."""
    phone = "+15551110003"
    _seed_stale_lead(env, phone, LeadStatus.LEASED, hours_since_contact=500)

    sent = run(env["settings"], env["crm"], env["quo"], env["log_store"], after=timedelta(hours=48))

    assert sent == []
    assert env["quo"].sent_messages == []


def test_follow_up_is_not_sent_twice_in_a_row(env):
    phone = "+15551110004"
    _seed_stale_lead(env, phone, LeadStatus.CONTACTED, hours_since_contact=72)

    first = run(env["settings"], env["crm"], env["quo"], env["log_store"], after=timedelta(hours=48))
    second = run(env["settings"], env["crm"], env["quo"], env["log_store"], after=timedelta(hours=48))

    assert len(first) == 1
    assert second == []
