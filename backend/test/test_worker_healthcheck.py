from types import SimpleNamespace

from app.core import worker_healthcheck


def test_healthcheck_requires_its_own_worker_reply(monkeypatch):
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://test:6379/15")
    monkeypatch.setattr(worker_healthcheck.socket, "gethostname", lambda: "this-worker")
    calls = []

    def ping(**kwargs):
        calls.append(kwargs)
        return [{"celery@another-worker": {"ok": "pong"}}]

    config = SimpleNamespace()
    monkeypatch.setattr(worker_healthcheck, "Celery", lambda *a, **k: SimpleNamespace(conf=config, control=SimpleNamespace(ping=ping)))
    assert not worker_healthcheck.worker_is_ready()
    assert config.broker_transport_options == {"sep": ":"}
    assert calls == [{"destination": ["celery@this-worker"], "timeout": 8}]


def test_healthcheck_accepts_this_worker(monkeypatch):
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://test:6379/15")
    monkeypatch.setattr(worker_healthcheck.socket, "gethostname", lambda: "this-worker")
    monkeypatch.setattr(worker_healthcheck, "Celery", lambda *a, **k: SimpleNamespace(
        conf=SimpleNamespace(),
        control=SimpleNamespace(ping=lambda **kw: [{"celery@this-worker": {"ok": "pong"}}]),
    ))
    assert worker_healthcheck.worker_is_ready()


def test_healthcheck_fails_without_broker(monkeypatch):
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert not worker_healthcheck.worker_is_ready()
