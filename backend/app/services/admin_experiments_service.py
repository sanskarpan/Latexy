"""Pre-registered A/B experiment registry, assignment and results (issue #2158).

Data boundary
-------------
An experiment row stores operator-authored pre-registration metadata, a
feature-flag key and a PostHog insight URL. Assignment and exposure rows store
only the account UUID, experiment UUID, bounded variant key, deterministic
bucket and server timestamp. No email, name, document text, prompt, token, IP
address, user agent or provider payload is accepted or returned. Admin surfaces
are aggregate-only and never list a subject or an assignment.

Preregistration immutability
----------------------------
A canonical hash covers the hypothesis, primary metric, guardrails, variants,
feature-flag link, minimum sample and insight link. The migration trigger
rejects any update to those fields or to the creation actor/time, so results
cannot be re-analysed against a retrospectively edited registration. Only the
``preregistered -> running -> stopped`` lifecycle may change.

Consent and assignment
----------------------
Experiment assignment is authenticated and requires the latest first-party
analytics decision for the supplied opaque browser id to be ``granted``. A
denial or withdrawal therefore stops assignment and exposure server-side even
if a caller bypasses the browser gate. Variant choice is deterministic from the
experiment id and account id, so retries and concurrent requests cannot drift
between variants. A failed or disabled linked operational flag skips the
experiment: a kill switch always wins.

Dedupe
------
One assignment per experiment and account is enforced by a unique constraint.
Exposure is recorded at most once per experiment, account and UTC calendar day;
a transaction-scoped advisory lock plus the unique constraint make retries and
concurrent requests idempotent.

Results
-------
Outcomes are measured from each subject's first exposure with the same 7-day
horizon and first-party joins used by the feature-flag exposure report. The
published groups are randomized intent-to-treat cohorts. Groups with 1-4
subjects are hidden, as are rates whose numerator or denominator is below five.
No lift or confidence interval is published until every variant reaches the
pre-registered minimum sample. A winner is never declared and no variant is
rolled out automatically.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models
from .admin_audit_service import AdminActor, record_admin_audit
from .admin_incident_service import _reject_pii
from .consent_analytics_service import normalize_identifier
from .feature_flag_service import OPERATIONAL_FLAGS, feature_flag_service
from .flag_exposure_service import (
    GUARDRAIL_KEYS,
    METRIC_BY_KEY,
    METRIC_DEFINITIONS,
    MIN_GROUP_SIZE,
    ConsentRequiredError,
    _group_suppressed,
    _latest_consent_decision,
    _load_outcomes,
    _metric_cell,
    _metric_counts,
)

AdminExperiment = models.AdminExperiment
AdminExperimentAssignment = models.AdminExperimentAssignment
AdminExperimentExposure = models.AdminExperimentExposure

EXPERIMENT_SOURCE = "first_party_experiment_evaluation"

STATUSES: tuple[str, ...] = ("preregistered", "running", "stopped")
PRIMARY_METRIC_KEYS: tuple[str, ...] = tuple(
    definition["key"]
    for definition in METRIC_DEFINITIONS
    if definition["kind"] == "outcome"
)
PRIMARY_METRIC_SET = frozenset(PRIMARY_METRIC_KEYS)
GUARDRAIL_SET = frozenset(GUARDRAIL_KEYS)

MIN_VARIANTS = 2
MAX_VARIANTS = 4
MIN_SAMPLE = 5
MAX_SAMPLE = 1_000_000
MAX_NAME = 160
MAX_HYPOTHESIS = 4000
MAX_REASON = 1000
MAX_VARIANT_LABEL = 80
MAX_ASSIGNMENT_KEYS = 10
MAX_POSTHOG_URL = 500
CONFIDENCE_LEVEL = 0.95
Z_95 = 1.959963984540054
OUTCOME_HORIZON_DAYS = 7
MIN_LIST_LIMIT = 1
MAX_LIST_LIMIT = 100
DEFAULT_LIST_LIMIT = 50

POSTHOG_HOSTS: tuple[str, ...] = (
    "app.posthog.com",
    "us.posthog.com",
    "eu.posthog.com",
)
CONTROL_VARIANT = "control"

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_VARIANT_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_INSIGHT_PATH_RE = re.compile(r"^/[A-Za-z0-9._~:/@!$&()*+,;=%-]*$")

_CLAIM = {
    "policy": "fixed_horizon_preregistered_metric",
    "causality": "randomized_first_party_assignment",
    "confidence_level": CONFIDENCE_LEVEL,
    "peeking": (
        "No lift or confidence interval is published before every variant reaches "
        "the pre-registered minimum sample. Earlier reads are descriptive only."
    ),
    "winner": (
        "No winner is declared. A winning variant is never rolled out automatically; "
        "a separate admin action and a new registration are required."
    ),
    "automatic_rollout": False,
    "multiple_looks_corrected": False,
}


class ExperimentError(Exception):
    """Base class for an experiment-domain failure."""

    status_code = 422
    code = "experiment_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ExperimentValidationError(ExperimentError):
    status_code = 422
    code = "experiment_invalid"


class ExperimentConflict(ExperimentError):
    status_code = 409
    code = "experiment_conflict"


class ExperimentNotRunning(ExperimentError):
    status_code = 409
    code = "experiment_not_running"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    normalized = _as_aware(value)
    return normalized.isoformat() if normalized else None


def _clean_text(
    value: Any,
    *,
    field: str,
    min_length: int,
    max_length: int,
) -> str:
    if not isinstance(value, str):
        raise ExperimentValidationError(f"{field} must be text")
    cleaned = " ".join(value.split())
    if len(cleaned) < min_length:
        raise ExperimentValidationError(
            f"{field} must be at least {min_length} characters"
        )
    if len(cleaned) > max_length:
        raise ExperimentValidationError(
            f"{field} must be at most {max_length} characters"
        )
    try:
        _reject_pii(cleaned, field=field)
    except ValueError as exc:
        raise ExperimentValidationError(str(exc)) from None
    return cleaned


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _registration_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _registration_payload(
    *,
    experiment_key: str,
    name: str,
    hypothesis: str,
    primary_metric: str,
    guardrail_metrics: Sequence[str],
    variants: Sequence[Mapping[str, Any]],
    flag_key: str | None,
    minimum_sample_per_variant: int,
    posthog_insight_url: str | None,
) -> dict[str, Any]:
    return {
        "experiment_key": experiment_key,
        "name": name,
        "hypothesis": hypothesis,
        "primary_metric": primary_metric,
        "guardrail_metrics": list(guardrail_metrics),
        "variants": [dict(variant) for variant in variants],
        "flag_key": flag_key,
        "minimum_sample_per_variant": minimum_sample_per_variant,
        "posthog_insight_url": posthog_insight_url,
    }


def _row_registration_payload(row: AdminExperiment) -> dict[str, Any]:
    return _registration_payload(
        experiment_key=row.experiment_key,
        name=row.name,
        hypothesis=row.hypothesis,
        primary_metric=row.primary_metric,
        guardrail_metrics=list(row.guardrail_metrics or []),
        variants=list(row.variants or []),
        flag_key=row.flag_key,
        minimum_sample_per_variant=int(row.minimum_sample_per_variant),
        posthog_insight_url=row.posthog_insight_url,
    )


def registration_intact(row: AdminExperiment) -> bool:
    """True when the stored hash still covers the stored registration fields."""

    return _registration_hash(_row_registration_payload(row)) == row.registration_hash


def normalize_experiment_key(value: Any) -> str:
    if not isinstance(value, str):
        raise ExperimentValidationError("key must be text")
    key = value.strip().lower()
    if _KEY_RE.fullmatch(key) is None:
        raise ExperimentValidationError(
            "key must be 2-64 lowercase letters, digits or underscores and start with a letter"
        )
    return key


def normalize_variant_key(value: Any) -> str:
    if not isinstance(value, str):
        raise ExperimentValidationError("variant key must be text")
    key = value.strip().lower()
    if _VARIANT_RE.fullmatch(key) is None:
        raise ExperimentValidationError(
            "variant key must be 1-32 lowercase letters, digits or underscores and start with a letter"
        )
    return key


def normalize_variants(raw: Any) -> list[dict[str, Any]]:
    """Validate 2-4 weighted variants with an explicit control reference."""

    if not isinstance(raw, list):
        raise ExperimentValidationError("variants must be a list")
    if len(raw) < MIN_VARIANTS or len(raw) > MAX_VARIANTS:
        raise ExperimentValidationError(
            f"variants must contain {MIN_VARIANTS}-{MAX_VARIANTS} entries"
        )

    variants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ExperimentValidationError(f"variants[{index}] must be an object")
        extra = set(item) - {"key", "label", "weight", "flag_enabled"}
        if extra:
            raise ExperimentValidationError(
                f"variants[{index}] has unsupported fields: {', '.join(sorted(extra))}"
            )
        key = normalize_variant_key(item.get("key"))
        if key in seen:
            raise ExperimentValidationError("variant keys must be unique")
        seen.add(key)
        label = _clean_text(
            item.get("label"),
            field=f"variants[{index}].label",
            min_length=1,
            max_length=MAX_VARIANT_LABEL,
        )
        weight = item.get("weight")
        if type(weight) is not int or weight < 1 or weight > 100:
            raise ExperimentValidationError(
                f"variants[{index}].weight must be an integer between 1 and 100"
            )
        flag_enabled = item.get("flag_enabled")
        if flag_enabled is not None and type(flag_enabled) is not bool:
            raise ExperimentValidationError(
                f"variants[{index}].flag_enabled must be a boolean or null"
            )
        variants.append(
            {
                "key": key,
                "label": label,
                "weight": weight,
                "flag_enabled": flag_enabled,
            }
        )

    if variants[0]["key"] != CONTROL_VARIANT:
        raise ExperimentValidationError("the first variant must be the control")
    if len({variant["key"] for variant in variants}) < MIN_VARIANTS:
        raise ExperimentValidationError("at least one treatment variant is required")
    if sum(variant["weight"] for variant in variants) != 100:
        raise ExperimentValidationError("variant weights must sum to 100")
    return variants


def _normalize_primary_metric(value: Any) -> str:
    metric = str(value or "").strip().lower()
    if metric not in PRIMARY_METRIC_SET:
        raise ExperimentValidationError(
            "primary_metric must be one of " + ", ".join(PRIMARY_METRIC_KEYS)
        )
    return metric


def _normalize_guardrails(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ExperimentValidationError("guardrail_metrics must be a non-empty list")
    if len(value) > 2:
        raise ExperimentValidationError("at most two guardrail metrics may be registered")
    guardrails: list[str] = []
    for raw in value:
        metric = str(raw or "").strip().lower()
        if metric not in GUARDRAIL_SET:
            raise ExperimentValidationError(
                "guardrail_metrics must be drawn from " + ", ".join(sorted(GUARDRAIL_SET))
            )
        if metric in guardrails:
            raise ExperimentValidationError("guardrail metrics must be unique")
        guardrails.append(metric)
    return guardrails


def _normalize_flag_key(value: Any) -> str | None:
    if value is None:
        return None
    key = str(value).strip().lower()
    if key not in OPERATIONAL_FLAGS:
        raise ExperimentValidationError(
            "flag_key must be an operational feature flag or null"
        )
    return key


def normalize_posthog_url(value: Any) -> str | None:
    """Accept only a credential-free standard PostHog insight URL."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ExperimentValidationError("posthog_insight_url must be text or null")
    url = value.strip()
    if not url:
        return None
    if len(url) > MAX_POSTHOG_URL:
        raise ExperimentValidationError(
            f"posthog_insight_url must be at most {MAX_POSTHOG_URL} characters"
        )
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        port = -1
    if (
        parsed.scheme != "https"
        or parsed.hostname not in POSTHOG_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or not _INSIGHT_PATH_RE.fullmatch(parsed.path or "")
    ):
        raise ExperimentValidationError(
            "posthog_insight_url must be an https insight URL on app, us or eu.posthog.com"
        )
    # Canonicalize the host so the database check and the stored value agree.
    return f"https://{parsed.hostname}{parsed.path}"


