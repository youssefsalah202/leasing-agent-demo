"""Tests for the browser demo's HTTP routes, with a fake agent so no Claude
call is made."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.demo.api import MAX_MESSAGE_CHARS, build_demo_router
from app.integrations.monday.stub import StubCrmClient
from app.logging_.conversation_log import ConversationLogStore

PHONE = "+15551230000"


class FakeAgent:
    """Mimics the real agent's side effects: updates the CRM and logs the turn."""

    def __init__(self, crm, log_store):
        self.crm, self.log_store = crm, log_store

    def invoke(self, state):
        lead = self.crm.get_or_create_lead(state["phone"])
        self.crm.update_lead(lead.id, name="Sam")
        reply = f"Echo: {state['inbound_body']}"
        self.log_store.append_turn(
            lead_id=lead.id,
            inbound_body=state["inbound_body"],
            outbound_body=reply,
            ai_meta={"faq_sources": ["pet_policy.md"], "tool_calls": []},
        )
        return {"outbound_body": reply}


@pytest.fixture()
def client(tmp_path):
    crm = StubCrmClient(tmp_path / "crm.json")
    log_store = ConversationLogStore(tmp_path / "conversations")
    app = FastAPI()
    app.include_router(build_demo_router(FakeAgent(crm, log_store), crm, log_store, crm_backend="monday"))
    return TestClient(app)


def test_chat_returns_reply_trace_lead_and_timing(client):
    res = client.post("/demo/chat", json={"phone": PHONE, "body": "Do you allow pets?"})
    assert res.status_code == 200
    data = res.json()
    assert data["reply"] == "Echo: Do you allow pets?"
    assert data["meta"]["faq_sources"] == ["pet_policy.md"]
    assert data["lead"]["phone"] == PHONE and data["lead"]["name"] == "Sam"
    assert data["elapsed_ms"] >= 0


def test_history_and_lead_routes(client):
    client.post("/demo/chat", json={"phone": PHONE, "body": "hello"})
    history = client.get(f"/demo/history/{PHONE}").json()
    assert [m["direction"] for m in history] == ["inbound", "outbound"]
    assert client.get(f"/demo/lead/{PHONE}").json()["name"] == "Sam"


def test_config_reports_the_crm_backend(client):
    assert client.get("/demo/config").json() == {"crm_backend": "monday"}


@pytest.mark.parametrize("phone", ["", "5551230000", "+1", "../../etc", "+1555abc1234", "+1555123000012345678"])
def test_bad_phone_numbers_are_rejected(client, phone):
    assert client.post("/demo/chat", json={"phone": phone, "body": "hi"}).status_code == 400
    assert client.get("/demo/lead/" + phone.replace("/", "%2F")).status_code in (400, 404)


def test_empty_and_oversized_messages_are_rejected(client):
    assert client.post("/demo/chat", json={"phone": PHONE, "body": "   "}).status_code == 400
    too_long = "x" * (MAX_MESSAGE_CHARS + 1)
    assert client.post("/demo/chat", json={"phone": PHONE, "body": too_long}).status_code == 400
