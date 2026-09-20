from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.integrations.monday.base import CrmClient
from app.logging_.conversation_log import ConversationLogStore

STATIC_DIR = Path(__file__).parent / "static"

# The demo is public, so its inputs are bounded: phone numbers become log file
# names and CRM keys, and every message costs a Claude call.
PHONE_RE = re.compile(r"\+[0-9]{7,15}")
MAX_MESSAGE_CHARS = 500


def _valid_phone(phone: object) -> str:
    phone = str(phone or "")
    if not PHONE_RE.fullmatch(phone):
        raise HTTPException(status_code=400, detail="phone must look like +15551234567")
    return phone


def build_demo_router(
    agent: Any,
    crm_client: CrmClient,
    log_store: ConversationLogStore,
    crm_backend: str = "stub",
) -> APIRouter:
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
        # no-cache: browsers must revalidate, so a redeploy is never hidden behind a stale copy.
        return FileResponse(STATIC_DIR / "chat.html", headers={"Cache-Control": "no-cache"})

    @router.get("/config")
    async def demo_config() -> dict:
        """Lets the page say honestly whether the CRM panel is a live Monday
        board or the local simulation."""
        return {"crm_backend": crm_backend}

    @router.post("/chat")
    async def demo_chat(request: Request) -> dict:
        payload = await request.json()
        phone = _valid_phone(payload.get("phone"))
        body = str(payload.get("body") or "").strip()
        if not body:
            raise HTTPException(status_code=400, detail="body is required")
        if len(body) > MAX_MESSAGE_CHARS:
            raise HTTPException(status_code=400, detail=f"message is longer than {MAX_MESSAGE_CHARS} characters")

        started = time.perf_counter()
        result = await run_in_threadpool(agent.invoke, {"phone": phone, "inbound_body": body})
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        # What the agent used for this reply (FAQ sources, tool calls), plus the
        # lead as it stands now — so the page can show both without extra calls.
        messages = log_store.load(phone).messages
        last = messages[-1] if messages and messages[-1].direction == "outbound" else None
        return {
            "reply": result.get("outbound_body", ""),
            "meta": last.ai_meta if last else None,
            "lead": crm_client.get_or_create_lead(phone).model_dump(mode="json"),
            "elapsed_ms": elapsed_ms,
        }

    @router.get("/lead/{phone}")
    async def demo_lead(phone: str) -> dict:
        return crm_client.get_or_create_lead(_valid_phone(phone)).model_dump(mode="json")

    @router.get("/history/{phone}")
    async def demo_history(phone: str) -> list[dict]:
        return [m.model_dump(mode="json") for m in log_store.load(_valid_phone(phone)).messages]

    return router
