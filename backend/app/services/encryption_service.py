"""
Encryption service for securing sensitive data like API keys.

This is the authoritative encryption implementation. All encryption in the
application should go through this service — api_key_service.APIKeyEncryption
is a thin wrapper over this class.

Key strategy:
  - If API_KEY_ENCRYPTION_KEY is a valid Fernet key (44-char URL-safe base64):
      use it directly (matches the format required for BYOK production keys).
  - Otherwise (arbitrary password string or absent):
      derive a Fernet key via PBKDF2HMAC — used in dev/test environments.
"""

import base64
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

_PBKDF2_SALT = b'latexy_salt_16b!'  # 16 bytes — fixed salt for deterministic derivation


class EncryptionService:
    """Authoritative service for encrypting and decrypting sensitive data."""

    def __init__(self, encryption_key: Optional[str] = None):
        raw_key = encryption_key or os.getenv('API_KEY_ENCRYPTION_KEY')
        if raw_key:
            key_bytes = raw_key.encode() if isinstance(raw_key, str) else raw_key
            # Use directly if it is already a valid Fernet key; otherwise derive via PBKDF2.
            try:
                Fernet(key_bytes)  # raises if not a valid Fernet key
                self._fernet = Fernet(key_bytes)
            except Exception:
                self._fernet = Fernet(self._derive_key(key_bytes))
        else:
            logger.warning(
                "API_KEY_ENCRYPTION_KEY is not set — using development fallback. "
                "Set this variable in production!"
            )
            self._fernet = Fernet(self._derive_key(b'latexy_dev_key_fallback!'))

    @staticmethod
    def _derive_key(password: bytes) -> bytes:
        """Derive a 32-byte Fernet key from an arbitrary password via PBKDF2HMAC."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_PBKDF2_SALT,
            iterations=100_000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password))

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string and return a base64-encoded ciphertext."""
        token = self._fernet.encrypt(plaintext.encode())
        return base64.b64encode(token).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a base64-encoded ciphertext and return the plaintext."""
        try:
            token = base64.b64decode(ciphertext.encode())
            return self._fernet.decrypt(token).decode()
        except (InvalidToken, Exception) as e:
            logger.error(f"Decryption failed: {e}")
            raise

    def encrypt_api_key(self, api_key: str, provider: str) -> str:
        """Encrypt an API key, embedding the provider as a prefix for verification."""
        return self.encrypt(f"{provider}:{api_key}")

    def decrypt_api_key(self, encrypted_key: str, expected_provider: str) -> str:
        """Decrypt a provider-scoped API key and verify the provider prefix."""
        decrypted = self.decrypt(encrypted_key)
        prefix = f"{expected_provider}:"
        if not decrypted.startswith(prefix):
            raise ValueError(f"API key provider mismatch. Expected {expected_provider}")
        return decrypted[len(prefix):]

    def is_encrypted(self, data: str) -> bool:
        """Heuristic: return True if data looks like output from encrypt()."""
        try:
            base64.b64decode(data.encode(), validate=True)
            return len(data) > 20 and len(data) % 4 == 0
        except Exception:
            return False

    def generate_key(self) -> str:
        """Generate a new random Fernet key (suitable as API_KEY_ENCRYPTION_KEY)."""
        return Fernet.generate_key().decode()


# Module-level singleton
encryption_service = EncryptionService()


# Utility helpers (backward-compatible)
def encrypt_data(plaintext: str) -> str:
    return encryption_service.encrypt(plaintext)


def decrypt_data(ciphertext: str) -> str:
    return encryption_service.decrypt(ciphertext)


def encrypt_api_key(api_key: str, provider: str) -> str:
    return encryption_service.encrypt_api_key(api_key, provider)


def decrypt_api_key(encrypted_key: str, provider: str) -> str:
    return encryption_service.decrypt_api_key(encrypted_key, provider)
