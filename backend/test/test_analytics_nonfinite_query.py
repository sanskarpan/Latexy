"""ASGI regression coverage for finite analytics query parameters."""

import math
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import analytics_routes
from app.core.errors import register_exception_handlers


class _StrictFakeDB:
    """Marker dependency: this test must never open a database connection."""


async def _fake_db():
    yield _StrictFakeDB()


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(analytics_routes.router)
    app.dependency_overrides[analytics_routes.get_db] = _fake_db
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_value", "expected_status", "expected_value"),
    [
        ("1.25", 201, 1.25),
        ("0", 201, 0.0),
        ("-1.25", 201, -1.25),  # This repair adds no new range restriction.
        (None, 201, None),
        ("NaN", 422, None),
        ("nan", 422, None),
        ("Infinity", 422, None),
        ("-Infinity", 422, None),
        ("1e309", 422, None),
        ("-1e309", 422, None),
    ],
)
async def test_compilation_time_query_rejects_nonfinite_before_jsonb_persistence(
    raw_value: str | None, expected_status: int, expected_value: float | None,
) -> None:
    persisted_values: list[float | None] = []

    async def strict_fake_persistence(*, compilation_time=None, **_kwargs):
        persisted_values.append(compilation_time)
        if compilation_time is not None and not math.isfinite(compilation_time):
            raise AssertionError("non-finite compilation time reached persistence")
        return True

    service_call = AsyncMock(side_effect=strict_fake_persistence)
    params = {"compilation_id": "synthetic-compilation", "status": "completed"}
    if raw_value is not None:
        params["compilation_time"] = raw_value
    with patch.object(analytics_routes.analytics_service, "track_compilation_event", service_call):
        async with AsyncClient(
            transport=ASGITransport(app=_app(), raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/analytics/track/compilation",
                params=params,
            )

    assert response.status_code == expected_status
    if expected_status == 201:
        assert response.json() == {"message": "Compilation event tracked successfully"}
        assert persisted_values == [expected_value]
        service_call.assert_awaited_once()
    else:
        body = response.json()
        assert body["error"]["code"] == "validation_error"
        detail = body["error"]["details"][0]
        assert detail["loc"] == ["query", "compilation_time"]
        assert detail["type"]
        assert detail["msg"]
        assert "input" not in detail
        assert "ctx" not in detail
        assert persisted_values == []
        service_call.assert_not_awaited()
