"""Tests for BYOK API key encryption/decryption round-trip (L25)."""

import pytest
from cryptography.fernet import Fernet

from app.services.encryption_service import (
    EncryptionService,
    decrypt_api_key,
    decrypt_data,
    encrypt_api_key,
    encrypt_data,
)


class TestEncryptDecryptRoundTrip:
    """Basic encrypt/decrypt round-trip tests."""

    def test_encrypt_decrypt_simple(self):
        svc = EncryptionService()
        plaintext = "sk-test-1234567890abcdef"
        encrypted = svc.encrypt(plaintext)
        assert encrypted != plaintext
        assert svc.decrypt(encrypted) == plaintext

    def test_encrypt_decrypt_empty_string(self):
        svc = EncryptionService()
        encrypted = svc.encrypt("")
        assert svc.decrypt(encrypted) == ""

    def test_encrypt_decrypt_long_key(self):
        svc = EncryptionService()
        long_key = "sk-" + "x" * 500
        encrypted = svc.encrypt(long_key)
        assert svc.decrypt(encrypted) == long_key

    def test_encrypt_produces_different_ciphertext_each_call(self):
        svc = EncryptionService()
        plaintext = "same_plaintext"
        enc1 = svc.encrypt(plaintext)
        enc2 = svc.encrypt(plaintext)
        # Fernet uses random IV — same plaintext yields different ciphertext
        assert enc1 != enc2
        # But both decrypt to the same plaintext
        assert svc.decrypt(enc1) == plaintext
        assert svc.decrypt(enc2) == plaintext

    def test_encrypt_decrypt_special_characters(self):
        svc = EncryptionService()
        special = "sk-abc/+==\n\t!@#$%^&*()"
        assert svc.decrypt(svc.encrypt(special)) == special

    def test_encrypt_decrypt_unicode(self):
        svc = EncryptionService()
        unicode_val = "кey-тест-日本語"
        assert svc.decrypt(svc.encrypt(unicode_val)) == unicode_val

    def test_two_instances_same_key_are_compatible(self):
        """Two EncryptionService instances initialised with the same key can cross-decrypt."""
        key = "test-shared-secret-key-12345678"
        svc1 = EncryptionService(encryption_key=key)
        svc2 = EncryptionService(encryption_key=key)
        plaintext = "cross-instance-test"
        encrypted = svc1.encrypt(plaintext)
        assert svc2.decrypt(encrypted) == plaintext

    def test_two_instances_different_keys_cannot_cross_decrypt(self):
        svc1 = EncryptionService(encryption_key="key-aaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        svc2 = EncryptionService(encryption_key="key-bbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        encrypted = svc1.encrypt("secret")
        with pytest.raises(Exception):  # InvalidToken or similar
            svc2.decrypt(encrypted)


class TestAPIKeyEncryption:
    """Tests for provider-scoped API key encryption."""

    def test_encrypt_decrypt_api_key_openai(self):
        svc = EncryptionService()
        api_key = "sk-openai-testkey123"
        provider = "openai"
        encrypted = svc.encrypt_api_key(api_key, provider)
        assert svc.decrypt_api_key(encrypted, provider) == api_key

    def test_encrypt_decrypt_api_key_anthropic(self):
        svc = EncryptionService()
        api_key = "sk-ant-api03-testkey456"
        provider = "anthropic"
        encrypted = svc.encrypt_api_key(api_key, provider)
        assert svc.decrypt_api_key(encrypted, provider) == api_key

    def test_wrong_provider_raises_value_error(self):
        svc = EncryptionService()
        encrypted = svc.encrypt_api_key("sk-abc", "openai")
        with pytest.raises(ValueError, match="provider mismatch"):
            svc.decrypt_api_key(encrypted, "anthropic")

    def test_api_key_with_colon_in_key(self):
        """Provider prefix uses ':' as separator — key itself may contain ':'."""
        svc = EncryptionService()
        api_key = "key:with:colons"
        provider = "openrouter"
        encrypted = svc.encrypt_api_key(api_key, provider)
        assert svc.decrypt_api_key(encrypted, provider) == api_key

    def test_empty_api_key(self):
        svc = EncryptionService()
        encrypted = svc.encrypt_api_key("", "openai")
        assert svc.decrypt_api_key(encrypted, "openai") == ""


class TestIsEncrypted:
    def test_encrypted_data_detected(self):
        svc = EncryptionService()
        encrypted = svc.encrypt("some api key")
        assert svc.is_encrypted(encrypted) is True

    def test_plaintext_not_detected_as_encrypted(self):
        svc = EncryptionService()
        assert svc.is_encrypted("sk-plain-key-not-encrypted") is False

    def test_short_string_not_detected(self):
        svc = EncryptionService()
        assert svc.is_encrypted("abc") is False


class TestGenerateKey:
    def test_generate_key_is_valid_fernet_key(self):
        svc = EncryptionService()
        key = svc.generate_key()
        # Fernet.generate_key() output is 44 chars base64url
        assert isinstance(key, str)
        assert len(key) == 44
        # Verify it can be used to create a Fernet instance without error
        Fernet(key.encode())

    def test_generate_key_produces_unique_keys(self):
        svc = EncryptionService()
        keys = {svc.generate_key() for _ in range(5)}
        assert len(keys) == 5


class TestModuleLevelHelpers:
    def test_encrypt_data_decrypt_data(self):
        plaintext = "helper-function-test"
        assert decrypt_data(encrypt_data(plaintext)) == plaintext

    def test_encrypt_api_key_decrypt_api_key_helper(self):
        api_key = "sk-helper-test"
        provider = "gemini"
        assert decrypt_api_key(encrypt_api_key(api_key, provider), provider) == api_key
