"""Shared validation and redaction for untrusted telemetry metadata."""

from __future__ import annotations

import json
from typing import Any, Optional

MAX_METADATA_BYTES = 4096
MAX_METADATA_DEPTH = 5
REDACTED_METADATA_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "password",
        "token",
        "secret",
        "api_key",
        "access_token",
        "refresh_token",
        "email",
        "phone",
        "name",
        "first_name",
        "last_name",
        "address",
        "ip_address",
        "user_agent",
        "resume_content",
        "latex_content",
        "prompt",
    }
)


def payload_depth(value: Any, depth: int = 1) -> int:
    """Return the maximum nesting depth of a JSON-like value."""
    maximum = depth
    pending: list[tuple[Any, int]] = [(value, depth)]
    while pending:
        current, current_depth = pending.pop()
        maximum = max(maximum, current_depth)
        if isinstance(current, dict):
            pending.extend((item, current_depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, current_depth + 1) for item in current)
    return maximum


def redact_metadata(value: Any) -> Any:
    """Strip credentials and direct identifiers recursively before persistence."""
    if isinstance(value, dict):
        return {
            key: (
                "[redacted]"
                if str(key).casefold() in REDACTED_METADATA_KEYS
                else redact_metadata(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_metadata(item) for item in value]
    return value


def validate_metadata(value: Optional[dict]) -> Optional[dict]:
    """Validate and redact a client-supplied telemetry metadata object."""
    if value is None:
        return None
    try:
        serialized = json.dumps(value, default=str, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("metadata must be JSON-serializable") from exc
    if len(serialized.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValueError(f"metadata exceeds maximum allowed size of {MAX_METADATA_BYTES} bytes")
    if payload_depth(value) > MAX_METADATA_DEPTH:
        raise ValueError(f"metadata nesting exceeds maximum depth of {MAX_METADATA_DEPTH}")
    return redact_metadata(value)
