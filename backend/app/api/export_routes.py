"""
Export Routes - Convert LaTeX resumes to other file formats for download.

All exports are synchronous (rule-based conversion, no LLM).
GET /export/{resume_id}/{fmt}   — export saved resume (requires auth)
POST /export/content/{fmt}      — export from raw LaTeX (no auth, for /try page)
"""

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..database.connection import get_db
from ..database.models import Compilation, Resume
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.entitlements import require_feature
from ..services.document_export_service import document_export_service
from ..services.json_resume_interchange_service import json_resume_interchange_service
from ..utils.bounded_io import BoundedReadError, read_file_bounded
from ..utils.file_utils import get_job_files
from ..utils.uuid_guard import ensure_uuid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])

# Supported export formats: key → (MIME type, download filename)
EXPORT_FORMATS: dict[str, tuple[str, str]] = {
    "tex": ("text/x-tex", "resume.tex"),
    "md": ("text/markdown", "resume.md"),
    "txt": ("text/plain", "resume.txt"),
    "html": ("text/html", "resume.html"),
    "json": ("application/json", "resume.json"),
    "yaml": ("text/yaml", "resume.yaml"),
    "xml": ("application/xml", "resume.xml"),
    # These are distinct, standards-backed document formats.  ``xml`` above
    # remains the existing JSON-shaped interchange XML; it is not DocBook.
    "epub": ("application/epub+zip", "resume.epub"),
    "odf": ("application/vnd.oasis.opendocument.text", "resume.odt"),
    "docbook": ("application/docbook+xml", "resume.docbook"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "resume.docx",
    ),
    # These are rendered from the latest compiled PDF with Poppler. They are
    # intentionally not offered by POST /export/content because raw LaTeX
    # cannot be honestly labelled as either image format.
    "svg": ("image/svg+xml", "resume.svg"),
    "jpeg": ("image/jpeg", "resume.jpeg"),
}

IMAGE_EXPORT_FORMATS = frozenset({"svg", "jpeg"})
MAX_RENDER_INPUT_BYTES = 20 * 1024 * 1024
MAX_RENDER_OUTPUT_BYTES = 20 * 1024 * 1024
PDF_RENDER_TIMEOUT_SECONDS = 15


class PdfRenderUnavailable(RuntimeError):
    """The deployment does not have the verified Poppler renderer."""


class PdfRenderFailed(RuntimeError):
    """Poppler could not render the bounded, owned PDF."""


class PdfRenderTimedOut(RuntimeError):
    """Poppler exceeded the fixed conversion timeout."""


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
    if fmt == "epub":
        return document_export_service.to_epub(latex_content)
    if fmt == "odf":
        return document_export_service.to_odf(latex_content)
    if fmt == "docbook":
        return document_export_service.to_docbook(latex_content).encode("utf-8")
    if fmt == "docx":
        return document_export_service.to_docx(latex_content)
    raise ValueError(f"Unknown format: {fmt}")


MAX_EXPORT_CONTENT_BYTES = 512 * 1024  # 512 KB — enough for any single resume


class ExportContentRequest(BaseModel):
    latex_content: str


async def _get_latest_compiled_pdf(
    resume_id: str,
    user_id: str,
    db: AsyncSession,
) -> bytes:
    """Fetch the latest owned compiled PDF without exposing storage paths."""
    compilation_result = await db.execute(
        select(Compilation)
        .where(
            Compilation.resume_id == resume_id,
            Compilation.user_id == user_id,
            Compilation.status == "completed",
        )
        .order_by(Compilation.created_at.desc())
        .limit(1)
    )
    compilation = compilation_result.scalar_one_or_none()
    if not compilation:
        raise HTTPException(status_code=422, detail="No compiled PDF found. Please compile your resume first.")
    declared_pdf_size = getattr(compilation, "pdf_size", None)
    if declared_pdf_size is not None and declared_pdf_size > MAX_RENDER_INPUT_BYTES:
        raise HTTPException(status_code=413, detail="Compiled PDF is too large to render")

    pdf_bytes: bytes | None = None
    if compilation.pdf_path:
        try:
            from ..services.storage_service import download_bytes

            pdf_bytes = await run_in_threadpool(
                download_bytes, compilation.pdf_path, MAX_RENDER_INPUT_BYTES
            )
        except Exception as exc:
            # Storage errors can contain object keys or provider details; keep
            # logs metadata-only and never include resume identifiers/content.
            logger.warning("Compiled PDF storage lookup failed", extra={"error_type": type(exc).__name__})

    if pdf_bytes is None:
        # Compilation job IDs are UUIDs generated by the server. Validate before
        # joining the configured temp root so a corrupt row cannot escape it.
        try:
            _, temp_pdf, _ = get_job_files(str(compilation.job_id))
        except HTTPException as exc:
            raise HTTPException(status_code=500, detail="Compiled PDF metadata is invalid") from exc
        if temp_pdf.is_file():
            if temp_pdf.stat().st_size <= MAX_RENDER_INPUT_BYTES:
                pdf_bytes = await run_in_threadpool(
                    read_file_bounded, temp_pdf, MAX_RENDER_INPUT_BYTES
                )

    if not pdf_bytes:
        raise HTTPException(status_code=422, detail="PDF not available. Please recompile your resume and try again.")
    if len(pdf_bytes) > MAX_RENDER_INPUT_BYTES:
        raise HTTPException(status_code=413, detail="Compiled PDF is too large to render")
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="Compiled PDF is invalid")
    return pdf_bytes


