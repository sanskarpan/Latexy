"""Admin content-library adoption, aggregate-only.

Sources are the existing tables only:

* ``snippets`` / ``snippet_installs`` / ``snippet_upvotes``
* ``user_macros``
* ``usage_analytics`` JSONB metadata for time-bounded insert/use events and
  aggregate-only tombstones of deleted snippets.

No snippet/macro body, description, script, recorded action, author id or user
id leaves this module.  Snippet rows with 1-4 distinct historical users are
suppressed; unused rows (zero users) stay visible because they identify no
person.  Macro adoption is emitted as an aggregate block only, never as
per-macro rows, because a macro has exactly one owner.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import Text, cast, func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models
from .content_library_events import (
    MACRO_USE_ACTION,
    SNIPPET_DELETE_ACTION,
    SNIPPET_INSERT_ACTION,
)

Snippet = models.Snippet
SnippetInstall = models.SnippetInstall
SnippetUpvote = models.SnippetUpvote
UserMacro = models.UserMacro
UsageAnalytics = models.UsageAnalytics

MIN_LIBRARY_USERS = 5
MAX_RANGE_DAYS = 365
STALE_AFTER_DAYS = 30
MAX_CATEGORY_FILTERS = 10
STATUSES = ("all", "active", "stale", "unused", "deleted")

CSV_COLUMNS = (
    "rank",
    "snippet_id",
    "snippet_title",
    "category",
    "official",
    "deleted",
    "created_at",
    "deleted_at",
    "age_days",
    "users",
    "active_users",
    "installers",
    "inserts",
    "uses",
    "upvotes",
    "upvote_ratio",
    "lifetime_installs",
    "lifetime_upvotes",
    "last_used_at",
    "stale",
    "unused",
)

_CSV_SOURCE_FIELDS = {
    "snippet_title": "title",
    "official": "is_official",
}

_SNIPPET_ID = UsageAnalytics.event_metadata["snippet_id"].as_string()
_MACRO_ID = UsageAnalytics.event_metadata["macro_id"].as_string()


def _as_date(value: date | str | None) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("date range must use YYYY-MM-DD") from exc


def _resolve_range(
    *,
    days: int,
    start_date: date | str | None,
    end_date: date | str | None,
) -> tuple[date, date, datetime, datetime]:
    """Return inclusive day bounds plus the UTC half-open event range."""
    today = datetime.now(timezone.utc).date()
    start_day = _as_date(start_date)
    end_day = _as_date(end_date)
    if start_day is None and end_day is None:
        end_day = today
        start_day = end_day - timedelta(days=max(1, int(days)) - 1)
    elif start_day is None:
        end_day = end_day or today
        start_day = end_day - timedelta(days=max(1, int(days)) - 1)
    elif end_day is None:
        end_day = today

    assert start_day is not None and end_day is not None
    if start_day > end_day:
        raise ValueError("start_date must be on or before end_date")
    if (end_day - start_day).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"date range cannot exceed {MAX_RANGE_DAYS} days")

    start_at = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start_day, end_day, start_at, end_at


def _split_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _categories(value: str | None) -> list[str]:
    categories = sorted({item.lower()[:40] for item in _split_csv(value)})
    if len(categories) > MAX_CATEGORY_FILTERS:
        raise ValueError(f"at most {MAX_CATEGORY_FILTERS} categories can be selected")
    return categories


def _try_uuid(value: Any) -> Optional[str]:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value).strip()))
    except (TypeError, ValueError, AttributeError):
        return None


def _normalize_uuid(value: str | None) -> Optional[str]:
    if not value:
        return None
    normalized = _try_uuid(value)
    if normalized is None:
        raise ValueError("snippet must be a valid UUID")
    return normalized


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _safe_csv_cell(value: Any) -> Any:
    """Neutralise spreadsheet formula prefixes in user-authored titles."""
    if not isinstance(value, str):
        return value
    if value[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return f"'{value}"
    return value


def _empty() -> dict[str, Any]:
    return {}


def _status_matches(row: dict[str, Any], status: str) -> bool:
    if status == "all":
        return True
    if status == "deleted":
        return bool(row["deleted"])
    if row["deleted"]:
        return False
    if status == "active":
        return bool(row["active"])
    if status == "stale":
        return bool(row["stale"])
    if status == "unused":
        return bool(row["unused"])
    return True


class AdminContentLibraryService:
    async def content_library_adoption(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        category: str | None = None,
        status: str = "all",
        official: bool | None = None,
        snippet: str | None = None,
    ) -> dict[str, Any]:
        days = max(1, min(int(days), MAX_RANGE_DAYS))
        if status not in STATUSES:
            raise ValueError("status must be one of " + ", ".join(STATUSES))
        start_day, end_day, start_at, end_at = _resolve_range(days=days, start_date=start_date, end_date=end_date)
        categories = _categories(category)
        snippet_filter = _normalize_uuid(snippet)
        selected_range_days = (end_day - start_day).days + 1

        snippet_conditions: list[Any] = [Snippet.created_at < end_at]
        if categories:
            snippet_conditions.append(Snippet.category.in_(categories))
        if official is not None:
            snippet_conditions.append(Snippet.is_official.is_(bool(official)))
        if snippet_filter:
            snippet_conditions.append(Snippet.id == snippet_filter)

        snippet_rows = (
            await db.execute(
                select(
                    Snippet.id,
                    Snippet.title,
                    Snippet.category,
                    Snippet.is_official,
                    Snippet.installs_count,
                    Snippet.upvotes_count,
                    Snippet.created_at,
                )
                .where(*snippet_conditions)
                .order_by(Snippet.created_at.asc(), Snippet.id.asc())
            )
        ).all()
        snippet_ids = [str(row.id) for row in snippet_rows]

        range_installs: dict[str, dict[str, Any]] = {}
        lifetime_installs: dict[str, dict[str, Any]] = {}
        upvotes_by_snippet: dict[str, dict[str, Any]] = {}
        range_inserts: dict[str, dict[str, Any]] = {}
        lifetime_inserts: dict[str, dict[str, Any]] = {}
        audience_users: dict[str, int] = {}
        active_users: dict[str, int] = {}

        if snippet_ids:
            rows = (
                await db.execute(
                    select(
                        SnippetInstall.snippet_id.label("snippet_id"),
                        func.count(SnippetInstall.user_id).label("inserts"),
                        func.count(func.distinct(SnippetInstall.user_id)).label("installers"),
                        func.max(SnippetInstall.installed_at).label("last_at"),
                    )
                    .where(
                        SnippetInstall.snippet_id.in_(snippet_ids),
                        SnippetInstall.installed_at >= start_at,
                        SnippetInstall.installed_at < end_at,
                    )
                    .group_by(SnippetInstall.snippet_id)
                )
            ).all()
            range_installs = {
                str(row.snippet_id): {
                    "inserts": _int(row.inserts),
                    "installers": _int(row.installers),
                    "last_at": row.last_at,
                }
                for row in rows
            }

            rows = (
                await db.execute(
                    select(
                        SnippetInstall.snippet_id.label("snippet_id"),
                        func.count(SnippetInstall.user_id).label("installs"),
                        func.count(func.distinct(SnippetInstall.user_id)).label("installers"),
                        func.max(SnippetInstall.installed_at).label("last_at"),
                    )
                    .where(SnippetInstall.snippet_id.in_(snippet_ids))
                    .group_by(SnippetInstall.snippet_id)
                )
            ).all()
            lifetime_installs = {
                str(row.snippet_id): {
                    "installs": _int(row.installs),
                    "installers": _int(row.installers),
                    "last_at": row.last_at,
                }
                for row in rows
            }

            rows = (
                await db.execute(
                    select(
                        SnippetUpvote.snippet_id.label("snippet_id"),
                        func.count(SnippetUpvote.user_id).label("upvotes"),
                        func.count(func.distinct(SnippetUpvote.user_id)).label("upvoters"),
                    )
                    .where(SnippetUpvote.snippet_id.in_(snippet_ids))
                    .group_by(SnippetUpvote.snippet_id)
                )
            ).all()
            upvotes_by_snippet = {
                str(row.snippet_id): {
                    "upvotes": _int(row.upvotes),
                    "upvoters": _int(row.upvoters),
                }
                for row in rows
            }

            rows = (
                await db.execute(
                    select(
                        _SNIPPET_ID.label("snippet_id"),
                        func.count(UsageAnalytics.id).label("uses"),
                        func.count(func.distinct(UsageAnalytics.user_id)).label("users"),
                        func.max(UsageAnalytics.created_at).label("last_at"),
                    )
                    .where(
                        UsageAnalytics.action == SNIPPET_INSERT_ACTION,
                        UsageAnalytics.created_at >= start_at,
                        UsageAnalytics.created_at < end_at,
                        _SNIPPET_ID.in_(snippet_ids),
                    )
                    .group_by(_SNIPPET_ID)
                )
            ).all()
            range_inserts = {
                str(row.snippet_id): {
                    "uses": _int(row.uses),
                    "users": _int(row.users),
                    "last_at": row.last_at,
                }
                for row in rows
                if row.snippet_id is not None
            }

            rows = (
                await db.execute(
                    select(
                        _SNIPPET_ID.label("snippet_id"),
                        func.count(UsageAnalytics.id).label("uses"),
                        func.count(func.distinct(UsageAnalytics.user_id)).label("users"),
                        func.max(UsageAnalytics.created_at).label("last_at"),
                    )
                    .where(
                        UsageAnalytics.action == SNIPPET_INSERT_ACTION,
                        _SNIPPET_ID.in_(snippet_ids),
                    )
                    .group_by(_SNIPPET_ID)
                )
            ).all()
            lifetime_inserts = {
                str(row.snippet_id): {
                    "uses": _int(row.uses),
                    "users": _int(row.users),
                    "last_at": row.last_at,
                }
                for row in rows
                if row.snippet_id is not None
            }

            install_users = select(
                cast(SnippetInstall.snippet_id, Text).label("snippet_id"),
                SnippetInstall.user_id.label("user_id"),
            ).where(
                SnippetInstall.snippet_id.in_(snippet_ids),
                SnippetInstall.user_id.is_not(None),
            )
            upvote_users = select(
                cast(SnippetUpvote.snippet_id, Text).label("snippet_id"),
                SnippetUpvote.user_id.label("user_id"),
            ).where(
                SnippetUpvote.snippet_id.in_(snippet_ids),
                SnippetUpvote.user_id.is_not(None),
            )
            insert_users = select(
                _SNIPPET_ID.label("snippet_id"),
                UsageAnalytics.user_id.label("user_id"),
            ).where(
                UsageAnalytics.action == SNIPPET_INSERT_ACTION,
                _SNIPPET_ID.in_(snippet_ids),
                UsageAnalytics.user_id.is_not(None),
            )
            audience_union = union(install_users, upvote_users, insert_users).subquery("content_library_snippet_users")
            rows = (
                await db.execute(
                    select(
                        audience_union.c.snippet_id,
                        func.count(func.distinct(audience_union.c.user_id)).label("users"),
                    ).group_by(audience_union.c.snippet_id)
                )
            ).all()
            audience_users = {str(row.snippet_id): _int(row.users) for row in rows if row.snippet_id is not None}

            range_install_users = select(
                cast(SnippetInstall.snippet_id, Text).label("snippet_id"),
                SnippetInstall.user_id.label("user_id"),
            ).where(
                SnippetInstall.snippet_id.in_(snippet_ids),
                SnippetInstall.user_id.is_not(None),
                SnippetInstall.installed_at >= start_at,
                SnippetInstall.installed_at < end_at,
            )
            range_insert_users = select(
                _SNIPPET_ID.label("snippet_id"),
                UsageAnalytics.user_id.label("user_id"),
            ).where(
                UsageAnalytics.action == SNIPPET_INSERT_ACTION,
                UsageAnalytics.created_at >= start_at,
                UsageAnalytics.created_at < end_at,
                _SNIPPET_ID.in_(snippet_ids),
                UsageAnalytics.user_id.is_not(None),
            )
            active_union = range_install_users.union(range_insert_users).subquery(
                "content_library_active_snippet_users"
            )
            rows = (
                await db.execute(
                    select(
                        active_union.c.snippet_id,
                        func.count(func.distinct(active_union.c.user_id)).label("users"),
                    ).group_by(active_union.c.snippet_id)
                )
            ).all()
            active_users = {str(row.snippet_id): _int(row.users) for row in rows if row.snippet_id is not None}

        rows: list[dict[str, Any]] = []
        for snippet_row in snippet_rows:
            snippet_id = str(snippet_row.id)
            installs = range_installs.get(snippet_id, _empty())
            lifetime = lifetime_installs.get(snippet_id, _empty())
            upvotes = upvotes_by_snippet.get(snippet_id, _empty())
            inserts = range_inserts.get(snippet_id, _empty())
            lifetime_insert = lifetime_inserts.get(snippet_id, _empty())
            users = audience_users.get(snippet_id, 0)
            counter_installs = _int(snippet_row.installs_count)
            counter_upvotes = _int(snippet_row.upvotes_count)
            lifetime_installs_count = _int(lifetime.get("installs", 0))
            lifetime_upvotes_count = _int(upvotes.get("upvotes", 0))
            lifetime_insert_count = _int(lifetime_insert.get("uses", 0))
            unused = (
                lifetime_installs_count == 0
                and lifetime_upvotes_count == 0
                and lifetime_insert_count == 0
                and counter_installs == 0
                and counter_upvotes == 0
            )
            created_at = snippet_row.created_at
            age_days = max(0, (end_day - created_at.date()).days) if created_at else 0
            last_candidates = [
                installs.get("last_at"),
                inserts.get("last_at"),
                lifetime.get("last_at"),
                lifetime_insert.get("last_at"),
            ]
            last_used_at = max((item for item in last_candidates if item is not None), default=None)
            rows.append(
                {
                    "snippet_id": snippet_id,
                    "title": str(snippet_row.title),
                    "category": str(snippet_row.category),
                    "is_official": bool(snippet_row.is_official),
                    "deleted": False,
                    "deleted_at": None,
                    "created_at": _iso(created_at),
                    "age_days": age_days,
                    "users": users,
                    "active_users": active_users.get(snippet_id, 0),
                    "installers": _int(installs.get("installers", 0)),
                    "inserts": _int(installs.get("inserts", 0)),
                    "uses": _int(inserts.get("uses", 0)),
                    "upvotes": lifetime_upvotes_count,
                    "upvote_ratio": (
                        round(lifetime_upvotes_count / lifetime_installs_count * 100, 2)
                        if lifetime_installs_count
                        else 0.0
                    ),
                    "lifetime_installs": lifetime_installs_count,
                    "lifetime_upvotes": lifetime_upvotes_count,
                    "counter_installs": counter_installs,
                    "counter_upvotes": counter_upvotes,
                    "last_used_at": _iso(last_used_at),
                    "active": _int(installs.get("inserts", 0)) > 0 or _int(inserts.get("uses", 0)) > 0,
                    "stale": (
                        not unused
                        and age_days >= STALE_AFTER_DAYS
                        and _int(installs.get("inserts", 0)) == 0
                        and _int(inserts.get("uses", 0)) == 0
                    ),
                    "unused": unused,
                    "suppression_users": max(
                        users,
                        counter_installs,
                        counter_upvotes,
                        _int(lifetime_insert.get("users", 0)),
                    ),
                }
            )

        tombstone_rows = (
            await db.execute(
                select(UsageAnalytics.event_metadata, UsageAnalytics.created_at)
                .where(
                    UsageAnalytics.action == SNIPPET_DELETE_ACTION,
                    UsageAnalytics.created_at >= start_at,
                    UsageAnalytics.created_at < end_at,
                )
                .order_by(UsageAnalytics.created_at.asc())
            )
        ).all()
        deleted_rows: dict[str, dict[str, Any]] = {}
        for tombstone_row in tombstone_rows:
            metadata = tombstone_row.event_metadata or {}
            if not isinstance(metadata, dict):
                continue
            snippet_id = _try_uuid(metadata.get("snippet_id"))
            if snippet_id is None or snippet_id in snippet_ids:
                continue
            title = metadata.get("title")
            row_category = metadata.get("category")
            if categories and (not isinstance(row_category, str) or row_category.lower() not in categories):
                continue
            row_official = bool(metadata.get("is_official", False))
            if official is not None and row_official is not official:
                continue
            if snippet_filter and snippet_id != snippet_filter:
                continue
            installs_count = _int(metadata.get("installs_count"))
            upvotes_count = _int(metadata.get("upvotes_count"))
            users_count = _int(metadata.get("users_count"))
            if users_count <= 0:
                users_count = max(installs_count, upvotes_count)
            created_at = _parse_dt(metadata.get("created_at"))
            deleted_at = tombstone_row.created_at
            age_days = max(0, (end_day - created_at.date()).days) if created_at else 0
            unused = installs_count == 0 and upvotes_count == 0
            deleted_rows[snippet_id] = {
                "snippet_id": snippet_id,
                "title": title if isinstance(title, str) and title.strip() else None,
                "category": row_category if isinstance(row_category, str) else None,
                "is_official": row_official,
                "deleted": True,
                "deleted_at": _iso(deleted_at),
                "created_at": _iso(created_at),
                "age_days": age_days,
                "users": users_count,
                "active_users": 0,
                "installers": 0,
                "inserts": 0,
                "uses": 0,
                "upvotes": upvotes_count,
                "upvote_ratio": (round(upvotes_count / installs_count * 100, 2) if installs_count else 0.0),
                "lifetime_installs": installs_count,
                "lifetime_upvotes": upvotes_count,
                "counter_installs": installs_count,
                "counter_upvotes": upvotes_count,
                "last_used_at": None,
                "active": False,
                "stale": False,
                "unused": unused,
                "suppression_users": max(users_count, installs_count, upvotes_count),
            }
        rows.extend(deleted_rows.values())

        filtered_rows = [row for row in rows if _status_matches(row, status)]
        visible_rows: list[dict[str, Any]] = []
        suppressed_rows: list[dict[str, Any]] = []
        for row in filtered_rows:
            suppression_users = _int(row.get("suppression_users", row["users"]))
            # Zero-user rows identify nobody, so an unused item remains
            # actionable for operators.  Any actual cohort below the floor is
            # suppressed instead of exposed as a one-to-four-user row.
            if suppression_users > 0 and suppression_users < MIN_LIBRARY_USERS:
                suppressed_rows.append(row)
            else:
                visible_rows.append(row)

        visible_rows.sort(
            key=lambda row: (
                -_int(row["uses"]),
                -_int(row["inserts"]),
                -_int(row["upvotes"]),
                -_int(row["users"]),
                row["title"] or row["snippet_id"],
            )
        )
        for index, row in enumerate(visible_rows, start=1):
            row["rank"] = index

        def _sum(source: list[dict[str, Any]], field: str) -> int:
            return sum(_int(row.get(field)) for row in source)

        source_installs = _sum(filtered_rows, "inserts")
        source_uses = _sum(filtered_rows, "uses")
        source_upvotes = _sum(filtered_rows, "upvotes")
        visible_installs = _sum(visible_rows, "inserts")
        visible_uses = _sum(visible_rows, "uses")
        visible_upvotes = _sum(visible_rows, "upvotes")
        suppressed_installs = source_installs - visible_installs
        suppressed_uses = source_uses - visible_uses
        suppressed_upvotes = source_upvotes - visible_upvotes
        visible_lifetime_installs = _sum(visible_rows, "lifetime_installs")

        macro_summary, macro_suppressed = await self._macro_summary(
            db,
            start_at=start_at,
            end_at=end_at,
            stale_cutoff=end_at - timedelta(days=STALE_AFTER_DAYS),
        )

        now = datetime.now(timezone.utc)
        return {
            "days": selected_range_days,
            "start_date": start_day.isoformat(),
            "end_date": end_day.isoformat(),
            "timezone": "UTC",
            "date_range": {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "days": selected_range_days,
                "timezone": "UTC",
            },
            "filters": {
                "days": selected_range_days,
                "start_date": start_day.isoformat(),
                "end_date": end_day.isoformat(),
                "category": categories or None,
                "status": status,
                "official": official,
                "snippet": snippet_filter,
                "timezone": "UTC",
            },
            "minimum_users": MIN_LIBRARY_USERS,
            "stale_after_days": STALE_AFTER_DAYS,
            "candidate_snippets": len(filtered_rows),
            "suppressed": bool(filtered_rows) and not visible_rows,
            "suppressed_snippets": len(suppressed_rows),
            "ranking": visible_rows,
            "macro_summary": macro_summary,
            "macro_suppressed": macro_suppressed,
            "totals": {
                "snippets": len(visible_rows),
                "suppressed_snippets": len(suppressed_rows),
                "installs": visible_installs,
                "uses": visible_uses,
                "upvotes": visible_upvotes,
                "lifetime_installs": visible_lifetime_installs,
                "lifetime_upvotes": _sum(visible_rows, "lifetime_upvotes"),
                "active_snippets": sum(1 for row in visible_rows if row["active"]),
                "stale_snippets": sum(1 for row in visible_rows if row["stale"]),
                "unused_snippets": sum(1 for row in visible_rows if row["unused"]),
                "deleted_snippets": sum(1 for row in visible_rows if row["deleted"]),
                "official_snippets": sum(1 for row in visible_rows if row["is_official"]),
                "upvote_ratio": (
                    round(visible_upvotes / visible_lifetime_installs * 100, 2) if visible_lifetime_installs else 0.0
                ),
            },
            "reconciliation": {
                "source": "snippets,snippet_installs,snippet_upvotes,user_macros,usage_analytics",
                "candidate_snippets": len(filtered_rows),
                "visible_snippets": len(visible_rows),
                "suppressed_snippets": len(suppressed_rows),
                "source_installs": source_installs,
                "visible_installs": visible_installs,
                "suppressed_installs": suppressed_installs,
                "source_uses": source_uses,
                "visible_uses": visible_uses,
                "suppressed_uses": suppressed_uses,
                "source_upvotes": source_upvotes,
                "visible_upvotes": visible_upvotes,
                "suppressed_upvotes": suppressed_upvotes,
                "counter_installs": _sum(filtered_rows, "counter_installs"),
                "lifetime_install_rows": _sum(filtered_rows, "lifetime_installs"),
                "counter_upvotes": _sum(filtered_rows, "counter_upvotes"),
                "lifetime_upvote_rows": _sum(filtered_rows, "lifetime_upvotes"),
                "counter_install_drift": _sum(filtered_rows, "counter_installs")
                - _sum(filtered_rows, "lifetime_installs"),
                "counter_upvote_drift": _sum(filtered_rows, "counter_upvotes")
                - _sum(filtered_rows, "lifetime_upvotes"),
                "reconciled": (
                    visible_installs + suppressed_installs == source_installs
                    and visible_uses + suppressed_uses == source_uses
                    and visible_upvotes + suppressed_upvotes == source_upvotes
                ),
                "macro_source": "user_macros,usage_analytics.macro_use",
                "macro_values_suppressed": macro_suppressed,
            },
            "definitions": {
                "users": (
                    "Distinct lifetime users across current installs, upvotes and "
                    "recorded insert events. Used for the five-user suppression floor."
                ),
                "active_users": ("Distinct users with an install or insert event inside the selected range."),
                "installs": "snippet_installs rows created inside the selected range.",
                "uses": (
                    "Recorded snippet insert events inside the selected range. "
                    "Older inserts predate this event and still appear as installs."
                ),
                "upvotes": (
                    "snippet_upvotes has no timestamp, so upvotes and upvote_ratio "
                    "are lifetime counters, not date-bounded."
                ),
                "upvote_ratio": "Lifetime upvotes divided by lifetime install rows.",
                "stale": (
                    f"No install or insert activity in range and at least {STALE_AFTER_DAYS} "
                    "days old, with historical adoption."
                ),
                "unused": "No recorded install, insert, or upvote activity at all.",
                "deleted": (
                    "A server-written aggregate tombstone from a hard snippet delete, selected by "
                    "deletion time in the range. Only id, title, category, counters and timestamps "
                    "are retained; the body, description, tags and author are not."
                ),
                "macro_summary": (
                    "Macro adoption is aggregate-only because each macro has one owner. "
                    "The block is omitted when fewer than five owners exist."
                ),
            },
            "generated_at": now.isoformat(),
        }

    async def _macro_summary(
        self,
        db: AsyncSession,
        *,
        start_at: datetime,
        end_at: datetime,
        stale_cutoff: datetime,
    ) -> tuple[Optional[dict[str, Any]], bool]:
        macro_rows = (
            await db.execute(
                select(
                    UserMacro.id,
                    UserMacro.user_id,
                    UserMacro.script,
                    UserMacro.created_at,
                    UserMacro.updated_at,
                ).where(UserMacro.created_at < end_at)
            )
        ).all()
        owners = {str(row.user_id) for row in macro_rows}
        if len(owners) < MIN_LIBRARY_USERS:
            return None, bool(macro_rows)

        macro_ids = [str(row.id) for row in macro_rows]
        range_use_events = 0
        range_used_ids: set[str] = set()
        active_owners: set[str] = set()
        last_used_at: Optional[datetime] = None
        lifetime_used_ids: set[str] = set()
        if macro_ids:
            rows = (
                await db.execute(
                    select(
                        _MACRO_ID.label("macro_id"),
                        UsageAnalytics.user_id.label("user_id"),
                        func.count(UsageAnalytics.id).label("events"),
                        func.max(UsageAnalytics.created_at).label("last_at"),
                    )
                    .where(
                        UsageAnalytics.action == MACRO_USE_ACTION,
                        UsageAnalytics.created_at >= start_at,
                        UsageAnalytics.created_at < end_at,
                        _MACRO_ID.in_(macro_ids),
                    )
                    .group_by(_MACRO_ID, UsageAnalytics.user_id)
                )
            ).all()
            for row in rows:
                if row.macro_id is None:
                    continue
                macro_id = str(row.macro_id)
                range_used_ids.add(macro_id)
                range_use_events += _int(row.events)
                if row.user_id is not None:
                    active_owners.add(str(row.user_id))
                if row.last_at is not None and (last_used_at is None or row.last_at > last_used_at):
                    last_used_at = row.last_at

            rows = (
                await db.execute(
                    select(_MACRO_ID.label("macro_id"))
                    .where(
                        UsageAnalytics.action == MACRO_USE_ACTION,
                        _MACRO_ID.in_(macro_ids),
                    )
                    .distinct()
                )
            ).all()
            lifetime_used_ids = {str(row.macro_id) for row in rows if row.macro_id is not None}

        total = len(macro_rows)
        script_macros = sum(1 for row in macro_rows if row.script is not None)
        created_in_range = sum(1 for row in macro_rows if row.created_at is not None and row.created_at >= start_at)
        updated_in_range = sum(
            1
            for row in macro_rows
            if row.updated_at is not None and row.updated_at >= start_at and row.updated_at < end_at
        )
        stale_macros = sum(
            1
            for row in macro_rows
            if row.created_at is not None and row.created_at < stale_cutoff and str(row.id) not in range_used_ids
        )
        unused_macros = sum(1 for row in macro_rows if str(row.id) not in lifetime_used_ids)
        return (
            {
                "total_macros": total,
                "script_macros": script_macros,
                "recorded_macros": total - script_macros,
                "owners": len(owners),
                "created_in_range": created_in_range,
                "updated_in_range": updated_in_range,
                "used_macros": len(range_used_ids),
                "use_events": range_use_events,
                "active_owners": len(active_owners),
                "unused_macros": unused_macros,
                "stale_macros": stale_macros,
                "last_used_at": _iso(last_used_at),
            },
            False,
        )

    def to_csv(self, result: dict[str, Any]) -> str:
        """Render the already-suppressed aggregate ranking as CSV."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for row in result.get("ranking", []):
            writer.writerow([_safe_csv_cell(row.get(_CSV_SOURCE_FIELDS.get(column, column))) for column in CSV_COLUMNS])
        return buffer.getvalue()


admin_content_library_service = AdminContentLibraryService()
