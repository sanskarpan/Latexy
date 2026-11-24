"""Signup funnel and verification metrics by server-derived auth provider.

The funnel is built from two server-owned sources:

* ``users`` / Better Auth ``account`` / ``passkey`` rows decide the provider of
  every account. A browser never supplies the provider that is attributed to an
  account, and only the six-value allowlist below is ever persisted.
* ``signup_funnel_events`` records coarse attempt, completion, verification and
  OAuth-failure counters. The table has no email, name, IP, user-agent or token
  columns, so a report cannot leak credentials or direct identifiers.

Anonymous ``signup_started``/``oauth_failure`` rows are attempted-signup
telemetry only. They carry no user id and are never joined back to an account
to assign it a provider.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database import models

logger = get_logger(__name__)

AUTH_PROVIDERS = ("email", "google", "github", "oidc", "passkey", "unknown")
SIGNUP_EVENTS = ("signup_started", "signup_completed", "email_verified", "oauth_failure")
OAUTH_FAILURE_CODES = (
    "access_denied",
    "account_not_linked",
    "callback_failed",
    "provider_error",
    "state_mismatch",
    "unknown",
)
PROVIDER_LABELS = {
    "email": "Email",
    "google": "Google",
    "github": "GitHub",
    "oidc": "Institutional SSO",
    "passkey": "Passkey",
    "unknown": "Unknown",
}
MIN_SEGMENT_SIZE = 5

# Only values already in the allowlist (plus Better Auth's "credential" name
# for password accounts) are accepted from telemetry callers. Anything else is
# bucketed to "unknown" instead of being stored verbatim.
_CLAIM_ALIASES = {
    "credential": "email",
    "email": "email",
    "google": "google",
    "github": "github",
    "oidc": "oidc",
    "passkey": "passkey",
    "unknown": "unknown",
}
_SERVER_PROVIDER_ALIASES = {
    "credential": "email",
    "credentialid": "passkey",
    "email": "email",
    "google": "google",
    "github": "github",
    "oidc": "oidc",
    "passkey": "passkey",
    "unknown": "unknown",
}

User = models.User
SignupFunnelEvent = models.SignupFunnelEvent


def normalize_provider_claim(value: Any) -> str:
    """Map an untrusted telemetry label onto the provider allowlist."""

    if value is None:
        return "unknown"
    return _CLAIM_ALIASES.get(str(value).strip().lower(), "unknown")


def provider_from_auth_id(value: Any) -> str:
    """Map a server-owned Better Auth provider id onto the allowlist.

    Google and GitHub keep their identity. Password credentials become
    ``email``. Any other provider Better Auth accepted (a generic OAuth / OIDC
    provider id) is bucketed as ``oidc``; it is never stored verbatim.
    """

    if value is None:
        return "unknown"
    raw = str(value).strip().lower()
    if not raw:
        return "unknown"
    return _SERVER_PROVIDER_ALIASES.get(raw, "oidc")


def _normalize_failure_code(value: Any) -> str:
    if value is None:
        return "unknown"
    raw = str(value).strip().lower()
    return raw if raw in OAUTH_FAILURE_CODES else "unknown"


def _pct(value: int, total: int) -> float:
    return round((value / total) * 100, 2) if total else 0.0


def _conversion(value: int, total: int) -> float:
    """A bounded conversion; anonymous attempts can be fewer than accounts."""

    return min(100.0, _pct(value, total))


def _median(values: Iterable[float]) -> float | None:
    items = list(values)
    return float(statistics.median(items)) if items else None


def _median_pair(values: Iterable[float]) -> tuple[float | None, float | None]:
    seconds = _median(values)
    if seconds is None:
        return None, None
    return round(seconds, 2), round(seconds / 86_400, 2)


async def _account_provider_map(
    db: AsyncSession, user_ids: Iterable[str]
) -> dict[str, str]:
    """Resolve providers from Better Auth's server-owned ``account`` rows."""

    ids = [str(item) for item in user_ids]
    if not ids:
        return {}
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    text(
                        'SELECT "userId", "providerId" FROM account '
                        'WHERE "userId" = ANY(:ids) '
                        'ORDER BY "createdAt" ASC NULLS LAST, id ASC'
                    ),
                    {"ids": ids},
                )
            ).all()
    except Exception as exc:  # pragma: no cover - defensive, table is migrated
        logger.warning("Signup funnel provider lookup failed (%s)", type(exc).__name__)
        return {}
    result: dict[str, str] = {}
    for user_id, provider_id in rows:
        if user_id and str(user_id) not in result:
            result[str(user_id)] = provider_from_auth_id(provider_id)
    return result


