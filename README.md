# Leasing SMS Agent Demo

A working demo of an AI leasing assistant system, built in two phases:

- **Phase 1 — live SMS agent**: receives an inbound text, looks up the
  prospect in a CRM, answers housing questions grounded in a small FAQ
  knowledge base (RAG), and can book a property tour — writing the booking
  back to the CRM and replying over SMS.
- **Phase 2 — nightly batch jobs**: **triage** classifies every lead's SMS
  *and* phone-call activity since the last run and updates the CRM — the
  only place call transcripts ever get processed, since phase 1's live agent
  only handles SMS. **QC** is an independent second pass that checks
  triage's work against the raw conversation and corrects or flags anything
  it got wrong. **Automated follow-up** proactively nudges leads who've gone
  quiet, grounded in their actual conversation history.

All three phase-2 jobs are implemented — see
[Phase 2: nightly batch jobs](#phase-2-nightly-batch-jobs) below for how
each one works. There's also a [browser chat demo](#browser-chat-demo-easiest-way-to-show-someone)
if you just want to see phase 1 working without touching a terminal.

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
    prompts.py               Shared status definitions (triage + QC must agree)
    triage.py                Nightly triage job (see Phase 2 below)
    qc.py                    Nightly QC job (see Phase 2 below)
    follow_up.py             Automated follow-up job (see Phase 2 below)
  logging_/
    conversation_log.py      Append-only JSONL conversation logs
    triage_store.py          Latest triage output per lead (JSON)
  demo/
    api.py                   Demo-only routes behind the browser chat widget
    static/chat.html          The widget itself (vanilla HTML/CSS/JS, no build step)
scripts/
  seed_faq_index.py          Rebuild the FAQ vector index manually
  send_test_message.py       CLI to POST a fake inbound SMS to the local server
  run_nightly_triage.py      Run nightly triage
  run_nightly_qc.py          Run nightly QC
  run_follow_up.py           Run automated follow-up
tests/
  fixtures/                  Scripted test conversations
  test_conversations.py      Phase 1 end-to-end tests (hit the real Claude API)
  test_triage.py             Phase 2 triage end-to-end tests
  test_qc.py                 Phase 2 QC end-to-end tests
  test_follow_up.py          Phase 2 follow-up end-to-end tests
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

### Browser chat demo (easiest way to show someone)

Open **http://127.0.0.1:8000/demo** in a browser while the server is
running. It's a small chat widget — type a message like a prospect texting
in, and a "CRM Record" panel next to the chat updates live as the agent
responds, books a tour, etc. No terminal, Python, or SMS account needed for
whoever you're showing it to; only the server needs to be running (on your
machine, or wherever you deploy it).

It talks to two small demo-only endpoints (`app/demo/api.py`) — not the
real `/webhooks/quo/sms` route. That's deliberate: a real Quo webhook is
fire-and-forget (the reply goes out later via a separate outbound SMS
call), so it has nothing to hand back in its HTTP response. The demo
endpoints exist purely so a browser can show the reply inline without
polling — mixing that convenience into the real webhook would make its
contract dishonest about how Quo actually works.

Each browser tab gets its own demo phone number (stored in
`localStorage`), so refreshing the page keeps the same conversation, and
"Start new conversation" begins a fresh lead.

### Or drive it from the command line

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

## Deploying a live demo (Render, free tier)

For a standing demo link you can send without your laptop running — as
opposed to the local browser demo above, which needs your own server up.

