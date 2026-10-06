"""Durable dispatch/ownership fencing for metered jobs.

Quota receipts live in the cache Redis database, while job state and worker
events live in the queue Redis database.  This module deliberately keeps the
dispatch lifecycle in the queue database: a worker must be able to atomically
claim work and a cleanup process must be able to fence that work before
refunding a receipt.  The receipt is only refunded after ``fence_job`` wins.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..core.logging import get_logger

logger = get_logger(__name__)

_owner_context = threading.local()
_heartbeat_context = threading.local()

LIFECYCLE_TTL = 40 * 86400
WORKER_LEASE_SECONDS = 15 * 60
LEASE_RENEW_SECONDS = 45
DISPATCH_DEADLINE_SECONDS = 15 * 60


def lifecycle_key(job_id: str) -> str:
    return f"latexy:job:{job_id}:lifecycle"


def _redis_one(value: Any) -> bool:
    return value == 1 or value == b"1"


def set_current_owner(job_id: str, owner: str) -> None:
    set_current_capability(job_id, owner, None)


def set_current_capability(job_id: str, owner: str, owner_epoch: Optional[int]) -> None:
    """Record the immutable Redis admission capability for this invocation.

    The epoch is captured at claim time.  Readers must not fetch the current
    epoch later: a duplicate delivery can take over the same Redis hash after
    the first lease expires, and the old delivery must remain fenced.
    """
    owners = getattr(_owner_context, "owners", None)
    if owners is None:
        owners = {}
        _owner_context.owners = owners
    owners[job_id] = (owner, owner_epoch)


def current_owner(job_id: str) -> Optional[str]:
    capability = getattr(_owner_context, "owners", {}).get(job_id)
    if isinstance(capability, tuple):
        return capability[0]
    return capability


def current_owner_epoch(job_id: str) -> Optional[int]:
    capability = getattr(_owner_context, "owners", {}).get(job_id)
    if not isinstance(capability, tuple):
        return None
    return capability[1]


def clear_current_owner(job_id: str) -> None:
    getattr(_owner_context, "owners", {}).pop(job_id, None)


_BEGIN_DISPATCH = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
redis.call('HSET', KEYS[1], 'status', 'dispatching', 'created_at', now,
  'updated_at', now, 'dispatch_deadline', now + tonumber(ARGV[1]))
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""

_MARK_ACCEPTED = """
if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
local status = redis.call('HGET', KEYS[1], 'status')
if status == 'cancelled' or status == 'failed' or status == 'completed' or status == 'finalizing' then return 0 end
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
if status ~= 'running' then
  redis.call('HSET', KEYS[1], 'status', 'queued')
end
redis.call('HSET', KEYS[1], 'updated_at', now, 'accepted_at', now)
redis.call('EXPIRE', KEYS[1], ARGV[1])
return 1
"""

_CLAIM_WORKER = """
if redis.call('EXISTS', KEYS[1]) == 0 then return -1 end
local status = redis.call('HGET', KEYS[1], 'status')
if status == 'cancelled' or status == 'failed' or status == 'completed' or status == 'finalizing' then return 0 end
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
if redis.call('HGET', KEYS[1], 'cancel_requested') == '1' then return 0 end
local lease = tonumber(redis.call('HGET', KEYS[1], 'lease_until') or '0')
local owner = redis.call('HGET', KEYS[1], 'owner')
if status == 'running' and lease > now and owner ~= ARGV[1] then return 0 end
local epoch = tonumber(redis.call('HGET', KEYS[1], 'epoch') or '0') + 1
redis.call('HSET', KEYS[1], 'status', 'running', 'owner', ARGV[1],
  'started_at', redis.call('HGET', KEYS[1], 'started_at') or now,
  'updated_at', now, 'lease_until', now + tonumber(ARGV[2]), 'epoch', epoch)
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""

