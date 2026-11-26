"""Privacy-safe client linter telemetry (issue #2148).

The browser linter never sends LaTeX source, line text, messages, document ids
or per-user history. An event may contain only an allowlisted rule id, its
bounded severity, a canonical route label, a ``fixed`` flag and an issue count.
Anything else a client submits is ignored before storage, and the route is
re-bucketed server-side into the same fixed vocabulary used by the admin report.

Storage uses the existing ``usage_analytics`` JSONB column with the dedicated
``linter_issue`` action. No schema change is required for this wave.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models

UsageAnalytics = models.UsageAnalytics

LINTER_ACTION = "linter_issue"
LINTER_RESOURCE_TYPE = "linter"

# Keep in lockstep with frontend/src/lib/latex-linter.ts. Unknown ids are
# rejected by ingestion, so a future rule must be added deliberately on both
# sides before it can be measured.
LINTER_RULE_IDS: frozenset[str] = frozenset(
    {
        "deprecated-bf",
        "deprecated-it",
        "deprecated-rm",
        "deprecated-tt",
        "wrong-quotes",
        "redundant-space",
        "double-dollar",
        "over-command",
        "multicol-ats-risk",
        "fontawesome-ats-risk",
        "tabular-layout",
        "missing-glyphtounicode",
        "hyperref-order",
        "missing-label",
        "duplicate-label",
    }
)

LINTER_SEVERITIES: frozenset[str] = frozenset({"error", "warning", "info"})

# Canonical route labels. A caller may submit a dynamic browser path; only the
# placeholder form below can be stored or returned.
_STATIC_ROUTES = frozenset(
    {
        "/",
        "/try",
        "/templates",
        "/dashboard",
        "/workspace",
        "/workspaces",
        "/login",
        "/signup",
        "/billing",
        "/byok",
        "/settings",
        "/tracker",
    }
)
_ROUTE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^/workspace/[^/]+/edit/?$"), "/workspace/:resumeId/edit"),
    (re.compile(r"^/workspace/[^/]+/optimize/?$"), "/workspace/:resumeId/optimize"),
    (re.compile(r"^/workspace/[^/]+/cover-letter/?$"), "/workspace/:resumeId/cover-letter"),
    (re.compile(r"^/workspace/[^/]+/career/?$"), "/workspace/:resumeId/career"),
    (re.compile(r"^/workspace/[^/]+/batch-tailor/?$"), "/workspace/:resumeId/batch-tailor"),
    (re.compile(r"^/workspaces/[^/]+/recruiter/?$"), "/workspaces/:workspaceId/recruiter"),
    (re.compile(r"^/workspaces/[^/]+/?$"), "/workspaces/:workspaceId"),
    (re.compile(r"^/workspace/[^/]+/?$"), "/workspace/:resumeId"),
)
_CANONICAL_DYNAMIC_ROUTES = frozenset(label for _pattern, label in _ROUTE_PATTERNS)
UNKNOWN_ROUTE = "/other"
MIN_GROUP_SIZE = 5
MAX_RANGE_DAYS = 366
MAX_EVENTS_PER_REQUEST = 25
MAX_ISSUE_COUNT = 10_000
MAX_REPORT_ROWS = 100_000

_ROUTE_SQL_PATTERN = re.compile(r"^/?[A-Za-z0-9_.:/~-]{0,127}$")


def sanitize_linter_route(value: Any) -> str:
    """Return a fixed route label, never a raw client path with identifiers."""

    if not isinstance(value, str):
        return UNKNOWN_ROUTE
    route = value.strip().split("?", 1)[0].split("#", 1)[0][:128]
    if not route or not _ROUTE_SQL_PATTERN.fullmatch(route):
        return UNKNOWN_ROUTE
    if not route.startswith("/"):
        route = f"/{route}"
    if route in _STATIC_ROUTES or route in _CANONICAL_DYNAMIC_ROUTES:
        return route
    for pattern, label in _ROUTE_PATTERNS:
        if pattern.fullmatch(route):
            return label
    return UNKNOWN_ROUTE


def coerce_issue_count(value: Any) -> int | None:
    """Accept only a bounded positive integer; bool is not an issue count."""

    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 1 or value > MAX_ISSUE_COUNT:
        return None
    return value


def normalize_linter_event(
    *,
    rule_id: Any,
    severity: Any,
    route: Any,
    fixed: Any,
    issue_count: Any,
) -> dict[str, Any] | None:
    """Build the exact allowlisted storage payload, or return ``None``."""

    if not isinstance(rule_id, str) or rule_id not in LINTER_RULE_IDS:
        return None
    if not isinstance(severity, str) or severity not in LINTER_SEVERITIES:
        return None
    if not isinstance(fixed, bool):
        return None
    count = coerce_issue_count(issue_count)
    if count is None:
        return None
    return {
        "rule_id": rule_id,
        "severity": severity,
        "route": sanitize_linter_route(route),
        "fixed": fixed,
        "issue_count": count,
    }


def dedupe_events(events: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Drop duplicates inside one client batch.

    Identical rule/severity/route/fixed/count tuples are one observation. The
    client also dedupes repeated lint runs over a rolling window.
    """

    seen: set[tuple[str, str, str, bool, int]] = set()
    fresh: list[dict[str, Any]] = []
    duplicates = 0
    for event in events:
        key = (
            event["rule_id"],
            event["severity"],
            event["route"],
            event["fixed"],
            event["issue_count"],
        )
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        fresh.append(event)
    return fresh, duplicates


