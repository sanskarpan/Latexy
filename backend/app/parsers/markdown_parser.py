"""
Markdown Parser - Parse Markdown and MDX resume files.
"""
import logging
import re
from typing import Optional

from .base_parser import AbstractParser, ParsedResume

logger = logging.getLogger(__name__)


class MarkdownParser(AbstractParser):
    """Parser for Markdown (.md) and MDX (.mdx) resume files."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        try:
            text = file_content.decode('utf-8', errors='ignore')

            # Strip MDX JSX components (self-closing and paired)
            text = re.sub(r'<[A-Z][a-zA-Z0-9]*[^>]*/>', '', text)
            text = re.sub(r'<[A-Z][a-zA-Z0-9]*[^>]*>.*?</[A-Z][a-zA-Z0-9]*>', '', text, flags=re.DOTALL)
            # Strip import/export statements from MDX
            text = re.sub(r'^(?:import|export)\s+.*?;?\s*$', '', text, flags=re.MULTILINE)

            # Extract headers as section hints
            headers = re.findall(r'^#{1,3}\s+(.+)$', text, re.MULTILINE)

            # Convert markdown to plain text
            # Remove header markers
            plain = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
            # Remove bold/italic
            plain = re.sub(r'\*\*(.+?)\*\*', r'\1', plain)
            plain = re.sub(r'__(.+?)__', r'\1', plain)
            plain = re.sub(r'\*(.+?)\*', r'\1', plain)
            plain = re.sub(r'_(.+?)_', r'\1', plain)
            # Convert links to text
            plain = re.sub(r'\[(.+?)\]\([^\)]+\)', r'\1', plain)
            # Remove code blocks
            plain = re.sub(r'```.*?```', '', plain, flags=re.DOTALL)
            plain = re.sub(r'`([^`]+)`', r'\1', plain)
            # Remove horizontal rules
            plain = re.sub(r'^[-*_]{3,}\s*$', '', plain, flags=re.MULTILINE)
            # Clean up
            plain = re.sub(r'\n{3,}', '\n\n', plain).strip()

            if not plain.strip():
                raise ValueError("Could not extract text from Markdown file")

            return self._build_parsed_resume(plain, filename, section_hints=headers)

        except Exception as e:
            logger.error(f"Error parsing Markdown: {e}")
            raise ValueError(f"Failed to parse Markdown: {str(e)}")

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        try:
            content = file_content.decode('utf-8', errors='ignore')
            if not content.strip():
                return False, "File is empty"
            return True, None
        except Exception as e:
            return False, str(e)
