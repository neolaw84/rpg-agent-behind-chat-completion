import json
import pytest
from unittest.mock import patch, AsyncMock
from rpg_agent.agent.prompts import get_summary_prompt, get_plan_prompt

def test_get_summary_prompt():
    prev_summary = "Alice went to the tavern."
    range_ref = "Hello ... Thanks."
    target_words = 50
    state = {"hp": 99}
    hidden_state = {"secret_var": "val"}
    
    # Standalone mode
    prompt = get_summary_prompt(prev_summary, target_words, "2 turns", range_ref, state, hidden_state, is_bundle=False)
    assert prev_summary in prompt
    assert range_ref in prompt
    assert "2 turns" in prompt
    assert str(target_words) in prompt
    assert "hp" in prompt
    assert "secret_var" in prompt
    assert "append_summary" not in prompt

    # Bundled mode
    prompt_bundled = get_summary_prompt(prev_summary, target_words, "2 turns", range_ref, state, hidden_state, is_bundle=True)
    assert prev_summary not in prompt_bundled
    assert range_ref in prompt_bundled
    assert "2 turns" in prompt_bundled
    assert str(target_words) in prompt_bundled
    assert "append_summary" in prompt_bundled
    assert prompt_bundled != prompt

def test_get_plan_prompt():
    prev_plan = [{"id": 1, "description": "Goal 1", "status": "to-do", "remark": ""}]
    range_ref = "Let's go. ... Alright."
    state = {"hp": 99}
    hidden_state = {"secret_var": "val"}
    
    # Standalone mode
    prompt = get_plan_prompt(prev_plan, "3 turns", range_ref, state, hidden_state, is_bundle=False)
    assert range_ref in prompt
    assert "3 turns" in prompt
    assert "Goal 1" in prompt
    assert "to-do" in prompt
    assert "hp" in prompt
    assert "secret_var" in prompt
    assert "update_plan" not in prompt

    # Bundled mode
    prompt_bundled = get_plan_prompt(prev_plan, "3 turns", range_ref, state, hidden_state, is_bundle=True)
    assert range_ref in prompt_bundled
    assert "3 turns" in prompt_bundled
    assert "Goal 1" not in prompt_bundled
    assert "update_plan" in prompt_bundled
    assert prompt_bundled != prompt


def test_get_tools_schema_filtering():
    from rpg_agent.sandbox.schemas import get_tools_schema

    # Test default
    schemas = get_tools_schema("v8")
    names = [s["function"]["name"] for s in schemas]
    assert "execute_code_sandbox" in names
    assert "roll_xdy" in names
    assert "random_int" in names
    assert "update_plan" not in names
    assert "update_plan_status" in names
    assert "append_summary" not in names

    # Test include plan
    schemas = get_tools_schema("v8", include_plan=True)
    names = [s["function"]["name"] for s in schemas]
    assert "update_plan" in names
    assert "update_plan_status" in names
    assert "append_summary" not in names

    # Test include summary
    schemas = get_tools_schema("v8", include_summary=True)
    names = [s["function"]["name"] for s in schemas]
    assert "update_plan" not in names
    assert "update_plan_status" in names
    assert "append_summary" in names

    # Test both
    schemas = get_tools_schema("v8", include_plan=True, include_summary=True)
    names = [s["function"]["name"] for s in schemas]
    assert "update_plan" in names
    assert "update_plan_status" in names
    assert "append_summary" in names


