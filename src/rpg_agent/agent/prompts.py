"""System Prompt Templates for the RPG Proxy Agent."""

import json
import re
from typing import Any, Sequence
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage
from rpg_agent.config import SUMMARY_TARGET_WORDS
from rpg_agent.agent.prompt_constants import (
    UPDATE_PLAN_TASK_TEMPLATE,
    APPEND_SUMMARY_TASK_TEMPLATE,
    CLEANUP_TASK_TEMPLATE,
    PROGRESS_STORY_TASK,
    STATE_SECTION_4_ELEMENT,
    STATE_SECTION_BASIC,
    SANDBOX_INFO_V8,
    SANDBOX_INFO_PYTHON,
    SYSTEM_INSTRUCTION_TEMPLATE,
    SUMMARY_PROMPT_BUNDLE,
    SUMMARY_PROMPT_STANDALONE,
    PLAN_PROMPT_BUNDLE,
    PLAN_PROMPT_STANDALONE,
    CLEANUP_PROMPT_BUNDLE,
    CLEANUP_PROMPT_STANDALONE,
)

def get_message_repr(message: BaseMessage, max_len: int = 150) -> str:
    """Format a single message as a clean single line for representation."""
    content = message.content or ""
    if not isinstance(content, str):
        content = str(content)
    # Strip proxy tags
    cleaned = re.sub(r"\[proxy:[^\]]*\]\n*", "", content, flags=re.IGNORECASE).strip()
    # Replace newlines/spaces with a single space
    single_line = re.sub(r"\s+", " ", cleaned)
    if len(single_line) > max_len:
        single_line = single_line[:max_len] + "..."
    return single_line

def get_range_reference(messages: Sequence[BaseMessage], turns_since_update: int) -> str:
    """Return a single range reference string like 'StartMsg ... EndMsg'."""
    if not messages:
        return ""
    num_messages = turns_since_update * 2
    num_messages = min(max(1, num_messages), len(messages))
    
    start_idx = len(messages) - num_messages
    end_idx = len(messages) - 1
    
    start_repr = get_message_repr(messages[start_idx])
    end_repr = get_message_repr(messages[end_idx])
    
    if start_idx == end_idx:
        return start_repr
    return f"{start_repr} ... {end_repr}"

def middle_out_messages(
    messages: Sequence[BaseMessage],
    turns_since_update: int,
) -> list[BaseMessage]:
    """Middle-out messages history. Returns a list where the prefix of already-processed
    messages is condensed into a single SystemMessage representing the start and end of that prefix.
    """
    if not messages:
        return []
    
    num_recent = turns_since_update * 2
    num_recent = min(max(1, num_recent), len(messages))
    
    prefix_len = len(messages) - num_recent
    
    # If the prefix has 0 or 1 message, no middle-out compression is needed
    if prefix_len < 2:
        return list(messages)
    
    first_msg = messages[0]
    last_prefix_msg = messages[prefix_len - 1]
    
    first_repr = get_message_repr(first_msg)
    last_prefix_repr = get_message_repr(last_prefix_msg)
    
    # Construct the condensed message
    condensed_content = f"{first_repr}\n\n<omitted for brevity>\n\n{last_prefix_repr}"
    condensed_msg = SystemMessage(content=condensed_content)
    
    # Combine condensed message with the remaining messages since last update
    result = [condensed_msg] + list(messages[prefix_len:])
    return result

