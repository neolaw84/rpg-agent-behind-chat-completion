"""Envelope Encryption & Key Derivation Module (HKDF-SHA256 + AES-256-GCM)."""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from rachel import config

logger = logging.getLogger(__name__)

_ENCRYPT_PREFIX = "enc_v1:"


def derive_kek(tenant_id: str = "local", sso_sub: str | None = None) -> bytes:
    """Derive a 32-byte Key Encryption Key (KEK) using HKDF-SHA256."""
    from rachel.auth import PROXY_API_KEY

    if not config.MULTI_TENANT_MODE or tenant_id == "local":
        secret_bytes = PROXY_API_KEY.encode("utf-8")
        salt = b"local"
        info = b"local_admin"
    else:
        secret_bytes = config.ENCRYPTION_MASTER_KEY.encode("utf-8")
        salt = tenant_id.encode("utf-8")
        info = (sso_sub or tenant_id).encode("utf-8")

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=info,
    )
    return hkdf.derive(secret_bytes)


def encrypt_api_key(raw_key: str, kek: bytes) -> str:
    """Encrypt plain text API key using AES-256-GCM and return encoded string."""
    if not raw_key:
        return ""
    if raw_key.startswith(_ENCRYPT_PREFIX):
        return raw_key

    nonce = os.urandom(12)
    aesgcm = AESGCM(kek)
    ciphertext = aesgcm.encrypt(nonce, raw_key.encode("utf-8"), None)
    encoded = base64.b64encode(nonce + ciphertext).decode("ascii")
    return f"{_ENCRYPT_PREFIX}{encoded}"


def decrypt_api_key(encrypted_payload: str, kek: bytes) -> str:
    """Decrypt payload string using AES-256-GCM, with transparent plaintext fallback."""
    if not encrypted_payload:
        return ""
    if not encrypted_payload.startswith(_ENCRYPT_PREFIX):
        # Legacy plain text key fallback
        return encrypted_payload

    raw_b64 = encrypted_payload[len(_ENCRYPT_PREFIX):]
    try:
        data = base64.b64decode(raw_b64)
        if len(data) < 13:
            raise ValueError("Payload too short.")
        nonce = data[:12]
        ciphertext = data[12:]
        aesgcm = AESGCM(kek)
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("Failed to decrypt credentials: %s", exc)
        raise ValueError("Decryption failed. Invalid encryption key or corrupted data.") from exc
