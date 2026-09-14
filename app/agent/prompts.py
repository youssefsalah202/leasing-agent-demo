from __future__ import annotations

from datetime import datetime, timezone

from app.models.lead import Lead

PERSONA = (
    "You are Riley, an SMS leasing assistant for Maple Grove Apartments. "
    "You help prospective renters get their questions answered and book tours. "
    "Keep replies short and text-message-appropriate (2-4 sentences, no markdown, "
    "no bullet points). Only answer housing questions using the FAQ context "
    "provided below — if the context doesn't cover something, say you'll check "
    "with the leasing office rather than guessing. Only call book_tour once the "
    "prospect has confirmed a specific date and time — resolve relative dates "
    "(\"Tuesday\", \"tomorrow\", \"next week\") against today's date below, and "
    "always pass scheduled_for with the correct year. Use update_crm_field to "
    "record their name or unit interest when they mention it."
)


def build_system_prompt(lead: Lead, faq_hits: list[dict]) -> str:
    # The model has no other way to know "today" — without this, relative
    # dates ("Tuesday", "this week") get resolved against its training data
    # instead of the real calendar, which can silently book a tour a year off.
    today = datetime.now(timezone.utc).strftime("%A, %Y-%m-%d")
    lead_block = (
        f"Today's date: {today}\n\n"
        "Prospect record:\n"
        f"- phone: {lead.phone}\n"
        f"- name: {lead.name or 'unknown'}\n"
        f"- status: {lead.status.value}\n"
        f"- unit_interest: {lead.unit_interest or 'unknown'}\n"
        f"- existing tour: {lead.tour.model_dump() if lead.tour else 'none'}\n"
    )
    if faq_hits:
        faq_block = "Relevant FAQ context:\n" + "\n".join(
            f"[{h['source']}] {h['text']}" for h in faq_hits
        )
    else:
        faq_block = "No FAQ context matched this message."
    return f"{PERSONA}\n\n{lead_block}\n{faq_block}"
