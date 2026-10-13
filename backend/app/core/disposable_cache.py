"""Bounded failover for two disposable caches, never for Redis authority.

The API deliberately exposes only GET and TTL-bound SET on allowlisted,
content-addressed keys. No counters, locks, GETDEL, deletion, streams or raw
commands can be routed here. Each process keeps its own sticky cache affinity;
this is safe only because misses can be recomputed and no coherence-dependent
state is admitted. See docs/architecture/redis-failover.md.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import httpx
import redis.asyncio as aioredis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import AuthenticationError, AuthorizationError, ResponseError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .config import settings
from .disposable_cache_config import DisposableCacheEndpoint
from .logging import get_logger

logger = get_logger(__name__)
_ALLOWED_KEY = re.compile(r"(?:latexy:embcache:[a-zA-Z0-9._-]+|esco:search):[a-f0-9]{64}\Z")
_PREFIX = "disposable:v1:"
_MAX_TTL = 30 * 24 * 3600
_MAX_VALUE_BYTES = 512 * 1024
# A Redis JSON string can escape each cached byte once more, plus its wrapper.
_MAX_REST_RESPONSE_BYTES = 2 * _MAX_VALUE_BYTES + 1024


class CacheRejected(Exception):
    """A known quota rejection, safe to try on another disposable backend."""


class CacheUnavailable(Exception):
    """No eligible disposable cache backend; callers can recompute a miss."""


def _quota_rejection(exc: Exception) -> bool:
    # Only an actual Redis response (not an arbitrary exception message) can
    # establish that the command was rejected rather than ambiguously applied.
    return isinstance(exc, CacheRejected) or (
        isinstance(exc, ResponseError)
        and str(exc).lower().strip().removeprefix("err ").rstrip(".") == "max requests limit exceeded"
    )


def _transport_error(exc: Exception) -> bool:
    return not isinstance(exc, (AuthenticationError, AuthorizationError)) and isinstance(
        exc, (RedisConnectionError, RedisTimeoutError, httpx.TransportError, TimeoutError)
    )


class RedisCacheBackend:
    def __init__(self, url: str, *, password: str | None = None):
        self.client = aioredis.Redis.from_url(
            url, password=password, decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            socket_connect_timeout=settings.DISPOSABLE_CACHE_TIMEOUT_SECONDS,
            socket_timeout=settings.DISPOSABLE_CACHE_TIMEOUT_SECONDS,
            retry=Retry(NoBackoff(), 0), retry_on_timeout=False, retry_on_error=[],
        )

    async def get(self, key: str):
        return await self.client.get(key)

    async def set(self, key: str, value: str, ttl: int):
        return await self.client.set(key, value, ex=ttl)

    async def aclose(self):
        await self.client.aclose()


class RestCacheBackend:
    def __init__(self, endpoint: DisposableCacheEndpoint):
        self.url = endpoint.url.get_secret_value().rstrip("/")
        self.client = httpx.AsyncClient(
            timeout=settings.DISPOSABLE_CACHE_TIMEOUT_SECONDS,
            follow_redirects=False,
            headers={"Authorization": f"Bearer {endpoint.token.get_secret_value()}", "Accept-Encoding": "identity"},
        )

    async def _command(self, command: list):
        # POST body keeps cache keys/content out of URLs. Never follow redirects
        # with a credential, and never use HTTP retry middleware for writes.
        async with self.client.stream("POST", self.url, json=command) as response:
            # Bound memory before JSON decoding, not after response.json() has
            # materialized an arbitrarily large provider/proxy response. Decline
            # compressed bodies so decompression cannot bypass the byte bound.
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise CacheUnavailable("Unsupported cache response encoding")
            body = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                if len(body) + len(chunk) > _MAX_REST_RESPONSE_BYTES:
                    raise CacheUnavailable("Cache response too large")
                body.extend(chunk)
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                raise CacheUnavailable("Invalid cache response") from None
            if isinstance(payload, dict) and isinstance(payload.get("error"), str):
                if response.status_code in {200, 400, 429} and payload["error"].lower().strip().removeprefix("err ").rstrip(".") == "max requests limit exceeded":
                    raise CacheRejected("Cache request quota exhausted")
                raise CacheUnavailable("Cache command rejected")
            if not response.is_success or not isinstance(payload, dict) or "result" not in payload:
                raise CacheUnavailable("Invalid cache response")
            return payload["result"]

    async def get(self, key: str):
        result = await self._command(["GET", key])
        if result is not None and not isinstance(result, str):
            raise CacheUnavailable("Invalid cache value")
        return result

    async def set(self, key: str, value: str, ttl: int):
        result = await self._command(["SET", key, value, "EX", ttl])
        if result != "OK":
            raise CacheUnavailable("Cache write unconfirmed")
        return True

    async def aclose(self):
        await self.client.aclose()


@dataclass
class _Slot:
    blocked_until: float = 0
    failed: bool = False
    probing: object | None = None


@dataclass
class _RoutingState:
    slots: list[_Slot]
    active: int = 0


class DisposableCacheChain:
    def __init__(self, backends: list, *, clock=time.monotonic, state: _RoutingState | None = None):
        if not 1 <= len(backends) <= 4:
            raise ValueError("Disposable cache requires one to four backends")
        self.backends = backends
        self.state = state or _RoutingState([_Slot() for _ in backends])
        if len(self.state.slots) != len(backends):
            raise ValueError("Disposable cache routing configuration changed without restart")
        self.slots = self.state.slots
        self.clock = clock

    @property
    def active(self):
        return self.state.active

    @active.setter
    def active(self, value):
        self.state.active = value

    def _claim(self, attempted: set[int]) -> int | None:
        for offset in range(len(self.slots)):
            index = (self.active + offset) % len(self.slots)
            slot = self.slots[index]
            if index in attempted or slot.blocked_until > self.clock() or slot.probing:
                continue
            # A recovering endpoint admits one real command, not extra PINGs.
            slot.probing = object() if slot.failed else None
            if self.active != index:
                logger.warning("Disposable cache switched to backend slot %d", index)
            self.active = index
            return index
        return None

    async def execute(self, operation: str, *args):
        if operation not in {"get", "set"}:
            raise ValueError("Unsupported disposable cache operation")
        attempted: set[int] = set()
        expiry = self.clock() + args[2] if operation == "set" else None
        while (index := self._claim(attempted)) is not None:
            attempted.add(index)
            slot = self.slots[index]
            probe = slot.probing
            try:
                attempt_args = args
                if expiry is not None:
                    remaining = min(args[2], math.ceil(expiry - self.clock()))
                    if remaining <= 0:
                        return False
                    attempt_args = (*args[:2], remaining)
                async with asyncio.timeout(settings.DISPOSABLE_CACHE_TIMEOUT_SECONDS):
                    result = await getattr(self.backends[index], operation)(*attempt_args)
                # A late success must not undo a concurrent failure/cooldown or
                # move affinity back to an endpoint another request abandoned.
                if slot.blocked_until <= self.clock():
                    slot.failed = False
                return result
            except Exception as exc:
                quota = _quota_rejection(exc)
                slot.failed = True
                cooldown = (settings.DISPOSABLE_CACHE_QUOTA_COOLDOWN_SECONDS if quota
                            else settings.DISPOSABLE_CACHE_ERROR_COOLDOWN_SECONDS)
                slot.blocked_until = max(slot.blocked_until, self.clock() + cooldown)
                kind = "quota" if quota else "transport" if _transport_error(exc) else "other"
                logger.warning("Disposable cache backend slot %d unavailable (%s)", index, kind)
                # A SET timeout, disconnect, malformed reply, 5xx or cancellation
                # cannot prove whether the write happened. Never replay it.
                if operation == "set" and not quota:
                    raise CacheUnavailable("Cache write outcome unknown") from None
                # Config/auth/programming failures are not evidence of exhaustion.
                if not quota and not _transport_error(exc):
                    raise CacheUnavailable("Cache backend unavailable") from None
            finally:
                if slot.probing is probe:
                    slot.probing = None
        raise CacheUnavailable("All disposable cache backends unavailable")

    async def aclose(self):
        for backend in self.backends:
            try:
                async with asyncio.timeout(settings.DISPOSABLE_CACHE_TIMEOUT_SECONDS):
                    await backend.aclose()
            except Exception:
                logger.warning("Could not close disposable cache backend")


class DisposableCache:
    _scope: ContextVar[DisposableCache | None] = ContextVar("disposable_cache_scope", default=None)

    def __init__(self):
        self._chain: DisposableCacheChain | None = None
        self._routing_owner = self
        self._routing_state: _RoutingState | None = None

    @asynccontextmanager
    async def isolated(self):
        """Own worker clients within the lifetime of its asyncio.run() loop."""
        scoped = DisposableCache()
        scoped._routing_owner = self._routing_owner
        token = self._scope.set(scoped)
        try:
            yield scoped
        finally:
            self._scope.reset(token)
            await scoped.aclose()

    async def _get_chain(self) -> DisposableCacheChain:
        scoped = self._scope.get()
        if scoped is not None and scoped is not self:
            return await scoped._get_chain()
        if self._chain is None:
            backends = []
            try:
                backends.append(RedisCacheBackend(settings.REDIS_CACHE_URL, password=settings.REDIS_PASSWORD or None))
                for endpoint in settings.DISPOSABLE_CACHE_BACKUPS:
                    backends.append(RestCacheBackend(endpoint) if endpoint.transport == "rest"
                                    else RedisCacheBackend(endpoint.url.get_secret_value()))
                owner = self._routing_owner
                if owner._routing_state is None:
                    owner._routing_state = _RoutingState([_Slot() for _ in backends])
                self._chain = DisposableCacheChain(backends, state=owner._routing_state)
            except Exception:
                # Factories can fail before a chain owns the previously-created
                # pools. Release every partial allocation without raw errors.
                for backend in backends:
                    try:
                        async with asyncio.timeout(settings.DISPOSABLE_CACHE_TIMEOUT_SECONDS):
                            await backend.aclose()
                    except Exception:
                        logger.warning("Could not close partially initialized disposable cache")
                raise CacheUnavailable("Could not initialize disposable cache") from None
        return self._chain

    @staticmethod
    def _validate_key(key: str):
        if not _ALLOWED_KEY.fullmatch(key):
            raise ValueError("Key is not an approved content-addressed disposable cache")

    async def get(self, key: str):
        self._validate_key(key)
        if not settings.DISPOSABLE_CACHE_BACKUPS:
            from .redis import cache_manager
            return await cache_manager.get(key)
        try:
            raw = await (await self._get_chain()).execute("get", _PREFIX + key)
            if not isinstance(raw, str) or len(raw.encode()) > _MAX_VALUE_BYTES:
                return None
            payload = json.loads(raw)
            expires = payload.get("expires_at") if isinstance(payload, dict) else None
            if not isinstance(expires, (int, float)) or not math.isfinite(expires) or expires <= time.time():
                return None
            return payload.get("value")
        except (CacheUnavailable, ValueError, TypeError):
            return None

    async def set(self, key: str, value: Any, ttl: int = 3600):
        self._validate_key(key)
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= _MAX_TTL:
            raise ValueError("Disposable cache TTL must be 1 second to 30 days")
        if not settings.DISPOSABLE_CACHE_BACKUPS:
            from .redis import cache_manager
            return await cache_manager.set(key, value, ttl=ttl)
        # An absolute expiry also protects against stale values returning after
        # switching endpoints. No mutable keys or cross-backend invalidations.
        raw = json.dumps({"value": value, "expires_at": time.time() + ttl}, allow_nan=False)
        if len(raw.encode()) > _MAX_VALUE_BYTES:
            return False
        try:
            return bool(await (await self._get_chain()).execute("set", _PREFIX + key, raw, ttl))
        except CacheUnavailable:
            return False

    async def aclose(self):
        chain, self._chain = self._chain, None
        if chain is not None:
            await chain.aclose()


disposable_cache = DisposableCache()
