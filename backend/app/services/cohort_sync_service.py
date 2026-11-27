"""PostHog cohort sync and fail-closed feature-flag evaluation (issue #2165).

Data boundary
-------------
A cohort row stores only bounded configuration: key, name, description,
optional tenant scope, optional opaque PostHog cohort id, freshness budget and
aggregate sync state. Membership rows store only the opaque account UUID and a
sync timestamp. No email, name, document text, prompt, token, IP address, user
agent, PostHog person payload or free-form provider error is accepted, stored or
returned.

Consent
-------
Membership is synced only from a consent-filtered PostHog cohort and no flag is
evaluated or exposed without a *current* first-party analytics grant for the
caller's opaque browser id. A denial or withdrawal therefore stops both
treatment and exposure server-side even when a membership row still exists.

Fail closed
-----------
A flag is never enabled from cohort state unless every cohort that can apply to
the caller is ``synced``, its last successful sync is inside its freshness
budget, and its synced size is at least the cohort minimum (five). A stale,
failed, never-synced or below-minimum cohort disables the mapped flag - it does
not fall back to the global flag value. A successful later sync restores
evaluation.

Tenant isolation
----------------
Tenant-scoped cohorts accept members only from that tenant (``users.
default_tenant_id`` or an active ``tenant_members`` row) and evaluation
re-checks the caller's tenant, so a stale membership row cannot cross tenants.
Platform cohorts have no tenant scope. The admin report returns tenant slugs
and aggregate size only, never member account ids.

Exposure
--------
One ``cohort_flag_exposed`` usage-analytics row is written per authenticated
subject, flag and UTC day when consent is granted. Metadata is limited to the
flag key, evaluation result, bounded reason, UTC window, mapped cohort keys and
a fixed source label. No cohort size or per-user membership is returned by the
evaluation route.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from fastapi import Request
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models
from .admin_audit_service import AdminActor, record_admin_audit
from .consent_analytics_service import CONSENT_ACTIONS, DECISION_BY_ACTION, normalize_identifier

FeatureCohort = models.FeatureCohort
FeatureCohortMember = models.FeatureCohortMember
FeatureCohortFlagMapping = models.FeatureCohortFlagMapping
FeatureFlag = models.FeatureFlag
Tenant = models.Tenant
TenantMember = models.TenantMember
UsageAnalytics = models.UsageAnalytics
User = models.User

MIN_COHORT_SIZE = 5
DEFAULT_STALE_AFTER_SECONDS = 86_400
MIN_STALE_AFTER_SECONDS = 300
MAX_STALE_AFTER_SECONDS = 604_800
MAX_SYNC_MEMBERS = 20_000
MAX_EVALUATED_FLAGS = 25
EXPOSURE_LOOKBACK_DAYS = 30

COHORT_FLAG_EXPOSED = "cohort_flag_exposed"
COHORT_FLAG_RESOURCE_TYPE = "feature_flag"
COHORT_EXPOSURE_SOURCE = "cohort_flag_evaluation"

SYNC_NEVER = "never_synced"
SYNC_OK = "synced"
SYNC_ERROR = "error"
SYNC_BELOW_MINIMUM = "below_minimum"
SYNC_STALE = "stale"

COHORT_KEY_RE = re.compile(r"^[a-z][a-z0-9][a-z0-9._-]{1,62}$")
POSTHOG_COHORT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
FLAG_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

CONSENT_BASIS = (
    "Cohort membership is sourced only from a consent-filtered PostHog cohort. "
    "Evaluation and exposure additionally require a current first-party "
    "analytics grant for the caller; a denial or withdrawal stops treatment."
)


class CohortError(Exception):
    status_code = 400
    code = "cohort_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CohortNotFound(CohortError):
    status_code = 404
    code = "cohort_not_found"


class CohortValidationError(CohortError):
    status_code = 422
    code = "cohort_invalid"


class CohortConflict(CohortError):
    status_code = 409
    code = "cohort_conflict"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clean_text(value: str | None, field: str, *, minimum: int, maximum: int) -> str:
    cleaned = " ".join((value or "").split())
    if len(cleaned) < minimum:
        raise CohortValidationError(f"{field} must be at least {minimum} characters")
    if len(cleaned) > maximum:
        raise CohortValidationError(f"{field} must be at most {maximum} characters")
    return cleaned


def _clean_cohort_key(value: Any) -> str:
    raw = str(value or "").strip()
    if COHORT_KEY_RE.fullmatch(raw) is None:
        raise CohortValidationError(
            "key must start with a lowercase letter and contain 3-64 "
            "lowercase letters, digits, dots, dashes or underscores"
        )
    return raw


def _clean_flag_key(value: Any) -> str:
    raw = str(value or "").strip()
    if FLAG_KEY_RE.fullmatch(raw) is None:
        raise CohortValidationError("flag_key is not a valid feature flag key")
    return raw


def _clean_posthog_id(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if POSTHOG_COHORT_ID_RE.fullmatch(raw) is None:
        raise CohortValidationError("posthog_cohort_id must be a bounded opaque id")
    return raw


def _clean_error_code(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if ERROR_CODE_RE.fullmatch(raw) is None:
        raise CohortValidationError("error_code must be a bounded lowercase code")
    return raw


def _clean_reason(value: str | None) -> str:
    return _clean_text(value, "reason", minimum=3, maximum=1000)


def _clean_tenant_id(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if _UUID_RE.fullmatch(raw) is None:
        raise CohortValidationError("tenant_id must be a UUID")
    return str(uuid.UUID(raw))


def _clean_user_ids(values: Iterable[Any]) -> tuple[list[str], int]:
    """Return canonical UUID strings and the count of malformed entries."""

    accepted: list[str] = []
    seen: set[str] = set()
    rejected = 0
    for value in values:
        raw = str(value or "").strip()
        if _UUID_RE.fullmatch(raw) is None:
            rejected += 1
            continue
        canonical = str(uuid.UUID(raw))
        if canonical in seen:
            continue
        seen.add(canonical)
        accepted.append(canonical)
    return accepted, rejected


def effective_status(cohort: FeatureCohort, *, now: datetime | None = None) -> str:
    """Resolve the reported sync status; staleness is computed, never stored."""

    if cohort.sync_state == SYNC_ERROR:
        return SYNC_ERROR
    if cohort.sync_state == SYNC_NEVER or cohort.last_synced_at is None:
        return SYNC_NEVER
    last_synced = _aware(cohort.last_synced_at)
    assert last_synced is not None
    if (now or _now()) - last_synced > timedelta(seconds=cohort.stale_after_seconds):
        return SYNC_STALE
    if cohort.sync_state == SYNC_BELOW_MINIMUM:
        return SYNC_BELOW_MINIMUM
    return SYNC_OK


def evaluation_allowed(cohort: FeatureCohort, *, now: datetime | None = None) -> bool:
    """True only for a fresh, successfully synced cohort at the size floor."""

    return (
        effective_status(cohort, now=now) == SYNC_OK
        and cohort.synced_size >= max(cohort.minimum_size, MIN_COHORT_SIZE)
    )


def _safe_size(value: int, minimum: int) -> tuple[int | None, bool]:
    """Hide 1-4 subject counts; zero is published as zero."""

    if 0 < value < max(minimum, MIN_COHORT_SIZE):
        return None, True
    return value, False


def _iso(value: datetime | None) -> str | None:
    aware = _aware(value)
    return aware.isoformat() if aware else None


def _cohort_state_payload(cohort: FeatureCohort, *, now: datetime) -> dict[str, Any]:
    status = effective_status(cohort, now=now)
    visible_size, suppressed = _safe_size(cohort.synced_size, cohort.minimum_size)
    return {
        "id": cohort.id,
        "key": cohort.key,
        "name": cohort.name,
        "description": cohort.description,
        "tenant_id": cohort.tenant_id,
        "posthog_cohort_id": cohort.posthog_cohort_id,
        "minimum_size": max(cohort.minimum_size, MIN_COHORT_SIZE),
        "stale_after_seconds": cohort.stale_after_seconds,
        "status": status,
        "is_stale": status == SYNC_STALE,
        "size": visible_size,
        "size_suppressed": suppressed,
        "suppression_note": (
            "Cohort size is hidden below the five-user minimum"
            if suppressed
            else None
        ),
        "synced_size_raw_is_hidden": True,
        "last_sync_attempt_at": _iso(cohort.last_sync_attempt_at),
        "last_synced_at": _iso(cohort.last_synced_at),
        "last_sync_error": cohort.last_sync_error,
        "created_at": _iso(cohort.created_at),
        "updated_at": _iso(cohort.updated_at),
    }


async def _tenant_slugs(
    db: AsyncSession, tenant_ids: Iterable[str | None]
) -> dict[str, str]:
    ids = {value for value in tenant_ids if value}
    if not ids:
        return {}
    rows = await db.execute(select(Tenant.id, Tenant.slug).where(Tenant.id.in_(ids)))
    return {str(row[0]): row[1] for row in rows.all()}


async def mapped_flag_keys(db: AsyncSession) -> set[str]:
    """Every flag that at least one cohort gates, for fail-closed public reads."""

    rows = await db.execute(select(FeatureCohortFlagMapping.flag_key).distinct())
    return {str(row[0]) for row in rows.all()}


async def _flag_rows_for_cohorts(
    db: AsyncSession, cohort_ids: Sequence[str]
) -> dict[str, list[dict[str, Any]]]:
    if not cohort_ids:
        return {}
    rows = await db.execute(
        select(
            FeatureCohortFlagMapping.cohort_id,
            FeatureFlag.key,
            FeatureFlag.label,
            FeatureFlag.enabled,
        )
        .join(FeatureFlag, FeatureFlag.key == FeatureCohortFlagMapping.flag_key)
        .where(FeatureCohortFlagMapping.cohort_id.in_(cohort_ids))
        .order_by(FeatureFlag.key)
    )
    result: dict[str, list[dict[str, Any]]] = {}
    for cohort_id, key, label, enabled in rows.all():
        result.setdefault(str(cohort_id), []).append(
            {"key": key, "label": label, "enabled": bool(enabled)}
        )
    return result


async def _exposure_counts(
    db: AsyncSession, *, now: datetime
) -> dict[str, int]:
    since = now - timedelta(days=EXPOSURE_LOOKBACK_DAYS)
    rows = await db.execute(
        text(
            """
            SELECT ck.cohort_key, COUNT(*)::int AS exposure_events
            FROM usage_analytics ua
            CROSS JOIN LATERAL jsonb_array_elements_text(
                CASE
                    WHEN jsonb_typeof(ua.event_metadata->'cohort_keys') = 'array'
                    THEN ua.event_metadata->'cohort_keys'
                    ELSE '[]'::jsonb
                END
            ) AS ck(cohort_key)
            WHERE ua.action = :action AND ua.created_at >= :since
            GROUP BY ck.cohort_key
            """
        ),
        {"action": COHORT_FLAG_EXPOSED, "since": since},
    )
    return {str(key): int(count) for key, count in rows.all()}


async def _cohort_payload(
    db: AsyncSession,
    cohort: FeatureCohort,
    *,
    now: datetime,
    flags: list[dict[str, Any]] | None = None,
    exposure_events: int = 0,
) -> dict[str, Any]:
    payload = _cohort_state_payload(cohort, now=now)
    payload["flags"] = flags or []
    payload["evaluation_allowed"] = evaluation_allowed(cohort, now=now) and bool(flags)
    visible_exposures, suppressed = _safe_size(exposure_events, cohort.minimum_size)
    payload["exposures_30d"] = visible_exposures
    payload["exposures_30d_suppressed"] = suppressed
    payload["consent_basis"] = CONSENT_BASIS
    tenant_slugs = await _tenant_slugs(db, [cohort.tenant_id])
    payload["tenant_slug"] = tenant_slugs.get(cohort.tenant_id or "")
    return payload


async def _get_cohort(db: AsyncSession, cohort_id: str) -> FeatureCohort:
    try:
        canonical = str(uuid.UUID(str(cohort_id)))
    except (ValueError, TypeError, AttributeError):
        raise CohortNotFound("Cohort not found") from None
    cohort = await db.scalar(select(FeatureCohort).where(FeatureCohort.id == canonical))
    if cohort is None:
        raise CohortNotFound("Cohort not found")
    return cohort


async def list_cohorts(
    db: AsyncSession, *, tenant_id: str | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Admin aggregate: size, status, error code and mapped flags only."""

    current = now or _now()
    clean_tenant = _clean_tenant_id(tenant_id)
    stmt = select(FeatureCohort).order_by(FeatureCohort.key)
    if clean_tenant:
        stmt = stmt.where(FeatureCohort.tenant_id == clean_tenant)
    cohorts = list((await db.execute(stmt)).scalars().all())
    cohort_ids = [cohort.id for cohort in cohorts]
    flags = await _flag_rows_for_cohorts(db, cohort_ids)
    exposures = await _exposure_counts(db, now=current)
    tenant_slugs = await _tenant_slugs(db, [cohort.tenant_id for cohort in cohorts])

    items: list[dict[str, Any]] = []
    summary = {
        "total": len(cohorts),
        "synced": 0,
        "stale": 0,
        "error": 0,
        "never_synced": 0,
        "below_minimum": 0,
        "with_flag_mappings": 0,
        "without_flag_mappings": 0,
        "evaluation_allowed": 0,
    }
    for cohort in cohorts:
        cohort_flags = flags.get(str(cohort.id), [])
        status = effective_status(cohort, now=current)
        if status in summary:
            summary[status] += 1
        if cohort_flags:
            summary["with_flag_mappings"] += 1
        else:
            summary["without_flag_mappings"] += 1
        if evaluation_allowed(cohort, now=current) and cohort_flags:
            summary["evaluation_allowed"] += 1
        payload = _cohort_state_payload(cohort, now=current)
        payload["tenant_slug"] = tenant_slugs.get(cohort.tenant_id or "")
        payload["flags"] = cohort_flags
        payload["evaluation_allowed"] = (
            evaluation_allowed(cohort, now=current) and bool(cohort_flags)
        )
        visible_exposures, suppressed = _safe_size(
            exposures.get(cohort.key, 0), cohort.minimum_size
        )
        payload["exposures_30d"] = visible_exposures
        payload["exposures_30d_suppressed"] = suppressed
        payload["consent_basis"] = CONSENT_BASIS
        items.append(payload)

    return {
        "cohorts": items,
        "summary": summary,
        "minimum_size": MIN_COHORT_SIZE,
        "exposure_lookback_days": EXPOSURE_LOOKBACK_DAYS,
        "consent_basis": CONSENT_BASIS,
        "aggregate_only": True,
        "member_identifiers_returned": False,
    }


