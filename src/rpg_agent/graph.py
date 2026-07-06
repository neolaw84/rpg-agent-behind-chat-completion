"""LangGraph agent for the RPG proxy.

Implements a 2-node graph:

    LLM Node  ──(tool calls?)──►  Tool Node  ──►  LLM Node  (repeat)
                   │ (no)
                   ▼
                 END

Tools exposed to the LLM:
  - ``execute_code_sandbox`` — runs LLM-generated Python against the current
    turn's RPG state dict.
  - ``roll_xdy``             — simulates rolling NdM dice.
  - ``random_int``           — generates a random integer in [min, max].

Uses direct OpenRouter HTTP requests to stream reasoning_content and content.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Annotated, Any, Sequence

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from rpg_agent.sandbox import execute_sandbox

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schemas for direct OpenRouter invocation
# ---------------------------------------------------------------------------

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "execute_code_sandbox",
            "description": (
                "Execute a Python code snippet to read or modify the current RPG state. "
                "The variable `state` (a dict) is available for reading and updating. "
                "Returns the stdout of the code execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The Python code snippet to run."
                    }
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "roll_xdy",
            "description": (
                "Roll num_dice dice each with num_sides sides and return the results. "
                "For example, roll_xdy(3, 6) simulates 3d6. "
                "Returns a string describing the rolls and the sum."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "num_dice": {
                        "type": "integer",
                        "description": "Number of dice to roll."
                    },
                    "num_sides": {
                        "type": "integer",
                        "description": "Number of sides on each die."
                    }
                },
                "required": ["num_dice", "num_sides"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "random_int",
            "description": "Return a random integer N such that min_val <= N <= max_val.",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_val": {
                        "type": "integer",
                        "description": "Minimum value (inclusive)."
                    },
                    "max_val": {
                        "type": "integer",
                        "description": "Maximum value (inclusive)."
                    }
                },
                "required": ["min_val", "max_val"]
            }
        }
    }
]


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
# Tool factory  (tools are closures so they can capture rpg_state by reference)
# ---------------------------------------------------------------------------

def _make_tools(state_container: dict[str, Any], sandbox_timeout: float):
    """Return a list of LangChain tools that share ``state_container`` by
    reference so that every tool call sees the latest state.
    """

    @tool
    def execute_code_sandbox(code: str) -> str:
        """Execute a Python code snippet to read or modify the current RPG state."""
        updated, output = execute_sandbox(code, state_container["rpg_state"], sandbox_timeout)
        state_container["rpg_state"] = updated
        logger.info("Sandbox executed. Output:\n%s", output or "<no output>")
        return output or "(no output)"

    @tool
    def roll_xdy(num_dice: int, num_sides: int) -> str:
        """Roll num_dice dice each with num_sides sides and return the results."""
        rolls = [random.randint(1, num_sides) for _ in range(num_dice)]
        total = sum(rolls)
        result = f"Rolled {num_dice}d{num_sides}: {rolls} = {total}"
        logger.info("Dice roll: %s", result)
        return result

    @tool
    def random_int(min_val: int, max_val: int) -> int:
        """Return a random integer N such that min_val <= N <= max_val."""
        return random.randint(min_val, max_val)

    return [execute_code_sandbox, roll_xdy, random_int]


# ---------------------------------------------------------------------------
# Message converter helper
# ---------------------------------------------------------------------------

def _convert_to_openai_messages(messages: Sequence[BaseMessage]) -> list[dict]:
    openai_msgs = []
    for m in messages:
        if isinstance(m, SystemMessage):
            openai_msgs.append({"role": "system", "content": m.content})
        elif isinstance(m, AIMessage):
            msg = {"role": "assistant"}
            if m.content:
                msg["content"] = m.content
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"])
                        }
                    }
                    for tc in m.tool_calls
                ]
            rc = m.additional_kwargs.get("reasoning_content")
            if rc:
                msg["reasoning_content"] = rc
            openai_msgs.append(msg)
        elif isinstance(m, ToolMessage):
            openai_msgs.append({
                "role": "tool",
                "tool_call_id": m.tool_call_id,
                "name": m.name,
                "content": m.content
            })
        else:
            openai_msgs.append({"role": "user", "content": m.content})
    return openai_msgs


# ---------------------------------------------------------------------------
# Custom HTTP Client for streaming reasoning_content and content
# ---------------------------------------------------------------------------

async def _call_openrouter_streaming(
    api_key: str,
    base_url: str,
    model: str,
    openai_messages: list[dict],
    stream_queue: asyncio.Queue | None,
) -> tuple[str, str, list[dict]]:
    """Call OpenRouter, streaming reasoning/content chunks to stream_queue if present."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "RPG Agent Proxy",
    }
    payload = {
        "model": model,
        "messages": openai_messages,
        "tools": TOOLS_SCHEMA,
        "stream": stream_queue is not None,
    }
    # Request reasoning explicitly if the provider/model supports it
    payload["extra_body"] = {"include_reasoning": True}

    if stream_queue is not None:
        final_content = []
        final_reasoning = []
        tool_calls_map = {}

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code >= 400:
                    err = await response.aread()
                    raise RuntimeError(f"OpenRouter error: {response.status_code} - {err.decode()}")
                
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    
                    # 1. Parse reasoning_content
                    rc = delta.get("reasoning_content") or delta.get("reasoning")
                    if rc:
                        final_reasoning.append(rc)
                        await stream_queue.put(("reasoning", rc))
                        
                    # 2. Parse content
                    c = delta.get("content")
                    if c:
                        final_content.append(c)
                        await stream_queue.put(("content", c))
                        
                    # 3. Parse tool_calls
                    tcs = delta.get("tool_calls", [])
                    for tc in tcs:
                        idx = tc.get("index", 0)
                        if idx not in tool_calls_map:
                            tool_calls_map[idx] = {
                                "id": tc.get("id", ""),
                                "name": tc.get("function", {}).get("name", ""),
                                "arguments": ""
                            }
                        if tc.get("id"):
                            tool_calls_map[idx]["id"] = tc["id"]
                        if tc.get("function", {}).get("name"):
                            tool_calls_map[idx]["name"] = tc["function"]["name"]
                        
                        arg_frag = tc.get("function", {}).get("arguments", "")
                        tool_calls_map[idx]["arguments"] += arg_frag

        tc_list = []
        for idx in sorted(tool_calls_map.keys()):
            tc = tool_calls_map[idx]
            tc_list.append({
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"]
                }
            })
        return "".join(final_content), "".join(final_reasoning), tc_list
    else:
        # Non-streaming call
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"OpenRouter error: {response.status_code} - {response.text}")
            
            res_json = response.json()
            msg = res_json["choices"][0]["message"]
            content = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            tcs = msg.get("tool_calls") or []
            return content, reasoning, tcs


