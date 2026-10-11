"""Actual Redis Lua atomic capacity reservations; no provider/cloud calls."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import redis

from app.services.resume_engine.provider import _LIMIT


@pytest.fixture
def capacity():
    client = redis.Redis.from_url(os.getenv("TEST_REDIS_URL", "redis://localhost:6380/15"), decode_responses=True)
    prefix = "latexy:test:provider-fairness:" + uuid4().hex
    def claim(tenant, intent, tokens=10, *, rpm=6, tpm=100, tenant_rpm=2, tenant_tpm=40):
        return client.eval(_LIMIT, 3, prefix, prefix + ":tenant:" + tenant, prefix + ":intent:" + intent,
                           tokens, rpm, tpm, tenant_rpm, tenant_tpm)
    yield client, prefix, claim
    keys = list(client.scan_iter(match=prefix + "*"))
    if keys:
        client.delete(*keys)
    client.close()


def counts(client, prefix, tenant):
    bucket = int(client.time()[0]) // 60
    return client.hgetall(prefix + ":" + str(bucket)), client.hgetall(prefix + ":tenant:" + tenant + ":" + str(bucket))


def test_tenant_request_cap_leaves_global_headroom_for_another(capacity):
    client, prefix, claim = capacity
    assert claim("a", "a1") == claim("a", "a2") == 1
    assert claim("a", "a3") == -3
    assert claim("b", "b1") == 1
    global_count, owner_count = counts(client, prefix, "a")
    assert global_count == {"requests": "3", "tokens": "30"}
    assert owner_count == {"requests": "2", "tokens": "20"}
    assert not client.exists(prefix + ":intent:a3")


def test_global_request_exhaustion_is_distinct_and_atomic(capacity):
    client, prefix, claim = capacity
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda tenant: claim(tenant, tenant, rpm=1), ["a", "b"]))
    assert sorted(results) == [-1, 1]
    global_count, _ = counts(client, prefix, "a")
    assert global_count == {"requests": "1", "tokens": "10"}
    rejected = "a" if results[0] == -1 else "b"
    assert counts(client, prefix, rejected)[1] == {}
    assert not client.exists(prefix + ":intent:" + rejected)


def test_tenant_and_global_token_limits_have_distinct_results(capacity):
    client, prefix, claim = capacity
    assert claim("a", "a1", 30) == 1
    assert claim("a", "a2", 11) == -4
    assert claim("b", "b1", 30) == 1
    assert claim("c", "c1", 41, tenant_tpm=100) == -2  # global 60 + 41 > 100
    assert counts(client, prefix, "a")[0] == {"requests": "2", "tokens": "60"}
    assert not client.exists(prefix + ":intent:a2") and not client.exists(prefix + ":intent:c1")


def test_same_paid_stage_rate_reservation_is_idempotent_and_expires(capacity):
    client, prefix, claim = capacity
    assert claim("a", "same") == 1
    assert claim("a", "same") == 1
    assert counts(client, prefix, "a")[0] == {"requests": "1", "tokens": "10"}
    keys = list(client.scan_iter(match=prefix + "*"))
    assert len(keys) == 3 and all(0 < client.ttl(key) <= 75 for key in keys)
    # Expiration is bounded, not a durable replay ledger. Production begin()
    # restores the DB stage before this script; an expired rate marker cannot
    # authorize repayment of an already-completed or ambiguous stage.
    for key in keys:
        client.expire(key, 0)
    assert claim("a", "new") == 1
    assert counts(client, prefix, "a")[0] == {"requests": "1", "tokens": "10"}


def test_credential_model_namespaces_do_not_share_capacity(capacity):
    client, prefix, claim = capacity
    assert claim("a", "first", rpm=1) == 1
    other = prefix + ":different-credential-model"
    assert client.eval(_LIMIT, 3, other, other + ":tenant:a", other + ":intent:first", 10, 1, 100, 1, 40) == 1
