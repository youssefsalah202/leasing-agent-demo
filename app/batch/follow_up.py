from __future__ import annotations

from datetime import datetime, timedelta, timezone

import anthropic

from app.config import Settings
from app.integrations.monday.base import CrmClient
from app.integrations.quo.base import QuoClient
from app.logging_.conversation_log import ConversationLogStore
from app.models.conversation import Message
from app.models.lead import Lead, LeadStatus

# Leads in these statuses are mid-funnel and can stall without a nudge.
# Deliberately excludes TOUR_SCHEDULED (they have an appointment — a generic
# "still interested?" nudge would be a worse experience than no message) and
# the funnel-terminal statuses (LEASED, LOST, NOT_A_LEAD).
FOLLOW_UP_ELIGIBLE_STATUSES = {
    LeadStatus.NEW,
    LeadStatus.CONTACTED,
    LeadStatus.QUALIFIED,
    LeadStatus.TOURED,
    LeadStatus.APPLIED,
    LeadStatus.UNRESPONSIVE,
}

FOLLOW_UP_SYSTEM_PROMPT = (
    "You are Riley, an SMS leasing assistant for Maple Grove Apartments, "
    "sending a proactive follow-up text to a prospect who hasn't heard from "
    "us in a while. Write ONE short, warm, specific text (2-3 sentences, no "
    "markdown, no bullet points) that references what they actually said "
    "before — never send a generic 'just checking in'. Give them an easy "
    "next step (reply with a question, or book a tour). Don't re-ask "
    "something they already answered, and don't invent details about the "
    "property that aren't in the conversation."
)


def _is_due(lead: Lead, now: datetime, after: timedelta) -> bool:
    if lead.status not in FOLLOW_UP_ELIGIBLE_STATUSES:
        return False
    if lead.next_follow_up_at is not None and now < lead.next_follow_up_at:
        return False
    if lead.last_contact_at is None:
        return True
    return now - lead.last_contact_at >= after


def _build_message(client: anthropic.Anthropic, settings: Settings, lead: Lead, log_store: ConversationLogStore) -> str:
    history = log_store.load(lead.id).messages[-10:]
    transcript = "\n".join(
        f"{'Prospect' if m.direction == 'inbound' else 'Agent'}: {m.body}" for m in history
    )
    lead_block = (
        f"Prospect: {lead.name or 'unknown name'}, status={lead.status.value}, "
        f"unit_interest={lead.unit_interest or 'unknown'}."
    )
    user_content = (
        f"{lead_block}\n\nConversation so far:\n{transcript or '(no prior messages)'}\n\n"
        "Write the follow-up text."
    )

    try:
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=512,
            system=FOLLOW_UP_SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": user_content}],
        )
    except anthropic.AuthenticationError as exc:
        raise RuntimeError("Anthropic API key is missing or invalid — check ANTHROPIC_API_KEY in .env") from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError("Anthropic API rate limit hit — wait a moment and retry") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Anthropic API error ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError("Could not reach the Anthropic API — check your network connection") from exc

    return "".join(block.text for block in response.content if block.type == "text").strip()


def run(
    settings: Settings,
    crm: CrmClient,
    quo: QuoClient,
    log_store: ConversationLogStore,
    after: timedelta | None = None,
) -> list[dict]:
    """Sends a follow-up to every eligible lead due for one. `after`
    overrides settings.follow_up_after_hours — mainly so tests don't have to
    wait real hours to exercise this."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    now = datetime.now(timezone.utc)
    after = after if after is not None else timedelta(hours=settings.follow_up_after_hours)

    sent: list[dict] = []
    for lead in crm.list_leads():
        if not _is_due(lead, now, after):
            continue

        try:
            body = _build_message(client, settings, lead, log_store)
        except RuntimeError as exc:
            print(f"[follow_up] skipping {lead.id}: {exc}")
            continue

        quo.send_sms(lead.phone, body)
        log_store.append_message(
            lead.id,
            Message(direction="outbound", body=body, ai_meta={"automated_follow_up": True}),
        )

        updates: dict = {"last_contact_at": now, "next_follow_up_at": now + after}
        if lead.status == LeadStatus.NEW:
            updates["status"] = LeadStatus.CONTACTED
        crm.update_lead(lead.id, **updates)

        print(f"[follow_up] {lead.id}: {body}")
        sent.append({"lead_id": lead.id, "body": body})

    return sent
