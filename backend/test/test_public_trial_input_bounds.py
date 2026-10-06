"""Offline safety checks for the public trial-usage input contract.

These tests deliberately use the real request model, route function, and trial
service with an in-memory async session double. They also exercise the actual
FastAPI route admission without opening the shared DB, Redis, or a provider.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import analytics_routes, routes
from app.database.models import DeviceTrial, UsageAnalytics
from app.services import feature_flag_service


class _ScalarResult:
    def scalar_one_or_none(self) -> None:
        return None


class _NestedTransaction:
    async def __aenter__(self) -> "_NestedTransaction":
        return self

    async def __aexit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> bool:
        return False


class _FakeDB:
    """Capture ORM objects without opening a database connection."""

    def __init__(self) -> None:
        self.added: list[object] = []

    async def execute(self, _statement: Any) -> _ScalarResult:
        return _ScalarResult()

    def begin_nested(self) -> _NestedTransaction:
        return _NestedTransaction()

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _Request:
    client = SimpleNamespace(host="198.51.100.20")


class _RecursionErrorString:
    def __str__(self) -> str:
        raise RecursionError("synthetic serializer recursion")


async def _submit_to_real_route(
    metadata: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> tuple[routes.TrackUsageResponse, UsageAnalytics]:
    """Run the actual route and service against only the fake DB above."""

    async def enabled(_key: str, _db: Any) -> bool:
        return True

    monkeypatch.setattr(feature_flag_service.feature_flag_service, "get_flag", enabled)
    db = _FakeDB()
    request_data = routes.TrackUsageRequest(
        deviceFingerprint="synthetic-device-input-bounds",
        sessionId="synthetic-session",
        action="compile",
        resourceType="resume",
        userAgent="synthetic-agent",
        metadata=metadata,
    )
    response = await routes.track_usage(request_data, _Request(), db)
    analytics = next(item for item in db.added if isinstance(item, UsageAnalytics))
    assert any(isinstance(item, DeviceTrial) for item in db.added)
    return response, analytics


def _test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(routes.router)
    return app


async def _post_public_trial(
    payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> tuple[int, dict[str, Any], _FakeDB]:
    async def enabled(_key: str, _db: Any) -> bool:
        return True

    monkeypatch.setattr(feature_flag_service.feature_flag_service, "get_flag", enabled)
    db = _FakeDB()

    async def override_db():
        yield db

    app = _test_app()
    app.dependency_overrides[routes.get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/public/track-usage", json=payload)
    return response.status_code, response.json(), db


@pytest.mark.asyncio
async def test_small_public_trial_metadata_is_still_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    response, analytics = await _submit_to_real_route(
        {"screen": "desktop", "language": "en"}, monkeypatch
    )

    assert response.success is True
    assert analytics.event_metadata == {"screen": "desktop", "language": "en"}


@pytest.mark.asyncio
async def test_public_trial_endpoint_rejects_oversized_metadata_before_db_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = {"blob": "x" * 5_000}
    assert len(json.dumps(metadata).encode("utf-8")) > analytics_routes._MAX_METADATA_BYTES

    status, body, db = await _post_public_trial(
        {
            "deviceFingerprint": "synthetic-device-input-bounds",
            "sessionId": "synthetic-session",
            "action": "compile",
            "metadata": metadata,
        },
        monkeypatch,
    )

    assert status == 422
    assert body["detail"]
    assert db.added == []


@pytest.mark.asyncio
async def test_public_trial_endpoint_rejects_deep_metadata_before_db_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata: dict[str, Any] = {}
    current = metadata
    for _ in range(8):
        child: dict[str, Any] = {}
        current["child"] = child
        current = child

    status, body, db = await _post_public_trial(
        {
            "deviceFingerprint": "synthetic-device-input-bounds",
            "action": "compile",
            "metadata": metadata,
        },
        monkeypatch,
    )

    assert status == 422
    assert body["detail"]
    assert db.added == []


@pytest.mark.asyncio
async def test_public_trial_endpoint_rejects_tiny_deep_metadata_before_db_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata: dict[str, Any] = {}
    current = metadata
    for _ in range(500):
        child: dict[str, Any] = {}
        current["child"] = child
        current = child

    status, body, db = await _post_public_trial(
        {
            "deviceFingerprint": "synthetic-device-input-bounds",
            "action": "compile",
            "metadata": metadata,
        },
        monkeypatch,
    )

    assert status == 422
    assert body["detail"]
    assert db.added == []


@pytest.mark.asyncio
async def test_public_trial_route_redacts_nested_sensitive_keys_and_preserves_safe_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = {
        "screen": "Résumé 😀",
        "items": [{"token": "synthetic-token"}, None],
        "nested": {"password": "synthetic-password", "language": "हिन्दी"},
    }

    response, analytics = await _submit_to_real_route(metadata, monkeypatch)

    assert response.success is True
    assert analytics.event_metadata == {
        "screen": "Résumé 😀",
        "items": [{"token": "[redacted]"}, None],
        "nested": {"password": "[redacted]", "language": "हिन्दी"},
    }


@pytest.mark.asyncio
async def test_public_trial_endpoint_accepts_max_fields_and_null_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, body, db = await _post_public_trial(
        {
            "deviceFingerprint": "d" * 255,
            "sessionId": "s" * 255,
            "action": "a" * 100,
            "resourceType": "r" * 50,
            "userAgent": "u" * 500,
            "metadata": None,
        },
        monkeypatch,
    )

    assert status == 200
    assert body["success"] is True
    analytics = next(item for item in db.added if isinstance(item, UsageAnalytics))
    assert analytics.event_metadata is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("deviceFingerprint", "x" * 256),
        ("sessionId", "x" * 256),
        ("action", "x" * 101),
        ("resourceType", "x" * 51),
        ("userAgent", "x" * 501),
    ],
)
async def test_public_trial_endpoint_rejects_values_beyond_storage_columns(
    field: str, value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload: dict[str, Any] = {
        "deviceFingerprint": "synthetic-device-input-bounds",
        "action": "compile",
    }
    payload[field] = value

    status, _body, db = await _post_public_trial(payload, monkeypatch)

    assert status == 422
    assert db.added == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fingerprint", ["", "x" * 256])
async def test_trial_status_rejects_unbounded_fingerprint_before_db_write(
    fingerprint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def enabled(_key: str, _db: Any) -> bool:
        return True

    monkeypatch.setattr(feature_flag_service.feature_flag_service, "get_flag", enabled)
    db = _FakeDB()

    async def override_db():
        yield db

    app = _test_app()
    app.dependency_overrides[routes.get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/public/trial-status", params={"fingerprint": fingerprint})

    assert response.status_code == 422
    assert db.added == []


def test_existing_analytics_contract_rejects_the_same_untrusted_shapes() -> None:
    with pytest.raises(ValueError):
        analytics_routes.EventTrackingRequest(
            event_type="page_view", metadata={"blob": "x" * 5_000}
        )

    nested: dict[str, Any] = {}
    current = nested
    for _ in range(8):
        child: dict[str, Any] = {}
        current["child"] = child
        current = child

    with pytest.raises(ValueError):
        analytics_routes.EventTrackingRequest(event_type="page_view", metadata=nested)


def test_metadata_depth_size_and_unicode_boundaries_are_explicit() -> None:
    exact_depth_five: Any = "ok"
    for _ in range(4):
        exact_depth_five = {"child": exact_depth_five}
    assert analytics_routes.EventTrackingRequest(
        event_type="page_view", metadata=exact_depth_five
    ).metadata == exact_depth_five

    too_deep: Any = "ok"
    for _ in range(5):
        too_deep = {"child": too_deep}
    with pytest.raises(ValueError, match="maximum depth"):
        analytics_routes.EventTrackingRequest(event_type="page_view", metadata=too_deep)

    exact_size = {"x": "a" * 4087}
    assert len(json.dumps(exact_size).encode("utf-8")) == analytics_routes._MAX_METADATA_BYTES
    assert analytics_routes.EventTrackingRequest(
        event_type="page_view", metadata=exact_size
    ).metadata == exact_size
    with pytest.raises(ValueError, match="maximum allowed size"):
        analytics_routes.EventTrackingRequest(
            event_type="page_view", metadata={"x": "a" * 4088}
        )

    unicode_payload = {"x": "é" * 682}
    assert len(json.dumps(unicode_payload).encode("utf-8")) > analytics_routes._MAX_METADATA_BYTES
    with pytest.raises(ValueError, match="maximum allowed size"):
        analytics_routes.EventTrackingRequest(event_type="page_view", metadata=unicode_payload)


def test_public_trial_serializer_recursion_is_reported_as_validation_error() -> None:
    with pytest.raises(ValueError, match="JSON-serializable"):
        routes.TrackUsageRequest(
            deviceFingerprint="synthetic-device-input-bounds",
            action="compile",
            metadata={"value": _RecursionErrorString()},
        )
