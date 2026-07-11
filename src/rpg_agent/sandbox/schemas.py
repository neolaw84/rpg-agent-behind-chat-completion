"""Tool Schemas for OpenRouter direct function calling."""

def get_tools_schema(engine_name: str = "v8") -> list[dict]:
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

    return [
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
    }
]

TOOLS_SCHEMA = get_tools_schema("python")
