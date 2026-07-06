"""OpenRouter Chat Completion Proxy.

Receives chat completion payloads, forwards them verbatim to the OpenRouter API,
and appends the raw payload to docs/example-janitorai-payload.md for inspection.
"""

import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from rpg_agent.session import compute_turn_key, resolve_session_id

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
PAYLOAD_LOG_PATH = Path(__file__).parent.parent.parent / "docs" / "example-janitorai-payload.md"

# Key file sits at the repo root alongside .env
_KEY_FILE = Path(__file__).parent.parent.parent / "proxy.key"


def _load_or_generate_proxy_key() -> str:
    """Load the proxy API key from proxy.key, or generate and persist a new one."""
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    key = secrets.token_urlsafe(32)
    _KEY_FILE.write_text(key + "\n", encoding="utf-8")
    return key


# Generated once at startup; persisted to proxy.key for reuse across restarts.
PROXY_API_KEY: str = _load_or_generate_proxy_key()

_bearer_scheme = HTTPBearer(auto_error=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Print the proxy API key to the console on startup."""
    print(
        "\n" + "=" * 60 + "\n"
        f"  Proxy API Key (use as Bearer token):\n"
        f"  {PROXY_API_KEY}\n"
        + "=" * 60 + "\n"
    )
    logger.info("Proxy API key printed to console.")
    yield


app = FastAPI(
    title="OpenRouter Chat Completion Proxy",
    description=(
        "A local proxy that forwards chat completion payloads to OpenRouter "
        "and logs them for inspection."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _require_proxy_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """Dependency: validate the proxy-level Bearer token."""
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, PROXY_API_KEY
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing proxy API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _get_api_key() -> str:
    """Retrieve the OpenRouter API key from environment variables."""
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


def _append_payload_to_log(
    request: Request,
    payload: dict[str, Any],
    session_id: str,
    session_method: str,
) -> None:
    """Append full request metadata, headers, body, and session info to the log."""
    PAYLOAD_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(tz=timezone.utc).isoformat()

    # --- Request metadata ---
    meta = {
        "method": request.method,
        "url": str(request.url),
        "path": request.url.path,
        "query_params": dict(request.query_params),
        "client": (
            f"{request.client.host}:{request.client.port}"
            if request.client
            else "unknown"
        ),
        "session_id": session_id,
        "session_method": session_method,
    }
    meta_json = json.dumps(meta, indent=2, ensure_ascii=False)

    # --- Incoming request headers (redact Authorization value) ---
    headers_dict = dict(request.headers)
    if "authorization" in headers_dict:
        headers_dict["authorization"] = "Bearer <REDACTED>"
    headers_json = json.dumps(headers_dict, indent=2, ensure_ascii=False)

    # --- Body ---
    payload_json = json.dumps(payload, indent=2, ensure_ascii=False)

    entry = (
        f"\n---\n\n"
        f"## Request captured at {timestamp}\n\n"
        f"**Session**: `{session_id}` _(resolved via {session_method})_\n\n"
        f"### Metadata\n\n"
        f"```json\n{meta_json}\n```\n\n"
        f"### Headers\n\n"
        f"```json\n{headers_json}\n```\n\n"
        f"### Body (forwarded to OpenRouter verbatim)\n\n"
        f"```json\n{payload_json}\n```\n"
    )

    with PAYLOAD_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(entry)

    logger.info(
        "Appended request log to %s [session=%s via %s]",
        PAYLOAD_LOG_PATH,
        session_id,
        session_method,
    )


@app.post("/v1/chat/completions", dependencies=[Depends(_require_proxy_key)])
@app.post("/v1/{session_id}/chat/completions", dependencies=[Depends(_require_proxy_key)])
async def proxy_chat_completions(
    request: Request,
    session_id: str | None = None,
) -> Any:
    """Proxy a chat completion request to OpenRouter.

    Accepts any JSON payload conforming to the OpenAI/OpenRouter chat
    completion schema, forwards it verbatim, and returns the response.
    Streaming responses are supported and passed through transparently.

    Session ID resolution (highest → lowest priority):
      1. URL path segment ``/v1/{session_id}/chat/completions``
      2. Query parameter ``?session_id=…``
      3. ``[session: name]`` OOC tag inside any message (newest first)
      4. MD5 suffix hash of system prompt + username from last user message
    """
    api_key = _get_api_key()

    # Also accept session_id from query param if not in path.
    explicit_sid = session_id or request.query_params.get("session_id")

    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc

    messages = payload.get("messages", [])
    resolved_sid, sid_method = resolve_session_id(messages, explicit_session_id=explicit_sid)
    turn_key = compute_turn_key(resolved_sid, messages)
    logger.info(
        "Session: %s (via %s) | Turn key: %s",
        resolved_sid, sid_method, turn_key,
    )

    # Log full request (metadata, headers, body, session) before forwarding.
    _append_payload_to_log(request, payload, resolved_sid, sid_method)

    is_streaming = payload.get("stream", False)

    if is_streaming:
        async def stream_generator():
            # Inject turn key as the first content chunk so it appears in
            # the rendered message text.  Uses the standard SSE delta format
            # so every compliant client renders it verbatim.
            import json as _json
            import time as _time
            annotation = f"[proxy: session={resolved_sid} turn={turn_key}]\n\n"
            first_chunk = _json.dumps({
                "id": "proxy-meta",
                "object": "chat.completion.chunk",
                "created": int(_time.time()),
                "model": payload.get("model", ""),
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": annotation},
                    "finish_reason": None,
                }],
            })
            yield f"data: {first_chunk}\n\n".encode()

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost",
                "X-Title": "RPG Agent Proxy",
            }
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    OPENROUTER_API_URL,
                    json=payload,
                    headers=headers,
                ) as upstream:
                    if upstream.status_code >= 400:
                        error_body = await upstream.aread()
                        logger.error(
                            "OpenRouter error %s: %s",
                            upstream.status_code,
                            error_body.decode(),
                        )
                        yield error_body
                        return
                    async for chunk in upstream.aiter_bytes():
                        yield chunk

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "RPG Agent Proxy",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            OPENROUTER_API_URL,
            json=payload,
            headers=headers,
        )

    if response.status_code >= 400:
        logger.error(
            "OpenRouter returned error %s: %s",
            response.status_code,
            response.text,
        )
        raise HTTPException(status_code=response.status_code, detail=response.json())

    result = response.json()
    # Prepend the turn key annotation into the message content so it is
    # visible in the client's chat UI.
    annotation = f"[proxy: session={resolved_sid} turn={turn_key}]\n\n"
    try:
        result["choices"][0]["message"]["content"] = (
            annotation + (result["choices"][0]["message"]["content"] or "")
        )
    except (KeyError, IndexError, TypeError):
        pass  # Non-standard response shape — skip annotation
    return result


@app.get("/health")
async def health() -> dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok"}
