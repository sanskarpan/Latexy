"""Database-linearized terminal decisions for metered and durable jobs.

Redis owns admission leases, but a Redis lease is not a transaction with the
database or object storage.  This module provides the database arbiter that
workers, cancellation, and cleanup must lock before making a terminal decision
or refunding a receipt.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..core.logging import get_logger
from ..database.models import Compilation, CoverLetter, JobFinalization
from ..services.storage_service import compilation_pdf_key

logger = get_logger(__name__)

FINALIZATION_TTL = timedelta(days=40)
MAX_RESULT_BYTES = 512 * 1024
MAX_LATEX_BYTES = 384 * 1024
MAX_GENERATED_TEXT_BYTES = 128 * 1024
MAX_PDF_SIZE = 20 * 1024 * 1024
_PDF_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PDF_PATH_RE = re.compile(r"^compilations/[A-Za-z0-9_-]{1,255}/finalization-[0-9a-f]{32}\.pdf$")
_REQUIRED_OUTPUT_LIMITS = {
    "optimized_latex": MAX_LATEX_BYTES,
    "latex_content": MAX_LATEX_BYTES,
    "cover_letter_latex": MAX_LATEX_BYTES,
    "fitted_latex": MAX_LATEX_BYTES,
}
_BOUNDED_OMITTED_OUTPUT_FIELDS = frozenset(
    {
        *_REQUIRED_OUTPUT_LIMITS,
        "deep_analysis",
        "keywords",
        "requirements",
        "preferred_qualifications",
        "detected_industry",
        "analysis_metrics",
        "projects",
        "ats_details",
        "artifacts",
        "ats_compatibility",
        "job_match",
        "multi_dim_scores",
        "changes_made",
        "detailed_analysis",
        "extracted_text",
        "overall_feedback",
        "calibration_statement",
    }
)
_TYPED_REQUIRED_OUTPUTS = {
    "ats_deep_analysis": ("deep_analysis",),
    "cover_letter_generation": ("cover_letter_latex",),
    "job_description_analysis": (
        "keywords",
        "requirements",
        "preferred_qualifications",
        "detected_industry",
        "analysis_metrics",
    ),
}


class FinalizationState(str, Enum):
    PENDING = "pending"
    COMMITTING = "committing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    FENCED = "fenced"


class FinalizationOutcome(str, Enum):
    ACCEPTED = "accepted"
    ALREADY_COMPLETED = "already_completed"
    NO_ROW = "no_row"
    CANCELLED = "cancelled"
    FENCED = "fenced"
    FAILED = "failed"
    BUSY = "busy"


def _expiry() -> datetime:
    # Retention is not a lease decision. Lease predicates below use
    # ``clock_timestamp()`` so client clock skew and long transactions cannot
    # authorize a stale owner.
    return datetime.now(timezone.utc) + FINALIZATION_TTL


def _bounded_text(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", errors="ignore")


_SENSITIVE_RESULT_MARKERS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "credential",
    "prompt",
    "task_arg",
    "user_id",
    "device_fingerprint",
    "input",
    "raw_error",
    "error",
    "exception",
    "traceback",
    "diagnostic",
)


def _safe_generated_value(value: Any, *, depth: int = 0) -> Any:
    """Bound nested generated output while rejecting request/provider data."""
    if depth > 3:
        return None
    if isinstance(value, str):
        return _bounded_text(value, 2048)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) <= 10**12:
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_safe_generated_value(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in list(value.items())[:100]:
            if not isinstance(key, str):
                continue
            lowered = key.lower()
            if any(marker in lowered for marker in _SENSITIVE_RESULT_MARKERS):
                continue
            safe[key[:128]] = _safe_generated_value(item, depth=depth + 1)
        return safe
    return None


def _bounded_signal_list(value: Any, *, limit: int = 50, text_limit: int = 2000) -> list[str]:
    """Retain only the bounded string-list fields in a validated ATS DTO."""
    if not isinstance(value, list):
        return []
    return [item for item in value[:limit] if isinstance(item, str) and len(item.encode("utf-8")) <= text_limit]


_JD_SIGNAL_FIELDS = ("keywords", "requirements", "preferred_qualifications")
_JD_ANALYSIS_METRIC_FIELDS = ("word_count", "sentence_count", "keyword_count")


def _bounded_jd_signal_list(value: Any) -> list[str] | None:
    """Preserve a JD string array exactly, or reject the whole field.

    JD analysis is a typed worker result, so silently filtering malformed
    items or truncating long requirements would make a terminal success look
    complete while losing user-visible analysis.  Keep the list small and
    bounded by aggregate UTF-8 bytes, but never rewrite an individual string.
    """
    if not isinstance(value, list) or len(value) > 100:
        return None
    retained: list[str] = []
    total_bytes = 0
    for item in value:
        if not isinstance(item, str):
            return None
        item_bytes = len(item.encode("utf-8"))
        total_bytes += item_bytes
        if total_bytes > MAX_GENERATED_TEXT_BYTES:
            return None
        retained.append(item)
    return retained


def _bounded_jd_analysis_metrics(value: Any) -> dict[str, int] | None:
    """Keep only the closed, non-negative integer JD metric contract."""
    if not isinstance(value, dict):
        return None
    metrics: dict[str, int] = {}
    for field in _JD_ANALYSIS_METRIC_FIELDS:
        number = value.get(field)
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            return None
        metrics[field] = number
    return metrics


def _invalid_jd_output_fields(result: dict[str, Any]) -> list[str]:
    """Identify present JD typed fields that cannot be faithfully bounded."""
    invalid: list[str] = []
    for field in _JD_SIGNAL_FIELDS:
        if field in result and _bounded_jd_signal_list(result[field]) is None:
            invalid.append(field)
    if "analysis_metrics" in result and _bounded_jd_analysis_metrics(result["analysis_metrics"]) is None:
        invalid.append("analysis_metrics")
    return invalid


def _bounded_score(value: Any) -> int | float | None:
    """Keep a finite ATS score in the provider contract's 0..100 range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if not 0 <= value <= 100:
        return None
    return value


