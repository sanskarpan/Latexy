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


def validate_job_id(job_id: str) -> None:
    """Validate job ID format."""
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")


def get_job_files(job_id: str) -> tuple[Path, Path, Path]:
    """Get file paths for a job."""
    job_dir = settings.TEMP_DIR / job_id
    pdf_file = job_dir / "resume.pdf"
    log_file = job_dir / "resume.log"
    return job_dir, pdf_file, log_file
