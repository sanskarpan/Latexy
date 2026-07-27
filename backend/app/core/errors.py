"""Consistent API error envelope and global exception handlers.

Every error response has the shape:
    {"error": {"code": str, "message": str, "request_id": str|null, "details": ...}}

Internal exceptions never leak stack traces or raw messages to the client; the
traceback is logged server-side with the request_id for correlation.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .logging import get_logger
from .observability import get_log_context

logger = get_logger(__name__)


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if rid:
        return rid
    return get_log_context().get("request_id")


def _cors_headers(request: Request) -> dict[str, str]:
    """CORS headers for error responses.

    Exception handlers return a JSONResponse directly, which bypasses
    CORSMiddleware (a Starlette ASGI-ordering limitation). Without this, every
    5xx / cold-start error reaches the browser WITHOUT an
    Access-Control-Allow-Origin header, so the browser reports a misleading
    "blocked by CORS policy" / net::ERR_FAILED instead of the real error. Echo
    the request Origin when it is allowed so errors surface truthfully.
    """
    origin = request.headers.get("origin")
    if not origin:
        return {}
    try:
        allowed = settings.effective_cors_origins()
    except Exception:
        allowed = settings.CORS_ORIGINS or []
    if origin in allowed or "*" in allowed:
        return {
            "access-control-allow-origin": origin,
            "access-control-allow-credentials": "true",
            "vary": "Origin",
        }
    return {}


def _merge_headers(request: Request, headers: dict | None) -> dict:
    merged = dict(headers or {})
    merged.update(_cors_headers(request))
    return merged


def error_body(code: str, message: str, request_id: str | None, details: Any = None, *, detail_compat: Any = None) -> dict:
    """Build the error envelope.

    A top-level ``detail`` key is preserved for backwards compatibility with the
    original FastAPI contract (existing clients read ``detail``); the structured
    ``error`` object is the forward-looking shape.
    """
    body: dict[str, Any] = {"error": {"code": code, "message": message, "request_id": request_id}}
    if details is not None:
        body["error"]["details"] = details
    if detail_compat is not None:
        body["detail"] = detail_compat
    return body


async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # jsonable_encoder mirrors FastAPI's default handler: pydantic error dicts can
    # carry non-serializable objects (e.g. a ValueError in `ctx`).
    details = jsonable_encoder(exc.errors())
    return JSONResponse(
        status_code=422,
        content=error_body(
            "validation_error", "Request validation failed.", _request_id(request),
            details=details, detail_compat=details,
        ),
        headers=_merge_headers(request, None),
    )


async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # HTTPException.detail is developer-authored (safe to surface). Preserve any
    # headers (e.g. WWW-Authenticate, Retry-After) the raising code attached.
    detail = exc.detail if isinstance(exc.detail, (str, list, dict)) else str(exc.detail)

    # If the raiser already built an error envelope via error_body() — e.g.
    # require_feature() raising {"error": {"code": "feature_disabled", ...}} —
    # pass it through as the top-level envelope instead of double-wrapping it
    # under a generic "http_error". This preserves the specific error code the
    # client (and frontend gating) keys on.
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        body = dict(detail)
        inner = dict(body["error"])
        if not inner.get("request_id"):
            inner["request_id"] = _request_id(request)
        body["error"] = inner
        return JSONResponse(
            status_code=exc.status_code,
            content=body,
            headers=_merge_headers(request, getattr(exc, "headers", None)),
        )

    message = detail if isinstance(detail, str) else "Request failed."
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body("http_error", message, _request_id(request), detail_compat=detail),
        headers=_merge_headers(request, getattr(exc, "headers", None)),
    )


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    rid = _request_id(request)
    # Log the full exception server-side; return a generic message to the client.
    logger.error(
        "unhandled_exception",
        exc_info=exc,
        extra={"path": request.url.path, "method": request.method, "request_id": rid},
    )
    return JSONResponse(
        status_code=500,
        content=error_body("internal_error", "An internal error occurred.", rid, detail_compat="Internal Server Error"),
        headers=_merge_headers(request, None),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register the global exception handlers on the FastAPI app."""
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