async def _passkey_user_ids(db: AsyncSession, user_ids: Iterable[str]) -> set[str]:
    ids = [str(item) for item in user_ids]
    if not ids:
        return set()
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    text('SELECT DISTINCT "userId" FROM "passkey" WHERE "userId" = ANY(:ids)'),
                    {"ids": ids},
                )
            ).all()
    except Exception:
        return set()
    return {str(row[0]) for row in rows if row[0]}


async def resolve_user_provider(db: AsyncSession, user_id: str) -> str:
    """Return the allowlisted provider for one account using server state."""

    account_map = await _account_provider_map(db, [user_id])
    resolved = account_map.get(str(user_id))
    if resolved:
        return resolved
    if str(user_id) in await _passkey_user_ids(db, [user_id]):
        return "passkey"
    return "unknown"


async def effective_provider_map(
    db: AsyncSession, users: Iterable[Mapping[str, Any] | tuple[str, str]]
) -> dict[str, str]:
    """Combine the persisted column with a live Better Auth fallback."""

    stored: dict[str, str] = {}
    for row in users:
        if isinstance(row, Mapping):
            user_id = str(row["id"])
            value = row.get("auth_provider")
        else:
            user_id, value = str(row[0]), row[1]
        stored[user_id] = provider_from_auth_id(value) if value else "unknown"

    unresolved = [user_id for user_id, provider in stored.items() if provider == "unknown"]
    account_map = await _account_provider_map(db, unresolved)
    for user_id, provider in account_map.items():
        if stored.get(user_id) == "unknown":
            stored[user_id] = provider

    still_unknown = [user_id for user_id, provider in stored.items() if provider == "unknown"]
    if still_unknown:
        for user_id in await _passkey_user_ids(db, still_unknown):
            stored[user_id] = "passkey"
    return stored


async def _insert_event(
    db: AsyncSession,
    *,
    event: str,
    provider: str,
    user_id: str | None = None,
    failure_code: str | None = None,
) -> bool:
    if event not in SIGNUP_EVENTS:
        raise ValueError("unsupported signup funnel event")
    if provider not in AUTH_PROVIDERS:
        raise ValueError("unsupported auth provider")
    stmt = (
        pg_insert(SignupFunnelEvent)
        .values(
            event=event,
            provider=provider,
            user_id=user_id,
            failure_code=failure_code,
        )
        .on_conflict_do_nothing()
    )
    result = await db.execute(stmt)
    return bool(result.rowcount)


async def record_signup_started(
    db: AsyncSession,
    *,
    user_id: str | None = None,
    provider: Any = None,
) -> str:
    """Record a signup attempt; account attribution always wins.

    When a session identifies the account, its provider is derived from server
    state and the caller's label is ignored. Anonymous attempts may carry an
    allowlisted label, but the row has no user id and is never attributed back
    to an account.
    """

    if user_id:
        stored = (
            await db.execute(select(User.auth_provider).where(User.id == user_id))
        ).scalar_one_or_none()
        resolved = provider_from_auth_id(stored) if stored else "unknown"
        if resolved == "unknown":
            resolved = await resolve_user_provider(db, user_id)
        effective = resolved
    else:
        effective = normalize_provider_claim(provider)

    await _insert_event(db, event="signup_started", provider=effective, user_id=user_id)
    await db.commit()
    return effective


async def record_oauth_failure(
    db: AsyncSession,
    *,
    provider: Any,
    failure_code: Any = None,
) -> str:
    """Count a failed OAuth attempt by allowlisted provider only.

    No tokens, email addresses, provider error descriptions or account ids are
    accepted or stored.
    """

    effective = normalize_provider_claim(provider)
    await _insert_event(
        db,
        event="oauth_failure",
        provider=effective,
        failure_code=_normalize_failure_code(failure_code),
    )
    await db.commit()
    return effective


async def record_signup_milestones(db: AsyncSession, *, user_id: str) -> dict[str, Any]:
    """Idempotently persist completion/verification for one authenticated user.

    The provider is resolved from ``users.auth_provider``/Better Auth's account
    rows/passkeys, never from the request. This is what the app calls after a
    session is established, so it also covers OAuth accounts that never submit
    the email form.
    """

    row = (
        await db.execute(
            select(
                User.id,
                User.email_verified,
                User.auth_provider,
            ).where(User.id == user_id)
        )
    ).one_or_none()
    if row is None:
        raise ValueError("user not found")

    stored = provider_from_auth_id(row.auth_provider) if row.auth_provider else "unknown"
    resolved = stored
    if resolved == "unknown":
        resolved = await resolve_user_provider(db, str(row.id))
        if resolved != "unknown":
            await db.execute(
                text(
                    "UPDATE users SET auth_provider = :provider "
                    "WHERE id = :uid AND auth_provider = 'unknown'"
                ),
                {"provider": resolved, "uid": str(row.id)},
            )

    recorded: list[str] = []
    if await _insert_event(
        db, event="signup_completed", provider=resolved, user_id=str(row.id)
    ):
        recorded.append("signup_completed")
    if bool(row.email_verified) and await _insert_event(
        db, event="email_verified", provider=resolved, user_id=str(row.id)
    ):
        recorded.append("email_verified")

    await db.commit()
    return {
        "provider": resolved,
        "email_verified": bool(row.email_verified),
        "recorded": recorded,
    }


