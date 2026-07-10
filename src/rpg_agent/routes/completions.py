"""Chat Completion Endpoint Router.

Handles ``POST /v1/chat/completions`` and
``POST /v1/{session_id}/chat/completions``, running the LangGraph RPG agent
and returning either a streaming SSE response or a standard JSON response.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import time as _time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from rpg_agent.auth import require_proxy_key
from rpg_agent.config import (
    MAX_ITERATIONS,
    NUM_STATES_TO_TRACK,
    OPENROUTER_BASE_URL,
    SANDBOX_TIMEOUT,
    STATE_STORAGE_DIR,
)
from rpg_agent.graph import run_agent
from rpg_agent.session import (
    compute_turn_key,
    extract_prev_turn_key,
    resolve_session_id,
    strip_proxy_annotations,
)
from rpg_agent.state import SessionStateStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["completions"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """Read the OpenRouter API key from the environment or raise HTTP 500."""
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


def _log_request(
    request: Request,
    payload: dict[str, Any],
    session_id: str,
    session_method: str,
    turn_key: str,
    prev_turn_key: str | None,
) -> None:
    """Log request metadata and body at debug level."""
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

    logger.debug(
        "Incoming Request: session_id=%s turn_key=%s prev_turn_key=%s. "
        "Meta: %s | Headers: %s | Payload: %s",
        session_id,
        turn_key,
        prev_turn_key,
        _json.dumps(meta, ensure_ascii=False),
        _json.dumps(headers_dict, ensure_ascii=False),
        _json.dumps(payload, ensure_ascii=False),
    )


def _make_sse_chunk(
    turn_key: str,
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> bytes:
    """Serialise a single SSE data chunk and return it as UTF-8 bytes."""
    chunk = _json.dumps({
        "id": f"proxy-{turn_key}",
        "object": "chat.completion.chunk",
        "created": int(_time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason,
        }],
    })
    return f"data: {chunk}\n\n".encode()


# ---------------------------------------------------------------------------
# Streaming generator (top-level, not a closure)
# ---------------------------------------------------------------------------

async def _stream_generator(
    *,
    agent_task: asyncio.Task,
    stream_queue: asyncio.Queue[tuple[str, str]],
    resolved_sid: str,
    turn_key: str,
    model: str,
    cache_miss: bool,
    store: SessionStateStore,
    before_state: dict[str, Any],
):
    """Consume the agent stream queue and yield SSE-formatted bytes.

    Steps:
    1. Emit the proxy annotation as the very first content chunk.
    2. Drain the queue until the agent task finishes.
    3. Optionally emit a cache-miss OOC notice.
    4. Await the agent task, persist state, and emit any error chunk.
    """
    # 1. Proxy annotation (first chunk)
    annotation = f"[proxy: session={resolved_sid} turn={turn_key}]\n\n"
    yield _make_sse_chunk(turn_key, model, {"role": "assistant", "content": annotation})

    # 2. Drain queue
    while not agent_task.done() or not stream_queue.empty():
        try:
            event_type, text = await asyncio.wait_for(stream_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            continue

        if event_type in ("reasoning", "tool_log"):
            delta: dict[str, Any] = {"reasoning_content": text}
        else:
            delta = {"content": text}

        yield _make_sse_chunk(turn_key, model, delta)
        stream_queue.task_done()

    # 3. Cache-miss OOC notice
    if cache_miss:
        ooc_text = (
            "\n\n(OOC: A state cache miss occurred. "
            "The proxy has generated a new session and made a best-effort restoration.)"
        )
        yield _make_sse_chunk(turn_key, model, {"content": ooc_text})

    # 4. Persist state (or surface error)
    try:
        result = await agent_task
        after_state = result["after_state"]
        store.save_turn(turn_key, before_state, after_state)
    except Exception as exc:
        logger.error("Agent task failed: %s", exc)
        yield _make_sse_chunk(
            turn_key, model,
            {"content": f"\n\n[Proxy Error: {exc}]"},
            finish_reason="error",
        )


# ---------------------------------------------------------------------------
# Chat completion endpoint
# ---------------------------------------------------------------------------

@router.post("/v1/chat/completions", dependencies=[Depends(require_proxy_key)])
@router.post("/v1/{session_id}/chat/completions", dependencies=[Depends(require_proxy_key)])
async def proxy_chat_completions(
    request: Request,
    session_id: str | None = None,
) -> Any:
    """Proxy a chat completion request through the LangGraph RPG agent."""
    api_key = _get_api_key()

    explicit_sid = session_id or request.query_params.get("session_id")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc

    messages: list[dict] = payload.get("messages", [])
    model: str = payload.get("model") or os.environ.get("DEFAULT_MODEL") or "google/gemini-flash-1.5"

    # --- Session & turn resolution ---
    resolved_sid, sid_method = resolve_session_id(
        messages, explicit_session_id=explicit_sid
    )
    turn_key = compute_turn_key(resolved_sid, messages)
    prev_turn_key = extract_prev_turn_key(messages)

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
    cache_miss = False
    if is_first_turn:
        before_state: dict[str, Any] = {}
    else:
        try:
            before_state = store.get_before_state(prev_turn_key)
        except KeyError:
            logger.warning(
                "Cache miss on turn key %s in session %s. Treating as a new session.",
                prev_turn_key,
                resolved_sid,
            )
            cache_miss = True
            before_state = {}

    _log_request(request, payload, resolved_sid, sid_method, turn_key, prev_turn_key)

    # Strip [proxy: ...] annotations from messages before hitting the LLM.
    # Session/turn resolution has already consumed them above, so it is safe
    # to remove them now.  This prevents LLMs from echoing the annotation.
    messages = strip_proxy_annotations(messages)

    is_streaming = payload.get("stream", False)

    if is_streaming:
        stream_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

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

        return StreamingResponse(
            _stream_generator(
                agent_task=agent_task,
                stream_queue=stream_queue,
                resolved_sid=resolved_sid,
                turn_key=turn_key,
                model=model,
                cache_miss=cache_miss,
                store=store,
                before_state=before_state,
            ),
            media_type="text/event-stream",
        )

    # --- Non-streaming ---
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
    if cache_miss:
        ooc_text = (
            "\n\n(OOC: A state cache miss occurred. "
            "The proxy has generated a new session and made a best-effort restoration.)"
        )
        final_content += ooc_text
    final_reasoning = result.get("reasoning_content") or ""

    store.save_turn(turn_key, before_state, after_state)

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
