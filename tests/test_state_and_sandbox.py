"""Unit tests for state.py, sandbox.py, and session.py."""
import json
import tempfile
from pathlib import Path

import pytest

from rpg_agent.core.state import SessionStateStore
from rpg_agent.sandbox.sandbox import execute_sandbox


# ---------------------------------------------------------------------------
# SessionStateStore tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_store(tmp_path):
    return SessionStateStore(
        session_id="test-session",
        storage_dir=tmp_path,
        max_size=3,
    )


def test_first_turn_returns_empty_state(tmp_store):
    assert tmp_store.get_before_state(None) == {
        "state": {},
        "plan": [],
        "summary": "",
        "hidden_state": {},
    }


def test_save_and_reload(tmp_path):
    store = SessionStateStore("s1", tmp_path, max_size=8)
    store.save_turn("key1", {"hp": 100}, {"hp": 90})

    store2 = SessionStateStore("s1", tmp_path, max_size=8)
    assert store2.get_before_state("key1") == {
        "state": {"hp": 90},
        "plan": [],
        "summary": "",
        "hidden_state": {},
    }


def test_missing_key_raises(tmp_store):
    with pytest.raises(KeyError, match="not found"):
        tmp_store.get_before_state("nonexistent")


def test_lru_eviction(tmp_path):
    store = SessionStateStore("s1", tmp_path, max_size=3)
    store.save_turn("k1", {}, {"a": 1})
    store.save_turn("k2", {}, {"a": 2})
    store.save_turn("k3", {}, {"a": 3})
    # Access k1 so it becomes the most recently used (MRU)
    assert store.get_before_state("k1") == {
        "state": {"a": 1},
        "plan": [],
        "summary": "",
        "hidden_state": {},
    }
    # Adding a 4th should evict k2 (LRU), not k1 (accessed) or k3 (newer)
    store.save_turn("k4", {}, {"a": 4})
    with pytest.raises(KeyError, match="not found"):
        store.get_before_state("k2")
    assert store.get_before_state("k1") == {
        "state": {"a": 1},
        "plan": [],
        "summary": "",
        "hidden_state": {},
    }
    assert store.get_before_state("k3") == {
        "state": {"a": 3},
        "plan": [],
        "summary": "",
        "hidden_state": {},
    }
    assert store.get_before_state("k4") == {
        "state": {"a": 4},
        "plan": [],
        "summary": "",
        "hidden_state": {},
    }


def test_reset_clears_state(tmp_path):
    store = SessionStateStore("s1", tmp_path, max_size=8)
    store.save_turn("k1", {}, {"x": 1})
    store.reset()
    store2 = SessionStateStore("s1", tmp_path, max_size=8)
    assert store2.get_before_state(None) == {
        "state": {},
        "plan": [],
        "summary": "",
        "hidden_state": {},
    }


def test_delete_removes_file(tmp_path):
    store = SessionStateStore("s1", tmp_path, max_size=8)
    store.save_turn("k1", {}, {"x": 1})
    store.delete()
    assert not (tmp_path / "s1.json").exists()


def test_list_sessions(tmp_path):
    for sid in ["alpha", "beta", "gamma"]:
        s = SessionStateStore(sid, tmp_path, max_size=8)
        s.save_turn("k1", {}, {})
    sessions = SessionStateStore.list_sessions(tmp_path)
    assert sorted(sessions) == ["alpha", "beta", "gamma"]


# ---------------------------------------------------------------------------
# Sandbox tests
# ---------------------------------------------------------------------------

from rpg_agent.sandbox.sandbox import PythonSandboxEngine, V8SandboxEngine

# --- Python Engine Tests ---

def test_python_sandbox_mutates_state():
    engine = PythonSandboxEngine()
    code = "state['hp'] -= 10"
    updated, output = engine.execute(code, {"hp": 100})
    assert updated["hp"] == 90


def test_python_sandbox_captures_stdout():
    engine = PythonSandboxEngine()
    code = "print('hello world')"
    _, output = engine.execute(code, {})
    assert "hello world" in output


def test_python_sandbox_blocks_os_import():
    engine = PythonSandboxEngine()
    code = "import os; os.system('echo pwned')"
    updated, output = engine.execute(code, {})
    assert "Sandbox Exception" in output or "import" in output.lower()


def test_python_sandbox_timeout():
    engine = PythonSandboxEngine()
    code = "while True: pass"
    updated, output = engine.execute(code, {}, timeout_seconds=0.3)
    assert "timed out" in output.lower()


def test_python_sandbox_exception_is_captured():
    engine = PythonSandboxEngine()
    code = "raise ValueError('oops')"
    updated, output = engine.execute(code, {})
    assert "ValueError" in output
    assert "oops" in output


