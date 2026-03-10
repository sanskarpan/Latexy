"""
Export Routes - Convert LaTeX resumes to other file formats for download.

All exports are synchronous (rule-based conversion, no LLM).
GET /export/{resume_id}/{fmt}   — export saved resume (requires auth)
POST /export/content/{fmt}      — export from raw LaTeX (no auth, for /try page)
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..database.models import Resume
from ..middleware.auth_middleware import get_current_user_required
from ..services.document_export_service import document_export_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])

# Supported export formats: key → (MIME type, download filename)
EXPORT_FORMATS: dict[str, tuple[str, str]] = {
    "tex":  ("text/x-tex", "resume.tex"),
    "md":   ("text/markdown", "resume.md"),
    "txt":  ("text/plain", "resume.txt"),
    "html": ("text/html", "resume.html"),
    "json": ("application/json", "resume.json"),
    "yaml": ("text/yaml", "resume.yaml"),
    "xml":  ("application/xml", "resume.xml"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "resume.docx",
    ),
}


def _convert_latex(latex_content: str, fmt: str) -> bytes:
    """Convert LaTeX content to the requested format. Returns bytes."""
    if fmt == "tex":
        return latex_content.encode("utf-8")
    if fmt == "md":
        return document_export_service.to_markdown(latex_content).encode("utf-8")
    if fmt == "txt":
        return document_export_service.to_text(latex_content).encode("utf-8")
    if fmt == "html":
        return document_export_service.to_html(latex_content).encode("utf-8")
    if fmt == "json":
        data = document_export_service.to_json(latex_content)
        return json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    if fmt == "yaml":
        return document_export_service.to_yaml(latex_content).encode("utf-8")
    if fmt == "xml":
        return document_export_service.to_xml(latex_content).encode("utf-8")
    if fmt == "docx":
        return document_export_service.to_docx(latex_content)
    raise ValueError(f"Unknown format: {fmt}")


class ExportContentRequest(BaseModel):
    latex_content: str


@router.get("/formats")
async def list_export_formats():
    """List all available export formats."""
    return {
        "formats": [
            {"key": k, "mime_type": v[0], "filename": v[1]}
            for k, v in EXPORT_FORMATS.items()
        ]
    }


@router.get("/{resume_id}/{fmt}")
async def export_resume(
    resume_id: str,
    fmt: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """
    Export a saved resume in the requested format.
    Requires authentication. User must own the resume.
    """
    if fmt not in EXPORT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported export format '{fmt}'. Supported: {', '.join(EXPORT_FORMATS)}",
        )

    try:
        resume = await db.get(Resume, resume_id)
        if not resume:
            raise HTTPException(status_code=404, detail="Resume not found")
        if resume.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        content_bytes = _convert_latex(resume.latex_content, fmt)
        mime_type, filename = EXPORT_FORMATS[fmt]

        return Response(
            content=content_bytes,
            media_type=mime_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error exporting resume {resume_id} as {fmt}: {exc}")
        raise HTTPException(status_code=500, detail="Export failed")


@router.post("/content/{fmt}")
async def export_content(fmt: str, body: ExportContentRequest):
    """
    Export raw LaTeX content in the requested format.
    No authentication required — used by the /try page.
    """
    if fmt not in EXPORT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported export format '{fmt}'. Supported: {', '.join(EXPORT_FORMATS)}",
        )

    if not body.latex_content.strip():
        raise HTTPException(status_code=400, detail="latex_content cannot be empty")

    try:
        content_bytes = _convert_latex(body.latex_content, fmt)
        mime_type, filename = EXPORT_FORMATS[fmt]

        return Response(
            content=content_bytes,
            media_type=mime_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except Exception as exc:
        logger.error(f"Error exporting content as {fmt}: {exc}")
        raise HTTPException(status_code=500, detail="Export failed")
