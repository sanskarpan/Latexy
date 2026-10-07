"""Bounded originals and expiry cleanup, separate from request/worker imports."""
from __future__ import annotations

import io

from sqlalchemy import delete, func, select

from ...database.models import ResumePdfImport

MAX_ORIGINAL_BYTES = 10 * 1024 * 1024


def validate_original_pdf(content: bytes) -> None:
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if not 1 <= len(pdf.pages) <= 50:
                raise ValueError("Choose a PDF with one to fifty pages")
    except Exception as exc:
        raise ValueError("This PDF could not be opened; use an unencrypted PDF with one to fifty pages") from exc


async def purge_expired_imports(db, *, limit=200) -> int:
    ids = (await db.scalars(select(ResumePdfImport.id).where(
        ResumePdfImport.resume_id.is_(None), ResumePdfImport.expires_at <= func.clock_timestamp(),
    ).order_by(ResumePdfImport.expires_at).limit(min(max(limit, 1), 500)).with_for_update(skip_locked=True))).all()
    if ids:
        await db.execute(delete(ResumePdfImport).where(ResumePdfImport.id.in_(ids), ResumePdfImport.resume_id.is_(None)))
    return len(ids)
