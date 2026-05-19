"""
Resume Template API Routes.

Endpoints:
  GET  /templates/categories       — category list with counts
  GET  /templates/                 — list all active templates (optional ?category= ?search=)
  GET  /templates/{id}             — full template detail (includes latex_content)
  GET  /templates/{id}/thumbnail   — PNG thumbnail from MinIO
  GET  /templates/{id}/pdf         — compiled PDF from MinIO
  POST /templates/{id}/use         — authenticated; create a Resume from this template
  POST /templates                  — admin; create a template
  PUT  /templates/{id}             — admin; replace template fields
  PATCH /templates/{id}/activate   — admin; mark active
  PATCH /templates/{id}/deactivate — admin; mark inactive
  DELETE /templates/{id}           — admin; delete template
"""

import uuid as _uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import Resume, ResumeTemplate
from ..middleware.auth_middleware import get_current_user_required
from ..services import storage_service

logger = get_logger(__name__)

router = APIRouter(prefix="/templates", tags=["templates"])

# ------------------------------------------------------------------ #
#  Constants                                                          #
# ------------------------------------------------------------------ #

VALID_CATEGORIES = frozenset({
    "software_engineering", "finance", "academic", "creative",
    "minimal", "ats_safe", "two_column", "executive",
    "marketing", "medical", "legal", "graduate",
})

CATEGORY_LABELS: dict[str, str] = {
    "software_engineering": "Software Engineering",
    "finance":              "Finance",
    "academic":             "Academic / Research",
    "creative":             "Creative & Design",
    "minimal":              "Minimal / Clean",
    "ats_safe":             "ATS-Safe",
    "two_column":           "Two-Column",
    "executive":            "Executive",
    "marketing":            "Marketing & Sales",
    "medical":              "Medical / Healthcare",
    "legal":                "Legal",
    "graduate":             "Graduate / Entry-Level",
}

# ------------------------------------------------------------------ #
#  Pydantic schemas                                                   #
# ------------------------------------------------------------------ #

class TemplateCategoryCount(BaseModel):
    category: str
    label: str
    count: int


class TemplateResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    category: str
    category_label: str
    tags: List[str]
    thumbnail_url: Optional[str]
    pdf_url: Optional[str]
    sort_order: int


class TemplateDetailResponse(TemplateResponse):
    latex_content: str


class UseTemplateRequest(BaseModel):
    title: Optional[str] = None


class TemplateAdminUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    category: str = Field(..., min_length=1, max_length=100)
    tags: List[str] = Field(default_factory=list)
    thumbnail_url: Optional[str] = Field(default=None, max_length=1000)
    latex_content: str = Field(..., min_length=1)
    is_active: bool = True
    sort_order: int = 0


# ------------------------------------------------------------------ #
#  Helpers                                                            #
# ------------------------------------------------------------------ #

def _validate_uuid(value: str) -> str:
    """Validate that value is a proper UUID string. Raises 404 if not."""
    try:
        _uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Template not found")
    return value


def _category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category.replace("_", " ").title())


def _require_valid_category(category: str) -> str:
    normalized = category.strip()
    if normalized not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown category: '{category}'")
    return normalized


async def require_template_admin(
    admin_secret: Optional[str] = Header(default=None, alias="X-Admin-Secret"),
):
    if not settings.ADMIN_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Admin template management is not configured")
    if admin_secret != settings.ADMIN_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin secret")


def _to_response(t: ResumeTemplate, request: Request) -> TemplateResponse:
    base = str(request.base_url).rstrip("/")
    return TemplateResponse(
        id=t.id,
        name=t.name,
        description=t.description,
        category=t.category,
        category_label=_category_label(t.category),
        tags=t.tags or [],
        thumbnail_url=f"{base}/templates/{t.id}/thumbnail",
        pdf_url=f"{base}/templates/{t.id}/pdf",
        sort_order=t.sort_order,
    )


