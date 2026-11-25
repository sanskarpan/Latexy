"""Worker/container heartbeats and the admin operations health projection.

Celery workers and Modal containers write a small, sanitized heartbeat to a
Redis key with a TTL. The admin operations view reads those keys and derives
per-worker states, stale-worker detection and queue ownership. The payload is
operational metadata only: no hostnames, container IDs, environment variables,
credentials or provider error text ever leave this module.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from ..core.logging import get_logger
from ..core.redis import redis_manager

logger = get_logger(__name__)

HEARTBEAT_KEY_PREFIX = "latexy:ops:worker:heartbeat:"
HEARTBEAT_TTL_SECONDS = 900
HEARTBEAT_INTERVAL_SECONDS = 30
DEGRADED_AFTER_SECONDS = 60
STALE_AFTER_SECONDS = 120

# Logical queues the deployment routes work to. Only used to report coverage;
# a Modal-only deployment is not expected to own any Celery queue.
EXPECTED_QUEUES = ("latex", "llm", "combined", "ats", "cleanup", "email")
SUPPORTED_KINDS = ("celery", "modal")

PROVIDER_CONSOLE_LINKS = (
    {"name": "Modal", "console_url": "https://modal.com/apps"},
    {"name": "Upstash Redis", "console_url": "https://console.upstash.com"},
    {"name": "Neon Postgres", "console_url": "https://console.neon.tech"},
    {"name": "Cloudflare R2", "console_url": "https://dash.cloudflare.com"},
)

_WORKER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_QUEUE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

_process_worker_ids: dict[str, str] = {}
_worker_ids_lock = threading.Lock()

_cpu_lock = threading.Lock()
_cpu_sample: tuple[float, float] | None = None

_sync_client = None
_sync_client_lock = threading.Lock()

_heartbeat_thread: threading.Thread | None = None
_heartbeat_stop = threading.Event()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def _read_int(path: str) -> int | None:
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return None


def _cpu_usage_seconds() -> float | None:
    """CPU time for this cgroup/process, in seconds, using stdlib file reads."""
    stats = _read_text("/sys/fs/cgroup/cpu.stat")
    if stats:
        for line in stats.splitlines():
            if line.startswith("usage_usec "):
                try:
                    return int(line.split()[1]) / 1_000_000
                except (IndexError, ValueError):
                    break
    v1_usage = _read_int("/sys/fs/cgroup/cpuacct/cpuacct.usage")
    if v1_usage is not None:
        return v1_usage / 1_000_000_000
    try:
        return time.process_time()
    except Exception:  # noqa: BLE001 - metrics must never break a heartbeat
        return None


def _cpu_snapshot() -> float | None:
    global _cpu_sample
    usage = _cpu_usage_seconds()
    if usage is None:
        return None
    now = time.monotonic()
    with _cpu_lock:
        previous = _cpu_sample
        _cpu_sample = (now, usage)
    if previous is None:
        return 0.0
    elapsed = now - previous[0]
    if elapsed <= 0:
        return 0.0
    percent = max(0.0, (usage - previous[1]) / elapsed * 100.0)
    return round(min(percent, 100.0), 1)


def _system_memory_total_bytes() -> int | None:
    raw = _read_text("/proc/meminfo")
    if not raw:
        return None
    for line in raw.splitlines():
        if line.startswith("MemTotal:"):
            try:
                return int(line.split()[1]) * 1024
            except (IndexError, ValueError):
                return None
    return None


def _process_rss_bytes() -> int | None:
    raw = _read_text("/proc/self/status")
    if not raw:
        return None
    for line in raw.splitlines():
        if line.startswith("VmRSS:"):
            try:
                return int(line.split()[1]) * 1024
            except (IndexError, ValueError):
                return None
    return None


def _memory_snapshot() -> dict[str, float]:
    """Container memory when cgroups are available, process RSS otherwise."""
    for current_path, limit_path in (
        ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory.max"),
        (
            "/sys/fs/cgroup/memory/memory.usage_in_bytes",
            "/sys/fs/cgroup/memory/memory.limit_in_bytes",
        ),
    ):
        current = _read_int(current_path)
        if current is None or current < 0:
            continue
        limit = _read_int(limit_path)
        if limit is None or limit <= 0 or limit >= (1 << 60):
            limit = _system_memory_total_bytes()
        payload: dict[str, float] = {"memory_mb": round(current / (1024 * 1024), 1)}
        if limit:
            payload["memory_percent"] = round(min(max(current / limit * 100.0, 0.0), 100.0), 1)
        return payload

    rss = _process_rss_bytes()
    if rss is None:
        return {}
    total = _system_memory_total_bytes()
    payload = {"memory_mb": round(rss / (1024 * 1024), 1)}
    if total:
        payload["memory_percent"] = round(min(max(rss / total * 100.0, 0.0), 100.0), 1)
    return payload


def _resource_snapshot() -> dict[str, float]:
    """Best-effort CPU/memory snapshot; unavailable metrics are simply absent."""
    snapshot: dict[str, float] = {}
    try:
        cpu = _cpu_snapshot()
        if cpu is not None:
            snapshot["cpu_percent"] = cpu
    except Exception:  # noqa: BLE001 - a metric must never break the writer
        pass
    try:
        snapshot.update(_memory_snapshot())
    except Exception:  # noqa: BLE001
        pass
    return snapshot


def _safe_queues(queues: Iterable[str] | str | None) -> list[str]:
    if queues is None:
        return []
    if isinstance(queues, str):
        queues = [queues]
    cleaned: set[str] = set()
    for queue in queues:
        if not isinstance(queue, str):
            continue
        name = queue.strip().lower()
        if _QUEUE_RE.match(name):
            cleaned.add(name)
    return sorted(cleaned)


def _opaque_worker_id(kind: str, token: str) -> str:
    digest = hashlib.sha256(f"{kind}:{token}".encode()).hexdigest()[:12]
    return f"{kind}-{digest}"


def _process_worker_id(kind: str) -> str:
    with _worker_ids_lock:
        existing = _process_worker_ids.get(kind)
        if existing:
            return existing
        worker_id = _opaque_worker_id(kind, uuid.uuid4().hex)
        _process_worker_ids[kind] = worker_id
        return worker_id


def _safe_worker_id(value: Any) -> str | None:
    if isinstance(value, str) and _WORKER_ID_RE.match(value.strip().lower()):
        return value.strip().lower()
    return None


def _bounded_number(value: Any, *, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(min(max(number, minimum), maximum), 1)


def _get_sync_client(client=None):
    if client is not None:
        return client
    try:
        configured = redis_manager.sync_redis_client
    except Exception:  # noqa: BLE001
        configured = None
    if configured is not None:
        return configured
    try:
        from ..workers.event_publisher import get_worker_redis

        return get_worker_redis()
    except Exception:  # noqa: BLE001 - a worker may not have initialised it yet
        pass

    global _sync_client
    with _sync_client_lock:
        if _sync_client is None:
            import redis as sync_redis

            from ..core.config import settings

            _sync_client = sync_redis.from_url(
                settings.REDIS_URL,
                password=settings.REDIS_PASSWORD or None,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=5,
                retry_on_timeout=True,
            )
        return _sync_client


def close_worker_heartbeat_client() -> None:
    """Release the fallback sync client owned by this process."""
    global _sync_client
    with _sync_client_lock:
        client = _sync_client
        _sync_client = None
    if client is not None:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


def record_worker_heartbeat(
    *,
    kind: str,
    queues: Iterable[str] | str | None = None,
    client=None,
    worker_id: str | None = None,
    recorded_at: datetime | None = None,
    resources: dict[str, Any] | None = None,
) -> bool:
    """Write one sanitized heartbeat. Best effort: never raises to the caller."""
    normalized_kind = kind.strip().lower() if isinstance(kind, str) else ""
    if normalized_kind not in SUPPORTED_KINDS:
        return False

    observed = recorded_at or _utcnow()
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    observed = observed.astimezone(timezone.utc)

    # Caller-supplied tokens may be a hostname or container ID. Hash them so
    # only an opaque, stable label can ever be stored or returned.
    identity = (
        _process_worker_id(normalized_kind) if worker_id is None else _opaque_worker_id(normalized_kind, worker_id)
    )
    payload: dict[str, Any] = {
        "worker_id": identity,
        "kind": normalized_kind,
        "queues": _safe_queues(queues),
        "recorded_at": _iso(observed),
    }
    metrics = resources if isinstance(resources, dict) else _resource_snapshot()

    cpu = _bounded_number(metrics.get("cpu_percent"), minimum=0.0, maximum=100.0)
    memory_percent = _bounded_number(metrics.get("memory_percent"), minimum=0.0, maximum=100.0)
    memory_mb = _bounded_number(metrics.get("memory_mb"), minimum=0.0, maximum=1_000_000.0)
    if cpu is not None:
        payload["cpu_percent"] = cpu
    if memory_percent is not None:
        payload["memory_percent"] = memory_percent
    if memory_mb is not None:
        payload["memory_mb"] = memory_mb

    try:
        writer = _get_sync_client(client)
        writer.set(
            f"{HEARTBEAT_KEY_PREFIX}{identity}",
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            ex=HEARTBEAT_TTL_SECONDS,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - heartbeat is advisory
        logger.warning(
            "worker heartbeat write failed",
            extra={"error_type": type(exc).__name__},
        )
        return False


def classify_worker(payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any] | None:
    """Sanitize and classify one stored heartbeat into a stable public shape."""
    if not isinstance(payload, dict):
        return None
    worker_id = _safe_worker_id(payload.get("worker_id"))
    kind = payload.get("kind")
    kind = kind.strip().lower() if isinstance(kind, str) else ""
    if worker_id is None or kind not in SUPPORTED_KINDS:
        return None

    recorded_raw = payload.get("recorded_at") or payload.get("last_seen")
    if not isinstance(recorded_raw, str):
        return None
    try:
        recorded = datetime.fromisoformat(recorded_raw)
    except (TypeError, ValueError):
        return None
    if recorded.tzinfo is None:
        recorded = recorded.replace(tzinfo=timezone.utc)
    recorded = recorded.astimezone(timezone.utc)

    current = (now or _utcnow()).astimezone(timezone.utc)
    age_seconds = max(0, int((current - recorded).total_seconds()))

    cpu = _bounded_number(payload.get("cpu_percent"), minimum=0.0, maximum=100.0)
    memory_percent = _bounded_number(payload.get("memory_percent"), minimum=0.0, maximum=100.0)
    memory_mb = _bounded_number(payload.get("memory_mb"), minimum=0.0, maximum=1_000_000.0)
    queues = _safe_queues(payload.get("queues"))
    missing_metrics = cpu is None or memory_percent is None
    missing_queue_ownership = kind == "celery" and not queues

    if age_seconds > STALE_AFTER_SECONDS:
        status = "unhealthy"
    elif age_seconds > DEGRADED_AFTER_SECONDS or missing_metrics or missing_queue_ownership:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "worker_id": worker_id,
        "kind": kind,
        "status": status,
        "last_seen": _iso(recorded),
        "age_seconds": age_seconds,
        "cpu_percent": cpu,
        "memory_percent": memory_percent,
        "memory_mb": memory_mb,
        "queues": queues,
        "missing_metrics": missing_metrics,
        "missing_queue_ownership": missing_queue_ownership,
    }


def _worst(statuses: Iterable[str]) -> str:
    values = list(statuses)
    if "unhealthy" in values:
        return "unhealthy"
    if "degraded" in values:
        return "degraded"
    return "healthy"


async def _read_heartbeat_payloads(client) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    async for key in client.scan_iter(match=f"{HEARTBEAT_KEY_PREFIX}*", count=100):
        raw = await client.get(key)
        if raw is None:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            payloads.append(value)
    return payloads


async def _resolve_async_client(client):
    """Use the app client when available, otherwise a short-lived fallback."""
    if client is not None:
        return client, False
    if redis_manager.redis_client is not None:
        return redis_manager.redis_client, False

    created = None
    try:
        import redis.asyncio as aioredis

        from ..core.config import settings

        created = aioredis.from_url(
            settings.REDIS_URL,
            password=settings.REDIS_PASSWORD or None,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        await asyncio.wait_for(created.ping(), timeout=3)
        return created, True
    except Exception:  # noqa: BLE001 - outage is reported as a fixed state
        if created is not None:
            try:
                await created.aclose()
            except Exception:  # noqa: BLE001
                pass
        return None, False


def _empty_payload(observed: datetime, *, detail: str, read_ok: bool) -> dict[str, Any]:
    return {
        "status": "unhealthy",
        "observed_at": _iso(observed),
        "last_check_at": _iso(observed),
        "read_ok": read_ok,
        "detail": detail,
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "ttl_seconds": HEARTBEAT_TTL_SECONDS,
        "active_workers": 0,
        "stale_workers": 0,
        "missing_metrics": 0,
        "components": [],
        "queue_ownership": {},
        "unowned_queues": [],
        "providers": [dict(provider) for provider in PROVIDER_CONSOLE_LINKS],
    }


def unavailable_worker_health(*, now: datetime | None = None) -> dict[str, Any]:
    """Fixed, non-revealing payload for a Redis/heartbeat-read outage."""
    return _empty_payload(
        (now or _utcnow()).astimezone(timezone.utc),
        detail="Worker heartbeats could not be read",
        read_ok=False,
    )


async def get_worker_health(
    *,
    client=None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read and classify worker heartbeats. Never raises."""
    current = (now or _utcnow()).astimezone(timezone.utc)
    resolved = None
    created = False
    try:
        resolved, created = await _resolve_async_client(client)
        if resolved is None:
            return unavailable_worker_health(now=current)
        payloads = await asyncio.wait_for(_read_heartbeat_payloads(resolved), timeout=5)
    except Exception as exc:  # noqa: BLE001 - fixed response, never raw detail
        logger.warning(
            "worker heartbeat read failed",
            extra={"error_type": type(exc).__name__},
        )
        return unavailable_worker_health(now=current)
    finally:
        if created and resolved is not None:
            try:
                await resolved.aclose()
            except Exception:  # noqa: BLE001
                pass

    components: list[dict[str, Any]] = []
    for payload in payloads:
        component = classify_worker(payload, now=current)
        if component is not None:
            components.append(component)

    if not components:
        return _empty_payload(
            current,
            detail="No worker heartbeats have been received",
            read_ok=True,
        )

    components.sort(
        key=lambda item: (
            {"healthy": 0, "degraded": 1, "unhealthy": 2}.get(item["status"], 3),
            item["kind"],
            item["worker_id"],
        )
    )
    status = _worst(component["status"] for component in components)
    stale_workers = sum(1 for component in components if component["age_seconds"] > STALE_AFTER_SECONDS)
    missing_metrics = sum(1 for component in components if component["missing_metrics"])

    queue_ownership: dict[str, int] = {}
    for component in components:
        if component["age_seconds"] > STALE_AFTER_SECONDS:
            continue
        for queue in component["queues"]:
            queue_ownership[queue] = queue_ownership.get(queue, 0) + 1

    unowned_queues: list[str] = []
    if any(component["kind"] == "celery" for component in components):
        unowned_queues = [queue for queue in EXPECTED_QUEUES if queue_ownership.get(queue, 0) == 0]

    parts: list[str] = []
    if stale_workers:
        parts.append(f"{stale_workers} worker heartbeat(s) are stale")
    if missing_metrics:
        parts.append(f"{missing_metrics} worker heartbeat(s) are missing CPU or memory metrics")
    if unowned_queues:
        parts.append(f"{len(unowned_queues)} queue(s) have no active owner")
    if parts and status == "healthy":
        status = "degraded"

    return {
        "status": status,
        "observed_at": _iso(current),
        "last_check_at": _iso(current),
        "read_ok": True,
        "detail": "; ".join(parts) if parts else None,
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "ttl_seconds": HEARTBEAT_TTL_SECONDS,
        "active_workers": sum(1 for component in components if component["age_seconds"] <= STALE_AFTER_SECONDS),
        "stale_workers": stale_workers,
        "missing_metrics": missing_metrics,
        "components": components,
        "queue_ownership": dict(sorted(queue_ownership.items())),
        "unowned_queues": unowned_queues,
        "providers": [dict(provider) for provider in PROVIDER_CONSOLE_LINKS],
    }


