"""User-facing GDPR endpoints: export bundles and account-deletion requests.

Kept separate from the admin control room so data-subject rights (which must
never be feature-gated) have their own small, auditable surface. Every route
requires an authenticated session and scopes all reads/writes to that user.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_required
from ..services import gdpr_service

router = APIRouter(prefix="/account/gdpr", tags=["gdpr"])

Confirmation = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class DeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Confirmation
    reason: Reason | None = None


def _http_error(exc: gdpr_service.GdprError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if isinstance(exc, gdpr_service.GdprLegalHoldBlocked):
        detail["request"] = exc.request_payload
    return HTTPException(status_code=exc.status_code, detail=detail)


@router.get("/policy")
async def get_gdpr_policy(
    _: str = Depends(get_current_user_required),
) -> dict[str, Any]:
    """Public-to-the-user policy metadata (retention exceptions, TTLs)."""
    return gdpr_service.public_policy()


@router.get("/requests")
async def list_gdpr_requests(
    limit: int = Query(default=50, ge=1, le=100),
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    items = await gdpr_service.list_user_requests(db, user_id=user_id, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/requests/{request_id}")
async def get_gdpr_request(
    request_id: UUID,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await gdpr_service.get_user_request(db, user_id=user_id, request_id=str(request_id))
    except gdpr_service.GdprError as exc:
        raise _http_error(exc) from None


@router.post("/exports", status_code=202)
async def create_gdpr_export(
    request: Request,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await gdpr_service.request_export(db, user_id=user_id, request=request)
    except gdpr_service.GdprError as exc:
        raise _http_error(exc) from None


@router.get("/exports/{request_id}/download")
async def download_gdpr_export(
    request_id: UUID,
    x_gdpr_export_token: str | None = Header(
        default=None,
        alias="X-GDPR-Export-Token",
        max_length=4096,
    ),
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # The token travels in a header rather than the URL so it cannot be
    # captured by access logs, proxy traces or browser history. It is still
    # bound to the authenticated owner and expires independently.
    if not x_gdpr_export_token or len(x_gdpr_export_token) < 20:
        raise HTTPException(
            status_code=400,
            detail={"code": "missing_export_token", "message": "Export token header is required"},
        )
    try:
        filename, body = await gdpr_service.download_export(
            db,
            user_id=user_id,
            request_id=str(request_id),
            token=x_gdpr_export_token,
        )
    except gdpr_service.GdprError as exc:
        raise _http_error(exc) from None
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post("/deletion", status_code=202)
async def request_account_deletion(
    body: DeletionRequest,
    request: Request,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await gdpr_service.request_deletion(
            db,
            user_id=user_id,
            confirmation=body.confirmation,
            reason=body.reason,
            request=request,
        )
    except gdpr_service.GdprError as exc:
        raise _http_error(exc) from None


@router.post("/deletion/{request_id}/cancel")
async def cancel_account_deletion(
    request_id: UUID,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await gdpr_service.cancel_deletion(db, user_id=user_id, request_id=str(request_id))
    except gdpr_service.GdprError as exc:
        raise _http_error(exc) from None
