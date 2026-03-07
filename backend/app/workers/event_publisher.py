"""
Event publisher for Celery workers.

Design principles:
- Uses a SYNCHRONOUS redis.Redis client (not aioredis).
  Celery workers are synchronous OS processes. asyncio.run() per call
  is wasteful and error-prone. This module has zero async code.
- Initialized once per worker OS process via the worker_process_init
  Celery signal (see celery_app.py).
- Every event is written to TWO Redis structures:
    1. XADD latexy:stream:{job_id}   — persistent event log, enables replay on reconnect
    2. PUBLISH latexy:events:{job_id} — ephemeral Pub/Sub, live delivery to FastAPI WebSocket layer
- State snapshot is also kept at latexy:job:{job_id}:state for REST polling fallback.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

import redis

logger = logging.getLogger(__name__)

# Module-level worker-local synchronous Redis client.
# None until initialize_worker_redis() is called via Celery signal.
_worker_redis: Optional[redis.Redis] = None

# Default TTL for all job-related keys (24 hours)
_DEFAULT_TTL = 86400


# ------------------------------------------------------------------ #
#  Initialisation (called once per Celery worker OS process)         #
# ------------------------------------------------------------------ #

def initialize_worker_redis(redis_url: str, password: Optional[str] = None) -> None:
    """
    Create a fresh synchronous Redis connection for this worker process.
    Called from the worker_process_init Celery signal in celery_app.py.
    """
    global _worker_redis
    _worker_redis = redis.from_url(
        redis_url,
        password=password or None,
        max_connections=5,
        decode_responses=True,
        retry_on_timeout=True,
        socket_connect_timeout=5,
        socket_timeout=10,
    )
    # Verify connectivity
    _worker_redis.ping()
    logger.info(f"Worker Redis client initialized (PID {os.getpid()})")


def get_worker_redis() -> redis.Redis:
    """Return the worker-local Redis client, raising if not initialized."""
    if _worker_redis is None:
        raise RuntimeError(
            "Worker Redis not initialized. "
            "Ensure initialize_worker_redis() is wired to the "
            "worker_process_init Celery signal."
        )
    return _worker_redis


# ------------------------------------------------------------------ #
#  Core publish_event()                                               #
# ------------------------------------------------------------------ #

def _next_sequence(r: redis.Redis, job_id: str, ttl: int) -> int:
    """Atomic monotonically increasing sequence number per job."""
    key = f"latexy:job:{job_id}:seq"
    seq = r.incr(key)
    r.expire(key, ttl)
    return seq


def publish_event(
    job_id: str,
    event_type: str,
    payload_extra: Dict[str, Any],
    ttl: int = _DEFAULT_TTL,
) -> str:
    """
    Build a typed event dict, persist it to a Redis Stream, and
    publish it to the Redis Pub/Sub channel for live delivery.

    Returns the Redis Stream entry ID (use as last_event_id for replay).

    Workers call this instead of job_status_manager.set_job_status().
    """
    r = get_worker_redis()

    event_id = str(uuid.uuid4())
    seq = _next_sequence(r, job_id, ttl)

    event: Dict[str, Any] = {
        "event_id": event_id,
        "job_id": job_id,
        "timestamp": time.time(),
        "sequence": seq,
        "type": event_type,
        **payload_extra,
    }

    payload_json = json.dumps(event)

    # 1. Persist to Redis Stream (for reconnect replay and history)
    stream_key = f"latexy:stream:{job_id}"
    entry_id = r.xadd(
        stream_key,
        {
            "payload": payload_json,
            "type": event_type,
            "sequence": str(seq),
            "event_id": event_id,
        },
        maxlen=10000,
        approximate=True,
    )
    r.expire(stream_key, ttl)

    # 2. Publish to Pub/Sub channel (live delivery to FastAPI → WebSocket)
    # Include stream_id so the frontend can track the Redis Stream entry position
    # for accurate XREAD replay on reconnect (entry_id format: ms-seq, e.g. 1234567890-0)
    ws_message = json.dumps({"type": "event", "event": event, "stream_id": entry_id})
    r.publish(f"latexy:events:{job_id}", ws_message)

    # 3. Update state snapshot (for REST polling fallback)
    _update_state_snapshot(r, job_id, event_type, payload_extra, ttl)

    logger.debug(f"[{job_id}] Published {event_type} (seq={seq})")
    return entry_id


def _update_state_snapshot(
    r: redis.Redis,
    job_id: str,
    event_type: str,
    payload_extra: Dict[str, Any],
    ttl: int,
) -> None:
    """Keep latexy:job:{job_id}:state in sync for REST polling."""
    from ..models.event_schemas import status_from_event_type

    state = {
        "status": status_from_event_type(event_type),
        "stage": payload_extra.get("stage", ""),
        "percent": payload_extra.get("percent", 0),
        "last_updated": time.time(),
    }
    r.setex(f"latexy:job:{job_id}:state", ttl, json.dumps(state))


# ------------------------------------------------------------------ #
#  Publish final result (fetched by REST GET /jobs/{id}/result)      #
# ------------------------------------------------------------------ #

def publish_job_result(
    job_id: str,
    result: Dict[str, Any],
    ttl: int = _DEFAULT_TTL,
) -> None:
    """
    Store the completed job result payload in Redis.
    Retrieved by the frontend via REST GET /jobs/{job_id}/result
    after the job.completed WebSocket event arrives.
    """
    r = get_worker_redis()
    r.setex(f"latexy:job:{job_id}:result", ttl, json.dumps(result))


# ------------------------------------------------------------------ #
#  Store job metadata (set at submission time by the API)            #
# ------------------------------------------------------------------ #

def store_job_meta(
    job_id: str,
    user_id: Optional[str],
    job_type: str,
    ttl: int = _DEFAULT_TTL,
) -> None:
    """Store job metadata for listing / dashboard purposes."""
    r = get_worker_redis()
    meta = {
        "job_id": job_id,
        "user_id": user_id,
        "job_type": job_type,
        "submitted_at": time.time(),
    }
    r.setex(f"latexy:job:{job_id}:meta", ttl, json.dumps(meta))

    if user_id:
        r.zadd(f"latexy:user:{user_id}:jobs", {job_id: time.time()})
        r.expire(f"latexy:user:{user_id}:jobs", 30 * 86400)


# ------------------------------------------------------------------ #
#  Cancellation check (workers poll this between stages)             #
# ------------------------------------------------------------------ #

def is_cancelled(job_id: str) -> bool:
    """Return True if the user has requested cancellation of this job."""
    r = get_worker_redis()
    return bool(r.exists(f"latexy:job:{job_id}:cancel"))
