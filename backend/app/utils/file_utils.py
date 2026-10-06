"""
File utility functions.
"""

import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from ..core.config import settings

ALLOWED_EXTENSIONS = {
    '.tex', '.latex', '.ltx',
    '.pdf',
    '.docx', '.doc',
    '.md', '.markdown', '.mdx',
    '.txt', '.text',
    '.html', '.htm',
    '.json',
    '.yaml', '.yml',
    '.toml',
    '.xml',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp',
}


def validate_file_upload(file: UploadFile) -> None:
    """Validate uploaded file."""
    if file.size and file.size > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.MAX_FILE_SIZE} bytes"
        )

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Filename is required"
        )

    # Check extension against allowed set
    import os
    ext = os.path.splitext(file.filename.lower())[1]
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )


async def read_upload_capped(
    file: UploadFile,
    max_bytes: int | None = None,
) -> bytes:
    """Read an upload without trusting Content-Length or UploadFile.size."""
    limit = settings.MAX_FILE_SIZE if max_bytes is None else max_bytes
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size: {limit} bytes",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def validate_job_id(job_id: str) -> None:
    """Validate job ID format."""
    try:
        uuid.UUID(job_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid job ID format")


def get_job_files(job_id: str) -> tuple[Path, Path, Path]:
    """Get file paths for a server-generated job beneath the temp root.

    Callers frequently use these paths as a local fallback after a cache or
    object-storage lookup.  Keep the validation next to path construction so
    a future caller cannot accidentally turn a corrupt/request-controlled job
    id into a path traversal primitive.
    """
    validate_job_id(job_id)
    job_dir = settings.TEMP_DIR / job_id
    pdf_file = job_dir / "resume.pdf"
    log_file = job_dir / "resume.log"
    return job_dir, pdf_file, log_file