def _bounded_deep_analysis(value: Any) -> dict[str, Any] | None:
    """Serialize the known DeepATSResponse shape without losing nested guidance.

    ``_safe_generated_value`` intentionally caps generic objects at a shallow
    depth. Deep ATS sections are a known, validated DTO whose string arrays are
    one level deeper, so sanitize that shape explicitly rather than widening the
    generic recursion and risking retention of arbitrary provider/request data.
    """
    if not isinstance(value, dict):
        return None

    overall_score = _bounded_score(value.get("overall_score"))
    overall_feedback = _bounded_text(value.get("overall_feedback"), 8000)
    if overall_score is None or overall_feedback is None:
        return None

    sections: list[dict[str, Any]] = []
    raw_sections = value.get("sections")
    if isinstance(raw_sections, list):
        for raw_section in raw_sections[:30]:
            if not isinstance(raw_section, dict):
                continue
            # ``DeepATSResponse`` emits ``name``; accept the legacy
            # ``section_name`` spelling too because older worker/provider
            # envelopes used it before validation normalized the DTO.
            name = _bounded_text(raw_section.get("name") or raw_section.get("section_name"), 160)
            score = _bounded_score(raw_section.get("score"))
            if not name or score is None:
                continue
            # Canonical DTO fields win even when explicitly empty. Legacy
            # issues/suggestions are retained under their own bounded names;
            # issues must never be reclassified as positive strengths.
            strengths = _bounded_signal_list(raw_section.get("strengths"))
            improvements = _bounded_signal_list(raw_section.get("improvements"))
            legacy_issues = _bounded_signal_list(raw_section.get("issues"))
            legacy_suggestions = _bounded_signal_list(raw_section.get("suggestions"))
            section: dict[str, Any] = {
                "name": name,
                "score": score,
                "strengths": strengths,
                "improvements": improvements,
            }
            # Preserve the legacy field names as well when they were the
            # source shape. They are part of the bounded Deep ATS DTO, not an
            # open-ended pass-through of provider keys.
            if "section_name" in raw_section:
                section["section_name"] = name
            if "issues" in raw_section:
                section["issues"] = legacy_issues
            if "suggestions" in raw_section:
                section["suggestions"] = legacy_suggestions
            rewrite = _bounded_text(raw_section.get("rewrite_suggestion"), 8000)
            if rewrite is not None:
                section["rewrite_suggestion"] = rewrite
            sections.append(section)

    raw_compatibility = value.get("ats_compatibility")
    compatibility: dict[str, Any] | None = None
    if isinstance(raw_compatibility, dict):
        score = _bounded_score(raw_compatibility.get("score"))
        if score is not None:
            compatibility = {
                "score": score,
                "issues": _bounded_signal_list(raw_compatibility.get("issues")),
                "keyword_gaps": _bounded_signal_list(raw_compatibility.get("keyword_gaps")),
            }
    if compatibility is None:
        return None

    bounded: dict[str, Any] = {
        "overall_score": overall_score,
        "overall_feedback": overall_feedback,
        "sections": sections,
        "ats_compatibility": compatibility,
        "job_match": None,
    }

    raw_job_match = value.get("job_match")
    if isinstance(raw_job_match, dict):
        score = _bounded_score(raw_job_match.get("score"))
        recommendation = _bounded_text(raw_job_match.get("recommendation"), 8000)
        if score is not None and recommendation is not None:
            bounded["job_match"] = {
                "score": score,
                "matched_requirements": _bounded_signal_list(raw_job_match.get("matched_requirements")),
                "missing_requirements": _bounded_signal_list(raw_job_match.get("missing_requirements")),
                "recommendation": recommendation,
            }

    raw_multi_dim = value.get("multi_dim_scores")
    if isinstance(raw_multi_dim, dict):
        multi_dim: dict[str, int | float] = {}
        for key, score in list(raw_multi_dim.items())[:100]:
            if not isinstance(key, str):
                continue
            bounded_score = _bounded_score(score)
            if bounded_score is not None:
                multi_dim[key[:128]] = bounded_score
        bounded["multi_dim_scores"] = multi_dim

    for key in ("industry_key", "industry_label"):
        text = _bounded_text(value.get(key), 255)
        if text is not None:
            bounded[key] = text

    for key in ("tokens_used",):
        number = value.get(key)
        if isinstance(number, int) and not isinstance(number, bool) and number >= 0:
            bounded[key] = number
    analysis_time = value.get("analysis_time")
    if isinstance(analysis_time, (int, float)) and not isinstance(analysis_time, bool) and math.isfinite(analysis_time):
        bounded["analysis_time"] = analysis_time

    return bounded