@pytest.mark.asyncio
@patch("rpg_agent.agent.graph.call_openrouter_streaming", new_callable=AsyncMock)
async def test_plan_summary_gap_triggers(mock_streaming):
    from unittest.mock import patch, AsyncMock
    from langchain_core.messages import AIMessage
    from rpg_agent.agent.graph import run_agent

    mock_streaming.return_value = ("GM reply", None, [])

    # Setup: k = 2, gap = 1.
    # For turn_number = 2 (1 assistant message in history):
    # plan_fired = (2 % 2 == 0) -> True.
    # summary_fired = ((2 + 1) % 2 == 0) -> False.
    with patch("rpg_agent.config.PLAN_OFFSET", 0), \
         patch("rpg_agent.config.PLAN_TRIGGER_TYPE", "periodic"), \
         patch("rpg_agent.config.PLAN_INTERVAL_TURNS", 2), \
         patch("rpg_agent.config.SUMMARY_TRIGGER_TYPE", "periodic"), \
         patch("rpg_agent.config.SUMMARY_INTERVAL_TURNS", 2), \
         patch("rpg_agent.config.PLAN_SUMMARY_GAP", 1):

         messages = [
             {"role": "user", "content": "hello"},
             {"role": "assistant", "content": "GM reply"},
             {"role": "user", "content": "next"}
         ]
         with patch("langgraph.graph.state.CompiledStateGraph.ainvoke", new_callable=AsyncMock) as mock_invoke:
             mock_invoke.return_value = {
                 "messages": [AIMessage(content="GM reply")],
                 "rpg_state": {}
             }
             await run_agent(
                 messages=messages,
                 before_state={"state": {}},
                 api_key="fake",
                 base_url="fake",
                 model="fake"
             )
             config = mock_invoke.call_args[1]["config"]
             assert config["configurable"]["plan_fired"] is True
             assert config["configurable"]["summary_fired"] is False

         # For turn_number = 1 (0 assistant messages in history):
         # plan_fired is forced to True on Turn 1.
         # summary_fired = ((1 + 1) % 2 == 0) -> True.
         messages_turn_1 = [
             {"role": "user", "content": "hello"}
         ]
         with patch("langgraph.graph.state.CompiledStateGraph.ainvoke", new_callable=AsyncMock) as mock_invoke:
             mock_invoke.return_value = {
                 "messages": [AIMessage(content="GM reply")],
                 "rpg_state": {}
             }
             await run_agent(
                 messages=messages_turn_1,
                 before_state={"state": {}},
                 api_key="fake",
                 base_url="fake",
                 model="fake"
             )
             config = mock_invoke.call_args[1]["config"]
             assert config["configurable"]["plan_fired"] is True
             assert config["configurable"]["summary_fired"] is True

         # For turn_number = 3 (2 assistant messages in history):
         # plan_fired = (3 % 2 == 0) -> False.
         # summary_fired = ((3 + 1) % 2 == 0) -> True.
         messages_turn_3 = [
             {"role": "user", "content": "hello"},
             {"role": "assistant", "content": "GM reply"},
             {"role": "user", "content": "next"},
             {"role": "assistant", "content": "GM reply 2"},
             {"role": "user", "content": "third"}
         ]
         with patch("langgraph.graph.state.CompiledStateGraph.ainvoke", new_callable=AsyncMock) as mock_invoke:
             mock_invoke.return_value = {
                 "messages": [AIMessage(content="GM reply")],
                 "rpg_state": {}
             }
             await run_agent(
                 messages=messages_turn_3,
                 before_state={"state": {}},
                 api_key="fake",
                 base_url="fake",
                 model="fake"
             )
             config = mock_invoke.call_args[1]["config"]
             assert config["configurable"]["plan_fired"] is False
             assert config["configurable"]["summary_fired"] is True


