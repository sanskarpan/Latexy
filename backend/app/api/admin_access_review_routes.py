"""Admin-only quarterly access review and attestation API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import error_body
from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_access_review_service import (
    MAX_EXPECTED_ACCOUNTS,
    AccessReviewConflict,
    access_review_snapshot,
    record_access_review_attestation,
    to_csv,
)
from ..services.admin_audit_service import AdminActor

router = APIRouter()

ReviewRole = Literal["admin", "support"]
AttestationDecision = Literal["attested", "follow_up_required"]
AttestationNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=10, max_length=1000),
]
IdempotencyKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=8,
        max_length=120,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]
SnapshotHash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class ExpectedAccount(BaseModel):
    user_id: UUID
    role: ReviewRole


class AccessReviewAttestRequest(BaseModel):
    quarter: str = Field(pattern=r"^\d{4}-Q[1-4]$")
    expected_snapshot_hash: SnapshotHash
    expected_accounts: Optional[list[ExpectedAccount]] = Field(
        default=None,
        max_length=MAX_EXPECTED_ACCOUNTS,
    )
    decision: AttestationDecision
    note: AttestationNote
    confirm: bool
    idempotency_key: Optional[IdempotencyKey] = None


def _csv_response(snapshot: dict[str, Any]) -> Response:
    generated = snapshot.get("generated_at")
    try:
        stamp = datetime.fromisoformat(str(generated)).strftime("%Y%m%d")
    except (TypeError, ValueError):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    quarter = str(snapshot.get("quarter") or "current")
    filename = f"admin-access-review-{quarter}-{stamp}.csv"
    return Response(
        content=to_csv(snapshot),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/admin/access-review")
async def get_admin_access_review(
    format: Literal["json", "csv"] = Query("json"),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> Any:
    """Read-only privileged roster with 2FA, last-login and stale flags."""
    snapshot = await access_review_snapshot(db)
    return _csv_response(snapshot) if format == "csv" else snapshot


@router.get("/admin/access-review/export.csv", include_in_schema=False)
async def export_admin_access_review_csv(
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> Response:
    """CSV alias for operators that prefer an explicit download path."""
    return _csv_response(await access_review_snapshot(db))


@router.post("/admin/access-review/attest")
async def attest_admin_access_review(
    body: AccessReviewAttestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Append a quarterly attestation bound to the reviewed snapshot.

    The attestation is audited and append-only. No role, session, passkey or
    two-factor setting is changed, and a changed roster is rejected with 409.
    """
    try:
        return await record_access_review_attestation(
            db,
            actor=actor,
            quarter_label=body.quarter,
            expected_snapshot_hash=body.expected_snapshot_hash,
            expected_accounts=(
                [{"user_id": str(account.user_id), "role": account.role} for account in body.expected_accounts]
                if body.expected_accounts is not None
                else None
            ),
            decision=body.decision,
            note=body.note,
            confirm=body.confirm,
            idempotency_key=body.idempotency_key,
            request=request,
        )
    except AccessReviewConflict as exc:
        # Release the transaction-scoped advisory lock and leave the session
        # clean when a stale snapshot is rejected.
        await db.rollback()
        raise HTTPException(
            status_code=exc.status_code,
            detail=error_body(
                exc.code,
                str(exc),
                getattr(request.state, "request_id", None),
                exc.details,
            ),
        ) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=422,
            detail=error_body("invalid_attestation", str(exc), None),
        ) from exc


__all__ = ["router"]
