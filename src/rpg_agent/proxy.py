"""OpenRouter Chat Completion Proxy.

Receives chat completion payloads from JanitorAI, resolves the session and
turn key, loads/validates the FIFO session state, runs the LangGraph agent
(LLM + code sandbox + dice tools), persists the updated state, and returns
the final assistant message to the client with a proxy metadata annotation
prepended to the message text.

Endpoints
---------
POST /v1/chat/completions
POST /v1/{session_id}/chat/completions  — explicit session override
GET  /v1/sessions                       — list active sessions
POST /v1/sessions/{session_id}/reset    — clear a session's state
DELETE /v1/sessions/{session_id}        — delete a session from disk
GET  /health
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from rpg_agent.graph import run_agent
from rpg_agent.session import compute_turn_key, resolve_session_id
from rpg_agent.state import SessionStateStore

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent
_CONFIG_PATH = _REPO_ROOT / "configs.yaml"

def _load_config() -> dict[str, Any]:
    if _CONFIG_PATH.exists():
        with _CONFIG_PATH.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    logger.warning("configs.yaml not found at %s — using defaults.", _CONFIG_PATH)
    return {}

_cfg = _load_config()
_state_cfg     = _cfg.get("state", {})
_sandbox_cfg   = _cfg.get("sandbox", {})
_langgraph_cfg = _cfg.get("langgraph", {})

NUM_STATES_TO_TRACK: int   = int(_state_cfg.get("num_states_to_track", 8))
STATE_STORAGE_DIR: Path    = _REPO_ROOT / _state_cfg.get("storage_dir", "data/states")
SANDBOX_TIMEOUT: float     = float(_sandbox_cfg.get("timeout_seconds", 2.0))
MAX_ITERATIONS: int        = int(_langgraph_cfg.get("max_iterations", 5))

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Payload log
PAYLOAD_LOG_PATH = _REPO_ROOT / "data" / "example-janitorai-payload.md"

# Proxy key
_KEY_FILE = _REPO_ROOT / "proxy.key"

# Pattern to extract turn_key from a proxy-annotated assistant message.
_TURN_KEY_RE = re.compile(r"\[proxy:.*?turn=([a-f0-9]{24})", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Proxy API key
# ---------------------------------------------------------------------------

def _load_or_generate_proxy_key() -> str:
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    key = secrets.token_urlsafe(32)
    _KEY_FILE.write_text(key + "\n", encoding="utf-8")
    return key

PROXY_API_KEY: str = _load_or_generate_proxy_key()
_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(
        "\n" + "=" * 60 + "\n"
        f"  Proxy API Key (use as Bearer token):\n"
        f"  {PROXY_API_KEY}\n"
        + "=" * 60 + "\n"
    )
    logger.info(
        "Config loaded: states=%d, timeout=%.1fs, max_iter=%d",
        NUM_STATES_TO_TRACK, SANDBOX_TIMEOUT, MAX_ITERATIONS,
    )
    yield


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="OpenRouter RPG Agent Proxy",
    description=(
        "Proxy that forwards JanitorAI requests to OpenRouter through a "
        "LangGraph agent with code sandbox and dice-rolling tools."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def _require_proxy_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, PROXY_API_KEY
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing proxy API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise HTTPException(
            status_code=500,
            detail=(
                "OPENROUTER_API_KEY environment variable is not set. "
                "Please create a .env file with OPENROUTER_API_KEY=<your-key>."
            ),
        )
    return key


def _extract_prev_turn_key(messages: list[dict]) -> str | None:
    """Scan the messages list (newest first) for the last assistant message
    that carries a ``[proxy: ... turn=<key>]`` annotation.

    Returns the turn key string, or None if no annotated assistant message is
    found (which is the expected case on the first turn).
    """
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content") or ""
        match = _TURN_KEY_RE.search(content)
        if match:
            return match.group(1)
    return None


def _log_request(
    request: Request,
    payload: dict[str, Any],
    session_id: str,
    session_method: str,
    turn_key: str,
    prev_turn_key: str | None,
) -> None:
    """Append request metadata and body to the payload log file."""
    import json
    from datetime import datetime, timezone

    PAYLOAD_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=timezone.utc).isoformat()

    meta = {
        "method": request.method,
        "url": str(request.url),
        "client": (
            f"{request.client.host}:{request.client.port}"
            if request.client else "unknown"
        ),
        "session_id": session_id,
        "session_method": session_method,
        "turn_key": turn_key,
        "prev_turn_key": prev_turn_key,
    }

    headers_dict = dict(request.headers)
    if "authorization" in headers_dict:
        headers_dict["authorization"] = "Bearer <REDACTED>"

    entry = (
        f"\n---\n\n"
        f"## Request captured at {timestamp}\n\n"
        f"**Session**: `{session_id}` _(resolved via {session_method})_\n"
        f"**Turn key**: `{turn_key}` | **Prev turn key**: `{prev_turn_key}`\n\n"
        f"### Metadata\n\n"
        f"```json\n{json.dumps(meta, indent=2, ensure_ascii=False)}\n```\n\n"
        f"### Headers\n\n"
        f"```json\n{json.dumps(headers_dict, indent=2, ensure_ascii=False)}\n```\n\n"
        f"### Body\n\n"
        f"```json\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n```\n"
    )

    with PAYLOAD_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(entry)

    logger.info(
        "Logged request [session=%s turn=%s prev=%s]",
        session_id, turn_key, prev_turn_key,
    )


# ---------------------------------------------------------------------------
# Chat completion endpoint
# ---------------------------------------------------------------------------

@app.post("/v1/chat/completions", dependencies=[Depends(_require_proxy_key)])
@app.post("/v1/{session_id}/chat/completions", dependencies=[Depends(_require_proxy_key)])
async def proxy_chat_completions(
    request: Request,
    session_id: str | None = None,
) -> Any:
    """Proxy a chat completion request through the LangGraph RPG agent.

    Session ID resolution (highest → lowest priority):
      1. URL path segment ``/v1/{session_id}/chat/completions``
      2. Query parameter ``?session_id=…``
      3. ``[session: name]`` OOC tag inside any message (newest first)
      4. MD5 suffix hash of system prompt + username from last user message

    State rehydration:
      - <= 2 messages → first turn, before_state = {}
      - > 2 messages  → extract prev_turn_key from last assistant message;
                        raise HTTP 400 if not found in the session store
    """
    api_key = _get_api_key()

    explicit_sid = session_id or request.query_params.get("session_id")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc

    messages: list[dict] = payload.get("messages", [])
    model: str = payload.get("model", "google/gemini-flash-1.5")

    # --- Session & turn resolution ---
    resolved_sid, sid_method = resolve_session_id(
        messages, explicit_session_id=explicit_sid
    )
    turn_key = compute_turn_key(resolved_sid, messages)
    prev_turn_key = _extract_prev_turn_key(messages)

    logger.info(
        "Session: %s (via %s) | Turn: %s | Prev: %s",
        resolved_sid, sid_method, turn_key, prev_turn_key,
    )

    # --- Load session state ---
    store = SessionStateStore(
        session_id=resolved_sid,
        storage_dir=STATE_STORAGE_DIR,
        max_size=NUM_STATES_TO_TRACK,
    )

    is_first_turn = len(messages) <= 2
    if is_first_turn:
        before_state: dict[str, Any] = {}
    else:
        try:
            before_state = store.get_before_state(prev_turn_key)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    _log_request(request, payload, resolved_sid, sid_method, turn_key, prev_turn_key)

    is_streaming = payload.get("stream", False)

    if is_streaming:
        stream_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

        # Run the agent in the background as a task
        agent_task = asyncio.create_task(
            run_agent(
                messages=messages,
                before_state=before_state,
                api_key=api_key,
                base_url=OPENROUTER_BASE_URL,
                model=model,
                sandbox_timeout=SANDBOX_TIMEOUT,
                max_iterations=MAX_ITERATIONS,
                stream_queue=stream_queue,
            )
        )

        async def stream_generator():
            import json as _json
            import time as _time

            # 1. Prepend proxy metadata as the first standard content chunk
            annotation = f"[proxy: session={resolved_sid} turn={turn_key}]\n\n"
            first_chunk = _json.dumps({
                "id": f"proxy-{turn_key}",
                "object": "chat.completion.chunk",
                "created": int(_time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": annotation},
                    "finish_reason": None,
                }],
            })
            yield f"data: {first_chunk}\n\n".encode()

            # 2. Concurrently consume queue items and yield them as SSE chunks
            while not agent_task.done() or not stream_queue.empty():
                try:
                    event_type, text = await asyncio.wait_for(stream_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                delta = {}
                if event_type in ("reasoning", "tool_log"):
                    delta = {"reasoning_content": text}
                else:
                    delta = {"content": text}

                chunk = _json.dumps({
                    "id": f"proxy-{turn_key}",
                    "object": "chat.completion.chunk",
                    "created": int(_time.time()),
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": delta,
                        "finish_reason": None,
                    }],
                })
                yield f"data: {chunk}\n\n".encode()
                stream_queue.task_done()

            # 3. Finalize and persist state
            try:
                result = await agent_task
                after_state = result["after_state"]
                store.save_turn(turn_key, before_state, after_state)
            except Exception as exc:
                logger.error("Agent task failed: %s", exc)
                err_chunk = _json.dumps({
                    "id": f"proxy-{turn_key}",
                    "object": "chat.completion.chunk",
                    "created": int(_time.time()),
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": f"\n\n[Proxy Error: {exc}]"},
                        "finish_reason": "error",
                    }],
                })
                yield f"data: {err_chunk}\n\n".encode()

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
        )
    else:
        # Non-streaming response
        try:
            result = await run_agent(
                messages=messages,
                before_state=before_state,
                api_key=api_key,
                base_url=OPENROUTER_BASE_URL,
                model=model,
                sandbox_timeout=SANDBOX_TIMEOUT,
                max_iterations=MAX_ITERATIONS,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Agent execution failed: {exc}") from exc

        after_state = result["after_state"]
        final_content = result["content"]
        final_reasoning = result.get("reasoning_content") or ""

        # Persist state
        store.save_turn(turn_key, before_state, after_state)

        # Prepend session metadata annotation
        annotation = f"[proxy: session={resolved_sid} turn={turn_key}]\n\n"
        full_content = annotation + final_content

        resp_payload: dict[str, Any] = {
            "id": f"proxy-{turn_key}",
            "object": "chat.completion",
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": full_content,
                },
                "finish_reason": "stop",
            }],
            "usage": {},
        }
        if final_reasoning:
            resp_payload["choices"][0]["message"]["reasoning_content"] = final_reasoning

        return JSONResponse(resp_payload)


# ---------------------------------------------------------------------------
# Session CRUD endpoints
# ---------------------------------------------------------------------------

@app.get("/v1/sessions", dependencies=[Depends(_require_proxy_key)])
async def list_sessions() -> dict[str, Any]:
    """List all active session IDs stored on disk."""
    sessions = SessionStateStore.list_sessions(STATE_STORAGE_DIR)
    return {"sessions": sessions, "count": len(sessions)}


@app.post(
    "/v1/sessions/{session_id}/reset",
    dependencies=[Depends(_require_proxy_key)],
)
async def reset_session(session_id: str) -> dict[str, str]:
    """Clear the FIFO state history for a session (keeps the session ID)."""
    store = SessionStateStore(
        session_id=session_id,
        storage_dir=STATE_STORAGE_DIR,
        max_size=NUM_STATES_TO_TRACK,
    )
    store.reset()
    return {"status": "reset", "session_id": session_id}


@app.delete(
    "/v1/sessions/{session_id}",
    dependencies=[Depends(_require_proxy_key)],
)
async def delete_session(session_id: str) -> dict[str, str]:
    """Delete a session's state file from disk entirely."""
    store = SessionStateStore(
        session_id=session_id,
        storage_dir=STATE_STORAGE_DIR,
        max_size=NUM_STATES_TO_TRACK,
    )
    store.delete()
    return {"status": "deleted", "session_id": session_id}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok"}
