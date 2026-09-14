# Leasing SMS Agent — Phase 1 Demo

A working demo of a live SMS leasing assistant: it receives an inbound text,
looks up the prospect in a CRM, answers housing questions grounded in a small
FAQ knowledge base (RAG), and can book a property tour — writing the booking
back to the CRM and replying over SMS. This is **phase 1** of a larger system;
see [Roadmap](#roadmap--phase-2) below for what comes next.

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
    conversation.py          ConversationLog, Message
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
  logging_/
    conversation_log.py      Append-only JSONL conversation logs
scripts/
  seed_faq_index.py          Rebuild the FAQ vector index manually
  send_test_message.py       CLI to POST a fake inbound SMS to the local server
tests/
  fixtures/                  Scripted test conversations
  test_conversations.py      End-to-end tests (hit the real Claude API)
data/                        Runtime state — CRM JSON, conversation logs, vector index
                              (git-ignored except this structure)
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
| **Quo** (SMS) | 🔶 Stubbed (`app/integrations/quo/stub.py`) | Real webhook payload shape (ours is a documented guess — see the docstring), `QUO_API_KEY`, an outbound-send API call |
| **Monday.com** (CRM) | 🔶 Stubbed (`app/integrations/monday/stub.py`) | `MONDAY_API_TOKEN`, board/column IDs (`MONDAY_BOARD_ID`), GraphQL mutations mapped to `CrmClient`'s three methods |

Both stubs sit behind a `Protocol` interface (`QuoClient`, `CrmClient`) — swap
in a real implementation and nothing else in the app changes, since
`app/main.py` and `app/agent/graph.py` only ever depend on the interface.

## Roadmap / Phase 2

Phase 1 deliberately keeps the data model ready for what's next:

- **`Lead`** already carries `status` (a full lifecycle enum, not just
  free text), `next_follow_up_at` (unused for now), and everything a CRM
  board column would need.
- **`ConversationLog`** already logs `ai_meta` per turn — which FAQ sources
  were used, which tools fired — exactly what a nightly QC pass would need
  to check the agent's work without re-deriving it.

Phase 2 adds, without changing this data model:

1. **Nightly prospect triage** — classify new conversations, update lead
   status in the CRM.
2. **Nightly QC** — review triage output against raw conversations for
   errors or missed info.
3. **Automated follow-up** — message prospects based on status/history/time
   since contact.

## Notes on model choice

Uses `claude-sonnet-5` via the Anthropic API, with adaptive thinking at low
effort — appropriate for a latency-sensitive chat reply rather than a deep
reasoning task. Configurable via `ANTHROPIC_MODEL` in `.env`.
