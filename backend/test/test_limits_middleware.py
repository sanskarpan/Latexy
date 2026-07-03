"""E2E tests for BodySizeLimitMiddleware (413) and TimeoutMiddleware (504)."""

import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

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

    return app


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_oversized_body_rejected_with_413():
    app = _build_app(max_bytes=50)
    async with await _client(app) as ac:
        resp = await ac.post("/echo", content=b"x" * 500, headers={"content-type": "application/json"})
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