@pytest.mark.asyncio
@patch("rpg_agent.agent.graph.call_openrouter_streaming", new_callable=AsyncMock)
async def test_periodic_trigger_order(mock_streaming):
    from unittest.mock import patch, AsyncMock
    from langchain_core.messages import AIMessage
    from rpg_agent.agent.graph import run_agent

    mock_streaming.return_value = ("GM reply", None, [])

    # Setup: Interval = 8, summary_gap = 1, cleanup_gap = 2
    with patch("rpg_agent.config.PLAN_OFFSET", 0), \
         patch("rpg_agent.config.PLAN_TRIGGER_TYPE", "periodic"), \
         patch("rpg_agent.config.PLAN_INTERVAL_TURNS", 8), \
         patch("rpg_agent.config.SUMMARY_TRIGGER_TYPE", "periodic"), \
         patch("rpg_agent.config.SUMMARY_INTERVAL_TURNS", 8), \
         patch("rpg_agent.config.PLAN_SUMMARY_GAP", 1), \
         patch("rpg_agent.config.CLEANUP_TRIGGER_TYPE", "periodic"), \
         patch("rpg_agent.config.CLEANUP_INTERVAL_TURNS", 8), \
         patch("rpg_agent.config.PLAN_CLEANUP_GAP", 2):

         # Check Turn 8 (Plan should fire, Summary/Cleanup should not)
         # 7 assistant messages in history means we are on Turn 8
         messages_8 = [{"role": "user", "content": "msg"}] + [{"role": "assistant", "content": "reply"}, {"role": "user", "content": "msg"}] * 7
         with patch("langgraph.graph.state.CompiledStateGraph.ainvoke", new_callable=AsyncMock) as mock_invoke:
             mock_invoke.return_value = {"messages": [AIMessage(content="GM reply")], "rpg_state": {}}
             await run_agent(messages=messages_8, before_state={"state": {}}, api_key="fake", base_url="fake", model="fake")
             cfg = mock_invoke.call_args[1]["config"]
             assert cfg["configurable"]["plan_fired"] is True
             assert cfg["configurable"]["summary_fired"] is False
             assert cfg["configurable"]["cleanup_fired"] is False

         # Check Turn 9 (Summary should fire, Plan/Cleanup should not)
         messages_9 = messages_8 + [{"role": "assistant", "content": "reply"}, {"role": "user", "content": "msg"}]
         with patch("langgraph.graph.state.CompiledStateGraph.ainvoke", new_callable=AsyncMock) as mock_invoke:
             mock_invoke.return_value = {"messages": [AIMessage(content="GM reply")], "rpg_state": {}}
             await run_agent(messages=messages_9, before_state={"state": {}}, api_key="fake", base_url="fake", model="fake")
             cfg = mock_invoke.call_args[1]["config"]
             assert cfg["configurable"]["plan_fired"] is False
             assert cfg["configurable"]["summary_fired"] is True
             assert cfg["configurable"]["cleanup_fired"] is False

         # Check Turn 10 (Cleanup should fire, Plan/Summary should not)
         messages_10 = messages_9 + [{"role": "assistant", "content": "reply"}, {"role": "user", "content": "msg"}]
         with patch("langgraph.graph.state.CompiledStateGraph.ainvoke", new_callable=AsyncMock) as mock_invoke:
             mock_invoke.return_value = {"messages": [AIMessage(content="GM reply")], "rpg_state": {}}
             await run_agent(messages=messages_10, before_state={"state": {}}, api_key="fake", base_url="fake", model="fake")
             cfg = mock_invoke.call_args[1]["config"]
             assert cfg["configurable"]["plan_fired"] is False
             assert cfg["configurable"]["summary_fired"] is False
             assert cfg["configurable"]["cleanup_fired"] is True


