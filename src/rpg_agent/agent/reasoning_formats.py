"""Dictionary of reasoning formats to their actual request payload extensions."""

REASONING_FORMATS = {
    "Open-Router": {
        "extra_body": {
            "include_reasoning": True
        }
    },
    "OpenAI": {
        "reasoning_effort": "medium"
    },
    "Gemini": {
        "extra_body": {
            "thinking_config": {
                "thinking_budget": -1
            }
        }
    },
    "Anthropic": {
        "thinking": {
            "type": "enabled",
            "budget_tokens": 1024
        }
    },
    "X.AI": {
        "reasoning_effort": "high"
    },
    "Z.AI": {
        "thinking": {
            "type": "enabled"
        },
        "reasoning_effort": "max"
    },
    "DeepSeek": {
        "extra_body": {
            "thinking": {
                "type": "enabled"
            }
        }
    }
}
