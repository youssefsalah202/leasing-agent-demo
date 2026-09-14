"""End-to-end scripted conversations, run directly against the agent graph
(no HTTP server needed). These hit the real Claude API — they're skipped
automatically if ANTHROPIC_API_KEY isn't set.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.agent.graph import build_graph
from app.config import Settings
from app.integrations.monday.stub import StubCrmClient
from app.integrations.quo.stub import StubQuoClient
from app.logging_.conversation_log import ConversationLogStore
from app.models.lead import LeadStatus
from app.rag.store import DOCS_DIR, FaqStore

FIXTURES_DIR = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="requires a real ANTHROPIC_API_KEY to exercise the live agent",
)


@pytest.fixture()
def env(tmp_path):
    settings = Settings(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        crm_store_path=str(tmp_path / "crm_store.json"),
        conversations_dir=str(tmp_path / "conversations"),
        chroma_persist_dir=str(tmp_path / "chroma"),
    )
    quo = StubQuoClient()
    crm = StubCrmClient(settings.crm_store_path)
    faq = FaqStore(settings.chroma_persist_dir)
    faq.seed_from_docs(DOCS_DIR)
    logs = ConversationLogStore(settings.conversations_dir)
    agent = build_graph(settings, crm, quo, faq, logs)
    return {"agent": agent, "quo": quo, "crm": crm}


def _run_scenario(env, fixture_name: str) -> str:
    scenario = json.loads((FIXTURES_DIR / fixture_name).read_text())
    for turn in scenario["turns"]:
        env["agent"].invoke({"phone": scenario["phone"], "inbound_body": turn["inbound"]})
    return scenario["phone"]


def test_faq_question_gets_grounded_answer(env):
    _run_scenario(env, "conversation_faq.json")

    assert env["quo"].sent_messages, "agent should have sent at least one reply"
    reply = env["quo"].sent_messages[-1]["body"]
    assert reply.strip() != ""
    print(f"\nFAQ reply: {reply}")


def test_tour_request_gets_booked(env):
    phone = _run_scenario(env, "conversation_tour.json")

    lead = env["crm"].get_or_create_lead(phone)
    assert lead.status == LeadStatus.TOUR_SCHEDULED
    assert lead.tour is not None
    print(f"\nBooked tour: {lead.tour}")
