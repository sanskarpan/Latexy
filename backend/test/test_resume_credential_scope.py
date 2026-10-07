from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.core.config import settings
from app.services.resume_engine.credential_scope import credential_scope
from app.services.resume_engine.provider import ProviderSpec, SemanticProvider


@pytest.fixture
def fernet_key(monkeypatch):
    value = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", value)
    return value


def test_scope_is_stable_across_calls_and_provider_instances(fernet_key):
    api_key = "synthetic-provider-key-for-scope-test"
    spec = ProviderSpec("openai", "test-model", None, 0, 0, False)

    first = credential_scope(api_key)
    second = SemanticProvider(
        spec=spec,
        api_key=api_key,
        ledger=object(),
        deadline=1,
        cancelled=lambda: False,
        owner_scope="owner-a",
    )
    third = SemanticProvider(
        spec=spec,
        api_key=api_key,
        ledger=object(),
        deadline=1,
        cancelled=lambda: False,
        owner_scope="owner-b",
    )

    assert len(first) == 64
    assert first == credential_scope(api_key)
    assert first == second.credential_scope == third.credential_scope
    assert api_key not in first
    assert fernet_key not in first


def test_scope_is_separated_by_provider_key_and_server_key(monkeypatch):
    api_key = "synthetic-provider-key-for-scope-test"
    first_server_key = Fernet.generate_key().decode("ascii")
    second_server_key = Fernet.generate_key().decode("ascii")

    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", first_server_key)
    first_scope = credential_scope(api_key)
    assert credential_scope(api_key + "-other") != first_scope

    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", second_server_key)
    assert credential_scope(api_key) != first_scope


@pytest.mark.parametrize("configured_key", ["", None, "not-a-fernet-key", "MDAwMDAw"])
def test_missing_or_invalid_server_key_fails_closed_without_secret_echo(monkeypatch, configured_key):
    monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", configured_key)
    api_key = "synthetic-provider-secret-never-echo"

    with pytest.raises(ValueError) as exc_info:
        credential_scope(api_key)

    assert api_key not in str(exc_info.value)
    assert "Credential scope key" in str(exc_info.value)


def test_missing_provider_key_fails_closed(fernet_key):
    with pytest.raises(ValueError, match="Provider credential is unavailable"):
        credential_scope("")