@pytest.mark.asyncio
@patch("rpg_agent.agent.graph.call_openrouter_streaming", new_callable=AsyncMock)
async def test_new_orchestration_trigger_schedule(mock_streaming):
    from unittest.mock import patch, AsyncMock
    from langchain_core.messages import AIMessage
    from rpg_agent.agent.graph import run_agent

    mock_streaming.return_value = ("GM reply", None, [])

    # Setup:
    # Plan starts on Turn 2 (interval 8)
    # Summary starts on Turn 8 (interval 8)
    # Cleanup starts on Turn 9 (interval 8)
    with patch("rpg_agent.config.PLAN_TRIGGER_TYPE", "periodic"), \
         patch("rpg_agent.config.PLAN_INTERVAL_TURNS", 8), \
         patch("rpg_agent.config.PLAN_OFFSET", 2), \
         patch("rpg_agent.config.SUMMARY_TRIGGER_TYPE", "periodic"), \
         patch("rpg_agent.config.SUMMARY_INTERVAL_TURNS", 8), \
         patch("rpg_agent.config.PLAN_SUMMARY_GAP", 8), \
         patch("rpg_agent.config.CLEANUP_TRIGGER_TYPE", "periodic"), \
         patch("rpg_agent.config.CLEANUP_INTERVAL_TURNS", 8), \
         patch("rpg_agent.config.PLAN_CLEANUP_GAP", 9):

         # 1. Turn 1 (0 assistant messages in history): None should fire
         messages_1 = [{"role": "user", "content": "msg"}]
         with patch("langgraph.graph.state.CompiledStateGraph.ainvoke", new_callable=AsyncMock) as mock_invoke:
             mock_invoke.return_value = {"messages": [AIMessage(content="GM reply")], "rpg_state": {}}
             await run_agent(messages=messages_1, before_state={"state": {}}, api_key="fake", base_url="fake", model="fake")
             cfg = mock_invoke.call_args[1]["config"]
             assert cfg["configurable"]["plan_fired"] is False
             assert cfg["configurable"]["summary_fired"] is False
             assert cfg["configurable"]["cleanup_fired"] is False

         # 2. Turn 2 (1 assistant message in history): Plan fires, Summary and Cleanup do not
         messages_2 = [{"role": "user", "content": "msg"}] + [{"role": "assistant", "content": "reply"}, {"role": "user", "content": "msg"}] * 1
         with patch("langgraph.graph.state.CompiledStateGraph.ainvoke", new_callable=AsyncMock) as mock_invoke:
             mock_invoke.return_value = {"messages": [AIMessage(content="GM reply")], "rpg_state": {}}
             await run_agent(messages=messages_2, before_state={"state": {}}, api_key="fake", base_url="fake", model="fake")
             cfg = mock_invoke.call_args[1]["config"]
             assert cfg["configurable"]["plan_fired"] is True
             assert cfg["configurable"]["summary_fired"] is False
             assert cfg["configurable"]["cleanup_fired"] is False

         # 3. Turn 8 (7 assistant messages in history): Summary fires, Plan and Cleanup do not
         messages_8 = [{"role": "user", "content": "msg"}] + [{"role": "assistant", "content": "reply"}, {"role": "user", "content": "msg"}] * 7
         with patch("langgraph.graph.state.CompiledStateGraph.ainvoke", new_callable=AsyncMock) as mock_invoke:
             mock_invoke.return_value = {"messages": [AIMessage(content="GM reply")], "rpg_state": {}}
             await run_agent(messages=messages_8, before_state={"state": {}}, api_key="fake", base_url="fake", model="fake")
             cfg = mock_invoke.call_args[1]["config"]
             assert cfg["configurable"]["plan_fired"] is False
             assert cfg["configurable"]["summary_fired"] is True
             assert cfg["configurable"]["cleanup_fired"] is False

         # 4. Turn 9 (8 assistant messages in history): Cleanup fires, Plan and Summary do not
         messages_9 = [{"role": "user", "content": "msg"}] + [{"role": "assistant", "content": "reply"}, {"role": "user", "content": "msg"}] * 8
         with patch("langgraph.graph.state.CompiledStateGraph.ainvoke", new_callable=AsyncMock) as mock_invoke:
             mock_invoke.return_value = {"messages": [AIMessage(content="GM reply")], "rpg_state": {}}
             await run_agent(messages=messages_9, before_state={"state": {}}, api_key="fake", base_url="fake", model="fake")
             cfg = mock_invoke.call_args[1]["config"]
             assert cfg["configurable"]["plan_fired"] is False
             assert cfg["configurable"]["summary_fired"] is False
             assert cfg["configurable"]["cleanup_fired"] is True

         # 5. Turn 10 (9 assistant messages in history): Plan fires, Summary and Cleanup do not (every 8th turn: 2, 10, ...)
         messages_10 = [{"role": "user", "content": "msg"}] + [{"role": "assistant", "content": "reply"}, {"role": "user", "content": "msg"}] * 9
         with patch("langgraph.graph.state.CompiledStateGraph.ainvoke", new_callable=AsyncMock) as mock_invoke:
             mock_invoke.return_value = {"messages": [AIMessage(content="GM reply")], "rpg_state": {}}
             await run_agent(messages=messages_10, before_state={"state": {}}, api_key="fake", base_url="fake", model="fake")
             cfg = mock_invoke.call_args[1]["config"]
             assert cfg["configurable"]["plan_fired"] is True
             assert cfg["configurable"]["summary_fired"] is False
             assert cfg["configurable"]["cleanup_fired"] is False


