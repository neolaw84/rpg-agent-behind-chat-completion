"""System Endpoints Router.

Serves the administration dashboard SPA, a favicon stub, a public health
check, and an authenticated status endpoint consumed by the dashboard.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Response
from fastapi.responses import HTMLResponse

from rpg_agent.auth import require_proxy_key
from rpg_agent.config import (
    MAX_ITERATIONS,
    NUM_STATES_TO_TRACK,
    SANDBOX_TIMEOUT,
    STATE_STORAGE_DIR,
)
from rpg_agent.state import SessionStateStore

router = APIRouter(tags=["system"])

_DASHBOARD_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "index.html")


# ---------------------------------------------------------------------------
# Public URL detection
# ---------------------------------------------------------------------------

def detect_public_url() -> str:
    """Detect the server's externally-reachable base URL.

    Resolution order (highest priority first):
    1. ``SPACE_HOST`` — set by Hugging Face Spaces; already contains the full
       subdomain including username and space name, e.g.
       ``username-space-name.hf.space``.
    2. ``RAILWAY_PUBLIC_DOMAIN`` — set by Railway deployments.
    3. Falls back to ``http://localhost:{PORT}`` using the ``PORT`` env var
       (default 8000).
    """
    hf_host = os.environ.get("SPACE_HOST")
    if hf_host:
        # HF sets the host without a scheme; always HTTPS in production.
        host = hf_host.rstrip("/")
        return f"https://{host}" if not host.startswith("http") else host

    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if railway_domain:
        host = railway_domain.rstrip("/")
        return f"https://{host}" if not host.startswith("http") else host

    port = int(os.environ.get("PORT", 8000))
    return f"http://localhost:{port}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard() -> HTMLResponse:
    """Serve the single-page administration dashboard."""
    try:
        with open(_DASHBOARD_PATH, encoding="utf-8") as fh:
            return HTMLResponse(fh.read())
    except FileNotFoundError:
        return HTMLResponse(
            "<h1>Dashboard not found</h1><p>index.html is missing.</p>",
            status_code=500,
        )


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    """Return an empty response for favicon requests to suppress 404 errors."""
    return Response(status_code=204)


@router.get("/health")
async def health() -> dict[str, str]:
    """Simple public health check endpoint."""
    return {"status": "ok"}


@router.get("/v1/status", dependencies=[Depends(require_proxy_key)])
async def proxy_status() -> dict:
    """Return configuration and runtime status for the dashboard."""
    from rpg_agent.sandbox import get_sandbox_engine
    public_url = detect_public_url()
    return {
        "openrouter_key_set": bool(os.environ.get("OPENROUTER_API_KEY")),
        "sandbox_engine": get_sandbox_engine().name,
        "state_storage_dir": str(STATE_STORAGE_DIR),
        "num_states_to_track": NUM_STATES_TO_TRACK,
        "sandbox_timeout": SANDBOX_TIMEOUT,
        "max_iterations": MAX_ITERATIONS,
        "active_sessions_count": len(SessionStateStore.list_sessions(STATE_STORAGE_DIR)),
        "public_url": public_url,
        "api_endpoint": f"{public_url}/v1",
    }
