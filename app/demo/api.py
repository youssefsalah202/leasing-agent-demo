from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.integrations.monday.base import CrmClient
from app.logging_.conversation_log import ConversationLogStore

STATIC_DIR = Path(__file__).parent / "static"


def build_demo_router(agent: Any, crm_client: CrmClient, log_store: ConversationLogStore) -> APIRouter:
    """Routes behind the no-install browser chat widget (static/chat.html) —
    so a client can try the phase-1 agent by typing in a browser, no
    Python/VS Code/SMS account required.

    Deliberately separate from /webhooks/quo/sms: a real Quo webhook is
    fire-and-forget (the reply goes out via a separate outbound SMS call,
    not back in the HTTP response). These endpoints exist purely so the
    browser demo can show a reply inline without polling — mixing that into
    the real webhook route would make its contract dishonest.
    """
    router = APIRouter(prefix="/demo", tags=["demo"])

    @router.get("")
    async def demo_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "chat.html")

    @router.post("/chat")
    async def demo_chat(request: Request) -> dict:
        payload = await request.json()
        result = agent.invoke({"phone": payload["phone"], "inbound_body": payload["body"]})
        return {"reply": result.get("outbound_body", "")}

    @router.get("/lead/{phone}")
    async def demo_lead(phone: str) -> dict:
        return crm_client.get_or_create_lead(phone).model_dump(mode="json")

    @router.get("/history/{phone}")
    async def demo_history(phone: str) -> list[dict]:
        return [m.model_dump(mode="json") for m in log_store.load(phone).messages]

    return router