def test_python_sandbox_non_dict_state_reverts():
    engine = PythonSandboxEngine()
    code = "state = 42"
    original = {"hp": 10}
    updated, output = engine.execute(code, original)
    assert updated == original
    assert "Warning" in output


def test_python_sandbox_allowed_imports_work():
    engine = PythonSandboxEngine()
    # Test importing whitelisted modules
    code = (
        "import math, random, json, datetime, collections, itertools, functools, re, string\n"
        "state['val'] = math.sqrt(16)\n"
        "state['rand'] = random.randint(1, 1)\n"
        "state['now'] = datetime.date(2026, 7, 8).isoformat()\n"
        "state['cnt'] = collections.Counter([1, 1])[1]\n"
    )
    updated, output = engine.execute(code, {})
    assert updated.get("val") == 4.0
    assert updated.get("rand") == 1
    assert updated.get("now") == "2026-07-08"
    assert updated.get("cnt") == 2


def test_python_sandbox_pre_injected_modules_work():
    engine = PythonSandboxEngine()
    # Test using math and random without explicit imports
    code = "state['val'] = math.floor(4.7)"
    updated, output = engine.execute(code, {})
    assert updated.get("val") == 4

    code = "state['rand'] = random.choice([42])"
    updated, output = engine.execute(code, {})
    assert updated.get("rand") == 42


def test_python_sandbox_blocks_unauthorized_imports():
    engine = PythonSandboxEngine()
    code = "import sys"
    updated, output = engine.execute(code, {})
    assert "ImportError" in output
    assert "sys" in output


# --- V8 Engine Tests ---

def test_v8_sandbox_mutates_state():
    engine = V8SandboxEngine()
    code = "state.hp -= 10;"
    updated, output = engine.execute(code, {"hp": 100})
    assert updated["hp"] == 90


def test_v8_sandbox_captures_stdout():
    engine = V8SandboxEngine()
    code = "console.log('hello world');"
    _, output = engine.execute(code, {})
    assert "hello world" in output


def test_v8_sandbox_timeout():
    engine = V8SandboxEngine()
    code = "while (true) {}"
    updated, output = engine.execute(code, {}, timeout_seconds=0.3)
    assert "timed out" in output.lower()


def test_v8_sandbox_exception_is_captured():
    engine = V8SandboxEngine()
    code = "throw new Error('oops');"
    updated, output = engine.execute(code, {})
    assert "Error" in output
    assert "oops" in output


def test_v8_sandbox_non_dict_state_reverts():
    engine = V8SandboxEngine()
    code = "state = 42;"
    original = {"hp": 10}
    updated, output = engine.execute(code, original)
    assert updated == original
    assert "Warning" in output


# ---------------------------------------------------------------------------
# Session tests
# ---------------------------------------------------------------------------

from rpg_agent.core.session import (
    resolve_session_id,
    extract_system_suffix_hash,
    extract_session_from_proxy_annotation,
    extract_first_assistant_suffix_hash,
)
import hashlib

def test_extract_system_suffix_hash_scans_newest_to_oldest():
    messages = [
        {"role": "system", "content": "This is system prompt A"},
        {"role": "user", "content": "Hello"},
        {"role": "system", "content": "This is system prompt B"},
    ]
    
    # It should extract from the newest (bottom-most) system message, which is "This is system prompt B"
    hash_b = extract_system_suffix_hash([{"role": "system", "content": "This is system prompt B"}])
    assert extract_system_suffix_hash(messages) == hash_b


def test_extract_session_from_proxy_annotation():
    # 1. No assistant message
    assert extract_session_from_proxy_annotation([{"role": "user", "content": "Hi"}]) is None

    # 2. Assistant message without annotation
    assert extract_session_from_proxy_annotation([
        {"role": "assistant", "content": "Hello player!"}
    ]) is None

    # 3. Newest first scan
    messages = [
        {"role": "assistant", "content": "[proxy: session=old-session turn=xyz]\n\nFirst"},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "[proxy: session=new-session turn=abc]\n\nSecond"},
    ]
    assert extract_session_from_proxy_annotation(messages) == "new-session"


def test_extract_first_assistant_suffix_hash():
    # 1. No assistant message
    assert extract_first_assistant_suffix_hash([{"role": "user", "content": "Hi"}]) is None

    # 2. Assistant message with whitespace and proxy block
    messages = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "[proxy: session=sess turn=xyz]\n\nHello   World \n\n Good game. "},
        {"role": "assistant", "content": "Should be ignored since it is the second assistant message."},
    ]
    # Content of first assistant: "Hello   World \n\n Good game. "
    # Stripped proxy: "Hello   World \n\n Good game. "
    # Stripped whitespace: "HelloWorldGoodgame."
    # len("HelloWorldGoodgame.") is 19. Suffix is "HelloWorldGoodgame."
    expected_hash = hashlib.md5(b"HelloWorldGoodgame.").hexdigest()[:16]
    assert extract_first_assistant_suffix_hash(messages) == expected_hash


