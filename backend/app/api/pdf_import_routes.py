"""Preserved private PDFs and explicit, deterministic template adaptation."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..database.connection import get_db
from ..database.models import Resume, ResumePdfImport, ResumeTemplate, User
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.entitlements import require_feature
from ..parsers.pdf_parser import PDFParser
from ..services.resume_builder_service import SUPPORTED_BUILDER_CATEGORIES, resume_builder_service
from ..services.resume_engine.pdf_imports import MAX_ORIGINAL_BYTES, purge_expired_imports, validate_original_pdf
from ..services.resume_engine.semantic import (
    DocumentConflict,
    apply_node_edits,
    project_document,
    project_managed_document,
    public_document,
)
from ..utils.file_utils import read_upload_capped
from ..utils.uuid_guard import ensure_uuid
from .resume_routes import _get_builder_template

router = APIRouter(prefix="/resumes", tags=["pdf-imports"])
MAX_STAGED_IMPORTS = 10
REVIEW_WARNING = "Extracted fields may omit or misinterpret content. Compare them with your original PDF before choosing a template."
UNAVAILABLE_WARNING = "Text extraction was unavailable. Your original PDF is preserved; add your details before adapting it."


class ImportFieldEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    node_id: str = Field(min_length=1, max_length=128)
    expected_node_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    text: str = Field(max_length=4000)


class AdaptImport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    template_id: str
    title: str = Field(min_length=1, max_length=255)
    expected_original_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    field_edits: list[ImportFieldEdit] = Field(default_factory=list, max_length=100)


def seed_document(row: ResumePdfImport, *, category="ats_safe", template_id=None) -> dict:
    return project_managed_document(document_id=row.id, owner_scope=row.user_id, content_revision=1,
                                    structured_content=row.structured_seed, category=category, template_id=template_id)


async def receipt(db, row) -> dict:
    document = seed_document(row)
    # Numeric confidence is not available from the current parser. Unknown
    # remains explicit; successful extraction is not factual verification.
    fields = [{"field_id": node["node_id"], "node_revision": node["node_revision"],
               "label": node["section"].replace("_", " ").title() + " · " +
                        (node["kind"].title() + " " + str(node["_path"][-1] + 1) if isinstance(node["_path"][-1], int)
                         else str(node["_path"][-1]).replace("_", " ").title()),
               "text": node["text"], "confidence": "unknown", "warnings": []}
              for node in document["nodes"]]
    templates = (await db.scalars(select(ResumeTemplate).where(
        ResumeTemplate.is_active.is_(True), ResumeTemplate.category.in_(SUPPORTED_BUILDER_CATEGORIES),
        or_(ResumeTemplate.document_type == "resume", ResumeTemplate.document_type.is_(None)),
    ).order_by(ResumeTemplate.sort_order, ResumeTemplate.id))).all()
    return {"import_id": row.id, "resume_id": row.resume_id,
            "original": {"filename": row.filename, "mime_type": "application/pdf", "size_bytes": row.size_bytes,
                         "sha256": row.source_sha256, "preview_url": f"/resumes/imports/{row.id}/original"},
            "extraction": {"status": row.extraction_status, "fields": fields,
                           "warnings": [UNAVAILABLE_WARNING if row.extraction_status == "unavailable" else REVIEW_WARNING]},
            "supported_templates": [{"template_id": template.id, "name": template.name, "category": template.category}
                                    for template in templates],
            "expires_at": row.expires_at.isoformat() if row.expires_at else None}


async def owned_import(db, import_id, user_id, *, lock=False):
    ensure_uuid(import_id, "Import not found")
    query = select(ResumePdfImport).where(ResumePdfImport.id == import_id, ResumePdfImport.user_id == user_id,
        or_(ResumePdfImport.expires_at.is_(None), ResumePdfImport.expires_at > func.clock_timestamp()))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(404, "Import not found")
    return row


@router.post("/imports/pdf", status_code=201, dependencies=[Depends(require_feature("resume_builder"))])
async def import_pdf(file: UploadFile = File(...), db: AsyncSession = Depends(get_db),
                     user_id: str = Depends(get_current_user_required)):
    content = await read_upload_capped(file, MAX_ORIGINAL_BYTES)
    if not content.startswith(b"%PDF-"):
        raise HTTPException(415, "Choose a PDF file")
    try:
        await asyncio.to_thread(validate_original_pdf, content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    seed, extraction_status = resume_builder_service.empty_document(), "unavailable"
    try:
        parsed = await PDFParser().parse(content, file.filename or "original.pdf")
        candidate = resume_builder_service.normalize(resume_builder_service.from_parsed_resume(parsed))
        projection = project_managed_document(document_id="import", owner_scope=user_id, content_revision=1,
                                              structured_content=candidate, category="ats_safe")
        if len(projection["nodes"]) > 400 or len(json.dumps(candidate, ensure_ascii=False).encode()) > 1024 * 1024:
            raise ValueError("Imported fields exceed bounded support")
        seed, extraction_status = candidate, "partial"
    except (ValueError, ValidationError, DocumentConflict):
        pass  # retain original even if no trustworthy bounded field projection exists
    # Serialize each owner's staged admission; concurrent uploads cannot exceed
    # the pending cap. Expired private attachments are deleted with their row.
    if await db.scalar(select(User.id).where(User.id == user_id).with_for_update()) is None:
        raise HTTPException(401, "Account not found")
    await purge_expired_imports(db)
    count = await db.scalar(select(func.count()).select_from(ResumePdfImport).where(
        ResumePdfImport.user_id == user_id, ResumePdfImport.resume_id.is_(None)))
    if count >= MAX_STAGED_IMPORTS:
        raise HTTPException(429, "Finish or remove a pending PDF import before adding another")
    filename = (file.filename or "original.pdf").replace("\\", "/").rsplit("/", 1)[-1]
    filename = "".join(character for character in filename if character.isprintable())[:255] or "original.pdf"
    row = ResumePdfImport(id=str(uuid4()), user_id=user_id, filename=filename, source_sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content), original_pdf=content, structured_seed=seed, extraction_status=extraction_status,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24))
    db.add(row)
    await db.commit()
    return await receipt(db, row)


@router.get("/imports/{import_id}")
async def get_import(import_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_required)):
    return await receipt(db, await owned_import(db, import_id, user_id))


@router.get("/imports/{import_id}/original")
async def original_pdf(import_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_required)):
    row = await owned_import(db, import_id, user_id)
    data = await db.scalar(select(ResumePdfImport.original_pdf).where(ResumePdfImport.id == row.id, ResumePdfImport.user_id == user_id))
    if (not isinstance(data, bytes) or len(data) != row.size_bytes or len(data) > MAX_ORIGINAL_BYTES
            or hashlib.sha256(data).hexdigest() != row.source_sha256):
        raise HTTPException(409, "Original PDF integrity check failed")
    return Response(data, media_type="application/pdf", headers={"Cache-Control": "private, no-store",
                    "Content-Disposition": 'inline; filename="original.pdf"', "X-Content-Type-Options": "nosniff"})


@router.delete("/imports/{import_id}", status_code=204)
async def discard_import(import_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_required)):
    row = await owned_import(db, import_id, user_id, lock=True)
    if row.resume_id is not None:
        raise HTTPException(409, "This original belongs to a saved resume")
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


@router.post("/imports/{import_id}/adapt", dependencies=[Depends(require_feature("resume_builder"))])
async def adapt_import(import_id: str, body: AdaptImport, db: AsyncSession = Depends(get_db),
                       user_id: str = Depends(get_current_user_required)):
    row = await owned_import(db, import_id, user_id, lock=True)
    if row.source_sha256 != body.expected_original_sha256:
        raise HTTPException(409, "Choose the original PDF again before adapting it")
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "Give the resume a title")
    template = await _get_builder_template(db, body.template_id)
    patches = [patch.model_dump() for patch in body.field_edits]
    identity = hashlib.sha256(json.dumps({"original": row.source_sha256, "template": template.id, "title": title,
        "patches": sorted(patches, key=lambda patch: patch["node_id"])}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if row.resume_id is not None:
        if row.adaptation_sha256 != identity:
            raise HTTPException(409, "This PDF was already adapted; open the saved resume")
        resume = await db.scalar(select(Resume).where(Resume.id == row.resume_id, Resume.user_id == user_id))
        if resume is None:
            raise HTTPException(404, "Saved resume not found")
        document = project_document(resume, template.category)
    else:
        document = seed_document(row, category=template.category, template_id=template.id)
        try:
            source, structured = apply_node_edits(document, patches, expected_revision=1, expected_source=document["source_sha256"])
        except (DocumentConflict, ValidationError) as exc:
            raise HTTPException(409, str(exc)) from exc
        resume = Resume(id=str(uuid4()), user_id=user_id, title=title, latex_content=source, structured_content=structured,
            structured_version=1, selected_template_id=template.id, content_source="builder", builder_status="active",
            document_type="resume", resume_settings={"compiler": settings.DEFAULT_NEW_RESUME_COMPILER})
        db.add(resume)
        await db.flush()
        row.resume_id, row.adaptation_sha256, row.expires_at = resume.id, identity, None
        document = project_document(resume, template.category)
    await db.commit()
    return {"resume_id": resume.id, "document": public_document(document), "latex_content": resume.latex_content,
            "original": (await receipt(db, row))["original"]}


@router.get("/{resume_id}/engine/import")
async def resume_import(resume_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_required)):
    ensure_uuid(resume_id, "Resume not found")
    if await db.scalar(select(Resume.id).where(Resume.id == resume_id, Resume.user_id == user_id)) is None:
        raise HTTPException(404, "Resume not found")
    row = await db.scalar(select(ResumePdfImport).where(ResumePdfImport.resume_id == resume_id, ResumePdfImport.user_id == user_id))
    return await receipt(db, row) if row else None