async def create_cohort(
    db: AsyncSession,
    *,
    actor: AdminActor,
    key: Any,
    name: str,
    reason: str | None,
    description: str | None = None,
    tenant_id: Any = None,
    posthog_cohort_id: Any = None,
    minimum_size: int = MIN_COHORT_SIZE,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
    request: Request | None = None,
) -> dict[str, Any]:
    """Create a cohort definition. No membership exists until a sync."""

    clean_reason = _clean_reason(reason)
    clean_key = _clean_cohort_key(key)
    clean_name = _clean_text(name, "name", minimum=2, maximum=255)
    clean_description = (
        _clean_text(description, "description", minimum=1, maximum=2000)
        if description
        else None
    )
    clean_tenant = _clean_tenant_id(tenant_id)
    clean_posthog = _clean_posthog_id(posthog_cohort_id)
    if int(minimum_size) < MIN_COHORT_SIZE:
        raise CohortValidationError(
            f"minimum_size cannot be below {MIN_COHORT_SIZE}"
        )
    if not (MIN_STALE_AFTER_SECONDS <= int(stale_after_seconds) <= MAX_STALE_AFTER_SECONDS):
        raise CohortValidationError(
            "stale_after_seconds must be between 300 and 604800"
        )
    if clean_tenant is not None:
        tenant = await db.scalar(
            select(Tenant).where(Tenant.id == clean_tenant, Tenant.active.is_(True))
        )
        if tenant is None:
            raise CohortValidationError("tenant_id does not identify an active tenant")

    existing = await db.scalar(
        select(FeatureCohort.id).where(FeatureCohort.key == clean_key)
    )
    if existing is not None:
        raise CohortConflict("A cohort with this key already exists")

    cohort = FeatureCohort(
        key=clean_key,
        name=clean_name,
        description=clean_description,
        tenant_id=clean_tenant,
        posthog_cohort_id=clean_posthog,
        minimum_size=max(int(minimum_size), MIN_COHORT_SIZE),
        stale_after_seconds=int(stale_after_seconds),
        sync_state=SYNC_NEVER,
        synced_size=0,
    )
    db.add(cohort)
    await db.flush()
    await db.refresh(cohort)
    await record_admin_audit(
        db,
        actor=actor,
        action="cohort.create",
        target_type="feature_cohort",
        target_id=cohort.id,
        reason=clean_reason,
        after={
            "key": cohort.key,
            "name": cohort.name,
            "tenant_id": cohort.tenant_id,
            "posthog_cohort_id": cohort.posthog_cohort_id,
            "minimum_size": cohort.minimum_size,
            "stale_after_seconds": cohort.stale_after_seconds,
        },
        request=request,
    )
    await db.commit()
    await db.refresh(cohort)
    return await _cohort_payload(db, cohort, now=_now())


