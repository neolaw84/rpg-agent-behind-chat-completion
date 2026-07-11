"""LangGraph agent for the RPG proxy.

Implements a 2-node graph:

    LLM Node  ──(tool calls?)──►  Tool Node  ──►  LLM Node  (repeat)
                   │ (no)
                   ▼
                 END

Uses direct OpenRouter HTTP requests to stream reasoning_content and content.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from rpg_agent.agent.prompts import get_system_instruction
from rpg_agent.agent.tools import make_tools
from rpg_agent.agent.openrouter import convert_to_openai_messages, call_openrouter_streaming
from rpg_agent.sandbox.sandbox import get_sandbox_engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LangGraph state definition
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    # Mutable RPG state dict for this turn (modified in-place by tools).
    rpg_state: dict[str, Any]
    # Track sandbox timeout for dynamic injection from config.
    sandbox_timeout: float
    # Number of tool-call iterations completed so far.
    iteration_count: int


# ---------------------------------------------------------------------------
# Node builders
# ---------------------------------------------------------------------------

def _build_llm_node(
    api_key: str,
    base_url: str,
    model: str,
    max_iterations: int,
    sandbox_timeout: float,
    state_container: dict[str, Any],
):
    """Return the LLM node callable."""
    async def llm_node(state: AgentState, config: RunnableConfig) -> dict:
        stream_queue = config.get("configurable", {}).get("stream_queue")

        # 1. Inject the Dynamic System Instruction warning the LLM about the remaining budget
        rem_iterations = max_iterations - state["iteration_count"]
        current_rpg_state = state_container.get("rpg_state", {})
        state_str = json.dumps(current_rpg_state, indent=2, ensure_ascii=False)

        system_instruction = get_system_instruction(
            state_str=state_str,
            sandbox_timeout=sandbox_timeout,
            max_iterations=max_iterations,
            current_iteration=state["iteration_count"] + 1,
            rem_iterations=rem_iterations,
            engine_name=get_sandbox_engine().name,
        )

        openai_msgs = convert_to_openai_messages(state["messages"])
        openai_msgs.append({"role": "system", "content": system_instruction})

        # 2. Call OpenRouter
        content, reasoning, tcs = await call_openrouter_streaming(
            api_key=api_key,
            base_url=base_url,
            model=model,
            openai_messages=openai_msgs,
            stream_queue=stream_queue,
        )

        # Convert tool calls to LangChain format
        lc_tool_calls = []
        for tc in tcs:
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}
            lc_tool_calls.append({
                "name": tc["function"]["name"],
                "args": args,
                "id": tc["id"],
                "type": "tool_call"
            })

        ai_msg = AIMessage(
            content=content,
            tool_calls=lc_tool_calls,
            additional_kwargs={"reasoning_content": reasoning} if reasoning else {}
        )

        return {
            "messages": [ai_msg],
            "iteration_count": state["iteration_count"] + 1,
        }
    return llm_node


def _build_tool_node(tools: list):
    """Return the Tool node callable."""
    tool_map = {t.name: t for t in tools}

    async def tool_node(state: AgentState, config: RunnableConfig) -> dict:
        stream_queue = config.get("configurable", {}).get("stream_queue")
        last_message = state["messages"][-1]
        tool_results: list[ToolMessage] = []

        for call in last_message.tool_calls:
            tool_fn = tool_map.get(call["name"])
            if tool_fn is None:
                result = f"[Unknown tool: {call['name']}]"
                if stream_queue:
                    await stream_queue.put(("tool_log", f"\n[Unknown tool call: {call['name']}]\n"))
            else:
                args_str = json.dumps(call["args"], ensure_ascii=False)
                if stream_queue:
                    await stream_queue.put((
                        "tool_log",
                        f"\n[Calling tool: {call['name']} with args: {args_str}]\n"
                    ))
                result = await tool_fn.ainvoke(call["args"])
                if stream_queue:
                    await stream_queue.put((
                        "tool_log",
                        f"[Output]: {result}\n"
                    ))
            tool_results.append(
                ToolMessage(content=str(result), tool_call_id=call["id"], name=call["name"])
            )
        return {"messages": tool_results}

    return tool_node


def _should_continue(max_iterations: int):
    """Return the conditional edge function."""
    def _edge(state: AgentState) -> str:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage):
            return "llm"
        has_tool_calls = bool(getattr(last, "tool_calls", None))
        over_limit = state["iteration_count"] >= max_iterations
        if has_tool_calls and not over_limit:
            return "tools"
        return END
    return _edge


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

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

    graph = StateGraph(AgentState)
    graph.add_node("llm", _build_llm_node(api_key, base_url, model, max_iterations, sandbox_timeout, state_container))
    graph.add_node("tools", _build_tool_node(tools))

    graph.set_entry_point("llm")
    graph.add_conditional_edges("llm", _should_continue(max_iterations))
    graph.add_edge("tools", "llm")

    return graph.compile()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _convert_messages(openai_messages: list[dict]) -> list[BaseMessage]:
    """Convert OpenAI-format message dicts to LangChain BaseMessage objects."""
    lc_messages: list[BaseMessage] = []
    for m in openai_messages:
        role = m.get("role", "system")
        content = m.get("content") or ""
        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        elif role == "assistant":
            # Reconstruct reasoning content if present in history
            additional = {}
            if "reasoning_content" in m:
                additional["reasoning_content"] = m["reasoning_content"]
            lc_messages.append(AIMessage(content=content, additional_kwargs=additional))
        else:
            lc_messages.append(HumanMessage(content=content))
    return lc_messages


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
    state_container: dict[str, Any] = {"rpg_state": dict(before_state)}

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

    config = {"recursion_limit": max_iterations * 2 + 4}
    if stream_queue is not None:
        config["configurable"] = {"stream_queue": stream_queue}

    final_state = await compiled.ainvoke(initial_state, config=config)

    # Extract final AIMessage details
    final_content = ""
    final_reasoning = ""
    for msg in reversed(final_state["messages"]):
        if isinstance(msg, AIMessage):
            final_content = msg.content or ""
            final_reasoning = msg.additional_kwargs.get("reasoning_content") or ""
            break

    return {
        "content": final_content,
        "reasoning_content": final_reasoning,
        "after_state": state_container["rpg_state"],
    }
