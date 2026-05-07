"""
One-click job application routes (Feature 87).

Prefix: /apply
Endpoints:
  POST /apply/detect      — detect platform from a job URL (no submission)
  POST /apply/greenhouse  — submit application to Greenhouse
  POST /apply/lever       — submit application to Lever
  GET  /apply/submissions — list user's submission history
  GET  /apply/submissions/{id} — single submission detail
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import ApplicationSubmission, Compilation, JobApplication, Resume
from ..middleware.auth_middleware import get_current_user_required
from ..services.greenhouse_service import ApplicantData as GHApplicant
from ..services.greenhouse_service import greenhouse_service
from ..services.lever_service import ApplicantData as LeverApplicant
from ..services.lever_service import lever_service

logger = get_logger(__name__)

router = APIRouter(prefix="/apply", tags=["apply"])

# ── Pydantic schemas ──────────────────────────────────────────────────────────


class DetectPlatformRequest(BaseModel):
    job_url: str = Field(..., max_length=2000)


class DetectPlatformResponse(BaseModel):
    platform: str                   # 'greenhouse' | 'lever' | 'unknown'
    company: Optional[str] = None
    job_id: Optional[str] = None


class GreenhouseApplyRequest(BaseModel):
    job_url: str = Field(..., max_length=2000)
    resume_id: str
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)
    email: str = Field(..., max_length=200)
    phone: str = Field("", max_length=50)
    cover_letter: Optional[str] = Field(None, max_length=10000)


class LeverApplyRequest(BaseModel):
    job_url: str = Field(..., max_length=2000)
    resume_id: str
    name: str = Field(..., max_length=200)
    email: str = Field(..., max_length=200)
    phone: str = Field("", max_length=50)
    org: Optional[str] = Field(None, max_length=200)
    cover_letter: Optional[str] = Field(None, max_length=10000)


class SubmissionResponse(BaseModel):
    id: str
    user_id: str
    resume_id: Optional[str]
    job_tracker_id: Optional[str]
    platform: str
    platform_job_id: Optional[str]
    application_url: str
    job_title: Optional[str]
    company_name: Optional[str]
    status: str
    submitted_at: Optional[str]
    error_message: Optional[str]
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _serialize_submission(s: ApplicationSubmission) -> dict:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "resume_id": s.resume_id,
        "job_tracker_id": s.job_tracker_id,
        "platform": s.platform,
        "platform_job_id": s.platform_job_id,
        "application_url": s.application_url,
        "job_title": s.job_title,
        "company_name": s.company_name,
        "status": s.status,
        "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
        "error_message": s.error_message,
        "created_at": s.created_at.isoformat(),
    }


async def _get_resume_pdf(resume_id: str, user_id: str, db: AsyncSession) -> bytes:
    """
    Retrieve the compiled PDF bytes for a resume.
    Looks up the most recent successful compilation and fetches from MinIO
    (falling back to the temp dir for fresh compilations).
    Raises HTTPException 404 if no PDF is found.
    """
    # Verify resume ownership
    res = (await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )).scalar_one_or_none()
    if not res:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Find latest successful compilation
    comp = (await db.execute(
        select(Compilation)
        .where(Compilation.resume_id == resume_id, Compilation.status == "completed")
        .order_by(Compilation.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not comp:
        raise HTTPException(
            status_code=422,
            detail="No compiled PDF found for this resume. Please compile it first.",
        )

    # Try MinIO first
    if comp.pdf_path:
        try:
            from ..services.storage_service import download_bytes
            data = download_bytes(comp.pdf_path)
            if data:
                return data
        except Exception as exc:
            logger.warning(f"MinIO fetch failed for {comp.pdf_path}: {exc}")

    # Fallback to temp dir
    temp_pdf = Path(settings.TEMP_DIR) / comp.job_id / "resume.pdf"
    if temp_pdf.exists():
        return temp_pdf.read_bytes()

    raise HTTPException(
        status_code=422,
        detail="PDF not available. Please recompile the resume and try again.",
    )


async def _create_or_update_tracker(
    *,
    user_id: str,
    resume_id: str,
    company_name: str,
    role_title: str,
    job_url: str,
    db: AsyncSession,
) -> str:
    """
    Create a JobApplication tracker entry for the submission (or reuse existing).
    Returns the tracker entry id.
    """
    # Avoid duplicate tracker entries for same resume + URL
    existing = (await db.execute(
        select(JobApplication).where(
            JobApplication.user_id == user_id,
            JobApplication.job_url == job_url,
        )
    )).scalar_one_or_none()

    if existing:
        return existing.id

    tracker = JobApplication(
        id=str(uuid4()),
        user_id=user_id,
        company_name=company_name,
        role_title=role_title,
        status="applied",
        resume_id=resume_id,
        job_url=job_url,
    )
    db.add(tracker)
    await db.flush()   # assign id without full commit
    return tracker.id


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/detect", response_model=DetectPlatformResponse)
async def detect_platform(
    body: DetectPlatformRequest,
    user_id: str = Depends(get_current_user_required),
):
    """
    Detect which job platform (Greenhouse / Lever) a URL belongs to
    and return company + job ID without submitting anything.
    """
    url = body.job_url

    # Try Greenhouse
    try:
        company, job_id = greenhouse_service.parse_url(url)
        return DetectPlatformResponse(platform="greenhouse", company=company, job_id=job_id)
    except ValueError:
        pass

    # Try Lever
    try:
        company, posting_id = lever_service.parse_url(url)
        return DetectPlatformResponse(platform="lever", company=company, job_id=posting_id)
    except ValueError:
        pass

    return DetectPlatformResponse(platform="unknown")


@router.post("/greenhouse/preview")
async def preview_greenhouse_job(
    body: DetectPlatformRequest,
    user_id: str = Depends(get_current_user_required),
):
    """Fetch and return Greenhouse job details (title, location, apply_url)."""
    try:
        company, job_id = greenhouse_service.parse_url(body.job_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        details = await greenhouse_service.get_job_details(company, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Greenhouse API error: {exc.response.status_code}",
        )

    return {
        "platform": "greenhouse",
        "company": details.company,
        "job_id": details.job_id,
        "title": details.title,
        "location": details.location,
        "apply_url": details.apply_url,
    }


@router.post("/lever/preview")
async def preview_lever_job(
    body: DetectPlatformRequest,
    user_id: str = Depends(get_current_user_required),
):
    """Fetch and return Lever posting details (title, team, location, apply_url)."""
    try:
        company, posting_id = lever_service.parse_url(body.job_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        details = await lever_service.get_posting(company, posting_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Lever API error: {exc.response.status_code}",
        )

    return {
        "platform": "lever",
        "company": details.company,
        "posting_id": details.posting_id,
        "title": details.title,
        "team": details.team,
        "location": details.location,
        "apply_url": details.apply_url,
    }


@router.post("/greenhouse", status_code=201, response_model=SubmissionResponse)
async def apply_greenhouse(
    body: GreenhouseApplyRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a one-click application to a Greenhouse job posting.

    - Parses company / job_id from the job URL
    - Fetches the compiled PDF for the given resume_id from MinIO
    - POSTs to the Greenhouse Job Board application endpoint
    - Creates an ApplicationSubmission record (and a JobApplication tracker entry)
    """
    # Parse URL
    try:
        company, job_id = greenhouse_service.parse_url(body.job_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Fetch PDF
    pdf_bytes = await _get_resume_pdf(body.resume_id, user_id, db)

    # Resolve job title for tracker (best-effort)
    job_title = None
    company_display = company
    try:
        details = await greenhouse_service.get_job_details(company, job_id)
        job_title = details.title
        company_display = company
    except Exception:
        pass   # non-critical

    # Create submission record (start as pending)
    sub = ApplicationSubmission(
        id=str(uuid4()),
        user_id=user_id,
        resume_id=body.resume_id,
        platform="greenhouse",
        platform_job_id=job_id,
        application_url=body.job_url,
        job_title=job_title,
        company_name=company_display,
        status="pending",
    )
    db.add(sub)
    await db.flush()

    # Submit to Greenhouse
    try:
        await greenhouse_service.submit_application(
            company,
            job_id,
            GHApplicant(
                first_name=body.first_name,
                last_name=body.last_name,
                email=body.email,
                phone=body.phone,
                resume_bytes=pdf_bytes,
                cover_letter_text=body.cover_letter,
            ),
        )
        sub.status = "submitted"
        sub.submitted_at = datetime.now(timezone.utc)

        # Create / reuse tracker entry
        tracker_id = await _create_or_update_tracker(
            user_id=user_id,
            resume_id=body.resume_id,
            company_name=company_display,
            role_title=job_title or "Unknown Role",
            job_url=body.job_url,
            db=db,
        )
        sub.job_tracker_id = tracker_id

    except ValueError as exc:
        sub.status = "failed"
        sub.error_message = str(exc)
        logger.warning(f"Greenhouse submission rejected for user {user_id}: {exc}")
    except httpx.HTTPStatusError as exc:
        sub.status = "failed"
        sub.error_message = f"Greenhouse API error {exc.response.status_code}"
        logger.error(f"Greenhouse HTTP error for user {user_id}: {exc}")
    except Exception as exc:
        sub.status = "failed"
        sub.error_message = f"Unexpected error: {exc}"
        logger.exception(f"Greenhouse unexpected error for user {user_id}")

    await db.commit()
    await db.refresh(sub)

    if sub.status == "failed":
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Application submission failed",
                "error": sub.error_message,
                "submission_id": sub.id,
            },
        )

    return _serialize_submission(sub)


