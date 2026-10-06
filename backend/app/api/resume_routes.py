import io
import json
import re
import secrets
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    computed_field,
    field_validator,
    model_validator,
)
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ..core.config import settings
from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import (
    Compilation,
    Optimization,
    Resume,
    ResumeCollaborator,
    ResumeTemplate,
    UsageAnalytics,
    User,
)
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.entitlements import require_feature
from ..parsers.parser_factory import parser_factory
from ..services.academic_cv_service import academic_cv_service
from ..services.ats_resume_schema import CanonicalATSResume, from_structured_resume
from ..services.collab_manager import CLOSE_ROLE_CHANGED, collab_manager
from ..services.entitlement_service import entitlement_service
from ..services.format_detection import ResumeFormat, format_detection_service
from ..services.json_resume_interchange_service import json_resume_interchange_service
from ..services.resume_builder_service import (
    SUPPORTED_BUILDER_CATEGORIES,
    StructuredResume,
    resume_builder_service,
)
from ..services.resume_validation_service import (
    pydantic_validation_issues,
    validation_error_detail,
    value_error_issue,
)
from ..services.variant_visibility_service import (
    VariantVisibility,
    apply_variant_visibility,
    prune_variant_visibility,
    validate_variant_visibility,
)
from ..utils.bounded_io import MAX_COMPILED_PDF_BYTES, decode_base64_bounded, read_file_bounded
from ..utils.file_utils import get_job_files, read_upload_capped, validate_file_upload
from ..utils.uuid_guard import ensure_uuid

logger = get_logger(__name__)

router = APIRouter(prefix="/resumes", tags=["resumes"])

# --- Schemas ---

ALLOWED_DOCUMENT_TYPES = frozenset({"resume", "presentation", "academic_cv", "cover_letter"})
MAX_LATEX_CONTENT_LEN = 1_000_000  # ~1MB cap to prevent unbounded storage/DoS
_MAX_COMPILED_PDF_BYTES = 20 * 1024 * 1024


def _validate_document_type(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in ALLOWED_DOCUMENT_TYPES:
        raise ValueError(f"document_type must be one of {sorted(ALLOWED_DOCUMENT_TYPES)}")
    return v


class ResumeBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    latex_content: str = Field(..., max_length=MAX_LATEX_CONTENT_LEN)
    is_template: bool = False
    tags: Optional[List[str]] = None
    document_type: str = "resume"


class ResumeCreate(ResumeBase):
    # document_type validation is enforced on input only (not on ResumeResponse,
    # which inherits ResumeBase and must faithfully echo stored values).
    @field_validator("document_type")
    @classmethod
    def _check_document_type(cls, v: str) -> str:
        return _validate_document_type(v)


class ResumeUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    latex_content: Optional[str] = Field(default=None, max_length=MAX_LATEX_CONTENT_LEN)
    # Optimistic-concurrency token for full-document writers. The endpoint
    # requires it whenever latex_content is present, so a stale collaboration
    # channel cannot overwrite a newer suggestion decision or peer edit.
    expected_latex_content: Optional[str] = Field(default=None, max_length=MAX_LATEX_CONTENT_LEN)
    is_template: Optional[bool] = None
    tags: Optional[List[str]] = None
    document_type: Optional[str] = None
    portfolio_visible: Optional[bool] = None

    @field_validator("document_type")
    @classmethod
    def _check_document_type(cls, v: Optional[str]) -> Optional[str]:
        return _validate_document_type(v)

    @field_validator("expected_latex_content", mode="after")
    @classmethod
    def _check_expected_latex_content_utf8(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                if len(v.encode("utf-8", errors="strict")) > 4_000_000:
                    raise ValueError("expected_latex_content exceeds the byte limit")
            except UnicodeEncodeError as exc:
                raise ValueError("expected_latex_content must contain valid Unicode text") from exc
        return v


class ResumeResponse(ResumeBase):
    id: str
    user_id: str
    document_type: str = "resume"
    parent_resume_id: Optional[str] = None
    variant_visibility: Optional[Dict[str, Any]] = None
    variant_count: int = 0
    selected_template_id: Optional[str] = None
    content_source: str = "manual_latex"
    builder_status: str = "detached"
    structured_content: Optional[Dict[str, Any]] = None
    structured_version: int = 1
    # resume_settings is the ORM attribute; we expose it as "metadata" in JSON
    metadata: Optional[Dict[str, Any]] = Field(default=None, validation_alias="resume_settings")
    share_token: Optional[str] = None
    share_url: Optional[str] = None
    share_anonymous: bool = False
    share_review_comments: bool = False
    # GitHub sync (Feature 37)
    github_sync_enabled: bool = False
    github_repo_name: Optional[str] = None
    github_last_sync_at: Optional[datetime] = None
    dropbox_sync_enabled: bool = False
    dropbox_folder_path: Optional[str] = None
    dropbox_last_sync_at: Optional[datetime] = None
    portfolio_visible: bool = False
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None
    pinned: bool = False
    # Effective access for the caller. Owner-only endpoints can rely on the
    # default; GET/PUT /resumes/{id} set this explicitly for collaborators.
    access_role: Literal["owner", "editor", "commenter", "viewer"] = "owner"

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="after")
    def _compute_share_url(self) -> "ResumeResponse":
        if self.share_token and not self.share_url:
            self.share_url = f"{settings.FRONTEND_URL}/r/{self.share_token}"
        return self

    @model_validator(mode="after")
    def _extract_pinned(self) -> "ResumeResponse":
        if self.metadata and self.metadata.get("pinned"):
            self.pinned = True
        return self

    # Freshness (Feature 48) — computed from updated_at, never read from ORM/mock
    @computed_field
    @property
    def days_since_updated(self) -> int:
        now = datetime.now(timezone.utc)
        updated = self.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return (now - updated).days

    @computed_field
    @property
    def freshness_status(self) -> str:
        days = self.days_since_updated
        return "fresh" if days < 30 else "stale" if days < 90 else "very_stale"


def _typed_attr(obj: Any, name: str, expected_type: type | tuple[type, ...], default: Any = None) -> Any:
    """Return an attribute only when it is the expected concrete type.

    Mock-based tests and partially-populated objects can expose MagicMock
    placeholders for newly added optional ORM fields. Those should fall back to
    response defaults instead of turning API serialization into a 500.
    """
    value = getattr(obj, name, default)
    return value if isinstance(value, expected_type) else default


def _resume_response_from_obj(resume: Any, *, access_role: str = "owner") -> ResumeResponse:
    """Serialize a Resume-like object with safe fallbacks for optional fields."""
    payload = {
        "id": str(resume.id),
        "user_id": str(resume.user_id),
        "title": resume.title,
        "latex_content": resume.latex_content,
        "is_template": bool(getattr(resume, "is_template", False)),
        "tags": _typed_attr(resume, "tags", list),
        "document_type": _typed_attr(resume, "document_type", str, "resume"),
        "parent_resume_id": _typed_attr(resume, "parent_resume_id", str),
        "variant_visibility": _typed_attr(resume, "variant_visibility", dict),
        "variant_count": int(getattr(resume, "variant_count", 0) or 0),
        "selected_template_id": _typed_attr(resume, "selected_template_id", str),
        "content_source": _typed_attr(resume, "content_source", str, "manual_latex"),
        "builder_status": _typed_attr(resume, "builder_status", str, "detached"),
        "structured_content": _typed_attr(resume, "structured_content", dict),
        "structured_version": int(getattr(resume, "structured_version", 1) or 1),
        "metadata": _typed_attr(resume, "resume_settings", dict),
        "share_token": _typed_attr(resume, "share_token", str),
        "share_url": _typed_attr(resume, "share_url", str),
        "share_anonymous": bool((_typed_attr(resume, "resume_settings", dict) or {}).get("share_anonymous", False)),
        "share_review_comments": bool(
            (_typed_attr(resume, "resume_settings", dict) or {}).get("share_review_comments", False)
        ),
        "github_sync_enabled": bool(getattr(resume, "github_sync_enabled", False)),
        "github_repo_name": _typed_attr(resume, "github_repo_name", str),
        "github_last_sync_at": getattr(resume, "github_last_sync_at", None),
        "dropbox_sync_enabled": bool(getattr(resume, "dropbox_sync_enabled", False)),
        "dropbox_folder_path": _typed_attr(resume, "dropbox_folder_path", str),
        "dropbox_last_sync_at": getattr(resume, "dropbox_last_sync_at", None),
        "portfolio_visible": bool(getattr(resume, "portfolio_visible", False)),
        "created_at": resume.created_at,
        "updated_at": resume.updated_at,
        "archived_at": getattr(resume, "archived_at", None),
        "pinned": bool(getattr(resume, "pinned", False)),
        "access_role": access_role,
    }
    return ResumeResponse.model_validate(payload)


# NOTE: --shell-escape is intentionally excluded — it enables arbitrary code execution
ALLOWED_LATEXMK_FLAGS = [
    "--synctex=1",
    "--file-line-error",
    "--interaction=nonstopmode",
    "--halt-on-error",
]
# These values are persisted in resume metadata and replayed by worker jobs.
# Keep their cardinality bounded even when a caller repeats valid values.
MAX_EXTRA_PACKAGES = 64
MAX_LATEXMK_FLAGS = len(ALLOWED_LATEXMK_FLAGS)


class ResumeSettingsUpdate(BaseModel):
    compiler: Optional[str] = None
    custom_flags: Optional[str] = None  # kept for backward compat
    texlive_version: Optional[str] = None
    main_file: Optional[str] = None
    latexmk_flags: Optional[List[str]] = None
    extra_packages: Optional[List[str]] = None
    halt_on_error: Optional[StrictBool] = None
    draft_mode: Optional[StrictBool] = None
    last_persona: Optional[str] = None

    @field_validator("texlive_version")
    @classmethod
    def validate_texlive_version(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("2022", "2023", "2024"):
            raise ValueError("texlive_version must be one of: 2022, 2023, 2024")
        return v

    @field_validator("main_file")
    @classmethod
    def validate_main_file(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.fullmatch(r"[a-zA-Z0-9_-]+\.tex", v):
            raise ValueError("main_file must match [a-zA-Z0-9_-]+.tex (no path separators)")
        return v

    @field_validator("latexmk_flags")
    @classmethod
    def validate_latexmk_flags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            if len(v) > MAX_LATEXMK_FLAGS:
                raise ValueError(f"At most {MAX_LATEXMK_FLAGS} compiler flags may be selected")
            v = list(dict.fromkeys(v))
            for flag in v:
                if flag not in ALLOWED_LATEXMK_FLAGS:
                    raise ValueError(f"Flag {flag!r} is not in the allowed list: {ALLOWED_LATEXMK_FLAGS}")
        return v

    @field_validator("extra_packages")
    @classmethod
    def validate_extra_packages(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            if len(v) > MAX_EXTRA_PACKAGES:
                raise ValueError(f"At most {MAX_EXTRA_PACKAGES} extra packages may be selected")
            v = list(dict.fromkeys(v))
            for pkg in v:
                if len(pkg) > 50:
                    raise ValueError(f"Package name too long: {pkg!r} (max 50 chars)")
                if not re.fullmatch(r"[a-zA-Z0-9-]+", pkg):
                    raise ValueError(f"Invalid package name {pkg!r}: only alphanumeric and hyphens allowed")
        return v


class ResumeStats(BaseModel):
    total_resumes: int
    total_templates: int
    last_updated: Optional[datetime]
    avg_ats_score: Optional[float] = None
    best_ats_score: Optional[float] = None
    optimized_count: int = 0


class BuilderTemplateResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    category: str
    category_label: str
    sort_order: int
    thumbnail_url: Optional[str]
    pdf_url: Optional[str]
    template_family: str


class BuilderMetricsResponse(BaseModel):
    completeness_score: int
    page_estimate: int
    warnings: List[str]
    missing_sections: List[str]


class BuilderPreviewSectionResponse(BaseModel):
    key: str
    title: str
    items: List[Any]


class BuilderPreviewResponse(BaseModel):
    template_family: str
    sections: List[BuilderPreviewSectionResponse]


class BuilderResumeCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    template_id: str
    structured_content: Optional[Dict[str, Any]] = None


class BuilderResumePatchRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    template_id: Optional[str] = None
    structured_content: Optional[Dict[str, Any]] = None
    force_reattach: bool = False


class BuilderResumeResponse(BaseModel):
    resume: ResumeResponse
    metrics: BuilderMetricsResponse
    preview: BuilderPreviewResponse
    template_family: str
    ats_profile: CanonicalATSResume


class BuilderSeedUploadResponse(BaseModel):
    success: bool
    filename: str
    format: str
    structured_content: Dict[str, Any]
    metrics: BuilderMetricsResponse
    interchange_warnings: List[str] = Field(default_factory=list)


# --- Search schemas ---


class SearchMatch(BaseModel):
    line_number: int
    line_content: str
    context_before: List[str]
    context_after: List[str]
    highlight_start: int
    highlight_end: int


class ResumeSearchResult(BaseModel):
    resume_id: str
    resume_title: str
    updated_at: datetime
    matches: List[SearchMatch]


class SearchResponse(BaseModel):
    results: List[ResumeSearchResult]
    total_resumes_matched: int
    query: str


# --- Endpoints ---

_BUILDER_CATEGORY_LABELS = {
    "ats_safe": "ATS-Safe",
    "minimal": "Minimal / Clean",
    "software_engineering": "Software Engineering",
    "executive": "Executive",
    "graduate": "Graduate / Entry-Level",
}


def _builder_category_label(category: str) -> str:
    return _BUILDER_CATEGORY_LABELS.get(category, category.replace("_", " ").title())


def _normalize_builder_input(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        return resume_builder_service.normalize(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=validation_error_detail(pydantic_validation_issues(exc, prefix=("structured_content",))),
        ) from exc


def _template_to_builder_response(template: ResumeTemplate, base_url: str) -> BuilderTemplateResponse:
    root = base_url.rstrip("/")
    return BuilderTemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        category_label=_builder_category_label(template.category),
        sort_order=template.sort_order,
        thumbnail_url=f"{root}/templates/{template.id}/thumbnail",
        pdf_url=f"{root}/templates/{template.id}/pdf",
        template_family=resume_builder_service.template_family(template.category),
    )


async def _get_builder_template(db: AsyncSession, template_id: str) -> ResumeTemplate:
    template = await db.get(ResumeTemplate, template_id)
    if not template or not template.is_active:
        raise HTTPException(status_code=404, detail="Template not found")
    if not resume_builder_service.is_supported_category(template.category, template.document_type):
        raise HTTPException(status_code=400, detail="Template is not supported by the guided builder")
    return template


def _builder_payload(resume: Resume, category: str) -> BuilderResumeResponse:
    render = resume_builder_service.render(resume.structured_content or {}, category)
    preview = resume_builder_service.build_preview(resume.structured_content or {}, category)
    return BuilderResumeResponse(
        resume=_resume_response_from_obj(resume),
        metrics=BuilderMetricsResponse.model_validate(render.metrics.model_dump()),
        preview=BuilderPreviewResponse.model_validate(preview),
        template_family=render.template_family,
        ats_profile=from_structured_resume(resume.structured_content or {}),
    )


async def _sync_linked_variants(parent: Resume, db: AsyncSession) -> None:
    """Regenerate direct linked variants after their master source changes."""
    if not parent.structured_content:
        return
    result = await db.execute(
        select(Resume).where(
            Resume.parent_resume_id == parent.id,
            Resume.content_source == "builder_variant",
        )
    )
    for variant in result.scalars().all():
        template_id = variant.selected_template_id or parent.selected_template_id
        template = await db.get(ResumeTemplate, template_id) if template_id else None
        if not template or not resume_builder_service.is_supported_category(template.category, template.document_type):
            logger.warning("Linked variant template is unavailable", extra={"resume_id": variant.id})
            continue
        visibility = prune_variant_visibility(parent.structured_content, variant.variant_visibility)
        effective = apply_variant_visibility(parent.structured_content, visibility)
        variant.variant_visibility = visibility.model_dump()
        variant.latex_content = resume_builder_service.render(effective, template.category).latex_content
        variant.structured_version = parent.structured_version
        variant.updated_at = datetime.now(timezone.utc)


@router.get("/builder/templates", response_model=List[BuilderTemplateResponse])
async def list_builder_templates(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ResumeTemplate)
        .where(
            ResumeTemplate.is_active.is_(True),
            ResumeTemplate.document_type == "resume",
            ResumeTemplate.category.in_(tuple(sorted(SUPPORTED_BUILDER_CATEGORIES))),
        )
        .order_by(ResumeTemplate.category, ResumeTemplate.sort_order, ResumeTemplate.name)
    )
    templates = (await db.execute(stmt)).scalars().all()
    base_url = str(request.base_url)
    return [_template_to_builder_response(template, base_url) for template in templates]


@router.post("/builder/seed-upload", response_model=BuilderSeedUploadResponse)
async def seed_builder_from_upload(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    del db, user_id
    validate_file_upload(file)
    content = await read_upload_capped(file)
    filename = file.filename or "upload"
    detected_format = format_detection_service.detect_format(
        filename=filename,
        mime_type=file.content_type,
        content=content,
    )
    if detected_format == ResumeFormat.UNKNOWN:
        raise HTTPException(status_code=415, detail=f"Unsupported file format: '{filename}'")
    interchange_warnings: list[str] = []
    structured: dict[str, Any] | None = None
    response_format = detected_format.value
    if detected_format == ResumeFormat.JSON:
        try:
            json_source = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail=validation_error_detail(
                    [{"path": "$", "message": "The JSON file must use UTF-8 encoding.", "line": None, "column": None}]
                ),
            ) from exc
        try:
            json_payload = json.loads(json_source)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail=validation_error_detail(
                    [{"path": "$", "message": exc.msg, "line": exc.lineno, "column": exc.colno}]
                ),
            ) from exc
        if isinstance(json_payload, dict) and any(
            key in json_payload for key in ("$schema", "basics", "work", "education", "skills", "projects")
        ):
            try:
                structured, interchange_warnings = json_resume_interchange_service.from_json_resume(json_payload)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=validation_error_detail([value_error_issue(exc, json_source)]),
                ) from exc
            response_format = "json_resume_v1"

    if structured is None:
        parser = parser_factory.get_parser(detected_format)
        if not parser:
            raise HTTPException(status_code=415, detail=f"No parser available for {detected_format.value}")
        try:
            parsed = await parser.parse(content, filename)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Could not parse the uploaded file.") from exc
        structured = resume_builder_service.from_parsed_resume(parsed)

    structured = _normalize_builder_input(structured)
    metrics = resume_builder_service.render(structured, "minimal").metrics
    return BuilderSeedUploadResponse(
        success=True,
        filename=filename,
        format=response_format,
        structured_content=structured,
        metrics=BuilderMetricsResponse.model_validate(metrics.model_dump()),
        interchange_warnings=interchange_warnings,
    )


@router.post(
    "/builder",
    response_model=BuilderResumeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_feature("resume_builder"))],
)
async def create_builder_resume(
    body: BuilderResumeCreateRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    template = await _get_builder_template(db, body.template_id)
    structured = _normalize_builder_input(body.structured_content)
    render = resume_builder_service.render(structured, template.category)

    resume = Resume(
        id=str(uuid4()),
        user_id=user_id,
        title=body.title.strip(),
        latex_content=render.latex_content,
        structured_content=structured,
        structured_version=1,
        is_template=False,
        selected_template_id=template.id,
        content_source="builder",
        builder_status="active",
        document_type="resume",
        resume_settings={"compiler": settings.DEFAULT_NEW_RESUME_COMPILER},
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)
    return _builder_payload(resume, template.category)


@router.get("/stats", response_model=ResumeStats)
async def get_resume_stats(db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_required)):
    """Get high-level stats about user's resumes."""
    total = await db.execute(select(func.count(Resume.id)).where(Resume.user_id == user_id))
    templates = await db.execute(select(func.count(Resume.id)).where(Resume.user_id == user_id, Resume.is_template))
    latest = await db.execute(select(func.max(Resume.updated_at)).where(Resume.user_id == user_id))
    ats_avg = await db.execute(
        select(func.avg(Optimization.ats_score)).where(
            Optimization.user_id == user_id,
            Optimization.ats_score.is_not(None),
        )
    )
    ats_max = await db.execute(
        select(func.max(Optimization.ats_score)).where(
            Optimization.user_id == user_id,
            Optimization.ats_score.is_not(None),
        )
    )
    opt_count = await db.execute(
        select(func.count(func.distinct(Optimization.resume_id))).where(
            Optimization.user_id == user_id,
            Optimization.ats_score.is_not(None),
        )
    )

    avg_val = ats_avg.scalar()
    max_val = ats_max.scalar()
    return {
        "total_resumes": total.scalar() or 0,
        "total_templates": templates.scalar() or 0,
        "last_updated": latest.scalar(),
        "avg_ats_score": round(float(avg_val), 1) if avg_val is not None else None,
        "best_ats_score": round(float(max_val), 1) if max_val is not None else None,
        "optimized_count": opt_count.scalar() or 0,
    }


