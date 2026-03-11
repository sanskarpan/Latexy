"""
XML Parser - Parse XML resume files.

Uses defusedxml to prevent XXE (XML External Entity) injection attacks.
"""
import logging
from typing import Optional

from .base_parser import AbstractParser, ParsedResume

logger = logging.getLogger(__name__)


class XMLParser(AbstractParser):
    """Parser for XML resume files."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        if not file_content:
            raise ValueError("XML file is empty")

        try:
            import defusedxml.ElementTree as ET
        except ImportError:
            raise ValueError("defusedxml not installed. Run: pip install defusedxml")

        try:
            root = ET.fromstring(file_content)
            # Extract all text nodes recursively
            lines = []
            for elem in root.iter():
                text = (elem.text or '').strip()
                tail = (elem.tail or '').strip()
                if text:
                    lines.append(text)
                if tail:
                    lines.append(tail)
            full_text = '\n'.join(lines)

            if not full_text.strip():
                raise ValueError("No text content found in XML file")

            return self._build_parsed_resume(full_text, filename)

        except ET.ParseError as e:
            raise ValueError(f"Invalid XML syntax: {e}")
        except Exception as e:
            logger.error(f"Error parsing XML: {e}")
            raise ValueError(f"Failed to parse XML: {str(e)}")

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        if not file_content:
            return False, "File is empty"
        try:
            import defusedxml.ElementTree as ET
            ET.fromstring(file_content)
            return True, None
        except Exception as e:
            return False, f"Invalid XML: {e}"
