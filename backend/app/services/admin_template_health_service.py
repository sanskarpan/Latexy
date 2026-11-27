"""Admin-only template health, compile status and audited re-verification.

The report joins three server-owned aggregate sources:

* ``resume_templates`` for the catalog identity and active state;
* ``compilations`` for recent compile success/failure counts and the latest
  allowlisted error class;
* ``template_health_checks`` for append-only rendered-asset, compile-contract
  and visual-verification evidence.

Only aggregate counts and allowlisted labels leave this module.  It never reads
template source, résumé/document content, compiler logs, provider payloads,
storage credentials, IP addresses or user agents.  A health status is
``unknown`` when no evidence exists or the newest evidence is stale; a ``fail``
is never hidden by a stale row.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.serve_identity import serving_revision
from ..database import models
from . import storage_service
from .admin_audit_service import AdminActor, record_admin_audit

TemplateHealthCheck = models.TemplateHealthCheck
ResumeTemplate = models.ResumeTemplate
Compilation = models.Compilation

REPOSITORY_URL = "https://github.com/sanskarpan/Latexy"
CI_WORKFLOW_URL = f"{REPOSITORY_URL}/actions/workflows/ci.yml"
RUNBOOK_URL = f"{REPOSITORY_URL}/blob/main/docs/ADMIN_CONTROL_ROOM.md"
DEFAULT_STALE_AFTER_HOURS = 72
MAX_STALE_AFTER_HOURS = 720
RECENT_COMPILE_DAYS = 30
MIN_COMPILE_SAMPLES = 5
FAILURE_RATE_THRESHOLD = 50.0
MAX_STATUS_DETAIL = 240

STATUS_VALUES = frozenset({"pass", "fail", "unknown"})
VISUAL_RESULTS = frozenset({"pass", "fail", "unknown"})
ERROR_CLASSES = frozenset(
    {
        "missing_asset",
        "compile_error",
        "syntax",
        "missing_package",
        "timeout",
        "engine",
        "storage",
        "pdf_limit",
        "visual_regression",
        "unknown",
    }
)
SOURCES = frozenset({"admin_retry", "compile_batch", "ci", "backfill"})

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID_RE = re.compile(r"^[0-9]{1,32}$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,80}$")


def _as_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("template must be a valid UUID") from exc


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _percent(value: float) -> float:
    return round(float(value), 2)


def _status_detail(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned[:MAX_STATUS_DETAIL] or None


def _validated_commit(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not _COMMIT_RE.fullmatch(cleaned):
        raise ValueError("commit_sha must be a lowercase 40-character hexadecimal SHA")
    return cleaned


def _validated_run_id(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not _RUN_ID_RE.fullmatch(cleaned):
        raise ValueError("ci_run_id must contain only digits (maximum 32)")
    return cleaned


def _validated_request_id(value: str) -> str:
    cleaned = (value or "").strip()
    if not _REQUEST_ID_RE.fullmatch(cleaned):
        raise ValueError("request_id must be 8-80 URL-safe characters")
    return cleaned


def _validated_status(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned not in STATUS_VALUES:
        raise ValueError("status must be pass, fail or unknown")
    return cleaned


def _validated_visual(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned not in VISUAL_RESULTS:
        raise ValueError("visual_test must be pass, fail or unknown")
    return cleaned


def _safe_error_class(value: Optional[str]) -> str:
    cleaned = (value or "").strip().lower()
    return cleaned if cleaned in ERROR_CLASSES else "unknown"


def _evidence_links(row: Any) -> dict[str, Optional[str]]:
    commit_sha = getattr(row, "commit_sha", None) if row is not None else None
    ci_run_id = getattr(row, "ci_run_id", None) if row is not None else None
    ci_url = f"{REPOSITORY_URL}/actions/runs/{ci_run_id}" if ci_run_id else CI_WORKFLOW_URL
    return {
        "ci_url": ci_url,
        "log_url": ci_url if ci_run_id else None,
        "commit_url": f"{REPOSITORY_URL}/commit/{commit_sha}" if commit_sha else None,
        "runbook_url": RUNBOOK_URL,
    }


def _check_payload(row: TemplateHealthCheck, *, duplicate: bool = False) -> dict[str, Any]:
    evidence = _evidence_links(row)
    return {
        "id": str(row.id),
        "template_id": str(row.template_id),
        "status": row.status,
        "error_class": row.error_class,
        "visual_test": row.visual_test,
        "commit_sha": row.commit_sha,
        "ci_run_id": row.ci_run_id,
        "source": row.source,
        "assets_present": row.assets_present,
        "compile_samples": row.compile_samples,
        "compile_failures": row.compile_failures,
        "status_detail": row.status_detail,
        "checked_at": _iso(row.checked_at),
        "evidence": evidence,
        "duplicate": duplicate,
    }


async def _recent_compile_stats(
    db: AsyncSession,
    *,
    template_ids: list[str],
    since: datetime,
) -> dict[str, dict[str, Any]]:
    if not template_ids:
        return {}
    success = func.count().filter(func.lower(Compilation.status) == "completed")
    failed = func.count().filter(func.lower(Compilation.status) == "failed")
    rows = (
        await db.execute(
            select(
                Compilation.template_id.label("template_id"),
                success.label("success"),
                failed.label("failed"),
                func.max(Compilation.created_at).label("last_at"),
            )
            .where(
                Compilation.template_id.in_(template_ids),
                Compilation.created_at >= since,
                func.lower(Compilation.status).in_(("completed", "failed")),
            )
            .group_by(Compilation.template_id)
        )
    ).all()
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        template_id = str(row.template_id)
        stats[template_id] = {
            "success": int(row.success or 0),
            "failed": int(row.failed or 0),
            "last_at": row.last_at,
        }
    return stats


async def _latest_failed_error_class(
    db: AsyncSession,
    *,
    template_id: str,
    since: datetime,
) -> Optional[str]:
    error_class = (
        await db.execute(
            select(Compilation.error_class)
            .where(
                Compilation.template_id == template_id,
                Compilation.created_at >= since,
                func.lower(Compilation.status) == "failed",
            )
            .order_by(Compilation.created_at.desc(), Compilation.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _safe_error_class(error_class) if error_class else None


class AdminTemplateHealthService:
    async def health_report(
        self,
        db: AsyncSession,
        *,
        stale_after_hours: int = DEFAULT_STALE_AFTER_HOURS,
        include_inactive: bool = False,
        status: Optional[str] = None,
        template: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Return one health row per catalog template, aggregate-only."""
        stale_hours = max(1, min(int(stale_after_hours), MAX_STALE_AFTER_HOURS))
        status_filter = _validated_status(status) if status else None
        template_filter = _as_uuid(template) if template else None
        observed_at = now or datetime.now(timezone.utc)
        stale_cutoff = observed_at - timedelta(hours=stale_hours)
        compile_since = observed_at - timedelta(days=RECENT_COMPILE_DAYS)

        template_stmt = select(
            ResumeTemplate.id,
            ResumeTemplate.name,
            ResumeTemplate.category,
            ResumeTemplate.is_active,
            ResumeTemplate.sort_order,
        )
        if not include_inactive:
            template_stmt = template_stmt.where(ResumeTemplate.is_active.is_(True))
        if template_filter:
            template_stmt = template_stmt.where(ResumeTemplate.id == template_filter)
        template_rows = (
            await db.execute(
                template_stmt.order_by(ResumeTemplate.sort_order.asc(), ResumeTemplate.name.asc())
            )
        ).all()
        template_ids = [str(row.id) for row in template_rows]

        latest_by_id: dict[str, Any] = {}
        if template_ids:
            ranked = (
                select(
                    TemplateHealthCheck.id.label("id"),
                    TemplateHealthCheck.template_id.label("template_id"),
                    TemplateHealthCheck.status.label("status"),
                    TemplateHealthCheck.error_class.label("error_class"),
                    TemplateHealthCheck.visual_test.label("visual_test"),
                    TemplateHealthCheck.commit_sha.label("commit_sha"),
                    TemplateHealthCheck.ci_run_id.label("ci_run_id"),
                    TemplateHealthCheck.source.label("source"),
                    TemplateHealthCheck.assets_present.label("assets_present"),
                    TemplateHealthCheck.compile_samples.label("compile_samples"),
                    TemplateHealthCheck.compile_failures.label("compile_failures"),
                    TemplateHealthCheck.status_detail.label("status_detail"),
                    TemplateHealthCheck.checked_at.label("checked_at"),
                    func.row_number()
                    .over(
                        partition_by=TemplateHealthCheck.template_id,
                        order_by=(
                            TemplateHealthCheck.checked_at.desc(),
                            TemplateHealthCheck.id.desc(),
                        ),
                    )
                    .label("row_number"),
                )
                .where(TemplateHealthCheck.template_id.in_(template_ids))
                .subquery()
            )
            latest_rows = (
                await db.execute(select(ranked).where(ranked.c.row_number == 1))
            ).all()
            latest_by_id = {str(row.template_id): row for row in latest_rows}

        compile_stats = await _recent_compile_stats(
            db,
            template_ids=template_ids,
            since=compile_since,
        )

        rows: list[dict[str, Any]] = []
        for template_row in template_rows:
            template_id = str(template_row.id)
            latest = latest_by_id.get(template_id)
            stats = compile_stats.get(template_id, {})
            success = int(stats.get("success", 0))
            failed = int(stats.get("failed", 0))
            samples = success + failed
            failure_rate = _percent(failed / samples * 100) if samples else 0.0

            stale = bool(
                latest is not None
                and latest.checked_at is not None
                and latest.checked_at < stale_cutoff
            )
            evidence_present = latest is not None
            if latest is None:
                effective_status = "unknown"
                reason = "no_evidence"
            elif stale:
                # Stale pass/fail evidence is not current proof.  Keep the
                # historical values visible but require fresh verification.
                effective_status = "unknown"
                reason = "stale_evidence"
            else:
                effective_status = _validated_status(latest.status)
                reason = latest.status_detail or latest.error_class or "verified"

            if status_filter and effective_status != status_filter:
                continue

            evidence = _evidence_links(latest)
            rows.append(
                {
                    "template_id": template_id,
                    "template_name": str(template_row.name),
                    "category": str(template_row.category),
                    "active": bool(template_row.is_active),
                    "template_url": f"/templates?preview={template_id}",
                    "status": effective_status,
                    "recorded_status": _validated_status(latest.status) if latest is not None else None,
                    "stale": stale,
                    "status_reason": reason,
                    "status_detail": latest.status_detail if latest is not None else None,
                    "error_class": latest.error_class if latest is not None else None,
                    "visual_test": latest.visual_test if latest is not None else "unknown",
                    "commit_sha": latest.commit_sha if latest is not None else None,
                    "ci_run_id": latest.ci_run_id if latest is not None else None,
                    "source": latest.source if latest is not None else None,
                    "evidence_present": evidence_present,
                    "last_verified_at": _iso(latest.checked_at) if latest is not None else None,
                    "evidence": evidence,
                    "recent_compile_success": success,
                    "recent_compile_failed": failed,
                    "recent_compile_samples": samples,
                    "recent_failure_rate": failure_rate,
                    "last_compile_at": _iso(stats.get("last_at")),
                }
            )

        summary = {
            "templates": len(rows),
            "pass": sum(1 for row in rows if row["status"] == "pass"),
            "fail": sum(1 for row in rows if row["status"] == "fail"),
            "unknown": sum(1 for row in rows if row["status"] == "unknown"),
            "stale": sum(1 for row in rows if row["stale"]),
            "without_evidence": sum(1 for row in rows if not row["evidence_present"]),
        }
        return {
            "timezone": "UTC",
            "stale_after_hours": stale_hours,
            "recent_compile_days": RECENT_COMPILE_DAYS,
            "minimum_compile_samples": MIN_COMPILE_SAMPLES,
            "filters": {
                "status": status_filter,
                "template": template_filter,
                "include_inactive": bool(include_inactive),
            },
            "summary": summary,
            "templates": rows,
            "evidence_contract": {
                "ci_workflow_url": CI_WORKFLOW_URL,
                "runbook_url": RUNBOOK_URL,
                "repository": REPOSITORY_URL,
            },
            "generated_at": observed_at.isoformat(),
        }

    async def retry_check(
        self,
        db: AsyncSession,
        *,
        template_id: str,
        actor: AdminActor,
        reason: str,
        request_id: str,
        visual_test: str = "unknown",
        commit_sha: Optional[str] = None,
        ci_run_id: Optional[str] = None,
        request: Optional[Request] = None,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Re-run the bounded asset/compile check and append evidence.

        This deliberately does not compile arbitrary LaTeX in the API process.
        It verifies that the rendered PDF/PNG assets exist, folds in recent
        aggregate compile outcomes for the template, records the caller's
        optional visual-test result, and links to allowlisted CI/commit
        evidence.  The ``request_id`` makes retries idempotent; the audit row
        and snapshot commit together.
        """
        canonical_id = _as_uuid(template_id)
        idempotency_key = _validated_request_id(request_id)
        visual = _validated_visual(visual_test)
        validated_commit = _validated_commit(commit_sha) or serving_revision()
        validated_run = _validated_run_id(ci_run_id)
        cleaned_reason = " ".join((reason or "").split())[:1000]
        if len(cleaned_reason) < 3:
            raise ValueError("A reason of at least 3 characters is required")
        observed_at = now or datetime.now(timezone.utc)

        template = await db.get(ResumeTemplate, canonical_id)
        if template is None:
            raise KeyError("Template not found")

        existing = (
            await db.execute(
                select(TemplateHealthCheck).where(
                    TemplateHealthCheck.template_id == canonical_id,
                    TemplateHealthCheck.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _check_payload(existing, duplicate=True)

        # Serialize concurrent retries with the same key without a second
        # unique-index race path.  The lock is released with the transaction.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"template-health:{canonical_id}:{idempotency_key}"},
        )
        existing = (
            await db.execute(
                select(TemplateHealthCheck).where(
                    TemplateHealthCheck.template_id == canonical_id,
                    TemplateHealthCheck.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _check_payload(existing, duplicate=True)

        missing_assets: list[str] = []
        assets_present: Optional[bool]
        storage_error = False
        try:
            for asset_name in ("pdf", "png"):
                if not storage_service.file_exists(f"templates/{canonical_id}.{asset_name}"):
                    missing_assets.append(asset_name)
            assets_present = not missing_assets
        except Exception:
            assets_present = None
            storage_error = True

        compile_since = observed_at - timedelta(days=RECENT_COMPILE_DAYS)
        stats = (
            await _recent_compile_stats(
                db,
                template_ids=[canonical_id],
                since=compile_since,
            )
        ).get(canonical_id, {})
        success = int(stats.get("success", 0))
        failed = int(stats.get("failed", 0))
        samples = success + failed
        failure_rate = failed / samples * 100 if samples else 0.0

        error_class: Optional[str] = None
        if storage_error:
            status = "unknown"
            error_class = "storage"
            detail = "asset_check_unavailable"
        elif missing_assets:
            status = "fail"
            error_class = "missing_asset"
            detail = "missing_" + "_and_".join(missing_assets)
        elif samples >= MIN_COMPILE_SAMPLES and failure_rate >= FAILURE_RATE_THRESHOLD:
            status = "fail"
            error_class = (
                await _latest_failed_error_class(
                    db,
                    template_id=canonical_id,
                    since=compile_since,
                )
                or "compile_error"
            )
            detail = "recent_compile_failure_rate"
        elif visual == "fail":
            status = "fail"
            error_class = "visual_regression"
            detail = "visual_test_failed"
        else:
            status = "pass"
            detail = "assets_present_compile_health_ok"

        snapshot = TemplateHealthCheck(
            template_id=canonical_id,
            status=status,
            error_class=error_class,
            visual_test=visual,
            commit_sha=validated_commit,
            ci_run_id=validated_run,
            source="admin_retry",
            assets_present=assets_present,
            compile_samples=samples,
            compile_failures=failed,
            status_detail=_status_detail(detail),
            idempotency_key=idempotency_key,
            checked_at=observed_at,
        )
        db.add(snapshot)
        try:
            await db.flush()
            await record_admin_audit(
                db,
                actor=actor,
                action="template.health.retry",
                target_type="template_health",
                target_id=canonical_id,
                reason=cleaned_reason,
                after={
                    "status": status,
                    "error_class": error_class,
                    "visual_test": visual,
                    "commit_sha": validated_commit,
                    "ci_run_id": validated_run,
                    "compile_samples": samples,
                    "compile_failures": failed,
                    "request_id": idempotency_key,
                },
                metadata={"source": "admin_retry", "idempotent": True},
                request=request,
            )
            await db.commit()
            await db.refresh(snapshot)
        except IntegrityError:
            # A concurrent identical retry won the unique constraint.  Return
            # that row rather than writing a second snapshot or audit entry.
            await db.rollback()
            winner = (
                await db.execute(
                    select(TemplateHealthCheck).where(
                        TemplateHealthCheck.template_id == canonical_id,
                        TemplateHealthCheck.idempotency_key == idempotency_key,
                    )
                )
            ).scalar_one_or_none()
            if winner is None:
                raise
            return _check_payload(winner, duplicate=True)
        return _check_payload(snapshot)

    async def record_compile_batch_results(
        self,
        db: AsyncSession,
        results: list[dict[str, Any]],
        *,
        commit_sha: Optional[str] = None,
        ci_run_id: Optional[str] = None,
    ) -> int:
        """Append health evidence for each asset-batch outcome.

        This is the server-owned compile path, not an admin mutation, so it
        writes no audit row.  Only allowlisted classes and bounded details are
        accepted; a malformed result is skipped rather than failing the batch.
        """
        validated_commit = serving_revision()
        try:
            provided_commit = _validated_commit(commit_sha)
            validated_commit = provided_commit or validated_commit
        except ValueError:
            validated_commit = serving_revision()
        try:
            validated_run = _validated_run_id(ci_run_id)
        except ValueError:
            validated_run = None
        rows: list[TemplateHealthCheck] = []
        for result in results:
            try:
                template_id = _as_uuid(str(result["template_id"]))
                status = _validated_status(str(result.get("status", "unknown")))
                visual = _validated_visual(str(result.get("visual_test", "unknown")))
            except (KeyError, ValueError):
                continue
            error_class = result.get("error_class")
            rows.append(
                TemplateHealthCheck(
                    template_id=template_id,
                    status=status,
                    error_class=_safe_error_class(error_class) if error_class else None,
                    visual_test=visual,
                    commit_sha=validated_commit,
                    ci_run_id=validated_run,
                    source="compile_batch",
                    assets_present=(status == "pass"),
                    compile_samples=None,
                    compile_failures=None,
                    status_detail=_status_detail(result.get("status_detail")),
                )
            )
        if not rows:
            return 0
        db.add_all(rows)
        await db.commit()
        return len(rows)


admin_template_health_service = AdminTemplateHealthService()