@router.post("/", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def create_resume(
    resume_in: ResumeCreate, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_required)
):
    """Create a new resume for the authenticated user."""
    payload = resume_in.model_dump()
    payload.setdefault("document_type", "resume")
    resume = Resume(
        id=str(uuid4()),
        user_id=user_id,
        content_source="manual_latex",
        builder_status="detached",
        structured_content=None,
        resume_settings={"compiler": settings.DEFAULT_NEW_RESUME_COMPILER},
        **payload,
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)

    if settings.OPENAI_API_KEY:
        try:
            from ..workers.ats_worker import submit_embed_resume

            submit_embed_resume(str(resume.id), resume.latex_content, user_id)
        except Exception as exc:
            logger.warning(
                "Failed to enqueue embedding for resume %s",
                resume.id,
                extra={"error_type": type(exc).__name__},
            )

    return resume


def _variant_count_subquery():
    """Correlated subquery counting direct child variants of each resume."""
    from sqlalchemy.orm import aliased

    ChildResume = aliased(Resume)
    return (
        select(func.count(ChildResume.id))
        .where(ChildResume.parent_resume_id == Resume.id)
        .correlate(Resume)
        .scalar_subquery()
        .label("variant_count")
    )


@router.get("/")
async def list_resumes(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    parent_id: Optional[str] = Query(None),
    archived: bool = Query(False),
    document_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """List resumes belonging to the authenticated user with pagination."""
    # FastAPI has already enforced page >= 1 and limit <= 200. Do not silently
    # clamp valid requests to 100 after advertising 200 in OpenAPI: clients use
    # the returned page count to make every resume reachable.
    offset = (page - 1) * limit

    filters = [Resume.user_id == user_id]
    if parent_id is not None:
        ensure_uuid(parent_id, "Parent resume not found")
        filters.append(Resume.parent_resume_id == parent_id)
    if document_type is not None:
        filters.append(Resume.document_type == document_type)
    # Filter by archive status
    if archived:
        filters.append(Resume.archived_at.is_not(None))
    else:
        filters.append(Resume.archived_at.is_(None))

    count_result = await db.execute(select(func.count(Resume.id)).where(*filters))
    total = count_result.scalar() or 0

    variant_count_sq = _variant_count_subquery()
    result = await db.execute(
        select(Resume, variant_count_sq).where(*filters).order_by(Resume.updated_at.desc()).offset(offset).limit(limit)
    )
    rows = result.all()

    resumes_out = []
    for resume, vc in rows:
        d = _resume_response_from_obj(resume).model_dump()
        d["variant_count"] = vc or 0
        resumes_out.append(d)

    return {
        "resumes": resumes_out,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


def _extract_search_matches(
    latex_content: Optional[str],
    query: str,
    context_lines: int = 2,
    max_matches: int = 5,
) -> List[SearchMatch]:
    if not latex_content:
        return []
    lines = latex_content.split("\n")
    q_lower = query.lower()
    matches: List[SearchMatch] = []
    for i, line in enumerate(lines):
        idx = line.lower().find(q_lower)
        if idx == -1:
            continue
        matches.append(
            SearchMatch(
                line_number=i + 1,
                line_content=line,
                context_before=lines[max(0, i - context_lines) : i],
                context_after=lines[i + 1 : i + 1 + context_lines],
                highlight_start=idx,
                highlight_end=idx + len(query),
            )
        )
        if len(matches) >= max_matches:
            break
    return matches


@router.get("/search", response_model=SearchResponse)
async def search_resumes(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Full-text search across all user resumes (title + LaTeX content)."""
    from sqlalchemy import or_

    where_clause = (
        Resume.user_id == user_id,
        Resume.is_template == False,  # noqa: E712
        or_(
            Resume.title.ilike(f"%{q}%"),
            Resume.latex_content.ilike(f"%{q}%"),
        ),
    )

    count_stmt = select(func.count()).select_from(Resume).where(*where_clause)
    total: int = (await db.execute(count_stmt)).scalar_one()

    stmt = select(Resume).where(*where_clause).order_by(Resume.updated_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    results = []
    for resume in rows:
        matches = _extract_search_matches(resume.latex_content, q)
        # If no latex match but title matched, still return with empty matches list
        results.append(
            ResumeSearchResult(
                resume_id=str(resume.id),
                resume_title=resume.title,
                updated_at=resume.updated_at,
                matches=matches[:3],
            )
        )

    return SearchResponse(
        results=results,
        total_resumes_matched=total,
        query=q,
    )


# ── Error History (Feature 88) ────────────────────────────────────────────


class ErrorHistorySummarySchema(BaseModel):
    error_type: str
    count: int
    last_seen: datetime
    last_resume_id: Optional[str]
    last_resume_title: Optional[str]
    example_line: str
    resolved: bool


@router.get("/error-history", response_model=List[ErrorHistorySummarySchema])
async def get_error_history(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """
    Return grouped compile-error history for the current user.

    Each entry represents a distinct LaTeX error type with occurrence count,
    last-seen timestamp, the offending resume, and whether it has since
    been resolved (i.e. a successful compile of that same resume followed).
    Sorted by count DESC, last_seen DESC.
    """
    from ..services.error_history_service import error_history_service

    summaries = await error_history_service.get_error_history(user_id=user_id, db=db, limit=limit)
    return [
        ErrorHistorySummarySchema(
            error_type=s.error_type,
            count=s.count,
            last_seen=s.last_seen,
            last_resume_id=s.last_resume_id,
            last_resume_title=s.last_resume_title,
            example_line=s.example_line,
            resolved=s.resolved,
        )
        for s in summaries
    ]


@router.get("/{resume_id}/builder", response_model=BuilderResumeResponse)
async def get_builder_resume(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    resume = await _verify_resume_ownership(db, resume_id, user_id)
    if not resume.selected_template_id or not resume.structured_content:
        raise HTTPException(status_code=404, detail="Builder data not available for this resume")
    template = await db.get(ResumeTemplate, resume.selected_template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Selected template not found")
    return _builder_payload(resume, template.category)


@router.patch("/{resume_id}/builder", response_model=BuilderResumeResponse)
async def update_builder_resume(
    resume_id: str,
    body: BuilderResumePatchRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    resume = await _verify_resume_ownership(db, resume_id, user_id)
    if resume.builder_status == "detached" and not body.force_reattach:
        raise HTTPException(
            status_code=409,
            detail="Builder is detached because this resume was edited in advanced mode. Pass force_reattach=true to overwrite LaTeX from builder data.",
        )

    template: Optional[ResumeTemplate] = None
    if body.template_id:
        template = await _get_builder_template(db, body.template_id)
        resume.selected_template_id = template.id
    elif resume.selected_template_id:
        template = await db.get(ResumeTemplate, resume.selected_template_id)

    if not template:
        raise HTTPException(status_code=400, detail="Builder resume must have a supported selected template")

    if body.title is not None:
        resume.title = body.title.strip()
    if body.structured_content is not None:
        resume.structured_content = _normalize_builder_input(body.structured_content)
        resume.structured_version = (resume.structured_version or 1) + 1
    elif not resume.structured_content:
        resume.structured_content = resume_builder_service.empty_document()

    render = resume_builder_service.render(resume.structured_content, template.category)
    resume.latex_content = render.latex_content
    resume.content_source = "builder"
    resume.builder_status = "active"
    resume.document_type = "resume"
    resume.updated_at = datetime.now(timezone.utc)
    await _sync_linked_variants(resume, db)
    await db.commit()
    await db.refresh(resume)
    return _builder_payload(resume, template.category)


_COLLABORATOR_ROLES = frozenset({"editor", "commenter", "viewer"})


async def _get_resume_document_access(
    db: AsyncSession,
    resume_id: str,
    user_id: str,
) -> tuple[Resume, str]:
    """Resolve owner/collaborator access without exposing unrelated resumes."""
    ensure_uuid(resume_id, "Resume not found")
    result = await db.execute(
        select(Resume, ResumeCollaborator.role)
        .outerjoin(
            ResumeCollaborator,
            and_(
                ResumeCollaborator.resume_id == Resume.id,
                ResumeCollaborator.user_id == user_id,
            ),
        )
        .where(Resume.id == resume_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Resume not found")

    resume, collaborator_role = row
    if resume.user_id == user_id:
        return resume, "owner"
    if collaborator_role in _COLLABORATOR_ROLES:
        return resume, collaborator_role
    raise HTTPException(status_code=404, detail="Resume not found")


@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(
    resume_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_required)
):
    """Get a specific resume by ID."""
    resume, access_role = await _get_resume_document_access(db, resume_id, user_id)
    variant_count_sq = _variant_count_subquery()
    vc_result = await db.execute(select(variant_count_sq).where(Resume.id == resume_id))
    vc = vc_result.scalar_one_or_none()
    resp = _resume_response_from_obj(resume, access_role=access_role)
    resp.variant_count = vc or 0
    return resp


@router.put("/{resume_id}", response_model=ResumeResponse)
async def update_resume(
    resume_id: str,
    resume_in: ResumeUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Update an existing resume."""
    resume, access_role = await _get_resume_document_access(db, resume_id, user_id)
    if access_role not in {"owner", "editor"}:
        raise HTTPException(status_code=403, detail="This collaborator has read-only access")

    update_data = resume_in.model_dump(exclude_unset=True)
    expected_latex_content = update_data.pop("expected_latex_content", None)
    if "latex_content" in update_data and expected_latex_content is None:
        raise HTTPException(
            status_code=428,
            detail={
                "code": "precondition_required",
                "message": "expected_latex_content is required when updating document content.",
            },
        )
    if "latex_content" in update_data:
        # Resolve the token against the latest row while holding the same row
        # lock used by other authoritative document mutations. The initial
        # access check above is intentionally repeated after the lock so a
        # collaborator revoked during this request cannot commit a stale save.
        locked_resume = (
            await db.execute(
                select(Resume)
                .where(Resume.id == resume_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if locked_resume is None:
            raise HTTPException(status_code=404, detail="Resume not found")
        resume, access_role = await _get_resume_document_access(db, resume_id, user_id)
        if access_role not in {"owner", "editor"}:
            raise HTTPException(status_code=403, detail="This collaborator has read-only access")
        incoming_latex_content = update_data["latex_content"]
        if resume.latex_content != expected_latex_content and resume.latex_content != incoming_latex_content:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "document_changed",
                    "message": "The document changed before this save; refresh and reconcile your edits.",
                },
            )
    if "portfolio_visible" in update_data and access_role != "owner":
        raise HTTPException(
            status_code=403,
            detail="Only the resume owner can change public portfolio visibility",
        )
    latex_changed = (
        "latex_content" in update_data
        and update_data["latex_content"] is not None
        and update_data["latex_content"] != resume.latex_content
    )
    for key, value in update_data.items():
        setattr(resume, key, value)

    if latex_changed and (
        (resume.selected_template_id and resume.structured_content) or resume.content_source == "builder_variant"
    ):
        resume.builder_status = "detached"
        resume.content_source = "manual_latex"
        resume.variant_visibility = None

    # Content changed → invalidate the cached anonymous (redacted) share PDF so the
    # next create_share_link call regenerates it from the updated content.
    if latex_changed:
        meta = dict(resume.resume_settings or {})
        if (
            meta.pop("share_anonymous_job_id", None) is not None
            or meta.pop("share_anonymous_pending", None) is not None
        ):
            resume.resume_settings = meta
            flag_modified(resume, "resume_settings")

    resume.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(resume)

    if settings.OPENAI_API_KEY and update_data.get("latex_content"):
        try:
            from ..workers.ats_worker import submit_embed_resume

            submit_embed_resume(str(resume.id), resume.latex_content, user_id)
        except Exception as exc:
            logger.warning(
                "Failed to enqueue embedding for resume %s",
                resume.id,
                extra={"error_type": type(exc).__name__},
            )

    return _resume_response_from_obj(resume, access_role=access_role)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_required)
):
    """Delete a resume."""
    # Guard non-UUID id (asyncpg DataError -> 500) as 404, like GET /{resume_id}.
    try:
        UUID(str(resume_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="Resume not found")
    result = await db.execute(delete(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Resume not found")
    await db.commit()
    return None


@router.patch("/{resume_id}/settings", response_model=ResumeResponse)
async def update_resume_settings(
    resume_id: str,
    body: ResumeSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Update per-resume settings (compiler preference, custom flags, etc.)."""
    # Guard non-UUID id (asyncpg DataError -> 500) as 404, like GET /{resume_id}.
    try:
        UUID(str(resume_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="Resume not found")
    result = await db.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Validate compiler if provided
    if body.compiler is not None:
        if body.compiler not in settings.ALLOWED_LATEX_COMPILERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid compiler '{body.compiler}'. Allowed: {settings.ALLOWED_LATEX_COMPILERS}",
            )

    # Merge into existing settings
    current_meta = dict(resume.resume_settings or {})
    if body.compiler is not None:
        current_meta["compiler"] = body.compiler
    if body.custom_flags is not None:
        current_meta["custom_flags"] = body.custom_flags
    if body.texlive_version is not None:
        current_meta["texlive_version"] = body.texlive_version
    if body.main_file is not None:
        current_meta["main_file"] = body.main_file
    if body.latexmk_flags is not None:
        current_meta["latexmk_flags"] = body.latexmk_flags
    if body.extra_packages is not None:
        current_meta["extra_packages"] = body.extra_packages
    if body.halt_on_error is not None:
        current_meta["halt_on_error"] = body.halt_on_error
    if body.draft_mode is not None:
        current_meta["draft_mode"] = body.draft_mode
    if body.last_persona is not None:
        current_meta["last_persona"] = body.last_persona

    resume.resume_settings = current_meta
    resume.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(resume)

    resp = _resume_response_from_obj(resume)
    resp.variant_count = 0
    return resp


# --- Tag / Pin / Archive endpoints (Feature 39) ---


class TagsUpdate(BaseModel):
    # max_length=10 on List in Pydantic v2 constrains item count (≤10 tags)
    tags: List[str] = Field(..., max_length=10)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        for tag in v:
            if len(tag) > 30:
                raise ValueError(f"Tag '{tag}' exceeds 30 characters")
            if not tag.strip():
                raise ValueError("Tags cannot be empty")
        return [t.strip() for t in v]


@router.patch("/{resume_id}/tags", response_model=ResumeResponse)
async def update_resume_tags(
    resume_id: str,
    body: TagsUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Set tags on a resume (replaces existing tags)."""
    resume = await _verify_resume_ownership(db, resume_id, user_id)
    resume.tags = body.tags
    await db.commit()
    await db.refresh(resume)
    return _resume_response_from_obj(resume)


@router.patch("/{resume_id}/pin", response_model=ResumeResponse)
async def pin_resume(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Pin a resume to the top of the workspace."""
    resume = await _verify_resume_ownership(db, resume_id, user_id)
    settings_dict = dict(resume.resume_settings or {})
    settings_dict["pinned"] = True
    resume.resume_settings = settings_dict
    await db.commit()
    await db.refresh(resume)
    return _resume_response_from_obj(resume)


@router.patch("/{resume_id}/unpin", response_model=ResumeResponse)
async def unpin_resume(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Unpin a resume."""
    resume = await _verify_resume_ownership(db, resume_id, user_id)
    settings_dict = dict(resume.resume_settings or {})
    settings_dict.pop("pinned", None)
    resume.resume_settings = settings_dict
    await db.commit()
    await db.refresh(resume)
    return _resume_response_from_obj(resume)


@router.patch("/{resume_id}/archive", response_model=ResumeResponse)
async def archive_resume(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Archive a resume (hides from default workspace listing)."""
    resume = await _verify_resume_ownership(db, resume_id, user_id)
    resume.archived_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(resume)
    return _resume_response_from_obj(resume)


@router.patch("/{resume_id}/unarchive", response_model=ResumeResponse)
async def unarchive_resume(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Unarchive a resume."""
    resume = await _verify_resume_ownership(db, resume_id, user_id)
    resume.archived_at = None
    await db.commit()
    await db.refresh(resume)
    return _resume_response_from_obj(resume)


# ── Variant / Fork system ─────────────────────────────────────────────────


class ForkResumeRequest(BaseModel):
    title: Optional[str] = None


class VariantVisibilityUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    visibility: VariantVisibility


class VariantVisibilityResponse(BaseModel):
    resume: ResumeResponse
    source_resume_id: str
    source_title: str
    source_content: Dict[str, Any]
    effective_content: Dict[str, Any]
    visibility: VariantVisibility
    metrics: BuilderMetricsResponse
    preview: BuilderPreviewResponse
    template_family: str


class DiffWithParentResponse(BaseModel):
    parent_latex: str
    parent_title: str
    variant_latex: str
    variant_title: str


async def _linked_variant_context(
    resume_id: str, user_id: str, db: AsyncSession
) -> tuple[Resume, Resume, ResumeTemplate]:
    variant = await _verify_resume_ownership(db, resume_id, user_id)
    if variant.content_source != "builder_variant" or not variant.parent_resume_id:
        raise HTTPException(status_code=409, detail="This is not a source-linked builder variant")
    parent_result = await db.execute(
        select(Resume).where(
            Resume.id == variant.parent_resume_id,
            Resume.user_id == user_id,
        )
    )
    parent = parent_result.scalar_one_or_none()
    if not parent or not parent.structured_content:
        raise HTTPException(status_code=409, detail="The variant source is no longer available")
    template_id = variant.selected_template_id or parent.selected_template_id
    template = await db.get(ResumeTemplate, template_id) if template_id else None
    if not template or not resume_builder_service.is_supported_category(template.category, template.document_type):
        raise HTTPException(status_code=409, detail="The variant template is no longer available")
    return variant, parent, template


def _variant_visibility_response(
    variant: Resume,
    parent: Resume,
    template: ResumeTemplate,
    visibility: VariantVisibility,
) -> VariantVisibilityResponse:
    source = StructuredResume.model_validate(parent.structured_content).model_dump()
    effective = apply_variant_visibility(source, visibility)
    render = resume_builder_service.render(effective, template.category)
    preview = resume_builder_service.build_preview(effective, template.category)
    return VariantVisibilityResponse(
        resume=_resume_response_from_obj(variant),
        source_resume_id=parent.id,
        source_title=parent.title,
        source_content=source,
        effective_content=effective,
        visibility=visibility,
        metrics=BuilderMetricsResponse.model_validate(render.metrics.model_dump()),
        preview=BuilderPreviewResponse.model_validate(preview),
        template_family=render.template_family,
    )


@router.get("/{resume_id}/variant-visibility", response_model=VariantVisibilityResponse)
async def get_variant_visibility(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    variant, parent, template = await _linked_variant_context(resume_id, user_id, db)
    visibility = prune_variant_visibility(parent.structured_content, variant.variant_visibility)
    return _variant_visibility_response(variant, parent, template, visibility)


@router.patch("/{resume_id}/variant-visibility", response_model=VariantVisibilityResponse)
async def update_variant_visibility(
    resume_id: str,
    body: VariantVisibilityUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    variant, parent, template = await _linked_variant_context(resume_id, user_id, db)
    try:
        visibility = validate_variant_visibility(parent.structured_content, body.visibility.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=validation_error_detail(
                [
                    {
                        "path": "variant_visibility",
                        "message": "Variant visibility is invalid.",
                        "line": None,
                        "column": None,
                    }
                ]
            ),
        ) from exc
    if body.title is not None:
        variant.title = body.title.strip()
    effective = apply_variant_visibility(parent.structured_content, visibility)
    render = resume_builder_service.render(effective, template.category)
    variant.variant_visibility = visibility.model_dump()
    variant.latex_content = render.latex_content
    variant.structured_version = parent.structured_version
    variant.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(variant)
    return _variant_visibility_response(variant, parent, template, visibility)


@router.post("/{resume_id}/fork", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def fork_resume(
    resume_id: str,
    body: ForkResumeRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Create a variant (fork) of an existing resume."""
    parent = await _verify_resume_ownership(db, resume_id, user_id)

    variant_title = body.title or f"{parent.title} — Variant"
    is_linked_builder_variant = bool(
        parent.structured_content
        and parent.selected_template_id
        and parent.builder_status == "active"
        and parent.content_source == "builder"
    )
    variant = Resume(
        id=str(uuid4()),
        user_id=user_id,
        title=variant_title,
        latex_content=parent.latex_content,
        is_template=False,
        tags=list(parent.tags) if parent.tags else None,
        parent_resume_id=parent.id,
        resume_settings=dict(parent.resume_settings or {}),
        selected_template_id=(parent.selected_template_id if is_linked_builder_variant else None),
        structured_content=None,
        structured_version=parent.structured_version,
        content_source=("builder_variant" if is_linked_builder_variant else "manual_latex"),
        builder_status="active" if is_linked_builder_variant else "detached",
        variant_visibility=VariantVisibility().model_dump() if is_linked_builder_variant else None,
    )
    db.add(variant)

    # Record analytics event
    analytics = UsageAnalytics(
        id=str(uuid4()),
        user_id=user_id,
        action="resume_forked",
        resource_type="resume",
        event_metadata={"parent_resume_id": parent.id, "variant_resume_id": variant.id},
    )
    db.add(analytics)

    await db.commit()
    await db.refresh(variant)

    # Fire-and-forget embedding task
    if settings.OPENAI_API_KEY:
        try:
            from ..workers.ats_worker import submit_embed_resume

            submit_embed_resume(str(variant.id), variant.latex_content, user_id)
        except Exception as exc:
            logger.warning(
                "Failed to enqueue embedding for variant %s",
                variant.id,
                extra={"error_type": type(exc).__name__},
            )

    resp = _resume_response_from_obj(variant)
    resp.variant_count = 0
    return resp


# ── Quick Tailor ──────────────────────────────────────────────────────────────


class QuickTailorRequest(BaseModel):
    job_description: str = Field(..., min_length=10, max_length=10000)
    company_name: Optional[str] = Field(None, max_length=200)
    role_title: Optional[str] = Field(None, max_length=200)


class QuickTailorResponse(BaseModel):
    fork_id: str
    job_id: str


class AcademicCVReportResponse(BaseModel):
    is_academic_cv: bool
    detected_sections: List[str]
    estimated_pages: int
    confidence: float
    reasons: List[str]


class AcademicCVConvertRequest(BaseModel):
    target_industry: str = Field(default="tech", pattern="^(tech|data_science|finance|consulting|product|other)$")
    target_role_description: Optional[str] = Field(None, max_length=10000)
    title: Optional[str] = Field(None, max_length=255)
    force: bool = False


class AcademicCVConvertResponse(BaseModel):
    success: bool
    variant_resume_id: str
    job_id: str
    report: AcademicCVReportResponse


@router.post(
    "/{resume_id}/quick-tailor",
    response_model=QuickTailorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def quick_tailor_resume(
    resume_id: str,
    body: QuickTailorRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Fork the resume and kick off an aggressive optimization tailored to the job description."""
    from .job_routes import _resolve_user_plan

    parent = await _verify_resume_ownership(db, resume_id, user_id)

    # Allocate the worker identity before charging so the receipt can recover
    # a crash between quota consumption and fork/dispatch.
    job_id = str(uuid4())
    plan = await _resolve_user_plan(db, user_id)

    label = body.role_title or body.company_name or "Tailored"
    fork_title = f"{parent.title} — {label}"

    fork = Resume(
        id=str(uuid4()),
        user_id=user_id,
        title=fork_title,
        latex_content=parent.latex_content,
        is_template=False,
        tags=list(parent.tags) if parent.tags else None,
        parent_resume_id=parent.id,
        resume_settings=dict(parent.resume_settings or {}),
    )
    from .job_routes import _new_finalization_row

    finalization_record = _new_finalization_row(
        job_id,
        "combined",
        user_id,
        {"resume_id": str(fork.id)},
    )
    try:
        db.add(fork)
        # The finalization row carries a FK to the newly-created fork.  Flush
        # the parent first so SQLAlchemy cannot order the independent objects
        # with the arbiter insert ahead of the resume row.
        await db.flush()
        db.add(finalization_record)
        await db.commit()
        await db.refresh(fork)
    except Exception:
        await db.rollback()
        raise

    try:
        quota_ticket = await entitlement_service.enforce_quota(
            "optimizations", user_id=user_id, plan=plan, job_id=job_id
        )
    except Exception:
        try:
            await db.delete(finalization_record)
            await db.delete(fork)
            await db.commit()
        except Exception:
            await db.rollback()
        raise

    # Submit combined optimize+compile job for the fork
    from ..workers.orchestrator import submit_optimize_and_compile
    from .job_routes import _mark_dispatch_accepted, _mark_dispatch_started, _write_initial_redis_state

    dispatch_attempted = False
    try:
        await _write_initial_redis_state(job_id, "combined", user_id, 120)
        await _mark_dispatch_started(job_id)
        dispatch_attempted = True
        fork_settings = dict(fork.resume_settings or {})
        compile_settings = {
            key: fork_settings[key]
            for key in (
                "main_file",
                "extra_packages",
                "latexmk_flags",
                "texlive_version",
                "bibtex",
                "halt_on_error",
                "draft_mode",
            )
            if key in fork_settings and fork_settings[key] is not None
        } or None
        stored_compiler = fork_settings.get("compiler")
        compiler = (
            stored_compiler
            if stored_compiler in settings.ALLOWED_LATEX_COMPILERS
            else settings.DEFAULT_LATEX_COMPILER
        )
        submit_optimize_and_compile(
            latex_content=fork.latex_content,
            job_description=body.job_description,
            job_id=job_id,
            user_id=user_id,
            optimization_level="aggressive",
            custom_instructions=(
                "Tailor this resume for the specific role. "
                "Maximize keyword alignment with the job description. "
                "Keep all factual information accurate."
            ),
            resume_id=str(fork.id),
            compiler=compiler,
            compile_settings=compile_settings,
            metadata={
                "persist_optimized_resume": True,
                "resume_id": str(fork.id),
                "expected_latex_content": fork.latex_content,
            },
            quota_refund=quota_ticket.refund_payload(),
        )
        await _mark_dispatch_accepted(job_id)
    except Exception:
        if dispatch_attempted:
            return QuickTailorResponse(fork_id=str(fork.id), job_id=job_id)
        await entitlement_service.refund_quota(quota_ticket)
        await db.delete(finalization_record)
        await db.delete(fork)
        await db.commit()
        raise

    return QuickTailorResponse(fork_id=str(fork.id), job_id=job_id)


@router.get("/{resume_id}/academic-cv-report", response_model=AcademicCVReportResponse)
async def get_academic_cv_report(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Inspect a resume and report whether it looks like an academic CV."""
    resume = await _verify_resume_ownership(db, resume_id, user_id)
    report = academic_cv_service.detect(
        resume.latex_content or "",
        document_type=resume.document_type,
    )
    return AcademicCVReportResponse(**report.to_dict())


@router.post(
    "/{resume_id}/academic-cv-convert",
    response_model=AcademicCVConvertResponse,
    status_code=status.HTTP_201_CREATED,
)
async def convert_academic_cv(
    resume_id: str,
    body: AcademicCVConvertRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """
    Create an industry-resume variant from an academic CV and queue a combined
    optimize+compile job for the new fork.
    """
    parent = await _verify_resume_ownership(db, resume_id, user_id)
    report = academic_cv_service.detect(
        parent.latex_content or "",
        document_type=parent.document_type,
    )
    if not report.is_academic_cv and not body.force:
        raise HTTPException(
            status_code=400,
            detail="Resume does not strongly resemble an academic CV. Pass force=true to continue anyway.",
        )

    user_plan = "free"
    user_result = await db.execute(select(User.subscription_plan).where(User.id == user_id))
    stored_plan = user_result.scalar_one_or_none()
    if isinstance(stored_plan, str) and stored_plan:
        user_plan = stored_plan

    job_id = str(uuid4())

    label = {
        "tech": "Industry Resume",
        "data_science": "Data Science Resume",
        "finance": "Finance Resume",
        "consulting": "Consulting Resume",
        "product": "Product Resume",
        "other": "Industry Resume",
    }.get(body.target_industry, "Industry Resume")
    variant_title = body.title or f"{parent.title} — {label}"

    variant = Resume(
        id=str(uuid4()),
        user_id=user_id,
        title=variant_title,
        latex_content=parent.latex_content,
        is_template=False,
        tags=list(parent.tags) if parent.tags else None,
        parent_resume_id=parent.id,
        resume_settings=dict(parent.resume_settings or {}),
        document_type="resume",
    )
    analytics = UsageAnalytics(
        id=str(uuid4()),
        user_id=user_id,
        action="academic_cv_converted",
        resource_type="resume",
        event_metadata={
            "parent_resume_id": parent.id,
            "variant_resume_id": variant.id,
            "target_industry": body.target_industry,
            "confidence": report.confidence,
        },
    )
    from .job_routes import _new_finalization_row

    finalization_record = _new_finalization_row(
        job_id,
        "combined",
        user_id,
        {"resume_id": str(variant.id)},
    )
    try:
        db.add(variant)
        db.add(analytics)
        # ``resume_id`` is a real FK; make the variant visible before adding
        # the independently-constructed finalization row.
        await db.flush()
        db.add(finalization_record)
        await db.commit()
        await db.refresh(variant)
    except Exception:
        await db.rollback()
        raise

    # Queue a real LLM run with a job-scoped receipt so DB/dispatch crashes
    # remain recoverable.
    try:
        quota_ticket = await entitlement_service.enforce_quota(
            "optimizations", user_id=user_id, plan=user_plan, job_id=job_id
        )
    except Exception:
        try:
            await db.delete(finalization_record)
            await db.delete(analytics)
            await db.delete(variant)
            await db.commit()
        except Exception:
            await db.rollback()
        raise

    from ..workers.orchestrator import submit_optimize_and_compile
    from .job_routes import _mark_dispatch_accepted, _mark_dispatch_started, _write_initial_redis_state

    dispatch_attempted = False
    instructions = academic_cv_service.build_conversion_instructions(
        report,
        target_industry=body.target_industry,
        target_role_description=body.target_role_description,
    )

    try:
        await _write_initial_redis_state(job_id, "combined", user_id, 120)
        await _mark_dispatch_started(job_id)
        dispatch_attempted = True
        variant_settings = dict(variant.resume_settings or {})
        compile_settings = {
            key: variant_settings[key]
            for key in (
                "main_file",
                "extra_packages",
                "latexmk_flags",
                "texlive_version",
                "bibtex",
                "halt_on_error",
                "draft_mode",
            )
            if key in variant_settings and variant_settings[key] is not None
        } or None
        stored_compiler = variant_settings.get("compiler")
        compiler = (
            stored_compiler
            if stored_compiler in settings.ALLOWED_LATEX_COMPILERS
            else settings.DEFAULT_LATEX_COMPILER
        )
        submit_optimize_and_compile(
            latex_content=variant.latex_content,
            job_description=body.target_role_description,
            job_id=job_id,
            user_id=user_id,
            user_plan=user_plan,
            optimization_level="aggressive",
            custom_instructions=instructions,
            resume_id=str(variant.id),
            compiler=compiler,
            compile_settings=compile_settings,
            metadata={
                "persist_optimized_resume": True,
                "resume_id": str(variant.id),
                "expected_latex_content": variant.latex_content,
            },
            quota_refund=quota_ticket.refund_payload(),
        )
        await _mark_dispatch_accepted(job_id)
    except Exception:
        if dispatch_attempted:
            return AcademicCVConvertResponse(
                success=True,
                variant_resume_id=str(variant.id),
                job_id=job_id,
                report=AcademicCVReportResponse(**report.to_dict()),
            )
        await entitlement_service.refund_quota(quota_ticket)
        await db.delete(finalization_record)
        await db.delete(variant)
        await db.commit()
        raise

    return AcademicCVConvertResponse(
        success=True,
        variant_resume_id=str(variant.id),
        job_id=job_id,
        report=AcademicCVReportResponse(**report.to_dict()),
    )


@router.get("/{resume_id}/variants", response_model=List[ResumeResponse])
async def list_variants(
    resume_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_required)
):
    """List all direct child variants of a resume."""
    await _verify_resume_ownership(db, resume_id, user_id)

    variant_count_sq = _variant_count_subquery()
    result = await db.execute(
        select(Resume, variant_count_sq)
        .where(Resume.parent_resume_id == resume_id, Resume.user_id == user_id)
        .order_by(Resume.created_at.desc())
    )
    rows = result.all()

    out = []
    for resume, vc in rows:
        d = _resume_response_from_obj(resume)
        d.variant_count = vc or 0
        out.append(d)
    return out


@router.get("/{resume_id}/diff-with-parent", response_model=DiffWithParentResponse)
async def diff_with_parent(
    resume_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_required)
):
    """Get diff data between a variant and its parent resume."""
    variant = await _verify_resume_ownership(db, resume_id, user_id)

    if not variant.parent_resume_id:
        raise HTTPException(status_code=400, detail="This resume has no parent")

    # Fetch parent (must be owned by same user)
    result = await db.execute(select(Resume).where(Resume.id == variant.parent_resume_id, Resume.user_id == user_id))
    parent = result.scalar_one_or_none()
    if not parent:
        raise HTTPException(status_code=400, detail="Parent resume not found")

    return DiffWithParentResponse(
        parent_latex=parent.latex_content,
        parent_title=parent.title,
        variant_latex=variant.latex_content,
        variant_title=variant.title,
    )


# ── Optimization history ──────────────────────────────────────────────────


class RecordOptimizationRequest(BaseModel):
    original_latex: str
    optimized_latex: str
    changes_made: Optional[List[Dict[str, Any]]] = None
    ats_score: Optional[float] = None
    tokens_used: Optional[int] = None
    job_description: Optional[str] = None


class OptimizationHistoryEntry(BaseModel):
    id: str
    created_at: datetime
    ats_score: Optional[float]
    changes_count: int
    tokens_used: Optional[int]


class ScoreHistoryPoint(BaseModel):
    timestamp: datetime
    ats_score: float
    label: Optional[str] = None


class RestoreOptimizationResponse(BaseModel):
    success: bool
    latex_content: str


@router.post("/{resume_id}/record-optimization", status_code=status.HTTP_201_CREATED)
async def record_optimization(
    resume_id: str,
    body: RecordOptimizationRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Save an optimization record after a successful AI job."""
    result = await db.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Resume not found")

    opt = Optimization(
        id=str(uuid4()),
        user_id=user_id,
        resume_id=resume_id,
        original_latex=body.original_latex,
        optimized_latex=body.optimized_latex,
        job_description=body.job_description or "",
        provider="openai",
        model="gpt-4o",
        tokens_used=body.tokens_used,
        ats_score=body.ats_score,
        changes_made=body.changes_made or [],
    )
    db.add(opt)
    await db.commit()
    return {"success": True, "id": opt.id}


@router.get("/{resume_id}/optimization-history", response_model=List[OptimizationHistoryEntry])
async def get_optimization_history(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Return the 20 most recent optimization records for a resume."""
    try:
        result = await db.execute(
            select(Optimization)
            .where(Optimization.resume_id == resume_id, Optimization.user_id == user_id)
            .order_by(Optimization.created_at.desc())
            .limit(20)
        )
        rows = result.scalars().all()
    except Exception as exc:
        logger.warning(
            "DB error fetching optimization history for resume %s",
            resume_id,
            extra={"error_type": type(exc).__name__},
        )
        return []
    try:
        return [
            {
                "id": r.id,
                "created_at": r.created_at,
                "ats_score": float(r.ats_score) if r.ats_score is not None else None,
                "changes_count": len(r.changes_made) if isinstance(r.changes_made, list) else 0,
                "tokens_used": r.tokens_used,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning(
            "Error serializing optimization history for resume %s",
            resume_id,
            extra={"error_type": type(exc).__name__},
        )
        return []


@router.get("/{resume_id}/score-history", response_model=List[ScoreHistoryPoint])
async def get_score_history(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Return ATS score history for a resume, sorted oldest-first. Only entries with a score."""
    try:
        result = await db.execute(
            select(Optimization)
            .where(
                Optimization.resume_id == resume_id,
                Optimization.user_id == user_id,
                Optimization.ats_score.is_not(None),
            )
            .order_by(Optimization.created_at.asc())
        )
        rows = result.scalars().all()
    except Exception as exc:
        logger.warning(
            "DB error fetching score history for resume %s",
            resume_id,
            extra={"error_type": type(exc).__name__},
        )
        return []
    return [
        {
            "timestamp": r.created_at,
            "ats_score": float(r.ats_score),
            "label": r.checkpoint_label,
        }
        for r in rows
    ]


@router.post(
    "/{resume_id}/restore-optimization/{opt_id}",
    response_model=RestoreOptimizationResponse,
)
async def restore_optimization(
    resume_id: str,
    opt_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Restore a resume to a previously optimized version."""
    # Verify ownership of resume
    res_result = await db.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
    resume = res_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Fetch the optimization record
    opt_result = await db.execute(
        select(Optimization).where(
            Optimization.id == opt_id,
            Optimization.resume_id == resume_id,
            Optimization.user_id == user_id,
        )
    )
    opt = opt_result.scalar_one_or_none()
    if not opt:
        raise HTTPException(status_code=404, detail="Optimization record not found")

    resume.latex_content = opt.optimized_latex
    resume.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"success": True, "latex_content": opt.optimized_latex}


# ── Checkpoints (version history) ────────────────────────────────────────


class CreateCheckpointRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)


class CheckpointEntry(BaseModel):
    id: str
    created_at: datetime
    checkpoint_label: Optional[str] = None
    is_checkpoint: bool
    is_auto_save: bool
    optimization_level: Optional[str] = None
    ats_score: Optional[float] = None
    changes_count: int
    has_content: bool = True


class CheckpointContentResponse(BaseModel):
    original_latex: str
    optimized_latex: str
    checkpoint_label: Optional[str] = None


async def _verify_resume_ownership(db: AsyncSession, resume_id: str, user_id: str) -> Resume:
    # Most of the /resumes/{resume_id}/* sub-routes reach the database through
    # here, so the UUID guard belongs at this chokepoint: a malformed id would
    # otherwise raise ValueError out of asyncpg and surface as a 500.
    ensure_uuid(resume_id, "Resume not found")
    result = await db.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume


@router.post("/{resume_id}/checkpoints", status_code=status.HTTP_201_CREATED)
async def create_checkpoint(
    resume_id: str,
    body: CreateCheckpointRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Create a manual checkpoint (named snapshot) of the current resume content."""
    resume = await _verify_resume_ownership(db, resume_id, user_id)

    # Enforce max 20 manual checkpoints per resume
    count_result = await db.execute(
        select(func.count(Optimization.id)).where(
            Optimization.resume_id == resume_id,
            Optimization.user_id == user_id,
            Optimization.is_checkpoint.is_(True),
            Optimization.is_auto_save.is_(False),
        )
    )
    if (count_result.scalar() or 0) >= 20:
        raise HTTPException(
            status_code=400,
            detail="Maximum 20 manual checkpoints per resume. Delete older ones first.",
        )

    cp = Optimization(
        id=str(uuid4()),
        user_id=user_id,
        resume_id=resume_id,
        original_latex=resume.latex_content,
        optimized_latex=resume.latex_content,
        job_description="",
        provider="checkpoint",
        model="manual",
        is_checkpoint=True,
        is_auto_save=False,
        checkpoint_label=body.label,
    )
    db.add(cp)
    await db.commit()
    await db.refresh(cp)

    return {"id": cp.id, "created_at": cp.created_at, "label": cp.checkpoint_label}


@router.get("/{resume_id}/checkpoints", response_model=List[CheckpointEntry])
async def list_checkpoints(
    resume_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """List all checkpoints + auto-saves + optimizations for a resume (newest first)."""
    await _verify_resume_ownership(db, resume_id, user_id)

    result = await db.execute(
        select(Optimization)
        .where(Optimization.resume_id == resume_id, Optimization.user_id == user_id)
        .order_by(Optimization.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.scalars().all()

    return [
        CheckpointEntry(
            id=r.id,
            created_at=r.created_at,
            checkpoint_label=r.checkpoint_label,
            is_checkpoint=r.is_checkpoint,
            is_auto_save=r.is_auto_save,
            optimization_level=(r.model if not r.is_checkpoint else None),
            ats_score=float(r.ats_score) if r.ats_score is not None else None,
            changes_count=len(r.changes_made) if isinstance(r.changes_made, list) else 0,
            has_content=True,
        )
        for r in rows
    ]


@router.get("/{resume_id}/checkpoints/{checkpoint_id}/content", response_model=CheckpointContentResponse)
async def get_checkpoint_content(
    resume_id: str,
    checkpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Fetch the full LaTeX content of a specific checkpoint/optimization."""
    await _verify_resume_ownership(db, resume_id, user_id)

    result = await db.execute(
        select(Optimization).where(
            Optimization.id == checkpoint_id,
            Optimization.resume_id == resume_id,
            Optimization.user_id == user_id,
        )
    )
    cp = result.scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    return CheckpointContentResponse(
        original_latex=cp.original_latex,
        optimized_latex=cp.optimized_latex,
        checkpoint_label=cp.checkpoint_label,
    )


@router.delete("/{resume_id}/checkpoints/{checkpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_checkpoint(
    resume_id: str,
    checkpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Delete a manual checkpoint. Only is_checkpoint=True entries can be deleted."""
    await _verify_resume_ownership(db, resume_id, user_id)

    result = await db.execute(
        select(Optimization).where(
            Optimization.id == checkpoint_id,
            Optimization.resume_id == resume_id,
            Optimization.user_id == user_id,
        )
    )
    cp = result.scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    if not cp.is_checkpoint or cp.is_auto_save:
        raise HTTPException(
            status_code=400,
            detail="Only manual checkpoint entries can be deleted. Auto-saves and optimization records are preserved for history.",
        )

    await db.delete(cp)
    await db.commit()
    return None


# ── Share links ───────────────────────────────────────────────────────────


class ShareLinkRequest(BaseModel):
    anonymous: bool = False
    regenerate_anonymous: bool = False
    # Public reviewers can comment only when the owner explicitly grants this
    # separate capability on the share token.
    review_comments: Optional[bool] = None


class ShareLinkResponse(BaseModel):
    share_token: str
    share_url: str
    created_at: datetime
    anonymous: bool = False
    review_comments: bool = False


@router.post("/{resume_id}/share", response_model=ShareLinkResponse)
async def create_share_link(
    resume_id: str,
    body: ShareLinkRequest = None,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Generate (or return existing) share token for a resume."""
    anonymous = body.anonymous if body else False
    regenerate_anonymous = bool(body and body.regenerate_anonymous and anonymous)
    resume = await _verify_resume_ownership(db, resume_id, user_id)
    # Serialize capability updates with public review writes. The review
    # endpoint rechecks the token after its rate-limit await under this same
    # lock, so a revoke/rotate that wins cannot be followed by an old-token
    # comment insertion.
    resume = await db.scalar(
        select(Resume)
        .where(Resume.id == resume_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Update anonymous flag in metadata regardless of whether token exists
    current_meta: dict = dict(resume.resume_settings or {})
    current_anonymous = current_meta.get("share_anonymous", False)
    current_review_comments = bool(current_meta.get("share_review_comments", False))
    if anonymous != current_anonymous:
        current_meta["share_anonymous"] = anonymous
        resume.resume_settings = current_meta
    # Omitted review_comments means "leave the existing capability unchanged".
    # This is important for older clients that update anonymous privacy and do
    # not know about the separate public-review capability.
    review_comments = current_review_comments if not body or body.review_comments is None else body.review_comments
    if body and body.review_comments is not None and review_comments != current_review_comments:
        current_meta["share_review_comments"] = review_comments
        resume.resume_settings = current_meta

    if regenerate_anonymous:
        current_meta.pop("share_anonymous_job_id", None)
        current_meta.pop("share_anonymous_pending", None)
        resume.resume_settings = dict(current_meta)
        flag_modified(resume, "resume_settings")

    if not resume.share_token:
        from ..database.models import Compilation

        # Try to upload the latest PDF to MinIO for persistent serving
        comp_result = await db.execute(
            select(Compilation)
            .where(
                Compilation.resume_id == resume_id,
                Compilation.status == "completed",
            )
            .order_by(Compilation.created_at.desc())
            .limit(1)
        )
        compilation = comp_result.scalar_one_or_none()

        if compilation and not compilation.pdf_path:
            # Rare path: the worker now uploads to an owner-tokenized
            # compilations/{job_id}/finalization-<hash>.pdf key
            # and fills pdf_path, so this only fires for rows reconciled by the
            # older API-side fallback, or when the MinIO upload failed at compile
            # time. Try local filesystem first, then Redis (Modal / serverless).
            try:
                _, temp_pdf, _ = get_job_files(str(compilation.job_id))
            except HTTPException:
                temp_pdf = None
            pdf_bytes_for_share: bytes | None = None
            if temp_pdf is not None and temp_pdf.exists():
                try:
                    pdf_bytes_for_share = read_file_bounded(temp_pdf, _MAX_COMPILED_PDF_BYTES)
                except ValueError as exc:
                    logger.warning(
                        "Local PDF exceeds share limit for %s",
                        resume_id,
                        extra={"error_type": type(exc).__name__},
                    )
            else:
                try:
                    from ..core.redis import get_redis_client as _get_rc

                    _r = await _get_rc()
                    _b64_val = await _r.get(f"latexy:job:{compilation.job_id}:pdf")
                    if _b64_val:
                        pdf_bytes_for_share = decode_base64_bounded(
                            _b64_val, MAX_COMPILED_PDF_BYTES
                        )
                except Exception as _re:
                    logger.warning(
                        "Redis PDF lookup failed for share %s",
                        resume_id,
                        extra={"error_type": type(_re).__name__},
                    )
            if pdf_bytes_for_share:
                try:
                    from ..services.storage_service import compilation_pdf_key, delete_object, upload_bytes

                    # A repair is an owner-scoped storage write.  Do not use
                    # one deterministic resume-wide key: concurrent legacy
                    # repairs must not overwrite each other's bytes before the
                    # conditional DB update elects a winner.
                    repair_owner = f"share-fallback:{uuid4()}"
                    share_key = compilation_pdf_key(str(compilation.job_id), repair_owner)
                    upload_bytes(share_key, pdf_bytes_for_share, "application/pdf")
                    repaired = await db.execute(
                        update(Compilation)
                        .where(
                            Compilation.id == compilation.id,
                            Compilation.pdf_path.is_(None),
                        )
                        .values(pdf_path=share_key)
                    )
                    if repaired.rowcount:
                        compilation.pdf_path = share_key
                    else:
                        # A concurrent worker may have persisted the durable
                        # path while this upload was in flight.  Keep its
                        # winner; never overwrite it with this fallback key.
                        await db.refresh(compilation)
                        if compilation.pdf_path and compilation.pdf_path != share_key:
                            try:
                                delete_object(share_key)
                            except Exception as cleanup_exc:
                                logger.warning(
                                    "Could not remove losing share repair object (%s)",
                                    type(cleanup_exc).__name__,
                                )
                    logger.info(f"Uploaded PDF to MinIO for resume {resume_id} at {share_key}")
                except Exception as exc:
                    logger.warning(
                        "Could not upload PDF to MinIO for share link",
                        extra={"error_type": type(exc).__name__},
                    )

        resume.share_token = secrets.token_urlsafe(24)
        resume.share_token_created_at = datetime.now(timezone.utc)

    # If anonymous mode is newly enabled, submit a compile job for redacted LaTeX
    if anonymous and not current_meta.get("share_anonymous_job_id"):
        try:
            from ..services.latex_pii_redactor import redact
            from ..workers.latex_worker import submit_latex_compilation

            anon_job_id = str(uuid4())
            redacted_latex = redact(resume.latex_content)
            submit_latex_compilation(
                latex_content=redacted_latex,
                job_id=anon_job_id,
                user_id=user_id,
                resume_id=resume_id,
                metadata={
                    "anonymous_share": True,
                    "resume_id": resume_id,
                    "skip_auto_save": True,
                },
            )
            current_meta["share_anonymous_job_id"] = anon_job_id
            # Reassign a fresh dict AND flag_modified so SQLAlchemy persists the
            # change even after an earlier autoflush (triggered by the Compilation
            # lookup above) committed `current_meta` — a plain JSONB column does not
            # track in-place mutations.
            resume.resume_settings = dict(current_meta)
            flag_modified(resume, "resume_settings")
            logger.info(f"Submitted anonymous compile job {anon_job_id} for resume {resume_id}")
        except Exception as exc:
            logger.error(
                "Could not submit anonymous compile job for resume %s",
                resume_id,
                extra={"error_type": type(exc).__name__},
            )
            current_meta["share_anonymous_pending"] = True
            resume.resume_settings = dict(current_meta)
            flag_modified(resume, "resume_settings")

    await db.commit()
    await db.refresh(resume)

    return ShareLinkResponse(
        share_token=resume.share_token,
        share_url=f"{settings.FRONTEND_URL}/r/{resume.share_token}",
        created_at=resume.share_token_created_at,
        anonymous=anonymous,
        review_comments=review_comments,
    )


@router.delete("/{resume_id}/share", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share_link(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Revoke a share token — the public link immediately stops working."""
    resume = await _verify_resume_ownership(db, resume_id, user_id)
    resume = await db.scalar(
        select(Resume)
        .where(Resume.id == resume_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    resume.share_token = None
    resume.share_token_created_at = None
    # Review access belongs to the revoked capability, not to the resume
    # forever. A subsequently-created share link must start closed unless the
    # owner explicitly enables review comments again.
    current_meta = dict(resume.resume_settings or {})
    if current_meta.pop("share_review_comments", None) is not None:
        resume.resume_settings = current_meta
        flag_modified(resume, "resume_settings")
    await db.commit()
    return None


# ── Resume View Analytics (Feature 43) ───────────────────────────────────────


class DayCount(BaseModel):
    date: str  # "YYYY-MM-DD"
    count: int


class CountryCount(BaseModel):
    country_code: Optional[str]
    count: int


class ReferrerCount(BaseModel):
    referrer: Optional[str]
    count: int


class ResumeAnalytics(BaseModel):
    total_views: int
    views_last_7_days: int
    views_last_30_days: int
    views_by_day: List[DayCount]  # last 30 days, one entry per day
    views_by_country: List[CountryCount]
    views_by_referrer: List[ReferrerCount]
    first_viewed_at: Optional[str]
    last_viewed_at: Optional[str]


@router.get("/{resume_id}/analytics", response_model=ResumeAnalytics)
async def get_resume_analytics(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Return view analytics for a resume. Owner-only."""
    from datetime import timedelta

    from sqlalchemy import func as sqlfunc
    from sqlalchemy import text as sqtext

    from ..database.models import ResumeView

    # Verify ownership
    await _verify_resume_ownership(db, resume_id, user_id)

    now = datetime.now(timezone.utc)
    day_30_ago = now - timedelta(days=30)
    day_7_ago = now - timedelta(days=7)

    # Total views
    total_q = await db.execute(select(sqlfunc.count()).select_from(ResumeView).where(ResumeView.resume_id == resume_id))
    total_views: int = total_q.scalar_one() or 0

    # Views last 7 days
    last7_q = await db.execute(
        select(sqlfunc.count())
        .select_from(ResumeView)
        .where(
            ResumeView.resume_id == resume_id,
            ResumeView.viewed_at >= day_7_ago,
        )
    )
    views_last_7_days: int = last7_q.scalar_one() or 0

    # Views last 30 days
    last30_q = await db.execute(
        select(sqlfunc.count())
        .select_from(ResumeView)
        .where(
            ResumeView.resume_id == resume_id,
            ResumeView.viewed_at >= day_30_ago,
        )
    )
    views_last_30_days: int = last30_q.scalar_one() or 0

    # Views by day (last 30 days) — fill every date in the window with 0 if no views
    day_rows = await db.execute(
        select(
            sqlfunc.date_trunc("day", ResumeView.viewed_at).label("day"),
            sqlfunc.count().label("cnt"),
        )
        .where(ResumeView.resume_id == resume_id, ResumeView.viewed_at >= day_30_ago)
        .group_by(sqtext("1"))
        .order_by(sqtext("1"))
    )
    # Build lookup: date string → count
    day_count_map = {row.day.strftime("%Y-%m-%d"): row.cnt for row in day_rows.all()}
    # Generate every date in the 30-day window (inclusive)
    views_by_day = [
        DayCount(
            date=(day_30_ago + timedelta(days=i)).strftime("%Y-%m-%d"),
            count=day_count_map.get((day_30_ago + timedelta(days=i)).strftime("%Y-%m-%d"), 0),
        )
        for i in range(31)
    ]

    # Views by country (top 10)
    country_rows = await db.execute(
        select(ResumeView.country_code, sqlfunc.count().label("cnt"))
        .where(ResumeView.resume_id == resume_id)
        .group_by(ResumeView.country_code)
        .order_by(sqtext("cnt DESC"))
        .limit(10)
    )
    views_by_country = [CountryCount(country_code=row.country_code, count=row.cnt) for row in country_rows.all()]

    # Views by referrer (top 10, strip protocol + www)
    referrer_rows = await db.execute(
        select(ResumeView.referrer, sqlfunc.count().label("cnt"))
        .where(ResumeView.resume_id == resume_id)
        .group_by(ResumeView.referrer)
        .order_by(sqtext("cnt DESC"))
        .limit(10)
    )
    views_by_referrer = [ReferrerCount(referrer=row.referrer, count=row.cnt) for row in referrer_rows.all()]

    # First / last viewed
    bounds_q = await db.execute(
        select(sqlfunc.min(ResumeView.viewed_at), sqlfunc.max(ResumeView.viewed_at)).where(
            ResumeView.resume_id == resume_id
        )
    )
    bounds = bounds_q.one()
    first_viewed_at = bounds[0].isoformat() if bounds[0] else None
    last_viewed_at = bounds[1].isoformat() if bounds[1] else None

    return ResumeAnalytics(
        total_views=total_views,
        views_last_7_days=views_last_7_days,
        views_last_30_days=views_last_30_days,
        views_by_day=views_by_day,
        views_by_country=views_by_country,
        views_by_referrer=views_by_referrer,
        first_viewed_at=first_viewed_at,
        last_viewed_at=last_viewed_at,
    )


# ── Bulk / Batch Export (Feature 49) ─────────────────────────────────────────


def _sanitize_filename(title: str) -> str:
    """Convert a resume title to a safe filename (no path traversal)."""
    safe = re.sub(r"[^\w\s-]", "", title).strip()
    safe = re.sub(r"[\s-]+", "_", safe)
    return safe or "resume"


@router.get("/export/bulk")
async def bulk_export(
    format: str = Query("tex", pattern="^(tex|pdf|docx)$"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """
    Download all non-archived resumes as a ZIP archive.
    format=tex  → one .tex file per resume
    format=pdf  → one .pdf per resume (skips resumes with no compiled PDF)
    format=docx → one .docx per resume (rule-based LaTeX→DOCX conversion)
    """
    result = await db.execute(
        select(Resume).where(Resume.user_id == user_id, Resume.archived_at.is_(None)).order_by(Resume.updated_at.desc())
    )
    resumes = result.scalars().all()

    if not resumes:
        # Return empty ZIP rather than 404
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED):
            pass
        buf.seek(0)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="latexy-resumes-{today}.zip"'},
        )

    latest_compilation_by_resume: dict[str, Compilation] = {}
    if format == "pdf":
        # Fetch the latest successful compilation for every resume in one query.
        # The previous query lived inside the ZIP loop and made a bulk export do
        # N+1 database round trips.
        compilation_result = await db.execute(
            select(Compilation)
            .where(
                Compilation.resume_id.in_([resume.id for resume in resumes]),
                Compilation.status == "completed",
            )
            .distinct(Compilation.resume_id)
            .order_by(Compilation.resume_id, Compilation.created_at.desc())
        )
        latest_compilation_by_resume = {
            compilation.resume_id: compilation for compilation in compilation_result.scalars().all()
        }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen_names: dict[str, int] = {}

        for resume in resumes:
            base = _sanitize_filename(resume.title)
            # Deduplicate filenames
            if base in seen_names:
                seen_names[base] += 1
                filename_base = f"{base}_{seen_names[base]}"
            else:
                seen_names[base] = 0
                filename_base = base

            if format == "tex":
                zf.writestr(f"{filename_base}.tex", resume.latex_content or "")

            elif format == "pdf":
                compilation = latest_compilation_by_resume.get(resume.id)
                if not compilation:
                    continue  # skip — no compiled PDF

                pdf_bytes: Optional[bytes] = None
                if compilation.pdf_path:
                    try:
                        from ..services.storage_service import download_bytes

                        pdf_bytes = download_bytes(compilation.pdf_path, _MAX_COMPILED_PDF_BYTES)
                    except Exception as exc:
                        logger.warning(
                            "Could not fetch PDF from MinIO for %s",
                            resume.id,
                            extra={"error_type": type(exc).__name__},
                        )
                if pdf_bytes is None:
                    try:
                        _, temp_pdf, _ = get_job_files(str(compilation.job_id))
                    except HTTPException:
                        temp_pdf = None
                    if temp_pdf is not None and temp_pdf.exists():
                        try:
                            pdf_bytes = read_file_bounded(temp_pdf, _MAX_COMPILED_PDF_BYTES)
                        except ValueError as exc:
                            logger.warning(
                                "Local PDF exceeds bulk-export limit for %s",
                                resume.id,
                                extra={"error_type": type(exc).__name__},
                            )
                if pdf_bytes:
                    zf.writestr(f"{filename_base}.pdf", pdf_bytes)

            elif format == "docx":
                try:
                    from ..services.document_export_service import DocumentExportService

                    svc = DocumentExportService()
                    docx_bytes = svc.to_docx(resume.latex_content or "")
                    zf.writestr(f"{filename_base}.docx", docx_bytes)
                except Exception as exc:
                    logger.warning(
                        "DOCX export failed for %s",
                        resume.id,
                        extra={"error_type": type(exc).__name__},
                    )

    buf.seek(0)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="latexy-resumes-{today}.zip"'},
    )


# ── Feature 40 — Collaborator management ─────────────────────────────────────

_VALID_ROLES = {"editor", "commenter", "viewer"}


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CollaboratorInviteRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: str = Field(default="editor")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v.lower()

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in _VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(_VALID_ROLES)}")
        return v


class CollaboratorRoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in _VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(_VALID_ROLES)}")
        return v


class CollaboratorResponse(BaseModel):
    id: str
    resume_id: str
    user_id: str
    user_name: Optional[str]
    user_email: Optional[str]
    role: str
    invited_by: Optional[str]
    joined_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post(
    "/{resume_id}/collaborators",
    response_model=CollaboratorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_collaborator(
    resume_id: str,
    body: CollaboratorInviteRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Invite a user by email to collaborate on a resume (owner only)."""
    await _verify_resume_ownership(db, resume_id, user_id)

    from ..database.models import User

    # Look up invitee by email
    result = await db.execute(select(User).where(User.email == body.email.lower().strip()))
    invitee = result.scalar_one_or_none()
    if invitee is None:
        raise HTTPException(status_code=404, detail="User with that email not found")

    if invitee.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot invite yourself")

    # Check for existing row
    existing_result = await db.execute(
        select(ResumeCollaborator).where(
            ResumeCollaborator.resume_id == resume_id,
            ResumeCollaborator.user_id == invitee.id,
        )
    )
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="User is already a collaborator")

    collab = ResumeCollaborator(
        resume_id=resume_id,
        user_id=invitee.id,
        role=body.role,
        invited_by=user_id,
    )
    db.add(collab)
    await db.commit()
    await db.refresh(collab)

    return CollaboratorResponse(
        id=collab.id,
        resume_id=collab.resume_id,
        user_id=collab.user_id,
        user_name=invitee.name,
        user_email=invitee.email,
        role=collab.role,
        invited_by=collab.invited_by,
        joined_at=collab.joined_at,
        created_at=collab.created_at,
    )


@router.get("/{resume_id}/collaborators", response_model=List[CollaboratorResponse])
async def list_collaborators(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """List all collaborators for a resume (owner only)."""
    await _verify_resume_ownership(db, resume_id, user_id)

    from ..database.models import User

    result = await db.execute(
        select(ResumeCollaborator, User)
        .join(User, User.id == ResumeCollaborator.user_id)
        .where(ResumeCollaborator.resume_id == resume_id)
        .order_by(ResumeCollaborator.created_at)
    )
    rows = result.all()

    return [
        CollaboratorResponse(
            id=collab.id,
            resume_id=collab.resume_id,
            user_id=collab.user_id,
            user_name=user.name,
            user_email=user.email,
            role=collab.role,
            invited_by=collab.invited_by,
            joined_at=collab.joined_at,
            created_at=collab.created_at,
        )
        for collab, user in rows
    ]


@router.patch(
    "/{resume_id}/collaborators/{collab_user_id}",
    response_model=CollaboratorResponse,
)
async def update_collaborator_role(
    resume_id: str,
    collab_user_id: str,
    body: CollaboratorRoleUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Change a collaborator's role (owner only)."""
    await _verify_resume_ownership(db, resume_id, user_id)

    from ..database.models import User

    result = await db.execute(
        select(ResumeCollaborator).where(
            ResumeCollaborator.resume_id == resume_id,
            ResumeCollaborator.user_id == collab_user_id,
        )
    )
    collab = result.scalar_one_or_none()
    if collab is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    collab.role = body.role
    await db.commit()
    await db.refresh(collab)

    # The role travels with the live collaboration socket, so drop the existing
    # sessions: the client reconnects and is re-authorised with the new role.
    # Sent with the role-changed code, not the revoked one — otherwise the client
    # reads a promotion as a loss of access and locks the buffer read-only.
    await collab_manager.revoke_access(
        resume_id,
        collab_user_id,
        reason="Role changed",
        code=CLOSE_ROLE_CHANGED,
        notice_code="role_changed",
    )

    user_result = await db.execute(select(User).where(User.id == collab_user_id))
    user = user_result.scalar_one_or_none()

    return CollaboratorResponse(
        id=collab.id,
        resume_id=collab.resume_id,
        user_id=collab.user_id,
        user_name=user.name if user else None,
        user_email=user.email if user else None,
        role=collab.role,
        invited_by=collab.invited_by,
        joined_at=collab.joined_at,
        created_at=collab.created_at,
    )


@router.delete(
    "/{resume_id}/collaborators/{collab_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_collaborator(
    resume_id: str,
    collab_user_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Remove a collaborator from a resume (owner only)."""
    await _verify_resume_ownership(db, resume_id, user_id)

    result = await db.execute(
        select(ResumeCollaborator).where(
            ResumeCollaborator.resume_id == resume_id,
            ResumeCollaborator.user_id == collab_user_id,
        )
    )
    collab = result.scalar_one_or_none()
    if collab is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    await db.delete(collab)
    await db.commit()

    # Terminate any live collaboration sockets so revocation takes effect
    # immediately instead of at the collaborator's next reconnect.
    await collab_manager.revoke_access(resume_id, collab_user_id, reason="Access removed")
    return None


# ── Reference Page Generator (Feature 70) ───────────────────────────────────


def _extract_documentclass(latex: str) -> str:
    m = re.search(r"\\documentclass(?:\[[^\]]*\])?\{[^}]+\}", latex)
    return m.group(0) if m else r"\documentclass{article}"


# Packages already injected by references_page.tex.j2 — skip to avoid option clashes.
_TEMPLATE_PACKAGES: set[str] = {"geometry", "hyperref", "parskip"}


def _extract_extra_preamble(latex: str) -> str:
    """Extract style macros from preamble to style-match the reference page."""
    lines_list = latex.splitlines()
    preamble_lines: list[str] = []
    in_preamble = False
    for line in lines_list:
        stripped = line.strip()
        if re.match(r"\\documentclass", stripped):
            in_preamble = True
            continue
        if stripped == r"\begin{document}":
            break
        if in_preamble and (
            stripped.startswith(r"\usepackage")
            or stripped.startswith(r"\definecolor")
            or stripped.startswith(r"\colorlet")
            or stripped.startswith(r"\setmainfont")
            or stripped.startswith(r"\newcommand")
            or stripped.startswith(r"\renewcommand")
        ):
            if "draftwatermark" in stripped:
                continue
            # Skip packages the template already provides to avoid option clashes
            pkg_m = re.match(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}", stripped)
            if pkg_m:
                pkgs = {p.strip() for p in pkg_m.group(1).split(",")}
                if pkgs & _TEMPLATE_PACKAGES:
                    continue
            preamble_lines.append(line)
    return "\n".join(preamble_lines)


def _escape_latex(text: str) -> str:
    """Escape LaTeX special characters to prevent compilation errors/injection."""
    if not text:
        return text
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return re.sub(r"[\\&%$#_{}~^]", lambda match: replacements[match.group(0)], text)


def _render_references_page(
    documentclass: str,
    extra_preamble: str,
    references: list[dict[str, str]],
) -> str:
    """Render the small LaTeX document without an HTML-oriented template engine."""
    lines = [
        documentclass,
        "",
        r"\usepackage[margin=1in]{geometry}",
        r"\usepackage{hyperref}",
        r"\usepackage{parskip}",
    ]
    if extra_preamble:
        lines.append(extra_preamble)
    lines.extend(
        [
            "",
            r"\begin{document}",
            "",
            r"{\Large \textbf{References}}",
            r"\vspace{0.5em}",
            r"\hrule",
            r"\vspace{1em}",
            "",
        ]
    )
    for reference in references:
        lines.extend(
            [
                rf"\textbf{{{reference['name']}}}\\",
                rf"\textit{{{reference['title']}, {reference['company']}}}\\",
                rf"\textit{{{reference['relationship']}}}\\",
            ]
        )
        if reference["email"]:
            lines.append(rf"\href{{mailto:{reference['email']}}}{{{reference['email']}}}\\")
        if reference["phone"]:
            lines.append(rf"Phone: {reference['phone']}\\")
        lines.extend([r"\vspace{0.8em}", ""])
    lines.extend([r"\end{document}", ""])
    return "\n".join(lines)


class ReferenceContact(BaseModel):
    name: str = Field(..., max_length=100)
    title: str = Field(..., max_length=200)
    company: str = Field(..., max_length=200)
    email: Optional[str] = Field(None, max_length=254)
    phone: Optional[str] = Field(None, max_length=50)
    relationship: str = Field(..., max_length=100)


class GenerateReferencesRequest(BaseModel):
    references: List[ReferenceContact] = Field(..., min_length=1, max_length=5)


class GenerateReferencesResponse(BaseModel):
    latex_content: str


@router.post("/{resume_id}/generate-references", response_model=GenerateReferencesResponse)
async def generate_references(
    resume_id: str,
    request: GenerateReferencesRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> GenerateReferencesResponse:
    """
    Generate a matching-style LaTeX reference page from up to 5 contact entries.
    Extracts \\documentclass and preamble macros from the source resume.
    """
    result = await db.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    source_latex: str = resume.latex_content or ""
    documentclass = _extract_documentclass(source_latex)
    extra_preamble = _extract_extra_preamble(source_latex)

    try:
        # Escape all user-supplied fields before rendering to prevent LaTeX
        # compilation errors or injection via special characters (%, &, _, etc.).
        safe_refs = [
            {
                "name": _escape_latex(ref.name),
                "title": _escape_latex(ref.title),
                "company": _escape_latex(ref.company),
                "relationship": _escape_latex(ref.relationship),
                "email": _escape_latex(ref.email or ""),
                "phone": _escape_latex(ref.phone or "") if ref.phone else "",
            }
            for ref in request.references
        ]
        latex_content = _render_references_page(documentclass, extra_preamble, safe_refs)
    except Exception as exc:
        logger.error("Reference page render failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=500, detail="Failed to render reference page template")

    return GenerateReferencesResponse(latex_content=latex_content)


# ── Multi-Resume Merge (Feature 69) ──────────────────────────────────────────


class MergeRequest(BaseModel):
    resume_ids: List[str] = Field(..., min_length=2, max_length=4)
    section_choices: Dict[str, str] = Field(default_factory=dict, max_length=100)
    # { "Experience": "resume_id_1", "Skills": "resume_id_2" }

    @field_validator("resume_ids")
    @classmethod
    def validate_resume_ids(cls, values: List[str]) -> List[str]:
        for value in values:
            try:
                UUID(value)
            except (TypeError, ValueError, AttributeError):
                raise ValueError("Every resume_id must be a valid UUID")
        if len(set(values)) != len(values):
            raise ValueError("At least two distinct resume_ids are required")
        return values

    @model_validator(mode="after")
    def validate_section_sources(self) -> "MergeRequest":
        unknown_sources = set(self.section_choices.values()) - set(self.resume_ids)
        if unknown_sources:
            raise ValueError("Every section source must be included in resume_ids")
        return self


class MergeResponse(BaseModel):
    merged_latex: str
    new_resume_id: str


def _extract_latex_preamble(latex: str) -> str:
    """Return everything up to and including \\begin{document}."""
    marker = "\\begin{document}"
    idx = latex.find(marker)
    if idx == -1:
        return latex
    return latex[: idx + len(marker)]


_SECTION_RE = re.compile(r"\\section\*?\{([^}]+)\}")


def _extract_latex_sections(latex: str) -> dict:
    """
    Parse LaTeX into {section_name: full_block_including_header}.
    Returns an empty dict if no \\section commands are found.
    """
    body_m = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", latex, re.DOTALL)
    if not body_m:
        return {}
    body = body_m.group(1)

    positions = list(_SECTION_RE.finditer(body))
    if not positions:
        return {}

    result: dict = {}
    for i, m in enumerate(positions):
        name = m.group(1).strip()
        start = m.start()
        end = positions[i + 1].start() if i + 1 < len(positions) else len(body)
        result[name] = body[start:end].strip()
    return result


def _extract_latex_presection(latex: str) -> str:
    """Return the body content before the first \\section (name block, etc.)."""
    body_m = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", latex, re.DOTALL)
    if not body_m:
        return ""
    body = body_m.group(1)
    first = _SECTION_RE.search(body)
    return body[: first.start()].strip() if first else body.strip()


@router.post("/merge", response_model=MergeResponse, status_code=status.HTTP_201_CREATED)
async def merge_resumes(
    request: MergeRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> MergeResponse:
    """
    Merge 2–4 resumes into a new resume.

    - Preamble and pre-section block come from resume_ids[0].
    - section_choices maps section names to the source resume ID.
    - Sections absent from section_choices are taken from resume_ids[0].
    - Saves result as a new resume titled "Merged Resume".
    """
    # Deduplicate while preserving order
    seen: set = set()
    ordered_ids: list = []
    for rid in request.resume_ids:
        if rid not in seen:
            seen.add(rid)
            ordered_ids.append(rid)

    # Fetch all in one query
    result = await db.execute(select(Resume).where(Resume.id.in_(ordered_ids)))
    found: dict = {r.id: r for r in result.scalars().all()}

    # Verify ownership — 403 if any resume is not owned by this user
    for rid in ordered_ids:
        resume = found.get(rid)
        if resume is None or resume.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Resume {rid} not found or access denied",
            )

    primary = found[ordered_ids[0]]
    preamble = _extract_latex_preamble(primary.latex_content or "")
    presection = _extract_latex_presection(primary.latex_content or "")

    # Extract sections from every source resume
    all_sections: dict = {}  # resume_id → {name: block}
    for rid in ordered_ids:
        all_sections[rid] = _extract_latex_sections(found[rid].latex_content or "")

    # Determine canonical section order (from resume_ids[0], then any extra from others)
    primary_sections = all_sections[ordered_ids[0]]
    extra_names = []
    for rid in ordered_ids[1:]:
        for name in all_sections[rid]:
            if name not in primary_sections and name not in extra_names:
                extra_names.append(name)
    section_order = list(primary_sections.keys()) + extra_names

    # Build merged body
    body_parts: list = []
    if presection:
        body_parts.append(presection)

    for name in section_order:
        source_id = request.section_choices.get(name, ordered_ids[0])
        # Fallback to primary if specified source doesn't have this section
        block = all_sections.get(source_id, {}).get(name) or primary_sections.get(name)
        if block:
            body_parts.append(block)

    merged_latex = preamble + "\n\n" + "\n\n".join(body_parts) + "\n\n\\end{document}"

    # Save as new resume
    new_resume = Resume(
        id=str(uuid4()),
        user_id=user_id,
        title="Merged Resume",
        latex_content=merged_latex,
        parent_resume_id=ordered_ids[0],
        resume_settings=dict(primary.resume_settings or {}),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(new_resume)
    await db.commit()
    await db.refresh(new_resume)

    return MergeResponse(merged_latex=merged_latex, new_resume_id=new_resume.id)


# ── Portfolio generation (Feature 68) ─────────────────────────────────────────


class GeneratePortfolioResponse(BaseModel):
    portfolio_url: str


@router.post("/{resume_id}/generate-portfolio", response_model=GeneratePortfolioResponse)
async def generate_portfolio(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> GeneratePortfolioResponse:
    """Generate a static HTML portfolio page for a resume and store it in MinIO."""
    from ..database.models import User
    from ..services.portfolio_generator import portfolio_generator

    result = await db.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
    resume = result.scalar_one_or_none()
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    theme = user.portfolio_theme or "minimal"
    portfolio_url = await portfolio_generator.generate(resume, user, theme)
    return GeneratePortfolioResponse(portfolio_url=portfolio_url)
