import json
import pytest
from unittest.mock import MagicMock, patch
from rachel.core.state import PostgresSessionStorage, _get_pg_pool


@pytest.fixture
def mock_pg():
    """Fixture to mock psycopg2 connection and pool."""
    with patch("psycopg2.pool.SimpleConnectionPool") as mock_pool_cls:
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool
        mock_conn = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        # Reset the global pool cache so it initializes again
        with patch("rachel.core.state._pg_pool", None):
            # Patch config credentials so pool creation doesn't fail
            with patch("rachel.config.DATABASE_URL", "postgresql://mock_user:mock_pass@localhost/mock_db"):
                yield {
                    "pool": mock_pool,
                    "conn": mock_conn,
                    "cur": mock_cur
                }


def test_postgres_storage_init(mock_pg):
    # Creating an instance triggers schema initialization
    storage = PostgresSessionStorage(session_id="test-session", max_size=5)
    
    # Assert that pool.getconn() was called
    mock_pg["pool"].getconn.assert_called()
    
    # Check that schema creation queries were executed
    calls = [call[0][0] for call in mock_pg["cur"].execute.call_args_list]
    assert any("CREATE TABLE IF NOT EXISTS session_turns" in q for q in calls)
    assert any("CREATE INDEX IF NOT EXISTS idx_session_turns_accessed_at" in q for q in calls)


def test_get_before_state_success(mock_pg):
    # Setup mock cursor output
    mock_pg["cur"].fetchone.return_value = ({"state": {"gold": 100}},)
    
    storage = PostgresSessionStorage(session_id="test-session", max_size=5)
    mock_pg["cur"].reset_mock()
    
    state = storage.get_before_state("abcdefabcdefabcdefabcdef")
    
    # Assert query
    mock_pg["cur"].execute.assert_any_call(
        "SELECT after_state FROM session_turns WHERE session_id = %s AND turn_key = %s;",
        ("test-session", "abcdefabcdefabcdefabcdef")
    )
    # Assert access time update
    mock_pg["cur"].execute.assert_any_call(
        "UPDATE session_turns SET accessed_at = CURRENT_TIMESTAMP WHERE session_id = %s AND turn_key = %s;",
        ("test-session", "abcdefabcdefabcdefabcdef")
    )
    assert state["state"] == {"gold": 100}


def test_get_before_state_none(mock_pg):
    storage = PostgresSessionStorage(session_id="test-session", max_size=5)
    mock_pg["cur"].reset_mock()
    
    state = storage.get_before_state(None)
    mock_pg["cur"].execute.assert_not_called()
    assert state == {"state": {}, "plan": [], "summary": "", "hidden_state": {}}


def test_get_before_state_not_found(mock_pg):
    mock_pg["cur"].fetchone.return_value = None
    
    storage = PostgresSessionStorage(session_id="test-session", max_size=5)
    
    with pytest.raises(KeyError):
        storage.get_before_state("abcdefabcdefabcdefabcdef")


def test_save_turn_and_lru_pruning(mock_pg):
    storage = PostgresSessionStorage(session_id="test-session", max_size=5)
    mock_pg["cur"].reset_mock()
    
    before = {"state": {"gold": 10}}
    after = {"state": {"gold": 20}}
    storage.save_turn("abcdefabcdefabcdefabcdef", before, after)
    
    # Check insert/upsert call
    args_list = [call[0] for call in mock_pg["cur"].execute.call_args_list]
    insert_query_called = any("INSERT INTO session_turns" in q[0] for q in args_list)
    assert insert_query_called
    
    # Check delete call for LRU pruning
    delete_query_called = any("DELETE FROM session_turns" in q[0] for q in args_list)
    assert delete_query_called


def test_reset_and_delete(mock_pg):
    storage = PostgresSessionStorage(session_id="test-session", max_size=5)
    mock_pg["cur"].reset_mock()
    
    storage.reset()
    mock_pg["cur"].execute.assert_called_with(
        "DELETE FROM session_turns WHERE session_id = %s;",
        ("test-session",)
    )
    
    mock_pg["cur"].reset_mock()
    storage.delete()
    mock_pg["cur"].execute.assert_called_with(
        "DELETE FROM session_turns WHERE session_id = %s;",
        ("test-session",)
    )


def test_get_all_turns(mock_pg):
    mock_pg["cur"].fetchall.return_value = [
        ("turn1", {"state": {"hp": 10}}, {"state": {"hp": 9}}),
        ("turn2", {"state": {"hp": 9}}, {"state": {"hp": 8}})
    ]
    
    storage = PostgresSessionStorage(session_id="test-session", max_size=5)
    turns = storage.get_all_turns()
    
    assert len(turns) == 2
    assert turns["turn1"]["before"]["state"] == {"hp": 10}
    assert turns["turn1"]["after"]["state"] == {"hp": 9}
    assert turns["turn2"]["before"]["state"] == {"hp": 9}
    assert turns["turn2"]["after"]["state"] == {"hp": 8}


def test_list_sessions(mock_pg):
    mock_pg["cur"].fetchall.return_value = [("session1",), ("session2",)]
    
    storage = PostgresSessionStorage(session_id="test-session", max_size=5)
    mock_pg["cur"].reset_mock()
    
    sessions = PostgresSessionStorage.list_sessions()
    mock_pg["cur"].execute.assert_called_with(
        "SELECT DISTINCT session_id FROM session_turns ORDER BY session_id;"
    )
    assert sessions == ["session1", "session2"]


def test_import_data(mock_pg):
    storage = PostgresSessionStorage(session_id="test-session", max_size=5)
    mock_pg["cur"].reset_mock()
    
    data = {
        "abcdefabcdefabcdefabcdef": {
            "before": {"state": {"gold": 10}},
            "after": {"state": {"gold": 20}}
        }
    }
    storage.import_data(data)
    
    args_list = [call[0] for call in mock_pg["cur"].execute.call_args_list]
    
    # Should delete existing first
    assert args_list[0][0] == "DELETE FROM session_turns WHERE session_id = %s;"
    
    # Should insert new turn
    insert_call = args_list[1]
    assert "INSERT INTO session_turns" in insert_call[0]
    assert insert_call[1][0] == "test-session"
    assert insert_call[1][1] == "abcdefabcdefabcdefabcdef"
