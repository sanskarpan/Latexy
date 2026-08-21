"""
Rate limiting middleware for API endpoints.
"""

import hashlib
import time
from typing import Optional

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import redis_manager

logger = get_logger(__name__)

# Throttle the fail-open "Redis unavailable" warning so a sustained Redis outage
# does not flood the logs (one line per interval instead of one per request).
_FAIL_OPEN_WARN_INTERVAL = 60.0
_last_fail_open_warn = 0.0


def _client_addr_was_rewritten(request: Request) -> bool:
    """Whether uvicorn's proxy-headers layer replaced ``request.client`` from XFF.

    That layer runs outside the app, so by the time we look, a rewritten address is
    indistinguishable from a real one BY VALUE — checking whether the host looks like
    a trusted proxy is useless, because the host we can see is already the spoofed
    one. It does leave a fingerprint though: it cannot recover the peer's port and
    sets ``(host, 0)`` (uvicorn/middleware/proxy_headers.py). A real TCP peer never
    has port 0, so this identifies exactly the requests whose address is untrustworthy
    — and only those, instead of everything that merely carries an XFF.
    """
    client = request.client
    return client is not None and getattr(client, "port", None) == 0


def client_ip_id(request: Request) -> str:
    """Peer-IP rate-limit bucket, ``ip:<addr>``.

    Proxy headers are only honoured behind a trusted proxy (TRUST_PROXY_HEADERS,
    shipped as true in every manifest that puts the bundled nginx in front of us);
    otherwise any caller could rotate them for a fresh bucket per request.

    When trusted, prefer ``X-Real-IP``: nginx sets it with ``$remote_addr``, which
    fully OVERWRITES whatever the client sent. ``X-Forwarded-For`` is built with
    ``$proxy_add_x_forwarded_for``, i.e. the client's own value with the real peer
    APPENDED — so the trustworthy hop is the last one, never ``split(",")[0]``.

    When we do NOT trust proxies, the peer address is used — it is a real socket
    address and cannot be spoofed — UNLESS uvicorn already rewrote it from the header
    (see _client_addr_was_rewritten), in which case those requests, and only those,
    share one bucket. Collapsing every request that merely CARRIES an X-Forwarded-For
    would be a self-DoS: nginx always adds the header, so one attacker could 429 the
    whole site any time TRUST_PROXY_HEADERS is unset.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if getattr(settings, "TRUST_PROXY_HEADERS", False):
        real_ip = (request.headers.get("X-Real-IP") or "").strip()
        if real_ip:
            return f"ip:{real_ip}"
        if forwarded_for:
            return f"ip:{forwarded_for.rsplit(',', 1)[-1].strip()}"
    elif forwarded_for and _client_addr_was_rewritten(request):
        return "ip:untrusted-proxy"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def _spoof_resistant_client_id(request: Request) -> str:
    """Shared, spoofing-resistant client identifier used by all rate limiters.

    Keys on the caller's own credential (session token / bearer) when present —
    unforgeable, unlike a plain X-User-ID header. Falls back to the peer IP;
    X-Forwarded-For is only honoured behind a trusted proxy (TRUST_PROXY_HEADERS).
    """
    token: Optional[str] = None
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        cookie_tok = (
            request.cookies.get("better-auth.session_token")
            or request.cookies.get("__Secure-better-auth.session_token")
        )
        if cookie_tok:
            token = cookie_tok.split(".", 1)[0]
    if token:
        return "user:" + hashlib.sha256(token.encode()).hexdigest()[:32]

    return client_ip_id(request)


# Public alias — per-route limiters (ATS, scraper, …) must key on this rather than
# rolling their own X-Forwarded-For parsing, which is trivially spoofed.
client_rate_limit_id = _spoof_resistant_client_id


def _warn_fail_open(context: str) -> None:
    """Log a rate-limited WARNING that rate limiting is failing OPEN.

    Behavior is intentionally fail-OPEN (requests are allowed) so a Redis blip
    never takes the whole API down; we just make that explicit and visible.
    """
    global _last_fail_open_warn
    now = time.monotonic()
    if now - _last_fail_open_warn >= _FAIL_OPEN_WARN_INTERVAL:
        _last_fail_open_warn = now
        logger.warning(
            "Redis unavailable for %s — failing OPEN (requests allowed, not rate limited)",
            context,
        )



# Paths hit on essentially every page load/navigation (session bootstrap
# reads, feature flags, tenant context, best-effort telemetry) — cheap,
# read-mostly, and not a meaningful abuse target on their own. Previously
# these shared ONE bucket with expensive routes (compile, AI optimize),
# keyed only by client_id with no per-endpoint segmentation at all — so a
# user opening a few tabs, or a shared/NAT IP, could exhaust the budget
# during completely normal browsing and get 429'd on these background calls.
# Confirmed in production: a 429 here was being misread by the frontend as
# "not authenticated" and evicting signed-in users mid-session (see
# useRequireAuth.ts for the client-side half of this fix). Giving them their
# own, more generous budget — not full exemption — fixes the false-eviction
# trigger without losing rate limiting on these routes altogether.
_LIGHTWEIGHT_PATHS = {
    "/config/feature-flags",
    "/tenants/current-context",
    "/telemetry/frontend",
}
_LIGHTWEIGHT_CALLS_PER_MINUTE = 300
_LIGHTWEIGHT_CALLS_PER_HOUR = 6000

# Third-party "Connect" buttons on the Settings page (GitHub, Zotero, Mendeley,
# Dropbox) — a single deliberate click that kicks off an OAuth redirect, not
# automated background traffic. These previously shared the SAME default
# per-IP bucket as everything else, including expensive compile/AI calls, so
# a user who had already spent their default per-minute budget on normal
# navigation could get 429'd just clicking "Connect GitHub" (production
# audit). These are low-frequency by nature (nobody clicks Connect more than
# a handful of times), so the budget is intentionally much tighter than the
# lightweight background-poll bucket above — generous enough for legitimate
# retries (e.g. fixing a misconfigured OAuth app) without exposing an
# expensive-relative-to-compile redirect endpoint to abuse.
_INTEGRATION_PATHS = {
    "/github/connect",
    "/zotero/connect",
    "/mendeley/connect",
    "/dropbox/connect",
}
_INTEGRATION_CALLS_PER_MINUTE = 10
_INTEGRATION_CALLS_PER_HOUR = 100


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using Redis for storage."""

    def __init__(self, app, calls_per_minute: int = 60, calls_per_hour: int = 1000):
        super().__init__(app)
        self.calls_per_minute = calls_per_minute
        self.calls_per_hour = calls_per_hour

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for preflight requests and static/meta endpoints
        if request.method == "OPTIONS":
            return await call_next(request)
        if (
            request.url.path in [
                "/health", "/livez", "/readyz", "/metrics",
                "/jobs/health", "/docs", "/openapi.json",
            ]
            or request.url.path.startswith("/static")
        ):
            return await call_next(request)

        # Get client identifier (IP address or user ID)
        client_id = self.get_client_id(request)

        # Check rate limits
        try:
            await self.check_rate_limit(client_id, request.url.path)
        except HTTPException as e:
            retry_after = e.headers.get("Retry-After", "60") if e.headers else "60"
            return Response(
                content=f'{{"error": "{e.detail}", "retry_after": {retry_after}}}',
                status_code=e.status_code,
                headers={"Content-Type": "application/json", "Retry-After": retry_after}
            )

        response = await call_next(request)
        return response

    def get_client_id(self, request: Request) -> str:
        """Get a spoofing-resistant client identifier for rate limiting."""
        return _spoof_resistant_client_id(request)

    # Lua script: atomically INCR+EXPIRE BOTH the minute and hour windows in a
    # single round-trip (was two separate EVALs = two ~100ms Upstash RTTs).
    # Returns {minute_count, hour_count}.
    _LUA_INCR_EXPIRE_2 = """
local m = redis.call('INCR', KEYS[1])
if m == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local h = redis.call('INCR', KEYS[2])
if h == 1 then redis.call('EXPIRE', KEYS[2], ARGV[2]) end
return {m, h}
"""

    async def check_rate_limit(self, client_id: str, endpoint: str):
        """Check if client has exceeded rate limits using a single atomic script."""
        if not redis_manager.redis_client:
            # If Redis is not available, allow the request (fail-open).
            _warn_fail_open("rate limiting")
            return

        # Lightweight paths get their own bucket (namespaced ":lw:") so they
        # never share budget with compile/AI calls — see _LIGHTWEIGHT_PATHS.
        if endpoint in _LIGHTWEIGHT_PATHS:
            per_minute, per_hour = _LIGHTWEIGHT_CALLS_PER_MINUTE, _LIGHTWEIGHT_CALLS_PER_HOUR
            bucket = f"rate_limit:{client_id}:lw"
        # OAuth "Connect" buttons get their own, distinct bucket (namespaced
        # ":int:") so a busy session's default-bucket usage can never 429 a
        # deliberate, infrequent click — see _INTEGRATION_PATHS.
        elif endpoint in _INTEGRATION_PATHS:
            per_minute, per_hour = _INTEGRATION_CALLS_PER_MINUTE, _INTEGRATION_CALLS_PER_HOUR
            bucket = f"rate_limit:{client_id}:int"
        else:
            per_minute, per_hour = self.calls_per_minute, self.calls_per_hour
            bucket = f"rate_limit:{client_id}"

        current_time = int(time.time())
        minute_key = f"{bucket}:minute:{current_time // 60}"
        hour_key = f"{bucket}:hour:{current_time // 3600}"

        try:
            counts = await redis_manager.redis_client.eval(
                self._LUA_INCR_EXPIRE_2, 2, minute_key, hour_key, 60, 3600
            )
            minute_count, hour_count = int(counts[0]), int(counts[1])
            if minute_count > per_minute:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded: {per_minute} calls per minute",
                    headers={"Retry-After": "60"},
                )
            if hour_count > per_hour:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded: {per_hour} calls per hour",
                    headers={"Retry-After": "3600"},
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            # If there's an error with rate limiting, allow the request
            pass