# ---------------------------------------------------------------------------
# Node builders
# ---------------------------------------------------------------------------

def _build_llm_node(api_key: str, base_url: str, model: str, max_iterations: int, sandbox_timeout: float):
    """Return the LLM node callable."""
    async def llm_node(state: AgentState, config: RunnableConfig) -> dict:
        stream_queue = config.get("configurable", {}).get("stream_queue")

        # 1. Inject the Dynamic System Instruction warning the LLM about the remaining budget
        rem_iterations = max_iterations - state["iteration_count"]
        system_instruction = (
            "[Proxy System Instruction]\n"
            f"- You have access to a Python code execution sandbox (`execute_code_sandbox`) and dice rolling tools (`roll_xdy`).\n"
            f"- Python sandbox execution has a hard timeout of {sandbox_timeout} seconds.\n"
            f"- You have a strict budget of up to {max_iterations} tool-calling iterations.\n"
            f"- Current Iteration: {state['iteration_count'] + 1} of {max_iterations}.\n"
            f"- Remaining Tool-Calling Budget: {rem_iterations}.\n"
            f"- If you reach iteration {max_iterations}, no further tool calls will be executed. You must formulate your final response based on the state at that point."
        )

        openai_msgs = _convert_to_openai_messages(state["messages"])
        openai_msgs.append({"role": "system", "content": system_instruction})

        # 2. Call OpenRouter
        content, reasoning, tcs = await _call_openrouter_streaming(
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
    tools = _make_tools(state_container, sandbox_timeout)

    graph = StateGraph(AgentState)
    graph.add_node("llm", _build_llm_node(api_key, base_url, model, max_iterations, sandbox_timeout))
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