@router.post("/lever", status_code=201, response_model=SubmissionResponse)
async def apply_lever(
    body: LeverApplyRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a one-click application to a Lever job posting.

    - Parses company / posting_id from the job URL
    - Fetches the compiled PDF for the given resume_id from MinIO
    - POSTs to the Lever Postings apply endpoint
    - Creates an ApplicationSubmission record (and a JobApplication tracker entry)
    """
    # Parse URL
    try:
        company, posting_id = lever_service.parse_url(body.job_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Fetch PDF
    pdf_bytes = await _get_resume_pdf(body.resume_id, user_id, db)

    # Resolve job title (best-effort)
    job_title = None
    company_display = company
    try:
        details = await lever_service.get_posting(company, posting_id)
        job_title = details.title
    except Exception:
        pass

    # Create submission record
    sub = ApplicationSubmission(
        id=str(uuid4()),
        user_id=user_id,
        resume_id=body.resume_id,
        platform="lever",
        platform_job_id=posting_id,
        application_url=body.job_url,
        job_title=job_title,
        company_name=company_display,
        status="pending",
    )
    db.add(sub)
    await db.flush()

    # Submit to Lever
    try:
        await lever_service.apply(
            company,
            posting_id,
            LeverApplicant(
                name=body.name,
                email=body.email,
                phone=body.phone,
                resume_bytes=pdf_bytes,
                org=body.org,
                cover_letter_text=body.cover_letter,
            ),
        )
        sub.status = "submitted"
        sub.submitted_at = datetime.now(timezone.utc)

        tracker_id = await _create_or_update_tracker(
            user_id=user_id,
            resume_id=body.resume_id,
            company_name=company_display,
            role_title=job_title or "Unknown Role",
            job_url=body.job_url,
            db=db,
        )
        sub.job_tracker_id = tracker_id

    except ValueError as exc:
        sub.status = "failed"
        sub.error_message = str(exc)
        logger.warning(f"Lever submission rejected for user {user_id}: {exc}")
    except httpx.HTTPStatusError as exc:
        sub.status = "failed"
        sub.error_message = f"Lever API error {exc.response.status_code}"
        logger.error(f"Lever HTTP error for user {user_id}: {exc}")
    except Exception as exc:
        sub.status = "failed"
        sub.error_message = f"Unexpected error: {exc}"
        logger.exception(f"Lever unexpected error for user {user_id}")

    await db.commit()
    await db.refresh(sub)

    if sub.status == "failed":
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Application submission failed",
                "error": sub.error_message,
                "submission_id": sub.id,
            },
        )

    return _serialize_submission(sub)


@router.get("/submissions", response_model=list[SubmissionResponse])
async def list_submissions(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """List the authenticated user's application submission history."""
    q = select(ApplicationSubmission).where(ApplicationSubmission.user_id == user_id)
    if platform:
        q = q.where(ApplicationSubmission.platform == platform)
    if status:
        q = q.where(ApplicationSubmission.status == status)
    q = q.order_by(ApplicationSubmission.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return [_serialize_submission(s) for s in rows]


@router.get("/submissions/{submission_id}", response_model=SubmissionResponse)
async def get_submission(
    submission_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Get a single submission by ID (must belong to the authenticated user)."""
    sub = (await db.execute(
        select(ApplicationSubmission).where(
            ApplicationSubmission.id == submission_id,
            ApplicationSubmission.user_id == user_id,
        )
    )).scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    return _serialize_submission(sub)