def _oversized_required_outputs(result: Optional[dict[str, Any]]) -> list[str]:
    if not isinstance(result, dict):
        return []
    return [
        key
        for key, limit in _REQUIRED_OUTPUT_LIMITS.items()
        if isinstance(result.get(key), str) and len(result[key].encode("utf-8")) > limit
    ]


def _bounded_omitted_output_fields(value: Any) -> list[str]:
    """Keep only known generated-output names from an earlier bounded pass."""
    if not isinstance(value, list):
        return []
    retained: list[str] = []
    for item in value:
        if isinstance(item, str) and item in _BOUNDED_OMITTED_OUTPUT_FIELDS and item not in retained:
            retained.append(item)
    return retained


def typed_required_output_fields(job_type: Optional[str]) -> tuple[str, ...]:
    """Return the bounded output fields required by a typed terminal family."""
    return _TYPED_REQUIRED_OUTPUTS.get(job_type or "", ())


def typed_missing_output_fields(job_type: Optional[str], payload: Optional[dict[str, Any]]) -> list[str]:
    """Validate required fields on an already-bounded typed result payload."""
    if not isinstance(payload, dict):
        return list(typed_required_output_fields(job_type))
    missing: list[str] = []
    for field in typed_required_output_fields(job_type):
        value = payload.get(field)
        if field == "deep_analysis":
            valid = isinstance(value, dict) and bool(value)
        elif field in {"keywords", "requirements", "preferred_qualifications"}:
            valid = _bounded_jd_signal_list(value) is not None
        elif field == "analysis_metrics":
            valid = _bounded_jd_analysis_metrics(value) is not None
        else:
            valid = isinstance(value, str) and bool(value.strip())
        if not valid:
            missing.append(field)
    return missing


