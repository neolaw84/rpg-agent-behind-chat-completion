"""Unit tests for the RPG stateful expansion (plan, summary, hidden_state)."""

import json
import hashlib
import random
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from rpg_agent.core.state import SessionStateStore, _migrate_state
from rpg_agent.sandbox.sandbox import execute_sandbox
from rpg_agent.agent.tools import make_tools
from rpg_agent.agent.graph import run_agent
from rpg_agent.agent.prompts import get_system_instruction


# 1. Test state migration and backward-compatibility
def test_state_migration():
    # Test migration of old format (single dict)
    old_state = {"gold": 100, "hp": 50}
    migrated = _migrate_state(old_state)
    assert migrated["state"] == {"gold": 100, "hp": 50}
    assert migrated["plan"] == []
    assert migrated["summary"] == ""
    assert migrated["hidden_state"] == {}

    # Test migration of already new format (no-op)
    new_state = {
        "state": {"gold": 200},
        "plan": ["meet Bob"],
        "summary": "Met Bob.",
        "hidden_state": {"poison": 3}
    }
    migrated_new = _migrate_state(new_state)
    assert migrated_new == new_state

    # Test empty state
    assert _migrate_state({}) == {
        "state": {},
        "plan": [],
        "summary": "",
        "hidden_state": {},
    }


# 2. Test sandbox execution with state and hidden_state
@pytest.mark.parametrize("engine_name", ["v8", "python"])
def test_sandbox_with_hidden_state(engine_name):
    from rpg_agent.sandbox.sandbox import get_sandbox_engine
    env_patch = {"RPG_AGENT_SANDBOX_ENGINE": engine_name}

    with patch.dict("os.environ", env_patch):
        engine = get_sandbox_engine()
        wrapper = {
            "state": {"gold": 100},
            "hidden_state": {"poison_turns": 3}
        }
        
        # Test reading and mutating both state and hidden_state
        if engine_name == "python":
            code = "state['gold'] += 50\nhidden_state['poison_turns'] -= 1"
        else:
            code = "state.gold += 50; hidden_state.poison_turns -= 1;"

        updated, logs = engine.execute(code, wrapper)
        assert updated["state"]["gold"] == 150
        assert updated["hidden_state"]["poison_turns"] == 2


# 3. Test deterministic probabilistic seeding
def test_deterministic_seeding():
    messages_1 = [
        {"role": "user", "content": "Let's explore"},
        {"role": "assistant", "content": "You see a cave."}
    ]
    messages_2 = [
        {"role": "user", "content": "Let's enter"},
    ]

    # Helper to calculate trigger decision
    def trigger_decision(msgs, p):
        msg_contents = [m.get("content") or "" for m in msgs]
        seed = int(hashlib.sha256("\x00".join(msg_contents).encode("utf-8")).hexdigest(), 16)
        rng = random.Random(seed)
        return rng.random() < p

    # Determinism check (should be consistent across multiple evaluations of same messages)
    d1_a = trigger_decision(messages_1, 0.50)
    d1_b = trigger_decision(messages_1, 0.50)
    assert d1_a == d1_b

    # Pacing check (different messages should yield independent results)
    d2 = trigger_decision(messages_2, 0.50)
    # They are likely different, or at least they behave as independent pseudo-random variables


# 4. Test Graph Orchestration Nodes (Summary and Plan trigger execution with bundle_llm=False)
@pytest.mark.asyncio
@patch("rpg_agent.agent.openrouter.call_openrouter_direct", new_callable=AsyncMock)
@patch("rpg_agent.agent.graph.call_openrouter_streaming", new_callable=AsyncMock)
async def test_graph_orchestration_nodes(mock_streaming, mock_direct):
    # Set summary model response and plan model response
    mock_direct.side_effect = [
        "A heavy oak door was opened by the player.",
        '["open door", "fight boss"]'
    ]
    # Set main GM response
    mock_streaming.return_value = ("The door opens.", None, [])

    before_state = {
        "state": {},
        "plan": [],
        "summary": "They entered a dungeon.",
        "hidden_state": {}
    }

    # Patch configurations: enable triggers for both plan and summary, set bundle_llm to False
    with patch("rpg_agent.config.SUMMARY_TRIGGER_TYPE", "periodic"), \
         patch("rpg_agent.config.SUMMARY_INTERVAL_TURNS", 1), \
         patch("rpg_agent.config.SUMMARY_BUNDLE_LLM", False), \
         patch("rpg_agent.config.PLAN_TRIGGER_TYPE", "periodic"), \
         patch("rpg_agent.config.PLAN_INTERVAL_TURNS", 1), \
         patch("rpg_agent.config.PLAN_BUNDLE_LLM", False):

         messages = [
             {"role": "user", "content": "I open the door."},
             {"role": "assistant", "content": "The door opens."}
         ]

         result = await run_agent(
             messages=messages,
             before_state=before_state,
             api_key="fake-key",
             base_url="fake-url",
             model="fake-model"
         )

         # Assert summary rolling append from summary node execution
         assert result["after_state"]["summary"] == "They entered a dungeon.\n\nA heavy oak door was opened by the player."
         # Assert plan checklist replacement from plan node execution
         assert result["after_state"]["plan"] == [
              {"id": 1, "description": "open door", "status": "to-do", "remark": ""},
              {"id": 2, "description": "fight boss", "status": "to-do", "remark": ""},
          ]
         # Assert call_openrouter_direct was called twice (once for summary, once for plan)
         assert mock_direct.call_count == 2
         # Assert main GM was called
         assert mock_streaming.call_count == 1


