"""
XML Parser - Parse XML resume files.
"""
import logging
from typing import Optional

from .base_parser import AbstractParser, ParsedResume

logger = logging.getLogger(__name__)


class XMLParser(AbstractParser):
    """Parser for XML resume files."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        try:
            from lxml import etree
        except ImportError:
            raise ValueError("lxml not installed. Run: pip install lxml")

        try:
            root = etree.fromstring(file_content)
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

        except etree.XMLSyntaxError as e:
            raise ValueError(f"Invalid XML syntax: {e}")
        except Exception as e:
            logger.error(f"Error parsing XML: {e}")
            raise ValueError(f"Failed to parse XML: {str(e)}")

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        try:
            from lxml import etree
            etree.fromstring(file_content)
            return True, None
        except Exception as e:
            return False, f"Invalid XML: {e}"
