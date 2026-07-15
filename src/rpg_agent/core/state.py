"""Session State Store — SOLID, file-backed and PostgreSQL implementations.

Adheres to:
- S: Separate classes for File and PostgreSQL storage.
- O: Easy to add new storage engines by inheriting from BaseSessionStorage.
- L: Interchangeable storage engines implementing abstract methods.
- I: Exposes clean interfaces.
- D: Routers depend on abstractions rather than details.
"""

from __future__ import annotations

import abc
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _migrate_state(state_dict: dict[str, Any]) -> dict[str, Any]:
    """Migrate state to the 4-element structure (state, plan, summary, hidden_state) if needed."""
    if any(k in state_dict for k in ("state", "plan", "summary", "hidden_state")):
        return {
            "state": state_dict.get("state", {}),
            "plan": state_dict.get("plan", []),
            "summary": state_dict.get("summary", ""),
            "hidden_state": state_dict.get("hidden_state", {}),
        }
    return {
        "state": state_dict,
        "plan": [],
        "summary": "",
        "hidden_state": {},
    }


def _validate_and_normalize_import(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate data structure and normalize states for imported session data."""
    if not isinstance(data, dict):
        raise ValueError("Imported data must be a JSON object.")

    validated: dict[str, dict[str, Any]] = {}
    for turn_key, turn_info in data.items():
        if not isinstance(turn_key, str) or len(turn_key) != 24:
            raise ValueError(f"Invalid turn key '{turn_key}': must be a 24-character string.")
        if not isinstance(turn_info, dict):
            raise ValueError(f"Value for turn '{turn_key}' must be a JSON object.")
        if "before" not in turn_info or "after" not in turn_info:
            raise ValueError(f"Turn '{turn_key}' must contain both 'before' and 'after' keys.")
        before_val = turn_info["before"]
        after_val = turn_info["after"]
        if not isinstance(before_val, dict) or not isinstance(after_val, dict):
            raise ValueError(f"The 'before' and 'after' properties of turn '{turn_key}' must be JSON objects.")

        validated[turn_key] = {
            "before": _migrate_state(before_val),
            "after": _migrate_state(after_val),
        }
    return validated



class BaseSessionStorage(abc.ABC):
    """Abstract base class defining the Session Storage Interface (SOLID)."""

    def __init__(self, session_id: str, max_size: int = 8) -> None:
        self.session_id = session_id
        self.max_size = max_size

    @abc.abstractmethod
    def get_before_state(self, prev_turn_key: str | None) -> dict[str, Any]:
        """Return the 'after' state of the previous turn, or an empty dict if first turn."""
        pass

    @abc.abstractmethod
    def save_turn(
        self,
        turn_key: str,
        before_state: dict[str, Any],
        after_state: dict[str, Any],
    ) -> None:
        """Persist a completed turn's before/after state, pruning if needed (LRU limit)."""
        pass

    @abc.abstractmethod
    def reset(self) -> None:
        """Clear all state/history for this session."""
        pass

    @abc.abstractmethod
    def delete(self) -> None:
        """Remove the session entirely from the storage medium."""
        pass

    @abc.abstractmethod
    def import_data(self, data: dict[str, Any]) -> None:
        """Validate structure, normalize states, and save imported data."""
        pass

    @abc.abstractmethod
    def get_all_turns(self) -> dict[str, dict[str, Any]]:
        """Return the raw internal dictionary of all turns (turn_key -> before/after)."""
        pass

    @classmethod
    @abc.abstractmethod
    def list_sessions(cls, storage_dir: Any = None) -> list[str]:
        """Return a list of session IDs present in storage."""
        pass


class FileSessionStorage(BaseSessionStorage):
    """JSON file-backed session storage engine."""

    def __init__(self, session_id: str, max_size: int = 8, storage_dir: Any = None) -> None:
        super().__init__(session_id, max_size)
        from rpg_agent.config import STATE_STORAGE_DIR
        self.storage_dir = Path(storage_dir) if storage_dir is not None else Path(STATE_STORAGE_DIR)
        self._path = self.storage_dir / f"{session_id}.json"
        self._data: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        """Load the session file from disk, or return an empty dict."""
        if self._path.exists():
            try:
                text = self._path.read_text(encoding="utf-8")
                return json.loads(text)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load session %s: %s", self.session_id, exc)
        return {}

    def _save(self) -> None:
        """Persist the current in-memory state to disk."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_before_state(self, prev_turn_key: str | None) -> dict[str, Any]:
        if prev_turn_key is None:
            return _migrate_state({})
        if prev_turn_key not in self._data:
            raise KeyError(
                f"turn_key '{prev_turn_key}' not found in session '{self.session_id}' file."
            )
        val = self._data.pop(prev_turn_key)
        self._data[prev_turn_key] = val
        self._save()
        return _migrate_state(val.get("after", {}))

    def save_turn(
        self,
        turn_key: str,
        before_state: dict[str, Any],
        after_state: dict[str, Any],
    ) -> None:
        if turn_key in self._data:
            del self._data[turn_key]
        self._data[turn_key] = {
            "before": _migrate_state(before_state),
            "after": _migrate_state(after_state),
        }
        while len(self._data) > self.max_size:
            oldest_key = next(iter(self._data))
            del self._data[oldest_key]
            logger.debug("LRU: evicted turn %s from session %s", oldest_key, self.session_id)
        self._save()

    def reset(self) -> None:
        self._data = {}
        self._save()
        logger.info("Session %s has been reset in file.", self.session_id)

    def delete(self) -> None:
        if self._path.exists():
            self._path.unlink()
            logger.info("Session %s file deleted.", self.session_id)
        self._data = {}

    def import_data(self, data: dict[str, Any]) -> None:
        self._data = _validate_and_normalize_import(data)
        self._save()
        logger.info("Session %s successfully imported to file.", self.session_id)

    def get_all_turns(self) -> dict[str, dict[str, Any]]:
        return self._data

    @classmethod
    def list_sessions(cls, storage_dir: Any = None) -> list[str]:
        from rpg_agent.config import STATE_STORAGE_DIR
        d = Path(storage_dir) if storage_dir is not None else Path(STATE_STORAGE_DIR)
        if not d.exists():
            return []
        return [p.stem for p in sorted(d.glob("*.json"))]


# ---------------------------------------------------------------------------
# PostgreSQL Storage Engine
# ---------------------------------------------------------------------------

_pg_pool: Any = None


def _get_pg_pool() -> Any:
    global _pg_pool
    if _pg_pool is None:
        import psycopg2.pool
        from rpg_agent.config import (
            DATABASE_URL,
            PGDATABASE,
            PGHOST,
            PGPASSWORD,
            PGPORT,
            PGUSER,
        )

        if DATABASE_URL:
            _pg_pool = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)
        else:
            conn_kwargs = {}
            if PGHOST:
                conn_kwargs["host"] = PGHOST
            if PGPORT:
                conn_kwargs["port"] = PGPORT
            if PGUSER:
                conn_kwargs["user"] = PGUSER
            if PGPASSWORD:
                conn_kwargs["password"] = PGPASSWORD
            if PGDATABASE:
                conn_kwargs["database"] = PGDATABASE
            if not conn_kwargs:
                raise ValueError(
                    "No PostgreSQL credentials found. Please set DATABASE_URL or PG* environment variables."
                )
            _pg_pool = psycopg2.pool.SimpleConnectionPool(1, 10, **conn_kwargs)

        # Initialize schema
        conn = _pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS session_turns (
                        session_id VARCHAR(255) NOT NULL,
                        turn_key VARCHAR(24) NOT NULL,
                        before_state JSONB NOT NULL,
                        after_state JSONB NOT NULL,
                        accessed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (session_id, turn_key)
                    );
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_session_turns_accessed_at 
                    ON session_turns (session_id, accessed_at DESC);
                """)
                conn.commit()
        finally:
            _pg_pool.putconn(conn)

    return _pg_pool


