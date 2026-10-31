"""No live provider calls: failure injection for explicitly disposable caching."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from unittest.mock import call as mock_call

import httpx
import pytest
from pydantic import ValidationError
from redis.exceptions import AuthenticationError, AuthorizationError, ConnectionError, ResponseError, TimeoutError

from app.core.config import Settings, settings
from app.core.disposable_cache import (
    CacheRejected,
    CacheUnavailable,
    DisposableCache,
    DisposableCacheChain,
    RedisCacheBackend,
    RestCacheBackend,
)
from app.core.disposable_cache_config import DisposableCacheEndpoint

KEY = "latexy:embcache:text-embedding-3-small:" + "a" * 64
BACKUP = DisposableCacheEndpoint(transport="redis", url="redis://backup.invalid:6379/0")


def backend(*, get=None, set=True):
    return Mock(get=AsyncMock(return_value=get), set=AsyncMock(return_value=set), aclose=AsyncMock())


def quota():
    return ResponseError("ERR max requests limit exceeded")


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "DISPOSABLE_CACHE_BACKUPS", [BACKUP])
    monkeypatch.setattr(settings, "DISPOSABLE_CACHE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(settings, "DISPOSABLE_CACHE_QUOTA_COOLDOWN_SECONDS", 3600)
    monkeypatch.setattr(settings, "DISPOSABLE_CACHE_ERROR_COOLDOWN_SECONDS", 30)


async def test_primary_success_and_miss_do_not_probe_backup(enabled):
    primary, backup = backend(), backend(get="stale")
    chain = DisposableCacheChain([primary, backup])
    assert await chain.execute("get", "key") is None
    await chain.execute("set", "key", "value", 10)
    backup.get.assert_not_awaited()
    backup.set.assert_not_awaited()


async def test_quota_rejections_walk_multiple_backups_and_remain_sticky(enabled):
    primary, secondary, tertiary = backend(), backend(), backend(get="cached")
    primary.get.side_effect = quota()
    secondary.get.side_effect = CacheRejected()
    now = [0]
    chain = DisposableCacheChain([primary, secondary, tertiary], clock=lambda: now[0])
    assert await chain.execute("get", "key") == "cached"
    assert chain.active == 2
    now[0] = 7200  # Healthy backup never oscillates back after cooldown.
    assert await chain.execute("get", "key") == "cached"
    assert primary.get.await_count == secondary.get.await_count == 1
    await chain.execute("set", "key", "same", 10)
    tertiary.set.assert_awaited_once_with("key", "same", 10)


async def test_only_known_quota_rejection_replays_set_with_remaining_ttl(enabled):
    primary, backup = backend(), backend()
    now = [100]

    async def reject(*args):
        now[0] += 3
        raise quota()

    primary.set.side_effect = reject
    chain = DisposableCacheChain([primary, backup], clock=lambda: now[0])
    assert await chain.execute("set", "key", "same-value", 10) is True
    backup.set.assert_awaited_once_with("key", "same-value", 7)


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionError(), RuntimeError("ERR max requests limit exceeded")])
async def test_uncertain_primary_write_is_never_replayed(enabled, error):
    primary, backup = backend(), backend(get="next-read")
    primary.set.side_effect = error
    chain = DisposableCacheChain([primary, backup])
    with pytest.raises(CacheUnavailable, match="outcome unknown"):
        await chain.execute("set", "key", "value", 10)
    primary.set.assert_awaited_once()
    backup.set.assert_not_awaited()
    assert await chain.execute("get", "key") == "next-read"


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionError(), httpx.ConnectError("unavailable")])
async def test_read_transport_failure_can_use_backup(enabled, error):
    primary, backup = backend(), backend(get="cached")
    primary.get.side_effect = error
    chain = DisposableCacheChain([primary, backup])
    assert await chain.execute("get", "key") == "cached"


async def test_backup_quota_then_transport_failure_opens_bounded_circuits(enabled):
    primary, backup, third = backend(), backend(), backend()
    primary.get.side_effect = quota()
    backup.get.side_effect = quota()
    third.get.side_effect = TimeoutError()
    chain = DisposableCacheChain([primary, backup, third])
    for _ in range(5):
        with pytest.raises(CacheUnavailable):
            await chain.execute("get", "key")
    assert [b.get.await_count for b in (primary, backup, third)] == [1, 1, 1]


@pytest.mark.parametrize("error", [AuthenticationError("WRONGPASS"), AuthorizationError("NOPERM"), ResponseError("WRONGTYPE")])
async def test_authentication_or_wrongtype_is_not_quota_failover(enabled, error):
    primary, backup = backend(), backend()
    primary.get.side_effect = error
    chain = DisposableCacheChain([primary, backup])
    with pytest.raises(CacheUnavailable):
        await chain.execute("get", "key")
    backup.get.assert_not_awaited()


async def test_recovery_half_open_has_only_one_probe(enabled):
    primary = backend(get="recovered")
    chain = DisposableCacheChain([primary], clock=lambda: 100)
    chain.slots[0].failed = True
    chain.slots[0].blocked_until = 99
    started, release = asyncio.Event(), asyncio.Event()

    async def probe(*args):
        started.set()
        await release.wait()
        return "recovered"

    primary.get.side_effect = probe
    first = asyncio.create_task(chain.execute("get", "key"))
    await started.wait()
    with pytest.raises(CacheUnavailable):
        await chain.execute("get", "key")
    release.set()
    assert await first == "recovered"
    assert chain.slots[0].failed is False
    assert chain.slots[0].probing is None
    assert primary.get.await_count == 1


async def test_late_success_does_not_undo_concurrent_failure_or_affinity(enabled):
    primary, backup = backend(), backend(get="backup")
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def primary_get(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
            return "old-success"
        raise quota()

    primary.get.side_effect = primary_get
    chain = DisposableCacheChain([primary, backup])
    slow = asyncio.create_task(chain.execute("get", "key"))
    await started.wait()
    assert await chain.execute("get", "key") == "backup"
    release.set()
    assert await slow == "old-success"
    assert chain.active == 1
    assert chain.slots[0].failed is True
    assert await chain.execute("get", "key") == "backup"
    assert primary.get.await_count == 2


async def test_outer_timeout_bounds_hung_backend_and_does_not_replay_set(enabled, monkeypatch):
    monkeypatch.setattr(settings, "DISPOSABLE_CACHE_TIMEOUT_SECONDS", 0.01)
    primary, backup = backend(), backend()

    async def hang(*args):
        await asyncio.sleep(10)

    primary.set.side_effect = hang
    chain = DisposableCacheChain([primary, backup])
    async with asyncio.timeout(0.1):
        with pytest.raises(CacheUnavailable):
            await chain.execute("set", "key", "value", 10)
    backup.set.assert_not_awaited()


async def test_task_cancellation_does_not_retry_any_write(enabled):
    primary, backup = backend(), backend()
    primary.set.side_effect = asyncio.CancelledError()
    chain = DisposableCacheChain([primary, backup])
    with pytest.raises(asyncio.CancelledError):
        await chain.execute("set", "key", "value", 10)
    backup.set.assert_not_awaited()


@pytest.mark.parametrize("key", ["quota:user", "gh:oauth:state", "tenant:user", "job:lock", "esco:search:x", KEY + "\n"])
async def test_authoritative_and_malformed_keys_are_rejected_before_io(enabled, key):
    cache = DisposableCache()
    with pytest.raises(ValueError):
        await cache.get(key)
    with pytest.raises(ValueError):
        await cache.set(key, "value")
    assert cache._chain is None


@pytest.mark.parametrize("ttl", [0, -1, 2592001, 1.5, True])
async def test_unbounded_or_invalid_ttl_is_rejected(enabled, ttl):
    cache = DisposableCache()
    with pytest.raises(ValueError):
        await cache.set(KEY, "value", ttl=ttl)
    assert cache._chain is None


async def test_cache_exhaustion_is_best_effort_miss_and_does_not_change_authority(enabled, monkeypatch):
    from app.core import redis as authoritative
    from app.services.entitlement_service import EntitlementService

    primary = backend()
    primary.get.side_effect = quota()
    primary.set.side_effect = quota()
    cache = DisposableCache()
    cache._chain = DisposableCacheChain([primary])
    authoritative_client = backend()
    monkeypatch.setattr(authoritative, "redis_cache_client", authoritative_client)
    assert await cache.get(KEY) is None
    assert await cache.set(KEY, [0.1], ttl=10) is False
    assert await authoritative.get_redis_cache_client() is authoritative_client
    authoritative_client.getdel = AsyncMock(return_value='{"one_time": true}')
    assert await authoritative.cache_manager.pop("gh:oauth:nonce") == {"one_time": True}
    authoritative_client.getdel.assert_awaited_once_with("cache:gh:oauth:nonce")
    # Monetary authority still imports the pinned getter, not disposable cache.
    assert "get_redis_cache_client" in __import__("inspect").getsource(EntitlementService.consume_quota)


@pytest.mark.parametrize("raw", ["invalid", "[]", '{}', '{"expires_at": 1, "value": "old"}', '{"expires_at": NaN}'])
async def test_malformed_and_expired_values_are_misses_without_promotion(enabled, raw):
    endpoint = backend(get=raw)
    cache = DisposableCache()
    cache._chain = DisposableCacheChain([endpoint])
    assert await cache.get(KEY) is None
    endpoint.set.assert_not_awaited()


async def test_serialization_namespace_absolute_expiry_and_no_ttl_refresh(enabled):
    endpoint = backend()
    cache = DisposableCache()
    cache._chain = DisposableCacheChain([endpoint])
    with patch("app.core.disposable_cache.time.time", return_value=1000):
        assert await cache.set(KEY, [0.1, 0.2], ttl=10) is True
        name, payload, ttl = endpoint.set.call_args.args
        assert name == "disposable:v1:" + KEY
        assert json.loads(payload) == {"expires_at": 1010, "value": [0.1, 0.2]}
        endpoint.get.return_value = payload
        assert await cache.get(KEY) == [0.1, 0.2]
    with patch("app.core.disposable_cache.time.time", return_value=1011):
        assert await cache.get(KEY) is None
    assert endpoint.set.await_count == 1


async def test_default_empty_backup_configuration_preserves_legacy_cache(monkeypatch):
    from app.core.redis import cache_manager
    monkeypatch.setattr(settings, "DISPOSABLE_CACHE_BACKUPS", [])
    monkeypatch.setattr(cache_manager, "get", AsyncMock(return_value=[0.3]))
    monkeypatch.setattr(cache_manager, "set", AsyncMock())
    cache = DisposableCache()
    assert await cache.get(KEY) == [0.3]
    await cache.set(KEY, [0.4], ttl=20)
    cache_manager.set.assert_awaited_once_with(KEY, [0.4], ttl=20)
    assert cache._chain is None


async def test_tcp_transport_disables_library_retries_and_owns_pool(enabled):
    endpoint = RedisCacheBackend("redis://cache.invalid:6379/0")
    kwargs = endpoint.client.connection_pool.connection_kwargs
    assert kwargs["retry"]._retries == 0
    assert kwargs["retry_on_timeout"] is False
    assert kwargs["retry_on_error"] == []
    assert endpoint.client.auto_close_connection_pool is True
    await endpoint.aclose()


async def test_rest_command_uses_json_body_header_auth_and_no_redirects(enabled):
    endpoint = RestCacheBackend(DisposableCacheEndpoint(
        transport="rest", url="https://cache.invalid", token="dummy-token",
    ))
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url == "https://cache.invalid"
        assert request.headers["Authorization"] == "Bearer dummy-token"
        command = json.loads(request.content)
        return httpx.Response(200, json={"result": "OK" if command[0] == "SET" else "cached"})

    await endpoint.client.aclose()
    endpoint.client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                       headers={"Authorization": "Bearer dummy-token"}, follow_redirects=False)
    assert await endpoint.set("key", "value", 10) is True
    assert await endpoint.get("key") == "cached"
    assert json.loads(calls[0].content) == ["SET", "key", "value", "EX", 10]
    await endpoint.aclose()


@pytest.mark.parametrize("status", [200, 400, 429])
async def test_rest_recognizes_documented_quota_error_in_body(enabled, status):
    endpoint = RestCacheBackend(DisposableCacheEndpoint(transport="rest", url="https://cache.invalid", token="dummy"))
    await endpoint.client.aclose()
    endpoint.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json={"error": "ERR max requests limit exceeded"})
    ))
    with pytest.raises(CacheRejected):
        await endpoint.get("key")
    await endpoint.aclose()


@pytest.mark.parametrize("response", [httpx.Response(500, json={"error": "ERR max requests limit exceeded"}), httpx.Response(500), httpx.Response(200, json={}),
                                     httpx.Response(307, headers={"Location": "https://wrong.invalid"}),
                                     httpx.Response(401, json={"error": "WRONGPASS token=secret"})])
async def test_rest_unconfirmed_write_is_never_replayed_or_logged(enabled, response, caplog):
    caplog.set_level("INFO", logger="httpx")
    endpoint = RestCacheBackend(DisposableCacheEndpoint(transport="rest", url="https://cache.invalid", token="dummy"))
    await endpoint.client.aclose()
    endpoint.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response))
    backup = backend()
    chain = DisposableCacheChain([endpoint, backup])
    with pytest.raises(CacheUnavailable):
        await chain.execute("set", "private-key", "private-value", 10)
    backup.set.assert_not_awaited()
    assert "private" not in caplog.text and "secret" not in caplog.text
    # httpx may log the credential-free origin at INFO. Our application
    # diagnostics must identify only the slot, never raw endpoint/error data.
    app_logs = "\n".join(record.getMessage() for record in caplog.records
                         if record.name == "app.core.disposable_cache")
    assert "cache.invalid" not in app_logs
    await endpoint.aclose()


async def test_close_cleans_all_backends_even_when_one_fails(enabled):
    first, second = backend(), backend()
    first.aclose.side_effect = RuntimeError()
    cache = DisposableCache()
    cache._chain = DisposableCacheChain([first, second])
    await cache.aclose()
    assert cache._chain is None
    second.aclose.assert_awaited_once()


@pytest.mark.parametrize("kwargs", [
    {"transport": "redis", "url": "https://cache.invalid"},
    {"transport": "rest", "url": "redis://cache.invalid", "token": "secret"},
    {"transport": "rest", "url": "https://cache.invalid"},
    {"transport": "rest", "url": "https://cache.invalid/get/foo", "token": "secret"},
    {"transport": "rest", "url": "https://cache.invalid?_token=secret", "token": "secret"},
    {"transport": "rest", "url": "https://user:secret@cache.invalid", "token": "secret"},
    {"transport": "redis", "url": "redis://cache.invalid/not-a-db"},
    {"transport": "redis", "url": "redis://cache.invalid", "token": "secret"},
])
def test_transport_configuration_is_explicit_and_errors_secret_safe(kwargs):
    with pytest.raises(ValidationError) as error:
        DisposableCacheEndpoint(**kwargs)
    assert "secret" not in str(error.value)


def test_settings_reject_same_database_different_transports_and_hide_credentials():
    with pytest.raises(ValidationError, match="distinct database hosts") as error:
        Settings(_env_file=None, REDIS_CACHE_URL="rediss://user:secret@cache.invalid:6379/0",
                 DISPOSABLE_CACHE_BACKUPS=[{"transport": "rest", "url": "https://cache.invalid", "token": "secret"}])
    assert "secret" not in str(error.value)


def test_only_reviewed_services_import_disposable_cache():
    root = Path(__file__).parents[1] / "app"
    consumers = []
    for path in root.rglob("*.py"):
        if path.parent == root / "core":
            continue
        if "core.disposable_cache import" in path.read_text(encoding="utf-8"):
            consumers.append(path.name)
    assert sorted(consumers) == ["ats_worker.py", "embedding_service.py", "esco_service.py"]


async def test_partial_initialization_closes_prior_backends(enabled):
    primary = backend()
    cache = DisposableCache()
    with patch("app.core.disposable_cache.RedisCacheBackend", side_effect=[primary, RuntimeError("private")]):
        assert await cache.get(KEY) is None
    primary.aclose.assert_awaited_once()
    assert cache._chain is None


def test_worker_scopes_close_in_each_event_loop_without_touching_api_cache(monkeypatch):
    monkeypatch.setattr(settings, "DISPOSABLE_CACHE_BACKUPS", [BACKUP])
    cache = DisposableCache()
    api_backend = backend()
    cache._chain = DisposableCacheChain([api_backend])
    worker_backends = []

    async def one_task():
        worker = backend()
        worker_backends.append(worker)
        async with cache.isolated() as scoped:
            scoped._chain = DisposableCacheChain([worker])
            await cache.set(KEY, [0.1], ttl=20)
            assert scoped._chain is not cache._chain
        assert scoped._chain is None
        worker.aclose.assert_awaited_once()

    asyncio.run(one_task())
    asyncio.run(one_task())
    assert len(worker_backends) == 2
    api_backend.set.assert_not_awaited()
    api_backend.aclose.assert_not_awaited()


async def test_isolated_scope_closes_on_cancellation_and_restores_context(enabled):
    cache = DisposableCache()
    worker = backend()
    with pytest.raises(asyncio.CancelledError):
        async with cache.isolated() as scoped:
            scoped._chain = DisposableCacheChain([worker])
            raise asyncio.CancelledError()
    assert cache._scope.get() is None
    worker.aclose.assert_awaited_once()


async def test_hung_disposable_close_is_bounded_and_closes_other_clients(enabled, monkeypatch):
    monkeypatch.setattr(settings, "DISPOSABLE_CACHE_TIMEOUT_SECONDS", 0.01)
    first, second = backend(), backend()

    async def hang():
        await asyncio.sleep(10)

    first.aclose.side_effect = hang
    async with asyncio.timeout(0.1):
        await DisposableCacheChain([first, second]).aclose()
    second.aclose.assert_awaited_once()


def test_worker_scopes_preserve_routing_affinity_across_closed_loops(monkeypatch):
    monkeypatch.setattr(settings, "DISPOSABLE_CACHE_BACKUPS", [BACKUP])
    cache = DisposableCache()
    primaries, backups = [], []

    async def one_task():
        primary, backup = backend(), backend(get=None)
        primary.get.side_effect = quota()
        primaries.append(primary)
        backups.append(backup)
        with patch("app.core.disposable_cache.RedisCacheBackend", side_effect=[primary, backup]):
            async with cache.isolated():
                assert await cache.get(KEY) is None
        primary.aclose.assert_awaited_once()
        backup.aclose.assert_awaited_once()

    asyncio.run(one_task())
    asyncio.run(one_task())
    assert primaries[0].get.await_count == 1
    primaries[1].get.assert_not_awaited()
    assert all(item.get.await_count == 1 for item in backups)


async def test_nested_worker_scope_restores_outer_and_isolates_api_context(enabled):
    cache = DisposableCache()
    api = backend(get=None)
    cache._chain = DisposableCacheChain([api])
    release, started = asyncio.Event(), asyncio.Event()

    async def worker():
        async with cache.isolated() as outer:
            outer._chain = DisposableCacheChain([backend()])
            async with cache.isolated() as inner:
                assert cache._scope.get() is inner
            assert cache._scope.get() is outer
            started.set()
            await release.wait()

    task = asyncio.create_task(worker())
    await started.wait()
    assert cache._scope.get() is None
    assert await cache.get(KEY) is None
    api.get.assert_awaited_once()
    release.set()
    await task
    api.aclose.assert_not_awaited()


async def test_embedding_worker_uses_and_closes_task_scope(enabled):
    from app.core.disposable_cache import disposable_cache
    from app.services.embedding_service import embedding_service
    from app.workers.ats_worker import _async_embed_resume

    primary, backup = backend(), backend()
    session = AsyncMock()
    factory = Mock(return_value=session)

    async def embed(*args):
        assert disposable_cache._scope.get() is not None
        await disposable_cache.set(KEY, [0.1], ttl=10)
        raise RuntimeError("embedding failed")

    with patch("app.core.disposable_cache.RedisCacheBackend", side_effect=[primary, backup]), patch.object(
        embedding_service, "embed_resume", side_effect=embed
    ):
        with pytest.raises(RuntimeError, match="embedding failed"):
            await _async_embed_resume("dummy-resume", "dummy-latex", session_factory=factory)
    assert disposable_cache._scope.get() is None
    primary.aclose.assert_awaited_once()
    backup.aclose.assert_awaited_once()


async def test_hung_disposable_cleanup_does_not_prevent_authoritative_cleanup(enabled, monkeypatch):
    from app.core import redis as authoritative
    from app.core.disposable_cache import disposable_cache

    monkeypatch.setattr(settings, "DISPOSABLE_CACHE_TIMEOUT_SECONDS", 0.01)
    hanging = backend()

    async def hang():
        await asyncio.sleep(10)

    hanging.aclose.side_effect = hang
    monkeypatch.setattr(disposable_cache, "_chain", DisposableCacheChain([hanging]))
    primary = backend()
    monkeypatch.setattr(authoritative, "redis_client", primary)
    monkeypatch.setattr(authoritative, "redis_cache_client", None)
    async with asyncio.timeout(0.1):
        await authoritative.RedisManager().close_redis()
    primary.aclose.assert_awaited_once()
    assert authoritative.redis_client is None


def test_backup_count_is_bounded_and_secret_values_are_redacted():
    config = {"transport": "rest", "url": "https://cache.invalid", "token": "secret"}
    assert "secret" not in repr(DisposableCacheEndpoint(**config))
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DISPOSABLE_CACHE_BACKUPS=[config] * 4)


class _BodyStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.read_count = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk

    async def aclose(self):
        self.closed = True


async def test_oversized_rest_body_stops_before_reading_entire_response(enabled, monkeypatch):
    monkeypatch.setattr("app.core.disposable_cache._MAX_REST_RESPONSE_BYTES", 64 * 1024)
    body = _BodyStream([b"x" * (64 * 1024)] * 20)
    endpoint = RestCacheBackend(DisposableCacheEndpoint(transport="rest", url="https://cache.invalid", token="dummy"))
    assert endpoint.client.headers["Accept-Encoding"] == "identity"
    await endpoint.client.aclose()
    endpoint.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=body)
    ))
    with pytest.raises(CacheUnavailable, match="too large"):
        await endpoint.get("key")
    assert body.read_count == 2
    assert body.closed is True
    await endpoint.aclose()


async def test_compressed_rest_body_is_rejected_before_decompression(enabled):
    body = _BodyStream([b"do-not-decompress"])
    endpoint = RestCacheBackend(DisposableCacheEndpoint(transport="rest", url="https://cache.invalid", token="dummy"))
    await endpoint.client.aclose()
    endpoint.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=body, headers={"Content-Encoding": "gzip"})
    ))
    with pytest.raises(CacheUnavailable, match="encoding"):
        await endpoint.get("key")
    assert body.read_count == 0
    assert body.closed is True
    await endpoint.aclose()


@pytest.mark.parametrize("cached", [{"bad": "shape"}, "bad", [], [0.1], [True] * 1536, [float("nan")] * 1536,
                                   [float("inf")] * 1536, ["0.1"] * 1536])
async def test_invalid_cached_embedding_is_recomputed_without_consuming_bad_shape(cached):
    from app.services.embedding_service import EmbeddingService

    cache = Mock(get=AsyncMock(return_value=cached), set=AsyncMock())
    vector = [0.1] * 1536
    provider = Mock(embeddings=Mock(create=AsyncMock(return_value=Mock(data=[Mock(embedding=vector)]))))
    service = EmbeddingService()
    service._client = provider
    with patch("app.services.embedding_service.disposable_cache", cache):
        assert await service.embed_text("dummy text") == vector
    provider.embeddings.create.assert_awaited_once()


async def test_valid_cached_embedding_avoids_provider_call():
    from app.services.embedding_service import EmbeddingService

    vector = [0.1] * 1536
    cache = Mock(get=AsyncMock(return_value=vector))
    service = EmbeddingService()
    with patch("app.services.embedding_service.disposable_cache", cache), patch.object(service, "_get_client") as provider:
        assert await service.embed_text("dummy text") == vector
    provider.assert_not_called()


async def test_chain_reports_success_under_disposable_role_only(enabled):
    primary = backend()
    chain = DisposableCacheChain([primary])
    with patch("app.core.disposable_cache.record_redis_command") as record:
        assert await chain.execute("get", "key") is None
        await chain.execute("set", "key", "value", 10)
    assert record.call_args_list == [mock_call("disposable"), mock_call("disposable")]


async def test_chain_reports_quota_rejection_under_disposable_role(enabled):
    from app.core.observability import classify_redis_error

    primary = backend()
    primary.get.side_effect = quota()
    chain = DisposableCacheChain([primary])
    with patch("app.core.disposable_cache.record_redis_command") as record:
        with pytest.raises(CacheUnavailable):
            await chain.execute("get", "key")
    assert len(record.call_args_list) == 1
    role, reported = record.call_args_list[0].args
    assert role == "disposable"
    assert classify_redis_error(reported) == "request_quota_exhausted"


async def test_chain_reports_transport_failure_under_disposable_role(enabled):
    from app.core.observability import classify_redis_error

    primary, backup = backend(), backend(get="cached")
    failure = TimeoutError("operation timed out")
    primary.get.side_effect = failure
    chain = DisposableCacheChain([primary, backup])
    with patch("app.core.disposable_cache.record_redis_command") as record:
        assert await chain.execute("get", "key") == "cached"
    roles = [call.args[0] for call in record.call_args_list]
    assert roles and all(role == "disposable" for role in roles)
    assert classify_redis_error(record.call_args_list[0].args[1]) == "timeout"
    # The healthy backup read is recorded too, still under the spare role.
    assert record.call_args_list[-1].args == ("disposable",)
