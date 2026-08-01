"""Shared guard for UUID path parameters.

``await db.get(Model, "notauuid")`` and ``select(...).where(Model.id == "x")``
do not return None for a malformed id — asyncpg raises ``ValueError`` while
encoding the parameter, which surfaces to the caller as a 500. A path segment
that cannot name a row should be a 404, so routes taking a UUID path parameter
run it through :func:`ensure_uuid` before touching the database.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Optional

from fastapi import HTTPException


def is_uuid(value: Optional[str]) -> bool:
    """Whether *value* parses as a UUID."""
    try:
        _uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def ensure_uuid(value: str, detail: str = "Not found") -> str:
    """Return *value* if it is a UUID, else raise 404 with *detail*."""
    if not is_uuid(value):
        raise HTTPException(status_code=404, detail=detail)
    return value
