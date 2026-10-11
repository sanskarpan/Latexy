"""Bounded duplicate-render coordination, independent of job authority."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

_RELEASE = "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0"


@dataclass
class RenderLease:
    redis: Any
    key: str
    token: str

    def close(self) -> None:
        try:
            self.redis.eval(_RELEASE, 1, self.key, self.token)
        except Exception:
            # Expiry bounds leaked leases; a stale closer cannot release a
            # replacement because release always compares the random token.
            pass


def await_render_slot(redis: Any, cache_key: str, job_id: str, timeout: float) -> RenderLease | None:
    """Return leader lease, or None when an immutable exact artifact is ready.

    This coordination never grants job ownership and every waiter must bind
    its own admitted capability before receiving a preview or terminal result.
    """
    from ...workers.job_lifecycle import write_owned_artifacts
    from .passes import RenderPassError

    key = cache_key + ":inflight"
    token = uuid.uuid4().hex
    deadline = time.monotonic() + min(30.0, max(0.1, timeout))
    ttl = max(2, min(360, int(timeout) + 30))
    while True:
        if redis.set(key, token, nx=True, ex=ttl):
            return RenderLease(redis, key, token)
        raw = redis.get(cache_key)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if isinstance(raw, str) and raw.startswith("{"):
            return None
        if not write_owned_artifacts(redis, job_id, {}, 60):
            raise RenderPassError("Render waiter lost job ownership")
        if time.monotonic() >= deadline:
            raise RenderPassError("Identical render is still in progress")
        time.sleep(0.1)