def get_system_instruction(
    rpg_state: Any,
    sandbox_timeout: float,
    max_iterations: int,
    current_iteration: int,
    rem_iterations: int,
    messages: Sequence[BaseMessage] = (),
    engine_name: str = "v8",
    bundle_plan_fired: bool = False,
    bundle_summary_fired: bool = False,
    bundle_cleanup_fired: bool = False,
    turn_number: int = 1,
) -> str:
    """Return the dynamic system instruction for the LLM node."""
    # 1. Resolve '? turns ago' values from hidden_state
    hidden = {}
    if isinstance(rpg_state, dict) and "hidden_state" in rpg_state and isinstance(rpg_state["hidden_state"], dict):
        hidden = rpg_state["hidden_state"]

    last_plan_turn = hidden.get("last_plan_turn", 0)
    if last_plan_turn == 0:
        plan_turns_val = turn_number
        plan_turns_ago = f"{turn_number} turns ago (at the start of the game)"
    else:
        plan_turns_val = turn_number - last_plan_turn
        plan_turns_ago = f"{plan_turns_val} turn ago" if plan_turns_val == 1 else f"{plan_turns_val} turns ago"

    last_summary_turn = hidden.get("last_summary_turn", 0)
    if last_summary_turn == 0:
        summary_turns_val = turn_number
        summary_turns_ago = f"{turn_number} turns ago (at the start of the game)"
    else:
        summary_turns_val = turn_number - last_summary_turn
        summary_turns_ago = f"{summary_turns_val} turn ago" if summary_turns_val == 1 else f"{summary_turns_val} turns ago"

    last_cleanup_turn = hidden.get("last_cleanup_turn", 0)
    if last_cleanup_turn == 0:
        cleanup_turns_ago = f"{turn_number} turns ago (at the start of the game)"
    else:
        cleanup_turns_val = turn_number - last_cleanup_turn
        cleanup_turns_ago = f"{cleanup_turns_val} turn ago" if cleanup_turns_val == 1 else f"{cleanup_turns_val} turns ago"

    # 2. Build tasks list
    tasks = []
    if bundle_plan_fired:
        tasks.append(
            UPDATE_PLAN_TASK_TEMPLATE.format(plan_turns_ago=plan_turns_ago)
        )
    if bundle_summary_fired:
        tasks.append(
            APPEND_SUMMARY_TASK_TEMPLATE.format(summary_turns_ago=summary_turns_ago)
        )
    if bundle_cleanup_fired:
        tasks.append(
            CLEANUP_TASK_TEMPLATE.format(cleanup_turns_ago=cleanup_turns_ago)
        )
    tasks.append(PROGRESS_STORY_TASK)

    total_tasks = len(tasks)
    tasks_formatted = []
    for idx, task_desc in enumerate(tasks):
        tasks_formatted.append(f"- Task {idx + 1} of {total_tasks}: {task_desc}")
    tasks_block = "\n".join(tasks_formatted)
    task_word = "task" if total_tasks == 1 else "tasks"

    # 3. Format state sections
    is_4_element = isinstance(rpg_state, dict) and all(k in rpg_state for k in ("state", "plan", "summary", "hidden_state"))
    if is_4_element:
        state_section = STATE_SECTION_4_ELEMENT.format(
            state_json=json.dumps(rpg_state['state'], indent=2, ensure_ascii=False),
            hidden_state_json=json.dumps(rpg_state['hidden_state'], indent=2, ensure_ascii=False),
            summary=rpg_state['summary'] or '[No events summarized yet]',
            plan_json=json.dumps(rpg_state['plan'], indent=2, ensure_ascii=False),
        )
    else:
        state_section = STATE_SECTION_BASIC.format(
            state_json=json.dumps(rpg_state, indent=2, ensure_ascii=False)
        )

    # 4. Format sandbox constraints
    if engine_name == "v8":
        sandbox_info = SANDBOX_INFO_V8
    else:
        sandbox_info = SANDBOX_INFO_PYTHON

    # 5. Format H2 blocks if triggered
    h2_instruction_blocks = ""
    if bundle_plan_fired:
        range_ref = get_range_reference(messages, plan_turns_val)
        plan_text = get_plan_prompt(
            prev_plan=rpg_state.get("plan", []) if isinstance(rpg_state, dict) else [],
            turns_since_update=plan_turns_ago,
            range_ref=range_ref,
            is_bundle=True,
        )
        h2_instruction_blocks += f"\n\n## Updating Plan\n{plan_text}"
    if bundle_summary_fired:
        range_ref = get_range_reference(messages, summary_turns_val)
        summary_text = get_summary_prompt(
            prev_summary=rpg_state.get("summary", "") if isinstance(rpg_state, dict) else "",
            target_words=SUMMARY_TARGET_WORDS,
            turns_since_update=summary_turns_ago,
            range_ref=range_ref,
            is_bundle=True,
        )
        h2_instruction_blocks += f"\n\n## Creating Summary to Append\n{summary_text}"
    if bundle_cleanup_fired:
        cleanup_text = get_cleanup_prompt(
            state=rpg_state.get("state", {}) if isinstance(rpg_state, dict) else {},
            hidden_state=rpg_state.get("hidden_state", {}) if isinstance(rpg_state, dict) else {},
            engine_name=engine_name,
            is_bundle=True,
        )
        h2_instruction_blocks += f"\n\n## Storage Cleanup Required\n{cleanup_text}"

    import rpg_agent.config as config

    # Dynamic Summary & Plan Accessibility guidelines
    guidelines_list = [
        "- **Plan Status Updates**: Use the `update_plan_status` tool to update the statuses of checklist items on the **Plan**."
    ]

    if bundle_plan_fired:
        guidelines_list.append(
            "- **Narrative Plan Updates**: Use the `update_plan` tool to replace the **Plan** entirely (a list of dictionaries)."
        )

    if bundle_summary_fired:
        guidelines_list.append(
            "- **Story Summary Updates**: Use the `append_summary` tool to modify the \"Active Story Summary (Rolling Summary)\"."
        )

    summary_plan_access_guidelines = "\n".join(guidelines_list) + "\n"

    state_constraints_info = (
        f"- **State Cleanliness Constraints**:\n"
        f"  - Limit string values in `state` or `hidden_state` to a maximum of {config.MAX_STRING_LENGTH} characters.\n"
        f"  - Limit object/dictionary/list width to a maximum of {config.MAX_WIDTH} keys or elements.\n"
        f"  - Limit object nesting depth to a maximum of {config.MAX_DEPTH} levels.\n"
        f"  - Sandbox validation will programmatically enforce these constraints and discard any violating updates.\n"
    )

    return SYSTEM_INSTRUCTION_TEMPLATE.format(
        total_tasks=total_tasks,
        task_word=task_word,
        tasks_block=tasks_block,
        state_section=state_section,
        sandbox_info=sandbox_info,
        summary_plan_access_guidelines=summary_plan_access_guidelines,
        state_constraints_info=state_constraints_info,
        sandbox_timeout=sandbox_timeout,
        max_iterations=max_iterations,
        current_iteration=current_iteration,
        rem_iterations=rem_iterations,
        h2_instruction_blocks=h2_instruction_blocks,
    )

