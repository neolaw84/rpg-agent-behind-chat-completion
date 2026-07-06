"""Unit tests for state.py, sandbox.py, and session.py."""
import json
import tempfile
from pathlib import Path

import pytest

from rpg_agent.state import SessionStateStore
from rpg_agent.sandbox import execute_sandbox


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
    assert tmp_store.get_before_state(None) == {}


def test_save_and_reload(tmp_path):
    store = SessionStateStore("s1", tmp_path, max_size=8)
    store.save_turn("key1", {"hp": 100}, {"hp": 90})

    store2 = SessionStateStore("s1", tmp_path, max_size=8)
    assert store2.get_before_state("key1") == {"hp": 90}


def test_missing_key_raises(tmp_store):
    with pytest.raises(KeyError, match="not found"):
        tmp_store.get_before_state("nonexistent")


def test_fifo_eviction(tmp_path):
    store = SessionStateStore("s1", tmp_path, max_size=3)
    store.save_turn("k1", {}, {"a": 1})
    store.save_turn("k2", {}, {"a": 2})
    store.save_turn("k3", {}, {"a": 3})
    # Adding a 4th should evict k1
    store.save_turn("k4", {}, {"a": 4})
    with pytest.raises(KeyError):
        store.get_before_state("k1")
    assert store.get_before_state("k4") == {"a": 4}


def test_reset_clears_state(tmp_path):
    store = SessionStateStore("s1", tmp_path, max_size=8)
    store.save_turn("k1", {}, {"x": 1})
    store.reset()
    store2 = SessionStateStore("s1", tmp_path, max_size=8)
    assert store2.get_before_state(None) == {}


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

def test_sandbox_mutates_state():
    code = "state['hp'] -= 10"
    updated, output = execute_sandbox(code, {"hp": 100})
    assert updated["hp"] == 90


def test_sandbox_captures_stdout():
    code = "print('hello world')"
    _, output = execute_sandbox(code, {})
    assert "hello world" in output


def test_sandbox_blocks_os_import():
    code = "import os; os.system('echo pwned')"
    updated, output = execute_sandbox(code, {})
    assert "Sandbox Exception" in output or "import" in output.lower()


def test_sandbox_timeout():
    code = "while True: pass"
    updated, output = execute_sandbox(code, {}, timeout_seconds=0.3)
    assert "timed out" in output.lower()


def test_sandbox_exception_is_captured():
    code = "raise ValueError('oops')"
    updated, output = execute_sandbox(code, {})
    assert "ValueError" in output
    assert "oops" in output


def test_sandbox_non_dict_state_reverts():
    code = "state = 42"
    original = {"hp": 10}
    updated, output = execute_sandbox(code, original)
    assert updated == original
    assert "Warning" in output


def test_sandbox_allowed_imports_work():
    # Test importing whitelisted modules
    code = "import math\nstate['val'] = math.sqrt(16)"
    updated, output = execute_sandbox(code, {})
    assert updated.get("val") == 4.0

    code = "import random\nstate['rand'] = random.randint(1, 1)"
    updated, output = execute_sandbox(code, {})
    assert updated.get("rand") == 1


def test_sandbox_pre_injected_modules_work():
    # Test using math and random without explicit imports
    code = "state['val'] = math.floor(4.7)"
    updated, output = execute_sandbox(code, {})
    assert updated.get("val") == 4

    code = "state['rand'] = random.choice([42])"
    updated, output = execute_sandbox(code, {})
    assert updated.get("rand") == 42


def test_sandbox_blocks_unauthorized_imports():
    code = "import sys"
    updated, output = execute_sandbox(code, {})
    assert "ImportError" in output
    assert "sys" in output

