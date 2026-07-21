"""Unit tests for SettingsStorage (FileSettingsStorage)."""

import tempfile
from pathlib import Path
from rachel.core.settings_storage import FileSettingsStorage

def test_file_settings_storage_defaults():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage = FileSettingsStorage(tenant_id="local", storage_dir=tmp_dir)
        assert storage.get_active_provider() == "openrouter_byok"
        assert storage.get_credentials() == {}

        active, base_url, api_key, default_model = storage.get_active_provider_details()
        assert active == "openrouter_byok"
        assert "openrouter.ai" in base_url
        assert api_key is None
        assert default_model == "google/gemini-3.5-flash"


def test_file_settings_storage_save_and_update():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage = FileSettingsStorage(tenant_id="local", storage_dir=tmp_dir)
        storage.set_credential("openai_byok", "sk-test12345")
        storage.set_active_provider("openai_byok")

        assert storage.get_active_provider() == "openai_byok"
        assert storage.get_credentials() == {"openai_byok": "sk-test12345"}

        active, base_url, api_key, default_model = storage.get_active_provider_details()
        assert active == "openai_byok"
        assert "api.openai.com" in base_url
        assert api_key == "sk-test12345"
        assert default_model == "gpt-4o-mini"

        # Reload from disk
        storage2 = FileSettingsStorage(tenant_id="local", storage_dir=tmp_dir)
        assert storage2.get_active_provider() == "openai_byok"
        assert storage2.get_credentials().get("openai_byok") == "sk-test12345"
