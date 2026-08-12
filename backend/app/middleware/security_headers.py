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

# Asset endpoints whose responses are meant to be embedded in the web app
# (template/resume PDF previews shown in an <iframe>, thumbnails). A blanket
# X-Frame-Options: DENY makes the browser refuse to render these cross-origin
# in latexy.xyz, so the preview shows a broken frame. Instead we allow framing
# from the app origins via CSP frame-ancestors (which supersedes X-Frame-Options
# in modern browsers) and skip the DENY for these paths only.
_APP_FRAME_ANCESTORS = (
    "frame-ancestors 'self' https://latexy.xyz https://www.latexy.xyz "
    "https://latexy-frontend-tau.vercel.app https://*.vercel.app"
)


def _is_framable_asset(path: str) -> bool:
    if path.startswith("/download/"):
        return True
    if path.startswith("/templates/") and (path.endswith("/pdf") or path.endswith("/thumbnail")):
        return True
    return False


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        framable = _is_framable_asset(request.url.path)
        for header, value in _SECURITY_HEADERS.items():
            # Framable asset endpoints must not be blocked from embedding.
            if header == "X-Frame-Options" and framable:
                continue
            # Do not clobber a value a handler intentionally set.
            response.headers.setdefault(header, value)
        if framable:
            response.headers.setdefault("Content-Security-Policy", _APP_FRAME_ANCESTORS)
        return response