async def map_flag(
    db: AsyncSession,
    *,
    actor: AdminActor,
    cohort_id: str,
    flag_key: Any,
    reason: str | None,
    request: Request | None = None,
) -> dict[str, Any]:
    """Attach one existing feature flag to a cohort."""

    clean_reason = _clean_reason(reason)
    clean_flag = _clean_flag_key(flag_key)
    cohort = await _get_cohort(db, cohort_id)
    flag = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == clean_flag))
    if flag is None:
        raise CohortValidationError("flag_key does not identify a feature flag")
    existing = await db.scalar(
        select(FeatureCohortFlagMapping.cohort_id).where(
            FeatureCohortFlagMapping.cohort_id == cohort.id,
            FeatureCohortFlagMapping.flag_key == clean_flag,
        )
    )
    if existing is not None:
        raise CohortConflict("This flag is already mapped to the cohort")

    db.add(FeatureCohortFlagMapping(cohort_id=cohort.id, flag_key=clean_flag))
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="cohort.flag_map",
        target_type="feature_cohort",
        target_id=cohort.id,
        reason=clean_reason,
        after={"key": cohort.key, "flag_key": clean_flag},
        request=request,
    )
    await db.commit()
    await db.refresh(cohort)
    flags = await _flag_rows_for_cohorts(db, [cohort.id])
    return await _cohort_payload(
        db, cohort, now=_now(), flags=flags.get(str(cohort.id), [])
    )


