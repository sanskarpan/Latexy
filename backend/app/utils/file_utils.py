"""
File utility functions.
"""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile

from ..core.config import settings


def validate_file_upload(file: UploadFile) -> None:
    """Validate uploaded file."""
    if file.size and file.size > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413, 
            detail=f"File too large. Maximum size: {settings.MAX_FILE_SIZE} bytes"
        )
    
    if not file.filename or not file.filename.endswith('.tex'):
        raise HTTPException(
            status_code=400, 
            detail="File must be a .tex file"
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
