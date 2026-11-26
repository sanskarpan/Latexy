"""Admin CSV/PDF exports, signed downloads and scheduled digests."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import admin_export_service as exports
from ..services.admin_audit_service import AdminActor

router = APIRouter()

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class ExportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: Literal["overview", "analytics", "billing", "users", "audit"]
    format: Literal["csv", "pdf"] = "csv"
    days: Optional[int] = Field(default=30, ge=1, le=365)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    plan: Optional[str] = Field(default=None, max_length=50)
    compiler: Optional[str] = Field(default=None, max_length=32)
    status: Optional[str] = Field(default=None, max_length=50)
    role: Optional[str] = Field(default=None, max_length=20)
    action: Optional[str] = Field(default=None, max_length=120)
    target_type: Optional[str] = Field(default=None, max_length=50)


class DigestConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    frequency: Literal["daily", "weekly", "monthly"] = "weekly"
    recipient_user_ids: list[str] = Field(default_factory=list, max_length=10)
    report: Literal["overview", "billing", "users"] = "overview"
    format: Literal["summary", "csv"] = "summary"
    days: Optional[int] = Field(default=30, ge=1, le=365)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    plan: Optional[str] = Field(default=None, max_length=50)
    compiler: Optional[str] = Field(default=None, max_length=32)
    status: Optional[str] = Field(default=None, max_length=50)
    role: Optional[str] = Field(default=None, max_length=20)


class DigestUpdateRequest(DigestConfigInput):
    reason: Reason
    confirm: Literal[True]


class DigestDryRunRequest(DigestConfigInput):
    pass


def _filters_from_body(body: BaseModel) -> dict[str, str]:
    payload: dict[str, str] = {}
    for key in ("plan", "compiler", "status", "role", "action", "target_type"):
        value = getattr(body, key, None)
        if value is not None and str(value).strip():
            payload[key] = str(value).strip()
    return payload


def _filters_from_query(
    *,
    plan: Optional[str] = None,
    compiler: Optional[str] = None,
    status: Optional[str] = None,
    role: Optional[str] = None,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
) -> dict[str, str]:
    return {
        key: value
        for key, value in {
            "plan": plan,
            "compiler": compiler,
            "status": status,
            "role": role,
            "action": action,
            "target_type": target_type,
        }.items()
        if value is not None and str(value).strip()
    }


def _spec_from_payload(
    *,
    report: str,
    export_format: str,
    days: Optional[int],
    start_date: Optional[date],
    end_date: Optional[date],
    filters: dict[str, str],
) -> exports.ExportSpec:
    return exports.normalize_spec(
        report=report,
        export_format=export_format,
        days=days,
        start_date=start_date,
        end_date=end_date,
        filters=filters,
    )


def _http_error(exc: exports.AdminExportError) -> HTTPException:
    headers = {}
    if isinstance(exc, exports.AdminExportRateLimited):
        headers["Retry-After"] = str(exc.retry_after)
    return HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers or None)


def _export_headers(prepared: exports.PreparedReport, *, filename: str) -> dict[str, str]:
    return {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "private, no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "X-Export-Schema-Version": exports.REPORT_SCHEMA_VERSION,
        "X-Export-Row-Count": str(prepared.row_count),
        "X-Export-Truncated": "true" if prepared.truncated else "false",
        "X-Export-Suppressed": "true" if prepared.suppressed else "false",
    }


def _filename(spec: exports.ExportSpec) -> str:
    start = spec.start_date.strftime("%Y%m%d")
    end = spec.end_date.strftime("%Y%m%d")
    return f"latexy-admin-{spec.report}-{start}-{end}.{spec.format}"


async def _build_download(
    db: AsyncSession,
    *,
    actor: AdminActor,
    spec: exports.ExportSpec,
    request: Request,
    action: str = exports.EXPORT_ACTIONS[0],
    metadata: Optional[dict[str, Any]] = None,
) -> Response:
    prepared = await exports.prepare_report(db, spec)
    if spec.format == "pdf":
        prepared = await exports.load_report_rows(db, spec, limit=exports.MAX_PDF_ROWS)
        prepared.spec = spec
        content = exports.render_report_pdf(prepared)
        await exports.record_export_event(
            db,
            actor=actor,
            action=action,
            export_id=str((metadata or {}).get("export_id") or uuid.uuid4()),
            spec=spec,
            row_count=prepared.row_count,
            metadata={"delivery": "pdf_download", **(metadata or {})},
            request=request,
        )
        return Response(
            content=content,
            media_type="application/pdf",
            headers=_export_headers(prepared, filename=_filename(spec)),
        )

    # The row count is known before streaming; the body itself is generated in
    # bounded batches so the response never holds the full result in memory.
    await exports.record_export_event(
        db,
        actor=actor,
        action=action,
        export_id=str((metadata or {}).get("export_id") or uuid.uuid4()),
        spec=spec,
        row_count=prepared.row_count,
        metadata={"delivery": "csv_stream", **(metadata or {})},
        request=request,
    )
    return StreamingResponse(
        exports.iter_report_csv(db, prepared),
        media_type="text/csv; charset=utf-8",
        headers=_export_headers(prepared, filename=_filename(spec)),
    )


@router.get("/admin/exports")
async def get_admin_exports(
    request: Request,
    report: Optional[Literal["overview", "analytics", "billing", "users", "audit"]] = Query(None),
    format: Literal["csv", "pdf"] = Query("csv"),
    days: Optional[int] = Query(30, ge=1, le=365),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    plan: Optional[str] = Query(None, max_length=50),
    compiler: Optional[str] = Query(None, max_length=32),
    status: Optional[str] = Query(None, max_length=50),
    role: Optional[str] = Query(None, max_length=20),
    action: Optional[str] = Query(None, max_length=120),
    target_type: Optional[str] = Query(None, max_length=50),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> Any:
    """Catalog, limits, history and digest state; streams when ``report`` is set."""
    if report is not None:
        if not await exports.allow_export_request(actor.user_id, limit=20):
            raise _http_error(exports.AdminExportRateLimited())
        try:
            spec = _spec_from_payload(
                report=report,
                export_format=format,
                days=days,
                start_date=start_date,
                end_date=end_date,
                filters=_filters_from_query(
                    plan=plan,
                    compiler=compiler,
                    status=status,
                    role=role,
                    action=action,
                    target_type=target_type,
                ),
            )
            return await _build_download(db, actor=actor, spec=spec, request=request)
        except exports.AdminExportError as exc:
            raise _http_error(exc) from None

    digest = await exports.load_digest_config(db, actor)
    return {
        "reports": [
            {
                "report": report,
                "label": spec["label"],
                "description": spec["description"],
                "filters": list(spec["filters"]),
                "formats": list(spec["formats"]),
                "aliases": list(spec.get("aliases", ())),
            }
            for report, spec in exports.REPORTS.items()
        ],
        "limits": {
            "max_rows": exports.MAX_CSV_ROWS,
            "max_pdf_rows": exports.MAX_PDF_ROWS,
            "signed_url_ttl_minutes": exports.export_ttl_minutes(),
            "max_range_days": 365,
            "minimum_users": exports.MIN_GROUP_USERS,
            "synchronous_row_threshold": exports.SYNC_ROW_THRESHOLD,
        },
        "schema_version": exports.REPORT_SCHEMA_VERSION,
        "history": await exports.list_export_history(db, actor_user_id=actor.user_id),
        "digest": {
            **digest.public_payload(),
            "last_run": await exports.digest_last_run(db, actor.user_id),
        },
        "privacy": {
            "aggregate_only": True,
            "content_fields_excluded": [
                "resume/document content and PDFs",
                "prompts and job descriptions",
                "emails, names, tokens and raw IP addresses",
                "provider payloads and payment identifiers",
                "per-user histories",
            ],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/admin/exports/history")
async def get_admin_export_history(
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return {
        "items": await exports.list_export_history(db, actor_user_id=actor.user_id, limit=limit),
        "schema_version": exports.REPORT_SCHEMA_VERSION,
    }


@router.post("/admin/exports")
async def create_admin_export(
    body: ExportCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Create a short-lived signed download bound to this admin actor."""
    if not await exports.allow_export_request(actor.user_id):
        raise _http_error(exports.AdminExportRateLimited())
    try:
        spec = _spec_from_payload(
            report=body.report,
            export_format=body.format,
            days=body.days,
            start_date=body.start_date,
            end_date=body.end_date,
            filters=_filters_from_body(body),
        )
        prepared = await exports.prepare_report(db, spec)
        token, expires_at, export_id = exports.issue_export_token(spec, actor_user_id=actor.user_id)
    except exports.AdminExportError as exc:
        raise _http_error(exc) from None
    large_job = prepared.row_count > exports.SYNC_ROW_THRESHOLD or spec.format == "pdf"
    await exports.record_export_event(
        db,
        actor=actor,
        action=exports.EXPORT_ACTIONS[0],
        export_id=export_id,
        spec=spec,
        row_count=prepared.row_count,
        metadata={
            "delivery": "signed_url",
            "large_job": large_job,
            "expires_at": expires_at.isoformat(),
        },
        request=request,
    )
    return {
        "export_id": export_id,
        "report": spec.report,
        "format": spec.format,
        "delivery": "signed_url",
        "large_job": large_job,
        "download_url": f"/admin/exports/download?token={token}",
        "download_token": token,
        "expires_at": expires_at.isoformat(),
        "schema_version": exports.REPORT_SCHEMA_VERSION,
        "row_cap": spec.row_cap,
        "row_count": prepared.row_count,
        "generated_at": prepared.generated_at.isoformat(),
        "range": prepared.spec.range_payload(),
        "filters": dict(prepared.spec.filters),
        "metadata": exports.report_metadata_payload(prepared),
    }