def bounded_result_payload(job_id: str, result: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Keep only bounded generated output needed for crash recovery.

    Deliberately excludes task arguments, provider diagnostics, credentials,
    and arbitrary ``error``/``error_message`` fields.
    """
    result = result if isinstance(result, dict) else {}
    oversized_outputs = _oversized_required_outputs(result)
    omitted_outputs = _bounded_omitted_output_fields(result.get("omitted_output_fields"))
    for field in (*oversized_outputs, *_invalid_jd_output_fields(result)):
        if field not in omitted_outputs:
            omitted_outputs.append(field)
    recovery_complete = result.get("recovery_complete") is not False and not omitted_outputs
    payload: dict[str, Any] = {
        "job_id": _bounded_text(job_id, 255) or "unknown",
        "success": result.get("success") is True,
        "recovery_complete": recovery_complete,
    }
    if omitted_outputs:
        payload["omitted_output_fields"] = omitted_outputs
    integer_fields = ("tokens_used", "page_count", "slide_count", "pdf_size")
    float_fields = ("compilation_time", "optimization_time", "ats_score")
    boolean_fields = ("is_beamer", "cancelled")
    for key in (
        "pdf_job_id",
        *integer_fields,
        *float_fields,
        *boolean_fields,
    ):
        value = result.get(key)
        if value is None:
            payload[key] = None
        elif key == "pdf_job_id" and isinstance(value, str):
            value = _bounded_text(value, 128)
            if value is not None:
                payload[key] = value
        elif key in integer_fields and isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            payload[key] = value
        elif key in float_fields and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            payload[key] = value
        elif key in boolean_fields and isinstance(value, bool):
            payload[key] = value
    error_code = _bounded_text(result.get("error_code"), 64)
    if error_code:
        payload["error_code"] = error_code
    latex = result.get("optimized_latex")
    # Never truncate source text: a truncated LaTeX document is not a valid
    # generated output. Oversized output is recoverable from the bounded event
    # store, but is intentionally omitted from this durable row.
    if isinstance(latex, str) and len(latex.encode("utf-8")) <= MAX_LATEX_BYTES:
        payload["optimized_latex"] = latex
    changes = result.get("changes_made")
    if isinstance(changes, list):
        payload["changes_made"] = [
            {
                key: _bounded_text(item.get(key), 512) or ""
                for key in ("section", "change_type", "reason")
                if isinstance(item, dict) and isinstance(item.get(key), str)
            }
            for item in changes[:200]
            if isinstance(item, dict)
        ]
    generated_text_fields = {
        "cover_letter_latex": MAX_LATEX_BYTES,
        "latex_content": MAX_LATEX_BYTES,
        "fitted_latex": MAX_LATEX_BYTES,
        "extracted_text": MAX_GENERATED_TEXT_BYTES,
        "detailed_analysis": MAX_GENERATED_TEXT_BYTES,
        "overall_feedback": 16 * 1024,
        "calibration_statement": 8 * 1024,
    }
    for key, limit in generated_text_fields.items():
        value = result.get(key)
        if isinstance(value, str) and len(value.encode("utf-8")) <= limit:
            payload[key] = value

    for key in (
        "cover_letter_id",
        "resume_id",
        "result_key",
        "custom_key",
        "source_format",
        "target_format",
        "file_name",
        "compiler",
        "industry_key",
        "industry_label",
        "locale_key",
        "locale_label",
        "detected_industry",
    ):
        value = result.get(key)
        if isinstance(value, str):
            bounded = _bounded_text(value, 255)
            if bounded is not None:
                payload[key] = bounded

    for key in ("generation_time", "conversion_time", "scoring_time", "analysis_time", "score_threshold"):
        value = result.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            payload[key] = value
    for key in ("tokens_total", "project_count", "fit_intensity", "fit_attempts"):
        value = result.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            payload[key] = value
    for key in ("auto_fit", "fit_succeeded"):
        value = result.get(key)
        if isinstance(value, bool):
            payload[key] = value

    for key in ("projects", "ats_compatibility", "job_match", "multi_dim_scores", "artifacts"):
        value = result.get(key)
        if isinstance(value, (dict, list)):
            payload[key] = _safe_generated_value(value)

    for key in _JD_SIGNAL_FIELDS:
        bounded = _bounded_jd_signal_list(result.get(key))
        if bounded is not None and key in result:
            payload[key] = bounded

    analysis_metrics = result.get("analysis_metrics")
    bounded_metrics = _bounded_jd_analysis_metrics(analysis_metrics)
    if bounded_metrics is not None:
        payload["analysis_metrics"] = bounded_metrics

    deep_analysis = _bounded_deep_analysis(result.get("deep_analysis"))
    if deep_analysis is not None:
        payload["deep_analysis"] = deep_analysis

    details = result.get("ats_details")
    if isinstance(details, dict):
        payload["ats_details"] = _safe_generated_value(details)
    # Deterministically discard optional fields until the hard bound is met;
    # unlike the old loop this always makes progress and never corrupts LaTeX.
    drop_order = (
        "ats_details",
        "analysis_metrics",
        "preferred_qualifications",
        "requirements",
        "keywords",
        "projects",
        "deep_analysis",
        "artifacts",
        "ats_compatibility",
        "job_match",
        "multi_dim_scores",
        "changes_made",
        "optimized_latex",
        "cover_letter_latex",
        "latex_content",
        "fitted_latex",
        "detailed_analysis",
        "extracted_text",
    )
    dropped_fields: list[str] = []
    for key in drop_order:
        if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) <= MAX_RESULT_BYTES:
            break
        if key in payload:
            payload.pop(key)
            dropped_fields.append(key)
    if dropped_fields:
        payload["recovery_complete"] = False
        payload["omitted_output_fields"] = sorted(
            set(payload.get("omitted_output_fields", [])) | set(dropped_fields)
        )
    return payload


def resume_content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _db_clock():
    """Use PostgreSQL wall-clock time, not the transaction start timestamp."""
    return func.clock_timestamp()


async def ensure_finalization(
    session,
    *,
    job_id: str,
    owner_token: str,
    owner_epoch: int,
    lease_expires_at: Optional[datetime],
    user_id: Optional[str] = None,
    compilation_id: Optional[str] = None,
    resume_id: Optional[str] = None,
    resume_apply_requested: bool = False,
    cover_letter_id: Optional[str] = None,
    cover_letter_apply_requested: bool = False,
) -> JobFinalization:
    """Create or lock a finalization row without reviving a tombstone."""
    if not isinstance(owner_token, str) or not owner_token:
        raise ValueError("owner_token is required")
    if owner_epoch < 0:
        raise ValueError("owner_epoch must be non-negative")
    await session.execute(
        pg_insert(JobFinalization)
        .values(
            id=str(uuid4()),
            job_id=job_id,
            owner_token=owner_token,
            owner_epoch=owner_epoch,
            state=FinalizationState.PENDING.value,
            lease_expires_at=lease_expires_at,
            user_id=user_id,
            compilation_id=compilation_id,
            resume_id=resume_id,
            resume_apply_requested=resume_apply_requested,
            cover_letter_id=cover_letter_id,
            cover_letter_applied=False,
            cover_letter_apply_requested=cover_letter_apply_requested,
            expires_at=_expiry(),
        )
        .on_conflict_do_nothing(index_elements=[JobFinalization.job_id])
    )
    row = await session.scalar(
        select(JobFinalization)
        .where(JobFinalization.job_id == job_id)
        .with_for_update()
    )
    if row is None:  # pragma: no cover - protected by the unique insert
        raise RuntimeError("finalization row disappeared after insert")
    if row.state != FinalizationState.PENDING.value:
        return row
    active_owner = await session.scalar(
        select(JobFinalization.id).where(
            JobFinalization.id == row.id,
            JobFinalization.lease_expires_at.is_not(None),
            JobFinalization.lease_expires_at > _db_clock(),
            JobFinalization.owner_token.is_not(None),
            JobFinalization.owner_token != owner_token,
        )
    )
    if active_owner:
        return row
    if owner_epoch >= row.owner_epoch:
        row.owner_token = owner_token
        row.owner_epoch = owner_epoch
        row.lease_expires_at = lease_expires_at
        row.user_id = row.user_id or user_id
        row.compilation_id = row.compilation_id or compilation_id
        row.resume_id = row.resume_id or resume_id
        row.resume_apply_requested = row.resume_apply_requested or resume_apply_requested
        row.cover_letter_id = row.cover_letter_id or cover_letter_id
        row.cover_letter_apply_requested = row.cover_letter_apply_requested or cover_letter_apply_requested
    return row


async def request_cancel(session, *, job_id: str, reason_code: str = "cancelled") -> FinalizationOutcome:
    """Linearize cancellation before any Redis refund or lifecycle mutation."""
    inserted_row_id = str(uuid4())
    await session.execute(
        pg_insert(JobFinalization)
        .values(
            id=inserted_row_id,
            job_id=job_id,
            state=FinalizationState.CANCELLED.value,
            terminal_result=FinalizationState.CANCELLED.value,
            cancel_requested=True,
            failure_code=_bounded_text(reason_code, 64),
            expires_at=_expiry(),
        )
        .on_conflict_do_nothing(index_elements=[JobFinalization.job_id])
    )
    row = await session.scalar(
        select(JobFinalization).where(JobFinalization.job_id == job_id).with_for_update()
    )
    if row is None:
        return FinalizationOutcome.NO_ROW
    if row.state == FinalizationState.COMPLETED.value:
        return FinalizationOutcome.ALREADY_COMPLETED
    if row.state in {FinalizationState.FAILED.value, FinalizationState.FENCED.value}:
        return FinalizationOutcome.FAILED

    # Compilation is the durable public status for PDF jobs. Lock it after
    # the arbiter row (the same order used by commit_success) so cancellation
    # cannot race a success commit or leave a processing row after a durable
    # CANCELLED decision. Non-PDF families have no Compilation row.
    compilation = await session.scalar(
        select(Compilation).where(Compilation.job_id == job_id).with_for_update()
    )
    if compilation is not None:
        # A populated compilation_id is an immutable identity assertion. Do
        # not mutate a same-job row if a legacy/corrupt arbiter points at a
        # different compilation record.
        if row.compilation_id is not None and str(row.compilation_id) != str(compilation.id):
            raise RuntimeError("finalization_compilation_identity_mismatch")
        for field in ("user_id", "resume_id"):
            expected = getattr(row, field, None)
            actual = getattr(compilation, field, None)
            if expected is not None and str(expected) != str(actual):
                raise RuntimeError("finalization_compilation_identity_mismatch")
        if compilation.status == "completed":
            # A completed Compilation is a winner even if an old arbiter row
            # was missing or still pending. Remove only a row inserted by
            # this call; never overwrite an existing durable decision.
            if row.id == inserted_row_id:
                await session.delete(row)
            return FinalizationOutcome.ALREADY_COMPLETED
        if compilation.status == "failed":
            if row.id == inserted_row_id:
                await session.delete(row)
            return FinalizationOutcome.FAILED
        if compilation.status != "cancelled":
            compilation.status = "cancelled"
            compilation.error_message = _bounded_text(reason_code, 255) or "cancelled"

    if row.state == FinalizationState.CANCELLED.value:
        if not isinstance(row.result_payload, dict):
            row.result_payload = bounded_result_payload(
                job_id,
                {"success": False, "job_id": job_id, "cancelled": True},
            )
        return FinalizationOutcome.CANCELLED
    row.cancel_requested = True
    row.state = FinalizationState.CANCELLED.value
    row.terminal_result = FinalizationState.CANCELLED.value
    row.failure_code = _bounded_text(reason_code, 64)
    # Cancellation is a durable terminal decision even when the worker never
    # starts. Store the canonical payload so REST/WS recovery can replay the
    # same cancelled result after Redis state/result expiry.
    row.result_payload = bounded_result_payload(
        job_id,
        {"success": False, "job_id": job_id, "cancelled": True},
    )
    row.decided_at = _db_clock()
    return FinalizationOutcome.CANCELLED


async def fence_finalization(
    session, *, job_id: str, reason_code: str = "lease_expired", owner_epoch: Optional[int] = None
) -> FinalizationOutcome:
    """Upsert a non-revivable tombstone, or fence an expired pending row."""
    await session.execute(
        pg_insert(JobFinalization)
        .values(
            id=str(uuid4()),
            job_id=job_id,
            state=FinalizationState.FENCED.value,
            terminal_result=FinalizationState.FAILED.value,
            cancel_requested=True,
            owner_epoch=owner_epoch or 0,
            failure_code=_bounded_text(reason_code, 64),
            expires_at=_expiry(),
        )
        .on_conflict_do_nothing(index_elements=[JobFinalization.job_id])
    )
    row = await session.scalar(
        select(JobFinalization).where(JobFinalization.job_id == job_id).with_for_update()
    )
    if row is None:
        return FinalizationOutcome.NO_ROW
    if row.state == FinalizationState.COMPLETED.value:
        return FinalizationOutcome.ALREADY_COMPLETED
    if row.state in {FinalizationState.FAILED.value, FinalizationState.CANCELLED.value}:
        return FinalizationOutcome.FAILED
    if row.state == FinalizationState.FENCED.value:
        # Fencing is an idempotent terminal decision.  A repeated cleanup
        # pass must not report a generic failure and accidentally skip the
        # already-established fence/refund protocol.
        return FinalizationOutcome.FENCED
    active = await session.scalar(
        select(JobFinalization.id).where(
            JobFinalization.id == row.id,
            JobFinalization.lease_expires_at.is_not(None),
            JobFinalization.lease_expires_at > _db_clock(),
        )
    )
    if active:
        return FinalizationOutcome.BUSY
    row.state = FinalizationState.FENCED.value
    row.terminal_result = FinalizationState.FAILED.value
    row.cancel_requested = True
    row.failure_code = _bounded_text(reason_code, 64)
    row.decided_at = _db_clock()
    return FinalizationOutcome.FENCED


async def commit_success(
    session,
    *,
    job_id: str,
    owner_token: str,
    owner_epoch: int,
    result_payload: Optional[dict[str, Any]],
    pdf_path: Optional[str] = None,
    pdf_sha256: Optional[str] = None,
    pdf_size: Optional[int] = None,
    compilation_time: Optional[float] = None,
    resume_id: Optional[str] = None,
    resume_user_id: Optional[str] = None,
    resume_content: Optional[str] = None,
    expected_resume_sha256: Optional[str] = None,
    cover_letter_id: Optional[str] = None,
    cover_letter_user_id: Optional[str] = None,
    cover_letter_content: Optional[str] = None,
    require_pdf: bool = False,
) -> FinalizationOutcome:
    """Commit generated resume/PDF/Compilation output in one DB transaction."""
    compilation = None

    def _record_rejected_terminal(code: str, *, fenced: bool = False) -> None:
        """Keep a replayable canonical payload with every arbiter rejection.

        A typed worker may be the only caller able to publish the terminal
        decision after this transaction.  Leaving ``result_payload`` NULL
        makes the durable FAILED/FENCED row impossible to replay and causes
        the Redis publisher's exact-canonical guard to reject the recovery
        attempt.  The payload is deliberately passed through the same bounded
        serializer used for successful output.
        """
        candidate = dict(result_payload) if isinstance(result_payload, dict) else {}
        candidate["success"] = False
        candidate["error_code"] = code
        row.result_payload = bounded_result_payload(job_id, candidate)
        row.state = FinalizationState.FENCED.value if fenced else FinalizationState.FAILED.value
        row.terminal_result = FinalizationState.FAILED.value
        row.cancel_requested = fenced
        row.failure_code = code
        row.decided_at = _db_clock()
        if not fenced and compilation is not None and compilation.status == "processing":
            # The owner/epoch capability was validated before this helper is
            # reached.  A rejected typed success (for example a Resume CAS
            # conflict) is itself a terminal compile outcome; leave no
            # processing Compilation row behind for cleanup to misclassify.
            compilation.status = "failed"
            compilation.error_message = code

    row = await session.scalar(
        select(JobFinalization).where(JobFinalization.job_id == job_id).with_for_update()
    )
    if row is None:
        return FinalizationOutcome.NO_ROW
    if row.state == FinalizationState.COMPLETED.value:
        return FinalizationOutcome.ALREADY_COMPLETED
    if row.state == FinalizationState.CANCELLED.value:
        return FinalizationOutcome.CANCELLED
    if row.state == FinalizationState.FAILED.value:
        return FinalizationOutcome.FAILED
    if row.state == FinalizationState.FENCED.value:
        return FinalizationOutcome.FENCED
    lease_active = await session.scalar(
        select(JobFinalization.id).where(
            JobFinalization.id == row.id,
            JobFinalization.lease_expires_at.is_not(None),
            JobFinalization.lease_expires_at > _db_clock(),
        )
    )
    owner_active = await session.scalar(
        select(JobFinalization.id).where(
            JobFinalization.id == row.id,
            JobFinalization.owner_token == owner_token,
            JobFinalization.owner_epoch == owner_epoch,
            JobFinalization.cancel_requested.is_(False),
            JobFinalization.lease_expires_at.is_not(None),
            JobFinalization.lease_expires_at > _db_clock(),
        )
    )
    if row.cancel_requested:
        return FinalizationOutcome.CANCELLED
    if not owner_active and lease_active:
        # Never let a stale worker fence a currently leased replacement owner.
        return FinalizationOutcome.BUSY
    if not owner_active or (require_pdf and (not pdf_path or not pdf_sha256 or not pdf_size)):
        _record_rejected_terminal("finalization_not_authorized", fenced=True)
        return FinalizationOutcome.FENCED
    compilation = await session.scalar(
        select(Compilation).where(Compilation.job_id == job_id).with_for_update()
    )
    if not isinstance(result_payload, dict) or result_payload.get("success") is not True:
        _record_rejected_terminal("invalid_success_payload")
        return FinalizationOutcome.FAILED
    oversized_outputs = _oversized_required_outputs(result_payload)
    if oversized_outputs:
        _record_rejected_terminal("generated_output_too_large")
        return FinalizationOutcome.FAILED
    # Build and validate the durable recovery payload before touching any
    # output row.  The bounded serializer can omit an otherwise individually
    # valid generated field when the aggregate payload exceeds the hard cap;
    # returning FAILED after mutating a Resume/CoverLetter/Compilation would
    # make those writes survive if the caller commits this terminal decision.
    bounded_payload = bounded_result_payload(job_id, result_payload)
    if bounded_payload.get("recovery_complete") is False:
        _record_rejected_terminal("recovery_output_too_large")
        return FinalizationOutcome.FAILED
    if typed_missing_output_fields(row.job_type, bounded_payload):
        _record_rejected_terminal("typed_output_missing")
        return FinalizationOutcome.FAILED
    if compilation is not None and (not pdf_path or not pdf_sha256 or not pdf_size):
        _record_rejected_terminal("compilation_pdf_missing", fenced=True)
        return FinalizationOutcome.FENCED
    if pdf_path is not None and pdf_path != compilation_pdf_key(job_id, owner_token):
        _record_rejected_terminal("pdf_owner_mismatch", fenced=True)
        return FinalizationOutcome.FENCED
    if pdf_path is not None and not _PDF_PATH_RE.fullmatch(pdf_path):
        _record_rejected_terminal("invalid_pdf_path", fenced=True)
        return FinalizationOutcome.FENCED
    if pdf_sha256 is not None and not _PDF_SHA256_RE.fullmatch(pdf_sha256):
        _record_rejected_terminal("invalid_pdf_digest", fenced=True)
        return FinalizationOutcome.FENCED
    if pdf_size is not None and (
        not isinstance(pdf_size, int) or isinstance(pdf_size, bool) or pdf_size < 0 or pdf_size > MAX_PDF_SIZE
    ):
        _record_rejected_terminal("invalid_pdf_size", fenced=True)
        return FinalizationOutcome.FENCED

    if row.resume_apply_requested and resume_content is None and not row.resume_applied:
        _record_rejected_terminal("resume_output_missing")
        return FinalizationOutcome.FAILED
    if row.cover_letter_apply_requested and cover_letter_content is None and not row.cover_letter_applied:
        _record_rejected_terminal("cover_letter_output_missing")
        return FinalizationOutcome.FAILED

    # Lock the output row before touching the resume. This validates all
    # terminal-output preconditions first, so a caller that commits this
    # transaction can never apply a resume and then discover a failed or
    # cancelled Compilation.
    if compilation is not None and compilation.status in {"failed", "cancelled"}:
        _record_rejected_terminal("compilation_terminal")
        return FinalizationOutcome.FAILED

    cover_letter = None
    cover_letter_key = cover_letter_id or row.cover_letter_id
    if cover_letter_content is not None:
        if not cover_letter_key:
            _record_rejected_terminal("cover_letter_missing")
            return FinalizationOutcome.FAILED
        cover_letter = await session.scalar(
            select(CoverLetter)
            .where(
                CoverLetter.id == cover_letter_key,
                *([CoverLetter.user_id == cover_letter_user_id] if cover_letter_user_id else []),
            )
            .with_for_update()
        )
        if cover_letter is None:
            _record_rejected_terminal("cover_letter_missing")
            return FinalizationOutcome.FAILED

    if resume_content is not None:
        resume_key = resume_id or row.resume_id
        if not resume_key or not resume_user_id or not expected_resume_sha256:
            _record_rejected_terminal("resume_snapshot_missing")
            return FinalizationOutcome.FAILED
        from .auto_save_worker import ResumePersistenceConflict, apply_resume_content

        try:
            applied = await apply_resume_content(
                session,
                resume_id=resume_key,
                user_id=resume_user_id,
                latex_content=resume_content,
                expected_latex_sha256=expected_resume_sha256,
            )
        except ResumePersistenceConflict:
            _record_rejected_terminal("resume_conflict")
            return FinalizationOutcome.FAILED
        if not applied:
            _record_rejected_terminal("resume_missing")
            return FinalizationOutcome.FAILED
        row.resume_id = resume_key
        row.resume_applied = True

    if cover_letter is not None:
        cover_letter.latex_content = cover_letter_content
        cover_letter.updated_at = datetime.now(timezone.utc)
        row.cover_letter_id = cover_letter_key
        row.cover_letter_applied = True

    if compilation is not None:
        compilation.status = "completed"
        compilation.compilation_time = compilation_time
        compilation.pdf_path = pdf_path
        compilation.pdf_size = pdf_size
        row.compilation_id = compilation.id

    row.state = FinalizationState.COMPLETED.value
    row.terminal_result = FinalizationState.COMPLETED.value
    row.result_payload = bounded_payload
    row.pdf_path = pdf_path
    row.pdf_sha256 = pdf_sha256
    row.pdf_size = pdf_size
    row.decided_at = _db_clock()
    return FinalizationOutcome.ACCEPTED


async def commit_failure(
    session,
    *,
    job_id: str,
    owner_token: Optional[str],
    owner_epoch: Optional[int],
    failure_code: str,
    result_payload: Optional[dict[str, Any]] = None,
    allow_fenced: bool = False,
) -> FinalizationOutcome:
    """Persist an immutable failed decision without storing raw diagnostics."""
    row = await session.scalar(
        select(JobFinalization).where(JobFinalization.job_id == job_id).with_for_update()
    )
    if row is None:
        return FinalizationOutcome.NO_ROW
    if row.state == FinalizationState.COMPLETED.value:
        return FinalizationOutcome.ALREADY_COMPLETED
    if row.state == FinalizationState.CANCELLED.value:
        return FinalizationOutcome.CANCELLED
    if row.state == FinalizationState.FENCED.value and not allow_fenced:
        return FinalizationOutcome.FENCED
    if row.state == FinalizationState.FAILED.value:
        return FinalizationOutcome.FAILED
    if allow_fenced and row.state != FinalizationState.FENCED.value:
        # A caller may use the cleanup capability only after the fenced
        # terminal state has been durably established. It is never a bypass
        # for an active owner's fencing checks.
        return FinalizationOutcome.BUSY
    if not allow_fenced:
        owner_active = await session.scalar(
            select(JobFinalization.id).where(
                JobFinalization.id == row.id,
                JobFinalization.owner_token == owner_token,
                JobFinalization.owner_epoch == owner_epoch,
                JobFinalization.cancel_requested.is_(False),
                JobFinalization.lease_expires_at.is_not(None),
                JobFinalization.lease_expires_at > _db_clock(),
            )
        )
        if owner_active is None:
            # An expired/stale worker never gains a terminal capability merely
            # by arriving after cleanup.  Leave the row untouched so cleanup
            # can acquire the explicit FENCED transition and refund safely.
            return FinalizationOutcome.FENCED
    row.state = FinalizationState.FAILED.value
    row.terminal_result = FinalizationState.FAILED.value
    row.failure_code = _bounded_text(failure_code, 64) or "failed"
    row.result_payload = bounded_result_payload(job_id, result_payload)
    row.decided_at = _db_clock()
    return FinalizationOutcome.ACCEPTED


async def recover_finalization(session, *, job_id: str) -> Optional[JobFinalization]:
    """Read the durable arbiter row for cleanup/result replay."""
    return await session.scalar(
        select(JobFinalization).where(JobFinalization.job_id == job_id)
    )


async def purge_expired_finalizations(session, *, limit: int = 500) -> int:
    """Delete expired recovery payloads; caller commits the cleanup transaction."""
    if not isinstance(limit, int) or limit < 1 or limit > 5000:
        raise ValueError("limit must be between 1 and 5000")
    ids = list(
        await session.scalars(
            select(JobFinalization.id)
            .where(JobFinalization.expires_at < _db_clock())
            .order_by(JobFinalization.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    if not ids:
        return 0
    result = await session.execute(sa_delete(JobFinalization).where(JobFinalization.id.in_(ids)))
    return int(result.rowcount or 0)
