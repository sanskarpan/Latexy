"""Admin-only route-transition (Sankey) report and CSV export (issue #2076)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.path_analysis_service import admin_path_analysis_service

router = APIRouter()

CohortFilter = Literal["all", "new", "established"]


def _csv_response(result: dict[str, Any]) -> Response:
    csv_body = admin_path_analysis_service.to_csv(result)
    start = str(result.get("start_date", "")).replace("-", "")
    end = str(result.get("end_date", "")).replace("-", "")
    filename = f"path-analysis-{start}-{end}.csv"
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
    plan: Optional[list[str]],
    cohort: CohortFilter,
    min_edge_count: int,
    export_format: Literal["json", "csv"],
    db: AsyncSession,
) -> dict[str, Any] | Response:
    try:
        result = await admin_path_analysis_service.snapshot(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
            plan=plan,
            cohort=cohort,
            min_edge_count=min_edge_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _csv_response(result) if export_format == "csv" else result


@router.get("/admin/analytics/paths")
async def get_admin_path_analysis(
    days: int = Query(30, ge=1, le=366),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    plan: Optional[list[str]] = Query(None),
    cohort: CohortFilter = Query("all"),
    min_edge_count: int = Query(1, ge=1, le=10_000),
    format: Literal["json", "csv"] = Query("json"),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> Any:
    """Return aggregate route transitions before upgrade and churn.

    Routes are canonicalized first-party page labels. Query strings, share
    tokens, document identifiers and document content are never returned, and
    all cohorts below five distinct users are suppressed.
    """

    return await _load_report(
        days=days,
        start_date=start_date,
        end_date=end_date,
        plan=plan,
        cohort=cohort,
        min_edge_count=min_edge_count,
        export_format=format,
        db=db,
    )


@router.get(
    "/admin/analytics/paths/export.csv",
    include_in_schema=False,
)
async def export_admin_path_analysis_csv(
    days: int = Query(30, ge=1, le=366),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    plan: Optional[list[str]] = Query(None),
    cohort: CohortFilter = Query("all"),
    min_edge_count: int = Query(1, ge=1, le=10_000),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> Response:
    """CSV alias for operators that prefer an explicit download path."""

    return await _load_report(
        days=days,
        start_date=start_date,
        end_date=end_date,
        plan=plan,
        cohort=cohort,
        min_edge_count=min_edge_count,
        export_format="csv",
        db=db,
    )
