"""E2E tests for the consistent error envelope and global exception handlers."""

import json
import math
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, field_validator

from app.core.errors import error_body, register_exception_handlers


class _FiniteMetadataPayload(BaseModel):
    metadata: dict[str, Any]

    @field_validator("metadata")
    @classmethod
    def require_finite_numbers(cls, value: dict[str, Any]) -> dict[str, Any]:
        def visit(item: Any) -> None:
            if isinstance(item, dict):
                for child in item.values():
                    visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("metadata values must be finite JSON numbers")

        visit(value)
        return value


def test_error_body_shape():
    body = error_body("some_code", "a message", "req-123", details={"x": 1})
    assert body == {
        "error": {
            "code": "some_code",
            "message": "a message",
            "request_id": "req-123",
            "details": {"x": 1},
        }
    }


def test_error_body_omits_details_when_none():
    body = error_body("c", "m", None)
    assert "details" not in body["error"]
    assert body["error"]["request_id"] is None


def _build_app() -> FastAPI:
    from fastapi import HTTPException

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret internal detail")

    @app.get("/nope")
    async def nope():
        raise HTTPException(status_code=403, detail="forbidden reason")

    @app.post("/validate")
    async def validate(payload: dict):
        return payload

    @app.post("/validate-finite")
    async def validate_finite(payload: _FiniteMetadataPayload):
        return {"ok": True, "metadata": payload.metadata}

    @app.get("/gated")
    async def gated():
        # Mimics require_feature(): raises an HTTPException whose detail is
        # already an error envelope built via error_body().
        raise HTTPException(status_code=403, detail=error_body("feature_disabled", "The 'x' feature is not available on your plan.", None))

    return app


async def _client(app: FastAPI) -> AsyncClient:
    # raise_app_exceptions=False so the ServerErrorMiddleware 500 response is
    # returned to the test client instead of the exception re-propagating.
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


async def test_preformed_error_envelope_passes_through_without_double_wrap():
    """An HTTPException whose detail is already an error_body() envelope is
    surfaced as the top-level envelope (specific code preserved, not wrapped
    under a generic http_error)."""
    app = _build_app()
    async with await _client(app) as ac:
        resp = await ac.get("/gated")
    assert resp.status_code == 403
    body = resp.json()
    err = body["error"]
    assert err["code"] == "feature_disabled"
    assert "not available on your plan" in err["message"]
    assert "request_id" in err  # present (value depends on request-context middleware)
    # not double-wrapped under a nested detail.error envelope
    assert not isinstance(body.get("detail"), dict)


async def test_unhandled_exception_returns_generic_500_envelope():
    """Internal errors never leak the raw exception message to the client."""
    app = _build_app()
    async with await _client(app) as ac:
        resp = await ac.get("/boom")
    assert resp.status_code == 500
    err = resp.json()["error"]
    assert err["code"] == "internal_error"
    assert err["message"] == "An internal error occurred."
    assert "secret internal detail" not in resp.text


async def test_http_exception_preserves_status_and_detail():
    app = _build_app()
    async with await _client(app) as ac:
        resp = await ac.get("/nope")
    assert resp.status_code == 403
    err = resp.json()["error"]
    assert err["code"] == "http_error"
    assert err["message"] == "forbidden reason"


async def test_validation_error_returns_422_envelope_with_details():
    app = _build_app()
    async with await _client(app) as ac:
        # Missing required JSON body → RequestValidationError.
        resp = await ac.post("/validate", content=b"not json", headers={"content-type": "application/json"})
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "validation_error"
    assert isinstance(err["details"], list)


async def test_validation_error_sanitizes_nonfinite_mixed_nested_input_and_preserves_finite_values():
    app = _build_app()
    async with await _client(app) as ac:
        finite = await ac.post(
            "/validate-finite",
            content=json.dumps({"metadata": {"finite": 1.25}}, allow_nan=False),
            headers={"content-type": "application/json"},
        )
        invalid = await ac.post(
            "/validate-finite",
            content=json.dumps(
                {"metadata": {"finite": 1.25, "nested": [float("nan"), float("inf"), float("-inf")]}},
                allow_nan=True,
            ),
            headers={"content-type": "application/json"},
        )

    assert finite.status_code == 200
    assert finite.json() == {"ok": True, "metadata": {"finite": 1.25}}
    assert invalid.status_code == 422
    details = invalid.json()["error"]["details"]
    assert details[0]["input"]["finite"] == 1.25
    assert details[0]["input"]["nested"] == [None, None, None]
