"""Bounded originals and expiry cleanup, separate from request/worker imports."""
from __future__ import annotations

import io
from itertools import islice

from sqlalchemy import delete, func, select

from ...database.models import ResumePdfImport

MAX_ORIGINAL_BYTES = 10 * 1024 * 1024


def validate_original_pdf(content: bytes) -> None:
    if not content.startswith(b"%PDF-") or len(content) > MAX_ORIGINAL_BYTES:
        raise ValueError("Choose a PDF no larger than ten MiB")

    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser

    try:
        with io.BytesIO(content) as stream:
            document = PDFDocument(PDFParser(stream), password="")
            # A PDF encrypted with an empty user password is readable, but is
            # still outside the explicitly unencrypted import contract.
            if document.encryption is not None:
                raise ValueError("Choose an unencrypted PDF")
            # Do not materialize every page of an arbitrarily large page tree
            # just to reject it. The 51st page is sufficient to fail admission.
            # pdfplumber.close() materializes its pages during cleanup even
            # after an early rejection; use its underlying parser directly.
            pages = sum(1 for _ in islice(PDFPage.create_pages(document), 51))
            if not 1 <= pages <= 50:
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
