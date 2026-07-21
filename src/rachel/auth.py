"""Authentication Module for the RACHEL Proxy."""

import os
import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from rachel.config import KEY_FILE

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