async def unmap_flag(
    db: AsyncSession,
    *,
    actor: AdminActor,
    cohort_id: str,
    flag_key: str,
    reason: str | None,
    request: Request | None = None,
) -> dict[str, Any]:
    """Detach a flag from a cohort."""

    clean_reason = _clean_reason(reason)
    clean_flag = _clean_flag_key(flag_key)
    cohort = await _get_cohort(db, cohort_id)
    mapping = await db.scalar(
        select(FeatureCohortFlagMapping).where(
            FeatureCohortFlagMapping.cohort_id == cohort.id,
            FeatureCohortFlagMapping.flag_key == clean_flag,
        )
    )
    if mapping is None:
        raise CohortNotFound("Flag mapping not found")
    await db.delete(mapping)
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="cohort.flag_unmap",
        target_type="feature_cohort",
        target_id=cohort.id,
        reason=clean_reason,
        before={"key": cohort.key, "flag_key": clean_flag},
        request=request,
    )
    await db.commit()
    await db.refresh(cohort)
    flags = await _flag_rows_for_cohorts(db, [cohort.id])
    return await _cohort_payload(
        db, cohort, now=_now(), flags=flags.get(str(cohort.id), [])
    )


async def _tenant_subject_ids(
    db: AsyncSession, tenant_id: str, candidate_ids: Sequence[str]
) -> set[str]:
    if not candidate_ids:
        return set()
    default_rows = await db.execute(
        select(User.id).where(
            User.id.in_(candidate_ids), User.default_tenant_id == tenant_id
        )
    )
    member_rows = await db.execute(
        select(TenantMember.user_id).where(
            TenantMember.tenant_id == tenant_id,
            TenantMember.user_id.in_(candidate_ids),
        )
    )
    return {str(row[0]) for row in default_rows.all()} | {
        str(row[0]) for row in member_rows.all()
    }