async def record_linter_events(
    db: AsyncSession,
    events: Sequence[Mapping[str, Any]],
    *,
    user_id: str | None,
) -> dict[str, int]:
    """Validate, deduplicate and append linter events to ``usage_analytics``.

    ``user_id`` is derived from the authenticated session by the route, never
    from the request body. IP address and user agent are deliberately not
    stored for this event family.
    """

    normalized: list[dict[str, Any]] = []
    rejected = 0
    for raw in events:
        event = normalize_linter_event(
            rule_id=raw.get("rule_id"),
            severity=raw.get("severity"),
            route=raw.get("route"),
            fixed=raw.get("fixed"),
            issue_count=raw.get("issue_count"),
        )
        if event is None:
            rejected += 1
            continue
        normalized.append(event)

    fresh, duplicates = dedupe_events(normalized)
    if fresh:
        for event in fresh:
            db.add(
                UsageAnalytics(
                    user_id=user_id,
                    action=LINTER_ACTION,
                    resource_type=LINTER_RESOURCE_TYPE,
                    event_metadata=event,
                    ip_address=None,
                    user_agent=None,
                )
            )
        await db.commit()

    return {
        "accepted": len(fresh),
        "rejected": rejected,
        "deduplicated": duplicates,
    }


def _identity(user_id: Any, device_fingerprint: Any) -> str | None:
    if isinstance(user_id, str) and user_id:
        return f"u:{user_id}"
    if isinstance(device_fingerprint, str) and device_fingerprint:
        return f"d:{device_fingerprint}"
    return None


@dataclass
class _RouteBucket:
    issues: int = 0
    users: set[str] = field(default_factory=set)


@dataclass
class _RuleBucket:
    severity: str = "unknown"
    detections: int = 0
    issues_detected: int = 0
    fixes_applied: int = 0
    issues_fixed: int = 0
    users: set[str] = field(default_factory=set)
    routes: dict[str, _RouteBucket] = field(default_factory=dict)

    def add(self, event: Mapping[str, Any], identity: str | None) -> None:
        count = int(event["issue_count"])
        if self.severity == "unknown":
            self.severity = str(event["severity"])
        if identity is not None:
            self.users.add(identity)
        if event["fixed"] is True:
            self.fixes_applied += 1
            self.issues_fixed += count
        else:
            self.detections += 1
            self.issues_detected += count
        route = str(event["route"])
        route_bucket = self.routes.setdefault(route, _RouteBucket())
        if event["fixed"] is not True:
            route_bucket.issues += count
        if identity is not None:
            route_bucket.users.add(identity)


def _fix_rate_pct(issues_fixed: int, issues_detected: int) -> float:
    """Share of detected issues that also have an applied fix event.

    Fix events are recorded by the browser when a user applies a single or bulk
    fix. Both counts are issue counts, so the rate is capped at 100 even if a
    user applies a fix more than once.
    """

    if issues_detected <= 0:
        return 0.0
    return round(min(issues_fixed, issues_detected) / issues_detected * 100, 2)


def _day_key(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).date().isoformat()