@pytest.mark.asyncio
@patch("rpg_agent.agent.graph.call_openrouter_streaming", new_callable=AsyncMock)
async def test_dynamic_tool_disabling_after_call(mock_streaming):
    from unittest.mock import patch, AsyncMock
    from langchain_core.messages import HumanMessage, AIMessage
    from rpg_agent.agent.graph import _build_llm_node, AgentState
    from langchain_core.runnables import RunnableConfig

    mock_streaming.return_value = ("GM response", None, [])

    # HumanMessage followed by AIMessage that already called update_plan
    messages = [
        HumanMessage(content="user message"),
        AIMessage(content="", tool_calls=[{"name": "update_plan", "args": {"checklist": []}, "id": "call_1", "type": "tool_call"}]),
    ]

    state: AgentState = {
        "messages": messages,
        "rpg_state": {},
        "sandbox_timeout": 2.0,
        "iteration_count": 1
    }

    state_container = {"rpg_state": {}}

    llm_node_fn = _build_llm_node(
        api_key="fake",
        base_url="fake",
        model="fake",
        max_iterations=5,
        sandbox_timeout=2.0,
        state_container=state_container
    )

    config: RunnableConfig = {
        "configurable": {
            "bundle_plan_fired": True,
            "bundle_summary_fired": True,
        }
    }

    with patch("rpg_agent.agent.graph.get_system_instruction") as mock_get_instruction:
        mock_get_instruction.return_value = "System Prompt"
        await llm_node_fn(state, config)

        # Verify get_system_instruction was called with plan disabled but summary enabled
        kwargs = mock_get_instruction.call_args[1]
        assert kwargs["bundle_plan_fired"] is False
        assert kwargs["bundle_summary_fired"] is True


def test_system_instruction_dynamic_formatting():
    from rpg_agent.agent.prompts import get_system_instruction
    from langchain_core.messages import HumanMessage, AIMessage

    messages = [
        HumanMessage(content="Hello"),
        AIMessage(content="Welcome to the tavern!"),
        HumanMessage(content="I want to buy a drink."),
        AIMessage(content="Sure, that's 5 gold."),
        HumanMessage(content="Here is the gold."),
        AIMessage(content="Enjoy your ale!"),
    ]

    # Case 1: no plan / no summary triggers
    rpg_state = {
        "state": {"hp": 100},
        "plan": [],
        "summary": "",
        "hidden_state": {"last_plan_turn": 2, "last_summary_turn": 3}
    }
    instruction = get_system_instruction(
        rpg_state=rpg_state,
        sandbox_timeout=2.0,
        max_iterations=5,
        current_iteration=1,
        rem_iterations=4,
        messages=messages,
        engine_name="v8",
        bundle_plan_fired=False,
        bundle_summary_fired=False,
        turn_number=5
    )
    assert "Perform the following 1 task:" in instruction
    assert "- Task 1 of 1: Progress the story" in instruction
    assert "## Updating Plan" not in instruction
    assert "## Creating Summary to Append" not in instruction

    # Case 2: plan and summary triggers active
    instruction_both = get_system_instruction(
        rpg_state=rpg_state,
        sandbox_timeout=2.0,
        max_iterations=5,
        current_iteration=1,
        rem_iterations=4,
        messages=messages,
        engine_name="v8",
        bundle_plan_fired=True,
        bundle_summary_fired=True,
        turn_number=5
    )
    assert "Perform the following 3 tasks:" in instruction_both
    assert "- Task 1 of 3: Call the `update_plan` tool" in instruction_both
    assert "which was 3 turns ago" in instruction_both  # plan: 5 - 2 = 3
    # For plan (3 turns ago = 6 messages range: index 0 to 5)
    # Range is "Hello ... Enjoy your ale!"
    assert 'The range of developments is: "Hello ... Enjoy your ale!"' in instruction_both
    
    assert "- Task 2 of 3: Call the `append_summary` tool" in instruction_both
    assert "which was 2 turns ago" in instruction_both  # summary: 5 - 3 = 2
    # For summary (2 turns ago = 4 messages range: index 2 to 5)
    # Range is "I want to buy a drink. ... Enjoy your ale!"
    assert 'The range of messages to summarize is: "I want to buy a drink. ... Enjoy your ale!"' in instruction_both
    
    assert "- Task 3 of 3: Progress the story" in instruction_both
    assert "## Updating Plan" in instruction_both
    assert "## Creating Summary to Append" in instruction_both

    # Case 3: first turn (never updated)
    rpg_state_empty = {
        "state": {},
        "plan": [],
        "summary": "",
        "hidden_state": {}
    }
    instruction_first = get_system_instruction(
        rpg_state=rpg_state_empty,
        sandbox_timeout=2.0,
        max_iterations=5,
        current_iteration=1,
        rem_iterations=4,
        messages=messages[:2],
        engine_name="v8",
        bundle_plan_fired=True,
        bundle_summary_fired=True,
        turn_number=1
    )
    assert "which was 1 turns ago (at the start of the game)" in instruction_first

