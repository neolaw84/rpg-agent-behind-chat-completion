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
from rachel.core.db import Session as SessionModel, get_engine, get_sessionmaker, init_db

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
        from rachel.config import STATE_STORAGE_DIR
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
        from rachel.config import STATE_STORAGE_DIR
        d = Path(storage_dir) if storage_dir is not None else Path(STATE_STORAGE_DIR)
        if not d.exists():
            return []
        return [p.stem for p in sorted(d.glob("*.json"))]


# ---------------------------------------------------------------------------
# Unified Relational Storage Engine (SQLite + PostgreSQL)
# ---------------------------------------------------------------------------

class RelationalSessionStorage(BaseSessionStorage):
    """Unified relational database session storage engine (SQLite + PostgreSQL)."""

    def __init__(
        self,
        session_id: str,
        max_size: int = 8,
        tenant_id: str = "local",
        engine: Any = None,
        db_url: str | None = None,
    ) -> None:
        super().__init__(session_id, max_size)
        self.tenant_id = tenant_id
        self.engine = engine or get_engine(db_url)
        init_db(engine=self.engine)
        self.SessionMaker = get_sessionmaker(self.engine)

    def _load_session_record(self, db_session: Any) -> SessionModel | None:
        return (
            db_session.query(SessionModel)
            .filter_by(tenant_id=self.tenant_id, session_id=self.session_id)
            .first()
        )

    def get_before_state(self, prev_turn_key: str | None) -> dict[str, Any]:
        if prev_turn_key is None:
            return _migrate_state({})

        with self.SessionMaker() as session:
            record = self._load_session_record(session)
            if not record or not record.turns_data:
                raise KeyError(
                    f"turn_key '{prev_turn_key}' not found in session '{self.session_id}' database."
                )
            turns_data = json.loads(record.turns_data) if record.turns_data else {}
            if prev_turn_key not in turns_data:
                raise KeyError(
                    f"turn_key '{prev_turn_key}' not found in session '{self.session_id}' database."
                )

            val = turns_data.pop(prev_turn_key)
            turns_data[prev_turn_key] = val
            record.turns_data = json.dumps(turns_data, ensure_ascii=False)
            session.commit()
            return _migrate_state(val.get("after", {}))

    def save_turn(
        self,
        turn_key: str,
        before_state: dict[str, Any],
        after_state: dict[str, Any],
    ) -> None:
        with self.SessionMaker() as session:
            record = self._load_session_record(session)
            if not record:
                record = SessionModel(
                    tenant_id=self.tenant_id,
                    session_id=self.session_id,
                    turns_data="{}",
                )
                session.add(record)

            turns_data = json.loads(record.turns_data) if record.turns_data else {}
            if turn_key in turns_data:
                del turns_data[turn_key]
            turns_data[turn_key] = {
                "before": _migrate_state(before_state),
                "after": _migrate_state(after_state),
            }

            while len(turns_data) > self.max_size:
                oldest_key = next(iter(turns_data))
                del turns_data[oldest_key]
                logger.debug(
                    "LRU: evicted turn %s from session %s", oldest_key, self.session_id
                )

            record.turns_data = json.dumps(turns_data, ensure_ascii=False)
            session.commit()

    def reset(self) -> None:
        with self.SessionMaker() as session:
            record = self._load_session_record(session)
            if record:
                session.delete(record)
                session.commit()
            logger.info("Session %s has been reset in DB.", self.session_id)

    def delete(self) -> None:
        self.reset()

    def import_data(self, data: dict[str, Any]) -> None:
        validated_data = _validate_and_normalize_import(data)
        with self.SessionMaker() as session:
            record = self._load_session_record(session)
            if not record:
                record = SessionModel(
                    tenant_id=self.tenant_id,
                    session_id=self.session_id,
                )
                session.add(record)
            record.turns_data = json.dumps(validated_data, ensure_ascii=False)
            session.commit()
            logger.info("Session %s successfully imported to DB.", self.session_id)

    def get_all_turns(self) -> dict[str, dict[str, Any]]:
        with self.SessionMaker() as session:
            record = self._load_session_record(session)
            if not record or not record.turns_data:
                return {}
            turns = json.loads(record.turns_data)
            return {
                tk: {
                    "before": _migrate_state(tv.get("before", {})),
                    "after": _migrate_state(tv.get("after", {})),
                }
                for tk, tv in turns.items()
            }

    @classmethod
    def list_sessions(
        cls,
        storage_dir: Any = None,
        tenant_id: str = "local",
        engine: Any = None,
        db_url: str | None = None,
    ) -> list[str]:
        eng = engine or get_engine(db_url)
        init_db(engine=eng)
        sm = get_sessionmaker(eng)
        with sm() as session:
            records = (
                session.query(SessionModel.session_id)
                .filter_by(tenant_id=tenant_id)
                .order_by(SessionModel.session_id)
                .all()
            )
            return [r[0] for r in records]


class PostgresSessionStorage(RelationalSessionStorage):
    """PostgreSQL-backed session storage engine (alias to RelationalSessionStorage)."""
    pass


# ---------------------------------------------------------------------------
# Factory & Backward Compatibility Wrapper
# ---------------------------------------------------------------------------

def get_session_storage(
    session_id: str,
    max_size: int = 8,
    storage_dir: Any = None,
    tenant_id: str = "local",
) -> BaseSessionStorage:
    """Factory to instantiate the configured storage engine."""
    from rachel.config import STORAGE_ENGINE
    if STORAGE_ENGINE.lower() in ("sqlite", "postgres", "sql", "relational"):
        return RelationalSessionStorage(session_id, max_size, tenant_id=tenant_id)
    return FileSessionStorage(session_id, max_size, storage_dir)


def list_all_sessions(storage_dir: Any = None, tenant_id: str = "local") -> list[str]:
    """Helper function to list all sessions using the active engine."""
    from rachel.config import STORAGE_ENGINE
    if STORAGE_ENGINE.lower() in ("sqlite", "postgres", "sql", "relational"):
        return RelationalSessionStorage.list_sessions(storage_dir=storage_dir, tenant_id=tenant_id)
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

