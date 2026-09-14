from __future__ import annotations

from datetime import datetime, timezone

import anthropic

from app.batch.prompts import LEAD_STATUS_GUIDE
from app.config import Settings
from app.integrations.monday.base import CrmClient
from app.logging_.conversation_log import ConversationLogStore
from app.logging_.triage_store import TriageStore
from app.models.conversation import Message
from app.models.triage import QcResult

QC_SYSTEM_PROMPT = (
    "You are quality-checking a nightly lead-triage classification for a "
    "leasing office. You'll see the full raw conversation and the status "
    "triage assigned. Your only job is to check triage's classification "
    "against what's actually in the conversation — not to suggest what "
    "should happen next with the lead. Raise a finding only when: triage's "
    "status is wrong given the status definitions below, its summary states "
    "something not actually said, or it missed a detail that changes the "
    "classification (e.g. the prospect disqualified themselves, or gave a "
    "name/unit interest triage didn't capture). Do NOT raise a finding just "
    "because a lead hasn't progressed further yet (no tour scheduled, no "
    "reply sent, no follow-up) — that's the normal, expected state of an "
    "early-stage lead and is a separate follow-up process's job, not "
    "something wrong with today's classification. Only set corrected_status "
    "when you're confident it's wrong; otherwise leave it null.\n\n" + LEAD_STATUS_GUIDE
)

# Below this, a disagreement with triage gets flagged for a human instead of
# auto-applied — cheap insurance against QC itself being wrong.
AUTO_CORRECT_CONFIDENCE = 0.8


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
    log_store: ConversationLogStore,
    triage_store: TriageStore,
) -> list[QcResult]:
    """Reviews every triage record not yet QC'd (qc_reviewed_at is None)."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    results: list[QcResult] = []

    for lead_id in triage_store.list_lead_ids():
        record = triage_store.load(lead_id)
        if record is None or record.qc_reviewed_at is not None:
            continue

        transcript = _format_transcript(log_store.load(lead_id).messages)
        prompt = (
            f"Transcript:\n\n{transcript}\n\n"
            f"Triage classified this lead as: {record.result.status.value}\n"
            f"Triage's summary: {record.result.summary}\n"
            f"Triage's confidence: {record.result.confidence:.2f}"
        )

        try:
            response = client.messages.parse(
                model=settings.anthropic_model,
                max_tokens=2048,
                system=QC_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                output_format=QcResult,
            )
        except anthropic.APIStatusError as exc:
            print(f"[qc] skipping {lead_id}: Anthropic API error ({exc.status_code}): {exc.message}")
            continue

        result = response.parsed_output
        lead = crm.get_or_create_lead(lead_id)
        actionable = [f for f in result.findings if f.severity in ("warning", "error")]
        info_only = [f for f in result.findings if f.severity == "info"]
        can_auto_correct = (
            not result.triage_status_correct
            and result.corrected_status is not None
            and result.confidence >= AUTO_CORRECT_CONFIDENCE
        )

        if can_auto_correct:
            crm.update_lead(
                lead_id,
                status=result.corrected_status,
                notes=lead.notes
                + [f"QC corrected status {record.result.status.value} -> {result.corrected_status.value}: {result.reasoning}"],
                needs_review=bool(actionable),
                review_notes=lead.review_notes + [f"QC: {f.issue}" for f in actionable],
            )
            print(
                f"[qc] {lead_id}: corrected status {record.result.status.value} -> "
                f"{result.corrected_status.value} (confidence {result.confidence:.2f})"
            )
        elif actionable or not result.triage_status_correct:
            notes = [f"QC: {f.issue}" for f in actionable]
            if not result.triage_status_correct:
                notes.append(
                    f"QC disagrees with triage's status ({record.result.status.value}) but "
                    f"isn't confident enough to auto-correct: {result.reasoning}"
                )
            crm.update_lead(lead_id, needs_review=True, review_notes=lead.review_notes + notes)
            print(f"[qc] {lead_id}: flagged for review — {len(notes)} note(s)")
        else:
            if info_only:
                crm.update_lead(lead_id, notes=lead.notes + [f"QC note: {f.issue}" for f in info_only])
            print(f"[qc] {lead_id}: triage looks correct (confidence {result.confidence:.2f})")

        record.qc_reviewed_at = datetime.now(timezone.utc)
        triage_store.save(record)
        results.append(result)

    return results
