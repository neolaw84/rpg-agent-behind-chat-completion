"""Nodes and conditional routing functions for the LangGraph RPG Agent."""

import json
import logging
from typing import Annotated, Any, Sequence, TypedDict
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from langgraph.graph.message import add_messages

from rpg_agent.agent.prompts import (
    get_system_instruction,
    get_summary_prompt,
    get_plan_prompt,
    get_range_reference,
    middle_out_messages,
)
from rpg_agent.agent.openrouter import convert_to_openai_messages, call_openrouter_streaming, call_openrouter_direct
from rpg_agent.sandbox.sandbox import get_sandbox_engine

logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    rpg_state: dict[str, Any]
    sandbox_timeout: float
    iteration_count: int

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
        bundle_plan_fired = config.get("configurable", {}).get("bundle_plan_fired", False)
        bundle_summary_fired = config.get("configurable", {}).get("bundle_summary_fired", False)

        # Check if the tools have already been invoked in the current turn (since the last user message)
        plan_called = False
        summary_called = False
        last_human_idx = -1
        for idx, msg in enumerate(state["messages"]):
            if isinstance(msg, HumanMessage):
                last_human_idx = idx

        messages_to_scan = state["messages"][last_human_idx + 1:] if last_human_idx != -1 else state["messages"]
        for msg in messages_to_scan:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.get("name") == "update_plan":
                        plan_called = True
                    elif tc.get("name") == "append_summary":
                        summary_called = True

        # Override trigger flags if they have already been executed
        if plan_called:
            bundle_plan_fired = False
        if summary_called:
            bundle_summary_fired = False

        # 1. Inject the Dynamic System Instruction warning the LLM about the remaining budget
        rem_iterations = max_iterations - state["iteration_count"]
        current_rpg_state = state_container.get("rpg_state", {})
        turn_number = sum(1 for m in state["messages"] if isinstance(m, AIMessage)) + 1

        import rpg_agent.agent.graph as graph
        system_instruction = graph.get_system_instruction(
            rpg_state=current_rpg_state,
            sandbox_timeout=sandbox_timeout,
            max_iterations=max_iterations,
            current_iteration=state["iteration_count"] + 1,
            rem_iterations=rem_iterations,
            messages=state["messages"],
            engine_name=get_sandbox_engine().name,
            bundle_plan_fired=bundle_plan_fired,
            bundle_summary_fired=bundle_summary_fired,
            turn_number=turn_number,
        )

        openai_msgs = convert_to_openai_messages(state["messages"])
        openai_msgs.append({"role": "system", "content": system_instruction})

        # 2. Call OpenRouter
        import rpg_agent.agent.graph as graph
        content, reasoning, tcs = await graph.call_openrouter_streaming(
            api_key=api_key,
            base_url=base_url,
            model=model,
            openai_messages=openai_msgs,
            stream_queue=stream_queue,
            include_plan=bundle_plan_fired,
            include_summary=bundle_summary_fired,
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

def _build_summary_node(api_key: str, state_container: dict[str, Any]):
    """Return the Summary node callable."""
    async def summary_node(state: AgentState, config: RunnableConfig) -> dict:
        from rpg_agent.config import (
            SUMMARY_MODEL,
            SUMMARY_BASE_URL,
            SUMMARY_TEMPERATURE,
            SUMMARY_TARGET_WORDS,
        )

        rpg = state_container["rpg_state"]
        current_turn = sum(1 for m in state["messages"] if isinstance(m, AIMessage)) + 1
        hidden = rpg.get("hidden_state", {}) or {}
        last_summary_turn = hidden.get("last_summary_turn", 0)

        if last_summary_turn == 0:
            summary_turns_val = current_turn
            turns_since_update = f"{current_turn} turns ago (at the start of the game)"
        else:
            summary_turns_val = current_turn - last_summary_turn
            turns_since_update = f"{summary_turns_val} turn ago" if summary_turns_val == 1 else f"{summary_turns_val} turns ago"

        range_ref = get_range_reference(state["messages"], summary_turns_val)
        prev_summary = rpg.get("summary", "")
        summary_prompt = get_summary_prompt(
            prev_summary=prev_summary,
            target_words=SUMMARY_TARGET_WORDS,
            turns_since_update=turns_since_update,
            range_ref=range_ref,
            state=rpg.get("state", {}),
            hidden_state=rpg.get("hidden_state", {}),
            is_bundle=False,
        )

        middled_msgs = middle_out_messages(state["messages"], summary_turns_val)
        history_msgs = convert_to_openai_messages(middled_msgs)
        history_msgs.append({"role": "system", "content": summary_prompt})

        try:
            import rpg_agent.agent.graph as graph
            summary_delta = await graph.call_openrouter_direct(
                api_key=api_key,
                base_url=SUMMARY_BASE_URL,
                model=SUMMARY_MODEL,
                openai_messages=history_msgs,
                temperature=SUMMARY_TEMPERATURE,
            )
            summary_delta = summary_delta.strip()
            if summary_delta.startswith('"') and summary_delta.endswith('"'):
                summary_delta = summary_delta[1:-1].strip()
            if prev_summary:
                rpg["summary"] = prev_summary.strip() + "\n\n" + summary_delta
            else:
                rpg["summary"] = summary_delta

            # Record last summary turn
            if "hidden_state" not in rpg or not isinstance(rpg["hidden_state"], dict):
                rpg["hidden_state"] = {}
            rpg["hidden_state"]["last_summary_turn"] = current_turn

            logger.info("Graph Summary node update complete: %s", summary_delta)
        except Exception as exc:
            logger.error("Failed to run summary node update: %s", exc)

        return {"rpg_state": rpg}
    return summary_node

def _build_plan_node(api_key: str, state_container: dict[str, Any]):
    """Return the Plan node callable."""
    async def plan_node(state: AgentState, config: RunnableConfig) -> dict:
        from rpg_agent.config import (
            PLAN_MODEL,
            PLAN_BASE_URL,
            PLAN_TEMPERATURE,
        )

        rpg = state_container["rpg_state"]
        current_turn = sum(1 for m in state["messages"] if isinstance(m, AIMessage)) + 1
        hidden = rpg.get("hidden_state", {}) or {}
        last_plan_turn = hidden.get("last_plan_turn", 0)

        if last_plan_turn == 0:
            plan_turns_val = current_turn
            turns_since_update = f"{current_turn} turns ago (at the start of the game)"
        else:
            plan_turns_val = current_turn - last_plan_turn
            turns_since_update = f"{plan_turns_val} turn ago" if plan_turns_val == 1 else f"{plan_turns_val} turns ago"

        range_ref = get_range_reference(state["messages"], plan_turns_val)
        prev_plan = rpg.get("plan", [])
        plan_prompt = get_plan_prompt(
            prev_plan=prev_plan,
            turns_since_update=turns_since_update,
            range_ref=range_ref,
            state=rpg.get("state", {}),
            hidden_state=rpg.get("hidden_state", {}),
            is_bundle=False,
        )

        middled_msgs = middle_out_messages(state["messages"], plan_turns_val)
        history_msgs = convert_to_openai_messages(middled_msgs)
        history_msgs.append({"role": "system", "content": plan_prompt})

        try:
            import rpg_agent.agent.graph as graph
            plan_response = await graph.call_openrouter_direct(
                api_key=api_key,
                base_url=PLAN_BASE_URL,
                model=PLAN_MODEL,
                openai_messages=history_msgs,
                temperature=PLAN_TEMPERATURE,
            )
            clean_resp = plan_response.strip()
            if clean_resp.startswith("```"):
                clean_resp = clean_resp.split("\n", 1)[-1]
                if clean_resp.endswith("```"):
                    clean_resp = clean_resp.rsplit("```", 1)[0]
                clean_resp = clean_resp.strip()
            new_plan = json.loads(clean_resp)
            if isinstance(new_plan, list):
                normalized = []
                for idx, item in enumerate(new_plan, 1):
                    if isinstance(item, dict):
                        normalized.append({
                            "id": item.get("id", idx),
                            "description": item.get("description", ""),
                            "status": item.get("status", "to-do"),
                            "remark": item.get("remark", ""),
                        })
                    else:
                        normalized.append({
                            "id": idx,
                            "description": str(item),
                            "status": "to-do",
                            "remark": "",
                        })
                rpg["plan"] = normalized

                # Record last plan turn
                if "hidden_state" not in rpg or not isinstance(rpg["hidden_state"], dict):
                    rpg["hidden_state"] = {}
                rpg["hidden_state"]["last_plan_turn"] = current_turn

                logger.info("Graph Plan node update complete: %s", rpg["plan"])
            else:
                logger.warning("Graph plan node update did not return a list: %s", clean_resp)
        except Exception as exc:
            logger.error("Failed to run plan node update: %s", exc)

        return {"rpg_state": rpg}
    return plan_node

def _build_tool_node(tools: list):
    """Return the Tool node callable."""
    tool_map = {t.name: t for t in tools}

    async def tool_node(state: AgentState, config: RunnableConfig) -> dict:
        stream_queue = config.get("configurable", {}).get("stream_queue")
        last_message = state["messages"][-1]
        tool_results: list[ToolMessage] = []

        tool_calls = getattr(last_message, "tool_calls", None) or []
        for call in tool_calls:
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

def _route_start(state: AgentState, config: RunnableConfig) -> str:
    summary_fired = config.get("configurable", {}).get("summary_fired", False)
    summary_bundle = config.get("configurable", {}).get("summary_bundle", True)
    if summary_fired and not summary_bundle:
        return "summary"
    plan_fired = config.get("configurable", {}).get("plan_fired", False)
    plan_bundle = config.get("configurable", {}).get("plan_bundle", True)
    if plan_fired and not plan_bundle:
        return "plan"
    return "llm"

def _route_summary_next(state: AgentState, config: RunnableConfig) -> str:
    plan_fired = config.get("configurable", {}).get("plan_fired", False)
    plan_bundle = config.get("configurable", {}).get("plan_bundle", True)
    if plan_fired and not plan_bundle:
        return "plan"
    return "llm"

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
