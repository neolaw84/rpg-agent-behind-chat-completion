"""Session State Store — FIFO, file-backed.

Each session is persisted as a single JSON file:
    data/states/{session_id}.json

The file contains an ordered dictionary (insertion order maintained in Python
3.7+) where:
  - keys   → turn_key (24-char hex string)
  - values → {"before": {...}, "after": {...}}

When the number of entries exceeds ``max_size`` (``num_states_to_track`` in
configs.yaml), the oldest entry is dropped (FIFO).

Best-effort guarantee: If the user edits or retries a turn, the turn key will
change.  The store is a cache — not the source of truth.  Any state must be
re-derivable from the messages array alone.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionStateStore:
    """Load, update, and persist a single session's FIFO state store."""

    def __init__(self, session_id: str, storage_dir: Path, max_size: int = 8) -> None:
        self.session_id = session_id
        self.storage_dir = Path(storage_dir)
        self.max_size = max_size
        self._path = self.storage_dir / f"{session_id}.json"
        self._data: dict[str, dict[str, Any]] = self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # FIFO access
    # ------------------------------------------------------------------

    def get_before_state(self, prev_turn_key: str | None) -> dict[str, Any]:
        """Return the ``after`` state of the previous turn (= ``before`` of the
        current turn), or an empty dict if this is the first turn.

        Raises:
            KeyError: If ``prev_turn_key`` is given but not found in the store.
        """
        if prev_turn_key is None:
            return {}
        if prev_turn_key not in self._data:
            raise KeyError(
                f"turn_key '{prev_turn_key}' not found in session '{self.session_id}'. "
                "The state history may have been lost (proxy restart, FIFO eviction, or "
                "the client sent a continuation without a prior proxy-annotated turn)."
            )
        return dict(self._data[prev_turn_key].get("after", {}))

    def save_turn(
        self,
        turn_key: str,
        before_state: dict[str, Any],
        after_state: dict[str, Any],
    ) -> None:
        """Persist a completed turn's before/after state, pruning if needed."""
        self._data[turn_key] = {"before": before_state, "after": after_state}
        # Prune oldest entries if we exceed the FIFO limit.
        while len(self._data) > self.max_size:
            oldest_key = next(iter(self._data))
            del self._data[oldest_key]
            logger.debug("FIFO: evicted turn %s from session %s", oldest_key, self.session_id)
        self._save()

    # ------------------------------------------------------------------
    # CRUD helpers (used by proxy CRUD endpoints)
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all state for this session (but keep the file)."""
        self._data = {}
        self._save()
        logger.info("Session %s has been reset.", self.session_id)

    def delete(self) -> None:
        """Remove the session file from disk entirely."""
        if self._path.exists():
            self._path.unlink()
            logger.info("Session %s deleted.", self.session_id)
        self._data = {}

    # ------------------------------------------------------------------
    # Class-level helpers
    # ------------------------------------------------------------------

    @classmethod
    def list_sessions(cls, storage_dir: Path) -> list[str]:
        """Return a list of session IDs present on disk."""
        d = Path(storage_dir)
        if not d.exists():
            return []
        return [p.stem for p in sorted(d.glob("*.json"))]
