"""Session Administration Endpoints Router."""

import logging
from fastapi import APIRouter, Depends
from rpg_agent.auth import require_proxy_key
from rpg_agent.config import STATE_STORAGE_DIR
from rpg_agent.state import SessionStateStore

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1",
    tags=["sessions"],
    dependencies=[Depends(require_proxy_key)],
)

@router.get("/sessions")
def list_sessions():
    """List session IDs present in the state directory."""
    return SessionStateStore.list_sessions(STATE_STORAGE_DIR)

@router.post("/sessions/{session_id}/reset")
def reset_session(session_id: str):
    """Reset the session store data for a specific session."""
    store = SessionStateStore(session_id, STATE_STORAGE_DIR)
    store.reset()
    return {"status": "ok", "message": f"Session {session_id} has been reset."}

@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    """Delete a session's data from disk entirely."""
    store = SessionStateStore(session_id, STATE_STORAGE_DIR)
    store.delete()
    return {"status": "ok", "message": f"Session {session_id} deleted."}
