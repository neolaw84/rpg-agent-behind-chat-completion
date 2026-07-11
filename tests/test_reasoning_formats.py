import pytest
import os
from unittest.mock import patch
from rpg_agent.agent.reasoning_formats import REASONING_FORMATS
from rpg_agent.agent.openrouter import deep_merge

def test_deep_merge():
    # Test flat dictionaries
    d1 = {"a": 1, "b": 2}
    d2 = {"b": 3, "c": 4}
    assert deep_merge(d1, d2) == {"a": 1, "b": 3, "c": 4}

    # Test nested dictionaries
    d3 = {
        "extra_body": {
            "first": "value",
            "thinking": {"type": "disabled"}
        }
    }
    d4 = {
        "extra_body": {
            "second": "another",
            "thinking": {"type": "enabled", "budget": 100}
        }
    }
    expected = {
        "extra_body": {
            "first": "value",
            "second": "another",
            "thinking": {"type": "enabled", "budget": 100}
        }
    }
    assert deep_merge(d3, d4) == expected

def test_config_reasoning_formats_resolution():
    # Test pre-defined format resolution (Gemini)
    with patch("yaml.safe_load", return_value={"llm": {"reasoning_format": "gemini"}}):
        # Reload or check resolved config locally
        import importlib
        import rpg_agent.config
        importlib.reload(rpg_agent.config)
        assert rpg_agent.config.REASONING_FORMAT == "gemini"
        assert rpg_agent.config.REASONING_PAYLOAD == REASONING_FORMATS["Gemini"]

    # Test custom payload resolution
    custom_payload = {"some_key": "some_value", "extra_body": {"special": True}}
    with patch("yaml.safe_load", return_value={"llm": {"reasoning_format": "custom", "reasoning_payload": custom_payload}}):
        importlib.reload(rpg_agent.config)
        assert rpg_agent.config.REASONING_FORMAT == "custom"
        assert rpg_agent.config.REASONING_PAYLOAD == custom_payload

    # Cleanup reload
    importlib.reload(rpg_agent.config)
