"""
LaTeX Parser - Passthrough parser for LaTeX files.
Since input is already in LaTeX format, this is a simple passthrough.
"""

from typing import Optional
from .base_parser import AbstractParser, ParsedResume
import logging

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
    
    def _extract_basic_info(self, latex_content: str, parsed_resume: ParsedResume):
        """
        Extract basic information from LaTeX for display purposes.
        This is optional and provides better UX.
        """
        try:
            # Try to extract author name if specified
            if '\\author{' in latex_content:
                start = latex_content.find('\\author{') + 8
                end = latex_content.find('}', start)
                if end > start:
                    name = latex_content[start:end].strip()
                    if name:
                        parsed_resume.contact.name = name
            
            # Try to extract title
            if '\\title{' in latex_content:
                start = latex_content.find('\\title{') + 7
                end = latex_content.find('}', start)
                if end > start:
                    title = latex_content[start:end].strip()
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