def _to_detail(t: ResumeTemplate, request: Request) -> TemplateDetailResponse:
    base = str(request.base_url).rstrip("/")
    return TemplateDetailResponse(
        id=t.id,
        name=t.name,
        description=t.description,
        category=t.category,
        category_label=_category_label(t.category),
        tags=t.tags or [],
        thumbnail_url=f"{base}/templates/{t.id}/thumbnail",
        pdf_url=f"{base}/templates/{t.id}/pdf",
        sort_order=t.sort_order,
        latex_content=t.latex_content,
    )


# ------------------------------------------------------------------ #
#  Endpoints                                                          #
# ------------------------------------------------------------------ #

@router.get("/categories", response_model=List[TemplateCategoryCount])
async def list_categories(db: AsyncSession = Depends(get_db)):
    """List template categories with per-category counts."""
    rows = (await db.execute(
        select(ResumeTemplate.category, func.count().label("cnt"))
        .where(ResumeTemplate.is_active.is_(True))
        .group_by(ResumeTemplate.category)
        .order_by(ResumeTemplate.category)
    )).all()
    return [
        TemplateCategoryCount(
            category=row.category,
            label=_category_label(row.category),
            count=row.cnt,
        )
        for row in rows
    ]


@router.get("/", response_model=List[TemplateResponse])
async def list_templates(
    request: Request,
    category: Optional[str] = Query(None, description="Filter by category slug"),
    search: Optional[str] = Query(None, description="Search by name (case-insensitive)"),
    db: AsyncSession = Depends(get_db),
):
    """List all active templates. Optionally filter by category or search by name."""
    stmt = (
        select(ResumeTemplate)
        .where(ResumeTemplate.is_active.is_(True))
    )

    if category and category.lower() != "all":
        if category not in VALID_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Unknown category: '{category}'")
        stmt = stmt.where(ResumeTemplate.category == category)

    if search:
        stmt = stmt.where(
            func.lower(ResumeTemplate.name).contains(search.strip().lower())
        )

    stmt = stmt.order_by(ResumeTemplate.category, ResumeTemplate.sort_order, ResumeTemplate.name)
    templates = (await db.execute(stmt)).scalars().all()
    return [_to_response(t, request) for t in templates]


