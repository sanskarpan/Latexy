"""Warm Redis reuse is scoped to process and credentials, with bounded checks."""
from unittest.mock import MagicMock

import pytest

from app.workers import event_publisher as ep


@pytest.fixture(autouse=True)
def isolated_client(monkeypatch):
    monkeypatch.setattr(ep, "_worker_redis", None)
    monkeypatch.setattr(ep, "_worker_redis_identity", None)
    monkeypatch.setattr(ep, "_worker_redis_checked_at", 0.0)


def test_warm_invocations_reuse_pool_without_ping(monkeypatch):
    client = MagicMock()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(ep.redis, "from_url", factory)
    for _ in range(20):
        ep.initialize_worker_redis("redis://localhost:6379/0", "password")
    factory.assert_called_once()
    client.ping.assert_called_once()
    client.close.assert_not_called()


@pytest.mark.parametrize("change", ["pid", "url", "password"])
def test_pool_replaced_on_identity_change(monkeypatch, change):
    original, replacement = MagicMock(), MagicMock()
    factory = MagicMock(side_effect=[original, replacement])
    monkeypatch.setattr(ep.redis, "from_url", factory)
    ep.initialize_worker_redis("redis://localhost:6379/0", "first")
    if change == "pid":
        monkeypatch.setattr(ep.os, "getpid", lambda: -1)
    ep.initialize_worker_redis(
        "redis://localhost:6379/1" if change == "url" else "redis://localhost:6379/0",
        "second" if change == "password" else "first",
    )
    original.close.assert_called_once()
    assert ep.get_worker_redis() is replacement


def test_health_check_replaces_failed_reused_pool(monkeypatch):
    original, replacement = MagicMock(), MagicMock()
    original.ping.side_effect = [True, ConnectionError("disconnected")]
    monkeypatch.setattr(ep.redis, "from_url", MagicMock(side_effect=[original, replacement]))
    clock = iter([100.0, 161.0])
    monkeypatch.setattr(ep.time, "monotonic", lambda: next(clock))
    ep.initialize_worker_redis("redis://localhost:6379/0")
    ep.initialize_worker_redis("redis://localhost:6379/0")
    original.close.assert_called_once()
    assert ep.get_worker_redis() is replacement


def test_rotated_credentials_failure_cannot_retain_old_pool(monkeypatch):
    original, replacement = MagicMock(), MagicMock()
    replacement.ping.side_effect = ConnectionError("unavailable")
    monkeypatch.setattr(ep.redis, "from_url", MagicMock(side_effect=[original, replacement]))
    ep.initialize_worker_redis("redis://localhost:6379/0", "first")
    with pytest.raises(ConnectionError):
        ep.initialize_worker_redis("redis://localhost:6379/0", "second")
    original.close.assert_called_once()
    replacement.close.assert_called_once()
    assert ep._worker_redis is None
    assert ep._worker_redis_identity is None


def test_close_forgets_identity_and_pool(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(ep.redis, "from_url", MagicMock(return_value=client))
    ep.initialize_worker_redis("redis://localhost:6379/0")
    ep.close_worker_redis()
    ep.close_worker_redis()
    client.close.assert_called_once()
    assert ep._worker_redis_identity is None
    assert ep._worker_redis_checked_at == 0.0