class PostgresSessionStorage(BaseSessionStorage):
    """PostgreSQL-backed session storage engine."""

    def __init__(self, session_id: str, max_size: int = 8) -> None:
        super().__init__(session_id, max_size)
        _get_pg_pool()

    def get_before_state(self, prev_turn_key: str | None) -> dict[str, Any]:
        if prev_turn_key is None:
            return _migrate_state({})

        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT after_state FROM session_turns WHERE session_id = %s AND turn_key = %s;",
                    (self.session_id, prev_turn_key),
                )
                row = cur.fetchone()
                if not row:
                    raise KeyError(
                        f"turn_key '{prev_turn_key}' not found in session '{self.session_id}' database."
                    )
                cur.execute(
                    "UPDATE session_turns SET accessed_at = CURRENT_TIMESTAMP WHERE session_id = %s AND turn_key = %s;",
                    (self.session_id, prev_turn_key),
                )
                conn.commit()
                return _migrate_state(row[0])
        finally:
            pool.putconn(conn)

    def save_turn(
        self,
        turn_key: str,
        before_state: dict[str, Any],
        after_state: dict[str, Any],
    ) -> None:
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO session_turns (session_id, turn_key, before_state, after_state, accessed_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (session_id, turn_key)
                    DO UPDATE SET before_state = EXCLUDED.before_state, after_state = EXCLUDED.after_state, accessed_at = CURRENT_TIMESTAMP;
                    """,
                    (
                        self.session_id,
                        turn_key,
                        json.dumps(_migrate_state(before_state)),
                        json.dumps(_migrate_state(after_state)),
                    ),
                )
                cur.execute(
                    """
                    DELETE FROM session_turns
                    WHERE session_id = %s
                      AND turn_key NOT IN (
                          SELECT turn_key
                          FROM session_turns
                          WHERE session_id = %s
                          ORDER BY accessed_at DESC, turn_key DESC
                          LIMIT %s
                      );
                    """,
                    (self.session_id, self.session_id, self.max_size),
                )
                conn.commit()
        finally:
            pool.putconn(conn)

    def reset(self) -> None:
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM session_turns WHERE session_id = %s;", (self.session_id,))
                conn.commit()
            logger.info("Session %s has been reset in DB.", self.session_id)
        finally:
            pool.putconn(conn)

    def delete(self) -> None:
        self.reset()

    def import_data(self, data: dict[str, Any]) -> None:
        validated_data = _validate_and_normalize_import(data)

        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM session_turns WHERE session_id = %s;", (self.session_id,))
                for idx, (turn_key, turn_info) in enumerate(validated_data.items()):
                    cur.execute(
                        """
                        INSERT INTO session_turns (session_id, turn_key, before_state, after_state, accessed_at)
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP + INTERVAL '%s second');
                        """,
                        (
                            self.session_id,
                            turn_key,
                            json.dumps(turn_info["before"]),
                            json.dumps(turn_info["after"]),
                            idx,
                        ),
                    )
                conn.commit()
            logger.info("Session %s successfully imported to DB.", self.session_id)
        finally:
            pool.putconn(conn)

    def get_all_turns(self) -> dict[str, dict[str, Any]]:
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT turn_key, before_state, after_state FROM session_turns WHERE session_id = %s ORDER BY accessed_at ASC;",
                    (self.session_id,),
                )
                rows = cur.fetchall()
                turns = {}
                for row in rows:
                    turns[row[0]] = {
                        "before": _migrate_state(row[1]),
                        "after": _migrate_state(row[2]),
                    }
                return turns
        finally:
            pool.putconn(conn)

    @classmethod
    def list_sessions(cls, storage_dir: Any = None) -> list[str]:
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT session_id FROM session_turns ORDER BY session_id;")
                rows = cur.fetchall()
                return [row[0] for row in rows]
        finally:
            pool.putconn(conn)


# ---------------------------------------------------------------------------
# Factory & Backward Compatibility Wrapper
# ---------------------------------------------------------------------------

def get_session_storage(session_id: str, max_size: int = 8, storage_dir: Any = None) -> BaseSessionStorage:
    """Factory to instantiate the configured storage engine."""
    from rpg_agent.config import STORAGE_ENGINE
    if STORAGE_ENGINE == "postgres":
        return PostgresSessionStorage(session_id, max_size)
    return FileSessionStorage(session_id, max_size, storage_dir)


def list_all_sessions(storage_dir: Any = None) -> list[str]:
    """Helper function to list all sessions using the active engine."""
    from rpg_agent.config import STORAGE_ENGINE
    if STORAGE_ENGINE == "postgres":
        return PostgresSessionStorage.list_sessions(storage_dir)
    return FileSessionStorage.list_sessions(storage_dir)


class SessionStateStore(BaseSessionStorage):
    """Compatibility wrapper delegator that directs operations to the configured engine."""

    def __init__(self, session_id: str, storage_dir: Any = None, max_size: int = 8) -> None:
        super().__init__(session_id, max_size)
        self._delegate = get_session_storage(session_id, max_size, storage_dir)

    def get_before_state(self, prev_turn_key: str | None) -> dict[str, Any]:
        return self._delegate.get_before_state(prev_turn_key)

    def save_turn(
        self,
        turn_key: str,
        before_state: dict[str, Any],
        after_state: dict[str, Any],
    ) -> None:
        self._delegate.save_turn(turn_key, before_state, after_state)

    def reset(self) -> None:
        self._delegate.reset()

    def delete(self) -> None:
        self._delegate.delete()

    def import_data(self, data: dict[str, Any]) -> None:
        self._delegate.import_data(data)

    def get_all_turns(self) -> dict[str, dict[str, Any]]:
        return self._delegate.get_all_turns()

    @property
    def _data(self) -> dict[str, dict[str, Any]]:
        return self._delegate.get_all_turns()

    @classmethod
    def list_sessions(cls, storage_dir: Any = None) -> list[str]:
        return list_all_sessions(storage_dir)
