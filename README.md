# Leasing SMS Agent Demo

A working demo of an AI leasing assistant system, built in two phases:

- **Phase 1 — live SMS agent**: receives an inbound text, looks up the
  prospect in a CRM, answers housing questions grounded in a small FAQ
  knowledge base (RAG), and can book a property tour — writing the booking
  back to the CRM and replying over SMS.
- **Phase 2 — nightly triage** (QC and automated follow-up next): classifies
  every lead's SMS *and* phone-call activity since the last run and updates
  the CRM — the only place call transcripts ever get processed, since phase
  1's live agent only handles SMS.

See [Phase 2: nightly batch jobs](#phase-2-nightly-batch-jobs) below for how
triage works, and [Roadmap](#roadmap) for what's still to come.

Quo (SMS) and Monday.com (CRM) are stubbed behind clean interfaces so the
whole thing runs locally with no external accounts except Anthropic's. See
[What's stubbed / what needs real credentials](#whats-stubbed--what-needs-real-credentials).

## How it works

```
inbound SMS (Quo webhook)
        │
        ▼
  load_context ──► look up/create the lead in the CRM, load conversation history
        │
        ▼
  retrieve_faq ──► search the FAQ vector store (Chroma) for relevant context
        │
        ▼
   generate ◄──────────────┐  Claude (Sonnet) decides: answer directly, or
        │                  │  call a tool (book_tour / update_crm_field)
        │ tool call?       │
        ▼ yes              │
  execute_tools ───────────┘  run the tool against the CRM, loop back
        │ no (plain reply)
        ▼
    respond ──► send the SMS reply (Quo), log the full exchange (JSONL)
```

This is a [LangGraph](https://github.com/langchain-ai/langgraph) graph — see
[app/agent/graph.py](app/agent/graph.py). Each box above is a graph node.

## Project layout

```
app/
  main.py                    FastAPI app + the inbound webhook route
  config.py                  Settings (env vars / .env)
  models/
    lead.py                  Lead, LeadStatus, TourSlot
    conversation.py          ConversationLog, Message, CallTranscript
    triage.py                TriageResult, TriageRecord
  integrations/
    quo/        base.py      QuoClient interface   stub.py   StubQuoClient
    monday/     base.py      CrmClient interface    stub.py   StubCrmClient (JSON-backed)
  rag/
    store.py                 Chroma wrapper (seed + retrieve)
    docs/                    Sample FAQ docs (pet policy, parking, amenities, ...)
  agent/
    graph.py                 The LangGraph agent (see diagram above)
    tools.py                 book_tour / update_crm_field tool defs + execution
    prompts.py                System prompt construction
  batch/
    state.py                 Last-run cursor for nightly jobs
    triage.py                Nightly triage job (see Phase 2 below)
  logging_/
    conversation_log.py      Append-only JSONL conversation logs
    triage_store.py          Latest triage output per lead (JSON)
scripts/
  seed_faq_index.py          Rebuild the FAQ vector index manually
  send_test_message.py       CLI to POST a fake inbound SMS to the local server
  run_nightly_triage.py      Run nightly triage
tests/
  fixtures/                  Scripted test conversations
  test_conversations.py      Phase 1 end-to-end tests (hit the real Claude API)
  test_triage.py             Phase 2 triage end-to-end tests
data/                        Runtime state — CRM JSON, conversation/triage logs, vector
                              index, stub call transcripts (git-ignored except structure)
```

## Setup

Requires **Python 3.10+**.

```bash
python -m venv .venv
```

Activate it:

```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS/Linux
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Copy the env template and add your Anthropic API key:

```bash
cp .env.example .env
```

Then open `.env` and set `ANTHROPIC_API_KEY=` to your key. Everything else in
`.env` has a working default. **This is the only credential required for
phase 1** — see [What's stubbed](#whats-stubbed--what-needs-real-credentials).

## Running the demo

Start the server:

```bash
uvicorn app.main:app --reload --port 8000
```

On first startup it seeds the FAQ vector index (`app/rag/docs/*.md` →
`data/chroma/`) — the first run also downloads a small embedding model
(~80MB, one-time, needs internet access).

In another terminal, send a fake inbound SMS:

```bash
python scripts/send_test_message.py --body "Do you allow pets? What's parking like?"
```

Watch the server's console — you'll see the CRM lookup, the retrieved FAQ
chunks' sources, and the outbound reply, e.g.:

```
[StubCrmClient] created new lead +15551234567
[StubQuoClient] -> +15551234567: We do allow pets! Cats have no breed
restrictions; for dogs we can't accommodate Pit Bulls, Rottweilers,
Doberman Pinschers, or Presa Canarios due to insurance rules...
```

Try a tour-booking flow across two messages from the same number:

```bash
python scripts/send_test_message.py --phone "+15559990000" --body "I'd like to see a 2 bedroom this week"
python scripts/send_test_message.py --phone "+15559990000" --body "Thursday at 2pm works, I'm Alex"
```

Then check the results:

- **CRM record** (mocked Monday board): `data/crm_store.json` — you'll see
  `status: "tour_scheduled"` and a populated `tour` field.
- **Conversation log**: `data/conversations/+15559990000.jsonl` — one JSON
  object per message, with `ai_meta` on each outbound turn recording which
  FAQ sources were used and which tools were called (this is what a future
  nightly QC job would read).

## Running the tests

```bash
pytest -v -s
```

`tests/test_conversations.py` runs two scripted conversations straight
through the agent graph (no HTTP layer) and checks the outcomes:

1. **FAQ question** → gets a non-empty, retrieval-grounded reply.
2. **Tour request across two turns** → ends with `LeadStatus.TOUR_SCHEDULED`
   and a populated `tour` field on the lead.

These tests **call the real Claude API** (a few small requests, well under a
cent) and are automatically skipped if `ANTHROPIC_API_KEY` isn't set. Each
test run uses an isolated temp directory, so it never touches your `data/`
folder.

## What's stubbed / what needs real credentials

| Integration | Status | What real integration would need |
|---|---|---|
| **Claude API** | ✅ Live | `ANTHROPIC_API_KEY` (required — this is the only thing the demo needs from you) |
| **Quo** (SMS + calls) | 🔶 Stubbed (`app/integrations/quo/stub.py`) | Real webhook payload shape (ours is a documented guess — see the docstring), `QUO_API_KEY`, an outbound-send API call, and a real call-transcript source for `fetch_call_transcripts` (we assume calls arrive already transcribed to text — see `data/stub_calls.json`) |
| **Monday.com** (CRM) | 🔶 Stubbed (`app/integrations/monday/stub.py`) | `MONDAY_API_TOKEN`, board/column IDs (`MONDAY_BOARD_ID`), GraphQL mutations mapped to `CrmClient`'s three methods |

Both stubs sit behind a `Protocol` interface (`QuoClient`, `CrmClient`) — swap
in a real implementation and nothing else in the app changes, since
`app/main.py` and `app/agent/graph.py` only ever depend on the interface.

## Phase 2: nightly batch jobs

### Nightly triage

`python scripts/run_nightly_triage.py` — classifies every lead with new
conversation activity (SMS or call) since the job's last run, and writes the
classification to the CRM.

**Why re-classify SMS the live agent already handled in real time?** Two
reasons: (1) phone calls have no live handler at all — a call never goes
through the SMS agent, so triage is the *only* place call content is ever
processed; (2) it's an unhurried second pass over the *full* conversation
with no latency budget, so it can catch things the live agent's inline
tool-calling might miss.

How it works:

1. Pulls new call transcripts from `QuoClient.fetch_call_transcripts()` and
   appends them into each lead's conversation log as `channel="call"`
   messages — after this, calls and SMS are one uniform timeline.
2. For every lead with a message timestamped since the job's last run,
   builds the full transcript and asks Claude for a structured
   `TriageResult` (status, name, unit interest, a summary, a confidence
   score) via `client.messages.parse()`.
3. Writes the result onto the `Lead` in the CRM, and saves the full
   `TriageResult` to `data/triage/<lead_id>.json` — kept separate from the
   raw conversation log so the (upcoming) QC job can compare "what triage
   concluded" against "what was actually said."

Run it:

```bash
python scripts/run_nightly_triage.py
```

It remembers the last time it ran (`data/batch_state.json`) so re-running it
only processes new activity. To force a specific lookback window instead
(useful for testing), use `--since-hours`:

```bash
python scripts/run_nightly_triage.py --since-hours 24
```

Try it against the two sample calls in `data/stub_calls.json` — a genuine
prospect (asks about a 2BR, gives her name) and a wrong-number call. Triage
correctly classifies the wrong number as `status: lost` rather than
inventing a plausible-looking lead out of it — worth checking after any
prompt change, since it's the easy way for a triage prompt to go wrong.

Test it: `pytest tests/test_triage.py -v -s` (same live-API pattern as
phase 1's tests).

### Data model additions for phase 2 (backward compatible)

- `Message.channel: "sms" | "call"` — a lead's conversation log can now hold
  both SMS turns and call transcripts on one timeline.
- `Lead.needs_review` / `Lead.review_notes` — where the (upcoming) QC job
  flags a triage classification it disagrees with, for a human to check.
- `TriageResult` / `TriageRecord` (`app/models/triage.py`) — the structured
  shape triage asks Claude for, stored via `TriageStore`.

## Roadmap

Still to come, without further data model changes:

1. **Nightly QC** — an independent LLM pass that re-reads each raw
   conversation *and* triage's output, checks them against each other, and
   either corrects low-severity misses or sets `Lead.needs_review` for
   anything ambiguous.
2. **Automated follow-up** — rule-based selection (plain code, not the LLM)
   of leads due for a nudge — active status, `last_contact_at` older than
   `FOLLOW_UP_AFTER_HOURS` — then a Claude-drafted SMS sent via
   `QuoClient.send_sms`.

## Notes on model choice

Uses `claude-sonnet-5` via the Anthropic API, with adaptive thinking at low
effort — appropriate for a latency-sensitive chat reply rather than a deep
reasoning task. Configurable via `ANTHROPIC_MODEL` in `.env`.
