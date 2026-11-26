"""Admin-only content-library adoption report and CSV export."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.admin_content_library_service import admin_content_library_service

router = APIRouter()

ContentLibraryStatus = Literal["all", "active", "stale", "unused", "deleted"]


def _csv_response(result: dict[str, Any]) -> Response:
    csv_body = admin_content_library_service.to_csv(result)
    start = str(result.get("start_date", "")).replace("-", "")
    end = str(result.get("end_date", "")).replace("-", "")
    filename = f"content-library-adoption-{start}-{end}.csv"
    return Response(
        content=csv_body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


async def _load_report(
    *,
    days: int,
    start_date: Optional[date],
    end_date: Optional[date],
    category: Optional[str],
    status: ContentLibraryStatus,
    official: Optional[bool],
    snippet: Optional[str],
    export_format: Literal["json", "csv"],
    db: AsyncSession,
) -> dict[str, Any] | Response:
    try:
        result = await admin_content_library_service.content_library_adoption(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
            category=category,
            status=status,
            official=official,
            snippet=snippet,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _csv_response(result) if export_format == "csv" else result


@router.get("/admin/content-library/adoption")
async def get_admin_content_library_adoption(
    days: int = Query(30, ge=1, le=365),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    category: Optional[str] = Query(None, max_length=300),
    status: ContentLibraryStatus = Query("all"),
    official: Optional[bool] = Query(None),
    snippet: Optional[str] = Query(None, max_length=64),
    format: Literal["json", "csv"] = Query("json"),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> Any:
    """Aggregate snippet and macro adoption, with five-user suppression."""
    return await _load_report(
        days=days,
        start_date=start_date,
        end_date=end_date,
        category=category,
        status=status,
        official=official,
        snippet=snippet,
        export_format=format,
        db=db,
    )


@router.get(
    "/admin/content-library/adoption/export.csv",
    include_in_schema=False,
)
async def export_admin_content_library_adoption_csv(
    days: int = Query(30, ge=1, le=365),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    category: Optional[str] = Query(None, max_length=300),
    status: ContentLibraryStatus = Query("all"),
    official: Optional[bool] = Query(None),
    snippet: Optional[str] = Query(None, max_length=64),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> Response:
    """CSV alias for operators that prefer an explicit download path."""
    return await _load_report(
        days=days,
        start_date=start_date,
        end_date=end_date,
        category=category,
        status=status,
        official=official,
        snippet=snippet,
        export_format="csv",
        db=db,
    )
