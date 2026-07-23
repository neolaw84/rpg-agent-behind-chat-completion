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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from rachel.auth import require_proxy_key, require_sso_admin_user
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


@router.get("/v1/status", dependencies=[Depends(require_sso_admin_user)])
async def proxy_status(request: Request) -> dict:
    """Return configuration and runtime status for the dashboard."""
    from rachel.sandbox.sandbox import get_sandbox_engine
    tenant_id = getattr(request.state, "tenant_id", "local")
    public_url = detect_public_url()
    storage = get_settings_storage(tenant_id=tenant_id)
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
        "active_sessions_count": len(list_all_sessions(tenant_id=tenant_id)),
        "public_url": public_url,
        "api_endpoint": f"{public_url}/v1",
    }


# ---------------------------------------------------------------------------
# Provider & Credentials Management Endpoints
# ---------------------------------------------------------------------------

@router.get("/v1/providers", dependencies=[Depends(require_sso_admin_user)])
async def list_providers(request: Request) -> dict[str, Any]:
    """Return configured active provider and credential status map."""
    tenant_id = getattr(request.state, "tenant_id", "local")
    storage = get_settings_storage(tenant_id=tenant_id)
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


@router.post("/v1/providers/active", dependencies=[Depends(require_sso_admin_user)])
async def set_active_provider(payload: dict[str, Any], request: Request) -> dict[str, str]:
    """Set active provider in SettingsStorage."""
    provider = payload.get("provider")
    if not provider or provider not in DEFAULT_PROVIDER_BASE_URLS:
        raise HTTPException(status_code=400, detail=f"Invalid provider: '{provider}'")
    tenant_id = getattr(request.state, "tenant_id", "local")
    storage = get_settings_storage(tenant_id=tenant_id)
    storage.set_active_provider(provider)
    return {"status": "ok", "active_provider": provider}


@router.post("/v1/providers/credentials", dependencies=[Depends(require_sso_admin_user)])
async def set_provider_credentials(payload: dict[str, Any], request: Request) -> dict[str, str]:
    """Save secret API key for specified provider into SettingsStorage."""
    provider = payload.get("provider")
    api_key = payload.get("api_key")
    if not provider or provider not in DEFAULT_PROVIDER_BASE_URLS:
        raise HTTPException(status_code=400, detail=f"Invalid provider: '{provider}'")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required.")

    tenant_id = getattr(request.state, "tenant_id", "local")
    storage = get_settings_storage(tenant_id=tenant_id)
    storage.set_credential(provider, api_key)
    return {"status": "ok", "provider": provider}


# ---------------------------------------------------------------------------
# Client Proxy Key Management Endpoints
# ---------------------------------------------------------------------------

@router.post("/v1/proxy-keys", dependencies=[Depends(require_sso_admin_user)])
async def create_proxy_key(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """Generate a new client proxy key (sk-local-... or sk-tenant-...)."""
    from datetime import datetime, timezone, timedelta
    from rachel.core.db import TenantApiKey, get_engine, get_sessionmaker, hash_key

    name = str(payload.get("name", "Default Proxy Key")).strip()
    expires_in_days = payload.get("expires_in_days")
    tenant_id = getattr(request.state, "tenant_id", "local")

    prefix = "sk-local-" if tenant_id == "local" else "sk-tenant-"
    raw_key = f"{prefix}{secrets.token_hex(20)}"
    kh = hash_key(raw_key)

    expires_at = None
    if expires_in_days is not None:
        try:
            expires_at = datetime.now(timezone.utc) + timedelta(days=int(expires_in_days))
        except (ValueError, TypeError):
            pass

    key_id = f"key_{secrets.token_hex(8)}"
    eng = get_engine()
    sm = get_sessionmaker(eng)
    with sm() as session:
        record = TenantApiKey(
            id=key_id,
            tenant_id=tenant_id,
            key_hash=kh,
            prefix=prefix,
            name=name,
            expires_at=expires_at,
            is_active=True,
        )
        session.add(record)
        session.commit()

    return {
        "id": key_id,
        "tenant_id": tenant_id,
        "name": name,
        "prefix": prefix,
        "proxy_key": raw_key,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


@router.get("/v1/proxy-keys", dependencies=[Depends(require_sso_admin_user)])
async def list_proxy_keys(request: Request) -> dict[str, Any]:
    """List proxy keys for the active tenant."""
    from rachel.core.db import TenantApiKey, get_engine, get_sessionmaker
    tenant_id = getattr(request.state, "tenant_id", "local")

    eng = get_engine()
    sm = get_sessionmaker(eng)
    with sm() as session:
        records = (
            session.query(TenantApiKey)
            .filter_by(tenant_id=tenant_id, is_active=True)
            .all()
        )
        keys_list = [
            {
                "id": r.id,
                "name": r.name,
                "prefix": r.prefix,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "is_active": r.is_active,
            }
            for r in records
        ]
        return {"keys": keys_list, "count": len(keys_list)}


@router.delete("/v1/proxy-keys/{key_id}", dependencies=[Depends(require_sso_admin_user)])
async def revoke_proxy_key(key_id: str, request: Request) -> dict[str, str]:
    """Revoke (deactivate) a client proxy key."""
    from rachel.core.db import TenantApiKey, get_engine, get_sessionmaker
    tenant_id = getattr(request.state, "tenant_id", "local")

    eng = get_engine()
    sm = get_sessionmaker(eng)
    with sm() as session:
        record = (
            session.query(TenantApiKey)
            .filter_by(id=key_id, tenant_id=tenant_id)
            .first()
        )
        if not record:
            raise HTTPException(status_code=444 if False else 404, detail=f"Proxy key '{key_id}' not found.")
        record.is_active = False
        session.commit()
    return {"status": "ok", "message": f"Proxy key '{key_id}' revoked."}


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
