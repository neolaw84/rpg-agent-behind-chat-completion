"""LangChain Tool definitions for the RPG Agent."""

import logging
import random
from typing import Any
from langchain_core.tools import tool
from rpg_agent.sandbox import execute_sandbox

logger = logging.getLogger(__name__)

def make_tools(state_container: dict[str, Any], sandbox_timeout: float):
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