**Why Render:** its free web service tier is genuinely free indefinitely
(no card required to start, per Render's stated policy), unlike Railway,
whose "free" tier in practice is a one-time trial credit followed by a
small monthly credit that doesn't really cover an always-available service.

**The trade-off**: free Render services have no persistent disk. Every
restart (after ~15 min idle, or a redeploy) wipes anything written to disk
at runtime — so `data/crm_store.json` and the conversation logs reset
periodically. For a demo link, that's a reasonable trade, arguably even a
feature (nobody visiting your link sees leftover data from your last demo).
[`render.yaml`](render.yaml) works around the one part of this that would
otherwise hurt the experience: it seeds the FAQ vector index at **build**
time (baked into the deployed image, not written at runtime), so retrieval
stays instant on every cold start instead of re-downloading the embedding
model each time.

**Steps** (the account creation and API key entry have to be you — not
something I can do on your behalf):

1. Push this repo to a GitHub repo you own (ask your assistant to do this
   part with you if you're not sure how — it just needs a repo URL to push
   to).
2. At [render.com](https://render.com), sign up, then **New +** → **Blueprint**
   → connect the GitHub repo. Render reads `render.yaml` and configures the
   service automatically.
3. When prompted for `ANTHROPIC_API_KEY`, paste it directly into Render's
   dashboard — never share it in chat with your assistant, the same rule as
   the local `.env` file.
4. Deploy. First build takes a few minutes (installs dependencies, seeds
   the FAQ index). Once live, your demo is at
   `https://<service-name>.onrender.com/demo`.

The nightly batch jobs (triage/QC/follow-up) aren't deployed as scheduled
jobs on the free tier — they're designed to run via `scripts/run_nightly_*.py`
on a real cron schedule in production, which is a paid Render feature (or
any scheduler). For portfolio purposes, demo those locally or in a
recording rather than expecting them live on the deployed link.

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
correctly classifies the wrong number as `status: not_a_lead` rather than
inventing a plausible-looking lead out of it — worth checking after any
prompt change, since it's the easy way for a triage prompt to go wrong.
(`not_a_lead` is distinct from `lost`, which means a genuine prospect who
didn't convert — see [Data model additions](#data-model-additions-for-phase-2-backward-compatible).)

Test it: `pytest tests/test_triage.py -v -s` (same live-API pattern as
phase 1's tests).

### Nightly QC

`python scripts/run_nightly_qc.py` — an independent LLM pass that re-reads
each raw conversation *and* triage's classification of it, and checks them
against each other.

**Scope matters here more than it looks.** QC's job is strictly "is this
classification accurate," not "what should happen to this lead next" — an
early version flagged perfectly-correct triage results as `needs_review`
just because no tour had been booked yet, which is normal for a fresh lead,
not a triage error. That's the (not-yet-built) follow-up job's territory.
The system prompt in `app/batch/qc.py` is explicit about this boundary.

QC also caught a real gap in the status taxonomy itself: it independently
flagged, twice, that forcing a wrong-number call into `status: lost`
mischaracterizes it as a prospect who dropped out of the funnel. That led to
adding `LeadStatus.NOT_A_LEAD` and a shared status-definitions block
(`app/batch/prompts.py`) that both triage and QC reference — before that,
triage and QC could "disagree" purely over ambiguous status semantics
(e.g. contacted vs. qualified) rather than an actual classification error,
which is noise, not signal.

How it works:

1. Reviews every `TriageRecord` with `qc_reviewed_at` still `None` (a fresh
   triage run always resets this, so a reclassified lead gets re-reviewed
   automatically — no separate cursor needed for QC).
2. Asks Claude for a structured `QcResult`: does it agree with triage's
   status, a confidence score, reasoning, and a list of findings (severity +
   issue + suggested fix).
3. Three outcomes, based on the result:
   - **Agrees** → nothing changes on the lead (an `info`-level finding, if
     any, just gets appended to `Lead.notes` as an FYI).
   - **Disagrees, confidently** (≥ 0.8 confidence) → auto-corrects
     `Lead.status`, with the reasoning logged to `Lead.notes`.
   - **Disagrees, not confidently — or raises a `warning`/`error` finding**
     → sets `Lead.needs_review = True` and appends to `Lead.review_notes`
     for a human to check, rather than silently guessing.

Run it after triage has produced some records:

```bash
python scripts/run_nightly_triage.py
python scripts/run_nightly_qc.py
```

Test it: `pytest tests/test_qc.py -v -s` — one test confirms QC doesn't flag
correctly-triaged leads (the "don't cry wolf" case); the other seeds a
*deliberately wrong* triage result (status `qualified` against a
conversation where the prospect explicitly says they leased elsewhere) and
confirms QC catches it — this is the test that actually proves QC earns its
place instead of just rubber-stamping triage.

### Automated follow-up

`python scripts/run_follow_up.py` — sends a proactive nudge to every lead
who's gone quiet, grounded in what they actually said before (never a
generic "just checking in").

**Selection is plain code, not the LLM** — the LLM only drafts the message
once a lead is already selected. A lead is due for a follow-up when:

- its status is one of `new`, `contacted`, `qualified`, `toured`, `applied`,
  or `unresponsive` (deliberately **excludes** `tour_scheduled` — nudging
  someone who already has an appointment booked would be a worse experience
  than no message — and the funnel-terminal statuses `leased`, `lost`,
  `not_a_lead`), **and**
- `last_contact_at` is more than `FOLLOW_UP_AFTER_HOURS` (default 48) ago,
  or was never set.

**This surfaced a real gap while building it**: `Lead.last_contact_at` was
never actually being *set* anywhere — phase 1's live agent updated specific
fields via tools but never touched it, so every lead's "last contacted"
timestamp would have stayed `null` forever and every lead would look
eternally overdue. Fixed by setting it: in the live agent's `respond` node
after every SMS exchange ([app/agent/graph.py](app/agent/graph.py)), and
when triage ingests a call, backdated to when the call actually happened
(not whenever triage got around to processing it overnight).

After sending, the job sets `last_contact_at = now` and schedules
`next_follow_up_at`, so re-running immediately doesn't double-send — no
separate cursor needed, same self-gating pattern as triage/QC.

Run it (against real elapsed time, or force it for testing):

```bash
python scripts/run_follow_up.py
python scripts/run_follow_up.py --after-hours 1   # force eligibility for a demo
```

Test it: `pytest tests/test_follow_up.py -v -s` — covers a stale eligible
lead getting followed up, a recently-contacted lead being left alone, a
`leased` lead never getting nudged no matter how stale (the exclusion rule
matters more than the inclusion rule here), and no double-send on a second
run.

### Data model additions for phase 2 (backward compatible)

- `Message.channel: "sms" | "call"` — a lead's conversation log can now hold
  both SMS turns and call transcripts on one timeline.
- `Lead.needs_review` / `Lead.review_notes` — where QC flags a triage
  classification it disagrees with, for a human to check.
- `LeadStatus.NOT_A_LEAD` — wrong number/spam/unrelated contact, distinct
  from `LOST` (a genuine prospect who didn't convert).
- `TriageResult` / `TriageRecord` and `QcFinding` / `QcResult`
  (`app/models/triage.py`) — the structured shapes triage and QC ask Claude
  for, stored via `TriageStore`.
- `Lead.last_contact_at` is now actually maintained (see above) —
  previously present in the model but never written to.

## Running the whole nightly pipeline

The three jobs run in this order — triage needs to run before QC has
anything to review, and follow-up's `last_contact_at` check benefits from
triage's call-ingestion having run first:

```bash
python scripts/run_nightly_triage.py
python scripts/run_nightly_qc.py
python scripts/run_follow_up.py
```

A real deployment would wire these up as three separate cron/scheduled-task
entries (not necessarily back-to-back — QC might run an hour after triage
to leave room for a human to intervene first) rather than one combined
script; kept separate here for the same reason.

## Notes on model choice

Uses `claude-sonnet-5` via the Anthropic API, with adaptive thinking at low
effort — appropriate for a latency-sensitive chat reply rather than a deep
reasoning task. Configurable via `ANTHROPIC_MODEL` in `.env`.