def _render_pdf_first_page(pdf_bytes: bytes, fmt: str) -> bytes:
    """Render only page one using fixed, safe pdftocairo arguments."""
    if fmt not in IMAGE_EXPORT_FORMATS:
        raise ValueError(f"Unsupported image format: {fmt}")
    if len(pdf_bytes) > MAX_RENDER_INPUT_BYTES:
        raise PdfRenderFailed("Compiled PDF is too large to render")
    converter = shutil.which("pdftocairo")
    if not converter:
        raise PdfRenderUnavailable("pdftocairo is not installed")

    with tempfile.TemporaryDirectory(prefix="latexy-export-") as temp_dir:
        work_dir = Path(temp_dir)
        input_path = work_dir / "input.pdf"
        output_prefix = work_dir / "rendered"
        output_path = work_dir / ("rendered.svg" if fmt == "svg" else "rendered.jpg")
        input_path.write_bytes(pdf_bytes)
        if fmt == "svg":
            # pdftocairo rejects -singlefile for SVG; with -f/-l selecting
            # one page, SVG's output argument is already the full filename.
            command = [
                converter,
                "-f", "1",
                "-l", "1",
                "-r", "150",
                "-svg",
                str(input_path),
                str(output_path),
            ]
        else:
            command = [
                converter,
                "-singlefile",
                "-f", "1",
                "-l", "1",
                "-r", "150",
                "-jpeg",
                str(input_path),
                str(output_prefix),
            ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(work_dir),
                # Poppler output is not part of the API response.  Discard it
                # so a malformed PDF cannot make subprocess.run retain an
                # unbounded diagnostic stream in memory.
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=PDF_RENDER_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PdfRenderTimedOut("PDF rendering timed out") from exc
        except OSError as exc:
            raise PdfRenderUnavailable("pdftocairo could not be started") from exc

        if completed.returncode != 0 or not output_path.is_file():
            raise PdfRenderFailed("PDF could not be rendered")
        if output_path.stat().st_size > MAX_RENDER_OUTPUT_BYTES:
            raise PdfRenderFailed("Rendered image is too large")
        try:
            rendered = read_file_bounded(output_path, MAX_RENDER_OUTPUT_BYTES)
        except BoundedReadError as exc:
            raise PdfRenderFailed("Rendered image is too large") from exc
        if not rendered:
            raise PdfRenderFailed("Rendered image is empty")
        if fmt == "svg" and b"<svg" not in rendered[:4096].lower():
            raise PdfRenderFailed("Renderer did not produce SVG output")
        if fmt == "jpeg" and not rendered.startswith(b"\xff\xd8\xff"):
            raise PdfRenderFailed("Renderer did not produce JPEG output")
        return rendered


@router.get("/formats")
async def list_export_formats():
    """List all available export formats."""
    return {"formats": [{"key": k, "mime_type": v[0], "filename": v[1]} for k, v in EXPORT_FORMATS.items()]}


# ── Feature 90: Canva / Figma export ─────────────────────────────────────────
# These routes must be registered BEFORE the generic /{resume_id}/{fmt} route
# so that literal path segments ("canva", "figma") win over the path parameter.


class CanvaElement(BaseModel):
    type: str  # "HEADING" | "TEXT" | "DIVIDER"
    text: str
    style: dict = {}


class CanvaResumeExport(BaseModel):
    type: str = "DESIGN"
    elements: list[CanvaElement]


class FigmaEntry(BaseModel):
    heading: str = ""
    subheading: str = ""
    date: str = ""
    bullets: list[str] = []


class FigmaSection(BaseModel):
    title: str
    entries: list[FigmaEntry]


class FigmaResumeExport(BaseModel):
    sections: list[FigmaSection]


@router.get("/{resume_id}/canva", response_model=CanvaResumeExport)
async def export_canva(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> CanvaResumeExport:
    """
    Export a resume as Canva Content Import API JSON.
    Maps LaTeX sections to typed Canva elements (HEADING, TEXT, DIVIDER).
    Requires authentication; user must own the resume.
    """
    resume = await db.get(Resume, ensure_uuid(resume_id, "Resume not found"))
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if resume.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if not (resume.latex_content or "").strip():
        raise HTTPException(status_code=400, detail="Resume has no content to export")
    if len(resume.latex_content.encode("utf-8")) > MAX_EXPORT_CONTENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Content too large (max {MAX_EXPORT_CONTENT_BYTES // 1024} KB)",
        )

    try:
        data = document_export_service.to_canva(resume.latex_content)
        elements = [CanvaElement(**e) for e in data["elements"]]
        return CanvaResumeExport(elements=elements)
    except Exception as exc:
        logger.error("Error exporting resume %s to Canva", resume_id, extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=500, detail="Export failed")


@router.get("/{resume_id}/figma", response_model=FigmaResumeExport)
async def export_figma(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> FigmaResumeExport:
    """
    Export a resume as Figma plugin JSON (structured sections → entries).
    The returned JSON is consumed by the Latexy Figma plugin.
    Requires authentication; user must own the resume.
    """
    resume = await db.get(Resume, ensure_uuid(resume_id, "Resume not found"))
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if resume.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if not (resume.latex_content or "").strip():
        raise HTTPException(status_code=400, detail="Resume has no content to export")
    if len(resume.latex_content.encode("utf-8")) > MAX_EXPORT_CONTENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Content too large (max {MAX_EXPORT_CONTENT_BYTES // 1024} KB)",
        )

    try:
        data = document_export_service.to_figma(resume.latex_content)
        sections = [
            FigmaSection(
                title=s["title"],
                entries=[FigmaEntry(**e) for e in s["entries"]],
            )
            for s in data["sections"]
        ]
        return FigmaResumeExport(sections=sections)
    except Exception as exc:
        logger.error("Error exporting resume %s to Figma", resume_id, extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=500, detail="Export failed")


@router.get(
    "/{resume_id}/{fmt}",
    dependencies=[Depends(require_feature("exports"))],
)
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
        resume = await db.get(Resume, ensure_uuid(resume_id, "Resume not found"))
        if not resume:
            raise HTTPException(status_code=404, detail="Resume not found")
        if resume.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        if not (resume.latex_content or "").strip():
            raise HTTPException(status_code=400, detail="Resume has no content to export")

        if fmt == "json" and resume.structured_content and resume.content_source == "builder":
            data = json_resume_interchange_service.to_json_resume(resume.structured_content)
            content_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        elif fmt in IMAGE_EXPORT_FORMATS:
            pdf_bytes = await _get_latest_compiled_pdf(resume.id, user_id, db)
            content_bytes = await run_in_threadpool(_render_pdf_first_page, pdf_bytes, fmt)
        else:
            content_bytes = _convert_latex(resume.latex_content, fmt)
        mime_type, filename = EXPORT_FORMATS[fmt]

        return Response(
            content=content_bytes,
            media_type=mime_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except HTTPException:
        raise
    except PdfRenderUnavailable as exc:
        raise HTTPException(status_code=503, detail="Image export is unavailable on this server") from exc
    except PdfRenderTimedOut as exc:
        raise HTTPException(status_code=504, detail="Image export timed out; please try again") from exc
    except PdfRenderFailed as exc:
        raise HTTPException(status_code=422, detail="Compiled PDF could not be rendered") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Resume cannot be represented as {fmt}: {exc}",
        ) from exc
    except Exception as exc:
        logger.error(
            "Error exporting resume %s as %s",
            resume_id,
            fmt,
            extra={"error_type": type(exc).__name__},
        )
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

    if fmt in IMAGE_EXPORT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail="SVG and JPEG exports require a saved resume with a compiled PDF",
        )

    if not body.latex_content.strip():
        raise HTTPException(status_code=400, detail="latex_content cannot be empty")

    if len(body.latex_content.encode("utf-8")) > MAX_EXPORT_CONTENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Content too large (max {MAX_EXPORT_CONTENT_BYTES // 1024} KB)",
        )

    try:
        content_bytes = _convert_latex(body.latex_content, fmt)
        mime_type, filename = EXPORT_FORMATS[fmt]

        return Response(
            content=content_bytes,
            media_type=mime_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except PdfRenderUnavailable as exc:
        raise HTTPException(status_code=503, detail="Image export is unavailable on this server") from exc
    except PdfRenderTimedOut as exc:
        raise HTTPException(status_code=504, detail="Image export timed out; please try again") from exc
    except PdfRenderFailed as exc:
        raise HTTPException(status_code=422, detail="Compiled PDF could not be rendered") from exc
    except Exception as exc:
        logger.error("Error exporting content as %s", fmt, extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=500, detail="Export failed")