class APIKeyRateLimitMiddleware(BaseHTTPMiddleware):
    """Enhanced rate limiting for API key operations."""

    def __init__(self, app):
        super().__init__(app)
        self.byok_limits = {
            "validate": {"calls": 10, "window": 300},  # 10 validations per 5 minutes
            "add_key": {"calls": 5, "window": 3600},   # 5 key additions per hour
            "delete_key": {"calls": 10, "window": 3600} # 10 deletions per hour
        }

    async def dispatch(self, request: Request, call_next):
        # Skip preflight requests — OPTIONS must reach CORSMiddleware uninhibited
        if request.method == "OPTIONS":
            return await call_next(request)
        # Only apply to BYOK endpoints
        if not request.url.path.startswith("/byok/"):
            return await call_next(request)

        # Determine operation type
        operation = self.get_operation_type(request)
        if not operation:
            return await call_next(request)

        client_id = self.get_client_id(request)

        try:
            await self.check_operation_limit(client_id, operation)
        except HTTPException as e:
            return Response(
                content=f'{{"error": "{e.detail}", "retry_after": {self.byok_limits[operation]["window"]}}}',
                status_code=e.status_code,
                headers={"Content-Type": "application/json", "Retry-After": str(self.byok_limits[operation]["window"])}
            )

        response = await call_next(request)
        return response

    def get_operation_type(self, request: Request) -> Optional[str]:
        """Determine the type of BYOK operation."""
        path = request.url.path
        method = request.method

        if path == "/byok/validate" and method == "POST":
            return "validate"
        elif path == "/byok/api-keys" and method == "POST":
            return "add_key"
        elif path.startswith("/byok/api-keys/") and method == "DELETE":
            return "delete_key"

        return None

    def get_client_id(self, request: Request) -> str:
        """Get a spoofing-resistant client identifier (shared with the main limiter)."""
        return _spoof_resistant_client_id(request)

    async def check_operation_limit(self, client_id: str, operation: str):
        """Check operation-specific rate limits."""
        if not redis_manager.redis_client:
            # Fail-open when Redis is down (availability over strict limiting).
            _warn_fail_open("operation rate limiting")
            return

        limit_config = self.byok_limits[operation]
        current_time = int(time.time())
        window_start = current_time - limit_config["window"]

        key = f"op_limit:{client_id}:{operation}"

        try:
            # Use sorted set to track requests in time window
            pipe = redis_manager.redis_client.pipeline()

            # Remove old entries
            pipe.zremrangebyscore(key, 0, window_start)

            # Count current requests in window
            pipe.zcard(key)

            # Add current request with unique member (prevents score collision in same second)
            import uuid as _uuid
            pipe.zadd(key, {f"{current_time}:{_uuid.uuid4().hex[:8]}": current_time})

            # Set expiration
            pipe.expire(key, limit_config["window"])

            results = await pipe.execute()
            current_count = results[1]  # Result of zcard

            if current_count >= limit_config["calls"]:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Operation rate limit exceeded: {limit_config['calls']} {operation} operations per {limit_config['window']} seconds"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Operation rate limiting error: {e}")
            # If there's an error, allow the request
            pass
