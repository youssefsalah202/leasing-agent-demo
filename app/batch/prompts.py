"""Shared prompt fragments for the nightly batch jobs. Triage and QC must
agree on what each status means — otherwise QC ends up "disagreeing" with
triage over semantics rather than actual errors, which is noise, not signal.
"""

from __future__ import annotations

LEAD_STATUS_GUIDE = """Status definitions (use exactly these meanings):
- new: no meaningful conversation yet.
- contacted: prospect engaged (asked questions, requested info) but hasn't given a specific, actionable unit interest and timeline.
- qualified: prospect gave a specific unit type/size AND a timeframe or clear urgency (e.g. a move-in date) — a serious, actionable prospect. Formal income/screening verification is NOT required for this status; that happens later, at "applied".
- tour_scheduled / toured / applied / leased: further down the funnel — only use these if the conversation clearly says a tour was booked/happened, an application was started, or a lease was signed.
- lost: was a genuine prospect who is no longer pursuing (disqualified themselves, chose another property, went quiet after real engagement).
- unresponsive: prospect went quiet after genuine engagement, but didn't explicitly decline (use "lost" if they did).
- not_a_lead: never a genuine leasing prospect at all — wrong number, spam, unrelated call/text. Use this instead of "lost" for these; don't invent a plausible-looking lead out of one."""
