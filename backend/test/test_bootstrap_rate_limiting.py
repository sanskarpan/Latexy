"""Session/capability bootstrap reads have an isolated, still-bounded budget."""

from collections import defaultdict

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.middleware import rate_limiting


class CounterRedis:
    """Model the existing atomic counter script with time frozen per test."""

    def __init__(self):
        self.counts = defaultdict(int)

    async def eval(self, script, key_count, minute_key, hour_key, minute_ttl, hour_ttl):
        assert script == rate_limiting.RateLimitMiddleware._LUA_INCR_EXPIRE_2
        assert (key_count, minute_ttl, hour_ttl) == (2, 60, 3600)
        self.counts[minute_key] += 1
        self.counts[hour_key] += 1
        return [self.counts[minute_key], self.counts[hour_key]]


@pytest.fixture
def counter_redis(monkeypatch):
    redis = CounterRedis()
    monkeypatch.setattr(rate_limiting.redis_manager, "redis_client", redis)
    monkeypatch.setattr(rate_limiting.time, "time", lambda: 7200)
    return redis


@pytest.mark.parametrize("window,limit", [("minute", 60), ("hour", 1000)])
async def test_default_exhaustion_cannot_starve_bootstrap(counter_redis, window, limit):
    limiter = rate_limiting.RateLimitMiddleware(FastAPI())
    index = 120 if window == "minute" else 2
    counter_redis.counts[f"rate_limit:user:test:{window}:{index}"] = limit

    with pytest.raises(HTTPException) as exc:
        await limiter.check_rate_limit("user:test", "/compile")
    assert exc.value.status_code == 429
    assert exc.value.detail == f"Rate limit exceeded: {limit} calls per {window}"

    for path in ("/me", "/config/entitlements"):
        await limiter.check_rate_limit("user:test", path)
    assert counter_redis.counts["rate_limit:user:test:lw:minute:120"] == 2
    assert counter_redis.counts["rate_limit:user:test:lw:hour:2"] == 2

    # Bootstrap reads do not reset or enlarge the exhausted expensive budget.
    with pytest.raises(HTTPException) as exc:
        await limiter.check_rate_limit("user:test", "/compile")
    assert exc.value.status_code == 429


@pytest.mark.parametrize("path", ["/me", "/config/entitlements"])
@pytest.mark.parametrize("window,limit,retry_after", [("minute", 300, "60"), ("hour", 6000, "3600")])
async def test_bootstrap_keeps_existing_lightweight_caps(counter_redis, path, window, limit, retry_after):
    limiter = rate_limiting.RateLimitMiddleware(FastAPI())
    index = 120 if window == "minute" else 2
    counter_redis.counts[f"rate_limit:user:test:lw:{window}:{index}"] = limit - 1

    await limiter.check_rate_limit("user:test", path)
    with pytest.raises(HTTPException) as exc:
        await limiter.check_rate_limit("user:test", path)
    assert exc.value.status_code == 429
    assert exc.value.detail == f"Rate limit exceeded: {limit} calls per {window}"
    assert exc.value.headers == {"Retry-After": retry_after}

    # The shared lightweight budget cannot be bypassed by rotating these paths.
    for other_path in ("/me", "/config/entitlements", "/config/feature-flags"):
        with pytest.raises(HTTPException) as exc:
            await limiter.check_rate_limit("user:test", other_path)
        assert exc.value.status_code == 429

    await limiter.check_rate_limit("user:other", path)
    await limiter.check_rate_limit("user:test", "/compile")


@pytest.mark.parametrize("path", ["/me/preferences", "/me/other", "/config/entitlements/other"])
async def test_bootstrap_allowlist_does_not_include_related_routes(counter_redis, path):
    limiter = rate_limiting.RateLimitMiddleware(FastAPI())
    counter_redis.counts["rate_limit:user:test:minute:120"] = 60
    with pytest.raises(HTTPException) as exc:
        await limiter.check_rate_limit("user:test", path)
    assert exc.value.status_code == 429
    assert exc.value.detail == "Rate limit exceeded: 60 calls per minute"
    assert "rate_limit:user:test:lw:minute:120" not in counter_redis.counts


async def test_middleware_routes_bootstrap_to_bounded_lightweight_budget(counter_redis):
    app = FastAPI()
    app.add_middleware(rate_limiting.RateLimitMiddleware)

    @app.get("/compile")
    @app.get("/me")
    @app.get("/config/entitlements")
    async def endpoint():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(60):
            assert (await client.get("/compile")).status_code == 200
        assert (await client.get("/compile")).status_code == 429
        assert (await client.get("/me")).status_code == 200
        assert (await client.get("/config/entitlements")).status_code == 200
        assert (await client.get("/compile")).status_code == 429

        for _ in range(298):
            assert (await client.get("/me")).status_code == 200
        response = await client.get("/config/entitlements")
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "60"
        assert response.json() == {"error": "Rate limit exceeded: 300 calls per minute", "retry_after": 60}
