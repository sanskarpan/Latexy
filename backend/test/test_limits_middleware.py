"""E2E tests for BodySizeLimitMiddleware (413) and TimeoutMiddleware (504)."""

import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import StreamingResponse

from app.middleware.limits import BodySizeLimitMiddleware, TimeoutMiddleware


def _build_app(*, max_bytes: int = 100, timeout_seconds: float = 0.2) -> FastAPI:
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)
    app.add_middleware(TimeoutMiddleware, timeout_seconds=timeout_seconds)

    @app.post("/echo")
    async def echo(payload: dict):
        return {"ok": True}

    @app.get("/slow")
    async def slow():
        await asyncio.sleep(1.0)
        return {"ok": True}

    @app.get("/fast")
    async def fast():
        return {"ok": True}

    @app.get("/stream")
    async def stream():
        async def body():
            yield b"first-"
            yield b"second"

        return StreamingResponse(body())

    return app


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_oversized_body_rejected_with_413():
    app = _build_app(max_bytes=50)
    async with await _client(app) as ac:
        resp = await ac.post("/echo", content=b"x" * 500, headers={"content-type": "application/json"})
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"


async def test_oversized_chunked_body_without_content_length_is_rejected():
    async def chunks():
        yield b"x" * 30
        yield b"y" * 30

    app = _build_app(max_bytes=50)
    async with await _client(app) as ac:
        resp = await ac.post(
            "/echo",
            content=chunks(),
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"


async def test_body_within_limit_passes_size_check():
    app = _build_app(max_bytes=10_000)
    async with await _client(app) as ac:
        resp = await ac.post("/echo", json={"a": 1})
    assert resp.status_code == 200


async def test_slow_request_times_out_with_504():
    app = _build_app(timeout_seconds=0.1)
    async with await _client(app) as ac:
        resp = await ac.get("/slow")
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "request_timeout"


async def test_fast_request_not_timed_out():
    app = _build_app(timeout_seconds=1.0)
    async with await _client(app) as ac:
        resp = await ac.get("/fast")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


async def test_streaming_response_is_not_mistaken_for_client_disconnect():
    app = _build_app()
    async with await _client(app) as ac:
        resp = await ac.get("/stream")
    assert resp.status_code == 200
    assert resp.content == b"first-second"


async def test_aborted_poll_does_not_raise_no_response_returned():
    """A browser abort can make BaseHTTPMiddleware see a disconnect before
    the route emits headers. It is a client lifecycle event, not a 500."""

    async def no_response(scope, receive, send):
        await receive()

    middleware = TimeoutMiddleware(no_response, timeout_seconds=1)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/jobs/job-1/state",
        "raw_path": b"/jobs/job-1/state",
        "query_string": b"",
        "headers": [],
        "server": ("test", 80),
        "client": ("test", 1234),
    }
    received = False
    sent = []

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    assert any(message.get("type") == "http.response.start" and message.get("status") == 499 for message in sent)


async def test_missing_response_without_disconnect_is_not_swallowed():
    """The middleware must continue surfacing an app that returns without
    emitting an ASGI response."""

    async def no_response(scope, receive, send):
        await receive()

    middleware = TimeoutMiddleware(no_response, timeout_seconds=1)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/jobs/job-1/state",
        "raw_path": b"/jobs/job-1/state",
        "query_string": b"",
        "headers": [],
        "server": ("test", 80),
        "client": ("test", 1234),
    }
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    try:
        await middleware(scope, receive, send)
    except RuntimeError as exc:
        assert str(exc) == "No response returned."
    else:
        raise AssertionError("missing downstream response was swallowed")
    assert sent == []


async def test_short_circuited_413_carries_cors_headers():
    """CORSMiddleware must wrap the limit middlewares so browsers can read the 413."""
    from app.core.config import settings
    from app.main import app as real_app

    oversized = b"x" * (settings.MAX_REQUEST_BODY_BYTES + 1)
    async with await _client(real_app) as ac:
        resp = await ac.post(
            "/compile",
            content=oversized,
            headers={"content-type": "application/json", "origin": "http://localhost:5180"},
        )
    assert resp.status_code == 413
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5180"
    # The fix is only useful if JS can actually read the diagnostic headers.
    exposed = {h.strip().lower() for h in resp.headers.get("access-control-expose-headers", "").split(",")}
    assert "retry-after" in exposed
    assert "x-request-id" in exposed


def test_cors_middleware_is_outermost():
    """Verified tenant CORS wraps static CORS; both remain outside limiters."""
    from starlette.middleware.cors import CORSMiddleware

    from app.main import app as real_app
    from app.middleware.tenant_middleware import VerifiedTenantCORSMiddleware

    assert real_app.user_middleware[0].cls is VerifiedTenantCORSMiddleware
    assert real_app.user_middleware[1].cls is CORSMiddleware


async def test_preflight_short_circuits_at_cors_and_is_allowed():
    """Documented consequence of CORS being outermost: OPTIONS never reaches the
    inner middlewares (no rate limiting / tenant resolution), and CORS answers it
    itself. Access-Control-Expose-Headers belongs on the actual response, not the
    preflight, so it is asserted in the 413 test instead."""
    from app.main import app as real_app

    async with await _client(real_app) as ac:
        resp = await ac.options(
            "/compile",
            headers={
                "origin": "http://localhost:5180",
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type,authorization",
            },
        )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5180"
    assert resp.headers["access-control-allow-credentials"] == "true"
    assert "authorization" in resp.headers.get("access-control-allow-headers", "").lower()
