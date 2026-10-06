"""Request body-size limit and request-timeout middleware."""

from __future__ import annotations

import asyncio

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..core.logging import get_logger

logger = get_logger(__name__)


class BodySizeLimitMiddleware:
    """Bound both declared and chunked request bodies before handlers read them."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    def _too_large_response(self, request_id: str | None = None) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={
                "error": {
                    "code": "payload_too_large",
                    "message": f"Request body exceeds the {self.max_bytes} byte limit.",
                    "request_id": request_id,
                }
            },
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length.decode("ascii")) > self.max_bytes:
                    await self._too_large_response()(scope, receive, send)
                    return
            except (UnicodeDecodeError, ValueError):
                pass

        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            total += len(body)
            if total > self.max_bytes:
                await self._too_large_response()(scope, receive, send)
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break

        replayed = False
        response_finished = asyncio.Event()

        async def replay_receive() -> Message:
            nonlocal replayed
            if replayed:
                # End-of-body is not a client disconnect. An immediate disconnect
                # here makes Starlette cancel streaming responses before they emit.
                await response_finished.wait()
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": b"".join(chunks), "more_body": False}

        try:
            await self.app(scope, replay_receive, send)
        finally:
            response_finished.set()


class TimeoutMiddleware(BaseHTTPMiddleware):
    """Abort a request that exceeds a wall-clock timeout with 504.

    Prevents a slow LaTeX/LLM/scraper handler from tying up a worker forever.
    """

    def __init__(self, app, timeout_seconds: float) -> None:
        super().__init__(app)
        self.timeout_seconds = timeout_seconds

    async def dispatch(self, request: Request, call_next):
        try:
            return await asyncio.wait_for(call_next(request), timeout=self.timeout_seconds)
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning(
                "request_timeout",
                extra={"path": request.url.path, "method": request.method, "timeout_s": self.timeout_seconds},
            )
            return JSONResponse(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                content={
                    "error": {
                        "code": "request_timeout",
                        "message": "The request took too long to process.",
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
            )
        except RuntimeError as exc:
            # Starlette's BaseHTTPMiddleware uses this exact exception when a
            # downstream handler observes http.disconnect before it has sent a
            # response. This is normal for a browser aborting a poll (the user
            # starts another compile, navigates away, or the tab is suspended),
            # and must not be logged as a server failure or turned into a 500.
            # Keep the response shape valid for the outer middleware stack; the
            # ASGI server will discard it if the socket is already closed.
            if str(exc) != "No response returned.":
                raise
            # The same RuntimeError is also raised when an application simply
            # returns without sending a response. Do not hide that programming
            # error behind a client-abort status. `_wrapped_rcv_disconnected`
            # is set by Starlette's _CachedRequest when its downstream app has
            # consumed an actual disconnect frame; `is_disconnected()` covers
            # middleware stacks that expose the receive channel directly.
            disconnected = await request.is_disconnected()
            disconnected = disconnected or bool(getattr(request, "_wrapped_rcv_disconnected", False))
            if not disconnected:
                raise
            logger.debug(
                "request_client_disconnected",
                extra={"path": request.url.path, "method": request.method},
            )
            return JSONResponse(status_code=499, content=None)
