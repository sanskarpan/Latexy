"""Exactly-once quota refunds from synchronous Celery/Modal workers."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ..core.logging import get_logger
from ..core.redis import get_sync_redis_cache_client

# Kept as a patchable module seam for worker tests; this intentionally resolves
# to the cache Redis database, where quota counters are consumed.
get_worker_redis = get_sync_redis_cache_client

logger = get_logger(__name__)

_REFUND_TTL = 40 * 86400
_REFUND_QUOTA = """
if not redis.call('SET', KEYS[2], '1', 'NX', 'EX', ARGV[2]) then
  return 0
end
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local refund = tonumber(ARGV[1])
if current > 0 and current <= refund then
  redis.call('SET', KEYS[1], '0', 'KEEPTTL')
elseif current > refund then
  redis.call('DECRBY', KEYS[1], refund)
end
return 1
"""


def clear_quota_refund_receipt(job_id: str) -> None:
    """Best-effort removal of a receipt after a job reaches success."""
    try:
        redis = get_worker_redis()
        # Keep a durable terminal outcome for at least as long as the quota
        # receipt. Job state/result keys expire much sooner; without this marker
        # a successful job whose receipt deletion raced a Redis outage could be
        # mistaken for a pre-dispatch crash and refunded later.
        redis.set(f"latexy:quota-terminal:{job_id}", "success", ex=_REFUND_TTL)
        redis.delete(f"latexy:quota-refund-pending:{job_id}")
    except Exception as exc:
        logger.warning(
            "Quota refund receipt cleanup failed for job %s",
            job_id,
            extra={"error_type": type(exc).__name__},
        )


def refund_quota_once(
    job_id: str,
    quota_refund: Optional[Dict[str, Any]],
    *,
    expected_dimension: str,
) -> bool:
    """Refund a trusted serialized quota receipt once per job and dimension."""
    if not quota_refund:
        return False

    dimension = quota_refund.get("dimension")
    user_id = quota_refund.get("user_id")
    period = quota_refund.get("period")
    cost = quota_refund.get("cost", 1)
    if (
        dimension != expected_dimension
        or not isinstance(user_id, str)
        or not user_id
        or not isinstance(period, str)
        or not re.fullmatch(r"\d{6}(?:\d{2})?", period)
        or not isinstance(cost, int)
        or isinstance(cost, bool)
        or cost < 1
    ):
        logger.error("Invalid %s quota refund payload for job %s", expected_dimension, job_id)
        return False

    counter_key = f"latexy:quota:{dimension}:{user_id}:{period}"
    marker_key = f"latexy:quota-refund:{dimension}:{job_id}"
    try:
        redis = get_worker_redis()
        refunded = redis.eval(
            _REFUND_QUOTA,
            2,
            counter_key,
            marker_key,
            cost,
            _REFUND_TTL,
        )
        # The atomic marker means a zero result is also a confirmed prior
        # refund.  In either case the durable pending receipt is no longer
        # needed; delete it only after the Lua operation has completed.
        redis.delete(f"latexy:quota-refund-pending:{job_id}")
        if refunded:
            logger.info("Refunded %s quota for failed job %s", dimension, job_id)
        return bool(refunded)
    except Exception as exc:
        logger.warning(
            "%s quota refund failed for job %s",
            dimension,
            job_id,
            extra={"error_type": type(exc).__name__},
        )
        return False