def test_middle_out_messages():
    from rpg_agent.agent.prompts import middle_out_messages
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    
    messages = [
        HumanMessage(content="Hello"),
        AIMessage(content="Welcome to the tavern!"),
        HumanMessage(content="I want to buy a drink."),
        AIMessage(content="Sure, that's 5 gold."),
        HumanMessage(content="Here is the gold."),
        AIMessage(content="Enjoy your ale!"),
    ]
    
    # Case 1: turns_since_update covers the entire history (no prefix length >= 2)
    # 3 turns = 6 messages. Prefix length = 0.
    result = middle_out_messages(messages, 3)
    assert len(result) == 6
    assert result == messages
    
    # Case 2: turns_since_update covers 2 turns (4 messages). Prefix length = 2.
    result_2 = middle_out_messages(messages, 2)
    assert len(result_2) == 5 # 1 condensed + 4 suffix
    assert isinstance(result_2[0], SystemMessage)
    assert "Hello" in result_2[0].content
    assert "Welcome to the tavern!" in result_2[0].content
    assert "<omitted for brevity>" in result_2[0].content
    # Check suffix
    assert result_2[1].content == "I want to buy a drink."
    assert result_2[4].content == "Enjoy your ale!"

def test_update_plan_status():
    from rpg_agent.agent.tools import make_tools
    state_container = {
        "current_turn": 5,
        "rpg_state": {
            "plan": [
                {"id": 1, "description": "Goal 1", "status": "to-do", "remark": ""},
                {"id": 2, "description": "Goal 2", "status": "in-progress", "remark": ""},
            ]
        }
    }
    tools = make_tools(state_container, 2.0)
    update_plan_status_tool = next(t for t in tools if t.name == "update_plan_status")
    
    res = update_plan_status_tool.invoke({"updates": [{"id": 1, "status": "done"}, {"id": "2", "status": "abandoned"}]})
    assert "Updated status of 2 plan items" in res
    plan = state_container["rpg_state"]["plan"]
    assert plan[0]["status"] == "done"
    assert plan[1]["status"] == "abandoned"


@pytest.mark.asyncio
@patch("rpg_agent.agent.graph.call_openrouter_streaming", new_callable=AsyncMock)
async def test_llm_node_remaining_iterations(mock_streaming):
    from unittest.mock import patch, AsyncMock
    from langchain_core.messages import HumanMessage
    from rpg_agent.agent.graph import _build_llm_node, AgentState
    from langchain_core.runnables import RunnableConfig

    mock_streaming.return_value = ("GM response", None, [])

    messages = [HumanMessage(content="user message")]

    state_container = {"rpg_state": {}}
    llm_node_fn = _build_llm_node(
        api_key="fake",
        base_url="fake",
        model="fake",
        max_iterations=5,
        sandbox_timeout=2.0,
        state_container=state_container
    )

    config: RunnableConfig = {"configurable": {}}

    # Test iteration 0 (1st run) -> rem_iterations should be 4
    state_0: AgentState = {
        "messages": messages,
        "rpg_state": {},
        "sandbox_timeout": 2.0,
        "iteration_count": 0
    }
    with patch("rpg_agent.agent.graph.get_system_instruction") as mock_get_instruction:
        mock_get_instruction.return_value = "System Prompt"
        await llm_node_fn(state_0, config)
        kwargs = mock_get_instruction.call_args[1]
        assert kwargs["rem_iterations"] == 4
        assert kwargs["current_iteration"] == 1

    # Test iteration 4 (5th run, final) -> rem_iterations should be 0
    state_4: AgentState = {
        "messages": messages,
        "rpg_state": {},
        "sandbox_timeout": 2.0,
        "iteration_count": 4
    }
    with patch("rpg_agent.agent.graph.get_system_instruction") as mock_get_instruction:
        mock_get_instruction.return_value = "System Prompt"
        await llm_node_fn(state_4, config)
        kwargs = mock_get_instruction.call_args[1]
        assert kwargs["rem_iterations"] == 0
        assert kwargs["current_iteration"] == 5





