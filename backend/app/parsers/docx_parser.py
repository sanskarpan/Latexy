"""
DOCX Parser - Extract text from Word documents using mammoth and python-docx.
"""
import io
import logging
from typing import Optional

from .base_parser import AbstractParser, ParsedResume

logger = logging.getLogger(__name__)


class DOCXParser(AbstractParser):
    """Parser for DOCX resume files."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        try:
            import mammoth
            from docx import Document
        except ImportError as e:
            raise ValueError(f"Required library not installed: {e}")

        try:
            # Use mammoth for clean text extraction
            result = mammoth.extract_raw_text(io.BytesIO(file_content))
            full_text = result.value or ""

            # Supplement with python-docx for heading-based section hints
            section_hints = []
            try:
                doc = Document(io.BytesIO(file_content))
                for para in doc.paragraphs:
                    if para.style.name.startswith('Heading') and para.text.strip():
                        section_hints.append(para.text.strip())
            except Exception as docx_err:
                logger.debug(f"python-docx heading extraction failed: {docx_err}")

            if not full_text.strip():
                raise ValueError("Could not extract text from DOCX file")

            return self._build_parsed_resume(full_text, filename, section_hints=section_hints)

        except Exception as e:
            logger.error(f"Error parsing DOCX: {e}")
            raise ValueError(f"Failed to parse DOCX: {str(e)}")

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        if not file_content.startswith(b"PK"):
            return False, "Not a valid DOCX file (missing ZIP/PK header)"
        return True, None