def worker_health_section(payload: dict[str, Any]) -> dict[str, Any]:
    """Flatten the worker payload for the existing per-section health view."""
    section: dict[str, Any] = {
        "status": payload.get("status", "unhealthy"),
        "observed_at": payload.get("observed_at"),
        "last_check_at": payload.get("last_check_at"),
        "active_workers": payload.get("active_workers", 0),
        "stale_workers": payload.get("stale_workers", 0),
        "missing_metrics": payload.get("missing_metrics", 0),
        "unowned_queues": len(payload.get("unowned_queues") or []),
    }
    if payload.get("detail"):
        section["detail"] = payload["detail"]
    return section


def _queue_names(source) -> list[str]:
    """Extract queue names from a Celery Consumer/TaskConsumer/QueueRegistry."""
    if source is None:
        return []
    value = source
    if not hasattr(value, "values") and not isinstance(value, (list, tuple, set)):
        value = getattr(source, "queues", None)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if hasattr(value, "values"):
        try:
            value = list(value.values())
        except Exception:  # noqa: BLE001
            return []
    try:
        items = list(value)
    except TypeError:
        return []
    names: list[str] = []
    for item in items:
        name = item if isinstance(item, str) else getattr(item, "name", None)
        if isinstance(name, str):
            names.append(name)
    return _safe_queues(names)


