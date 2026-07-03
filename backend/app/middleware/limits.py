"""Request body-size limit and request-timeout middleware."""

from __future__ import annotations

import asyncio

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..core.logging import get_logger

logger = get_logger(__name__)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose declared body exceeds a global byte ceiling (413).

    Guards against memory exhaustion from oversized uploads/JSON before the
    handler reads the body. Clients uploading files send Content-Length, so this
    is enforced up front.
    """

    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    return JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={
                            "error": {
                                "code": "payload_too_large",
                                "message": f"Request body exceeds the {self.max_bytes} byte limit.",
                                "request_id": getattr(request.state, "request_id", None),
                            }
                        },
                    )
            except ValueError:
                pass
        return await call_next(request)


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