def _event_scope_days(days: int) -> int:
    return max(1, min(int(days), 365))


async def signup_funnel(
    db: AsyncSession,
    *,
    days: int = 30,
    plan: str | None = None,
    provider: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the provider-segmented signup funnel for the selected period."""

    period_days = _event_scope_days(days)
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=period_days)

    stmt = select(
        User.id,
        User.created_at,
        User.email_verified,
        User.auth_provider,
        User.subscription_plan,
    ).where(User.created_at >= start, User.created_at <= now)
    if plan:
        stmt = stmt.where(User.subscription_plan == plan)
    user_rows = (await db.execute(stmt)).all()

    provider_map = await effective_provider_map(
        db, [(str(row.id), row.auth_provider) for row in user_rows]
    )
    provider_filter = normalize_provider_claim(provider) if provider else None

    cohort: list[dict[str, Any]] = []
    for row in user_rows:
        user_id = str(row.id)
        effective_provider = provider_map.get(user_id, "unknown")
        if provider_filter is not None and effective_provider != provider_filter:
            continue
        cohort.append(
            {
                "id": user_id,
                "created_at": row.created_at,
                "email_verified": bool(row.email_verified),
                "provider": effective_provider,
                "plan": row.subscription_plan,
            }
        )

    cohort_ids = [item["id"] for item in cohort]
    signup_times = {
        item["id"]: item["created_at"] for item in cohort if item["created_at"] is not None
    }

    started_scope = [SignupFunnelEvent.event == "signup_started"]
    started_scope.append(SignupFunnelEvent.created_at >= start)
    started_scope.append(SignupFunnelEvent.created_at <= now)
    failure_scope = [
        SignupFunnelEvent.event == "oauth_failure",
        SignupFunnelEvent.created_at >= start,
        SignupFunnelEvent.created_at <= now,
    ]
    if plan:
        # Anonymous attempt rows cannot be safely split by plan, so a
        # plan-filtered report uses only attempt rows tied to that cohort.
        started_scope.append(SignupFunnelEvent.user_id.in_(cohort_ids))
    if provider_filter is not None:
        started_scope.append(SignupFunnelEvent.provider == provider_filter)
        failure_scope.append(SignupFunnelEvent.provider == provider_filter)

    started_rows = (
        await db.execute(
            select(SignupFunnelEvent.provider, func.count(SignupFunnelEvent.id))
            .where(*started_scope)
            .group_by(SignupFunnelEvent.provider)
        )
    ).all()
    started_by_provider = {str(row[0]): int(row[1] or 0) for row in started_rows}
    started_total = sum(started_by_provider.values())

    verified_event_rows = (
        await db.execute(
            select(
                SignupFunnelEvent.user_id,
                func.min(SignupFunnelEvent.created_at),
            )
            .where(
                SignupFunnelEvent.event == "email_verified",
                SignupFunnelEvent.user_id.in_(cohort_ids),
                SignupFunnelEvent.created_at >= start,
                SignupFunnelEvent.created_at <= now,
            )
            .group_by(SignupFunnelEvent.user_id)
        )
    ).all()
    verified_at: dict[str, datetime] = {
        str(user_id): timestamp
        for user_id, timestamp in verified_event_rows
        if user_id and timestamp is not None
    }

    failure_rows = (
        await db.execute(
            select(
                SignupFunnelEvent.provider,
                SignupFunnelEvent.failure_code,
                func.count(SignupFunnelEvent.id),
            )
            .where(*failure_scope)
            .group_by(SignupFunnelEvent.provider, SignupFunnelEvent.failure_code)
        )
    ).all()
    failures_by_provider: dict[str, int] = defaultdict(int)
    failures_by_code: dict[str, int] = defaultdict(int)
    for failure_provider, failure_code, count in failure_rows:
        failures_by_provider[str(failure_provider)] += int(count or 0)
        failures_by_code[str(failure_code or "unknown")] += int(count or 0)
    failure_total = sum(failures_by_provider.values())

    cohort_by_id = {item["id"]: item for item in cohort}

    def _verified_ids(ids: Iterable[str]) -> set[str]:
        result: set[str] = set()
        for user_id in ids:
            item = cohort_by_id.get(user_id)
            if item is None:
                continue
            if item["email_verified"] or user_id in verified_at:
                result.add(user_id)
        return result

    def _verify_gaps(ids: Iterable[str]) -> list[float]:
        gaps: list[float] = []
        for user_id in ids:
            verified_timestamp = verified_at.get(user_id)
            signup_timestamp = signup_times.get(user_id)
            if verified_timestamp is None or signup_timestamp is None:
                continue
            gap = (verified_timestamp - signup_timestamp).total_seconds()
            if gap >= 0:
                gaps.append(gap)
        return gaps

    all_verified = _verified_ids(cohort_ids)
    median_seconds, median_days = _median_pair(_verify_gaps(cohort_ids))
    completed = len(cohort_ids)
    verified = len(all_verified)
    verification_rate = _pct(verified, completed)

    by_provider: list[dict[str, Any]] = []
    suppressed_providers = 0
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in cohort:
        grouped[item["provider"]].append(item["id"])

    for label, ids in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(ids) < MIN_SEGMENT_SIZE:
            suppressed_providers += 1
            continue
        segment_verified = _verified_ids(ids)
        segment_median_seconds, segment_median_days = _median_pair(_verify_gaps(ids))
        by_provider.append(
            {
                "label": label,
                "provider": label,
                "provider_label": PROVIDER_LABELS.get(label, label),
                "users": len(ids),
                "started": started_by_provider.get(label, 0),
                "completed": len(ids),
                "verified": len(segment_verified),
                "verification_rate": _pct(len(segment_verified), len(ids)),
                "conversion_start_to_complete": _conversion(
                    len(ids), started_by_provider.get(label, 0)
                ),
                "conversion_complete_to_verified": _pct(len(segment_verified), len(ids)),
                "median_seconds_to_verify": segment_median_seconds,
                "median_days_to_verify": segment_median_days,
            }
        )

    steps = [
        {
            "key": "signup_started",
            "label": "Signup started",
            "count": started_total,
            "from_previous": None,
            "from_start": 100.0 if started_total else 0.0,
            "median_seconds": None,
            "median_days": None,
        },
        {
            "key": "signup_completed",
            "label": "Signup completed",
            "count": completed,
            "from_previous": _conversion(completed, started_total),
            "from_start": _conversion(completed, started_total),
            "median_seconds": None,
            "median_days": None,
        },
        {
            "key": "email_verified",
            "label": "Email verified",
            "count": verified,
            "from_previous": _pct(verified, completed),
            "from_start": _conversion(verified, started_total),
            "median_seconds": median_seconds,
            "median_days": median_days,
        },
    ]

    return {
        "period_days": period_days,
        "cohort_size": completed,
        "steps": steps,
        "started": started_total,
        "completed": completed,
        "verified": verified,
        "verification_rate": verification_rate,
        "conversion_start_to_complete": _conversion(completed, started_total),
        "conversion_complete_to_verified": _pct(verified, completed),
        "median_seconds_to_verify": median_seconds,
        "median_days_to_verify": median_days,
        "by_provider": by_provider,
        "oauth_failures": {
            "total": failure_total,
            "by_provider": [
                {
                    "label": label,
                    "provider": label,
                    "provider_label": PROVIDER_LABELS.get(label, label),
                    "count": count,
                }
                for label, count in sorted(
                    failures_by_provider.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "by_code": [
                {"code": code, "count": count}
                for code, count in sorted(
                    failures_by_code.items(), key=lambda item: (-item[1], item[0])
                )
            ],
        },
        "suppressed_segments": {"provider": suppressed_providers},
        "minimum_segment_size": MIN_SEGMENT_SIZE,
        "provider_labels": PROVIDER_LABELS,
        "started_by_provider": [
            {
                "label": label,
                "provider": label,
                "count": count,
            }
            for label, count in sorted(
                started_by_provider.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "generated_at": now.isoformat(),
    }


class SignupFunnelService:
    """Small facade so routes/services share one instance and import path."""

    normalize_provider_claim = staticmethod(normalize_provider_claim)
    provider_from_auth_id = staticmethod(provider_from_auth_id)
    resolve_user_provider = staticmethod(resolve_user_provider)
    effective_provider_map = staticmethod(effective_provider_map)
    record_signup_started = staticmethod(record_signup_started)
    record_oauth_failure = staticmethod(record_oauth_failure)
    record_signup_milestones = staticmethod(record_signup_milestones)
    signup_funnel = staticmethod(signup_funnel)


signup_funnel_service = SignupFunnelService()
