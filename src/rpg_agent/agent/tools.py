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
        updated, output = engine.execute(code, state_container["rpg_state"], sandbox_timeout)
        state_container["rpg_state"] = updated
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

    return [execute_code_sandbox, roll_xdy, random_int]
