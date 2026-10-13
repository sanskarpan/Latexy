"""Optional two-instance Redis transport check, with no provider credentials.

Run against isolated local Redis processes by setting both explicit URLs below.
Skipped in ordinary unit runs; uses unique keys and never flushes either DB.
"""

import os
import uuid
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import pytest
from redis.exceptions import ResponseError

from app.core.disposable_cache import DisposableCacheChain, RedisCacheBackend


async def test_real_redis_roundtrip_and_quota_failover(monkeypatch):
    from app.core.config import settings

    urls = [os.environ.get(name) for name in (
        "TEST_DISPOSABLE_REDIS_PRIMARY_URL", "TEST_DISPOSABLE_REDIS_BACKUP_URL",
    )]
    if not all(urls):
        pytest.skip("Two explicit isolated local Redis URLs are required")
    for url in urls:
        parsed = urlsplit(url)
        assert parsed.scheme == "redis" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        assert not parsed.username and not parsed.password
    assert urls[0] != urls[1]
    monkeypatch.setattr(settings, "DISPOSABLE_CACHE_TIMEOUT_SECONDS", 1.0)
    primary, backup = [RedisCacheBackend(url) for url in urls]
    chain = DisposableCacheChain([primary, backup])
    key = "test:disposable:" + uuid.uuid4().hex
    try:
        assert await chain.execute("set", key, "primary", 60) is True
        assert await chain.execute("get", key) == "primary"
        primary.set = AsyncMock(side_effect=ResponseError("ERR max requests limit exceeded"))
        assert await chain.execute("set", key, "backup", 60) is True
        assert chain.active == 1
        assert await chain.execute("get", key) == "backup"
        assert await primary.client.get(key) == "primary"
        assert await backup.client.get(key) == "backup"
        assert 0 < await backup.client.ttl(key) <= 60
    finally:
        await primary.client.delete(key)
        await backup.client.delete(key)
        await chain.aclose()
