"""Exactly-once quota refunds from synchronous Celery/Modal workers."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ..core.logging import get_logger
from .event_publisher import get_worker_redis

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
        refunded = get_worker_redis().eval(
            _REFUND_QUOTA,
            2,
            counter_key,
            marker_key,
            cost,
            _REFUND_TTL,
        )
        if refunded:
            logger.info("Refunded %s quota for failed job %s", dimension, job_id)
        return bool(refunded)
    except Exception as exc:
        logger.warning("%s quota refund failed for job %s: %s", dimension, job_id, exc)
        return False
