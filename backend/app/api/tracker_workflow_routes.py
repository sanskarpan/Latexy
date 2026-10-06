"""Saved-job, alert, follow-up, interview, and contact workflows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..database.models import (
    ApplicationInterview,
    ApplicationReminder,
    JobAlert,
    JobApplication,
    SavedJob,
    TrackerCompany,
    TrackerContact,
)
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.entitlements import require_feature
from ..utils.uuid_guard import ensure_uuid
from .tracker_routes import _logo_url
from .tracker_routes import _serialize as _serialize_application

router = APIRouter(
    prefix="/tracker",
    tags=["tracker"],
    dependencies=[Depends(require_feature("application_tracker"))],
)


def _validate_web_url(value: Optional[str]) -> Optional[str]:
    if value is None or not value.strip():
        return None
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if (
        any(ord(character) < 32 for character in candidate)
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Must be an http(s) URL without embedded credentials")
    return candidate


def _require_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone offset is required")
    return value.astimezone(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SavedJobCreate(StrictModel):
    company_name: str = Field(min_length=1, max_length=200)
    role_title: str = Field(min_length=1, max_length=200)
    job_url: Optional[str] = Field(None, max_length=500)
    job_description_text: Optional[str] = Field(None, max_length=20_000)
    notes: Optional[str] = Field(None, max_length=5_000)

    _job_url = field_validator("job_url")(_validate_web_url)


class SavedJobUpdate(StrictModel):
    company_name: Optional[str] = Field(None, min_length=1, max_length=200)
    role_title: Optional[str] = Field(None, min_length=1, max_length=200)
    job_url: Optional[str] = Field(None, max_length=500)
    job_description_text: Optional[str] = Field(None, max_length=20_000)
    notes: Optional[str] = Field(None, max_length=5_000)

    _job_url = field_validator("job_url")(_validate_web_url)


class TrackSavedJobRequest(StrictModel):
    status: Literal["applied", "phone_screen", "technical", "onsite", "offer", "rejected", "withdrawn"] = "applied"
    resume_id: Optional[str] = None
    applied_at: Optional[datetime] = None

    _applied_at = field_validator("applied_at")(_require_aware)

    @field_validator("resume_id")
    @classmethod
    def normalize_resume_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        try:
            return str(UUID(value.strip()))
        except ValueError as exc:
            raise ValueError("resume_id must be a valid UUID") from exc


class JobAlertCreate(StrictModel):
    query: str = Field(min_length=1, max_length=300)
    company_name: Optional[str] = Field(None, max_length=200)
    location: Optional[str] = Field(None, max_length=200)
    source_url: str = Field(min_length=1, max_length=500)
    frequency: Literal["daily", "weekly"] = "daily"
    active: bool = True

    _source_url = field_validator("source_url")(_validate_web_url)


class JobAlertUpdate(StrictModel):
    query: Optional[str] = Field(None, min_length=1, max_length=300)
    company_name: Optional[str] = Field(None, max_length=200)
    location: Optional[str] = Field(None, max_length=200)
    source_url: Optional[str] = Field(None, min_length=1, max_length=500)
    frequency: Optional[Literal["daily", "weekly"]] = None
    active: Optional[bool] = None

    _source_url = field_validator("source_url")(_validate_web_url)


class ReminderCreate(StrictModel):
    remind_at: datetime
    note: Optional[str] = Field(None, max_length=1_000)

    _remind_at = field_validator("remind_at")(_require_aware)


class ReminderUpdate(StrictModel):
    remind_at: Optional[datetime] = None
    note: Optional[str] = Field(None, max_length=1_000)

    _remind_at = field_validator("remind_at")(_require_aware)


class InterviewCreate(StrictModel):
    round_name: str = Field(min_length=1, max_length=200)
    interview_format: Literal["phone", "video", "onsite", "take_home", "other"]
    starts_at: datetime
    duration_minutes: int = Field(60, ge=5, le=1_440)
    timezone: str = Field("UTC", min_length=1, max_length=100)
    location: Optional[str] = Field(None, max_length=500)
    interviewers: list[str] = Field(default_factory=list, max_length=20)
    notes: Optional[str] = Field(None, max_length=5_000)

    _starts_at = field_validator("starts_at")(_require_aware)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value

    @field_validator("interviewers")
    @classmethod
    def validate_interviewers(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if any(len(value) > 200 for value in cleaned):
            raise ValueError("Interviewer names must be at most 200 characters")
        return cleaned


class InterviewUpdate(StrictModel):
    round_name: Optional[str] = Field(None, min_length=1, max_length=200)
    interview_format: Optional[Literal["phone", "video", "onsite", "take_home", "other"]] = None
    starts_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(None, ge=5, le=1_440)
    timezone: Optional[str] = Field(None, min_length=1, max_length=100)
    location: Optional[str] = Field(None, max_length=500)
    interviewers: Optional[list[str]] = Field(None, max_length=20)
    notes: Optional[str] = Field(None, max_length=5_000)

    _starts_at = field_validator("starts_at")(_require_aware)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value

    @field_validator("interviewers")
    @classmethod
    def validate_interviewers(cls, values: Optional[list[str]]) -> Optional[list[str]]:
        if values is None:
            return None
        cleaned = [value.strip() for value in values if value.strip()]
        if any(len(value) > 200 for value in cleaned):
            raise ValueError("Interviewer names must be at most 200 characters")
        return cleaned


class CompanyCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    website: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=5_000)

    _website = field_validator("website")(_validate_web_url)


class CompanyUpdate(StrictModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    website: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=5_000)

    _website = field_validator("website")(_validate_web_url)


class ContactCreate(StrictModel):
    company_id: Optional[str] = None
    name: str = Field(min_length=1, max_length=200)
    role_title: Optional[str] = Field(None, max_length=200)
    email: Optional[str] = Field(None, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    phone: Optional[str] = Field(None, max_length=100)
    linkedin_url: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=5_000)

    _linkedin_url = field_validator("linkedin_url")(_validate_web_url)


class ContactUpdate(StrictModel):
    company_id: Optional[str] = None
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    role_title: Optional[str] = Field(None, max_length=200)
    email: Optional[str] = Field(None, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    phone: Optional[str] = Field(None, max_length=100)
    linkedin_url: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=5_000)

    _linkedin_url = field_validator("linkedin_url")(_validate_web_url)


def _serialize(model: object, fields: tuple[str, ...]) -> dict:
    result = {}
    for field in fields:
        value = getattr(model, field)
        result[field] = value.isoformat() if isinstance(value, datetime) else value
    return result


SAVED_FIELDS = (
    "id",
    "company_name",
    "role_title",
    "job_url",
    "job_description_text",
    "notes",
    "created_at",
    "updated_at",
)
ALERT_FIELDS = (
    "id",
    "query",
    "company_name",
    "location",
    "source_url",
    "frequency",
    "active",
    "last_notified_at",
    "created_at",
    "updated_at",
)
REMINDER_FIELDS = ("id", "application_id", "remind_at", "note", "sent_at", "created_at")
INTERVIEW_FIELDS = (
    "id",
    "application_id",
    "round_name",
    "interview_format",
    "starts_at",
    "duration_minutes",
    "timezone",
    "location",
    "interviewers",
    "notes",
    "created_at",
    "updated_at",
)
COMPANY_FIELDS = ("id", "name", "website", "notes", "created_at")
CONTACT_FIELDS = (
    "id",
    "company_id",
    "name",
    "role_title",
    "email",
    "phone",
    "linkedin_url",
    "notes",
    "created_at",
    "updated_at",
)


async def _owned(db: AsyncSession, model: type, item_id: str, user_id: str, label: str):
    ensure_uuid(item_id, f"{label} not found")
    item = (await db.execute(select(model).where(model.id == item_id, model.user_id == user_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return item


async def _owned_application(db: AsyncSession, app_id: str, user_id: str) -> JobApplication:
    return await _owned(db, JobApplication, app_id, user_id, "Application")


async def _validate_company(db: AsyncSession, company_id: Optional[str], user_id: str) -> None:
    if company_id is not None:
        await _owned(db, TrackerCompany, company_id, user_id, "Company")


def _reject_nulls(values: dict, required_fields: set[str]) -> None:
    if any(field in values and values[field] is None for field in required_fields):
        raise HTTPException(status_code=422, detail="Required fields cannot be null")


@router.post("/saved-jobs", status_code=status.HTTP_201_CREATED)
async def create_saved_job(
    body: SavedJobCreate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    item = SavedJob(id=str(uuid4()), user_id=user_id, **body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _serialize(item, SAVED_FIELDS)


@router.get("/saved-jobs")
async def list_saved_jobs(user_id: str = Depends(get_current_user_required), db: AsyncSession = Depends(get_db)):
    items = (
        await db.execute(select(SavedJob).where(SavedJob.user_id == user_id).order_by(SavedJob.created_at.desc()))
    ).scalars()
    return [_serialize(item, SAVED_FIELDS) for item in items]


@router.put("/saved-jobs/{item_id}")
async def update_saved_job(
    item_id: str,
    body: SavedJobUpdate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    item = await _owned(db, SavedJob, item_id, user_id, "Saved job")
    values = body.model_dump(exclude_unset=True)
    _reject_nulls(values, {"company_name", "role_title"})
    for field, value in values.items():
        setattr(item, field, value)
    item.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _serialize(item, SAVED_FIELDS)


@router.delete("/saved-jobs/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_job(
    item_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    ensure_uuid(item_id, "Saved job not found")
    item = (
        await db.execute(select(SavedJob).where(SavedJob.id == item_id, SavedJob.user_id == user_id).with_for_update())
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Saved job not found")
    await db.delete(item)
    await db.commit()


@router.delete("/saved-jobs", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_delete_saved_jobs(
    ids: Annotated[list[str], Query(min_length=1, max_length=100)],
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    for item_id in ids:
        ensure_uuid(item_id, "Saved job not found")
    await db.execute(delete(SavedJob).where(SavedJob.user_id == user_id, SavedJob.id.in_(ids)))
    await db.commit()


@router.post("/saved-jobs/{item_id}/track", status_code=status.HTTP_201_CREATED)
async def track_saved_job(
    item_id: str,
    body: TrackSavedJobRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    from .tracker_routes import _get_latest_ats_score

    ensure_uuid(item_id, "Saved job not found")
    item = (
        await db.execute(select(SavedJob).where(SavedJob.id == item_id, SavedJob.user_id == user_id).with_for_update())
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Saved job not found")
    ats_score = None
    if body.resume_id:
        from ..database.models import Resume

        await _owned(db, Resume, body.resume_id, user_id, "Resume")
        ats_score = await _get_latest_ats_score(body.resume_id, db)
    now = datetime.now(timezone.utc)
    application = JobApplication(
        id=str(uuid4()),
        user_id=user_id,
        company_name=item.company_name,
        role_title=item.role_title,
        status=body.status,
        resume_id=body.resume_id,
        ats_score_at_submission=ats_score,
        job_description_text=item.job_description_text,
        job_url=item.job_url,
        company_logo_url=_logo_url(item.company_name),
        notes=item.notes,
        applied_at=body.applied_at or now,
        created_at=now,
        updated_at=now,
    )
    db.add(application)
    await db.delete(item)
    await db.commit()
    return {"application_id": str(application.id), "saved_job_deleted": True}


@router.post("/alerts", status_code=status.HTTP_201_CREATED)
async def create_alert(
    body: JobAlertCreate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    item = JobAlert(id=str(uuid4()), user_id=user_id, **body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _serialize(item, ALERT_FIELDS)


@router.get("/alerts")
async def list_alerts(user_id: str = Depends(get_current_user_required), db: AsyncSession = Depends(get_db)):
    items = (
        await db.execute(select(JobAlert).where(JobAlert.user_id == user_id).order_by(JobAlert.created_at.desc()))
    ).scalars()
    return [_serialize(item, ALERT_FIELDS) for item in items]


@router.get("/stale-applications")
async def list_stale_applications(
    days: int = Query(14, ge=1, le=365),
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Return active applications that have not changed within the selected window."""
    current = datetime.now(timezone.utc)
    cutoff = current - timedelta(days=days)
    items = (
        await db.execute(
            select(JobApplication)
            .where(
                JobApplication.user_id == user_id,
                JobApplication.status.notin_({"offer", "rejected", "withdrawn"}),
                JobApplication.updated_at <= cutoff,
            )
            .order_by(JobApplication.updated_at)
        )
    ).scalars()
    result = []
    for item in items:
        updated_at = item.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        serialized = _serialize_application(item)
        serialized["days_since_update"] = max(0, (current - updated_at).days)
        result.append(serialized)
    return result


