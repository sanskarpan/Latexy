"""
Text Parser - Parse plain text resume files with heuristic section detection.
"""
import logging
from typing import Optional

from .base_parser import AbstractParser, ParsedResume

logger = logging.getLogger(__name__)


class TextParser(AbstractParser):
    """Parser for plain text (.txt) resume files."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        try:
            text = file_content.decode('utf-8', errors='ignore')
            if not text.strip():
                raise ValueError("Text file is empty")
            section_hints = self._extract_sections_heuristic(text)
            return self._build_parsed_resume(text, filename, section_hints=list(section_hints))
        except Exception as e:
            logger.error(f"Error parsing text file: {e}")
            raise ValueError(f"Failed to parse text file: {str(e)}")

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        try:
            content = file_content.decode('utf-8', errors='ignore')
            if not content.strip():
                return False, "Text file is empty"
            return True, None
        except Exception as e:
            return False, str(e)
