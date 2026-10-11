"""Atomic initial Redis snapshot and replayable queued event admission."""

import json
import uuid

_INITIAL_JOB_SCRIPT = r"""
-- Never reset an invocation that already has admission or worker evidence.
-- Repeated calls are no-ops, including after completion/cancellation.
for _, index in ipairs({1, 2, 3, 4, 7, 8, 9}) do
  if redis.call('EXISTS', KEYS[index]) == 1 then
    return {'', '0'}
  end
end
if ARGV[5] == '1' then
  local kind = redis.call('TYPE', KEYS[6]).ok
  if kind ~= 'none' and kind ~= 'zset' then
    return redis.error_reply('Invalid job index type')
  end
end
local ttl = tonumber(ARGV[1])
local meta = cjson.decode(ARGV[2])
local event = cjson.decode(ARGV[3])
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local sequence = redis.call('INCR', KEYS[3])
meta['submitted_at'] = now
event['timestamp'] = now
event['sequence'] = sequence
local payload = cjson.encode(event)
local stream_id = redis.call('XADD', KEYS[4], 'MAXLEN', '~', 10000, '*',
  'payload', payload, 'type', 'job.queued', 'sequence', tostring(sequence),
  'event_id', event['event_id'])
redis.call('SET', KEYS[1], cjson.encode({status='queued', stage='', percent=0, last_updated=now}), 'EX', ttl)
redis.call('SET', KEYS[2], cjson.encode(meta), 'EX', ttl)
redis.call('EXPIRE', KEYS[3], ttl)
redis.call('EXPIRE', KEYS[4], ttl)
if ARGV[5] == '1' then
  redis.call('ZADD', KEYS[6], now, ARGV[4])
  redis.call('EXPIRE', KEYS[6], ttl)
end
redis.call('PUBLISH', KEYS[5], cjson.encode({type='event', event=event, stream_id=stream_id}))
return {stream_id, tostring(sequence)}
"""


async def initialize_job_state(redis, *, job_id: str, job_type: str, user_id: str | None,
                               estimated_seconds: int, ttl: int) -> None:
    """Publish a fresh queued job in one round trip, before broker dispatch.

    Auth, durable intent and quotas are decided by the existing API caller.
    This helper does not claim worker ownership or acknowledge dispatch.
    Explicit JSON null ownership remains part of anonymous job metadata.
    """
    if ttl <= 0:
        raise ValueError("Job TTL must be positive")
    meta = {"job_id": job_id, "user_id": user_id, "job_type": job_type}
    event = {"event_id": str(uuid.uuid4()), "job_id": job_id, "type": "job.queued",
             "job_type": job_type, "user_id": user_id, "estimated_seconds": estimated_seconds}
    prefix = f"latexy:job:{job_id}"
    await redis.eval(
        _INITIAL_JOB_SCRIPT, 9,
        f"{prefix}:state", f"{prefix}:meta", f"{prefix}:seq", f"latexy:stream:{job_id}",
        f"latexy:events:{job_id}",
        f"latexy:user:{user_id}:jobs" if user_id else f"{prefix}:unindexed",
        f"{prefix}:lifecycle", f"{prefix}:result", f"{prefix}:cancel",
        str(ttl), json.dumps(meta), json.dumps(event), job_id, "1" if user_id else "0",
    )
