from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict

import anthropic
from langgraph.graph import END, START, StateGraph

from app.agent.prompts import build_system_prompt
from app.agent.tools import TOOLS, execute_tool
from app.config import Settings
from app.integrations.monday.base import CrmClient
from app.integrations.quo.base import QuoClient
from app.logging_.conversation_log import ConversationLogStore
from app.rag.store import FaqStore

MAX_TOOL_LOOPS = 4


class AgentState(TypedDict, total=False):
    phone: str
    lead_id: str
    inbound_body: str
    faq_hits: list[dict]
    messages: list[dict[str, Any]]
    stop_reason: str | None
    tool_calls_made: list[dict]
    tool_loop_count: int
    outbound_body: str


def _serialize_content(content: list[Any]) -> list[dict[str, Any]]:
    """Convert Anthropic SDK content blocks into plain dicts so the message
    history is uniform (dicts in, dicts out) regardless of whether a turn
    came from the API or from a tool-result we built ourselves."""
    blocks = []
    for block in content:
        if isinstance(block, dict):
            blocks.append(block)
        elif block.type == "text":
            blocks.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            blocks.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
        else:
            blocks.append(block.model_dump())
    return blocks


def build_graph(
    settings: Settings,
    crm: CrmClient,
    quo: QuoClient,
    faq_store: FaqStore,
    log_store: ConversationLogStore,
):
    """Assemble the phase-1 agent graph:

        load_context -> retrieve_faq -> generate <-> execute_tools -> respond

    `generate` and `execute_tools` loop on each other while Claude keeps
    making tool calls, then fall through to `respond` once it returns a
    plain-text answer (or the loop safety valve trips).
    """
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def load_context(state: AgentState) -> AgentState:
        lead = crm.get_or_create_lead(state["phone"])
        state["lead_id"] = lead.id

        history = log_store.load(lead.id)
        messages: list[dict[str, Any]] = []
        for msg in history.messages[-10:]:  # last 10 turns is plenty of context for a demo
            role = "user" if msg.direction == "inbound" else "assistant"
            messages.append({"role": role, "content": msg.body})
        messages.append({"role": "user", "content": state["inbound_body"]})

        state["messages"] = messages
        state["tool_calls_made"] = []
        state["tool_loop_count"] = 0
        return state

    def retrieve_faq(state: AgentState) -> AgentState:
        state["faq_hits"] = faq_store.retrieve(state["inbound_body"], k=3)
        return state

    def generate(state: AgentState) -> AgentState:
        lead = crm.get_or_create_lead(state["phone"])
        system = build_system_prompt(lead, state.get("faq_hits", []))

        try:
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=2048,
                system=system,
                tools=TOOLS,
                # This is a latency-sensitive chat reply, not a hard reasoning
                # task, so keep thinking effort low rather than the default.
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
                messages=state["messages"],
            )
        except anthropic.AuthenticationError as exc:
            raise RuntimeError("Anthropic API key is missing or invalid — check ANTHROPIC_API_KEY in .env") from exc
        except anthropic.RateLimitError as exc:
            raise RuntimeError("Anthropic API rate limit hit — wait a moment and retry") from exc
        except anthropic.APIStatusError as exc:
            raise RuntimeError(f"Anthropic API error ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise RuntimeError("Could not reach the Anthropic API — check your network connection") from exc

        state["messages"].append({"role": "assistant", "content": _serialize_content(response.content)})
        state["stop_reason"] = response.stop_reason

        if response.stop_reason != "tool_use":
            state["outbound_body"] = "".join(
                block.text for block in response.content if block.type == "text"
            ).strip()
        return state

    def execute_tools(state: AgentState) -> AgentState:
        last_content = state["messages"][-1]["content"]
        tool_results = []
        for block in last_content:
            if block["type"] == "tool_use":
                is_error = False
                try:
                    result_text = execute_tool(block["name"], block["input"], crm, state["lead_id"])
                except Exception as exc:  # noqa: BLE001 - deliberately broad: any tool
                    # failure becomes a tool_result the model can see and react to
                    # (e.g. retry with a corrected argument) instead of a 500.
                    result_text = f"Error: {exc}"
                    is_error = True
                state["tool_calls_made"].append(
                    {"name": block["name"], "input": block["input"], "result": result_text, "error": is_error}
                )
                tool_result: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": result_text,
                }
                if is_error:
                    tool_result["is_error"] = True
                tool_results.append(tool_result)
        state["messages"].append({"role": "user", "content": tool_results})
        state["tool_loop_count"] = state.get("tool_loop_count", 0) + 1
        return state

    def respond(state: AgentState) -> AgentState:
        quo.send_sms(state["phone"], state["outbound_body"])
        # Automated follow-up (phase 2) times its nudges off this field, so
        # every real exchange — not just the ones that call a CRM tool —
        # needs to count as "contact".
        crm.update_lead(state["lead_id"], last_contact_at=datetime.now(timezone.utc))
        log_store.append_turn(
            lead_id=state["lead_id"],
            inbound_body=state["inbound_body"],
            outbound_body=state["outbound_body"],
            ai_meta={
                "faq_sources": [h["source"] for h in state.get("faq_hits", [])],
                "tool_calls": state.get("tool_calls_made", []),
            },
        )
        return state

    def route_after_generate(state: AgentState) -> str:
        if state.get("stop_reason") == "tool_use":
            if state.get("tool_loop_count", 0) < MAX_TOOL_LOOPS:
                return "execute_tools"
            # Safety valve: stop looping rather than call Claude forever.
            state["outbound_body"] = (
                state.get("outbound_body")
                or "Let me check on that and get back to you from our leasing office."
            )
        return "respond"

    graph = StateGraph(AgentState)
    graph.add_node("load_context", load_context)
    graph.add_node("retrieve_faq", retrieve_faq)
    graph.add_node("generate", generate)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("respond", respond)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "retrieve_faq")
    graph.add_edge("retrieve_faq", "generate")
    graph.add_conditional_edges(
        "generate", route_after_generate, {"execute_tools": "execute_tools", "respond": "respond"}
    )
    graph.add_edge("execute_tools", "generate")
    graph.add_edge("respond", END)

    return graph.compile()
