"""BYOK errors must not relay provider/SDK diagnostics to API clients."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi import HTTPException

import app.api.byok_routes as byok_routes
from app.api.byok_routes import GenerateWithProviderRequest
from app.core.logging import JsonFormatter
from app.services.api_key_service import APIKeyService

SECRET = "https://provider.example/request?api_key=do-not-leak"


@pytest.mark.asyncio
async def test_generate_error_does_not_expose_provider_exception(monkeypatch):
    async def fail(*_args, **_kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(byok_routes.api_key_service, "load_user_providers", fail)
    request = GenerateWithProviderRequest(
        provider="openai",
        messages=[{"role": "user", "content": "hello"}],
        model="gpt-4o-mini",
    )

    response = await byok_routes.generate_with_provider(request, db=None, user_id="user-1")

    assert response.error == "Provider request failed. Please try again."
    assert SECRET not in response.error


@pytest.mark.asyncio
async def test_generate_value_error_does_not_expose_provider_exception(monkeypatch):
    async def fail(*_args, **_kwargs):
        raise ValueError(SECRET)

    monkeypatch.setattr(byok_routes.api_key_service, "load_user_providers", fail)
    request = GenerateWithProviderRequest(
        provider="openai",
        messages=[{"role": "user", "content": "hello"}],
        model="gpt-4o-mini",
    )

    with pytest.raises(HTTPException) as caught:
        await byok_routes.generate_with_provider(request, db=None, user_id="user-1")

    assert caught.value.detail == "Provider request was invalid."
    assert SECRET not in str(caught.value.detail)


@pytest.mark.asyncio
async def test_validation_error_uses_safe_provider_independent_message():
    class Provider:
        def __init__(self, _api_key):
            self.last_validation_error = {
                "kind": "rejected",
                "message": SECRET,
            }

        async def validate_api_key(self):
            return False

    service = APIKeyService()
    service.provider_classes = {"openai": Provider}

    result = await service.validate_api_key("openai", "sk-test")

    assert result["error"] == "The provider rejected this API key."
    assert SECRET not in result["error"]


@pytest.mark.asyncio
async def test_add_key_storage_error_uses_safe_message():
    class FailingDB:
        async def execute(self, *_args, **_kwargs):
            raise RuntimeError(SECRET)

        async def rollback(self):
            return None

    result = await APIKeyService().add_api_key(
        db=FailingDB(),
        user_id="user-1",
        provider="openai",
        api_key="sk-test",
        validate_key=False,
    )

    assert result["error"] == "Failed to add API key. Please try again."
    assert SECRET not in result["error"]


@pytest.mark.asyncio
async def test_reference_provider_error_does_not_reach_response(monkeypatch):
    reference_routes = pytest.importorskip("app.api.reference_routes")

    async def fail(*_args, **_kwargs):
        raise ValueError(SECRET)

    monkeypatch.setattr(reference_routes.reference_service, "fetch_doi", fail)

    result = await reference_routes._fetch_one("10.1234/example")

    assert result.error == "Reference provider request failed. Please try again."
    assert SECRET not in result.error


def test_analytics_metadata_redacts_credentials_and_direct_identifiers():
    from app.api.analytics_routes import EventTrackingRequest

    request = EventTrackingRequest(
        event_type="editor_opened",
        metadata={
            "api_key": SECRET,
            "nested": [{"email": "person@example.com", "feature": "editor"}],
        },
    )

    assert request.metadata == {
        "api_key": "[redacted]",
        "nested": [{"email": "[redacted]", "feature": "editor"}],
    }

    with pytest.raises(ValueError):
        EventTrackingRequest(event_type="email=person@example.com\r\nsecret")


def test_frontend_telemetry_uses_bounded_log_labels():
    from app.api.telemetry_routes import _bucket_name, _bucket_route

    assert _bucket_name("business_event", "email=person@example.com\r\nsecret") == "other"
    assert _bucket_route("/user/person@example.com") == "other"


def test_json_logs_redact_url_queries_from_exception_messages():
    secret_url = "https://provider.example/request?opaque-secret=do-not-leak#token"
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        "provider failed: %s",
        (secret_url,),
        None,
    )

    formatted = JsonFormatter().format(record)

    assert "opaque-secret" not in formatted
    assert "do-not-leak" not in formatted
    assert "#token" not in formatted


def test_json_logs_preserve_safe_error_type_metadata():
    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "Operation failed", (), None)
    record.error_type = "TimeoutError"
    assert json.loads(JsonFormatter().format(record))["error_type"] == "TimeoutError"
