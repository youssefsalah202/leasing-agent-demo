from __future__ import annotations

from datetime import datetime, timezone

import anthropic

from app.batch.prompts import LEAD_STATUS_GUIDE
from app.config import Settings
from app.integrations.monday.base import CrmClient
from app.integrations.quo.base import QuoClient
from app.logging_.conversation_log import ConversationLogStore
from app.logging_.triage_store import TriageStore
from app.models.conversation import Message
from app.models.triage import TriageRecord, TriageResult

TRIAGE_SYSTEM_PROMPT = (
    "You are triaging leasing-office conversations for Maple Grove Apartments. "
    "Given a transcript (SMS and/or a phone call), classify the prospect's "
    "current status, extract their name and unit interest if mentioned, and "
    "write a short summary.\n\n" + LEAD_STATUS_GUIDE
)


def _ingest_new_calls(
    quo: QuoClient, crm: CrmClient, log_store: ConversationLogStore, since: datetime
) -> None:
    """Pull new call transcripts from Quo and append them to each lead's
    conversation log, tagged channel="call" — after this, triage (and later
    QC) can treat calls and SMS as one uniform timeline.

    Idempotent by call_id: fetch_call_transcripts(since) can legitimately
    return the same call twice across runs (e.g. --since-hours overlapping
    a prior window, or a cursor that isn't perfectly exclusive) — skip any
    call_id already present in that lead's log instead of double-logging it.
    """
    for call in quo.fetch_call_transcripts(since):
        lead = crm.get_or_create_lead(call.lead_phone)
        already_logged = {
            m.channel_message_id for m in log_store.load(lead.id).messages if m.channel == "call"
        }
        if call.call_id in already_logged:
            continue
        log_store.append_message(
            lead.id,
            Message(
                direction="inbound",
                body=call.transcript,
                channel="call",
                timestamp=call.occurred_at,
                channel_message_id=call.call_id,
            ),
        )
        print(f"[triage] ingested call {call.call_id} for {lead.id}")


def _format_transcript(messages: list[Message]) -> str:
    lines = []
    for m in messages:
        tag = "CALL" if m.channel == "call" else "SMS"
        who = "Prospect" if m.direction == "inbound" else "Agent"
        lines.append(f"[{tag} {m.timestamp.isoformat()}] {who}: {m.body}")
    return "\n".join(lines)


def run(
    settings: Settings,
    crm: CrmClient,
    quo: QuoClient,
    log_store: ConversationLogStore,
    triage_store: TriageStore,
    since: datetime,
) -> list[TriageRecord]:
    """Triage every lead with conversation activity at or after `since`.
    Returns the TriageRecords produced, for the caller to print/inspect."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    _ingest_new_calls(quo, crm, log_store, since)

    records: list[TriageRecord] = []
    for lead_id in log_store.list_lead_ids():
        log = log_store.load(lead_id)
        new_messages = [m for m in log.messages if m.timestamp >= since]
        if not new_messages:
            continue

        transcript = _format_transcript(log.messages)  # full history for context
        try:
            response = client.messages.parse(
                model=settings.anthropic_model,
                max_tokens=2048,
                system=TRIAGE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"Transcript:\n\n{transcript}"}],
                output_format=TriageResult,
            )
        except anthropic.APIStatusError as exc:
            print(f"[triage] skipping {lead_id}: Anthropic API error ({exc.status_code}): {exc.message}")
            continue

        result = response.parsed_output
        existing = crm.get_or_create_lead(lead_id)
        crm.update_lead(
            lead_id,
            status=result.status,
            unit_interest=result.unit_interest or existing.unit_interest,
            name=result.name or existing.name,
        )

        record = TriageRecord(lead_id=lead_id, result=result)
        triage_store.save(record)
        records.append(record)
        print(f"[triage] {lead_id}: status={result.status.value} confidence={result.confidence:.2f} — {result.summary}")

    return records
