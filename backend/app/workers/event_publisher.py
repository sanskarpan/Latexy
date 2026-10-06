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

import asyncio
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


def _persist_arbiter_terminal(
    job_id: str,
    owner: str,
    owner_epoch: int,
    result: Dict[str, Any],
    terminal_status: str,
) -> bool:
    """Durably decide generic terminal outcomes before Redis publication.

    Compilation/resume/cover-letter workers pass their typed persistence
    payloads through their storage-specific caller; this bridge handles the
    generic LLM/result rows and all terminal failures.  A missing row is the
    explicit legacy path.  Existing durable rows fail closed on DB errors.
    """

    async def _persist() -> bool:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from ..core.config import settings
        from ..utils.db_url import normalize_database_url
        from .finalization_arbiter import (
            FinalizationOutcome,
            bounded_result_payload,
            commit_failure,
            commit_success,
            recover_finalization,
            request_cancel,
        )

        engine = create_async_engine(normalize_database_url(settings.DATABASE_URL), poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                row = await recover_finalization(session, job_id=job_id)
                if row is None:
                    return True
                if terminal_status == "completed":
                    if row.state == "completed":
                        # ``ALREADY_COMPLETED`` is an idempotency result, not a
                        # permission to replace the durable winner's payload.
                        # Compare the same bounded representation that was
                        # persisted so a duplicate can replay an identical
                        # result while a losing attempt cannot overwrite Redis.
                        canonical = (
                            bounded_result_payload(job_id, row.result_payload)
                            if isinstance(row.result_payload, dict)
                            else None
                        )
                        candidate = bounded_result_payload(job_id, result)
                        return canonical is not None and candidate == canonical
                    # Typed output persistence (PDF/resume/cover letter) must
                    # call commit_success with its owner-scoped fields. Do not
                    # mark those rows complete with an incomplete payload.
                    if row.compilation_id or row.resume_apply_requested or row.cover_letter_apply_requested:
                        # The typed caller owns the DB commit. A pending row
                        # must never be treated as an accepted Redis result;
                        # otherwise a crash between storage and arbiter commit
                        # could clear/refund the receipt without durable output.
                        return row.state == "completed"
                    outcome = await commit_success(
                        session,
                        job_id=job_id,
                        owner_token=owner,
                        owner_epoch=owner_epoch,
                        result_payload=result,
                    )
                    await session.commit()
                    return outcome in {
                        FinalizationOutcome.ACCEPTED,
                        FinalizationOutcome.ALREADY_COMPLETED,
                    }
                if terminal_status == "cancelled":
                    # A cancellation decision may already have been
                    # linearized by the API/cleanup transaction.  Preserve
                    # that decision, but do not let a worker turn it into a
                    # fresh arbitrary terminal payload.
                    if row.state == "cancelled":
                        return bool(result.get("cancelled") is True or result.get("success") is False)
                    outcome = await request_cancel(session, job_id=job_id, reason_code="worker_cancelled")
                else:
                    if row.state == "failed":
                        # Typed workers persist the immutable failure before
                        # publishing Redis.  Re-publication is valid only for
                        # that exact bounded canonical payload; otherwise a
                        # late retry could overwrite the durable decision.
                        canonical = row.result_payload if isinstance(row.result_payload, dict) else None
                        candidate = bounded_result_payload(job_id, result)
                        return bool(canonical is not None and candidate == canonical)
                    if row.state == "fenced":
                        # FENCED is cleanup-owned.  The recovery worker, not a
                        # stale invocation, must publish its canonical result.
                        return False
                    outcome = await commit_failure(
                        session,
                        job_id=job_id,
                        owner_token=owner,
                        owner_epoch=owner_epoch,
                        failure_code=str(result.get("error_code") or "job_failed"),
                        result_payload=result,
                    )
                await session.commit()
                return outcome in {
                    FinalizationOutcome.ACCEPTED,
                    FinalizationOutcome.CANCELLED,
                    FinalizationOutcome.ALREADY_COMPLETED,
                }
        finally:
            await engine.dispose()

    try:
        return bool(asyncio.run(_persist()))
    except Exception:
        logger.warning(
            "Durable terminal decision failed for %s",
            job_id,
            extra={"error_type": "database"},
        )
        return False

# Keep sequence allocation, stream persistence, Pub/Sub delivery, TTL refreshes,
# and the optional REST snapshot in one Redis round-trip. This matters for
# ``llm.token`` events, which can be emitted thousands of times per generation and
# may be sent to a remote Redis service. The script also makes the stream and live
# event agree on the same atomic sequence and stream id.
_PUBLISH_EVENT_SCRIPT = r"""
local event = cjson.decode(ARGV[2])
local lifecycle_key = string.gsub(KEYS[4], ':state$', ':lifecycle')
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local lifecycle_status = redis.call('HGET', lifecycle_key, 'status')
local lifecycle_owner = redis.call('HGET', lifecycle_key, 'owner')
local cancel_requested = redis.call('HGET', lifecycle_key, 'cancel_requested')
local lifecycle_lease = tonumber(redis.call('HGET', lifecycle_key, 'lease_until') or '0')
local terminal_result = redis.call('HGET', lifecycle_key, 'terminal_result')
local terminal_owner = redis.call('HGET', lifecycle_key, 'terminal_owner')
local lifecycle_epoch = redis.call('HGET', lifecycle_key, 'epoch')
local fenced_at = redis.call('HGET', lifecycle_key, 'fenced_at')
local event_owner = event['_lifecycle_owner']
local event_epoch = event['_lifecycle_epoch']
event['_lifecycle_owner'] = nil
event['_lifecycle_epoch'] = nil
local terminal_event = (ARGV[3] == 'job.completed' or ARGV[3] == 'job.failed' or ARGV[3] == 'job.cancelled')
local completion_aux_event = (ARGV[3] == 'ats.deep_complete' or ARGV[3] == 'job.pdf_extracted' or ARGV[3] == 'llm.complete')
if event_owner and not lifecycle_status then
  return {'', '0', ''}
end
if cancel_requested == '1' and ARGV[3] ~= 'job.cancelled' then
  return {'', '0', ''}
end
-- Every lifecycle-backed worker event must carry the invocation capability.
-- Ownerless publication remains available only for legacy jobs with no
-- lifecycle hash; it must never bypass a live admitted job after a worker
-- thread lost its context or after post-run cleanup cleared it.
if (lifecycle_status == 'running' or lifecycle_status == 'finalizing') and not event_owner then
  return {'', '0', ''}
end
if event_owner and (lifecycle_status == 'running' or lifecycle_status == 'finalizing') and
   (event_owner ~= lifecycle_owner or event_epoch ~= lifecycle_epoch or lifecycle_lease <= now) then
  return {'', '0', ''}
end
event['timestamp'] = now
if lifecycle_status and not terminal_event and not completion_aux_event and ARGV[3] ~= 'job.retrying' and
   (lifecycle_status == 'completed' or lifecycle_status == 'failed' or lifecycle_status == 'cancelled') then
  return {'', '0', ''}
end
if lifecycle_status and completion_aux_event and
   (lifecycle_status == 'completed' or lifecycle_status == 'failed' or lifecycle_status == 'cancelled') then
  -- Auxiliary content is replayable only after a completed terminal result
  -- won the lifecycle fence. Never leak final content for failed/cancelled
  -- jobs, and require the immutable owner epoch as well as the token so an
  -- ABA owner cannot publish a losing attempt's payload.
  if lifecycle_status ~= 'completed' or terminal_result ~= 'completed' or
     event_owner ~= terminal_owner or event_epoch ~= lifecycle_epoch then
    return {'', '0', ''}
  end
end
if lifecycle_status and terminal_event then
  -- A fenced/terminal job cannot be resurrected by a late worker.  The
  -- cleanup owner publishes its matching failure event after fencing.
  if lifecycle_status == 'cancelled' and ARGV[3] ~= 'job.cancelled' then
    return {'', '0', ''}
  end
  if lifecycle_status == 'failed' and ARGV[3] == 'job.completed' then
    return {'', '0', ''}
  end
  if lifecycle_status == 'completed' then
    -- Ordinary terminal events must carry the exact owner capability that
    -- reserved the result.  Recovery is the only ownerless exception: its
    -- durable recovery marker deliberately has no worker epoch/token.
    local terminal_capability_matches =
      (terminal_owner == 'recovery' and not event_owner) or
      (terminal_owner ~= 'recovery' and event_owner == terminal_owner and event_epoch == lifecycle_epoch)
    if ARGV[3] ~= 'job.completed' or terminal_result ~= 'completed' or not terminal_capability_matches then
      return {'', '0', ''}
    end
    redis.call('HDEL', lifecycle_key, 'terminal_result', 'terminal_owner')
  end
  if lifecycle_status == 'failed' and ARGV[3] == 'job.failed' then
    if terminal_result == 'failed' and event_owner == terminal_owner and event_epoch == lifecycle_epoch then
      redis.call('HDEL', lifecycle_key, 'terminal_result', 'terminal_owner')
    elseif not fenced_at or event_owner then
      return {'', '0', ''}
    end
  end
  if lifecycle_status == 'cancelled' and ARGV[3] == 'job.cancelled' then
    if terminal_result == 'cancelled' and event_owner == terminal_owner and event_epoch == lifecycle_epoch then
      redis.call('HDEL', lifecycle_key, 'terminal_result', 'terminal_owner')
    elseif not fenced_at or event_owner then
      return {'', '0', ''}
    end
  end
  if (lifecycle_status == 'running' or lifecycle_status == 'finalizing') and (not event_owner or event_owner ~= lifecycle_owner) then
    return {'', '0', ''}
  end
  if ARGV[3] == 'job.failed' and event['retryable'] ~= true and (lifecycle_status == 'running' or lifecycle_status == 'finalizing') then
    -- Failure events are emitted before the result by several legacy worker
    -- paths. Keep ownership until the result write atomically records the
    -- terminal outcome; otherwise the immediately-following result would be
    -- rejected and the receipt could be cleared without evidence.
    if terminal_result == 'failed' then
      redis.call('HSET', lifecycle_key, 'status', 'failed', 'updated_at', now)
      redis.call('HDEL', lifecycle_key, 'owner', 'lease_until')
      redis.call('EXPIRE', lifecycle_key, 3456000)
    end
  elseif ARGV[3] == 'job.completed' and (lifecycle_status == 'running' or lifecycle_status == 'finalizing') then
    if terminal_result == 'completed' then
      redis.call('HSET', lifecycle_key, 'status', 'completed', 'updated_at', now)
      redis.call('HDEL', lifecycle_key, 'owner', 'lease_until')
      redis.call('EXPIRE', lifecycle_key, 3456000)
    end
  elseif ARGV[3] == 'job.cancelled' and lifecycle_status ~= 'completed' then
    if terminal_result == 'cancelled' then
      redis.call('HSET', lifecycle_key, 'status', 'cancelled', 'updated_at', now)
      redis.call('HDEL', lifecycle_key, 'owner', 'lease_until')
      redis.call('EXPIRE', lifecycle_key, 3456000)
    end
  end
elseif lifecycle_status and ARGV[3] == 'job.retrying' then
  if (lifecycle_status == 'running' or lifecycle_status == 'finalizing') and lifecycle_owner and event_owner == lifecycle_owner then
    redis.call('HSET', lifecycle_key, 'status', 'queued', 'updated_at', now)
    redis.call('HDEL', lifecycle_key, 'owner', 'lease_until')
  else
    return {'', '0', ''}
  end
end
local sequence = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[1])

event['sequence'] = sequence
local payload = cjson.encode(event)
local stream_id = redis.call(
  'XADD', KEYS[2], 'MAXLEN', '~', 1000, '*',
  'payload', payload,
  'type', ARGV[3],
  'sequence', tostring(sequence),
  'event_id', ARGV[4]
)
redis.call('EXPIRE', KEYS[2], ARGV[1])

redis.call('PUBLISH', KEYS[3], cjson.encode({
  type = 'event', event = event, stream_id = stream_id
}))

if ARGV[5] == '1' and not (lifecycle_status == 'completed' and completion_aux_event) then
  local state = cjson.decode(ARGV[6])
  state['last_updated'] = now
  redis.call('SET', KEYS[4], cjson.encode(state), 'EX', ARGV[1])
end

return {stream_id, tostring(sequence), payload}
"""


# ------------------------------------------------------------------ #
#  Initialisation (called once per Celery worker OS process)         #
# ------------------------------------------------------------------ #

def initialize_worker_redis(redis_url: str, password: Optional[str] = None) -> None:
    """
    Create a fresh synchronous Redis connection for this worker process.
    Called from the worker_process_init Celery signal in celery_app.py.
    """
    global _worker_redis

    previous = _worker_redis
    client = redis.from_url(
        redis_url,
        password=password or None,
        max_connections=5,
        decode_responses=True,
        retry_on_timeout=True,
        socket_connect_timeout=5,
        socket_timeout=10,
    )
    try:
        # Verify connectivity before publishing the process-wide reference.
        client.ping()
    except Exception:
        _close_redis_client(client)
        raise

    _worker_redis = client
    if previous is not None:
        _close_redis_client(previous)
    logger.info(f"Worker Redis client initialized (PID {os.getpid()})")


def _close_redis_client(client: redis.Redis) -> None:
    try:
        client.close()
    except Exception as exc:
        logger.warning("Failed to close worker Redis client", extra={"error_type": type(exc).__name__})


def close_worker_redis() -> None:
    """Close and forget the synchronous client owned by this worker process."""
    global _worker_redis

    client = _worker_redis
    _worker_redis = None
    if client is None:
        return
    _close_redis_client(client)


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
    event: Dict[str, Any] = {
        "event_id": event_id,
        "job_id": job_id,
        "timestamp": time.time(),
        "type": event_type,
        **payload_extra,
    }
    # The owner token is consumed inside the queue-side Lua script and removed
    # before the event is written/published. It prevents a stale worker from
    # publishing success after cleanup has taken over its expired lease.
    try:
        from .job_lifecycle import current_owner, current_owner_epoch

        owner = current_owner(job_id)
        if owner:
            event["_lifecycle_owner"] = owner
            owner_epoch = current_owner_epoch(job_id)
            if owner_epoch is None:
                # ``set_current_owner`` is retained for direct legacy worker
                # entry points which predate epoch capabilities.  Production
                # admission always calls ``set_current_capability`` with the
                # claimed epoch; only this compatibility path may resolve the
                # epoch once, immediately before the guarded Lua decision.
                raw_epoch = r.hget(f"latexy:job:{job_id}:lifecycle", "epoch")
                try:
                    owner_epoch = int(raw_epoch)
                except (TypeError, ValueError):
                    if isinstance(raw_epoch, bytes):
                        try:
                            owner_epoch = int(raw_epoch.decode("utf-8"))
                        except (TypeError, ValueError):
                            return ""
                    else:
                        return ""
                event["_lifecycle_epoch"] = str(owner_epoch)
            else:
                event["_lifecycle_epoch"] = str(owner_epoch)
    except Exception:
        owner = None
    # High-frequency content deltas are not state transitions and carry no
    # stage/percent. Persisting them would both add needless writes and reset the
    # REST fallback progress snapshot to blank/zero.
    update_state = event_type not in {"llm.token", "log.line"}
    if update_state:
        from ..models.event_schemas import status_from_event_type

        state_json = json.dumps(
            {
                "status": status_from_event_type(event_type),
                "stage": payload_extra.get("stage", ""),
                "percent": payload_extra.get("percent", 0),
                "last_updated": time.time(),
            }
        )
    else:
        state_json = ""

    sequence_key = f"latexy:job:{job_id}:seq"
    stream_key = f"latexy:stream:{job_id}"
    channel = f"latexy:events:{job_id}"
    state_key = f"latexy:job:{job_id}:state"
    result = r.eval(
        _PUBLISH_EVENT_SCRIPT,
        4,
        sequence_key,
        stream_key,
        channel,
        state_key,
        str(ttl),
        json.dumps(event),
        event_type,
        event_id,
        "1" if update_state else "0",
        state_json,
    )
    if event_type in {"job.completed", "job.failed", "job.cancelled", "job.retrying"}:
        try:
            from .job_lifecycle import (
                clear_current_owner,
                current_owner_epoch,
                lifecycle_status,
                release_database_ownership,
                stop_lease_heartbeat,
            )

            stop_lease_heartbeat(job_id)
            status = lifecycle_status(r, job_id)
            if event_type == "job.retrying":
                if owner and result[0]:
                    epoch = current_owner_epoch(job_id)
                    if epoch is not None:
                        release_database_ownership(job_id, owner, epoch)
                clear_current_owner(job_id)
            elif status in {"completed", "failed", "cancelled"}:
                # Keep the owner through a failure/cancel event that precedes
                # its result write; clear it once the atomic result transition
                # has completed or a retry has explicitly released ownership.
                if not r.hget(f"latexy:job:{job_id}:lifecycle", "terminal_result") and not owner:
                    clear_current_owner(job_id)
        except Exception:
            pass
    entry_id = result[0]
    if isinstance(entry_id, bytes):
        entry_id = entry_id.decode("utf-8")
    seq = int(result[1])

    # 4. A terminal failure has many worker call sites. Dispatch its optional
    # email here so every job type is covered, with Redis NX preventing duplicate
    # messages when signal recovery and a task handler publish the same outcome.
    if event_type == "job.failed" and entry_id:
        _submit_job_failure_email_once(r, job_id, ttl)

    logger.debug(f"[{job_id}] Published {event_type} (seq={seq})")
    return str(entry_id)


def _submit_job_failure_email_once(r: redis.Redis, job_id: str, ttl: int) -> None:
    """Best-effort, deduplicated dispatch for an owned terminal job failure."""
    dedupe_key = f"latexy:job:{job_id}:failure-email-enqueued"
    try:
        raw_meta = r.get(f"latexy:job:{job_id}:meta")
        if not raw_meta:
            return
        if isinstance(raw_meta, bytes):
            raw_meta = raw_meta.decode("utf-8")
        meta = json.loads(raw_meta)
        user_id = meta.get("user_id")
        if not user_id:
            return

        claimed = r.set(dedupe_key, "1", ex=ttl, nx=True)
        if not claimed:
            return

        from .email_worker import submit_job_failure_email

        if not submit_job_failure_email(
            str(user_id),
            str(meta.get("job_type") or "resume_job"),
            job_id,
        ):
            # Dispatch never left this process; release the claim so a later
            # terminal recovery event can retry instead of silently losing it.
            r.delete(dedupe_key)
    except Exception as exc:
        logger.warning("[%s] Failed to dispatch job-failure email (%s)", job_id, type(exc).__name__)


# ------------------------------------------------------------------ #
#  Publish final result (fetched by REST GET /jobs/{id}/result)      #
# ------------------------------------------------------------------ #

def publish_owned_result(
    job_id: str,
    result_key: str,
    result: Dict[str, Any],
    *,
    terminal_status: str,
    ttl: int = _DEFAULT_TTL,
    force: bool = False,
    serialized_result: Optional[str] = None,
) -> bool:
    """Atomically store a result and reserve its matching terminal event.

    ``result_key`` may be a job's canonical result key or a job-type-specific
    result key. Metered writers must have the current owner and an unexpired
    lease; the lifecycle's ``terminal_result``/``terminal_owner`` fields then
    let ``publish_event`` accept exactly the corresponding terminal event.
    """
    r = get_worker_redis()
    lifecycle = f"latexy:job:{job_id}:lifecycle"
    if terminal_status not in {"completed", "failed", "cancelled"}:
        raise ValueError("terminal_status must be completed, failed, or cancelled")
    owner = None
    try:
        from .job_lifecycle import current_owner

        owner = current_owner(job_id)
    except Exception:
        pass
    if owner:
        from .job_lifecycle import current_owner_epoch

        owner_epoch = current_owner_epoch(job_id)
        if owner_epoch is None:
            # Compatibility for callers that explicitly set only an owner.
            # Admitted workers carry an immutable epoch and never use this
            # mutable lookup; the Lua script still checks lease and owner.
            raw_epoch = r.hget(lifecycle, "epoch")
            try:
                owner_epoch = int(raw_epoch)
            except (TypeError, ValueError):
                if isinstance(raw_epoch, bytes):
                    try:
                        owner_epoch = int(raw_epoch.decode("utf-8"))
                    except (TypeError, ValueError):
                        return False
                else:
                    return False
        if not _persist_arbiter_terminal(job_id, owner, owner_epoch, result, terminal_status):
            return False
    serialized = serialized_result if serialized_result is not None else json.dumps(result)
    # ``force`` is a cleanup-only capability after a durable fence. A live
    # worker must never turn it into an unguarded write if a caller accidentally
    # passes the flag while it still owns the job.
    if force and owner:
        return False
    if force:
        r.set(result_key, serialized, ex=ttl)
        return True
    lifecycle_exists = bool(r.exists(lifecycle))
    if lifecycle_exists and not owner:
        # An admitted metered job cannot fall back to an unguarded result write
        # after its owner context was lost.
        return False
    if owner:
        if not lifecycle_exists:
            return False
        script = """
        local status = redis.call('HGET', KEYS[1], 'status')
        if status ~= 'running' and status ~= 'finalizing' then return 0 end
        if redis.call('HGET', KEYS[1], 'owner') ~= ARGV[2] then return 0 end
        if redis.call('HGET', KEYS[1], 'epoch') ~= ARGV[3] then return 0 end
        local clock = redis.call('TIME')
        local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
        if tonumber(redis.call('HGET', KEYS[1], 'lease_until') or '0') <= now then return 0 end
        if ARGV[5] == 'completed' and redis.call('HGET', KEYS[1], 'cancel_requested') == '1' then return 0 end
        redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[4])
        redis.call('HSET', KEYS[1], 'status', ARGV[5], 'terminal_result', ARGV[5],
          'terminal_owner', ARGV[2], 'updated_at', now)
        redis.call('HDEL', KEYS[1], 'owner', 'lease_until')
        redis.call('EXPIRE', KEYS[1], 3456000)
        return 1
        """
        return bool(r.eval(
            script,
            2,
            lifecycle,
            result_key,
            serialized,
            owner,
            str(owner_epoch),
            ttl,
            terminal_status,
        ))
    # Legacy jobs without a lifecycle record still need an atomic first-writer
    # decision.  The ordinary ``exists`` check above only decides whether an
    # ownerless write is permitted; it must not become a check-then-set race
    # between a late success and a signal/cleanup failure result.
    legacy_result_script = """
    if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
    redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
    return 1
    """
    return bool(r.eval(legacy_result_script, 1, result_key, serialized, ttl))


def publish_job_result(
    job_id: str,
    result: Dict[str, Any],
    ttl: int = _DEFAULT_TTL,
    *,
    force: bool = False,
) -> bool:
    """Store the canonical job result with lifecycle ownership fencing."""
    terminal_status = "cancelled" if result.get("cancelled") is True else (
        "completed" if result.get("success") is True else "failed"
    )
    return publish_owned_result(
        job_id,
        f"latexy:job:{job_id}:result",
        result,
        terminal_status=terminal_status,
        ttl=ttl,
        force=force,
    )


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
    r.set(f"latexy:job:{job_id}:meta", json.dumps(meta), ex=ttl)

    if user_id:
        r.zadd(f"latexy:user:{user_id}:jobs", {job_id: time.time()})
        r.expire(f"latexy:user:{user_id}:jobs", 30 * 86400)


# ------------------------------------------------------------------ #
#  Cancellation helpers (workers poll + publish via stream+pubsub)   #
# ------------------------------------------------------------------ #

def is_cancelled(job_id: str) -> bool:
    """Return True if the user has requested cancellation of this job."""
    r = get_worker_redis()
    return bool(
        r.exists(f"latexy:job:{job_id}:cancel")
        or r.hget(f"latexy:job:{job_id}:lifecycle", "cancel_requested")
    )


def publish_cancel_event(
    job_id: str,
    reason: str = "Cancelled by user",
    ttl: int = _DEFAULT_TTL,
) -> str:
    """
    Publish a job.cancelled event to both the Redis Stream and Pub/Sub channel.

    This ensures the frontend receives cancellation via WebSocket (Pub/Sub)
    and can replay it on reconnect (Stream).  Call this after detecting
    is_cancelled() inside a worker, immediately before returning.

    Returns the Redis Stream entry ID.
    """
    return publish_event(
        job_id=job_id,
        event_type="job.cancelled",
        payload_extra={
            "reason": reason,
            "stage": "cancelled",
            "percent": 0,
        },
        ttl=ttl,
    )
