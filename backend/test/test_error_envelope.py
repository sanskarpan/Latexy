"""E2E tests for the consistent error envelope and global exception handlers."""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import error_body, register_exception_handlers


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

    return app


async def _client(app: FastAPI) -> AsyncClient:
    # raise_app_exceptions=False so the ServerErrorMiddleware 500 response is
    # returned to the test client instead of the exception re-propagating.
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


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
