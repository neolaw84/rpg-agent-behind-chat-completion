"""Tool Schemas for OpenRouter direct function calling."""

from typing import Any

def get_tools_schema(
    engine_name: str = "v8",
    include_plan: bool = False,
    include_summary: bool = False,
) -> list[dict[str, Any]]:
    """Return the tools schema for OpenRouter completions based on engine name."""
    if engine_name == "v8":
        sandbox_desc = (
            "Execute a JavaScript code snippet to read or modify the current RPG state. "
            "The global variable `state` (an object) is available for reading and updating. "
            "Use console.log(...) to print outputs. Returns the log output."
        )
        code_desc = "The JavaScript code snippet to run."
    else:
        sandbox_desc = (
            "Execute a Python code snippet to read or modify the current RPG state. "
            "The variable `state` (a dict) is available for reading and updating. "
            "Available libraries: math, random, json, time, datetime, collections, itertools, functools, re, string. "
            "Nothing outside of these libraries is available. Returns the stdout of the code execution."
        )
        code_desc = "The Python code snippet to run."

    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "execute_code_sandbox",
                "description": sandbox_desc,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": code_desc
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
    },
    {
        "type": "function",
        "function": {
            "name": "update_plan_status",
            "description": "Update the status of plan items by their ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "updates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "integer",
                                    "description": "The ID of the plan item to update"
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["to-do", "in-progress", "done", "abandoned"]
                                }
                            },
                            "required": ["id", "status"]
                        },
                        "description": "List of updates to apply."
                    }
                },
                "required": ["updates"]
            }
        }
    }
]

    if include_plan:
        tools.append({
            "type": "function",
            "function": {
                "name": "update_plan",
                "description": "Update the narrative plan/checklist entirely. The checklist is a list of dictionaries matching the plan schema.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "checklist": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {
                                        "type": "integer",
                                        "description": "Sequential unique item identifier starting at 1"
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "The description of the narrative goal or action"
                                    },
                                    "status": {
                                        "type": "string",
                                        "enum": ["to-do", "in-progress", "done", "abandoned"],
                                        "description": "Status of the checklist item"
                                    },
                                    "remark": {
                                        "type": "string",
                                        "description": "Remark, schedule, or notes for this item"
                                    }
                                },
                                "required": ["id", "description", "status", "remark"]
                            },
                            "description": "The updated plan checklist of narrative goals."
                        }
                    },
                    "required": ["checklist"]
                }
            }
        })

    if include_summary:
        tools.append({
            "type": "function",
            "function": {
                "name": "append_summary",
                "description": "Append a new summary block describing the events that have unfolded since the last summary (200-300 words).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The concise new summary block to append."
                        }
                    },
                    "required": ["text"]
                }
            }
        })

    return tools


TOOLS_SCHEMA = get_tools_schema("python")

