"""Privacy-safe content-library telemetry on the existing analytics table.

Snippet inserts and macro executions are written as allowlisted aggregate
events in ``usage_analytics``.  Deleted snippets leave an append-only tombstone
containing only the id, title snapshot, category and the last aggregate
counters; bodies, descriptions, tags and author identifiers are never copied.

No schema change is involved: the existing ``usage_analytics.event_metadata``
JSONB column carries the small, curated payload.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import SnippetInstall, SnippetUpvote, UsageAnalytics

SNIPPET_INSERT_ACTION = "snippet_insert"
SNIPPET_DELETE_ACTION = "snippet_delete"
MACRO_USE_ACTION = "macro_use"

_MAX_TITLE = 200
_MAX_CATEGORY = 40


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _text(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned[:limit] if cleaned else None


async def _add(db: AsyncSession, record: UsageAnalytics) -> None:
    """Add a row without assuming a concrete AsyncSession in route doubles."""
    added = db.add(record)
    if inspect.isawaitable(added):
        await added


async def record_snippet_insert(
    db: AsyncSession,
    *,
    snippet_id: str,
    user_id: Optional[str],
    category: Optional[str],
    is_official: bool,
) -> None:
    """Record one marketplace insert attempt for time-bounded adoption."""
    await _add(
        db,
        UsageAnalytics(
            user_id=user_id,
            action=SNIPPET_INSERT_ACTION,
            resource_type="snippet",
            event_metadata={
                "snippet_id": str(snippet_id),
                "category": _text(category, _MAX_CATEGORY),
                "is_official": bool(is_official),
            },
        ),
    )


async def record_snippet_delete_snapshot(
    db: AsyncSession,
    *,
    snippet: Any,
    user_id: Optional[str],
) -> None:
    """Keep an aggregate-only identity/name tombstone before a hard delete.

    ``snippet`` is the ORM row being deleted.  Only the values below are copied;
    ``content``, ``description``, ``tags`` and the author id stay out of the
    analytics table.  Live row counts are preferred over the denormalized
    counters so a drifted counter cannot erase the adoption history.
    """
    snippet_id = str(getattr(snippet, "id", ""))
    install_count = 0
    upvote_count = 0
    users_count = 0
    try:
        install_stats = (
            await db.execute(
                select(
                    func.count(SnippetInstall.user_id).label("installs"),
                ).where(SnippetInstall.snippet_id == snippet_id)
            )
        ).one()
        install_count = _int(getattr(install_stats, "installs", 0))
        upvote_stats = (
            await db.execute(
                select(
                    func.count(SnippetUpvote.user_id).label("upvotes"),
                ).where(SnippetUpvote.snippet_id == snippet_id)
            )
        ).one()
        upvote_count = _int(getattr(upvote_stats, "upvotes", 0))
        install_users = select(SnippetInstall.user_id.label("user_id")).where(
            SnippetInstall.snippet_id == snippet_id,
            SnippetInstall.user_id.is_not(None),
        )
        upvote_users = select(SnippetUpvote.user_id.label("user_id")).where(
            SnippetUpvote.snippet_id == snippet_id,
            SnippetUpvote.user_id.is_not(None),
        )
        combined = union(install_users, upvote_users).subquery("snippet_delete_users")
        users_count = _int(
            (await db.execute(select(func.count(func.distinct(combined.c.user_id))).select_from(combined))).scalar()
        )
    except Exception:
        # A lightweight route double may not implement aggregate queries.  Fall
        # back to the denormalized counters rather than blocking the delete.
        install_count = 0
        upvote_count = 0
        users_count = 0

    metadata = {
        "snippet_id": snippet_id,
        "title": _text(getattr(snippet, "title", None), _MAX_TITLE),
        "category": _text(getattr(snippet, "category", None), _MAX_CATEGORY),
        "is_official": bool(getattr(snippet, "is_official", False)),
        "created_at": _iso(getattr(snippet, "created_at", None)),
        "installs_count": max(_int(getattr(snippet, "installs_count", 0)), install_count),
        "upvotes_count": max(_int(getattr(snippet, "upvotes_count", 0)), upvote_count),
        "users_count": users_count,
        "snapshot_version": 1,
    }
    await _add(
        db,
        UsageAnalytics(
            user_id=user_id,
            action=SNIPPET_DELETE_ACTION,
            resource_type="snippet",
            event_metadata=metadata,
        ),
    )


async def record_macro_use(
    db: AsyncSession,
    *,
    macro_id: str,
    user_id: Optional[str],
    script_version: Optional[int],
) -> None:
    """Record a server-executed script macro without its name or source."""
    await _add(
        db,
        UsageAnalytics(
            user_id=user_id,
            action=MACRO_USE_ACTION,
            resource_type="macro",
            event_metadata={
                "macro_id": str(macro_id),
                "script_version": _int(script_version),
            },
        ),
    )
