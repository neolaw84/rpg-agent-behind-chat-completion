"""Unit tests for Client Proxy Keys Management and Authentication dependencies."""

from __future__ import annotations

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from rachel.auth import PROXY_API_KEY, require_proxy_key, require_sso_admin_user
from rachel.core.db import init_db
from rachel.routes.system import router as system_router


@pytest.fixture
def test_app():
    """Create FastAPI test app with clean in-memory database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine=engine)

    app = FastAPI()
    app.include_router(system_router)

    with patch("rachel.core.db.get_engine", return_value=engine):
        yield app


def test_create_list_revoke_proxy_keys(test_app):
    """Test creating, listing, and revoking database-backed client proxy keys."""
    client = TestClient(test_app)
    headers = {"Authorization": f"Bearer {PROXY_API_KEY}"}

    # 1. Create a proxy key
    create_res = client.post(
        "/v1/proxy-keys",
        json={"name": "JanitorAI Client Key", "expires_in_days": 30},
        headers=headers,
    )
    assert create_res.status_code == 200
    key_data = create_res.json()
    assert key_data["name"] == "JanitorAI Client Key"
    assert key_data["prefix"] == "sk-local-"
    raw_proxy_key = key_data["proxy_key"]
    key_id = key_data["id"]
    assert raw_proxy_key.startswith("sk-local-")

    # 2. List proxy keys
    list_res = client.get("/v1/proxy-keys", headers=headers)
    assert list_res.status_code == 200
    listed_keys = list_res.json()["keys"]
    # Includes bootstrap key + newly created key
    assert any(k["id"] == key_id for k in listed_keys)

    # 3. Authenticate using the newly created database proxy key on status endpoint
    status_res = client.get("/v1/status", headers={"Authorization": f"Bearer {raw_proxy_key}"})
    assert status_res.status_code == 200

    # 4. Revoke proxy key
    revoke_res = client.delete(f"/v1/proxy-keys/{key_id}", headers=headers)
    assert revoke_res.status_code == 200

    # 5. Authenticate using revoked key should fail (401)
    revoked_status_res = client.get("/v1/status", headers={"Authorization": f"Bearer {raw_proxy_key}"})
    assert revoked_status_res.status_code == 401


def test_require_sso_admin_user_cloud_mode(test_app):
    """Test require_sso_admin_user JWT validation in MULTI_TENANT_MODE=True."""
    client = TestClient(test_app)

    mock_jwt = jwt.encode({"sub": "user_sso_12345", "tenant_id": "tenant_sso_12345"}, "secret", algorithm="HS256")

    with patch("rachel.auth.MULTI_TENANT_MODE", True):
        # Request with valid mock JWT token
        res = client.get("/v1/providers", headers={"Authorization": f"Bearer {mock_jwt}"})
        assert res.status_code == 200

        # Request with missing token
        bad_res = client.get("/v1/providers")
        assert bad_res.status_code == 401