@router.put("/alerts/{item_id}")
async def update_alert(
    item_id: str,
    body: JobAlertUpdate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    item = await _owned(db, JobAlert, item_id, user_id, "Alert")
    values = body.model_dump(exclude_unset=True)
    _reject_nulls(values, {"query", "source_url", "frequency", "active"})
    for field, value in values.items():
        setattr(item, field, value)
    if values:
        # A worker may have claimed this alert before the edit. Invalidate that
        # claim so it cannot send the pre-edit content or finalize stale state.
        item.delivery_claimed_at = None
        item.delivery_claim_token = None
        item.delivery_last_error = None
    item.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _serialize(item, ALERT_FIELDS)


@router.delete("/alerts/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    item_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    item = await _owned(db, JobAlert, item_id, user_id, "Alert")
    await db.delete(item)
    await db.commit()


@router.post("/applications/{app_id}/reminders", status_code=status.HTTP_201_CREATED)
async def create_reminder(
    app_id: str,
    body: ReminderCreate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    await _owned_application(db, app_id, user_id)
    if body.remind_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Reminder must be in the future")
    item = ApplicationReminder(id=str(uuid4()), user_id=user_id, application_id=app_id, **body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _serialize(item, REMINDER_FIELDS)


@router.get("/applications/{app_id}/reminders")
async def list_reminders(
    app_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    await _owned_application(db, app_id, user_id)
    items = (
        await db.execute(
            select(ApplicationReminder)
            .where(
                ApplicationReminder.application_id == app_id,
                ApplicationReminder.user_id == user_id,
            )
            .order_by(ApplicationReminder.remind_at)
        )
    ).scalars()
    return [_serialize(item, REMINDER_FIELDS) for item in items]


@router.put("/applications/{app_id}/reminders/{item_id}")
async def update_reminder(
    app_id: str,
    item_id: str,
    body: ReminderUpdate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    await _owned_application(db, app_id, user_id)
    item = await _owned(db, ApplicationReminder, item_id, user_id, "Reminder")
    if str(item.application_id) != app_id:
        raise HTTPException(status_code=404, detail="Reminder not found")
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=422, detail="At least one reminder field is required")
    _reject_nulls(values, {"remind_at"})
    if values.get("remind_at") is not None and values["remind_at"] <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Reminder must be in the future")
    if item.sent_at is not None and "remind_at" not in values:
        raise HTTPException(
            status_code=422,
            detail="A future reminder time is required to reschedule a sent reminder",
        )
    for field, value in values.items():
        setattr(item, field, value)
    if "remind_at" in values:
        item.sent_at = None
        # Rescheduling invalidates an in-flight claim for the old due time.
        item.delivery_claimed_at = None
        item.delivery_claim_token = None
        item.delivery_last_error = None
    await db.commit()
    return _serialize(item, REMINDER_FIELDS)


@router.delete("/applications/{app_id}/reminders/{item_id}", status_code=204)
async def delete_reminder(
    app_id: str,
    item_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    await _owned_application(db, app_id, user_id)
    item = await _owned(db, ApplicationReminder, item_id, user_id, "Reminder")
    if str(item.application_id) != app_id:
        raise HTTPException(status_code=404, detail="Reminder not found")
    await db.delete(item)
    await db.commit()


@router.post("/applications/{app_id}/interviews", status_code=status.HTTP_201_CREATED)
async def create_interview(
    app_id: str,
    body: InterviewCreate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    await _owned_application(db, app_id, user_id)
    item = ApplicationInterview(id=str(uuid4()), user_id=user_id, application_id=app_id, **body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _serialize(item, INTERVIEW_FIELDS)


@router.get("/applications/{app_id}/interviews")
async def list_interviews(
    app_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    await _owned_application(db, app_id, user_id)
    items = (
        await db.execute(
            select(ApplicationInterview)
            .where(
                ApplicationInterview.application_id == app_id,
                ApplicationInterview.user_id == user_id,
            )
            .order_by(ApplicationInterview.starts_at)
        )
    ).scalars()
    return [_serialize(item, INTERVIEW_FIELDS) for item in items]


@router.put("/applications/{app_id}/interviews/{item_id}")
async def update_interview(
    app_id: str,
    item_id: str,
    body: InterviewUpdate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    await _owned_application(db, app_id, user_id)
    item = await _owned(db, ApplicationInterview, item_id, user_id, "Interview")
    if str(item.application_id) != app_id:
        raise HTTPException(status_code=404, detail="Interview not found")
    values = body.model_dump(exclude_unset=True)
    _reject_nulls(
        values,
        {
            "round_name",
            "interview_format",
            "starts_at",
            "duration_minutes",
            "timezone",
            "interviewers",
        },
    )
    for field, value in values.items():
        setattr(item, field, value)
    item.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _serialize(item, INTERVIEW_FIELDS)


@router.delete("/applications/{app_id}/interviews/{item_id}", status_code=204)
async def delete_interview(
    app_id: str,
    item_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    await _owned_application(db, app_id, user_id)
    item = await _owned(db, ApplicationInterview, item_id, user_id, "Interview")
    if str(item.application_id) != app_id:
        raise HTTPException(status_code=404, detail="Interview not found")
    await db.delete(item)
    await db.commit()


def _ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _fold_ics_line(value: str) -> list[str]:
    """Fold one RFC 5545 content line without splitting UTF-8 characters."""
    lines: list[str] = []
    current = ""
    byte_limit = 75
    for character in value:
        candidate = current + character
        if current and len(candidate.encode("utf-8")) > byte_limit:
            lines.append(current)
            current = f" {character}"
            byte_limit = 75
        else:
            current = candidate
    lines.append(current)
    return lines


@router.get("/applications/{app_id}/interviews/{item_id}.ics")
async def export_interview_calendar(
    app_id: str,
    item_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    application = await _owned_application(db, app_id, user_id)
    item = await _owned(db, ApplicationInterview, item_id, user_id, "Interview")
    if str(item.application_id) != app_id:
        raise HTTPException(status_code=404, detail="Interview not found")
    start = item.starts_at.astimezone(timezone.utc)
    end = start + timedelta(minutes=item.duration_minutes)
    summary = _ics_escape(f"{item.round_name} — {application.company_name}")
    description_parts = [f"Role: {application.role_title}"]
    if item.interviewers:
        description_parts.append(f"Interviewers: {', '.join(item.interviewers)}")
    if item.notes:
        description_parts.append(item.notes)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Latexy//Application Tracker//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{item.id}@latexy.xyz",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{summary}",
        f"DESCRIPTION:{_ics_escape(chr(10).join(description_parts))}",
    ]
    if item.location:
        lines.append(f"LOCATION:{_ics_escape(item.location)}")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    folded_lines = [folded for line in lines for folded in _fold_ics_line(line)]
    return Response(
        content="\r\n".join([*folded_lines, ""]),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="interview-{item.id}.ics"'},
    )


@router.post("/companies", status_code=status.HTTP_201_CREATED)
async def create_company(
    body: CompanyCreate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    item = TrackerCompany(id=str(uuid4()), user_id=user_id, **body.model_dump())
    db.add(item)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A company with this name already exists") from exc
    await db.refresh(item)
    return _serialize(item, COMPANY_FIELDS)


@router.get("/companies")
async def list_companies(user_id: str = Depends(get_current_user_required), db: AsyncSession = Depends(get_db)):
    items = (
        await db.execute(select(TrackerCompany).where(TrackerCompany.user_id == user_id).order_by(TrackerCompany.name))
    ).scalars()
    return [_serialize(item, COMPANY_FIELDS) for item in items]


@router.put("/companies/{item_id}")
async def update_company(
    item_id: str,
    body: CompanyUpdate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    item = await _owned(db, TrackerCompany, item_id, user_id, "Company")
    values = body.model_dump(exclude_unset=True)
    _reject_nulls(values, {"name"})
    for field, value in values.items():
        setattr(item, field, value)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A company with this name already exists") from exc
    return _serialize(item, COMPANY_FIELDS)


@router.delete("/companies/{item_id}", status_code=204)
async def delete_company(
    item_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    item = await _owned(db, TrackerCompany, item_id, user_id, "Company")
    await db.delete(item)
    await db.commit()


@router.post("/contacts", status_code=status.HTTP_201_CREATED)
async def create_contact(
    body: ContactCreate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    await _validate_company(db, body.company_id, user_id)
    item = TrackerContact(id=str(uuid4()), user_id=user_id, **body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _serialize(item, CONTACT_FIELDS)


@router.get("/contacts")
async def list_contacts(user_id: str = Depends(get_current_user_required), db: AsyncSession = Depends(get_db)):
    items = (
        await db.execute(select(TrackerContact).where(TrackerContact.user_id == user_id).order_by(TrackerContact.name))
    ).scalars()
    return [_serialize(item, CONTACT_FIELDS) for item in items]


@router.put("/contacts/{item_id}")
async def update_contact(
    item_id: str,
    body: ContactUpdate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    item = await _owned(db, TrackerContact, item_id, user_id, "Contact")
    values = body.model_dump(exclude_unset=True)
    _reject_nulls(values, {"name"})
    if "company_id" in values:
        await _validate_company(db, values["company_id"], user_id)
    for field, value in values.items():
        setattr(item, field, value)
    item.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return _serialize(item, CONTACT_FIELDS)


@router.delete("/contacts/{item_id}", status_code=204)
async def delete_contact(
    item_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    item = await _owned(db, TrackerContact, item_id, user_id, "Contact")
    await db.delete(item)
    await db.commit()
