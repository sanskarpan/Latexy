"""Contract and auth tests for the review-only email status endpoint."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.email_status_routes import router
from app.database.connection import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.services.email_status_parser_service import MAX_RAW_EMAIL_BYTES

RAW_EMAIL = (
    "From: Acme Recruiting <jobs@acme.example>\n"
    "Subject: Your application for Data Analyst\n"
    "\n"
    "We have received your application."
)


async def _empty_db():
    yield object()


def _feature_dependency():
    route = next(item for item in router.routes if item.path == "/tracker/email-status/parse")
    return route.dependant.dependencies[0].call


def _isolated_app(*, authenticated: bool = False, feature_enabled: bool | None = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = _empty_db
    if authenticated:
        app.dependency_overrides[get_current_user_required] = lambda: "user-a"
    if feature_enabled is True:
        app.dependency_overrides[_feature_dependency()] = lambda: "user-a"
    elif feature_enabled is False:
        async def _deny():
            raise HTTPException(status_code=403, detail="feature disabled")

        app.dependency_overrides[_feature_dependency()] = _deny
    return app


async def _post(app: FastAPI, payload: object) -> object:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/tracker/email-status/parse", json=payload)


@pytest.mark.asyncio
async def test_parse_requires_authentication() -> None:
    response = await _post(_isolated_app(feature_enabled=None), {"raw_email": RAW_EMAIL})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_parse_requires_application_tracker_feature() -> None:
    response = await _post(_isolated_app(authenticated=True, feature_enabled=False), {"raw_email": RAW_EMAIL})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_parse_returns_review_only_canonical_contract_without_writes() -> None:
    app = _isolated_app(authenticated=True)
    db_calls = 0

    async def _tracking_db():
        nonlocal db_calls
        db_calls += 1
        yield object()

    # The review-only route has no request DB dependency and must not create a
    # session or touch tracker rows after its feature dependency is satisfied.
    app.dependency_overrides[get_db] = _tracking_db
    response = await _post(app, {"raw_email": RAW_EMAIL})
    assert response.status_code == 200
    assert db_calls == 0
    assert response.json() == {
        "status": "applied",
        "company": "Acme",
        "role": "Data Analyst",
        "confidence": 0.96,
        "company_confidence": 0.88,
        "role_confidence": 0.88,
        "evidence": [{"signal": "application received", "source": "body"}],
        "requires_review": True,
    }


@pytest.mark.asyncio
async def test_parse_rejects_unknown_fields() -> None:
    response = await _post(_isolated_app(authenticated=True), {"raw_email": RAW_EMAIL, "mutate": True})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_parse_uses_stable_422_for_malformed_and_oversized_input() -> None:
    malformed = await _post(_isolated_app(authenticated=True), {"raw_email": "From: user@example.test"})
    assert malformed.status_code == 422
    assert malformed.json()["detail"] == "Invalid forwarded email"

    oversized = await _post(
        _isolated_app(authenticated=True),
        {"raw_email": "From: user@example.test\n\n" + "x" * MAX_RAW_EMAIL_BYTES},
    )
    assert oversized.status_code == 422
    assert oversized.json()["detail"] == "Invalid forwarded email"