def queues_from_worker(sender) -> list[str]:
    """Resolve the queues this worker consumes, falling back to the known set."""
    candidates = []
    task_consumer = getattr(sender, "task_consumer", None)
    if task_consumer is not None:
        candidates.append(task_consumer)
    candidates.append(sender)
    app = getattr(sender, "app", None)
    amqp = getattr(app, "amqp", None)
    if amqp is not None:
        candidates.append(getattr(amqp, "queues", None))
    for candidate in candidates:
        names = _queue_names(candidate)
        if names:
            return names
    return list(EXPECTED_QUEUES)


def start_celery_worker_heartbeat(sender=None) -> None:
    """Start one daemon heartbeat thread per Celery worker parent process."""
    global _heartbeat_thread, _heartbeat_stop
    if _heartbeat_thread is not None and _heartbeat_thread.is_alive():
        return
    queues = queues_from_worker(sender)
    stop = threading.Event()
    _heartbeat_stop = stop

    def run() -> None:
        while not stop.is_set():
            record_worker_heartbeat(kind="celery", queues=queues)
            if stop.wait(HEARTBEAT_INTERVAL_SECONDS):
                break

    thread = threading.Thread(
        target=run,
        name="latexy-worker-heartbeat",
        daemon=True,
    )
    _heartbeat_thread = thread
    thread.start()


def stop_celery_worker_heartbeat() -> None:
    """Stop the worker heartbeat thread and release its fallback Redis client."""
    global _heartbeat_thread, _heartbeat_stop
    _heartbeat_stop.set()
    thread = _heartbeat_thread
    _heartbeat_thread = None
    if thread is not None and thread.is_alive():
        thread.join(timeout=1)
    close_worker_heartbeat_client()
