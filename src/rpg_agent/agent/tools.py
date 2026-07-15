"""LangChain Tool definitions for the RPG Agent."""

import logging
import random
from typing import Any
from langchain_core.tools import tool, StructuredTool
from rpg_agent.sandbox.sandbox import get_sandbox_engine

logger = logging.getLogger(__name__)

def make_tools(state_container: dict[str, Any], sandbox_timeout: float):
    """Return a list of LangChain tools that share ``state_container`` by
    reference so that every tool call sees the latest state.
    """
    engine = get_sandbox_engine()
    if engine.name == "v8":
        description = (
            "Execute a JavaScript code snippet to read or modify the current RPG state. "
            "Variables: `state` (JSON object representing the RPG state). Use `console.log(...)` to print outputs."
        )
    else:
        description = (
            "Execute a Python code snippet to read or modify the current RPG state. "
            "Variables: `state` (dict representing the RPG state). Available libraries: "
            "math, random, json, time, datetime, collections, itertools, functools, re, string. "
            "No other libraries are available."
        )

    def _execute_code_sandbox(code: str) -> str:
        import copy
        import rpg_agent.config as config
        from rpg_agent.sandbox.validation import validate_state_constraints

        # Take a deep copy of the original state to restore on validation failure
        rpg_copy = copy.deepcopy(state_container["rpg_state"])

        rpg = state_container["rpg_state"]
        # If it is the 4-element dict, construct the wrapper for execution
        is_4_element = isinstance(rpg, dict) and all(k in rpg for k in ("state", "plan", "summary", "hidden_state"))
        if is_4_element:
            wrapper = {
                "state": rpg.get("state", {}),
                "hidden_state": rpg.get("hidden_state", {}),
            }
            updated, output = engine.execute(code, wrapper, sandbox_timeout)
            if isinstance(updated, dict) and "state" in updated and "hidden_state" in updated:
                rpg["state"] = updated["state"]
                rpg["hidden_state"] = updated["hidden_state"]
            else:
                rpg["state"] = updated
        else:
            updated, output = engine.execute(code, rpg, sandbox_timeout)
            state_container["rpg_state"] = updated

        # Perform post-execution validation checks
        try:
            rpg_current = state_container["rpg_state"]
            if is_4_element:
                validate_state_constraints(
                    rpg_current.get("state", {}),
                    config.MAX_DEPTH,
                    config.MAX_WIDTH,
                    config.MAX_STRING_LENGTH,
                    "state",
                    1
                )
                validate_state_constraints(
                    rpg_current.get("hidden_state", {}),
                    config.MAX_DEPTH,
                    config.MAX_WIDTH,
                    config.MAX_STRING_LENGTH,
                    "hidden_state",
                    1
                )
            else:
                validate_state_constraints(
                    rpg_current,
                    config.MAX_DEPTH,
                    config.MAX_WIDTH,
                    config.MAX_STRING_LENGTH,
                    "state",
                    1
                )
        except ValueError as e:
            # Revert any mutations back to the clean pre-execution copy
            state_container["rpg_state"] = rpg_copy
            
            validation_error_msg = (
                f"\n--- Sandbox Validation Error ---\n{str(e)}\n"
                f"Notice: You have wasted one tool call due to this validation failure. Please adjust your state modifications."
            )
            output = (output or "").strip()
            if output:
                output = f"{output}\n{validation_error_msg}"
            else:
                output = validation_error_msg

        logger.info("Sandbox executed (%s). Output:\n%s", engine.name, output or "<no output>")
        return output or "(no output)"

    execute_code_sandbox = StructuredTool.from_function(
        func=_execute_code_sandbox,
        name="execute_code_sandbox",
        description=description,
    )

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

    @tool
    def update_plan(checklist: list[Any]) -> str:
        """Update the narrative plan/checklist for how the story should progress. The checklist items can be strings or dictionaries matching the plan schema."""
        normalized = []
        for idx, item in enumerate(checklist, 1):
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
        state_container["rpg_state"]["plan"] = normalized
        rpg = state_container["rpg_state"]
        if isinstance(rpg, dict) and "hidden_state" in rpg and isinstance(rpg["hidden_state"], dict):
            rpg["hidden_state"]["last_plan_turn"] = state_container.get("current_turn", 1)
        logger.info("Plan updated: %s", normalized)
        return "[Plan checklist updated successfully]"

    @tool
    def update_plan_status(updates: list[dict]) -> str:
        """Update the status of plan items by their ID. updates parameter is a list of {'id': int_or_str, 'status': str} updates."""
        rpg = state_container["rpg_state"]
        plan = rpg.get("plan", [])
        if not isinstance(plan, list):
            plan = []
        
        # Build a map of id -> item for fast lookups
        plan_map = {}
        for item in plan:
            if isinstance(item, dict) and "id" in item:
                plan_map[item["id"]] = item
        
        updated_count = 0
        for u in updates:
            if not isinstance(u, dict) or "id" not in u or "status" not in u:
                continue
            
            item_id = u["id"]
            item = None
            if item_id in plan_map:
                item = plan_map[item_id]
            else:
                # Fallback: try converting string key to integer or vice versa
                try:
                    int_id = int(item_id)
                    if int_id in plan_map:
                        item = plan_map[int_id]
                except (ValueError, TypeError):
                    pass
                
                if not item:
                    str_id = str(item_id)
                    if str_id in plan_map:
                        item = plan_map[str_id]

            if item:
                item["status"] = u["status"]
                updated_count += 1
                
        logger.info("Plan status updated: %s items updated", updated_count)
        return f"[Updated status of {updated_count} plan items successfully]"

    @tool
    def append_summary(text: str) -> str:
        """Append a new summary block describing the events that have unfolded since the last summary (200-300 words)."""
        current_summary = state_container["rpg_state"].get("summary", "")
        if current_summary:
            state_container["rpg_state"]["summary"] = current_summary.strip() + "\n\n" + text.strip()
        else:
            state_container["rpg_state"]["summary"] = text.strip()
        rpg = state_container["rpg_state"]
        if isinstance(rpg, dict) and "hidden_state" in rpg and isinstance(rpg["hidden_state"], dict):
            rpg["hidden_state"]["last_summary_turn"] = state_container.get("current_turn", 1)
        logger.info("Summary appended: %s", text)
        return "[Summary appended successfully]"

    return [execute_code_sandbox, roll_xdy, random_int, update_plan, update_plan_status, append_summary]