def _normalize_minimum_sample(value: Any) -> int:
    if type(value) is not int or value < MIN_SAMPLE or value > MAX_SAMPLE:
        raise ExperimentValidationError(
            f"minimum_sample_per_variant must be an integer between {MIN_SAMPLE} and {MAX_SAMPLE}"
        )
    return value


def _clean_reason(value: Any) -> str:
    cleaned = _clean_text(
        value,
        field="reason",
        min_length=3,
        max_length=MAX_REASON,
    )
    return cleaned


def _variant_payload(variants: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "key": str(variant["key"]),
            "label": str(variant["label"]),
            "weight": int(variant["weight"]),
            "flag_enabled": (
                bool(variant["flag_enabled"])
                if variant.get("flag_enabled") is not None
                else None
            ),
        }
        for variant in variants
    ]


def _sample_payload(
    row: AdminExperiment,
    counts: Mapping[str, int],
    *,
    minimum_sample: int,
) -> dict[str, Any]:
    variants: list[dict[str, Any]] = []
    any_suppressed = False
    total = 0
    minimum_met = row.status != "preregistered"
    for variant in row.variants or []:
        key = str(variant["key"])
        count = int(counts.get(key, 0) or 0)
        total += count
        if 0 < count < MIN_GROUP_SIZE:
            visible = None
            suppressed = True
            any_suppressed = True
            minimum_met = False
        else:
            visible = count
            suppressed = False
            if count < minimum_sample:
                minimum_met = False
        variants.append(
            {
                "variant": key,
                "label": str(variant["label"]),
                "sample_size": visible,
                "suppressed": suppressed,
                "minimum_sample": minimum_sample,
            }
        )

    total_visible: int | None = total
    if any_suppressed or 0 < total < MIN_GROUP_SIZE:
        total_visible = None
    return {
        "variants": variants,
        "sample_size": total_visible,
        "minimum_sample_per_variant": minimum_sample,
        "minimum_sample_met": minimum_met,
        "suppressed": any_suppressed,
    }


