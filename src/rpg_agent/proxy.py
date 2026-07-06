"""OpenRouter Chat Completion Proxy.

Receives chat completion payloads from JanitorAI, resolves the session and
turn key, loads/validates the FIFO session state, runs the LangGraph agent,
persists the updated state, and returns the final assistant message.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from rpg_agent.config import (
    NUM_STATES_TO_TRACK,
    STATE_STORAGE_DIR,
    SANDBOX_TIMEOUT,
    MAX_ITERATIONS,
    OPENROUTER_BASE_URL,
)
from rpg_agent.auth import PROXY_API_KEY, require_proxy_key
from rpg_agent.routes.sessions import router as sessions_router
from rpg_agent.graph import run_agent
from rpg_agent.session import compute_turn_key, resolve_session_id
from rpg_agent.state import SessionStateStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pattern to extract turn_key from a proxy-annotated assistant message.
_TURN_KEY_RE = re.compile(r"\[proxy:.*?turn=([a-f0-9]{24})", re.IGNORECASE)


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

# Include refactored session CRUD router
app.include_router(sessions_router)


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
    """Log request metadata and body at debug level."""
    import json

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
        "Incoming Request: session_id=%s turn_key=%s prev_turn_key=%s. Meta: %s | Headers: %s | Payload: %s",
        session_id,
        turn_key,
        prev_turn_key,
        json.dumps(meta, ensure_ascii=False),
        json.dumps(headers_dict, ensure_ascii=False),
        json.dumps(payload, ensure_ascii=False),
    )


# ---------------------------------------------------------------------------
# Chat completion endpoint
# ---------------------------------------------------------------------------

@app.post("/v1/chat/completions", dependencies=[Depends(require_proxy_key)])
@app.post("/v1/{session_id}/chat/completions", dependencies=[Depends(require_proxy_key)])
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
# Public public API health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    """Simple public health check endpoint."""
    return {"status": "ok"}


def main():
    import argparse
    import uvicorn

    default_port = int(os.environ.get("PORT", 8000))

    parser = argparse.ArgumentParser(description="RPG Agent Chat Completion Proxy")
    parser.add_argument("--host", default="0.0.0.0", help="Binding host")
    parser.add_argument("--port", type=int, default=default_port, help="Binding port")
    parser.add_argument("--config", help="Path to configs.yaml")
    parser.add_argument("--state-dir", help="Directory where per-session state files are saved")
    parser.add_argument("--key-file", help="Path to the proxy API key file")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload")

    args = parser.parse_args()

    # Pass configurations to module via environment variables before running uvicorn
    if args.config:
        os.environ["RPG_AGENT_CONFIG_PATH"] = args.config
    if args.state_dir:
        os.environ["RPG_AGENT_STATE_DIR"] = args.state_dir
    if args.key_file:
        os.environ["RPG_AGENT_KEY_FILE"] = args.key_file

    uvicorn.run("rpg_agent.proxy:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