class AdminLinterRulesService:
    """Aggregate-only rule frequency, fix rate and daily trend report."""

    async def snapshot(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        bounded_days = max(1, min(int(days), MAX_RANGE_DAYS))
        start_at = current - timedelta(days=bounded_days)
        end_at = current

        rows = (
            await db.execute(
                select(
                    UsageAnalytics.user_id,
                    UsageAnalytics.device_fingerprint,
                    UsageAnalytics.event_metadata,
                    UsageAnalytics.created_at,
                )
                .where(
                    UsageAnalytics.action == LINTER_ACTION,
                    UsageAnalytics.created_at >= start_at,
                    UsageAnalytics.created_at < end_at,
                )
                .order_by(UsageAnalytics.created_at.asc())
                .limit(MAX_REPORT_ROWS + 1)
            )
        ).all()
        truncated = len(rows) > MAX_REPORT_ROWS
        rows = rows[:MAX_REPORT_ROWS]

        by_rule: dict[str, _RuleBucket] = {}
        by_day: dict[str, _RuleBucket] = {}
        all_users: set[str] = set()
        events = 0
        invalid_rows = 0

        for user_id, device_fingerprint, metadata, created_at in rows:
            if not isinstance(metadata, Mapping):
                invalid_rows += 1
                continue
            event = normalize_linter_event(
                rule_id=metadata.get("rule_id"),
                severity=metadata.get("severity"),
                route=metadata.get("route"),
                fixed=metadata.get("fixed"),
                issue_count=metadata.get("issue_count"),
            )
            if event is None or not isinstance(created_at, datetime):
                invalid_rows += 1
                continue

            identity = _identity(user_id, device_fingerprint)
            if identity is not None:
                all_users.add(identity)
            events += 1
            by_rule.setdefault(str(event["rule_id"]), _RuleBucket()).add(event, identity)
            by_day.setdefault(_day_key(created_at), _RuleBucket()).add(event, identity)

        suppressed = events > 0 and len(all_users) < MIN_GROUP_SIZE

        if suppressed:
            summary: dict[str, Any] = {
                "events": None,
                "issues_detected": None,
                "issues_fixed": None,
                "fix_rate_pct": None,
                "rules_seen": None,
                "distinct_users": None,
            }
            rule_rows: list[dict[str, Any]] = []
            top_noisy: list[dict[str, Any]] = []
            trend: list[dict[str, Any]] = []
        else:
            total_detected = sum(bucket.issues_detected for bucket in by_rule.values())
            total_fixed = sum(bucket.issues_fixed for bucket in by_rule.values())
            summary = {
                "events": events,
                "issues_detected": total_detected,
                "issues_fixed": total_fixed,
                "fix_rate_pct": _fix_rate_pct(total_fixed, total_detected),
                "rules_seen": len(by_rule),
                "distinct_users": len(all_users),
            }
            rule_rows = []
            for rule_id, bucket in by_rule.items():
                if len(bucket.users) < MIN_GROUP_SIZE:
                    continue
                visible_routes: list[dict[str, Any]] = []
                suppressed_routes = 0
                for route, route_bucket in bucket.routes.items():
                    if len(route_bucket.users) < MIN_GROUP_SIZE:
                        suppressed_routes += 1
                        continue
                    visible_routes.append(
                        {
                            "route": route,
                            "issues_detected": route_bucket.issues,
                            "users": len(route_bucket.users),
                        }
                    )
                visible_routes.sort(
                    key=lambda item: (-item["issues_detected"], item["route"])
                )
                rule_rows.append(
                    {
                        "rule_id": rule_id,
                        "severity": bucket.severity,
                        "frequency": bucket.detections,
                        "issues_detected": bucket.issues_detected,
                        "fixes_applied": bucket.fixes_applied,
                        "issues_fixed": bucket.issues_fixed,
                        "fix_rate_pct": _fix_rate_pct(
                            bucket.issues_fixed, bucket.issues_detected
                        ),
                        "users": len(bucket.users),
                        "share_pct": round(
                            (bucket.issues_detected / total_detected * 100)
                            if total_detected
                            else 0.0,
                            2,
                        ),
                        "top_routes": visible_routes[:5],
                        "suppressed_routes": suppressed_routes,
                    }
                )
            rule_rows.sort(
                key=lambda item: (
                    -item["issues_detected"],
                    -item["frequency"],
                    item["rule_id"],
                )
            )
            top_noisy = rule_rows[:5]
            trend = []
            for day, bucket in sorted(by_day.items()):
                if len(bucket.users) < MIN_GROUP_SIZE:
                    continue
                trend.append(
                    {
                        "date": day,
                        "frequency": bucket.detections,
                        "issues_detected": bucket.issues_detected,
                        "issues_fixed": bucket.issues_fixed,
                        "fix_rate_pct": _fix_rate_pct(
                            bucket.issues_fixed, bucket.issues_detected
                        ),
                    }
                )

        suppressed_rules = max(0, len(by_rule) - len(rule_rows))
        suppressed_days = len(by_day) if suppressed else max(0, len(by_day) - len(trend))

        return {
            "days": bounded_days,
            "period": {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "timezone": "UTC",
            },
            "minimum_users": MIN_GROUP_SIZE,
            "suppressed": suppressed,
            "suppression": {
                "minimum_users": MIN_GROUP_SIZE,
                "rule": "Hide a rule, route or day with fewer than 5 distinct users.",
                "suppressed_rules": suppressed_rules,
                "suppressed_days": suppressed_days,
                "suppressed_events_in_rows": suppressed,
            },
            "summary": summary,
            "rules": rule_rows,
            "top_noisy_rules": top_noisy,
            "trend": trend,
            "reconciliation": {
                "events": events if not suppressed else None,
                "invalid_rows": invalid_rows,
                "truncated": truncated,
                "max_rows": MAX_REPORT_ROWS,
            },
            "privacy": {
                "aggregate_only": True,
                "per_user_rows": False,
                "stored_fields": [
                    "rule_id",
                    "severity",
                    "route",
                    "fixed",
                    "issue_count",
                ],
                "content_fields_excluded": [
                    "LaTeX source",
                    "line text",
                    "lint messages",
                    "document or resume ids",
                    "account identity in responses",
                ],
            },
            "notes": [
                "Frequency counts lint runs in which a rule was detected; issues_detected sums occurrence counts.",
                "Fix rate is issues_fixed / issues_detected, capped at 100%.",
                "Routes are canonical labels re-derived on the server; raw paths and ids are never stored.",
                "Cohorts with fewer than 5 distinct users are suppressed; no per-user history is returned.",
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


admin_linter_rules_service = AdminLinterRulesService()
