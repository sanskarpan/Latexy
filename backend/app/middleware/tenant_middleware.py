"""
Tenant resolution middleware — Feature 85C.

Resolves the current white-label tenant from:
  1. X-Tenant-Slug header (explicit; takes priority)
  2. Subdomain: slug.latexy.io  →  slug lookup
  3. Custom domain: matches tenants.custom_domain

Attaches tenant (or None) to request.state.tenant so route handlers
can access branding and enforce tenant isolation.

Results are Redis-cached for 5 minutes to avoid per-request DB queries.
"""

from __future__ import annotations

import json
import logging
import time

from fastapi import Request
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from ..core.redis import cache_manager
from ..database.connection import get_async_db_session
from ..database.models import Tenant

logger = logging.getLogger(__name__)

# Hostname suffix used to detect slug-based subdomains
LATEXY_DOMAIN_SUFFIX = ".latexy.io"
CACHE_TTL = 300  # 5 minutes (Redis)

# First-party hosts that can never be white-label tenant domains. Resolving these
# would cost a ~100ms Upstash round-trip on EVERY request for nothing, so we
# short-circuit to "no tenant" without touching Redis/DB.
_FIRST_PARTY_EXACT = frozenset({
    "latexy.xyz", "www.latexy.xyz",
    "localhost", "127.0.0.1", "",
})
_FIRST_PARTY_SUFFIX = (".vercel.app", ".modal.run")


def _is_first_party(host: str) -> bool:
    if host in _FIRST_PARTY_EXACT:
        return True
    return any(host.endswith(s) for s in _FIRST_PARTY_SUFFIX)


# Process-local cache in front of Redis so repeated tenant lookups within a warm
# container don't each pay the Upstash round-trip. Shorter TTL than Redis so a
# tenant change still propagates within a minute.
_INPROC_TTL = 60.0
_INPROC_CACHE: dict[str, tuple[object, float]] = {}
_CACHE_MISS = object()


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Resolves the current tenant from request headers / Host and attaches
    it to request.state.tenant (a dict with tenant fields, or None).
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        request.state.tenant = None

        slug: str | None = None
        host: str = request.headers.get("host", "").split(":")[0].lower()

        # ── 1. Explicit X-Tenant-Slug header ─────────────────────────────────
        slug_header = request.headers.get("x-tenant-slug", "").strip().lower()
        if slug_header:
            slug = slug_header

        # ── 2. Subdomain pattern: <slug>.latexy.io ───────────────────────────
        elif host.endswith(LATEXY_DOMAIN_SUFFIX):
            sub = host[: -len(LATEXY_DOMAIN_SUFFIX)]
            if sub and "." not in sub:  # single-level subdomain only
                slug = sub

        try:
            if slug:
                request.state.tenant = await self._resolve_by_slug(slug)
            elif host and not _is_first_party(host):
                # First-party hosts (latexy.xyz, *.vercel.app, *.modal.run, …)
                # are never tenants — skip the Redis/DB lookup entirely.
                request.state.tenant = await self._resolve_by_domain(host)
        except Exception as exc:
            logger.debug("Tenant resolution error", extra={"error_type": type(exc).__name__})

        return await call_next(request)

    # ── Lookup helpers ────────────────────────────────────────────────────────

    async def _resolve_by_slug(self, slug: str) -> dict | None:
        cache_key = f"tenant:slug:{slug}"
        cached = await _cache_get(cache_key)
        if cached is not _CACHE_MISS:
            return cached if isinstance(cached, dict) else None

        async with get_async_db_session() as db:
            result = await db.execute(
                select(Tenant).where(Tenant.slug == slug, Tenant.active.is_(True))
            )
            tenant = result.scalar_one_or_none()

        data = _serialize(tenant)
        await _cache_set(cache_key, data)
        return data

    async def _resolve_by_domain(self, domain: str) -> dict | None:
        return await resolve_verified_tenant_domain(domain)


async def resolve_verified_tenant_domain(domain: str) -> dict | None:
    """Resolve an active DNS-verified custom domain with negative caching."""
    cache_key = f"tenant:domain:{domain}"
    cached = await _cache_get(cache_key)
    if cached is not _CACHE_MISS:
        return cached if isinstance(cached, dict) else None

    async with get_async_db_session() as db:
        result = await db.execute(
            select(Tenant).where(
                Tenant.custom_domain == domain,
                Tenant.domain_verified_at.is_not(None),
                Tenant.active.is_(True),
            )
        )
        tenant = result.scalar_one_or_none()

    data = _serialize(tenant)
    await _cache_set(cache_key, data)
    return data


