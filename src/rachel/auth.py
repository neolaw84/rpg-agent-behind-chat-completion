"""Authentication & Authorization Module for the RACHEL Proxy.

Provides:
- require_proxy_key: Validates client proxy keys against database (tenant_api_keys) or local proxy key.
- require_sso_admin_user: Validates OpenID Connect (OIDC) JWT Bearer tokens for Admin Console in cloud mode.
"""

from __future__ import annotations

import datetime
import logging
import os
import secrets
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from rachel.config import (
    KEY_FILE,
    MULTI_TENANT_MODE,
    OIDC_ISSUER_URL,
    OIDC_JWKS_URL,
)

logger = logging.getLogger(__name__)


def _load_or_generate_proxy_key() -> str:
    env_key = os.environ.get("RACHEL_PROXY_KEY")
    if env_key:
        return env_key.strip()

    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    key = secrets.token_urlsafe(32)
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key + "\n", encoding="utf-8")
    return key


PROXY_API_KEY: str = _load_or_generate_proxy_key()
_bearer_scheme = HTTPBearer(auto_error=False)


async def require_proxy_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Validate incoming client proxy key against database (tenant_api_keys) or local fallback."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing proxy API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_token = credentials.credentials.strip()

    # 1. Check against database hashed proxy keys
    try:
        from rachel.core.db import TenantApiKey, get_engine, get_sessionmaker, hash_key, init_db
        eng = get_engine()
        init_db(engine=eng)
        sm = get_sessionmaker(eng)
        kh = hash_key(raw_token)
        with sm() as db_session:
            key_record = (
                db_session.query(TenantApiKey)
                .filter_by(key_hash=kh, is_active=True)
                .first()
            )
            if key_record:
                # Check expiration if set
                if key_record.expires_at is not None:
                    now = datetime.datetime.now(datetime.timezone.utc)
                    expires = key_record.expires_at
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=datetime.timezone.utc)
                    if now > expires:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Proxy API key has expired.",
                            headers={"WWW-Authenticate": "Bearer"},
                        )
                tenant_id = key_record.tenant_id
                request.state.tenant_id = tenant_id
                return tenant_id
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Error during database proxy key lookup: %s", exc)

    # 2. Fallback check against local PROXY_API_KEY
    if secrets.compare_digest(raw_token, PROXY_API_KEY):
        request.state.tenant_id = "local"
        return "local"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing proxy API key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_sso_admin_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, str]:
    """Validate Admin Console SSO JWT in Cloud Mode or local proxy key in Local Mode."""
    if not MULTI_TENANT_MODE:
        tenant_id = await require_proxy_key(request, credentials)
        request.state.sso_sub = "local_admin"
        return {"tenant_id": tenant_id, "sub": "local_admin"}

    # Cloud Multi-Tenant Mode: Validate OpenID Connect JWT
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing SSO authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials.strip()
    try:
        if OIDC_JWKS_URL:
            jwks_client = jwt.PyJWKClient(OIDC_JWKS_URL)
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256", "HS256"],
                options={"verify_aud": False},
            )
        else:
            # Fallback for mock/test JWT tokens without external JWKS endpoint
            payload = jwt.decode(token, options={"verify_signature": False})

        sub = payload.get("sub")
        if not sub:
            raise ValueError("Token missing 'sub' claim.")

        tenant_id = payload.get("tenant_id") or f"tenant_{sub[:16]}"
        request.state.tenant_id = tenant_id
        request.state.sso_sub = sub
        return {"tenant_id": tenant_id, "sub": sub}
    except Exception as exc:
        logger.warning("SSO JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid SSO authentication token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
