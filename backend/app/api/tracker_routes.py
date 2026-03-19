"""Job Application Tracker routes."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..database.models import JobApplication, Optimization, Resume
from ..middleware.auth_middleware import get_current_user_required

router = APIRouter(prefix="/tracker", tags=["tracker"])

VALID_STATUSES = frozenset(
    {"applied", "phone_screen", "technical", "onsite", "offer", "rejected", "withdrawn"}
)

ALL_STATUSES = ["applied", "phone_screen", "technical", "onsite", "offer", "rejected", "withdrawn"]

# ------------------------------------------------------------------ #
#  Request / Response schemas                                          #
# ------------------------------------------------------------------ #


class CreateApplicationRequest(BaseModel):
    company_name: str = Field(..., max_length=200)
    role_title: str = Field(..., max_length=200)
    status: str = Field("applied")
    resume_id: Optional[str] = None
    job_description_text: Optional[str] = Field(None, max_length=20000)
    job_url: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=5000)
    applied_at: Optional[datetime] = None


class UpdateApplicationRequest(BaseModel):
    company_name: Optional[str] = Field(None, max_length=200)
    role_title: Optional[str] = Field(None, max_length=200)
    status: Optional[str] = None
    resume_id: Optional[str] = None
    job_description_text: Optional[str] = Field(None, max_length=20000)
    job_url: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=5000)
    applied_at: Optional[datetime] = None


class StatusUpdateRequest(BaseModel):
    status: str


class TrackerStats(BaseModel):
    total_applications: int
    by_status: Dict[str, int]
    avg_ats_score: Optional[float]
    applications_this_week: int
    applications_this_month: int
    response_rate: float
    offer_rate: float


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #


def _guess_domain(company_name: str) -> str:
    """Guess a company domain from its name for Clearbit logo URLs."""
    cleaned = company_name.lower().strip()
    for suffix in [" inc", " llc", " ltd", " corp", " co.", " co,", " company", "&"]:
        cleaned = cleaned.replace(suffix, "")
    return cleaned.strip().replace(" ", "") + ".com"


def _logo_url(company_name: str) -> str:
    return f"https://logo.clearbit.com/{_guess_domain(company_name)}"


def _serialize(app: JobApplication) -> dict:
    return {
        "id": str(app.id),
        "user_id": str(app.user_id),
        "company_name": app.company_name,
        "role_title": app.role_title,
        "status": app.status,
        "resume_id": str(app.resume_id) if app.resume_id else None,
        "ats_score_at_submission": app.ats_score_at_submission,
        "job_description_text": app.job_description_text,
        "job_url": app.job_url,
        "company_logo_url": app.company_logo_url,
        "notes": app.notes,
        "applied_at": app.applied_at.isoformat() if app.applied_at else None,
        "updated_at": app.updated_at.isoformat() if app.updated_at else None,
        "created_at": app.created_at.isoformat() if app.created_at else None,
    }


async def _get_latest_ats_score(resume_id: str, db: AsyncSession) -> Optional[float]:
    result = await db.execute(
        select(Optimization.ats_score)
        .where(Optimization.resume_id == resume_id, Optimization.ats_score.isnot(None))
        .order_by(Optimization.created_at.desc())
        .limit(1)
    )
    row = result.fetchone()
    return row[0] if row else None


# ------------------------------------------------------------------ #
#  Endpoints                                                           #
# ------------------------------------------------------------------ #


@router.post("/applications", status_code=status.HTTP_201_CREATED)
async def create_application(
    body: CreateApplicationRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    if body.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    ats_score = None
    if body.resume_id:
        res_result = await db.execute(
            select(Resume).where(Resume.id == body.resume_id, Resume.user_id == user_id)
        )
        if not res_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Resume not found or not owned by user")
        ats_score = await _get_latest_ats_score(body.resume_id, db)

    now = datetime.now(timezone.utc)
    app = JobApplication(
        id=str(uuid4()),
        user_id=user_id,
        company_name=body.company_name,
        role_title=body.role_title,
        status=body.status,
        resume_id=body.resume_id,
        ats_score_at_submission=ats_score,
        job_description_text=body.job_description_text,
        job_url=body.job_url,
        company_logo_url=_logo_url(body.company_name),
        notes=body.notes,
        applied_at=body.applied_at or now,
        created_at=now,
        updated_at=now,
    )
    db.add(app)
    await db.commit()
    return _serialize(app)


@router.get("/applications")
async def list_applications(
    status_filter: Optional[str] = Query(None, alias="status"),
    flat: bool = Query(False),
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(JobApplication)
        .where(JobApplication.user_id == user_id)
        .order_by(JobApplication.applied_at.desc())
    )
    if status_filter:
        stmt = stmt.where(JobApplication.status == status_filter)

    result = await db.execute(stmt)
    apps = result.scalars().all()

    if flat:
        return [_serialize(a) for a in apps]

    by_status: Dict[str, List[dict]] = {s: [] for s in ALL_STATUSES}
    for a in apps:
        if a.status in by_status:
            by_status[a.status].append(_serialize(a))
    return {"by_status": by_status}


@router.get("/stats", response_model=TrackerStats)
async def get_tracker_stats(
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JobApplication).where(JobApplication.user_id == user_id)
    )
    apps = result.scalars().all()

    total = len(apps)
    by_status: Dict[str, int] = {s: 0 for s in ALL_STATUSES}
    ats_scores: List[float] = []

    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_week = 0
    this_month = 0

    for a in apps:
        if a.status in by_status:
            by_status[a.status] += 1
        if a.ats_score_at_submission is not None:
            ats_scores.append(a.ats_score_at_submission)
        applied_dt = a.applied_at
        if applied_dt:
            if applied_dt.tzinfo is None:
                applied_dt = applied_dt.replace(tzinfo=timezone.utc)
            if applied_dt >= week_start:
                this_week += 1
            if applied_dt >= month_start:
                this_month += 1

    progressed = sum(by_status.get(s, 0) for s in ["phone_screen", "technical", "onsite", "offer"])
    response_rate = round(progressed / total, 4) if total > 0 else 0.0
    offer_rate = round(by_status.get("offer", 0) / total, 4) if total > 0 else 0.0

    return TrackerStats(
        total_applications=total,
        by_status=by_status,
        avg_ats_score=round(sum(ats_scores) / len(ats_scores), 1) if ats_scores else None,
        applications_this_week=this_week,
        applications_this_month=this_month,
        response_rate=response_rate,
        offer_rate=offer_rate,
    )


@router.get("/applications/{app_id}")
async def get_application(
    app_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JobApplication).where(
            JobApplication.id == app_id, JobApplication.user_id == user_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return _serialize(app)


@router.put("/applications/{app_id}")
async def update_application(
    app_id: str,
    body: UpdateApplicationRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JobApplication).where(
            JobApplication.id == app_id, JobApplication.user_id == user_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    if body.status is not None and body.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    if body.resume_id is not None and body.resume_id:
        res_result = await db.execute(
            select(Resume).where(Resume.id == body.resume_id, Resume.user_id == user_id)
        )
        if not res_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Resume not found or not owned by user")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(app, field, value)

    app.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _serialize(app)


@router.delete("/applications/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    app_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JobApplication).where(
            JobApplication.id == app_id, JobApplication.user_id == user_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    await db.delete(app)
    await db.commit()


@router.patch("/applications/{app_id}/status")
async def update_application_status(
    app_id: str,
    body: StatusUpdateRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    if body.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    result = await db.execute(
        select(JobApplication).where(
            JobApplication.id == app_id, JobApplication.user_id == user_id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    app.status = body.status
    app.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _serialize(app)