@router.head("/{template_id}/thumbnail")
async def head_template_thumbnail(template_id: str):
    """Check if a thumbnail exists in MinIO (lightweight — no body download)."""
    _validate_uuid(template_id)
    try:
        if not storage_service.file_exists(f"templates/{template_id}.png"):
            raise HTTPException(status_code=404, detail="Thumbnail not found")
    except HTTPException:
        raise
    except Exception:
        logger.exception("MinIO error checking thumbnail for %s", template_id)
        raise HTTPException(status_code=502, detail="Storage unavailable")
    return Response(
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{template_id}/thumbnail")
async def get_template_thumbnail(template_id: str):
    """Serve the pre-compiled PNG thumbnail from MinIO."""
    _validate_uuid(template_id)
    try:
        data = storage_service.download_bytes(f"templates/{template_id}.png")
    except Exception:
        logger.exception("MinIO error fetching thumbnail for %s", template_id)
        raise HTTPException(status_code=502, detail="Storage unavailable")
    if data is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.head("/{template_id}/pdf")
async def head_template_pdf(template_id: str):
    """Check if a PDF exists in MinIO (lightweight — no body download)."""
    _validate_uuid(template_id)
    try:
        if not storage_service.file_exists(f"templates/{template_id}.pdf"):
            raise HTTPException(status_code=404, detail="PDF not found")
    except HTTPException:
        raise
    except Exception:
        logger.exception("MinIO error checking PDF for %s", template_id)
        raise HTTPException(status_code=502, detail="Storage unavailable")
    return Response(
        media_type="application/pdf",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{template_id}/pdf")
async def get_template_pdf(template_id: str):
    """Serve the pre-compiled PDF from MinIO."""
    _validate_uuid(template_id)
    try:
        data = storage_service.download_bytes(f"templates/{template_id}.pdf")
    except Exception:
        logger.exception("MinIO error fetching PDF for %s", template_id)
        raise HTTPException(status_code=502, detail="Storage unavailable")
    if data is None:
        raise HTTPException(status_code=404, detail="PDF not found")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{template_id}", response_model=TemplateDetailResponse)
async def get_template(template_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Get full template details including latex_content."""
    _validate_uuid(template_id)
    t = await db.get(ResumeTemplate, template_id)
    if not t or not t.is_active:
        raise HTTPException(status_code=404, detail="Template not found")
    return _to_detail(t, request)


@router.post("/{template_id}/use")
async def use_template(
    template_id: str,
    body: UseTemplateRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Create a new resume from a template. Requires authentication."""
    _validate_uuid(template_id)
    t = await db.get(ResumeTemplate, template_id)
    if not t or not t.is_active:
        raise HTTPException(status_code=404, detail="Template not found")

    title = (body.title or "").strip() or t.name
    resume = Resume(
        user_id=user_id,
        title=title,
        latex_content=t.latex_content,
        is_template=False,
        tags=[t.category],
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)

    logger.info("User %s created resume %s from template %s (%s)", user_id, resume.id, template_id, t.name)
    return {"resume_id": resume.id, "title": resume.title}


@router.post("", response_model=TemplateDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateAdminUpsertRequest,
    request: Request,
    _: None = Depends(require_template_admin),
    db: AsyncSession = Depends(get_db),
):
    template = ResumeTemplate(
        name=body.name.strip(),
        description=body.description.strip() if body.description else None,
        category=_require_valid_category(body.category),
        tags=[tag.strip() for tag in body.tags if tag.strip()],
        thumbnail_url=body.thumbnail_url.strip() if body.thumbnail_url else None,
        latex_content=body.latex_content,
        is_active=body.is_active,
        sort_order=body.sort_order,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return _to_detail(template, request)


@router.put("/{template_id}", response_model=TemplateDetailResponse)
async def update_template(
    template_id: str,
    body: TemplateAdminUpsertRequest,
    request: Request,
    _: None = Depends(require_template_admin),
    db: AsyncSession = Depends(get_db),
):
    _validate_uuid(template_id)
    template = await db.get(ResumeTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    template.name = body.name.strip()
    template.description = body.description.strip() if body.description else None
    template.category = _require_valid_category(body.category)
    template.tags = [tag.strip() for tag in body.tags if tag.strip()]
    template.thumbnail_url = body.thumbnail_url.strip() if body.thumbnail_url else None
    template.latex_content = body.latex_content
    template.is_active = body.is_active
    template.sort_order = body.sort_order
    await db.commit()
    await db.refresh(template)
    return _to_detail(template, request)


@router.patch("/{template_id}/activate", response_model=TemplateDetailResponse)
async def activate_template(
    template_id: str,
    request: Request,
    _: None = Depends(require_template_admin),
    db: AsyncSession = Depends(get_db),
):
    _validate_uuid(template_id)
    template = await db.get(ResumeTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    template.is_active = True
    await db.commit()
    await db.refresh(template)
    return _to_detail(template, request)


@router.patch("/{template_id}/deactivate", response_model=TemplateDetailResponse)
async def deactivate_template(
    template_id: str,
    request: Request,
    _: None = Depends(require_template_admin),
    db: AsyncSession = Depends(get_db),
):
    _validate_uuid(template_id)
    template = await db.get(ResumeTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    template.is_active = False
    await db.commit()
    await db.refresh(template)
    return _to_detail(template, request)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: str,
    _: None = Depends(require_template_admin),
    db: AsyncSession = Depends(get_db),
):
    _validate_uuid(template_id)
    template = await db.get(ResumeTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(template)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
