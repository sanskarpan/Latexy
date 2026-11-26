"""Privacy-safe integration adoption and failure analytics (issue #2081).

Data boundary
-------------
Events are written to the existing ``usage_analytics`` JSONB column. A stored
event contains only a provider enum, a normalized plan family, an optional
operation/error/disconnect bucket, and never an OAuth token, refresh token,
email, filename, account handle, provider error body, IP address or user-agent
string. The report reads integration events and the server-owned connection
columns (``users.github_access_token``, ``users.dropbox_access_token``, and the
encrypted integration entries in ``users.user_metadata``) and joins them only
in aggregate. Per-user histories are never selected for display.

Reconciliation
--------------
Current connected accounts always come from the token/status columns rather
than telemetry. A provider with token rows but no telemetry in the period is
labelled ``missing_telemetry``; telemetry with no current rows is labelled
``no_current_connections``. ``resumes.github_sync_enabled`` and
``resumes.dropbox_sync_enabled`` provide the linked-resource reconciliation for
the two providers that persist per-resume sync state.

Suppression
-----------
A provider, plan, or report cohort with 1-4 distinct users is never published.
Counts and rates for that cohort become ``null`` and the hidden cell names are
returned. Zero is always safe to publish. When any provider cohort is hidden,
the report summary is withheld too so the hidden cohort cannot be recovered by
subtracting visible providers. A hidden plan cohort withholds that provider's
entire plan breakdown.
"""

from __future__ import annotations

import inspect
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping

import httpx
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES, resolve_plan_family
from ..core.logging import get_logger
from ..database import models
from .google_drive_service import GOOGLE_DRIVE_SCOPE

logger = get_logger(__name__)

UsageAnalytics = models.UsageAnalytics
User = models.User
Resume = models.Resume

INTEGRATION_CONNECT_STARTED = "connect_started"
INTEGRATION_CONNECTED = "connected"
INTEGRATION_DISCONNECTED = "disconnected"
INTEGRATION_SYNC_SUCCEEDED = "sync_succeeded"
INTEGRATION_SYNC_FAILED = "sync_failed"
INTEGRATION_ACTIONS: tuple[str, ...] = (
    INTEGRATION_CONNECT_STARTED,
    INTEGRATION_CONNECTED,
    INTEGRATION_DISCONNECTED,
    INTEGRATION_SYNC_SUCCEEDED,
    INTEGRATION_SYNC_FAILED,
)
INTEGRATION_RESOURCE_TYPE = "integration"

PROVIDERS: tuple[str, ...] = (
    "github",
    "dropbox",
    "google_drive",
    "zotero",
    "mendeley",
)
PROVIDER_LABELS: dict[str, str] = {
    "github": "GitHub",
    "dropbox": "Dropbox",
    "google_drive": "Google Drive",
    "zotero": "Zotero",
    "mendeley": "Mendeley",
}
PROVIDER_CONNECTION_SOURCES: dict[str, str] = {
    "github": "users:github_connection",
    "dropbox": "users:dropbox_connection",
    "google_drive": "users:google_drive_grant",
    "zotero": "users:zotero_grant",
    "mendeley": "users:mendeley_grant",
}
PROVIDER_SYNC_SOURCES: dict[str, str | None] = {
    "github": "resumes:github_sync_status",
    "dropbox": "resumes:dropbox_sync_status",
    "google_drive": None,
    "zotero": None,
    "mendeley": None,
}

