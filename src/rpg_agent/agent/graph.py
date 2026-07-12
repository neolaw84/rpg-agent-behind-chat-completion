"""LangGraph agent for the RPG proxy.

Implements a multi-node state graph for orchestration.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Sequence, TypedDict
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages

# Expose node builders and helpers from nodes
from rpg_agent.agent.nodes import (
    AgentState,
    _build_llm_node,
    _build_summary_node,
    _build_plan_node,
    _build_tool_node,
    _should_continue,
    _route_start,
    _route_summary_next,
    _convert_messages,
)

# Exported/delegated for test mock compatibility
from rpg_agent.agent.prompts import get_system_instruction

async def call_openrouter_direct(*args, **kwargs):
    from rpg_agent.agent import openrouter
    return await openrouter.call_openrouter_direct(*args, **kwargs)

async def call_openrouter_streaming(*args, **kwargs):
    from rpg_agent.agent import openrouter
    return await openrouter.call_openrouter_streaming(*args, **kwargs)

from rpg_agent.agent.tools import make_tools

def build_graph(
    api_key: str,
    base_url: str,
    model: str,
    state_container: dict[str, Any],
    sandbox_timeout: float,
    max_iterations: int,
):
    """Compile and return the LangGraph agent graph."""
    tools = make_tools(state_container, sandbox_timeout)

    graph = StateGraph(AgentState)  # type: ignore[arg-type]
    graph.add_node("summary", _build_summary_node(api_key, state_container))
    graph.add_node("plan", _build_plan_node(api_key, state_container))
    graph.add_node("llm", _build_llm_node(api_key, base_url, model, max_iterations, sandbox_timeout, state_container))
    graph.add_node("tools", _build_tool_node(tools))

    graph.set_conditional_entry_point(_route_start, {
        "summary": "summary",
        "plan": "plan",
        "llm": "llm",
    })

    graph.add_conditional_edges("summary", _route_summary_next, {
        "plan": "plan",
        "llm": "llm",
    })

    graph.add_edge("plan", "llm")
    graph.add_conditional_edges("llm", _should_continue(max_iterations))
    graph.add_edge("tools", "llm")

    return graph.compile()

async def run_agent(
    messages: list[dict],
    before_state: dict[str, Any],
    api_key: str,
    base_url: str,
    model: str,
    sandbox_timeout: float = 2.0,
    max_iterations: int = 5,
    stream_queue: asyncio.Queue | None = None,
) -> dict[str, Any]:
    """Run the LangGraph agent for one proxy turn."""
    turn_number = sum(1 for m in messages if m.get("role") == "assistant") + 1
    state_container: dict[str, Any] = {
        "rpg_state": dict(before_state),
        "current_turn": turn_number,
    }

    compiled = build_graph(
        api_key=api_key,
        base_url=base_url,
        model=model,
        state_container=state_container,
        sandbox_timeout=sandbox_timeout,
        max_iterations=max_iterations,
    )

    initial_state: AgentState = {
        "messages": _convert_messages(messages),
        "rpg_state": state_container["rpg_state"],
        "sandbox_timeout": sandbox_timeout,
        "iteration_count": 0,
    }

    # 1. Decoupled trigger calculations for plan and summary
    from rpg_agent.config import (
        PLAN_TRIGGER_TYPE,
        PLAN_INTERVAL_TURNS,
        PLAN_TRIGGER_PROBABILITY,
        PLAN_BUNDLE_LLM,
        SUMMARY_TRIGGER_TYPE,
        SUMMARY_INTERVAL_TURNS,
        SUMMARY_TRIGGER_PROBABILITY,
        SUMMARY_BUNDLE_LLM,
        PLAN_SUMMARY_GAP,
    )
    import hashlib
    import random

    # Plan Trigger
    if PLAN_TRIGGER_TYPE == "disabled":
        plan_fired = False
    elif turn_number == 1:
        plan_fired = True
    elif PLAN_TRIGGER_TYPE == "probabilistic":
        msg_contents = [m.get("content") or "" for m in messages]
        seed = int(hashlib.sha256("\x00".join(msg_contents).encode("utf-8")).hexdigest(), 16)
        seed_plan = seed ^ 0xAAAA_AAAA
        rng = random.Random(seed_plan)
        plan_fired = rng.random() < PLAN_TRIGGER_PROBABILITY
    else:
        plan_fired = (turn_number % PLAN_INTERVAL_TURNS == 0)

    # Summary Trigger
    if SUMMARY_TRIGGER_TYPE == "disabled":
        summary_fired = False
    elif SUMMARY_TRIGGER_TYPE == "probabilistic":
        msg_contents = [m.get("content") or "" for m in messages]
        seed = int(hashlib.sha256("\x00".join(msg_contents).encode("utf-8")).hexdigest(), 16)
        seed_summary = seed ^ 0x5555_5555
        rng = random.Random(seed_summary)
        summary_fired = rng.random() < SUMMARY_TRIGGER_PROBABILITY
    else:
        summary_fired = ((turn_number + PLAN_SUMMARY_GAP) % SUMMARY_INTERVAL_TURNS == 0)

    config: RunnableConfig = {"recursion_limit": max_iterations * 2 + 10}
    config["configurable"] = {
        "plan_fired": plan_fired,
        "summary_fired": summary_fired,
        "plan_bundle": PLAN_BUNDLE_LLM,
        "summary_bundle": SUMMARY_BUNDLE_LLM,
        "bundle_plan_fired": plan_fired and PLAN_BUNDLE_LLM,
        "bundle_summary_fired": summary_fired and SUMMARY_BUNDLE_LLM,
    }
    if stream_queue is not None:
        config["configurable"]["stream_queue"] = stream_queue

    final_state = await compiled.ainvoke(initial_state, config=config)

    # Extract final AIMessage details
    final_content = ""
    final_reasoning = ""
    for msg in reversed(final_state["messages"]):
        if isinstance(msg, AIMessage):
            content = msg.content or ""
            if not isinstance(content, str):
                content = str(content)
            final_content = content
            final_reasoning = msg.additional_kwargs.get("reasoning_content") or ""
            break

    return {
        "content": final_content,
        "reasoning_content": final_reasoning,
        "after_state": state_container["rpg_state"],
    }
