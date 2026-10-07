"""Keyed, purpose-specific fingerprints for provider credential scoping.

The scope is persisted in rate-limit, checkpoint, and durable-run identity. Rotating
``API_KEY_ENCRYPTION_KEY`` intentionally changes this namespace: an in-flight run
with the old scope fails closed instead of replaying output under a different key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ...core.config import settings

_SALT = b"latexy/resume-engine/credential-scope/hkdf-salt/v1"
_INFO = b"latexy/resume-engine/credential-scope/hmac-key/v1"
_MESSAGE_DOMAIN = b"latexy/resume-engine/credential-scope/v1\x00"


def credential_scope(api_key: str) -> str:
    """Return a stable HMAC fingerprint without exposing an unkeyed key oracle.

    The Fernet configuration key is validated before derivation. HKDF's fixed,
    public ``info`` label separates this use from encryption and other purposes.
    Missing or malformed configuration fails closed in every environment.
    """
    configured_key = settings.API_KEY_ENCRYPTION_KEY
    if not isinstance(configured_key, str) or not configured_key:
        raise ValueError("Credential scope key is unavailable")
    if not isinstance(api_key, str) or not api_key:
        raise ValueError("Provider credential is unavailable")

    encoded_key = configured_key.encode("utf-8")
    try:
        Fernet(encoded_key)  # Enforce the application's canonical 32-byte Fernet secret.
        key_material = base64.urlsafe_b64decode(encoded_key)
        if len(key_material) != 32:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("Credential scope key is invalid") from exc

    derived_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        info=_INFO,
    ).derive(key_material)
    return hmac.new(
        derived_key,
        _MESSAGE_DOMAIN + api_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
