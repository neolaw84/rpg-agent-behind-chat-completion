"""Session Administration Endpoints Router."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from rachel.auth import require_proxy_key
from rachel.config import STATE_STORAGE_DIR
from rachel.core.state import get_session_storage, list_all_sessions

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1",
    tags=["sessions"],
    dependencies=[Depends(require_proxy_key)],
)

@router.get("/sessions")
def list_sessions():
    """List session IDs present in the state storage."""
    sessions = list_all_sessions(STATE_STORAGE_DIR)
    return {"sessions": sessions, "count": len(sessions)}

@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    """Return the full state JSON for a specific session."""
    store = get_session_storage(session_id, storage_dir=STATE_STORAGE_DIR)
    turns = []
    for turn_key, turn_data in store.get_all_turns().items():
        turns.append({
            "turn_key": turn_key,
            "before": turn_data.get("before", {}),
            "after": turn_data.get("after", {}),
        })
    if not turns:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found or has no state.")
    # The most recent turn's "after" is the current live state
    current_state = turns[-1]["after"] if turns else {}
    return {
        "session_id": session_id,
        "current_state": current_state,
        "turn_count": len(turns),
        "turns": turns,
    }

@router.post("/sessions/{session_id}/reset")
def reset_session(session_id: str):
    """Reset the session store data for a specific session."""
    store = get_session_storage(session_id, storage_dir=STATE_STORAGE_DIR)
    store.reset()
    return {"status": "ok", "message": f"Session {session_id} has been reset."}

@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    """Delete a session's data from storage entirely."""
    store = get_session_storage(session_id, storage_dir=STATE_STORAGE_DIR)
    store.delete()
    return {"status": "ok", "message": f"Session {session_id} deleted."}

@router.get("/sessions/{session_id}/export")
def export_session(session_id: str):
    """Return the raw internal dictionary for a session to be exported."""
    store = get_session_storage(session_id, storage_dir=STATE_STORAGE_DIR)
    data = store.get_all_turns()
    if not data:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found or has no state.")
    return data

@router.post("/sessions/{session_id}/import")
def import_session(session_id: str, data: dict):
    """Import and validate raw session dictionary."""
    store = get_session_storage(session_id, storage_dir=STATE_STORAGE_DIR)
    try:
        store.import_data(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "message": f"Session {session_id} imported."}


