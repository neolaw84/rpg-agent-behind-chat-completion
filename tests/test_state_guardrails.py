"""Unit tests for RPG state validation and codebase guardrails."""

import pytest
import copy
from unittest.mock import patch
from rachel.agent.tools import make_tools
from rachel.sandbox.sandbox import get_sandbox_engine
import rachel.config as config

@pytest.fixture
def clean_state():
    return {
        "state": {
            "hp": 100,
            "location": "town",
            "inventory": ["sword", "shield"]
        },
        "plan": [],
        "summary": "",
        "hidden_state": {
            "quest_stage": 1,
            "secret_flag": False
        }
    }

def get_code_for_engine(engine_name, action):
    if engine_name == "python":
        if action == "valid":
            return "state['hp'] = 90\nhidden_state['secret_flag'] = True"
        elif action == "long_string":
            return "state['location'] = 'a' * 100"
        elif action == "wide_dict":
            return "state['wide'] = {str(i): i for i in range(50)}"
        elif action == "deep_dict":
            return "state['deep'] = {'a': {'b': {'c': {'d': {'e': 42}}}}}"
    else:  # JS / V8
        if action == "valid":
            return "state.hp = 90; hidden_state.secret_flag = true;"
        elif action == "long_string":
            return "state.location = 'a'.repeat(100);"
        elif action == "wide_dict":
            return "state.wide = {}; for (let i = 0; i < 50; i++) { state.wide[i.toString()] = i; }"
        elif action == "deep_dict":
            return "state.deep = {a: {b: {c: {d: {e: 42}}}}};"
    return ""

def test_validation_success(clean_state):
    state_container = {"rpg_state": clean_state}
    tools = make_tools(state_container, 2.0)
    sandbox_tool = next(t for t in tools if t.name == "execute_code_sandbox")
    
    engine = get_sandbox_engine()
    code = get_code_for_engine(engine.name, "valid")
    
    result = sandbox_tool.invoke({"code": code})
    
    assert "Sandbox Validation Error" not in result
    assert state_container["rpg_state"]["state"]["hp"] == 90
    assert state_container["rpg_state"]["hidden_state"]["secret_flag"] is True

def test_validation_string_too_long(clean_state):
    state_container = {"rpg_state": clean_state}
    original_state = copy.deepcopy(clean_state)
    tools = make_tools(state_container, 2.0)
    sandbox_tool = next(t for t in tools if t.name == "execute_code_sandbox")
    
    engine = get_sandbox_engine()
    code = get_code_for_engine(engine.name, "long_string")
    
    with patch("rachel.config.MAX_STRING_LENGTH", 80):
        result = sandbox_tool.invoke({"code": code})
        
    assert "Sandbox Validation Error" in result
    assert "String length limit exceeded" in result
    assert "wasted one tool call" in result
    # State must be completely reverted to original
    assert state_container["rpg_state"] == original_state

def test_validation_wide_structure(clean_state):
    state_container = {"rpg_state": clean_state}
    original_state = copy.deepcopy(clean_state)
    tools = make_tools(state_container, 2.0)
    sandbox_tool = next(t for t in tools if t.name == "execute_code_sandbox")
    
    engine = get_sandbox_engine()
    code = get_code_for_engine(engine.name, "wide_dict")
    
    with patch("rachel.config.MAX_WIDTH", 32):
        result = sandbox_tool.invoke({"code": code})
        
    assert "Sandbox Validation Error" in result
    assert "State width limit exceeded" in result
    assert "wasted one tool call" in result
    assert state_container["rpg_state"] == original_state

def test_validation_deep_structure(clean_state):
    state_container = {"rpg_state": clean_state}
    original_state = copy.deepcopy(clean_state)
    tools = make_tools(state_container, 2.0)
    sandbox_tool = next(t for t in tools if t.name == "execute_code_sandbox")
    
    engine = get_sandbox_engine()
    code = get_code_for_engine(engine.name, "deep_dict")
    
    with patch("rachel.config.MAX_DEPTH", 4):
        result = sandbox_tool.invoke({"code": code})
        
    assert "Sandbox Validation Error" in result
    assert "State nesting depth limit exceeded" in result
    assert "wasted one tool call" in result
    assert state_container["rpg_state"] == original_state
