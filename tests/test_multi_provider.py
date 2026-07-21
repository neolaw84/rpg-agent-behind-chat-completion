"""Unit tests for Multi-Provider endpoints, CORS, and PKCE OAuth flow."""

import pytest
from fastapi.testclient import TestClient

from rachel.auth import PROXY_API_KEY
from rachel.proxy import app
from rachel.core.settings_storage import get_settings_storage

client = TestClient(app)
AUTH_HEADERS = {"Authorization": f"Bearer {PROXY_API_KEY}"}


def test_cors_headers():
    # JanitorAI origin
    res = client.options(
        "/v1/chat/completions",
        headers={"Origin": "https://janitorai.com", "Access-Control-Request-Method": "POST"}
    )
    assert res.headers.get("access-control-allow-origin") == "https://janitorai.com"

    # Localhost origin
    res_local = client.options(
        "/v1/chat/completions",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"}
    )
    assert res_local.headers.get("access-control-allow-origin") == "http://localhost:3000"

    # Disallowed origin
    res_other = client.options(
        "/v1/chat/completions",
        headers={"Origin": "https://untrusted-domain.com", "Access-Control-Request-Method": "POST"}
    )
    assert res_other.headers.get("access-control-allow-origin") is None


def test_provider_management_endpoints(tmp_path, monkeypatch):
    from rachel.core import settings_storage
    storage = settings_storage.FileSettingsStorage(tenant_id="local", storage_dir=str(tmp_path))
    monkeypatch.setattr("rachel.routes.system.get_settings_storage", lambda: storage)
    monkeypatch.setattr("rachel.routes.completions.get_settings_storage", lambda: storage)

    # List providers
    res = client.get("/v1/providers", headers=AUTH_HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data["active_provider"] == "openrouter_byok"
    assert "openrouter_byok" in data["providers"]

    # Set credentials
    res_cred = client.post(
        "/v1/providers/credentials",
        headers=AUTH_HEADERS,
        json={"provider": "deepseek_byok", "api_key": "sk-deepseek-test"}
    )
    assert res_cred.status_code == 200

    # Set active provider
    res_active = client.post(
        "/v1/providers/active",
        headers=AUTH_HEADERS,
        json={"provider": "deepseek_byok"}
    )
    assert res_active.status_code == 200
    assert res_active.json()["active_provider"] == "deepseek_byok"

    # Verify status
    status_res = client.get("/v1/status", headers=AUTH_HEADERS)
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["active_provider"] == "deepseek_byok"
    assert status_data["provider_key_set"] is True


def test_openrouter_pkce_authorize_route():
    res = client.get("/v1/auth/openrouter/authorize", follow_redirects=False)
    assert res.status_code == 307
    location = res.headers.get("location")
    assert "openrouter.ai/auth" in location
    assert "code_challenge=" in location
    assert "code_challenge_method=S256" in location