def test_resolve_session_id_4_levels():
    messages = [
        {"role": "system", "content": "System prompt info"},
        {"role": "assistant", "content": "[proxy: session=prox-sess turn=xyz]\n\nHello player"},
        {"role": "user", "content": "Shan Yu: [session: ooc-sess] I attack!"},
    ]

    # Level 1: Explicit session ID
    assert resolve_session_id(messages, explicit_session_id="explicit-sess") == ("explicit-sess", "explicit")

    # Level 2: OOC tag
    assert resolve_session_id(messages) == ("ooc-sess", "ooc-tag")

    # Level 3: Proxy annotation (no OOC tag)
    messages_no_ooc = [
        {"role": "system", "content": "System prompt info"},
        {"role": "assistant", "content": "[proxy: session=prox-sess turn=xyz]\n\nHello player"},
        {"role": "user", "content": "Shan Yu: I attack!"},
    ]
    assert resolve_session_id(messages_no_ooc) == ("prox-sess", "proxy-annotation")

    # Level 4: First assistant suffix hash + username hash (no OOC, no proxy annotation)
    messages_fallback = [
        {"role": "system", "content": "System prompt info"},
        {"role": "assistant", "content": "Hello World. Good game."},
        {"role": "user", "content": "Shan Yu: I attack!"},
    ]
    # Suffix hash for "HelloWorld.Goodgame." is md5 of it.
    asst_hash = hashlib.md5(b"HelloWorld.Goodgame.").hexdigest()[:16]
    # Username hash for "Shan Yu" is md5 of it.
    u_hash = hashlib.md5(b"Shan Yu").hexdigest()[:16]
    expected_l4 = f"{asst_hash}__{u_hash}"
    assert resolve_session_id(messages_fallback) == (expected_l4, "assistant-suffix-hash+username-hash")

    # Level 4: Only username hash (no assistant message yet)
    messages_no_asst = [
        {"role": "system", "content": "System prompt info"},
        {"role": "user", "content": "Shan Yu: I attack!"},
    ]
    assert resolve_session_id(messages_no_asst) == (u_hash, "assistant-suffix-hash+username-hash")


def test_roll_xdy_python_tool():
    from rpg_agent.agent.tools import make_tools, get_dice_interpretation
    
    interp = get_dice_interpretation(4, {4: "crit fail", 8: "fail", 16: "success", 18: "crit success"})
    assert interp == "crit fail"
    interp_8 = get_dice_interpretation(5, {4: "crit fail", 8: "fail", 16: "success", 18: "crit success"})
    assert interp_8 == "fail"

    state_container = {"rpg_state": {}}
    tools = {t.name: t for t in make_tools(state_container, 2.0)}
    assert "random_int" not in tools
    
    res = tools["roll_xdy"].invoke({
        "num_dice": 3,
        "num_sides": 6,
        "interpretation": {4: "crit fail", 8: "fail", 16: "success", 18: "crit success"}
    })
    assert isinstance(res, dict)
    assert len(res["rolls"]) == 3
    assert res["total"] == sum(res["rolls"])
    assert res["interpretation"].startswith("interpretation of the dice roll is '")


def test_roll_xdy_in_v8_sandbox():
    from rpg_agent.sandbox.v8_engine import V8SandboxEngine
    engine = V8SandboxEngine()
    code = """
    var res = roll_xdy(3, 6, {"4": "crit fail", "8": "fail", "16": "success", "18": "crit success"});
    state.res = res;
    """
    updated_state, output = engine.execute(code, {}, 2.0)
    assert "res" in updated_state
    res = updated_state["res"]
    assert isinstance(res["rolls"], list) and len(res["rolls"]) == 3
    assert res["total"] == sum(res["rolls"])
    assert res["interpretation"].startswith("interpretation of the dice roll is '")
    assert "interpretation of the dice roll is '" in output


def test_roll_xdy_in_python_sandbox():
    from rpg_agent.sandbox.python_engine import PythonSandboxEngine
    engine = PythonSandboxEngine()
    code = """
res = roll_xdy(3, 6, {4: "crit fail", 8: "fail", 16: "success", 18: "crit success"})
state['res'] = res
"""
    updated_state, output = engine.execute(code, {}, 2.0)
    assert "res" in updated_state
    res = updated_state["res"]
    assert isinstance(res["rolls"], list) and len(res["rolls"]) == 3
    assert res["total"] == sum(res["rolls"])
    assert res["interpretation"].startswith("interpretation of the dice roll is '")
    assert "interpretation of the dice roll is '" in output



