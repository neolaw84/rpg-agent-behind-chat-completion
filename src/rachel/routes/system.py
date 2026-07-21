"""System Endpoints Router.

Serves the administration dashboard SPA, a favicon stub, a public health
check, status endpoint, provider configuration endpoints, and OpenRouter PKCE OAuth flow.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Any
import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from rachel.auth import require_proxy_key
from rachel.config import (
    CONFIG_PUBLIC_URL,
    MAX_ITERATIONS,
    NUM_STATES_TO_TRACK,
    SANDBOX_TIMEOUT,
    STATE_STORAGE_DIR,
    STORAGE_ENGINE,
)
from rachel.core.state import list_all_sessions
from rachel.core.settings_storage import (
    DEFAULT_PROVIDER_BASE_URLS,
    DEFAULT_PROVIDER_MODELS,
    get_settings_storage,
)

router = APIRouter(tags=["system"])

_DASHBOARD_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "index.html")

# In-memory store for PKCE verifiers (state -> verifier)
_PKCE_VERIFIERS: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Public URL detection
# ---------------------------------------------------------------------------

def detect_public_url() -> str:
    """Detect the server's externally-reachable base URL.

    Resolution order (highest priority first):
    1. ``configs.yaml`` -> ``server.public_url`` (if explicitly set)
    2. ``SPACE_HOST`` — set by Hugging Face Spaces.
    3. ``RAILWAY_PUBLIC_DOMAIN`` — set by Railway deployments.
    4. Falls back to ``http://localhost:{PORT}`` using the ``PORT`` env var (default 8000).
    """
    if CONFIG_PUBLIC_URL:
        host = str(CONFIG_PUBLIC_URL).rstrip("/")
        return f"https://{host}" if not host.startswith("http") else host

    hf_host = os.environ.get("SPACE_HOST")
    if hf_host:
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
    from rachel.sandbox.sandbox import get_sandbox_engine
    public_url = detect_public_url()
    storage = get_settings_storage()
    active_provider, _, api_key, _ = storage.get_active_provider_details()
    return {
        "active_provider": active_provider,
        "provider_key_set": bool(api_key),
        "openrouter_key_set": bool(api_key),  # Backward compatibility
        "sandbox_engine": get_sandbox_engine().name,
        "storage_engine": STORAGE_ENGINE,
        "state_storage_dir": str(STATE_STORAGE_DIR),
        "num_states_to_track": NUM_STATES_TO_TRACK,
        "sandbox_timeout": SANDBOX_TIMEOUT,
        "max_iterations": MAX_ITERATIONS,
        "active_sessions_count": len(list_all_sessions()),
        "public_url": public_url,
        "api_endpoint": f"{public_url}/v1",
    }


# ---------------------------------------------------------------------------
# Provider & Credentials Management Endpoints
# ---------------------------------------------------------------------------

@router.get("/v1/providers", dependencies=[Depends(require_proxy_key)])
async def list_providers() -> dict[str, Any]:
    """Return configured active provider and credential status map."""
    storage = get_settings_storage()
    active_provider = storage.get_active_provider()
    creds = storage.get_credentials()

    provider_status = {}
    for p in DEFAULT_PROVIDER_BASE_URLS.keys():
        key = creds.get(p, "")
        provider_status[p] = {
            "configured": bool(key),
            "base_url": DEFAULT_PROVIDER_BASE_URLS[p],
            "default_model": DEFAULT_PROVIDER_MODELS[p],
        }

    return {
        "active_provider": active_provider,
        "providers": provider_status,
    }


@router.post("/v1/providers/active", dependencies=[Depends(require_proxy_key)])
async def set_active_provider(payload: dict[str, Any]) -> dict[str, str]:
    """Set active provider in SettingsStorage."""
    provider = payload.get("provider")
    if not provider or provider not in DEFAULT_PROVIDER_BASE_URLS:
        raise HTTPException(status_code=400, detail=f"Invalid provider: '{provider}'")
    storage = get_settings_storage()
    storage.set_active_provider(provider)
    return {"status": "ok", "active_provider": provider}


@router.post("/v1/providers/credentials", dependencies=[Depends(require_proxy_key)])
async def set_provider_credentials(payload: dict[str, Any]) -> dict[str, str]:
    """Save secret API key for specified provider into SettingsStorage."""
    provider = payload.get("provider")
    api_key = payload.get("api_key")
    if not provider or provider not in DEFAULT_PROVIDER_BASE_URLS:
        raise HTTPException(status_code=400, detail=f"Invalid provider: '{provider}'")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required.")

    storage = get_settings_storage()
    storage.set_credential(provider, api_key)
    return {"status": "ok", "provider": provider}


# ---------------------------------------------------------------------------
# OpenRouter OAuth PKCE Flow
# ---------------------------------------------------------------------------

@router.get("/v1/auth/openrouter/authorize")
async def openrouter_authorize() -> RedirectResponse:
    """Initiate OpenRouter PKCE OAuth flow."""
    # Generate PKCE verifier (43-128 chars base64url)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("utf-8")).digest()
    ).decode("utf-8").rstrip("=")

    state_token = secrets.token_hex(16)
    _PKCE_VERIFIERS[state_token] = code_verifier

    public_url = detect_public_url()
    callback_url = f"{public_url}/v1/auth/openrouter/callback"

    auth_url = (
        f"https://openrouter.ai/auth"
        f"?callback_url={callback_url}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&state={state_token}"
    )
    return RedirectResponse(auth_url)


@router.get("/v1/auth/openrouter/callback")
async def openrouter_callback(
    code: str = Query(...),
    state: str | None = Query(None),
) -> HTMLResponse:
    """Handle OpenRouter OAuth PKCE callback and exchange code for API key."""
    code_verifier = _PKCE_VERIFIERS.pop(state, None) if state else None
    if not code_verifier:
        # Fallback if state was not returned
        if _PKCE_VERIFIERS:
            code_verifier = next(iter(_PKCE_VERIFIERS.values()))
            _PKCE_VERIFIERS.clear()

    if not code_verifier:
        raise HTTPException(status_code=400, detail="OAuth state mismatch or code_verifier expired.")

    # Exchange authorization code for OpenRouter API key
    token_url = "https://openrouter.ai/api/v1/auth/keys"
    payload = {
        "code": code,
        "code_verifier": code_verifier,
        "code_challenge_method": "S256",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(token_url, json=payload)
        if res.status_code >= 400:
            raise HTTPException(
                status_code=400,
                detail=f"OpenRouter key exchange failed ({res.status_code}): {res.text}",
            )
        data = res.json()
        api_key = data.get("key")
        if not api_key:
            raise HTTPException(status_code=500, detail="OpenRouter did not return an API key.")

    # Save to SettingsStorage
    storage = get_settings_storage()
    storage.set_credential("openrouter_pkce", api_key)
    storage.set_active_provider("openrouter_pkce")

    success_html = """
    <!DOCTYPE html>
    <html>
    <head><title>OpenRouter Authorized</title></head>
    <body style="font-family: sans-serif; background: #0b0e1a; color: #d4deff; text-align: center; padding-top: 50px;">
        <h2 style="color: #22d36e;">✓ OpenRouter Connected Successfully!</h2>
        <p>Your OpenRouter PKCE token has been saved and selected as the Active Provider.</p>
        <p><a href="/" style="color: #6c8aff; text-decoration: underline;">Return to Admin Dashboard</a></p>
        <script>setTimeout(function() { window.location.href = "/"; }, 2500);</script>
    </body>
    </html>
    """
    return HTMLResponse(content=success_html)
