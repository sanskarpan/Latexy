"""Pure environment parsing for the process-local deployment traffic hold."""

from __future__ import annotations

import os
from collections.abc import Mapping

DEPLOYMENT_TRAFFIC_HOLD_ENV = "MODAL_DEPLOYMENT_TRAFFIC_HOLD"


def deployment_traffic_held(environ: Mapping[str, str] | None = None) -> bool:
    """Return the explicitly configured traffic hold state.

    Empty and false values disable the hold. Unknown values fail closed by
    raising so an invalid deployment setting cannot start serving traffic.
    """
    source = os.environ if environ is None else environ
    value = source.get(DEPLOYMENT_TRAFFIC_HOLD_ENV, "")
    normalized = value.strip().lower()
    if normalized in {"", "false"}:
        return False
    if normalized == "true":
        return True
    raise ValueError(f"{DEPLOYMENT_TRAFFIC_HOLD_ENV} must be true or false")
