"""
DOCX Parser - Extract text from Word documents using mammoth and python-docx.
"""
import asyncio
import io
import logging
import zipfile
from typing import Optional

from .base_parser import AbstractParser, ParsedResume

logger = logging.getLogger(__name__)

MAX_DOCX_ENTRIES = 1_000
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


class DOCXParser(AbstractParser):
    """Parser for DOCX resume files."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        return await asyncio.to_thread(self._parse_sync, file_content, filename)

    @staticmethod
    def _validate_archive(file_content: bytes) -> None:
        """Reject malformed or expansion-heavy OOXML archives before extraction."""
        try:
            with zipfile.ZipFile(io.BytesIO(file_content)) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_DOCX_ENTRIES:
                    raise ValueError("DOCX archive contains too many files")
                if sum(entry.file_size for entry in entries) > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise ValueError("DOCX archive expands beyond the 50 MB safety limit")
                if not any(entry.filename.startswith("word/") for entry in entries):
                    raise ValueError("Not a valid DOCX file (missing 'word/' directory in ZIP)")
        except zipfile.BadZipFile as exc:
            raise ValueError("Not a valid DOCX file (corrupt ZIP archive)") from exc

    def _parse_sync(self, file_content: bytes, filename: str = "") -> ParsedResume:
        self._validate_archive(file_content)
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
            logger.error("Error parsing DOCX", extra={"error_type": type(e).__name__})
            raise ValueError("Failed to parse DOCX input") from e

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        if not file_content:
            return False, "File is empty"
        if not file_content.startswith(b"PK"):
            return False, "Not a valid DOCX file (missing ZIP/PK header)"
        # Verify it's actually a DOCX, not just any ZIP archive
        try:
            with zipfile.ZipFile(io.BytesIO(file_content)) as z:
                names = z.namelist()
            if not any(n.startswith('word/') for n in names):
                return False, "Not a valid DOCX file (missing 'word/' directory in ZIP)"
        except zipfile.BadZipFile:
            return False, "Not a valid DOCX file (corrupt ZIP archive)"
        except Exception:
            pass  # If zip check fails for any other reason, proceed to parse
        return True, None
