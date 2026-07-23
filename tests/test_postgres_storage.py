"""Tests for PostgresSessionStorage (built on RelationalSessionStorage & SQLAlchemy)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from rachel.core.db import init_db
from rachel.core.state import PostgresSessionStorage


@pytest.fixture
def pg_engine():
    """SQLite in-memory engine with StaticPool mimicking Postgres relational storage behavior."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine=engine)
    return engine


def test_postgres_storage_init(pg_engine):
    """Creating PostgresSessionStorage initializes storage engine."""
    storage = PostgresSessionStorage(session_id="test-session-init", max_size=5, engine=pg_engine)
    assert storage.session_id == "test-session-init"
    assert storage.max_size == 5


def test_get_before_state_success(pg_engine):
    """Retrieve before state after saving a turn."""
    storage = PostgresSessionStorage(session_id="test-session-before", max_size=5, engine=pg_engine)
    tk = "abcdefabcdefabcdefabcdef"
    storage.save_turn(tk, {"state": {"gold": 50}}, {"state": {"gold": 100}})

    state = storage.get_before_state(tk)
    assert state["state"] == {"gold": 100}


def test_get_before_state_none(pg_engine):
    """Return initial blank state when turn key is None."""
    storage = PostgresSessionStorage(session_id="test-session-none", max_size=5, engine=pg_engine)
    state = storage.get_before_state(None)
    assert state == {"state": {}, "plan": [], "summary": "", "hidden_state": {}}


def test_get_before_state_not_found(pg_engine):
    """Raise KeyError when turn key is not present."""
    storage = PostgresSessionStorage(session_id="test-session-notfound", max_size=5, engine=pg_engine)
    with pytest.raises(KeyError):
        storage.get_before_state("nonexistentturnkey1234567")


def test_save_turn_and_lru_pruning(pg_engine):
    """Verify in-memory zero-sort LRU pruning on turn limit."""
    storage = PostgresSessionStorage(session_id="test-session-lru", max_size=2, engine=pg_engine)

    tk1 = "1" * 24
    tk2 = "2" * 24
    tk3 = "3" * 24

    storage.save_turn(tk1, {"v": 1}, {"v": 2})
    storage.save_turn(tk2, {"v": 2}, {"v": 3})
    storage.save_turn(tk3, {"v": 3}, {"v": 4})

    turns = storage.get_all_turns()
    assert len(turns) == 2
    assert tk1 not in turns
    assert tk2 in turns
    assert tk3 in turns


def test_reset_and_delete(pg_engine):
    """Verify reset and delete purge session turns."""
    storage = PostgresSessionStorage(session_id="test-session-reset", max_size=5, engine=pg_engine)
    tk = "a" * 24
    storage.save_turn(tk, {"hp": 10}, {"hp": 5})

    storage.reset()
    assert len(storage.get_all_turns()) == 0

    storage.save_turn(tk, {"hp": 10}, {"hp": 5})
    storage.delete()
    assert len(storage.get_all_turns()) == 0


def test_get_all_turns(pg_engine):
    """Retrieve full history of turns."""
    storage = PostgresSessionStorage(session_id="test-session-turns", max_size=5, engine=pg_engine)
    tk1 = "1" * 24
    tk2 = "2" * 24

    storage.save_turn(tk1, {"hp": 10}, {"hp": 9})
    storage.save_turn(tk2, {"hp": 9}, {"hp": 8})

    turns = storage.get_all_turns()
    assert len(turns) == 2
    assert turns[tk1]["before"]["state"] == {"hp": 10}
    assert turns[tk1]["after"]["state"] == {"hp": 9}
    assert turns[tk2]["before"]["state"] == {"hp": 9}
    assert turns[tk2]["after"]["state"] == {"hp": 8}


def test_list_sessions(pg_engine):
    """List session IDs in postgres storage."""
    s1 = PostgresSessionStorage(session_id="session1", max_size=5, engine=pg_engine)
    s2 = PostgresSessionStorage(session_id="session2", max_size=5, engine=pg_engine)

    s1.save_turn("a" * 24, {}, {})
    s2.save_turn("b" * 24, {}, {})

    sessions = PostgresSessionStorage.list_sessions(engine=pg_engine)
    assert "session1" in sessions
    assert "session2" in sessions


def test_import_data(pg_engine):
    """Import JSON data into postgres storage."""
    storage = PostgresSessionStorage(session_id="test-session-import", max_size=5, engine=pg_engine)
    tk = "abcdefabcdefabcdefabcdef"
    data = {
        tk: {
            "before": {"state": {"gold": 10}},
            "after": {"state": {"gold": 20}}
        }
    }
    storage.import_data(data)
    turns = storage.get_all_turns()
    assert tk in turns
    assert turns[tk]["after"]["state"] == {"gold": 20}