def get_summary_prompt(
    prev_summary: str,
    target_words: int,
    turns_since_update: str,
    range_ref: str,
    state: dict = {},
    hidden_state: dict = {},
    is_bundle: bool = False,
) -> str:
    """Return the prompt for the narrative summarizer."""
    if is_bundle:
        return SUMMARY_PROMPT_BUNDLE.format(
            turns_since_update=turns_since_update,
            range_ref=range_ref,
            target_words=target_words,
        )
    else:
        state_str = json.dumps(state, indent=2, ensure_ascii=False) if state is not None else "{}"
        hidden_str = json.dumps(hidden_state, indent=2, ensure_ascii=False) if hidden_state is not None else "{}"
        return SUMMARY_PROMPT_STANDALONE.format(
            state_str=state_str,
            hidden_str=hidden_str,
            prev_summary=prev_summary or '[None]',
            target_words=target_words,
            turns_since_update=turns_since_update,
            range_ref=range_ref,
        )

def get_plan_prompt(
    prev_plan: list[dict],
    turns_since_update: str,
    range_ref: str,
    state: dict = {},
    hidden_state: dict = {},
    is_bundle: bool = False,
) -> str:
    """Return the prompt for the story planner and NPC coordinator."""
    if is_bundle:
        return PLAN_PROMPT_BUNDLE.format(
            turns_since_update=turns_since_update,
            range_ref=range_ref,
        )
    else:
        state_str = json.dumps(state, indent=2, ensure_ascii=False) if state is not None else "{}"
        hidden_str = json.dumps(hidden_state, indent=2, ensure_ascii=False) if hidden_state is not None else "{}"
        return PLAN_PROMPT_STANDALONE.format(
            state_str=state_str,
            hidden_str=hidden_str,
            prev_plan=json.dumps(prev_plan, indent=2, ensure_ascii=False),
            turns_since_update=turns_since_update,
            range_ref=range_ref,
        )


def get_cleanup_prompt(
    state: dict = {},
    hidden_state: dict = {},
    engine_name: str = "v8",
    is_bundle: bool = False,
) -> str:
    """Return the prompt for the storage cleanup task/node."""
    lang = "JavaScript" if engine_name == "v8" else "Python"
    syntax_example = (
        "delete state.temp_buff; delete hidden_state.expired_quest_flag;"
        if engine_name == "v8"
        else "state.pop('temp_buff', None)\nhidden_state.pop('expired_quest_flag', None)"
    )
    if is_bundle:
        return CLEANUP_PROMPT_BUNDLE
    else:
        state_str = json.dumps(state, indent=2, ensure_ascii=False) if state is not None else "{}"
        hidden_str = json.dumps(hidden_state, indent=2, ensure_ascii=False) if hidden_state is not None else "{}"
        return CLEANUP_PROMPT_STANDALONE.format(
            state_str=state_str,
            hidden_str=hidden_str,
            lang=lang,
            syntax_example=syntax_example,
        )
