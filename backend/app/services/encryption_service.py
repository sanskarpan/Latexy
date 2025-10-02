"""
Encryption service for securing sensitive data like API keys.
"""

import base64
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class EncryptionService:
    """Service for encrypting and decrypting sensitive data."""
    
    def __init__(self, encryption_key: Optional[str] = None):
        """Initialize encryption service with a key."""
        if encryption_key:
            self.key = encryption_key.encode()
        else:
            # Use environment variable or generate a key
            env_key = os.getenv('API_KEY_ENCRYPTION_KEY')
            if env_key:
                self.key = env_key.encode()
            else:
                # Generate a key for development (not recommended for production)
                self.key = b'development_key_32_chars_long!!'
                logger.warning("Using development encryption key. Set API_KEY_ENCRYPTION_KEY in production!")
        
        # Derive a Fernet key from the provided key
        self.fernet_key = self._derive_key(self.key)
        self.cipher = Fernet(self.fernet_key)
    
    def _derive_key(self, password: bytes) -> bytes:
        """Derive a Fernet key from a password."""
        # Use a fixed salt for consistency (in production, use a proper salt management)
        salt = b'latexy_salt_16b!'  # 16 bytes salt
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password))
        return key
    
    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string and return base64 encoded result."""
        try:
            encrypted_data = self.cipher.encrypt(plaintext.encode())
            return base64.urlsafe_b64encode(encrypted_data).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise
    
    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt base64 encoded encrypted data and return plaintext."""
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
            decrypted_data = self.cipher.decrypt(encrypted_bytes)
            return decrypted_data.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise
    
    def encrypt_api_key(self, api_key: str, provider: str) -> str:
        """Encrypt an API key with provider context."""
        # Add provider prefix for additional security
        prefixed_key = f"{provider}:{api_key}"
        return self.encrypt(prefixed_key)
    
    def decrypt_api_key(self, encrypted_key: str, expected_provider: str) -> str:
        """Decrypt an API key and verify provider context."""
        decrypted = self.decrypt(encrypted_key)
        
        # Verify provider prefix
        if not decrypted.startswith(f"{expected_provider}:"):
            raise ValueError(f"API key provider mismatch. Expected {expected_provider}")
        
        # Remove provider prefix
        return decrypted[len(expected_provider) + 1:]
    
    def is_encrypted(self, data: str) -> bool:
        """Check if data appears to be encrypted (base64 encoded)."""
        try:
            # Try to decode as base64
            base64.urlsafe_b64decode(data.encode())
            # If successful and reasonable length, likely encrypted
            return len(data) > 20 and len(data) % 4 == 0
        except Exception:
            return False
    
    def generate_key(self) -> str:
        """Generate a new encryption key."""
        return Fernet.generate_key().decode()

# Global encryption service instance
encryption_service = EncryptionService()

# Utility functions
def encrypt_data(plaintext: str) -> str:
    """Utility function to encrypt data."""
    return encryption_service.encrypt(plaintext)

def decrypt_data(encrypted_data: str) -> str:
    """Utility function to decrypt data."""
    return encryption_service.decrypt(encrypted_data)

def encrypt_api_key(api_key: str, provider: str) -> str:
    """Utility function to encrypt API key with provider context."""
    return encryption_service.encrypt_api_key(api_key, provider)

def decrypt_api_key(encrypted_key: str, provider: str) -> str:
    """Utility function to decrypt API key with provider verification."""
    return encryption_service.decrypt_api_key(encrypted_key, provider)
