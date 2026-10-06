"""Same-origin protection for ambient Better Auth session-cookie requests.

The REST API primarily uses explicit ``Authorization: Bearer`` credentials,
which are not sent by a browser cross-site. Better Auth session cookies are
ambient credentials, however, so mutating requests carrying one must prove
that they originated from an allowed application origin.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from ..core.config import settings

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_SESSION_COOKIE_NAMES = (
    "better-auth.session_token",
    "__Secure-better-auth.session_token",
)


def _origin(value: str) -> str | None:
    """Normalize an Origin or Referer value to ``scheme://host``."""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/").lower()


def _allowed_origins(request: Request) -> set[str]:
    allowed: set[str] = set()
    for candidate in settings.effective_cors_origins() or []:
        if isinstance(candidate, str):
            normalized = _origin(candidate)
            if normalized:
                allowed.add(normalized)

    frontend_url = getattr(settings, "FRONTEND_URL", "")
    if isinstance(frontend_url, str):
        normalized = _origin(frontend_url)
        if normalized:
            allowed.add(normalized)

    # Same-host deployments (including verified custom domains) do not need to
    # enumerate the API host in the static frontend CORS list.
    request_host = request.headers.get("host")
    if request_host:
        normalized = _origin(f"{request.url.scheme}://{request_host}")
        if normalized:
            allowed.add(normalized)
    return allowed


def _request_origin(request: Request) -> str | None:
    # Browsers send Origin on all mutating fetches. Referer is the compatibility
    # fallback for older navigation/form clients that omit Origin.
    raw_origin = request.headers.get("origin")
    if raw_origin is not None:
        return _origin(raw_origin)
    return _origin(request.headers.get("referer", ""))


def _has_explicit_bearer(request: Request) -> bool:
    """Return true only for a non-empty supported bearer credential.

    An arbitrary ``Authorization`` value (for example ``Basic ...``) must not
    disable CSRF checks: FastAPI's auth dependency can still fall back to the
    ambient session cookie when it cannot parse that scheme.
    """
    value = request.headers.get("authorization", "").strip()
    scheme, separator, token = value.partition(" ")
    return bool(separator and scheme.lower() == "bearer" and token.strip())


async def _is_verified_custom_origin(origin: str) -> bool:
    """Accept a dynamic tenant origin only after DNS verification."""
    try:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.port is not None
        ):
            return False
        # Import lazily to avoid making tenant resolution part of application
        # startup and to keep this middleware usable in isolated unit tests.
        from . import tenant_middleware

        return (
            await tenant_middleware.resolve_tenant_origin_hostname(parsed.hostname.lower())
        ) is not None
    except Exception:
        return False


class SessionCookieCSRFMiddleware(BaseHTTPMiddleware):
    """Reject cross-site state changes authenticated only by a session cookie."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if (
            request.method.upper() in _UNSAFE_METHODS
            and not _has_explicit_bearer(request)
            and any(request.cookies.get(name) for name in _SESSION_COOKIE_NAMES)
        ):
            origin = _request_origin(request)
            allowed = origin is not None and origin in _allowed_origins(request)
            if not allowed and origin is not None:
                allowed = await _is_verified_custom_origin(origin)
            if not allowed:
                return JSONResponse(
                    {
                        "detail": (
                            "Cross-site requests are not allowed for "
                            "session-authenticated mutations"
                        )
                    },
                    status_code=403,
                )
        return await call_next(request)