def experiment_summary(
    row: AdminExperiment,
    *,
    sample_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    counts = sample_counts or {}
    sample = _sample_payload(
        row,
        counts,
        minimum_sample=int(row.minimum_sample_per_variant),
    )
    return {
        "id": row.id,
        "key": row.experiment_key,
        "name": row.name,
        "hypothesis": row.hypothesis,
        "primary_metric": row.primary_metric,
        "guardrail_metrics": list(row.guardrail_metrics or []),
        "variants": _variant_payload(row.variants or []),
        "flag_key": row.flag_key,
        "posthog_insight_url": row.posthog_insight_url,
        "minimum_sample_per_variant": int(row.minimum_sample_per_variant),
        "status": row.status,
        "registration_hash": row.registration_hash,
        "registration_intact": registration_intact(row),
        "started_at": _iso(row.started_at),
        "stopped_at": _iso(row.stopped_at),
        "stop_reason": row.stop_reason,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "sample": sample,
        "results_ready": sample["minimum_sample_met"] and sample["sample_size"] is not None,
    }


def experiment_catalog() -> dict[str, Any]:
    return {
        "primary_metrics": [
            dict(METRIC_BY_KEY[key])
            for key in PRIMARY_METRIC_KEYS
            if key in METRIC_BY_KEY
        ],
        "guardrail_metrics": [
            dict(METRIC_BY_KEY[key])
            for key in GUARDRAIL_KEYS
            if key in METRIC_BY_KEY
        ],
        "metric_definitions": [dict(item) for item in METRIC_DEFINITIONS],
        "operational_flags": sorted(OPERATIONAL_FLAGS),
        "statuses": list(STATUSES),
        "minimum_sample_floor": MIN_SAMPLE,
        "minimum_group_size": MIN_GROUP_SIZE,
        "outcome_horizon_days": OUTCOME_HORIZON_DAYS,
        "posthog_hosts": list(POSTHOG_HOSTS),
        "claim": dict(_CLAIM),
        "notes": [
            "Registration fields are immutable after insert; only start and stop may change.",
            "Assignment is deterministic per experiment and account and requires analytics consent.",
            "Exposure is recorded at most once per experiment, subject and UTC day.",
            "Results are aggregate-only; no account, assignment or per-user history is returned.",
            "No winning variant is rolled out automatically.",
        ],
    }


async def _get_experiment(
    db: AsyncSession,
    experiment_id: str,
    *,
    for_update: bool = False,
) -> AdminExperiment:
    try:
        normalized_id = str(uuid.UUID(str(experiment_id)))
    except (ValueError, TypeError, AttributeError):
        raise KeyError("Experiment not found") from None
    statement = select(AdminExperiment).where(AdminExperiment.id == normalized_id)
    if for_update:
        statement = statement.with_for_update()
    row = (await db.execute(statement)).scalar_one_or_none()
    if row is None:
        raise KeyError("Experiment not found")
    return row


async def create_experiment(
    db: AsyncSession,
    *,
    actor: AdminActor,
    experiment_key: Any,
    name: Any,
    hypothesis: Any,
    primary_metric: Any,
    guardrail_metrics: Any,
    variants: Any,
    flag_key: Any,
    posthog_insight_url: Any,
    minimum_sample_per_variant: Any,
    reason: Any,
    request=None,
) -> dict[str, Any]:
    key = normalize_experiment_key(experiment_key)
    cleaned_name = _clean_text(
        name, field="name", min_length=1, max_length=MAX_NAME
    )
    cleaned_hypothesis = _clean_text(
        hypothesis,
        field="hypothesis",
        min_length=20,
        max_length=MAX_HYPOTHESIS,
    )
    metric = _normalize_primary_metric(primary_metric)
    guardrails = _normalize_guardrails(guardrail_metrics)
    normalized_variants = normalize_variants(variants)
    flag = _normalize_flag_key(flag_key)
    insight_url = normalize_posthog_url(posthog_insight_url)
    minimum_sample = _normalize_minimum_sample(minimum_sample_per_variant)
    cleaned_reason = _clean_reason(reason)

    registration = _registration_payload(
        experiment_key=key,
        name=cleaned_name,
        hypothesis=cleaned_hypothesis,
        primary_metric=metric,
        guardrail_metrics=guardrails,
        variants=normalized_variants,
        flag_key=flag,
        minimum_sample_per_variant=minimum_sample,
        posthog_insight_url=insight_url,
    )
    now = _now()
    row = AdminExperiment(
        id=str(uuid.uuid4()),
        experiment_key=key,
        name=cleaned_name,
        hypothesis=cleaned_hypothesis,
        primary_metric=metric,
        guardrail_metrics=guardrails,
        variants=normalized_variants,
        flag_key=flag,
        posthog_insight_url=insight_url,
        minimum_sample_per_variant=minimum_sample,
        status="preregistered",
        registration_hash=_registration_hash(registration),
        created_by=actor.user_id[:36],
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ExperimentConflict(
            "An experiment with this key already exists"
        ) from None

    await record_admin_audit(
        db,
        actor=actor,
        action="admin.experiment.create",
        target_type="admin_experiment",
        target_id=row.id,
        reason=cleaned_reason,
        after={
            "experiment_key": row.experiment_key,
            "primary_metric": row.primary_metric,
            "guardrail_metrics": list(row.guardrail_metrics),
            "minimum_sample_per_variant": int(row.minimum_sample_per_variant),
            "flag_key": row.flag_key,
            "registration_hash": row.registration_hash,
            "status": row.status,
        },
        metadata={"experiment_key": row.experiment_key},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return experiment_summary(row)


async def list_experiments(
    db: AsyncSession,
    *,
    status: str | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    if status is not None and status not in STATUSES:
        raise ExperimentValidationError("Unknown experiment status")
    if limit < MIN_LIST_LIMIT or limit > MAX_LIST_LIMIT:
        raise ExperimentValidationError(
            f"limit must be between {MIN_LIST_LIMIT} and {MAX_LIST_LIMIT}"
        )
    if offset < 0:
        raise ExperimentValidationError("offset must be non-negative")

    statement = select(AdminExperiment)
    count_statement = select(func.count()).select_from(AdminExperiment)
    if status is not None:
        statement = statement.where(AdminExperiment.status == status)
        count_statement = count_statement.where(AdminExperiment.status == status)
    total = int((await db.execute(count_statement)).scalar_one())
    rows = (
        await db.execute(
            statement.order_by(
                AdminExperiment.created_at.desc(), AdminExperiment.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    sample_counts: dict[str, dict[str, int]] = {}
    if rows:
        experiment_ids = [row.id for row in rows]
        sample_rows = (
            await db.execute(
                select(
                    AdminExperimentExposure.experiment_id,
                    AdminExperimentExposure.variant,
                    func.count(func.distinct(AdminExperimentExposure.user_id)),
                )
                .where(AdminExperimentExposure.experiment_id.in_(experiment_ids))
                .group_by(
                    AdminExperimentExposure.experiment_id,
                    AdminExperimentExposure.variant,
                )
            )
        ).all()
        for experiment_id, variant, count in sample_rows:
            sample_counts.setdefault(str(experiment_id), {})[str(variant)] = int(count)

    return {
        "experiments": [
            experiment_summary(row, sample_counts=sample_counts.get(row.id, {}))
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "statuses": list(STATUSES),
        "minimum_group_size": MIN_GROUP_SIZE,
        "outcome_horizon_days": OUTCOME_HORIZON_DAYS,
        "catalog": experiment_catalog(),
        "generated_at": _now().isoformat(),
    }


async def _sample_counts(
    db: AsyncSession, experiment_id: str
) -> dict[str, int]:
    rows = (
        await db.execute(
            select(
                AdminExperimentExposure.variant,
                func.count(func.distinct(AdminExperimentExposure.user_id)),
            )
            .where(AdminExperimentExposure.experiment_id == experiment_id)
            .group_by(AdminExperimentExposure.variant)
        )
    ).all()
    return {str(variant): int(count) for variant, count in rows}


async def get_experiment_detail(
    db: AsyncSession, *, experiment_id: str
) -> dict[str, Any]:
    row = await _get_experiment(db, experiment_id)
    counts = await _sample_counts(db, row.id)
    return experiment_summary(row, sample_counts=counts)


async def start_experiment(
    db: AsyncSession,
    *,
    experiment_id: str,
    actor: AdminActor,
    reason: Any,
    confirm: Any,
    request=None,
) -> dict[str, Any]:
    if confirm is not True:
        raise ExperimentValidationError("Explicit confirmation is required")
    cleaned_reason = _clean_reason(reason)
    row = await _get_experiment(db, experiment_id, for_update=True)
    if row.status != "preregistered":
        raise ExperimentConflict(
            "Only a preregistered experiment can be started; stopped experiments cannot be restarted"
        )

    now = _now()
    row.status = "running"
    row.started_by = actor.user_id[:36]
    row.started_at = now
    row.updated_at = now
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.experiment.start",
        target_type="admin_experiment",
        target_id=row.id,
        reason=cleaned_reason,
        before={"status": "preregistered"},
        after={
            "status": "running",
            "started_at": now,
            "started_by": row.started_by,
            "registration_hash": row.registration_hash,
        },
        metadata={"experiment_key": row.experiment_key},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return experiment_summary(row)


async def stop_experiment(
    db: AsyncSession,
    *,
    experiment_id: str,
    actor: AdminActor,
    reason: Any,
    confirm: Any,
    revert_assignments: bool = True,
    request=None,
) -> dict[str, Any]:
    if confirm is not True:
        raise ExperimentValidationError("Explicit confirmation is required")
    if type(revert_assignments) is not bool:
        raise ExperimentValidationError("revert_assignments must be a boolean")
    cleaned_reason = _clean_reason(reason)
    row = await _get_experiment(db, experiment_id, for_update=True)
    if row.status != "running":
        raise ExperimentConflict("Only a running experiment can be stopped")

    now = _now()
    row.status = "stopped"
    row.stopped_by = actor.user_id[:36]
    row.stopped_at = now
    row.stop_reason = cleaned_reason
    row.updated_at = now

    reverted = 0
    if revert_assignments:
        result = await db.execute(
            update(AdminExperimentAssignment)
            .where(
                AdminExperimentAssignment.experiment_id == row.id,
                AdminExperimentAssignment.reverted_at.is_(None),
            )
            .values(reverted_at=now)
        )
        reverted = int(result.rowcount or 0)

    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.experiment.stop",
        target_type="admin_experiment",
        target_id=row.id,
        reason=cleaned_reason,
        before={"status": "running"},
        after={
            "status": "stopped",
            "stopped_at": now,
            "stopped_by": row.stopped_by,
            "revert_assignments": revert_assignments,
            "reverted_assignments": reverted,
            "registration_hash": row.registration_hash,
        },
        metadata={"experiment_key": row.experiment_key},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    summary = experiment_summary(
        row, sample_counts=await _sample_counts(db, row.id)
    )
    summary["reverted_assignments"] = reverted
    return summary


async def revert_experiment_assignments(
    db: AsyncSession,
    *,
    experiment_id: str,
    actor: AdminActor,
    reason: Any,
    confirm: Any,
    request=None,
) -> dict[str, Any]:
    """Revert any remaining assignments after a stop, without changing a flag."""

    if confirm is not True:
        raise ExperimentValidationError("Explicit confirmation is required")
    cleaned_reason = _clean_reason(reason)
    row = await _get_experiment(db, experiment_id, for_update=True)
    if row.status != "stopped":
        raise ExperimentConflict(
            "Assignments can only be reverted after the experiment is stopped"
        )

    now = _now()
    result = await db.execute(
        update(AdminExperimentAssignment)
        .where(
            AdminExperimentAssignment.experiment_id == row.id,
            AdminExperimentAssignment.reverted_at.is_(None),
        )
        .values(reverted_at=now)
    )
    reverted = int(result.rowcount or 0)
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.experiment.revert",
        target_type="admin_experiment",
        target_id=row.id,
        reason=cleaned_reason,
        before={"status": "stopped", "reverted_assignments": "open"},
        after={"reverted_assignments": reverted},
        metadata={"experiment_key": row.experiment_key},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    summary = experiment_summary(row, sample_counts=await _sample_counts(db, row.id))
    summary["reverted_assignments"] = reverted
    return summary


def _choose_variant(
    variants: Sequence[Mapping[str, Any]], bucket: int
) -> Mapping[str, Any]:
    cumulative = 0
    for variant in variants:
        cumulative += int(variant["weight"])
        if bucket < cumulative:
            return variant
    return variants[-1]


def assignment_bucket(experiment_id: str, user_id: str) -> int:
    """Stable 0-99 bucket for one experiment/account pair."""

    digest = hashlib.sha256(
        f"{experiment_id}:{user_id}".encode("utf-8")
    ).hexdigest()
    return int(digest[:8], 16) % 100


def _comparison(
    treatment: Mapping[str, Any],
    control: Mapping[str, Any],
    *,
    ready: bool,
) -> dict[str, Any]:
    numerator = treatment.get("numerator")
    denominator = treatment.get("denominator")
    control_numerator = control.get("numerator")
    control_denominator = control.get("denominator")
    suppressed = bool(treatment.get("suppressed") or control.get("suppressed"))
    if (
        not ready
        or suppressed
        or numerator is None
        or denominator is None
        or control_numerator is None
        or control_denominator is None
        or denominator == 0
        or control_denominator == 0
    ):
        return {
            "lift_pp": None,
            "relative_lift_pct": None,
            "ci_low_pp": None,
            "ci_high_pp": None,
            "confidence_level": CONFIDENCE_LEVEL,
            "comparable": False,
            "suppressed": suppressed,
            "method": "wald_two_proportion",
            "approximate": True,
        }

    treatment_rate = float(numerator) / float(denominator)
    control_rate = float(control_numerator) / float(control_denominator)
    difference = (treatment_rate - control_rate) * 100.0
    standard_error = math.sqrt(
        treatment_rate * (1.0 - treatment_rate) / denominator
        + control_rate * (1.0 - control_rate) / control_denominator
    ) * 100.0
    return {
        "lift_pp": round(difference, 2),
        "relative_lift_pct": (
            round((treatment_rate - control_rate) / control_rate * 100.0, 2)
            if control_rate > 0
            else None
        ),
        "ci_low_pp": round(difference - Z_95 * standard_error, 2),
        "ci_high_pp": round(difference + Z_95 * standard_error, 2),
        "confidence_level": CONFIDENCE_LEVEL,
        "comparable": True,
        "suppressed": False,
        "method": "wald_two_proportion",
        "approximate": True,
    }


def _metric_payload(
    definition: Mapping[str, Any],
    *,
    cohorts: Mapping[str, Mapping[str, Mapping[str, Any]]],
    outcome: Mapping[str, Mapping[str, list[datetime]]],
    report_end: datetime,
    ready: bool,
    variant_labels: Mapping[str, str],
) -> dict[str, Any]:
    cells: dict[str, dict[str, Any]] = {}
    for variant_key, cohort in cohorts.items():
        cells[variant_key] = _metric_cell(
            *_metric_counts(
                str(definition["key"]),
                cohort,
                outcome,
                report_end,
            ),
            group_suppressed=_group_suppressed(len(cohort)),
        )

    comparisons: list[dict[str, Any]] = []
    control_cell = cells.get(CONTROL_VARIANT)
    for variant_key, cell in cells.items():
        if variant_key == CONTROL_VARIANT or control_cell is None:
            continue
        comparison = _comparison(cell, control_cell, ready=ready)
        comparisons.append(
            {
                "variant": variant_key,
                "variant_label": variant_labels.get(variant_key, variant_key),
                "control_variant": CONTROL_VARIANT,
                "control_label": variant_labels.get(CONTROL_VARIANT, CONTROL_VARIANT),
                **comparison,
            }
        )

    return {
        "key": str(definition["key"]),
        "label": str(definition["label"]),
        "kind": str(definition["kind"]),
        "direction": str(definition["direction"]),
        "definition": str(definition["definition"]),
        "cells": cells,
        "comparisons": comparisons,
        "ready": ready,
        "suppressed": all(cell["suppressed"] for cell in cells.values())
        if cells
        else True,
    }


async def experiment_results(
    db: AsyncSession,
    *,
    experiment_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    row = await _get_experiment(db, experiment_id)
    current = now or _now()
    start = _as_aware(row.started_at)

    exposure_statement = select(
        AdminExperimentExposure.user_id,
        AdminExperimentExposure.variant,
        AdminExperimentExposure.exposed_at,
    ).where(
        AdminExperimentExposure.experiment_id == row.id,
        AdminExperimentExposure.exposed_at <= current,
    )
    if row.stopped_at is not None:
        exposure_statement = exposure_statement.where(
            AdminExperimentExposure.exposed_at <= _as_aware(row.stopped_at)
        )
    if start is not None:
        exposure_statement = exposure_statement.where(
            AdminExperimentExposure.exposed_at >= start
        )
    exposure_rows = (
        await db.execute(
            exposure_statement.order_by(
                AdminExperimentExposure.exposed_at,
                AdminExperimentExposure.id,
            )
        )
    ).all()

    subjects: dict[str, dict[str, Any]] = {}
    for user_id, variant, exposed_at in exposure_rows:
        if user_id is None or not isinstance(exposed_at, datetime):
            continue
        subject = str(user_id)
        variant_key = str(variant)
        entry = subjects.get(subject)
        if entry is None:
            subjects[subject] = {
                "first_at": exposed_at,
                "variant": variant_key,
                "events": 1,
            }
        else:
            entry["events"] += 1

    variant_labels = {
        str(variant["key"]): str(variant["label"])
        for variant in row.variants or []
    }
    cohorts: dict[str, dict[str, Mapping[str, Any]]] = {
        str(variant["key"]): {} for variant in row.variants or []
    }
    raw_counts: dict[str, int] = {key: 0 for key in cohorts}
    for subject, entry in subjects.items():
        variant_key = str(entry["variant"])
        if variant_key not in cohorts:
            continue
        cohorts[variant_key][subject] = entry
        raw_counts[variant_key] += 1

    sample = _sample_payload(
        row,
        raw_counts,
        minimum_sample=int(row.minimum_sample_per_variant),
    )
    ready = bool(
        row.status != "preregistered"
        and sample["minimum_sample_met"]
        and sample["sample_size"] is not None
    )

    outcome = (
        await _load_outcomes(db, set(subjects), current) if subjects else {}
    )

    primary_definition = METRIC_BY_KEY.get(row.primary_metric)
    if primary_definition is None:
        raise ExperimentValidationError("The registered primary metric is unknown")
    primary = _metric_payload(
        primary_definition,
        cohorts=cohorts,
        outcome=outcome,
        report_end=current,
        ready=ready,
        variant_labels=variant_labels,
    )
    guardrails = [
        _metric_payload(
            METRIC_BY_KEY[key],
            cohorts=cohorts,
            outcome=outcome,
            report_end=current,
            ready=ready,
            variant_labels=variant_labels,
        )
        for key in row.guardrail_metrics or []
        if key in METRIC_BY_KEY
    ]

    if row.status == "preregistered":
        message = "The experiment is pre-registered but has not started; no variants are assigned."
    elif not sample["minimum_sample_met"]:
        message = (
            "The pre-registered minimum sample per variant has not been reached. "
            "No lift or confidence interval is published."
        )
    else:
        message = (
            "Fixed-horizon comparison of the pre-registered primary metric. "
            "No winner is declared and no variant is rolled out automatically."
        )

    summary = experiment_summary(row, sample_counts=raw_counts)
    return {
        "experiment": summary,
        "analysis_window": {
            "started_at": _iso(row.started_at),
            "stopped_at": _iso(row.stopped_at),
            "as_of": current.isoformat(),
            "analysis_end": current.isoformat(),
            "outcome_horizon_days": OUTCOME_HORIZON_DAYS,
        },
        "sample": sample,
        "ready": ready,
        "primary_metric": primary,
        "guardrails": guardrails,
        "claim": dict(_CLAIM),
        "message": message,
        "notes": [
            "Cohorts are assigned by a stable first-party hash, not self-selection.",
            "Outcomes run from first exposure until the earlier of seven days and the analysis time.",
            "Groups with 1-4 subjects and rates below the five-user floor are hidden.",
            "Confidence intervals use an approximate two-proportion Wald method and are published only after the minimum sample.",
            "A stopped experiment keeps its assignment evidence but assigns no new subjects.",
        ],
        "generated_at": current.isoformat(),
    }


async def record_assignments(
    db: AsyncSession,
    *,
    user_id: str,
    anonymous_id: Any,
    experiment_keys: Sequence[Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assign and expose the signed-in subject for running experiments.

    Only running experiments are considered. A linked operational flag that is
    off (or unreadable) skips the experiment so a kill switch always wins.
    """

    canonical_anonymous_id = normalize_identifier(anonymous_id)
    if canonical_anonymous_id is None:
        raise ExperimentValidationError(
            "anonymous_id must be a bounded opaque identifier"
        )
    decision = await _latest_consent_decision(db, canonical_anonymous_id)
    if decision != "granted":
        raise ConsentRequiredError("analytics consent is required")

    rejected = 0
    keys: list[str] | None = None
    if experiment_keys is not None:
        if not isinstance(experiment_keys, (list, tuple)):
            raise ExperimentValidationError("experiment_keys must be a list")
        if len(experiment_keys) > MAX_ASSIGNMENT_KEYS:
            raise ExperimentValidationError(
                f"experiment_keys cannot contain more than {MAX_ASSIGNMENT_KEYS} entries"
            )
        cleaned: list[str] = []
        for raw in experiment_keys:
            try:
                key = normalize_experiment_key(raw)
            except ExperimentValidationError:
                rejected += 1
                continue
            if key not in cleaned:
                cleaned.append(key)
        keys = cleaned

    if keys is not None:
        if not keys:
            return {
                "assignments": [],
                "accepted": 0,
                "duplicate": 0,
                "rejected": rejected,
                "skipped": 0,
                "window": (now or _now()).astimezone(timezone.utc).date().isoformat(),
            }
        # Resolve every syntactically valid key so an unknown experiment is
        # counted as rejected while a known stopped/preregistered one is skipped.
        statement = select(AdminExperiment).where(
            AdminExperiment.experiment_key.in_(keys)
        )
    else:
        statement = select(AdminExperiment).where(AdminExperiment.status == "running")
    experiments = (
        await db.execute(statement.order_by(AdminExperiment.created_at))
    ).scalars().all()
    found_keys = {row.experiment_key for row in experiments}
    if keys is not None:
        rejected += sum(1 for key in keys if key not in found_keys)

    current = now or _now()
    window_date: date = current.astimezone(timezone.utc).date()
    assignments: list[dict[str, Any]] = []
    accepted = 0
    duplicate = 0
    skipped = 0

    for row in experiments:
        if row.status != "running":
            skipped += 1
            continue
        if row.flag_key:
            enabled = await feature_flag_service.get_flag(row.flag_key, db)
            if not enabled:
                skipped += 1
                continue

        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"experiment-assignment:{row.id}:{user_id}"},
        )
        assignment = (
            await db.execute(
                select(AdminExperimentAssignment).where(
                    AdminExperimentAssignment.experiment_id == row.id,
                    AdminExperimentAssignment.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

        if assignment is None:
            bucket = assignment_bucket(row.id, user_id)
            variant = _choose_variant(row.variants or [], bucket)
            assignment = AdminExperimentAssignment(
                id=str(uuid.uuid4()),
                experiment_id=row.id,
                user_id=user_id,
                variant=str(variant["key"]),
                bucket=bucket,
                assigned_at=current,
            )
            db.add(assignment)
            await db.flush()
        elif assignment.reverted_at is not None:
            skipped += 1
            continue

        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"experiment-exposure:{row.id}:{user_id}:{window_date.isoformat()}"},
        )
        exposure = (
            await db.execute(
                select(AdminExperimentExposure.id)
                .where(
                    AdminExperimentExposure.experiment_id == row.id,
                    AdminExperimentExposure.user_id == user_id,
                    AdminExperimentExposure.window_date == window_date,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        exposure_recorded = False
        if exposure is None:
            db.add(
                AdminExperimentExposure(
                    id=str(uuid.uuid4()),
                    experiment_id=row.id,
                    assignment_id=assignment.id,
                    user_id=user_id,
                    variant=assignment.variant,
                    window_date=window_date,
                    source=EXPERIMENT_SOURCE,
                    exposed_at=current,
                )
            )
            accepted += 1
            exposure_recorded = True
        else:
            duplicate += 1

        variant_definition = next(
            (
                variant
                for variant in row.variants or []
                if str(variant["key"]) == assignment.variant
            ),
            None,
        )
        flag_override = None
        if row.flag_key and variant_definition is not None:
            flag_override = variant_definition.get("flag_enabled")
            if flag_override is not None:
                flag_override = bool(flag_override)

        assignments.append(
            {
                "experiment_key": row.experiment_key,
                "variant": assignment.variant,
                "variant_label": (
                    str(variant_definition["label"])
                    if variant_definition is not None
                    else assignment.variant
                ),
                "flag_key": row.flag_key,
                "flag_override": flag_override,
                "exposure_recorded": exposure_recorded,
            }
        )

    # Commit even when every exposure was deduplicated so advisory locks are
    # released with the request transaction.
    await db.commit()
    return {
        "assignments": assignments,
        "accepted": accepted,
        "duplicate": duplicate,
        "rejected": rejected,
        "skipped": skipped,
        "window": window_date.isoformat(),
    }
