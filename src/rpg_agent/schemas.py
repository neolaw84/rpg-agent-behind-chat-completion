"""Tool Schemas for OpenRouter direct function calling."""

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
