"""Unit tests for Envelope Encryption & Key Derivation (HKDF-SHA256 + AES-256-GCM)."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from rachel.core.crypto import decrypt_api_key, derive_kek, encrypt_api_key


def test_derive_kek_local_and_cloud_modes():
    """Verify HKDF key derivation produces deterministic 32-byte keys for local and cloud tenant contexts."""
    kek_local = derive_kek(tenant_id="local")
    assert isinstance(kek_local, bytes)
    assert len(kek_local) == 32

    # Deterministic output check
    assert derive_kek(tenant_id="local") == kek_local

    with patch("rachel.config.MULTI_TENANT_MODE", True):
        with patch("rachel.config.ENCRYPTION_MASTER_KEY", "master_test_secret_12345"):
            kek_tenant_1 = derive_kek(tenant_id="tenant_123", sso_sub="sub_abc")
            kek_tenant_2 = derive_kek(tenant_id="tenant_456", sso_sub="sub_def")

            assert len(kek_tenant_1) == 32
            assert len(kek_tenant_2) == 32
            # Isolation check across tenants
            assert kek_tenant_1 != kek_tenant_2
            assert kek_tenant_1 != kek_local


def test_encrypt_decrypt_api_key_roundtrip():
    """Verify AES-256-GCM encryption and decryption round-trip."""
    kek = derive_kek(tenant_id="local")
    raw_key = "sk-proj-openai-secret-key-12345"

    encrypted = encrypt_api_key(raw_key, kek)
    assert encrypted.startswith("enc_v1:")
    assert encrypted != raw_key

    decrypted = decrypt_api_key(encrypted, kek)
    assert decrypted == raw_key


def test_legacy_plaintext_key_fallback():
    """Verify legacy plain text API keys return unchanged without raising errors."""
    kek = derive_kek(tenant_id="local")
    raw_plain_key = "sk-openrouter-raw-bearer-token-999"

    # Plain text does not start with enc_v1:
    decrypted = decrypt_api_key(raw_plain_key, kek)
    assert decrypted == raw_plain_key


def test_invalid_decryption_key_failure():
    """Verify decryption fails when supplied with an invalid/wrong KEK."""
    kek_correct = derive_kek(tenant_id="local")
    kek_wrong = b"0" * 32
    raw_key = "sk-secret-key-to-protect"

    encrypted = encrypt_api_key(raw_key, kek_correct)

    with pytest.raises(ValueError, match="Decryption failed"):
        decrypt_api_key(encrypted, kek_wrong)
