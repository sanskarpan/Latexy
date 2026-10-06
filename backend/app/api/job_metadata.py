"""Fail-closed parsing of security-critical Redis ownership envelopes."""

import json
from typing import Any

from fastapi import HTTPException


def parse_ownership_metadata(raw: Any, expected_id: str, *, id_field: str = "job_id") -> dict:
    """Preserve explicit legacy ownership; reject malformed/misbound envelopes.

    Older transport envelopes can omit the ID because the Redis key supplied
    it. An explicit ID must agree with that key. Missing ownership is never an
    anonymous job: only a present JSON null grants the anonymous contract.
    """
    try:
        metadata = json.loads(raw)
        if not isinstance(metadata, dict) or "user_id" not in metadata:
            raise ValueError("missing ownership")
        owner = metadata["user_id"]
        if owner is not None and (not isinstance(owner, str) or not owner.strip()):
            raise ValueError("invalid ownership")
        if id_field in metadata and metadata[id_field] != expected_id:
            raise ValueError("mismatched identity")
    except (TypeError, ValueError, RecursionError):
        raise HTTPException(status_code=503, detail="Job ownership could not be verified") from None
    return metadata
