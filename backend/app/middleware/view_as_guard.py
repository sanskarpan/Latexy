"""Refuse writes that present a read-only view-as preview token.

The preview token is not an authentication credential. It only unlocks the
snapshot GET route, and this outer guard prevents a client from accidentally
carrying it into any product or admin mutation. Ending a preview session is the
one allowed control write; the token is not required for that route.
"""

from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

VIEW_AS_TOKEN_HEADER = "x-view-as-token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_PREVIEW_PREFIX = "/admin/view-as/"
_END_SUFFIX = "/end"


class ViewAsReadOnlyMiddleware(BaseHTTPMiddleware):
    """Reject any non-GET request that carries a view-as preview token."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        token = request.headers.get(VIEW_AS_TOKEN_HEADER)
        if not token:
            return await call_next(request)

        path = request.url.path.rstrip("/") or "/"
        method = request.method.upper()
        if method in _SAFE_METHODS and path.startswith(_PREVIEW_PREFIX):
            return await call_next(request)
        if (
            method == "POST"
            and path.startswith(f"{_PREVIEW_PREFIX}sessions/")
            and path.endswith(_END_SUFFIX)
        ):
            return await call_next(request)

        return JSONResponse(
            {
                "detail": {
                    "code": "view_as_read_only",
                    "message": (
                        "View-as preview sessions are read-only; this request "
                        "was refused."
                    ),
                }
            },
            status_code=403,
        )
