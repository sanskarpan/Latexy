"""
PDF Parser - Extract text from PDF resumes using pdfplumber.
Falls back to OCR for scanned/image-based PDFs.
"""
import io
import logging
from typing import Optional

from .base_parser import AbstractParser, ParsedResume

logger = logging.getLogger(__name__)


class PDFParser(AbstractParser):
    """Parser for PDF resume files."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        try:
            import pdfplumber
        except ImportError:
            raise ValueError("pdfplumber not installed. Run: pip install pdfplumber")

        try:
            pages_text = []
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                for page in pdf.pages:
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

            return self._build_parsed_resume(full_text, filename)

        except Exception as e:
            logger.error(f"Error parsing PDF: {e}")
            raise ValueError(f"Failed to parse PDF: {str(e)}")

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        if not file_content.startswith(b"%PDF"):
            return False, "Not a valid PDF file (missing %PDF header)"
        return True, None