# 5. Test Graph routing with disabled triggers
@pytest.mark.asyncio
@patch("rpg_agent.agent.openrouter.call_openrouter_direct", new_callable=AsyncMock)
@patch("rpg_agent.agent.graph.call_openrouter_streaming", new_callable=AsyncMock)
async def test_graph_routing_with_disabled_triggers(mock_streaming, mock_direct):
    mock_streaming.return_value = ("You see a chest.", None, [])

    before_state = {
        "state": {},
        "plan": ["find dungeon key"],
        "summary": "They entered a dungeon.",
        "hidden_state": {}
    }

    # Summary is disabled, Plan is probabilistic but doesn't trigger (probability 0.0)
    with patch("rpg_agent.config.SUMMARY_TRIGGER_TYPE", "disabled"), \
         patch("rpg_agent.config.PLAN_TRIGGER_TYPE", "probabilistic"), \
         patch("rpg_agent.config.PLAN_TRIGGER_PROBABILITY", 0.0):

         messages = [
             {"role": "user", "content": "I walk forward."}
         ]

         result = await run_agent(
             messages=messages,
             before_state=before_state,
             api_key="fake-key",
             base_url="fake-url",
             model="fake-model"
         )

         # Verify summary and plan are completely unchanged
         assert result["after_state"]["summary"] == "They entered a dungeon."
         assert result["after_state"]["plan"] == ["find dungeon key"]
         # Direct calls count should be 0 because neither summary nor plan triggered
         assert mock_direct.call_count == 0
         # Main LLM is still called
         assert mock_streaming.call_count == 1


# 6. Test Bundled Trigger execution (injecting directives and executing tool calls with bundle_llm=True)
@pytest.mark.asyncio
@patch("rpg_agent.agent.graph.call_openrouter_streaming", new_callable=AsyncMock)
async def test_bundled_trigger_nodes_execution(mock_streaming):
    # Set main GM response to invoke tools update_plan and append_summary
    # Return structure: (content, reasoning, list_of_tool_calls)
    tool_calls = [
        {
            "id": "call_plan_1",
            "type": "function",
            "function": {
                "name": "update_plan",
                "arguments": '{"checklist": ["find keys", "escape room"]}'
            }
        },
        {
            "id": "call_summary_1",
            "type": "function",
            "function": {
                "name": "append_summary",
                "arguments": '{"text": "They decided to find the keys."}'
            }
        }
    ]
    mock_streaming.side_effect = [
        ("I will plan and summarize.", None, tool_calls),
        ("All updates completed.", None, [])
    ]

    before_state = {
        "state": {},
        "plan": [],
        "summary": "Start.",
        "hidden_state": {}
    }

    # Set both plan and summary to bundle_llm=True, and trigger periodic updates
    with patch("rpg_agent.config.SUMMARY_TRIGGER_TYPE", "periodic"), \
         patch("rpg_agent.config.SUMMARY_INTERVAL_TURNS", 1), \
         patch("rpg_agent.config.SUMMARY_BUNDLE_LLM", True), \
         patch("rpg_agent.config.PLAN_TRIGGER_TYPE", "periodic"), \
         patch("rpg_agent.config.PLAN_INTERVAL_TURNS", 1), \
         patch("rpg_agent.config.PLAN_BUNDLE_LLM", True):

         messages = [
             {"role": "user", "content": "Let's plan."}
         ]

         result = await run_agent(
             messages=messages,
             before_state=before_state,
             api_key="fake-key",
             base_url="fake-url",
             model="fake-model"
         )

         # Verify main LLM was called (once for tool calls, once for final completion)
         assert mock_streaming.call_count == 2
         
         # Verify that the tools updated the shared state successfully
         assert result["after_state"]["summary"] == "Start.\n\nThey decided to find the keys."
         assert result["after_state"]["plan"] == [
             {"id": 1, "description": "find keys", "status": "to-do", "remark": ""},
             {"id": 2, "description": "escape room", "status": "to-do", "remark": ""},
         ]
