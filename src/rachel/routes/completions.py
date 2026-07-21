"""Chat Completion Endpoint Router.

Handles ``POST /v1/chat/completions`` and
``POST /v1/{session_id}/chat/completions``, running the LangGraph RPG agent
and returning either a streaming SSE response or a standard JSON response.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import time as _time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from rachel.auth import require_proxy_key
from rachel.config import (
    MAX_ITERATIONS,
    NUM_STATES_TO_TRACK,
    SANDBOX_TIMEOUT,
    STATE_STORAGE_DIR,
)
from rachel.agent.graph import run_agent
from rachel.core.session import (
    compute_turn_key,
    extract_prev_turn_key,
    resolve_session_id,
    strip_proxy_annotations,
)
from rachel.core.state import BaseSessionStorage, get_session_storage
from rachel.core.settings_storage import get_settings_storage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["completions"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_active_provider_config() -> tuple[str, str, str, str]:
    """Retrieve active provider configuration and credentials from SettingsStorage."""
    storage = get_settings_storage()
    active_provider, base_url, api_key, default_model = storage.get_active_provider_details()
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No API key configured for active provider '{active_provider}'. "
                "Please configure provider credentials in the Admin Console GUI (http://localhost:8000)."
            ),
        )
    return active_provider, base_url, api_key, default_model


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
    store: BaseSessionStorage,
    before_state: dict[str, Any],
):
    """Consume the agent stream queue and yield SSE-formatted bytes."""
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
# Internal completion execution helpers
# ---------------------------------------------------------------------------

def _resolve_session_and_state(
    explicit_sid: str | None,
    messages: list[dict],
    store_max_size: int,
    storage_dir: Any,
) -> tuple[str, str, str, str | None, dict[str, Any], bool, BaseSessionStorage]:
    """Resolve session ID, turn keys, load session storage and state."""
    resolved_sid, sid_method = resolve_session_id(
        messages, explicit_session_id=explicit_sid
    )
    turn_key = compute_turn_key(resolved_sid, messages)
    prev_turn_key = extract_prev_turn_key(messages)

    store = get_session_storage(
        session_id=resolved_sid,
        max_size=store_max_size,
        storage_dir=storage_dir,
    )

    is_first_turn = len(messages) <= 2
    cache_miss = False
    if is_first_turn:
        before_state = {}
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

    return resolved_sid, sid_method, turn_key, prev_turn_key, before_state, cache_miss, store


async def _handle_streaming_completion(
    resolved_sid: str,
    turn_key: str,
    model: str,
    messages: list[dict],
    before_state: dict[str, Any],
    cache_miss: bool,
    store: BaseSessionStorage,
    api_key: str,
    base_url: str,
) -> StreamingResponse:
    """Run the agent asynchronously and return a streaming SSE response."""
    stream_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

    agent_task = asyncio.create_task(
        run_agent(
            messages=messages,
            before_state=before_state,
            api_key=api_key,
            base_url=base_url,
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


async def _handle_non_streaming_completion(
    resolved_sid: str,
    turn_key: str,
    model: str,
    messages: list[dict],
    before_state: dict[str, Any],
    cache_miss: bool,
    store: BaseSessionStorage,
    api_key: str,
    base_url: str,
) -> JSONResponse:
    """Run the agent and return a standard JSON chat completion response."""
    try:
        result = await run_agent(
            messages=messages,
            before_state=before_state,
            api_key=api_key,
            base_url=base_url,
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


# Chat completion endpoint
# ---------------------------------------------------------------------------

@router.post("/v1/chat/completions", dependencies=[Depends(require_proxy_key)])
@router.post("/v1/{session_id}/chat/completions", dependencies=[Depends(require_proxy_key)])
async def proxy_chat_completions(
    request: Request,
    session_id: str | None = None,
) -> Any:
    """Proxy a chat completion request through the LangGraph RPG agent."""
    active_provider, base_url, api_key, default_model = _get_active_provider_config()

    explicit_sid = session_id or request.query_params.get("session_id")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc

    messages: list[dict] = payload.get("messages", [])
    # Forward model verbatim if present in request; fallback to active provider default model if missing
    model: str = payload.get("model") or default_model

    # Resolve session and load state
    (
        resolved_sid,
        sid_method,
        turn_key,
        prev_turn_key,
        before_state,
        cache_miss,
        store,
    ) = _resolve_session_and_state(
        explicit_sid=explicit_sid,
        messages=messages,
        store_max_size=NUM_STATES_TO_TRACK,
        storage_dir=STATE_STORAGE_DIR,
    )

    _log_request(request, payload, resolved_sid, sid_method, turn_key, prev_turn_key)

    # Strip [proxy: ...] annotations from messages before hitting the LLM.
    messages = strip_proxy_annotations(messages)

    is_streaming = payload.get("stream", False)

    if is_streaming:
        return await _handle_streaming_completion(
            resolved_sid=resolved_sid,
            turn_key=turn_key,
            model=model,
            messages=messages,
            before_state=before_state,
            cache_miss=cache_miss,
            store=store,
            api_key=api_key,
            base_url=base_url,
        )

    return await _handle_non_streaming_completion(
        resolved_sid=resolved_sid,
        turn_key=turn_key,
        model=model,
        messages=messages,
        before_state=before_state,
        cache_miss=cache_miss,
        store=store,
        api_key=api_key,
        base_url=base_url,
    )
