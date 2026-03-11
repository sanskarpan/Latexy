"""
LaTeX Parser - Passthrough parser for LaTeX files.
Since input is already in LaTeX format, this is a simple passthrough.
"""

import logging
from typing import Optional

from .base_parser import AbstractParser, ParsedResume

logger = logging.getLogger(__name__)


class LaTeXParser(AbstractParser):
    """Parser for LaTeX resume files (passthrough)."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        """
        Parse LaTeX file - essentially a passthrough since it's already in LaTeX.

        Args:
            file_content: Raw LaTeX file content
            filename: Original filename

        Returns:
            ParsedResume with raw_text containing the LaTeX content
        """
        try:
            # Decode content
            latex_content = file_content.decode('utf-8', errors='ignore')

            # Create ParsedResume with raw text
            # For LaTeX, we don't extract structured data since it's already formatted
            parsed_resume = ParsedResume(
                raw_text=latex_content,
                metadata={
                    "filename": filename,
                    "format": "latex",
                    "file_size": len(file_content),
                    "is_passthrough": True
                }
            )

            # Try to extract some basic info for better UX
            # (This is optional and can be enhanced)
            self._extract_basic_info(latex_content, parsed_resume)

            return parsed_resume

        except Exception as e:
            logger.error(f"Error parsing LaTeX file: {e}")
            raise ValueError(f"Failed to parse LaTeX file: {str(e)}")

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        """
        Validate LaTeX file content.

        Args:
            file_content: Raw file content

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            content = file_content.decode('utf-8', errors='ignore')

            # Check for basic LaTeX structure
            required_elements = [
                ('\\documentclass', 'Missing \\documentclass'),
                ('\\begin{document}', 'Missing \\begin{document}'),
                ('\\end{document}', 'Missing \\end{document}')
            ]

            for element, error_msg in required_elements:
                if element not in content:
                    return False, error_msg

            return True, None

        except UnicodeDecodeError:
            return False, "File is not valid UTF-8 text"
        except Exception as e:
            return False, f"Validation error: {str(e)}"

    @staticmethod
    def _extract_brace_content(text: str, cmd_end: int) -> str:
        """
        Extract the content of a LaTeX brace group starting at cmd_end.
        Handles nested braces correctly, e.g. \author{John {Jr.} Smith}.
        Returns the inner content string, or empty string if not found.
        """
        if cmd_end >= len(text) or text[cmd_end] != '{':
            return ''
        depth = 0
        start = cmd_end + 1
        for i in range(cmd_end, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i].strip()
        return ''

    def _extract_basic_info(self, latex_content: str, parsed_resume: ParsedResume):
        """
        Extract basic information from LaTeX for display purposes.
        This is optional and provides better UX.
        Uses brace-aware extraction to handle nested braces correctly.
        """
        try:
            # Try to extract author name if specified
            author_pos = latex_content.find('\\author{')
            if author_pos >= 0:
                name = self._extract_brace_content(latex_content, author_pos + len('\\author'))
                if name:
                    parsed_resume.contact.name = name

            # Try to extract title
            title_pos = latex_content.find('\\title{')
            if title_pos >= 0:
                title = self._extract_brace_content(latex_content, title_pos + len('\\title'))
                if title:
                    parsed_resume.metadata['document_title'] = title

        except Exception as e:
            logger.debug(f"Could not extract basic info from LaTeX: {e}")

    def get_latex_content(self, parsed_resume: ParsedResume) -> str:
        """
        Get LaTeX content from parsed resume.
        For LaTeX parser, this is just returning the raw_text.
        """
        return parsed_resume.raw_text or ""

