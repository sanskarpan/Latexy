"""
Request context middleware for correlation IDs and request metrics.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ..core.logging import get_logger
from ..core.observability import (
    elapsed_seconds,
    normalize_route_path,
    record_http_request,
    request_timer,
    reset_context,
    route_path_var,
    set_request_context,
    set_route_path,
)

logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach correlation IDs to requests and emit request metrics."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "").strip() or str(uuid4())
        request.state.request_id = request_id
        context_tokens = set_request_context(request_id=request_id)
        start = request_timer()

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            route_path = normalize_route_path(request.scope.get("route"), request.url.path)
            route_tokens = []
            route_token = set_route_path(route_path)
            if route_token is not None:
                route_tokens.append((route_path_var(), route_token))
            try:
                record_http_request(
                    method=request.method,
                    route_path=route_path,
                    status_code=500,
                    duration_seconds=elapsed_seconds(start),
                )
                logger.exception(
                    "request_failed",
                    extra={
                        "method": request.method,
                        "route": route_path,
                        "status_code": 500,
                    },
                )
            finally:
                if route_tokens:
                    reset_context(route_tokens)
                reset_context(context_tokens)
            raise

        route_path = normalize_route_path(request.scope.get("route"), request.url.path)
        route_tokens = []
        route_token = set_route_path(route_path)
        if route_token is not None:
            route_tokens.append((route_path_var(), route_token))
        try:
            record_http_request(
                method=request.method,
                route_path=route_path,
                status_code=status_code,
                duration_seconds=elapsed_seconds(start),
            )
        finally:
            if route_tokens:
                reset_context(route_tokens)

        response.headers["X-Request-ID"] = request_id
        reset_context(context_tokens)
        return response
