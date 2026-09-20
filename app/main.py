from __future__ import annotations

from fastapi import FastAPI, Request

from app.agent.graph import build_graph
from app.config import get_settings
from app.demo.api import build_demo_router
from app.integrations.monday.factory import build_crm_client
from app.integrations.quo.stub import StubQuoClient
from app.logging_.conversation_log import ConversationLogStore
from app.rag.store import DOCS_DIR, FaqStore

settings = get_settings()

quo_client = StubQuoClient(settings.stub_calls_path)
crm_client = build_crm_client(settings)
faq_store = FaqStore(settings.chroma_persist_dir)
log_store = ConversationLogStore(settings.conversations_dir)

if not faq_store.is_seeded():
    n = faq_store.seed_from_docs(DOCS_DIR)
    print(f"[startup] seeded FAQ store with {n} chunks")

agent = build_graph(settings, crm_client, quo_client, faq_store, log_store)

app = FastAPI(title="Leasing SMS Agent — Phase 1 demo")
app.include_router(build_demo_router(agent, crm_client, log_store, crm_backend=settings.crm_backend))


@app.post("/webhooks/quo/sms")
async def quo_sms_webhook(request: Request):
    """Inbound SMS webhook. Real Quo payload shape is a guess for now
    (see StubQuoClient.parse_inbound_webhook) — adjust once we have docs."""
    payload = await request.json()
    inbound = quo_client.parse_inbound_webhook(payload)
    agent.invoke({"phone": inbound.from_phone, "inbound_body": inbound.body})
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}
