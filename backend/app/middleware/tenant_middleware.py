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
from starlette.types import ASGIApp

from ..core.redis import cache_manager
from ..database.connection import SessionLocal as AsyncSessionLocal
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
    "latexy.com", "www.latexy.com", "app.latexy.com",
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
            logger.debug("Tenant resolution error: %s", exc)

        return await call_next(request)

    # ── Lookup helpers ────────────────────────────────────────────────────────

    async def _resolve_by_slug(self, slug: str) -> dict | None:
        cache_key = f"tenant:slug:{slug}"
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Tenant).where(Tenant.slug == slug, Tenant.active.is_(True))
            )
            tenant = result.scalar_one_or_none()

        data = _serialize(tenant)
        await _cache_set(cache_key, data)
        return data

    async def _resolve_by_domain(self, domain: str) -> dict | None:
        cache_key = f"tenant:domain:{domain}"
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Tenant).where(
                    Tenant.custom_domain == domain, Tenant.active.is_(True)
                )
            )
            tenant = result.scalar_one_or_none()

        data = _serialize(tenant)
        await _cache_set(cache_key, data)
        return data


# ── Cache helpers ─────────────────────────────────────────────────────────────

async def _cache_get(key: str) -> dict | None:
    """Return cached dict, or None if miss (including negative 'no tenant' cache).

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
            return None
        # Negative cache: store empty string to mean "no tenant found"
        if raw == "":
            _INPROC_CACHE[key] = (None, time.monotonic() + _INPROC_TTL)
            return None
        data = raw if isinstance(raw, dict) else (json.loads(raw) if isinstance(raw, str) else None)
        _INPROC_CACHE[key] = (data, time.monotonic() + _INPROC_TTL)
        return data
    except Exception:
        return None


async def _cache_set(key: str, data: dict | None) -> None:
    _INPROC_CACHE[key] = (data, time.monotonic() + _INPROC_TTL)
    try:
        value = data if data is not None else ""
        await cache_manager.set(key, value, ttl=CACHE_TTL)
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
