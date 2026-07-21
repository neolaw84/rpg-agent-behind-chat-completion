"""User Settings & LLM Credentials Storage Engine.

Adheres to SOLID principles:
- BaseSettingsStorage defining abstract operations.
- FileSettingsStorage for local JSON storage (data/settings.json).
- PostgresSettingsStorage for cloud PostgreSQL storage.
"""

from __future__ import annotations

import abc
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER_BASE_URLS = {
    "openrouter_byok": "https://openrouter.ai/api/v1/chat/completions",
    "openrouter_pkce": "https://openrouter.ai/api/v1/chat/completions",
    "openai_byok": "https://api.openai.com/v1/chat/completions",
    "gemini_byok": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "deepseek_byok": "https://api.deepseek.com/chat/completions",
}

DEFAULT_PROVIDER_MODELS = {
    "openrouter_byok": "google/gemini-3.5-flash",
    "openrouter_pkce": "google/gemini-3.5-flash",
    "openai_byok": "gpt-4o-mini",
    "gemini_byok": "gemini-2.5-flash",
    "deepseek_byok": "deepseek-chat",
}


class BaseSettingsStorage(abc.ABC):
    """Abstract Base Class for User Settings and Credentials Storage."""

    def __init__(self, tenant_id: str = "local") -> None:
        self.tenant_id = tenant_id

    @abc.abstractmethod
    def get_active_provider(self) -> str:
        """Return active provider string name (e.g. 'openrouter_byok')."""
        pass

    @abc.abstractmethod
    def set_active_provider(self, provider: str) -> None:
        """Set active provider string name."""
        pass

    @abc.abstractmethod
    def get_credentials(self) -> dict[str, str]:
        """Return map of provider_key -> secret_api_key."""
        pass

    @abc.abstractmethod
    def set_credential(self, provider: str, api_key: str) -> None:
        """Save secret API key for specified provider."""
        pass

    def get_active_provider_details(self) -> tuple[str, str, str | None, str]:
        """Return (active_provider, base_url, api_key, default_model)."""
        active = self.get_active_provider()
        creds = self.get_credentials()
        api_key = creds.get(active)
        base_url = DEFAULT_PROVIDER_BASE_URLS.get(active, DEFAULT_PROVIDER_BASE_URLS["openrouter_byok"])
        default_model = DEFAULT_PROVIDER_MODELS.get(active, "google/gemini-3.5-flash")
        return active, base_url, api_key, default_model


class FileSettingsStorage(BaseSettingsStorage):
    """Local JSON file storage implementation for settings & credentials."""

    def __init__(self, tenant_id: str = "local", storage_dir: Any = None) -> None:
        super().__init__(tenant_id)
        from rachel.config import STATE_STORAGE_DIR
        base_dir = Path(storage_dir) if storage_dir is not None else Path(STATE_STORAGE_DIR).parent
        self._path = base_dir / "settings.json"
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                text = self._path.read_text(encoding="utf-8")
                return json.loads(text)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load settings file %s: %s", self._path, exc)
        return {
            "active_provider": "openrouter_byok",
            "credentials": {},
        }

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_active_provider(self) -> str:
        return self._data.get("active_provider") or "openrouter_byok"

    def set_active_provider(self, provider: str) -> None:
        if provider not in DEFAULT_PROVIDER_BASE_URLS:
            raise ValueError(f"Invalid provider: '{provider}'")
        self._data["active_provider"] = provider
        self._save()

    def get_credentials(self) -> dict[str, str]:
        return dict(self._data.get("credentials", {}))

    def set_credential(self, provider: str, api_key: str) -> None:
        if provider not in DEFAULT_PROVIDER_BASE_URLS:
            raise ValueError(f"Invalid provider: '{provider}'")
        if "credentials" not in self._data:
            self._data["credentials"] = {}
        self._data["credentials"][provider] = api_key.strip()
        self._save()


class PostgresSettingsStorage(BaseSettingsStorage):
    """PostgreSQL storage implementation for tenant settings & credentials."""

    def __init__(self, tenant_id: str = "local") -> None:
        super().__init__(tenant_id)
        from rachel.core.state import _get_pg_pool
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tenant_settings (
                        tenant_id VARCHAR(255) PRIMARY KEY,
                        active_provider VARCHAR(64) NOT NULL DEFAULT 'openrouter_byok',
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tenant_credentials (
                        tenant_id VARCHAR(255) NOT NULL,
                        provider VARCHAR(64) NOT NULL,
                        api_key TEXT NOT NULL,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (tenant_id, provider)
                    );
                """)
                conn.commit()
        finally:
            pool.putconn(conn)

    def get_active_provider(self) -> str:
        from rachel.core.state import _get_pg_pool
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT active_provider FROM tenant_settings WHERE tenant_id = %s;", (self.tenant_id,))
                row = cur.fetchone()
                return row[0] if row else "openrouter_byok"
        finally:
            pool.putconn(conn)

    def set_active_provider(self, provider: str) -> None:
        if provider not in DEFAULT_PROVIDER_BASE_URLS:
            raise ValueError(f"Invalid provider: '{provider}'")
        from rachel.core.state import _get_pg_pool
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO tenant_settings (tenant_id, active_provider, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (tenant_id)
                    DO UPDATE SET active_provider = EXCLUDED.active_provider, updated_at = CURRENT_TIMESTAMP;
                """, (self.tenant_id, provider))
                conn.commit()
        finally:
            pool.putconn(conn)

    def get_credentials(self) -> dict[str, str]:
        from rachel.core.state import _get_pg_pool
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT provider, api_key FROM tenant_credentials WHERE tenant_id = %s;", (self.tenant_id,))
                rows = cur.fetchall()
                return {row[0]: row[1] for row in rows}
        finally:
            pool.putconn(conn)

    def set_credential(self, provider: str, api_key: str) -> None:
        if provider not in DEFAULT_PROVIDER_BASE_URLS:
            raise ValueError(f"Invalid provider: '{provider}'")
        from rachel.core.state import _get_pg_pool
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO tenant_credentials (tenant_id, provider, api_key, updated_at)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (tenant_id, provider)
                    DO UPDATE SET api_key = EXCLUDED.api_key, updated_at = CURRENT_TIMESTAMP;
                """, (self.tenant_id, provider, api_key.strip()))
                conn.commit()
        finally:
            pool.putconn(conn)


def get_settings_storage(tenant_id: str = "local", storage_dir: Any = None) -> BaseSettingsStorage:
    """Factory function to get settings storage engine based on STORAGE_ENGINE config."""
    from rachel.config import STORAGE_ENGINE
    if STORAGE_ENGINE == "postgres":
        return PostgresSettingsStorage(tenant_id)
    return FileSettingsStorage(tenant_id, storage_dir)