_RENEW_LEASE = """
local status = redis.call('HGET', KEYS[1], 'status')
if status ~= 'running' and status ~= 'finalizing' then return 0 end
if redis.call('HGET', KEYS[1], 'owner') ~= ARGV[1] then return 0 end
if ARGV[2] ~= '' and redis.call('HGET', KEYS[1], 'epoch') ~= ARGV[2] then return 0 end
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
if tonumber(redis.call('HGET', KEYS[1], 'lease_until') or '0') <= now then return 0 end
redis.call('HSET', KEYS[1], 'updated_at', now, 'lease_until', now + tonumber(ARGV[3]))
redis.call('EXPIRE', KEYS[1], ARGV[4])
return 1
"""

_BEGIN_FINALIZING = """
if redis.call('HGET', KEYS[1], 'status') ~= 'running' then return 0 end
if redis.call('HGET', KEYS[1], 'owner') ~= ARGV[1] then return 0 end
local lifecycle_epoch = redis.call('HGET', KEYS[1], 'epoch')
if ARGV[2] ~= '' and lifecycle_epoch ~= ARGV[2] then return 0 end
if redis.call('HGET', KEYS[1], 'cancel_requested') == '1' then return 0 end
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
if tonumber(redis.call('HGET', KEYS[1], 'lease_until') or '0') <= now then return 0 end
redis.call('HSET', KEYS[1], 'status', 'finalizing', 'updated_at', now, 'lease_until', now + tonumber(ARGV[3]))
redis.call('EXPIRE', KEYS[1], ARGV[4])
return 1
"""

_FENCE_JOB = """
if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
local status = redis.call('HGET', KEYS[1], 'status')
if status == 'cancelled' or status == 'failed' or status == 'completed' then return 0 end
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
if (status == 'running' or status == 'finalizing') and tonumber(redis.call('HGET', KEYS[1], 'lease_until') or '0') > now then
  return 0
end
redis.call('HSET', KEYS[1], 'status', 'failed', 'fenced_at', now,
  'updated_at', now, 'reason', ARGV[1])
redis.call('HDEL', KEYS[1], 'owner', 'lease_until')
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""

_FENCE_ORPHAN_WITHOUT_LIFECYCLE = """
if redis.call('EXISTS', KEYS[1]) == 1 or redis.call('EXISTS', KEYS[2]) == 1 or
   redis.call('EXISTS', KEYS[3]) == 1 or redis.call('EXISTS', KEYS[4]) == 1 then
  return 0