OPERATIONS: tuple[str, ...] = (
    "connect",
    "push",
    "pull",
    "import",
    "export",
    "enable",
    "collections",
    "unknown",
)
DISCONNECT_REASONS: tuple[str, ...] = (
    "user_requested",
    "grant_invalid",
    "reauth_replaced",
    "unknown",
)
DISCONNECT_REASON_LABELS: dict[str, str] = {
    "user_requested": "User requested",
    "grant_invalid": "Grant already invalid",
    "reauth_replaced": "Replaced by reauthorization",
    "unknown": "Unknown",
}
ERROR_CLASSES: tuple[str, ...] = (
    "auth",
    "permission",
    "rate_limited",
    "not_found",
    "conflict",
    "invalid_request",
    "invalid_response",
    "payload_too_large",
    "provider_rejected",
    "provider_unavailable",
    "network",
    "timeout",
    "unknown",
)
ERROR_CLASS_LABELS: dict[str, str] = {
    "auth": "Authentication",
    "permission": "Permission denied",
    "rate_limited": "Rate limited",
    "not_found": "Not found",
    "conflict": "Conflict",
    "invalid_request": "Invalid request",
    "invalid_response": "Invalid provider response",
    "payload_too_large": "Payload too large",
    "provider_rejected": "Provider rejected",
    "provider_unavailable": "Provider unavailable",
    "network": "Network error",
    "timeout": "Timeout",
    "unknown": "Unknown",
}
TELEMETRY_STATE_LABELS: dict[str, str] = {
    "ok": "Telemetry present",
    "missing_telemetry": "Telemetry missing",
    "no_current_connections": "No current connections",
    "no_activity": "No activity",
    "suppressed": "Suppressed",
}

MIN_GROUP_SIZE = 5
MAX_RANGE_DAYS = 366
MAX_EVENT_ROWS = 200_000
MAX_CONNECTION_ROWS = 200_000
UNKNOWN = "unknown"

_PLAN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")


def normalize_plan(value: Any) -> str:
    """Map an account plan/SKU onto stable, bounded plan family names."""

    if not isinstance(value, str):
        return "free"
    normalized = value.strip().lower()
    if not normalized:
        return "free"
    if normalized in PLAN_FAMILY_ALIASES:
        return resolve_plan_family(normalized)
    return normalized[:32]


def normalize_plan_filter(value: str | None) -> str | None:
    """Validate an optional admin plan filter and return its normalized family."""

    if value is None or value == "":
        return None
    raw = str(value).strip().lower()
    if _PLAN_PATTERN.fullmatch(raw) is None:
        raise ValueError("plan must be a bounded lowercase plan identifier")
    return normalize_plan(raw)


