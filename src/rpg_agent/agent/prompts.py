"""System Prompt Templates for the RPG Proxy Agent."""

import json
import re
from typing import Any, Sequence
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage
from rpg_agent.config import SUMMARY_TARGET_WORDS

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
            f"Call the `update_plan` tool to add, modify, or delete items on the **Plan**. "
            f"It should reflect the developments since the last planning, which was {plan_turns_ago}."
        )
    if bundle_summary_fired:
        tasks.append(
            f"Call the `append_summary` tool during this turn to append a 200-300 word summary "
            f"describing the events that have unfolded since the last update, which was {summary_turns_ago}, into **Summary**."
        )
    if bundle_cleanup_fired:
        tasks.append(
            f"Call the `execute_code_sandbox` tool to review the global `state` and `hidden_state` objects, "
            f"cleaning up any expired, redundant, or unnecessary keys/values to keep the variables lean and focused. "
            f"The last cleanup was {cleanup_turns_ago}."
        )
    tasks.append(
        "Progress the story and event in this role-play using the available tools such as "
        "`execute_code_sandbox`, `roll_xdy` and `random_int` based on the **State** and **Hidden-State**."
    )

    total_tasks = len(tasks)
    tasks_formatted = []
    for idx, task_desc in enumerate(tasks):
        tasks_formatted.append(f"- Task {idx + 1} of {total_tasks}: {task_desc}")
    tasks_block = "\n".join(tasks_formatted)
    task_word = "task" if total_tasks == 1 else "tasks"

    # 3. Format state sections
    is_4_element = isinstance(rpg_state, dict) and all(k in rpg_state for k in ("state", "plan", "summary", "hidden_state"))
    if is_4_element:
        state_section = (
            f"- **Current State (available as `state` json to `execute_code_sandbox`):\n"
            f"```json\n{json.dumps(rpg_state['state'], indent=2, ensure_ascii=False)}\n```\n\n"
            f"- **Current Hidden-State (available as `hidden_state` to `execute_code_sandbox`):\n"
            f"```json\n{json.dumps(rpg_state['hidden_state'], indent=2, ensure_ascii=False)}\n```\n"
            f"Note: DO NOT reveal Hidden-State to the player directly; simulate its effects organically if you must.\n\n"
            f"- **Summary:**\n"
            f"{rpg_state['summary'] or '[No events summarized yet]'}\n\n"
            f"- **Plan:**\n"
            f"{json.dumps(rpg_state['plan'], indent=2, ensure_ascii=False)}"
        )
    else:
        state_section = (
            f"- **Current State (available as `state` json to `execute_code_sandbox`):\n"
            f"```json\n{json.dumps(rpg_state, indent=2, ensure_ascii=False)}\n```"
        )

    # 4. Format sandbox constraints
    if engine_name == "v8":
        sandbox_info = (
            "- You have access to a JavaScript code execution sandbox (`execute_code_sandbox`) and dice rolling tools (`roll_xdy`).\n"
            "- The JavaScript sandbox allows you to read/mutate the global `state` and `hidden_state` objects. Standard console methods like `console.log` work.\n"
            "  Note: If the sandbox execution fails (due to syntax errors, exceptions, timeouts, or replacing `state` or `hidden_state` with a non-object), any changes are discarded and the original pre-execution state is fully restored.\n"
            "- **Syntax Rules**:\n"
            "  - Modify properties directly on the global objects. Example: `state.party.warrior.hp -= 10; hidden_state.ambush_triggered = true;`\n"
            "  - Do NOT re-declare the `state` or `hidden_state` objects (e.g., do not write `let state = ...`).\n"
            "  - Do NOT write return statements.\n"
        )
    else:
        sandbox_info = (
            "- You have access to a Python code execution sandbox (`execute_code_sandbox`) and dice rolling tools (`roll_xdy`).\n"
            "- The Python sandbox allows you to read/mutate the `state` and `hidden_state` dicts.\n"
            "- The Python sandbox has the following libraries available: math, random, json, time, datetime, collections, itertools, functools, re, string. Nothing outside of these libraries is available.\n"
            "  Note: If the sandbox execution fails (due to syntax errors, exceptions, timeouts, or replacing `state` or `hidden_state` with a non-dict), any changes are discarded and the original pre-execution state is fully restored.\n"
            "- **Syntax Rules**:\n"
            "  - Modify properties directly on the dict objects. Example: `state['party']['warrior']['hp'] -= 10\nhidden_state['ambush_triggered'] = True`\n"
            "  - Do NOT re-declare the `state` or `hidden_state` variables (e.g., do not write `state = ...`).\n"
        )

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

    return (
        "[Agent System Instruction]\n\n"
        "### Tasks\n\n"
        f"Perform the following {total_tasks} {task_word}: \n\n"
        f"{tasks_block}\n\n"
        "### Current Variables\n\n"
        f"{state_section}\n\n"
        "### Roleplay & Secrecy Guidelines\n"
        "- **Hidden State Privacy**: Never mention the words \"Secret State\", \"Hidden State\", or output the raw JSON contents/variables from that section. Translate these metrics into organic, atmospheric narrative (e.g., instead of outputting \"dungeon_boss_hp: 250\", write \"The threat ahead looms large and formidable\").\n"
        "- **Stateless Nature**: You do not retain memory of variables across turns (API calls). To remember a variable, you MUST save it to the public `state` object or the `hidden_state` object using the code sandbox.\n\n"
        "### Tool & State Mapping Rules\n"
        "- **State Modifications**: Use the `execute_code_sandbox` tool to modify the **State** (`state`) and **Hidden State** (`hidden_state`).\n"
        "- **Narrative Plan Updates**: Use the `update_plan` tool to replace the **Plan** entirely (a list of dictionaries). Use the `update_plan_status` tool to update the statuses of checklist items.\n"
        "- **Story Summary Updates**: Use the `append_summary` tool to modify the \"Active Story Summary (Rolling Summary)\".\n\n"
        "### Sandbox Execution Constraints\n"
        f"{sandbox_info}"
        f"- Sandbox execution has a hard timeout of {sandbox_timeout} seconds. If execution fails, all changes are discarded.\n\n"
        "### Budget & Directives\n"
        f"- You have a strict budget of up to {max_iterations} tool-calling iterations.\n"
        f"- Current Iteration: {current_iteration} of {max_iterations}.\n"
        f"- Remaining Tool-Calling Budget: {rem_iterations}.\n"
        f"- If you reach iteration {max_iterations}, no further tool calls will be executed. You must formulate your final response based on the state at that point.\n"
        f"- Feel free to use the sandbox (`execute_code_sandbox`), dice rolling (`roll_xdy`), or random number generator (`random_int`) tools for mathematics, determining random events, and chances."
        f"{h2_instruction_blocks}"
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
        return (
            f"Review the events of the last {turns_since_update} turns of conversation. "
            f"The range of messages to summarize is: \"{range_ref}\".\n"
            f"You must call the `append_summary` tool with a concise summary block (approximately {target_words} words) "
            f"describing the developments in this range. Keep the tone matching the story."
        )
    else:
        state_str = json.dumps(state, indent=2, ensure_ascii=False) if state is not None else "{}"
        hidden_str = json.dumps(hidden_state, indent=2, ensure_ascii=False) if hidden_state is not None else "{}"
        return (
            "You are a narrative summarizer for a role-playing game.\n"
            f"Here is the public State:\n```json\n{state_str}\n```\n\n"
            f"Here is the secret Hidden-State:\n```json\n{hidden_str}\n```\n\n"
            f"Here is the story summary so far (reference only do not include it in your summary):\n{prev_summary or '[None]'}\n\n"
            f"Write a concise summary block (approximately {target_words} words) "
            f"summarizing the events of the last {turns_since_update} turns of conversation. "
            f"The range of messages to summarize is: \"{range_ref}\".\n\n"
            "Keep the tone matching the story.\n"
            "Output ONLY the new summary block to append. Do not include introductory text, markdown formatting, or quotes."
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
        return (
            f"Review the story developed since the last planning, which was {turns_since_update} ago. "
            f"The range of developments is: \"{range_ref}\".\n"
            f"You must call the `update_plan` tool with an updated checklist (as an array of objects) "
            f"incorporating new sub-goals that have emerged, keeping pending tasks, and removing completed items."
        )
    else:
        state_str = json.dumps(state, indent=2, ensure_ascii=False) if state is not None else "{}"
        hidden_str = json.dumps(hidden_state, indent=2, ensure_ascii=False) if hidden_state is not None else "{}"
        return (
            "You are a story planner and NPC coordinator for a role-playing game.\n"
            f"Here is the public State:\n```json\n{state_str}\n```\n\n"
            f"Here is the secret Hidden-State:\n```json\n{hidden_str}\n```\n\n"
            f"Here is the current plan, which was created {turns_since_update} turns ago, is:\n{json.dumps(prev_plan, indent=2, ensure_ascii=False)}\n\n"
            f"Review the story developed since the last planning. "
            f"The range of developments (under the current plan) is: \"{range_ref}\".\n\n"
            "Review the current checklist and how the story has progressed.\n"
            "Generate an updated checklist of future story goals and NPC plans as a JSON array of objects, "
            "where each object matches the schema: {\"id\": int, \"description\": str, \"status\": str, \"remark\": str}.\n"
            "Output ONLY a valid JSON array of objects. Do not include markdown wraps (like ```json) or explanation."
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
        return (
            f"Review the current `state` and `hidden_state` JSON objects. "
            f"Identify any keys, list elements, or parameters that have expired, are no longer active, "
            f"or are redundant for the current narrative. Use the `execute_code_sandbox` tool to "
            f"clean them up. Keep the variables slim and focused only on active/relevant game state."
        )
    else:
        state_str = json.dumps(state, indent=2, ensure_ascii=False) if state is not None else "{}"
        hidden_str = json.dumps(hidden_state, indent=2, ensure_ascii=False) if hidden_state is not None else "{}"
        return (
            f"You are a state optimization utility for an RPG agent.\n"
            f"Here is the public State:\n```json\n{state_str}\n```\n\n"
            f"Here is the secret Hidden-State:\n```json\n{hidden_str}\n```\n\n"
            f"Review these objects and write a {lang} code snippet to remove/delete any "
            f"expired, redundant, or unnecessary keys or parameters. "
            f"For example, you can write: `{syntax_example}`.\n\n"
            f"Output ONLY the raw {lang} code snippet to execute. Do NOT include markdown code blocks, "
            f"introductory conversational text, or any explanations."
        )