@router.get("/admin/exports/stream")
async def stream_admin_export(
    request: Request,
    report: Literal["overview", "analytics", "billing", "users", "audit"] = Query(...),
    format: Literal["csv", "pdf"] = Query("csv"),
    days: Optional[int] = Query(30, ge=1, le=365),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    plan: Optional[str] = Query(None, max_length=50),
    compiler: Optional[str] = Query(None, max_length=32),
    status: Optional[str] = Query(None, max_length=50),
    role: Optional[str] = Query(None, max_length=20),
    action: Optional[str] = Query(None, max_length=120),
    target_type: Optional[str] = Query(None, max_length=50),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> Response:
    """Direct authenticated stream for small reports; still row-capped."""
    if not await exports.allow_export_request(actor.user_id, limit=20):
        raise _http_error(exports.AdminExportRateLimited())
    try:
        spec = _spec_from_payload(
            report=report,
            export_format=format,
            days=days,
            start_date=start_date,
            end_date=end_date,
            filters=_filters_from_query(
                plan=plan,
                compiler=compiler,
                status=status,
                role=role,
                action=action,
                target_type=target_type,
            ),
        )
        return await _build_download(db, actor=actor, spec=spec, request=request)
    except exports.AdminExportError as exc:
        raise _http_error(exc) from None


@router.get("/admin/exports/download")
async def download_admin_export(
    request: Request,
    token: str = Query(..., min_length=20, max_length=4096),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> Response:
    """Validate the signed, actor-bound token before streaming the file."""
    if not await exports.allow_export_request(actor.user_id, limit=30):
        raise _http_error(exports.AdminExportRateLimited())
    try:
        spec, export_id = exports.validate_export_token(token, actor_user_id=actor.user_id)
        return await _build_download(
            db,
            actor=actor,
            spec=spec,
            request=request,
            action=exports.EXPORT_ACTIONS[1],
            metadata={"export_id": export_id, "delivery": "signed_download"},
        )
    except exports.AdminExportError as exc:
        raise _http_error(exc) from None


@router.get("/admin/exports/digest")
async def get_admin_digest(
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    config = await exports.load_digest_config(db, actor)
    return {
        **config.public_payload(),
        "available_recipients": await exports.list_admin_recipients(db, current_actor_user_id=actor.user_id),
        "last_run": await exports.digest_last_run(db, actor.user_id),
        "schema_version": exports.REPORT_SCHEMA_VERSION,
    }


@router.put("/admin/exports/digest")
async def update_admin_digest(
    body: DigestUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Enable/update the scheduled digest; reason, confirmation and audit required."""
    recipient_ids = body.recipient_user_ids or [actor.user_id]
    try:
        config = exports.DigestConfig(
            enabled=body.enabled,
            frequency=body.frequency,
            recipient_user_ids=tuple(recipient_ids),
            report=body.report,
            format=body.format,
            days=int(body.days or 30),
            start_date=body.start_date,
            end_date=body.end_date,
            filters=_filters_from_body(body),
        )
        saved = await exports.save_digest_config(db, actor=actor, config=config, reason=body.reason, request=request)
    except exports.AdminExportError as exc:
        raise _http_error(exc) from None
    return {
        **saved.public_payload(),
        "last_run": await exports.digest_last_run(db, actor.user_id),
        "schema_version": exports.REPORT_SCHEMA_VERSION,
    }


@router.post("/admin/exports/digest/dry-run")
async def dry_run_admin_digest(
    body: DigestDryRunRequest,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Build the aggregate digest without sending email or creating a schedule."""
    recipient_ids = body.recipient_user_ids or [actor.user_id]
    try:
        config = exports.DigestConfig(
            enabled=False,
            frequency=body.frequency,
            recipient_user_ids=tuple(recipient_ids),
            report=body.report,
            format=body.format,
            days=int(body.days or 30),
            start_date=body.start_date,
            end_date=body.end_date,
            filters=_filters_from_body(body),
        )
        payload = await exports.build_digest_payload(db, actor=actor, config=config)
    except exports.AdminExportError as exc:
        raise _http_error(exc) from None
    await exports.record_digest_event(
        db,
        actor=actor,
        action=exports.DIGEST_DRY_RUN_ACTION,
        metadata={
            "status": "dry_run",
            "report": payload["report"],
            "format": payload["format"],
            "row_count": payload["row_count"],
            "recipient_count": len(payload["recipient_user_ids"]),
            "schema_version": exports.REPORT_SCHEMA_VERSION,
        },
    )
    return {
        "sent": False,
        "dry_run": True,
        "subject": payload["subject"],
        "text_body": payload["text_body"],
        "metadata": payload["metadata"],
        "recipient_user_ids": payload["recipient_user_ids"],
        "recipient_count": len(payload["recipient_user_ids"]),
        "rejected_recipient_count": payload["rejected_recipient_count"],
        "schema_version": exports.REPORT_SCHEMA_VERSION,
    }