end
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
redis.call('HSET', KEYS[1], 'status', 'failed', 'fenced_at', now,
  'updated_at', now, 'reason', ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""

# A broker marker can survive a crash between ``dispatch-started`` and the
# lifecycle/state write (or after those short-lived snapshots expire).  Once
# the receipt has exceeded the conservative dispatch deadline, create a
# terminal tombstone only when no lifecycle, result, or worker-owned state is
# present.  New workers reject the tombstone at admission, fencing a late
# broker delivery before it can run without a receipt.
_FENCE_DISPATCH_ORPHAN_WITHOUT_LIFECYCLE = """
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
if redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
if redis.call('EXISTS', KEYS[3]) == 0 then return 0 end
if redis.call('EXISTS', KEYS[4]) == 1 then return 0 end
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
redis.call('HSET', KEYS[1], 'status', 'failed', 'terminal_result', 'failed',
  'fenced_at', now, 'updated_at', now, 'reason', ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""

_REQUEST_CANCEL = """
if redis.call('EXISTS', KEYS[1]) == 0 then return -1 end
local status = redis.call('HGET', KEYS[1], 'status')
if status == 'completed' or status == 'failed' or status == 'cancelled' then return 0 end
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
if status == 'running' then
  redis.call('HSET', KEYS[1], 'cancel_requested', '1', 'updated_at', now)
  return 2
end
redis.call('HSET', KEYS[1], 'status', 'cancelled', 'cancel_requested', '1', 'updated_at', now)
redis.call('HDEL', KEYS[1], 'owner', 'lease_until')
redis.call('EXPIRE', KEYS[1], ARGV[1])
return 1
"""


def begin_dispatch(redis_client: Any, job_id: str) -> bool:
    return _redis_one(redis_client.eval(
        _BEGIN_DISPATCH,
        1,
        lifecycle_key(job_id),
        DISPATCH_DEADLINE_SECONDS,
        LIFECYCLE_TTL,
    ))


async def begin_dispatch_async(redis_client: Any, job_id: str) -> bool:
    result = await redis_client.eval(
        _BEGIN_DISPATCH,
        1,
        lifecycle_key(job_id),
        DISPATCH_DEADLINE_SECONDS,
        LIFECYCLE_TTL,
    )
    return result == 1 or result == b"1"


def mark_dispatch_accepted(redis_client: Any, job_id: str) -> bool:
    return _redis_one(redis_client.eval(
        _MARK_ACCEPTED,
        1,
        lifecycle_key(job_id),
        LIFECYCLE_TTL,
    ))


async def mark_dispatch_accepted_async(redis_client: Any, job_id: str) -> bool:
    result = await redis_client.eval(
        _MARK_ACCEPTED,
        1,
        lifecycle_key(job_id),
        LIFECYCLE_TTL,
    )
    return result == 1 or result == b"1"


def claim_worker(redis_client: Any, job_id: str, owner: str) -> bool:
    result = redis_client.eval(
        _CLAIM_WORKER,
        1,
        lifecycle_key(job_id),
        owner,
        WORKER_LEASE_SECONDS,
        LIFECYCLE_TTL,
    )
    return result == 1 or result == b"1"


def renew_worker_lease(
    redis_client: Any,
    job_id: str,
    owner: str,
    owner_epoch: Optional[int] = None,
) -> bool:
    result = redis_client.eval(
        _RENEW_LEASE,
        1,
        lifecycle_key(job_id),
        owner,
        "" if owner_epoch is None else str(owner_epoch),
        WORKER_LEASE_SECONDS,
        LIFECYCLE_TTL,
    )
    return result == 1 or result == b"1"


def begin_finalizing(
    redis_client: Any, job_id: str, owner: str, owner_epoch: Optional[int] = None
) -> bool:
    if owner_epoch is None and current_owner(job_id) == owner:
        owner_epoch = current_owner_epoch(job_id)
    return _redis_one(redis_client.eval(
        _BEGIN_FINALIZING,
        1,
        lifecycle_key(job_id),
        owner,
        "" if owner_epoch is None else str(owner_epoch),
        WORKER_LEASE_SECONDS,
        LIFECYCLE_TTL,
    ))


def fence_job(redis_client: Any, job_id: str, reason: str = "timeout") -> bool:
    result = redis_client.eval(
        _FENCE_JOB,
        1,
        lifecycle_key(job_id),
        reason,
        LIFECYCLE_TTL,
    )
    return result == 1 or result == b"1"


def fence_orphan_without_lifecycle(
    redis_client: Any,
    job_id: str,
    reason: str = "dispatch_timeout",
) -> bool:
    """Create a terminal tombstone only for a proven pre-dispatch orphan."""
    return _redis_one(redis_client.eval(
        _FENCE_ORPHAN_WITHOUT_LIFECYCLE,
        4,
        lifecycle_key(job_id),
        f"latexy:job:{job_id}:state",
        f"latexy:job:{job_id}:dispatch-started",
        f"latexy:job:{job_id}:result",
        reason,
        LIFECYCLE_TTL,
    ))


def fence_expired_dispatch_without_lifecycle(
    redis_client: Any,
    job_id: str,
    reason: str = "dispatch_timeout",
) -> bool:
    """Fence an aged broker marker when its lifecycle never materialized."""
    return _redis_one(redis_client.eval(
        _FENCE_DISPATCH_ORPHAN_WITHOUT_LIFECYCLE,
        4,
        lifecycle_key(job_id),
        f"latexy:job:{job_id}:state",
        f"latexy:job:{job_id}:dispatch-started",
        f"latexy:job:{job_id}:result",
        reason,
        LIFECYCLE_TTL,
    ))


def request_cancel(redis_client: Any, job_id: str) -> int:
    """Request user cancellation; return 2 when a live worker must stop."""
    result = redis_client.eval(
        _REQUEST_CANCEL,
        1,
        lifecycle_key(job_id),
        LIFECYCLE_TTL,
    )
    try:
        return int(result)
    except (TypeError, ValueError):
        return int(result.decode("utf-8")) if isinstance(result, bytes) else -1


_RECOVER_COMPLETED = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local status = redis.call('HGET', KEYS[1], 'status')
-- A committed database completion is the authoritative terminal decision. It
-- may repair an expired/cancelled Redis snapshot, but never rewrites the
-- result payload itself. The recovery marker reserves the matching event.
redis.call('HSET', KEYS[1], 'status', 'completed', 'terminal_result', 'completed',
  'terminal_owner', 'recovery', 'recovered_at', now, 'updated_at', now)
redis.call('HDEL', KEYS[1], 'owner', 'lease_until', 'cancel_requested', 'reason')
redis.call('EXPIRE', KEYS[1], ARGV[1])
return 1
"""


def recover_completed_lifecycle(redis_client: Any, job_id: str) -> bool:
    """Rebuild a completed Redis lifecycle from committed DB evidence."""
    return _redis_one(redis_client.eval(
        _RECOVER_COMPLETED,
        1,
        lifecycle_key(job_id),
        LIFECYCLE_TTL,
    ))


async def request_cancel_async(redis_client: Any, job_id: str) -> int:
    result = await redis_client.eval(
        _REQUEST_CANCEL,
        1,
        lifecycle_key(job_id),
        LIFECYCLE_TTL,
    )
    try:
        return int(result)
    except (TypeError, ValueError):
        return int(result.decode("utf-8")) if isinstance(result, bytes) else -1


def _renew_database_lease(job_id: str, owner: str, owner_epoch: int) -> bool:
    """Extend the DB arbiter lease using PostgreSQL wall-clock time."""

    async def _renew() -> bool:
        from sqlalchemy import text, update
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from ..core.config import settings
        from ..database.models import JobFinalization
        from ..utils.db_url import normalize_database_url
        from .finalization_arbiter import FinalizationState

        engine = create_async_engine(normalize_database_url(settings.DATABASE_URL), poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                result = await session.execute(
                    update(JobFinalization)
                    .where(
                        JobFinalization.job_id == job_id,
                        JobFinalization.owner_token == owner,
                        JobFinalization.owner_epoch == owner_epoch,
                        JobFinalization.cancel_requested.is_(False),
                        JobFinalization.state.in_((
                            FinalizationState.PENDING.value,
                            FinalizationState.COMMITTING.value,
                        )),
                        JobFinalization.lease_expires_at > text("clock_timestamp()"),
                    )
                    .values(
                        lease_expires_at=text(
                            f"clock_timestamp() + interval '{WORKER_LEASE_SECONDS} seconds'"
                        ),
                        updated_at=text("clock_timestamp()"),
                    )
                )
                await session.commit()
                return bool(result.rowcount)
        finally:
            await engine.dispose()

    try:
        return bool(asyncio.run(_renew()))
    except Exception:
        logger.warning("Durable finalization lease renewal failed for %s", job_id)
        return False


def lifecycle_status(redis_client: Any, job_id: str) -> Optional[str]:
    value = redis_client.hget(lifecycle_key(job_id), "status")
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return value or None


def start_lease_heartbeat(
    redis_client: Any, job_id: str, owner: str, owner_epoch: Optional[int] = None
) -> threading.Thread:
    """Renew a worker lease until a terminal event/fence changes its status."""

    stop_event = threading.Event()

    def _run() -> None:
        while True:
            if stop_event.wait(LEASE_RENEW_SECONDS):
                return
            try:
                if not renew_worker_lease(redis_client, job_id, owner, owner_epoch):
                    return
                if owner_epoch is None:
                    logger.warning("Lifecycle heartbeat has no captured epoch for %s", job_id)
                    return
                if not _renew_database_lease(job_id, owner, owner_epoch):
                    logger.warning("Durable finalization lease renewal rejected for %s", job_id)
                    return
            except Exception:
                # A transient Redis failure must not turn into an unbounded
                # lease.  The next renewal may succeed; cleanup still fails
                # closed while the prior lease remains valid.
                logger.warning("Lifecycle lease renewal failed for %s", job_id)

    thread = threading.Thread(
        target=_run,
        name=f"latexy-lease-{job_id[:8]}",
        daemon=True,
    )
    heartbeats = getattr(_heartbeat_context, "heartbeats", None)
    if heartbeats is None:
        heartbeats = {}
        _heartbeat_context.heartbeats = heartbeats
    heartbeats[job_id] = stop_event
    thread.start()
    return thread


def stop_lease_heartbeat(job_id: str) -> None:
    stop_event = getattr(_heartbeat_context, "heartbeats", {}).pop(job_id, None)
    if stop_event is not None:
        stop_event.set()


def release_database_ownership(job_id: str, owner: str, owner_epoch: int) -> bool:
    """Release a retrying worker's DB lease without terminalizing the job.

    Redis transitions the lifecycle to ``queued`` atomically with the
    retrying event.  This matching DB update lets the next delivery claim the
    same durable arbiter row immediately instead of waiting the full lease.
    """

    async def _release() -> bool:
        from sqlalchemy import text, update
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from ..core.config import settings
        from ..database.models import JobFinalization
        from ..utils.db_url import normalize_database_url
        from .finalization_arbiter import FinalizationState

        engine = create_async_engine(normalize_database_url(settings.DATABASE_URL), poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                result = await session.execute(
                    update(JobFinalization)
                    .where(
                        JobFinalization.job_id == job_id,
                        JobFinalization.owner_token == owner,
                        JobFinalization.owner_epoch == owner_epoch,
                        JobFinalization.state == FinalizationState.PENDING.value,
                        JobFinalization.cancel_requested.is_(False),
                    )
                    .values(
                        owner_token=None,
                        lease_expires_at=None,
                        updated_at=text("clock_timestamp()"),
                    )
                )
                await session.commit()
                return bool(result.rowcount)
        finally:
            await engine.dispose()

    try:
        return bool(asyncio.run(_release()))
    except Exception:
        logger.warning("Durable retry lease release failed for %s", job_id)
        return False


def _persist_database_ownership(
    job_id: str,
    owner: str,
    owner_epoch: int,
    quota_refund: Any,
    user_id: Optional[str],
) -> bool:
    """Linearize Redis admission in the durable finalization arbiter.

    The route creates a pending row before consuming a metered ticket.  This
    short synchronous bridge is used by Celery/Modal workers after the Redis
    claim and before they publish any event or touch output.  Legacy tasks that
    have neither a lifecycle nor a receipt retain their compatibility path.
    A database failure is fail-closed: the Redis lease remains for cleanup to
    fence once it expires, and the receipt is deliberately left recoverable.
    """

    async def _claim() -> bool:
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from ..core.config import settings
        from ..utils.db_url import normalize_database_url
        from .finalization_arbiter import FinalizationState, ensure_finalization

        engine = create_async_engine(normalize_database_url(settings.DATABASE_URL), poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                db_now = await session.scalar(select(func.clock_timestamp()))
                if not isinstance(db_now, datetime):
                    db_now = datetime.now(timezone.utc)
                row = await ensure_finalization(
                    session,
                    job_id=job_id,
                    owner_token=owner,
                    owner_epoch=owner_epoch,
                    lease_expires_at=db_now + timedelta(seconds=WORKER_LEASE_SECONDS),
                    user_id=(user_id or (quota_refund or {}).get("user_id"))
                    if isinstance(quota_refund, dict)
                    else user_id,
                )
                accepted = (
                    row.state == FinalizationState.PENDING.value
                    and row.owner_token == owner
                    and row.owner_epoch == owner_epoch
                )
                await session.commit()
                return accepted
        finally:
            await engine.dispose()

    try:
        return bool(asyncio.run(_claim()))
    except Exception:
        logger.exception("Durable finalization admission failed for %s", job_id)
        return False


def admit_worker(
    redis_client: Any,
    job_id: str,
    owner: str,
    quota_refund: Any,
    user_id: Optional[str] = None,
) -> bool:
    """Atomically admit work with a lifecycle record.

    Lifecycle records are also created for non-metered jobs so dispatch and
    cancellation have one durable fence.  Only legacy jobs that predate the
    lifecycle record may use the unguarded compatibility path; once a record
    exists every worker must own it before publishing state or a result.
    """
    try:
        # Celery may reuse the same execution thread after an exceptional
        # delivery. Never let that stale thread-local capability authorize a
        # later task before this claim has produced a fresh epoch.
        clear_current_owner(job_id)
        lifecycle_exists = redis_client.exists(lifecycle_key(job_id))
        if not quota_refund:
            if lifecycle_exists in (False, 0, b"0"):
                return True
        if not claim_worker(redis_client, job_id, owner):
            return False
        # ``epoch`` is assigned atomically by the Redis claim script.  Never
        # invent an epoch when the field is absent: an owner without a durable
        # capability must not publish or refund.
        epoch = redis_client.hget(lifecycle_key(job_id), "epoch")
        if isinstance(epoch, bytes):
            epoch = epoch.decode("utf-8")
        try:
            owner_epoch = int(epoch)
        except (TypeError, ValueError):
            return False
        if not _persist_database_ownership(job_id, owner, owner_epoch, quota_refund, user_id):
            return False
        set_current_capability(job_id, owner, owner_epoch)
        start_lease_heartbeat(redis_client, job_id, owner, owner_epoch)
        return True
    except Exception:
        logger.exception("Could not claim lifecycle for metered job %s", job_id)
        return False


_WRITE_ARTIFACTS = """
local lifecycle_exists = redis.call('EXISTS', KEYS[1])
local owner = ARGV[1]
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
if lifecycle_exists == 1 then
  if owner == '' then return 0 end
  local status = redis.call('HGET', KEYS[1], 'status')
  if status ~= 'running' and status ~= 'finalizing' then return 0 end
  if redis.call('HGET', KEYS[1], 'cancel_requested') == '1' then return 0 end
  if redis.call('HGET', KEYS[1], 'owner') ~= owner then return 0 end
  if ARGV[2] ~= '' and redis.call('HGET', KEYS[1], 'epoch') ~= ARGV[2] then return 0 end
  if tonumber(redis.call('HGET', KEYS[1], 'lease_until') or '0') <= now then return 0 end
elseif owner ~= '' then
  -- An admitted worker must fail closed if its lifecycle disappeared.
  return 0
end
local value_index = 3
for key_index = 2, #KEYS do
  redis.call('SET', KEYS[key_index], ARGV[value_index], 'EX', ARGV[#ARGV])
  value_index = value_index + 1
end
return 1
"""


def write_owned_artifacts(
    redis_client: Any,
    job_id: str,
    artifacts: dict[str, str],
    ttl: int,
) -> bool:
    """Write job artifacts only while the current lifecycle owner is leased.

    A missing lifecycle is accepted only for legacy, ownerless jobs.  Once a
    worker has an owner, disappearance or takeover fails closed atomically
    with the artifact writes.
    """
    owner = current_owner(job_id) or ""
    owner_epoch = current_owner_epoch(job_id)
    keys = [lifecycle_key(job_id), *artifacts]
    args = [owner, "" if owner_epoch is None else str(owner_epoch), *artifacts.values(), ttl]
    result = redis_client.eval(_WRITE_ARTIFACTS, len(keys), *keys, *args)
    return _redis_one(result)
