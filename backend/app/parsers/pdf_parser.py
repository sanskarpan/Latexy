"""
PDF Parser - Extract text from PDF resumes using pdfplumber.
Falls back to OCR for scanned/image-based PDFs.
"""
import io
import logging
from typing import Optional

from .base_parser import AbstractParser, ParsedResume
from .pdf_layout import extract_layout_text

logger = logging.getLogger(__name__)

MAX_PDF_PAGES = 50  # Hard limit to prevent processing arbitrarily large PDFs


class PDFParser(AbstractParser):
    """Parser for PDF resume files."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        if not file_content:
            raise ValueError("PDF file is empty")

        try:
            import pdfplumber
        except ImportError:
            raise ValueError("pdfplumber not installed. Run: pip install pdfplumber")

        try:
            # Layout-aware pass first: it keeps right-aligned dates and
            # two-column blocks from being run together into one ambiguous line,
            # and identifies section headings by font prominence. Falls back to
            # flat extraction if it yields nothing (scanned/encrypted) or raises,
            # so this can only add information, never lose it.
            section_hints: list = []
            full_text = ""
            try:
                layout = extract_layout_text(file_content, max_pages=MAX_PDF_PAGES)
                if layout and layout.text.strip():
                    full_text = layout.text
                    section_hints = layout.section_hints
                    if layout.pages > MAX_PDF_PAGES:
                        logger.warning(
                            f"PDF has {layout.pages} pages; truncating to first "
                            f"{MAX_PDF_PAGES}: {filename}"
                        )
            except Exception as layout_err:
                logger.warning(
                    f"Layout-aware extraction failed, falling back to flat text: {layout_err}"
                )

            if not full_text:
                pages_text = []
                with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                    total_pages = len(pdf.pages)
                    if total_pages > MAX_PDF_PAGES:
                        logger.warning(
                            f"PDF has {total_pages} pages; truncating to first {MAX_PDF_PAGES}: {filename}"
                        )
                    for page in pdf.pages[:MAX_PDF_PAGES]:
                        text = page.extract_text(x_tolerance=3, y_tolerance=3)
                        if text:
                            pages_text.append(text)

                full_text = "\n\n".join(pages_text).strip()

            # If no text extracted (scanned PDF), fall back to OCR
            if not full_text:
                logger.info(f"PDF has no extractable text, falling back to OCR: {filename}")
                try:
                    from .image_parser import ocr_pdf_bytes
                    full_text = ocr_pdf_bytes(file_content)
                except Exception as ocr_err:
                    logger.warning(f"OCR fallback failed: {ocr_err}")
                    full_text = ""

            if not full_text.strip():
                raise ValueError("Could not extract text from PDF (no text content and OCR failed)")

            return self._build_parsed_resume(
                full_text, filename, section_hints=section_hints
            )

        except Exception as e:
            logger.error(f"Error parsing PDF: {e}")
            raise ValueError(f"Failed to parse PDF: {str(e)}")

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        if not file_content:
            return False, "File is empty"
        if not file_content.startswith(b"%PDF"):
            return False, "Not a valid PDF file (missing %PDF header)"
        return True, None