def normalize_provider(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in PROVIDERS else None


def normalize_provider_filter(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    normalized = str(value).strip().lower()
    return normalized if normalized in PROVIDERS else None


def _normalize_operation(value: Any) -> str:
    if isinstance(value, str) and value.strip().lower() in OPERATIONS:
        return value.strip().lower()
    return UNKNOWN


def _normalize_error_class(value: Any) -> str:
    if isinstance(value, str) and value.strip().lower() in ERROR_CLASSES:
        return value.strip().lower()
    return UNKNOWN


def _normalize_disconnect_reason(value: Any) -> str:
    if isinstance(value, str) and value.strip().lower() in DISCONNECT_REASONS:
        return value.strip().lower()
    return UNKNOWN


def _classify_status(status: int | None) -> str:
    if status is None:
        return UNKNOWN
    if status == 401:
        return "auth"
    if status == 403:
        return "permission"
    if status == 404:
        return "not_found"
    if status == 409:
        return "conflict"
    if status == 413:
        return "payload_too_large"
    if status == 429:
        return "rate_limited"
    if status in (400, 422):
        return "invalid_request" if status == 400 else "invalid_response"
    if status >= 500:
        return "provider_unavailable"
    if 400 <= status < 500:
        return "provider_rejected"
    return UNKNOWN


def classify_integration_exception(exc: BaseException | None) -> str:
    """Return a stable error class without reading a provider response body."""

    if exc is None:
        return UNKNOWN
    if isinstance(exc, httpx.HTTPStatusError):
        return _classify_status(exc.response.status_code)
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.RequestError):
        return "network"
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return _classify_status(status)
    name = type(exc).__name__
    if name == "GitHubSyncConflict":
        return "conflict"
    if name == "BoundedReadError":
        return "payload_too_large"
    if name == "GoogleDriveProviderError":
        operation = str(getattr(exc, "operation", "") or "")
        if "response_too_large" in operation:
            return "payload_too_large"
        if "invalid_response" in operation:
            return "invalid_response"
        return UNKNOWN
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "invalid_response"
    return UNKNOWN


async def _resolve_plan(db: AsyncSession, user_id: str, plan: str | None) -> str:
    if isinstance(plan, str) and plan.strip():
        return normalize_plan(plan)
    try:
        raw = await db.scalar(select(User.subscription_plan).where(User.id == user_id))
    except Exception:
        raw = None
    return normalize_plan(raw)


async def record_integration_event(
    db: AsyncSession,
    *,
    provider: str,
    action: str,
    user_id: str | None,
    plan: str | None = None,
    operation: str | None = None,
    error_class: str | None = None,
    disconnect_reason: str | None = None,
    commit: bool = True,
) -> bool:
    """Persist one allowlisted integration event; analytics never blocks work.

    Callers on a success path pass ``commit=False`` and record just before their
    existing transaction commits, so the event shares the action's commit.
    Failure paths and actions without another write pass ``commit=True`` so the
    event survives the raised response. Only the fields named here are copied
    into the JSON payload; no caller-supplied dictionary is accepted.
    """

    effective_provider = normalize_provider(provider)
    if (
        effective_provider is None
        or action not in INTEGRATION_ACTIONS
        or not isinstance(user_id, str)
        or not user_id
        or db is None
        or not hasattr(db, "add")
    ):
        return False

    effective_plan = await _resolve_plan(db, user_id, plan)
    metadata: dict[str, Any] = {
        "provider": effective_provider,
        "plan": effective_plan,
    }
    if action in (INTEGRATION_SYNC_SUCCEEDED, INTEGRATION_SYNC_FAILED):
        metadata["operation"] = _normalize_operation(operation)
    if action == INTEGRATION_SYNC_FAILED:
        metadata["error_class"] = _normalize_error_class(error_class)
    if action == INTEGRATION_DISCONNECTED:
        metadata["disconnect_reason"] = _normalize_disconnect_reason(disconnect_reason)

    try:
        added = db.add(
            UsageAnalytics(
                user_id=user_id,
                device_fingerprint=None,
                action=action,
                resource_type=INTEGRATION_RESOURCE_TYPE,
                event_metadata=metadata,
                ip_address=None,
                user_agent=None,
            )
        )
        if inspect.isawaitable(added):
            await added
        if commit:
            await db.commit()
    except Exception as exc:
        logger.warning(
            "Integration analytics event persistence failed (%s)",
            type(exc).__name__,
        )
        if commit:
            try:
                await db.rollback()
            except Exception:
                pass
        return False
    return True


# --------------------------------------------------------------------------- #
#  Aggregate reporting                                                        #
# --------------------------------------------------------------------------- #


def _resolve_period(
    *,
    days: int,
    start_date: date | None,
    end_date: date | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    current = now or datetime.now(timezone.utc)
    if end_date is not None:
        end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    else:
        end_at = current
    if start_date is not None:
        start_at = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    else:
        start_at = end_at - timedelta(days=max(1, min(int(days), MAX_RANGE_DAYS)))
    if start_at >= end_at:
        raise ValueError("start_date must be before end_date")
    if end_at - start_at > timedelta(days=MAX_RANGE_DAYS):
        raise ValueError("date range cannot exceed 366 days")
    return start_at, end_at


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)


def _visible(value: Any, hidden: bool) -> Any:
    return None if hidden else value


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _label(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("_", " ").split())


@dataclass
class _Metrics:
    connect_started: int = 0
    connected: int = 0
    disconnected: int = 0
    sync_succeeded: int = 0
    sync_failed: int = 0
    last_activity_at: datetime | None = None
    users: set[str] = field(default_factory=set)
    disconnect_reasons: Counter[str] = field(default_factory=Counter)
    sync_error_classes: Counter[str] = field(default_factory=Counter)
    sync_failed_by_operation: Counter[str] = field(default_factory=Counter)

    def add_action(
        self,
        action: str,
        *,
        user_id: str,
        created_at: datetime,
        metadata: Mapping[str, Any],
    ) -> None:
        self.users.add(user_id)
        if self.last_activity_at is None or created_at > self.last_activity_at:
            self.last_activity_at = created_at
        if action == INTEGRATION_CONNECT_STARTED:
            self.connect_started += 1
        elif action == INTEGRATION_CONNECTED:
            self.connected += 1
        elif action == INTEGRATION_DISCONNECTED:
            self.disconnected += 1
            self.disconnect_reasons[_normalize_disconnect_reason(metadata.get("disconnect_reason"))] += 1
        elif action == INTEGRATION_SYNC_SUCCEEDED:
            self.sync_succeeded += 1
        elif action == INTEGRATION_SYNC_FAILED:
            self.sync_failed += 1
            self.sync_failed_by_operation[_normalize_operation(metadata.get("operation"))] += 1
            self.sync_error_classes[_normalize_error_class(metadata.get("error_class"))] += 1

    @property
    def event_count(self) -> int:
        return self.connect_started + self.connected + self.disconnected + self.sync_succeeded + self.sync_failed


@dataclass
class _ProviderData:
    events: _Metrics = field(default_factory=_Metrics)
    plan_events: dict[str, _Metrics] = field(default_factory=dict)
    connected_users: dict[str, str] = field(default_factory=dict)
    plan_connected_users: dict[str, set[str]] = field(default_factory=dict)
    sync_users: set[str] = field(default_factory=set)
    plan_sync_users: dict[str, set[str]] = field(default_factory=dict)
    sync_resources: int = 0
    plan_sync_resources: Counter[str] = field(default_factory=Counter)

    def users(self) -> set[str]:
        return self.events.users | set(self.connected_users) | self.sync_users

    def plan_users(self, plan: str) -> set[str]:
        return (
            self.plan_events.get(plan, _Metrics()).users
            | self.plan_connected_users.get(plan, set())
            | self.plan_sync_users.get(plan, set())
        )

    def plans(self) -> set[str]:
        return set(self.plan_events) | set(self.plan_connected_users) | set(self.plan_sync_users)


def _telemetry_state(metrics: _Metrics, connected_accounts: int) -> str:
    if metrics.event_count == 0:
        return "missing_telemetry" if connected_accounts > 0 else "no_activity"
    if connected_accounts == 0:
        return "no_current_connections"
    return "ok"


def _reason_rows(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {"reason": reason, "label": DISCONNECT_REASON_LABELS.get(reason, _label(reason)), "count": count}
        for reason, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _error_rows(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {
            "error_class": error_class,
            "label": ERROR_CLASS_LABELS.get(error_class, _label(error_class)),
            "count": count,
        }
        for error_class, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _provider_metrics(
    metrics: _Metrics,
    *,
    connected_accounts: int,
    hidden: bool,
) -> dict[str, Any]:
    return {
        "connected_accounts": _visible(connected_accounts, hidden),
        "connect_started": _visible(metrics.connect_started, hidden),
        "connected": _visible(metrics.connected, hidden),
        "disconnected": _visible(metrics.disconnected, hidden),
        "oauth_success_rate_pct": (None if hidden else _rate(metrics.connected, metrics.connect_started)),
        "sync_succeeded": _visible(metrics.sync_succeeded, hidden),
        "sync_failed": _visible(metrics.sync_failed, hidden),
        "sync_success_rate_pct": (
            None if hidden else _rate(metrics.sync_succeeded, metrics.sync_succeeded + metrics.sync_failed)
        ),
        "sync_failure_rate_pct": (
            None if hidden else _rate(metrics.sync_failed, metrics.sync_succeeded + metrics.sync_failed)
        ),
        "distinct_users": _visible(len(metrics.users), hidden),
        "last_activity_at": None if hidden else _iso(metrics.last_activity_at),
    }


def _plan_row(
    plan: str,
    *,
    data: _ProviderData,
    plan_users: set[str],
) -> dict[str, Any]:
    metrics = data.plan_events.get(plan, _Metrics())
    connected = len(data.plan_connected_users.get(plan, set()))
    return {
        "plan": plan,
        "plan_label": _label(plan),
        "connected_accounts": connected,
        "connect_started": metrics.connect_started,
        "connected": metrics.connected,
        "disconnected": metrics.disconnected,
        "oauth_success_rate_pct": _rate(metrics.connected, metrics.connect_started),
        "sync_succeeded": metrics.sync_succeeded,
        "sync_failed": metrics.sync_failed,
        "sync_success_rate_pct": _rate(metrics.sync_succeeded, metrics.sync_succeeded + metrics.sync_failed),
        "sync_failure_rate_pct": _rate(metrics.sync_failed, metrics.sync_succeeded + metrics.sync_failed),
        "sync_enabled_resources": int(data.plan_sync_resources.get(plan, 0)),
        "distinct_users": len(plan_users),
        "last_activity_at": _iso(metrics.last_activity_at),
        "telemetry_state": _telemetry_state(metrics, connected),
        "telemetry_state_label": TELEMETRY_STATE_LABELS[_telemetry_state(metrics, connected)],
    }


def _provider_row(provider: str, data: _ProviderData) -> dict[str, Any]:
    connected_accounts = len(data.connected_users)
    users = data.users()
    hidden = 0 < len(users) < MIN_GROUP_SIZE
    state = "suppressed" if hidden else _telemetry_state(data.events, connected_accounts)

    plan_rows: list[dict[str, Any]] = []
    suppressed_plan_rows = 0
    plan_suppressed = False
    for plan in sorted(data.plans()):
        plan_users = data.plan_users(plan)
        if 0 < len(plan_users) < MIN_GROUP_SIZE:
            suppressed_plan_rows += 1
            plan_suppressed = True
            continue
        plan_rows.append(_plan_row(plan, data=data, plan_users=plan_users))
    if plan_suppressed:
        # Publishing the visible plan rows would let the hidden cohort be
        # recovered by subtracting them from the provider total.
        plan_rows = []

    metrics = _provider_metrics(data.events, connected_accounts=connected_accounts, hidden=hidden)
    metrics.update(
        {
            "provider": provider,
            "label": PROVIDER_LABELS[provider],
            "suppressed": hidden,
            "distinct_users": _visible(len(users), hidden),
            "suppressed_cells": (
                [
                    "connected_accounts",
                    "connect_started",
                    "connected",
                    "disconnected",
                    "oauth_success_rate_pct",
                    "sync_succeeded",
                    "sync_failed",
                    "sync_success_rate_pct",
                    "sync_failure_rate_pct",
                    "distinct_users",
                    "last_activity_at",
                    "disconnect_reasons",
                    "sync_error_classes",
                ]
                if hidden
                else []
            ),
            "telemetry_state": state,
            "telemetry_state_label": TELEMETRY_STATE_LABELS[state],
            "disconnect_reasons": ([] if hidden else _reason_rows(data.events.disconnect_reasons)),
            "sync_error_classes": ([] if hidden else _error_rows(data.events.sync_error_classes)),
            "sync_failed_by_operation": (
                []
                if hidden
                else [
                    {
                        "operation": operation,
                        "label": _label(operation),
                        "count": count,
                    }
                    for operation, count in sorted(
                        data.events.sync_failed_by_operation.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ]
            ),
            "by_plan": plan_rows,
            "plan_breakdown_suppressed": plan_suppressed,
            "suppressed_plan_rows": suppressed_plan_rows,
            "reconciliation": {
                "current_connected_accounts": _visible(connected_accounts, hidden),
                "period_net_connection_events": _visible(data.events.connected - data.events.disconnected, hidden),
                "telemetry_users": _visible(len(data.events.users), hidden),
                "sync_enabled_resources": (
                    _visible(data.sync_resources, hidden) if PROVIDER_SYNC_SOURCES.get(provider) else None
                ),
                "connection_source": PROVIDER_CONNECTION_SOURCES[provider],
                "sync_status_source": PROVIDER_SYNC_SOURCES.get(provider),
                "telemetry_state": state,
                "telemetry_state_label": TELEMETRY_STATE_LABELS[state],
            },
        }
    )
    return metrics


async def _load_events(
    db: AsyncSession,
    *,
    start_at: datetime,
    end_at: datetime,
    plan: str | None,
    provider: str | None,
) -> list[Any]:
    stmt = select(
        UsageAnalytics.id,
        UsageAnalytics.user_id,
        UsageAnalytics.action,
        UsageAnalytics.event_metadata,
        UsageAnalytics.created_at,
    ).where(
        UsageAnalytics.action.in_(INTEGRATION_ACTIONS),
        UsageAnalytics.resource_type == INTEGRATION_RESOURCE_TYPE,
        UsageAnalytics.created_at >= start_at,
        UsageAnalytics.created_at < end_at,
    )
    if plan is not None:
        stmt = stmt.where(UsageAnalytics.event_metadata["plan"].as_string() == plan)
    if provider is not None:
        stmt = stmt.where(UsageAnalytics.event_metadata["provider"].as_string() == provider)
    stmt = stmt.order_by(UsageAnalytics.created_at, UsageAnalytics.id).limit(MAX_EVENT_ROWS + 1)
    return (await db.execute(stmt)).all()


async def _load_connections(
    db: AsyncSession,
    *,
    provider: str,
    plan: str | None,
) -> tuple[list[tuple[str, str]], bool]:
    conditions = {
        "github": and_(
            User.github_access_token.is_not(None),
            User.github_access_token != "",
        ),
        "dropbox": and_(
            User.dropbox_access_token.is_not(None),
            User.dropbox_access_token != "",
        ),
        "google_drive": and_(
            User.user_metadata["google_drive_oauth"]["access_token"].as_string().is_not(None),
            User.user_metadata["google_drive_oauth"]["access_token"].as_string() != "",
            User.user_metadata["google_drive_oauth"]["scopes"].contains([GOOGLE_DRIVE_SCOPE]),
        ),
        "zotero": and_(
            User.user_metadata["zotero_token"].as_string().is_not(None),
            User.user_metadata["zotero_token"].as_string() != "",
        ),
        "mendeley": and_(
            User.user_metadata["mendeley_token"].as_string().is_not(None),
            User.user_metadata["mendeley_token"].as_string() != "",
        ),
    }
    stmt = (
        select(User.id, User.subscription_plan)
        .where(conditions[provider])
        .order_by(User.id)
        .limit(MAX_CONNECTION_ROWS + 1)
    )
    rows = (await db.execute(stmt)).all()
    truncated = len(rows) > MAX_CONNECTION_ROWS
    if truncated:
        rows = rows[:MAX_CONNECTION_ROWS]
    parsed: list[tuple[str, str]] = []
    for user_id, raw_plan in rows:
        normalized = normalize_plan(raw_plan)
        if plan is not None and normalized != plan:
            continue
        parsed.append((str(user_id), normalized))
    return parsed, truncated


async def _load_sync_resources(
    db: AsyncSession,
    *,
    provider: str,
    plan: str | None,
) -> tuple[list[tuple[str, str]], int, bool]:
    if provider == "github":
        enabled = Resume.github_sync_enabled.is_(True)
    elif provider == "dropbox":
        enabled = Resume.dropbox_sync_enabled.is_(True)
    else:
        return [], 0, False

    stmt = (
        select(Resume.user_id, User.subscription_plan)
        .join(User, User.id == Resume.user_id)
        .where(enabled)
        .order_by(Resume.user_id)
        .limit(MAX_CONNECTION_ROWS + 1)
    )
    rows = (await db.execute(stmt)).all()
    truncated = len(rows) > MAX_CONNECTION_ROWS
    if truncated:
        rows = rows[:MAX_CONNECTION_ROWS]
    parsed: list[tuple[str, str]] = []
    for user_id, raw_plan in rows:
        normalized = normalize_plan(raw_plan)
        if plan is not None and normalized != plan:
            continue
        parsed.append((str(user_id), normalized))
    return parsed, len(parsed), truncated


async def snapshot(
    db: AsyncSession,
    *,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
    plan: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Return aggregate integration adoption, OAuth, sync and reconciliation."""

    start_at, end_at = _resolve_period(days=days, start_date=start_date, end_date=end_date)
    plan_filter = normalize_plan_filter(plan)
    provider_filter = normalize_provider_filter(provider)
    if provider is not None and provider_filter is None:
        raise ValueError("provider is not a supported integration")

    selected_providers = [provider_filter] if provider_filter is not None else list(PROVIDERS)
    provider_data: dict[str, _ProviderData] = {name: _ProviderData() for name in PROVIDERS}

    event_rows = await _load_events(
        db,
        start_at=start_at,
        end_at=end_at,
        plan=plan_filter,
        provider=provider_filter,
    )
    truncated_events = len(event_rows) > MAX_EVENT_ROWS
    if truncated_events:
        event_rows = event_rows[:MAX_EVENT_ROWS]

    invalid_rows = 0
    unattributed_events = 0
    for row_id, user_id, action, metadata, created_at in event_rows:
        if (
            not isinstance(metadata, Mapping)
            or action not in INTEGRATION_ACTIONS
            or not isinstance(created_at, datetime)
        ):
            invalid_rows += 1
            continue
        provider_key = normalize_provider(metadata.get("provider"))
        if provider_key is None:
            invalid_rows += 1
            continue
        if provider_filter is not None and provider_key != provider_filter:
            continue
        if not isinstance(user_id, str) or not user_id:
            # A deleted account leaves the row (FK SET NULL) but no identity to
            # count. It is excluded from distinct-user totals and reported as
            # unattributed instead.
            unattributed_events += 1
            continue
        plan_key = normalize_plan(metadata.get("plan"))
        if plan_filter is not None and plan_key != plan_filter:
            continue
        data = provider_data[provider_key]
        data.events.add_action(action, user_id=user_id, created_at=created_at, metadata=metadata)
        data.plan_events.setdefault(plan_key, _Metrics()).add_action(
            action, user_id=user_id, created_at=created_at, metadata=metadata
        )

    truncated_connections = False
    for name in selected_providers:
        connections, truncated = await _load_connections(db, provider=name, plan=plan_filter)
        truncated_connections = truncated_connections or truncated
        data = provider_data[name]
        for user_id, plan_key in connections:
            data.connected_users[user_id] = plan_key
            data.plan_connected_users.setdefault(plan_key, set()).add(user_id)

        sync_users, sync_count, sync_truncated = await _load_sync_resources(db, provider=name, plan=plan_filter)
        truncated_connections = truncated_connections or sync_truncated
        data.sync_resources = sync_count
        for user_id, plan_key in sync_users:
            data.sync_users.add(user_id)
            data.plan_sync_users.setdefault(plan_key, set()).add(user_id)
            data.plan_sync_resources[plan_key] += 1

    rows = [_provider_row(name, provider_data[name]) for name in selected_providers]

    visible_rows = [row for row in rows if not row["suppressed"]]
    hidden_rows = [row for row in rows if row["suppressed"]]
    all_users: set[str] = set()
    for name in selected_providers:
        all_users |= provider_data[name].users()
    summary_hidden = 0 < len(all_users) < MIN_GROUP_SIZE
    if hidden_rows:
        # Complementary suppression: with at least one provider cohort hidden,
        # publishing the all-provider totals would allow the hidden cohort to
        # be recovered by subtracting the visible provider rows.
        summary_hidden = True

    totals = _Metrics()
    for name in selected_providers:
        data = provider_data[name]
        totals.connect_started += data.events.connect_started
        totals.connected += data.events.connected
        totals.disconnected += data.events.disconnected
        totals.sync_succeeded += data.events.sync_succeeded
        totals.sync_failed += data.events.sync_failed
        if totals.last_activity_at is None or (
            data.events.last_activity_at is not None and data.events.last_activity_at > totals.last_activity_at
        ):
            totals.last_activity_at = data.events.last_activity_at

    connected_total = sum(len(provider_data[name].connected_users) for name in selected_providers)
    providers_with_connections = sum(1 for name in selected_providers if provider_data[name].connected_users)
    summary_cells = [
        "connected_accounts",
        "providers_with_connections",
        "connect_started",
        "connected",
        "disconnected",
        "oauth_success_rate_pct",
        "sync_succeeded",
        "sync_failed",
        "sync_success_rate_pct",
        "sync_failure_rate_pct",
        "distinct_users",
    ]
    summary = {
        "connected_accounts": _visible(connected_total, summary_hidden),
        "providers_with_connections": _visible(providers_with_connections, summary_hidden),
        "connect_started": _visible(totals.connect_started, summary_hidden),
        "connected": _visible(totals.connected, summary_hidden),
        "disconnected": _visible(totals.disconnected, summary_hidden),
        "oauth_success_rate_pct": (None if summary_hidden else _rate(totals.connected, totals.connect_started)),
        "sync_succeeded": _visible(totals.sync_succeeded, summary_hidden),
        "sync_failed": _visible(totals.sync_failed, summary_hidden),
        "sync_success_rate_pct": (
            None if summary_hidden else _rate(totals.sync_succeeded, totals.sync_succeeded + totals.sync_failed)
        ),
        "sync_failure_rate_pct": (
            None if summary_hidden else _rate(totals.sync_failed, totals.sync_succeeded + totals.sync_failed)
        ),
        "distinct_users": _visible(len(all_users), summary_hidden),
        "suppressed": summary_hidden,
        "suppressed_cells": sorted(summary_cells) if summary_hidden else [],
        "last_activity_at": (None if summary_hidden else _iso(totals.last_activity_at)),
        "telemetry_state": ("suppressed" if summary_hidden else _telemetry_state(totals, connected_total)),
    }

    return {
        "period": {
            "start": start_at.isoformat(),
            "end": end_at.isoformat(),
            "days": round((end_at - start_at).total_seconds() / 86_400, 2),
            "timezone": "UTC",
        },
        "filters": {
            "plan": plan_filter,
            "provider": provider_filter,
        },
        "minimum_cohort_size": MIN_GROUP_SIZE,
        "summary": summary,
        "providers": rows,
        "reconciliation": {
            "connection_rows_truncated": truncated_connections,
            "event_rows_truncated": truncated_events,
            "unattributed_events": unattributed_events,
            "invalid_rows": invalid_rows,
            "visible_providers": len(visible_rows),
            "suppressed_providers": len(hidden_rows),
            "connected_accounts_source": "token/status columns",
            "telemetry_source": "usage_analytics integration events",
        },
        "notes": [
            "Connected accounts are read from the server-owned token/status "
            "columns, not from telemetry. Integrations with current connections "
            "but no events are labelled missing_telemetry.",
            "OAuth success rate = connected events / connect_started events in "
            "the selected period. Sync failure rate = sync_failed / "
            "(sync_succeeded + sync_failed).",
            "Event payloads contain only provider, plan family, operation, "
            "stable error class and disconnect reason. OAuth tokens, refresh "
            "tokens, emails, filenames, account handles, provider error bodies, "
            "IP addresses and user-agent strings are never stored or returned.",
            "Groups with fewer than 5 distinct users are hidden. When any "
            "provider cohort is hidden, report totals are withheld; a hidden "
            "plan cohort withholds that provider's plan breakdown.",
            "Reconciliation compares current token/status rows with period "
            "net connection events and, for GitHub and Dropbox, resume sync "
            "status columns. No per-user history is exposed.",
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