async def resolve_tenant_origin_hostname(hostname: str) -> dict | None:
    """Resolve either an official tenant subdomain or a verified custom host."""
    if hostname.endswith(LATEXY_DOMAIN_SUFFIX):
        slug = hostname[: -len(LATEXY_DOMAIN_SUFFIX)]
        if slug and "." not in slug:
            cache_key = f"tenant:slug:{slug}"
            cached = await _cache_get(cache_key)
            if cached is not _CACHE_MISS:
                return cached if isinstance(cached, dict) else None
            async with get_async_db_session() as db:
                result = await db.execute(
                    select(Tenant).where(
                        Tenant.slug == slug, Tenant.active.is_(True)
                    )
                )
                tenant = result.scalar_one_or_none()
            data = _serialize(tenant)
            await _cache_set(cache_key, data)
            return data
    return await resolve_verified_tenant_domain(hostname)


class VerifiedTenantCORSMiddleware(BaseHTTPMiddleware):
    """Allow browser API calls only from active, verified tenant origins."""

    _ALLOWED_METHODS = "GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS"
    _ALLOWED_HEADERS = frozenset(
        {
            "authorization",
            "content-type",
            "traceparent",
            "tracestate",
            "x-device-fingerprint",
            "x-request-id",
            "x-tenant-slug",
        }
    )

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        if not origin:
            return await call_next(request)
        try:
            from urllib.parse import urlsplit

            parsed = urlsplit(origin)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.path
                or parsed.port is not None
            ):
                return await call_next(request)
            tenant = await resolve_tenant_origin_hostname(parsed.hostname.lower())
        except Exception:
            tenant = None
        if tenant is None:
            return await call_next(request)

        if request.method == "OPTIONS" and request.headers.get("access-control-request-method"):
            requested = {
                item.strip().lower()
                for item in request.headers.get("access-control-request-headers", "").split(",")
                if item.strip()
            }
            if not requested.issubset(self._ALLOWED_HEADERS):
                return Response("Disallowed CORS headers", status_code=400)
            response = Response(status_code=200)
        else:
            response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = self._ALLOWED_METHODS
        response.headers["Access-Control-Allow-Headers"] = ", ".join(
            sorted(self._ALLOWED_HEADERS)
        )
        response.headers["Access-Control-Max-Age"] = "600"
        response.headers.add_vary_header("Origin")
        return response


# ── Cache helpers ─────────────────────────────────────────────────────────────

async def _cache_get(key: str) -> dict | None | object:
    """Return a cached value or the distinct ``_CACHE_MISS`` sentinel.

    Checks the process-local cache first (no network) before Redis.
    """
    hit = _INPROC_CACHE.get(key)
    if hit is not None:
        value, expiry = hit
        if expiry > time.monotonic():
            return value if isinstance(value, dict) else None
        _INPROC_CACHE.pop(key, None)
    try:
        raw = await cache_manager.get(key)
        if raw is None:
            return _CACHE_MISS
        # Negative cache: store empty string to mean "no tenant found"
        if raw == "":
            _INPROC_CACHE[key] = (None, time.monotonic() + _INPROC_TTL)
            return None
        data = raw if isinstance(raw, dict) else (json.loads(raw) if isinstance(raw, str) else None)
        _INPROC_CACHE[key] = (data, time.monotonic() + _INPROC_TTL)
        return data
    except Exception:
        return _CACHE_MISS


async def _cache_set(key: str, data: dict | None) -> None:
    _INPROC_CACHE[key] = (data, time.monotonic() + _INPROC_TTL)
    try:
        value = data if data is not None else ""
        await cache_manager.set(key, value, ttl=CACHE_TTL)
    except Exception:
        pass


async def invalidate_tenant_cache(
    *, slug: str, current_domain: str | None = None, previous_domain: str | None = None
) -> None:
    """Invalidate lookup keys affected by a tenant mutation."""
    keys = {f"tenant:slug:{slug}"}
    for domain in (current_domain, previous_domain):
        if domain:
            keys.add(f"tenant:domain:{domain}")
    for key in keys:
        _INPROC_CACHE.pop(key, None)
        try:
            await cache_manager.delete(key)
        except Exception:
            pass


def _serialize(tenant: Tenant | None) -> dict | None:
    if tenant is None:
        return None
    return {
        "id": tenant.id,
        "slug": tenant.slug,
        "name": tenant.name,
        "logo_url": tenant.logo_url,
        "primary_color": tenant.primary_color,
        "custom_domain": tenant.custom_domain,
        "plan_id": tenant.plan_id,
        "max_members": tenant.max_members,
    }


def get_current_tenant(request: Request) -> dict | None:
    """Dependency / helper to retrieve the resolved tenant from request state."""
    return getattr(request.state, "tenant", None)