async def sync_members(
    db: AsyncSession,
    *,
    actor: AdminActor,
    cohort_id: str,
    reason: str | None,
    members: Sequence[str] | None = None,
    error_code: str | None = None,
    posthog_cohort_id: Any = None,
    request: Request | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Report one PostHog cohort sync result.

    With ``error_code`` the attempt is recorded as failed and the previous
    membership is left in place, but evaluation fails closed because the state
    is ``error``. Otherwise the membership snapshot replaces the cohort's rows
    atomically.
    """

    clean_reason = _clean_reason(reason)
    cohort = await _get_cohort(db, cohort_id)
    current = now or _now()
    clean_posthog = _clean_posthog_id(posthog_cohort_id)
    if clean_posthog is not None:
        cohort.posthog_cohort_id = clean_posthog

    if error_code is not None:
        clean_error = _clean_error_code(error_code)
        cohort.sync_state = SYNC_ERROR
        cohort.last_sync_attempt_at = current
        cohort.last_sync_error = clean_error
        await db.flush()
        await record_admin_audit(
            db,
            actor=actor,
            action="cohort.sync_error",
            target_type="feature_cohort",
            target_id=cohort.id,
            reason=clean_reason,
            after={
                "key": cohort.key,
                "status": SYNC_ERROR,
                "error_code": clean_error,
            },
            request=request,
        )
        await db.commit()
        await db.refresh(cohort)
        flags = await _flag_rows_for_cohorts(db, [cohort.id])
        return await _cohort_payload(
            db, cohort, now=current, flags=flags.get(str(cohort.id), [])
        )

    supplied = list(members or [])
    if len(supplied) > MAX_SYNC_MEMBERS:
        raise CohortValidationError(
            f"members cannot exceed {MAX_SYNC_MEMBERS} entries per sync"
        )
    candidate_ids, malformed = _clean_user_ids(supplied)

    existing_rows = await db.execute(select(User.id).where(User.id.in_(candidate_ids)))
    existing_ids = {str(row[0]) for row in existing_rows.all()}
    accepted_ids = sorted(existing_ids)
    rejected_tenant = 0
    if cohort.tenant_id is not None:
        tenant_ids = await _tenant_subject_ids(db, cohort.tenant_id, accepted_ids)
        rejected_tenant = len(accepted_ids) - len(tenant_ids)
        accepted_ids = sorted(tenant_ids)

    await db.execute(
        delete(FeatureCohortMember).where(FeatureCohortMember.cohort_id == cohort.id)
    )
    if accepted_ids:
        await db.execute(
            insert(FeatureCohortMember),
            [
                {
                    "cohort_id": cohort.id,
                    "user_id": user_id,
                    "synced_at": current,
                }
                for user_id in accepted_ids
            ],
        )

    cohort.synced_size = len(accepted_ids)
    cohort.last_sync_attempt_at = current
    cohort.last_synced_at = current
    cohort.last_sync_error = None
    cohort.sync_state = (
        SYNC_BELOW_MINIMUM
        if len(accepted_ids) < max(cohort.minimum_size, MIN_COHORT_SIZE)
        else SYNC_OK
    )
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="cohort.sync",
        target_type="feature_cohort",
        target_id=cohort.id,
        reason=clean_reason,
        after={
            "key": cohort.key,
            "status": cohort.sync_state,
            "requested": len(supplied),
            "accepted": len(accepted_ids),
            "rejected_malformed": malformed,
            "rejected_unknown": len(candidate_ids) - len(existing_ids),
            "rejected_tenant": rejected_tenant,
            "below_minimum": cohort.sync_state == SYNC_BELOW_MINIMUM,
        },
        request=request,
    )
    await db.commit()
    await db.refresh(cohort)
    flags = await _flag_rows_for_cohorts(db, [cohort.id])
    payload = await _cohort_payload(
        db, cohort, now=current, flags=flags.get(str(cohort.id), [])
    )
    payload["sync_counts"] = {
        "requested": len(supplied),
        "accepted": len(accepted_ids),
        "rejected_malformed": malformed,
        "rejected_unknown": len(candidate_ids) - len(existing_ids),
        "rejected_tenant": rejected_tenant,
    }
    return payload


async def _latest_consent_decision(
    db: AsyncSession, anonymous_id: str
) -> str | None:
    action = (
        await db.execute(
            select(UsageAnalytics.action)
            .where(
                UsageAnalytics.action.in_(tuple(CONSENT_ACTIONS.values())),
                UsageAnalytics.event_metadata["anonymous_id"].as_string()
                == anonymous_id,
            )
            .order_by(UsageAnalytics.created_at.desc(), UsageAnalytics.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return DECISION_BY_ACTION.get(action) if action else None


def _evaluation_window(now: datetime) -> str:
    return now.astimezone(timezone.utc).date().isoformat()


def _normalize_flag_keys(values: Sequence[Any]) -> list[str]:
    if not values:
        raise CohortValidationError("flag_keys must contain at least one flag")
    if len(values) > MAX_EVALUATED_FLAGS:
        raise CohortValidationError(
            f"flag_keys cannot exceed {MAX_EVALUATED_FLAGS} entries"
        )
    keys: list[str] = []
    seen: set[str] = set()
    for value in values:
        raw = str(value or "").strip()
        if FLAG_KEY_RE.fullmatch(raw) is None:
            raise CohortValidationError("flag_keys contains an invalid flag key")
        if raw in seen:
            continue
        seen.add(raw)
        keys.append(raw)
    return keys


async def evaluate_flags(
    db: AsyncSession,
    *,
    user_id: str,
    anonymous_id: Any,
    flag_keys: Sequence[Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate cohort-mapped flags for one authenticated subject.

    The caller must present an opaque browser id with a current analytics
    grant. Without it every result is disabled, no membership is read and no
    exposure is recorded.
    """

    canonical_anonymous_id = normalize_identifier(anonymous_id)
    if canonical_anonymous_id is None:
        raise CohortValidationError("anonymous_id must be a bounded opaque identifier")
    keys = _normalize_flag_keys(flag_keys)
    current = now or _now()
    window = _evaluation_window(current)

    consent = await _latest_consent_decision(db, canonical_anonymous_id)
    if consent != "granted":
        return {
            "evaluated_at": current.isoformat(),
            "window": window,
            "consent_required": True,
            "exposure_recorded": 0,
            "results": [
                {
                    "key": key,
                    "enabled": False,
                    "reason": "consent_required",
                    "exposure_recorded": False,
                }
                for key in keys
            ],
        }

    flag_rows = {
        row.key: row
        for row in (
            await db.execute(select(FeatureFlag).where(FeatureFlag.key.in_(keys)))
        )
        .scalars()
        .all()
    }
    mapping_rows = (
        await db.execute(
            select(FeatureCohortFlagMapping, FeatureCohort)
            .join(
                FeatureCohort,
                FeatureCohort.id == FeatureCohortFlagMapping.cohort_id,
            )
            .where(FeatureCohortFlagMapping.flag_key.in_(keys))
        )
    ).all()
    mapped: dict[str, list[FeatureCohort]] = {}
    for mapping, cohort in mapping_rows:
        mapped.setdefault(mapping.flag_key, []).append(cohort)

    user_tenant_ids: set[str] = set()
    default_tenant = await db.scalar(select(User.default_tenant_id).where(User.id == user_id))
    if default_tenant:
        user_tenant_ids.add(str(default_tenant))
    tenant_rows = await db.execute(
        select(TenantMember.tenant_id).where(TenantMember.user_id == user_id)
    )
    user_tenant_ids.update(str(row[0]) for row in tenant_rows.all())

    all_cohort_ids = {
        cohort.id for cohorts in mapped.values() for cohort in cohorts
    }
    member_cohort_ids: set[str] = set()
    if all_cohort_ids:
        member_rows = await db.execute(
            select(FeatureCohortMember.cohort_id).where(
                FeatureCohortMember.user_id == user_id,
                FeatureCohortMember.cohort_id.in_(all_cohort_ids),
            )
        )
        member_cohort_ids = {str(row[0]) for row in member_rows.all()}

    results: list[dict[str, Any]] = []
    exposures = 0
    for key in keys:
        flag = flag_rows.get(key)
        if flag is None:
            results.append(
                {
                    "key": key,
                    "enabled": False,
                    "reason": "unknown_flag",
                    "exposure_recorded": False,
                }
            )
            continue

        cohorts = mapped.get(key, [])
        eligible = [
            cohort
            for cohort in cohorts
            if cohort.tenant_id is None or str(cohort.tenant_id) in user_tenant_ids
        ]
        if not cohorts:
            enabled = bool(flag.enabled)
            reason = "no_cohort_mapping" if enabled else "flag_disabled"
        elif not flag.enabled:
            enabled = False
            reason = "flag_disabled"
        elif not eligible:
            enabled = False
            reason = "not_in_cohort"
        elif any(not evaluation_allowed(cohort, now=current) for cohort in eligible):
            enabled = False
            reason = "sync_not_current"
        elif not ({cohort.id for cohort in eligible} & member_cohort_ids):
            enabled = False
            reason = "not_in_cohort"
        else:
            enabled = True
            reason = "cohort_match"

        cohort_keys = sorted({cohort.key for cohort in cohorts})
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"cohort-exposure:{user_id}:{key}:{window}"},
        )
        existing = (
            await db.execute(
                select(UsageAnalytics.id)
                .where(
                    UsageAnalytics.action == COHORT_FLAG_EXPOSED,
                    UsageAnalytics.user_id == user_id,
                    UsageAnalytics.event_metadata["flag_key"].as_string() == key,
                    UsageAnalytics.event_metadata["window"].as_string() == window,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        recorded = False
        if existing is None:
            db.add(
                UsageAnalytics(
                    user_id=user_id,
                    device_fingerprint=None,
                    action=COHORT_FLAG_EXPOSED,
                    resource_type=COHORT_FLAG_RESOURCE_TYPE,
                    event_metadata={
                        "flag_key": key,
                        "enabled": enabled,
                        "reason": reason,
                        "variant": "treatment" if enabled else "control",
                        "window": window,
                        "cohort_keys": cohort_keys,
                        "source": COHORT_EXPOSURE_SOURCE,
                    },
                    ip_address=None,
                    user_agent=None,
                    created_at=current,
                )
            )
            recorded = True
            exposures += 1

        results.append(
            {
                "key": key,
                "enabled": enabled,
                "reason": reason,
                "exposure_recorded": recorded,
            }
        )

    await db.commit()
    return {
        "evaluated_at": current.isoformat(),
        "window": window,
        "consent_required": False,
        "exposure_recorded": exposures,
        "results": results,
    }


async def evaluation_stats(
    db: AsyncSession, *, cohort_keys: Sequence[str], days: int = EXPOSURE_LOOKBACK_DAYS
) -> dict[str, Any]:
    """Aggregate-only exposure counts for a bounded cohort key set."""

    if not cohort_keys:
        return {"cohorts": {}, "minimum_size": MIN_COHORT_SIZE}
    since = _now() - timedelta(days=max(1, min(days, EXPOSURE_LOOKBACK_DAYS)))
    rows = await db.execute(
        text(
            """
            SELECT ck.cohort_key, COUNT(*)::int
            FROM usage_analytics ua
            CROSS JOIN LATERAL jsonb_array_elements_text(
                CASE
                    WHEN jsonb_typeof(ua.event_metadata->'cohort_keys') = 'array'
                    THEN ua.event_metadata->'cohort_keys'
                    ELSE '[]'::jsonb
                END
            ) AS ck(cohort_key)
            WHERE ua.action = :action AND ua.created_at >= :since
              AND ck.cohort_key = ANY(:keys)
            GROUP BY ck.cohort_key
            """
        ),
        {
            "action": COHORT_FLAG_EXPOSED,
            "since": since,
            "keys": list(cohort_keys),
        },
    )
    counts: dict[str, int | None] = {}
    for key, count in rows.all():
        visible, _ = _safe_size(int(count), MIN_COHORT_SIZE)
        counts[str(key)] = visible
    return {"cohorts": counts, "minimum_size": MIN_COHORT_SIZE}


class CohortSyncService:
    """Object facade used by routes and future sync workers."""

    create_cohort = staticmethod(create_cohort)
    list_cohorts = staticmethod(list_cohorts)
    map_flag = staticmethod(map_flag)
    unmap_flag = staticmethod(unmap_flag)
    sync_members = staticmethod(sync_members)
    evaluate_flags = staticmethod(evaluate_flags)
    mapped_flag_keys = staticmethod(mapped_flag_keys)
    evaluation_stats = staticmethod(evaluation_stats)
    effective_status = staticmethod(effective_status)
    evaluation_allowed = staticmethod(evaluation_allowed)


cohort_sync_service = CohortSyncService()
