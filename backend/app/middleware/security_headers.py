"""
Security headers middleware.

Adds a small set of conservative, always-safe HTTP security headers to every
response. These do not affect JSON/API payloads or CORS behavior (CORS headers
are managed separately by CORSMiddleware).
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Headers that are safe to apply uniformly to API (JSON) and HTML responses.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            # Do not clobber a value a handler intentionally set.
            response.headers.setdefault(header, value)
        return response
