"""
Parser Factory - Creates appropriate parser based on file format.
"""

from typing import Optional
import logging

from .base_parser import AbstractParser
from ..services.format_detection import ResumeFormat, format_detection_service

logger = logging.getLogger(__name__)


class ParserFactory:
    """Factory for creating format-specific parsers."""
    
    def __init__(self):
        self._parsers = {}
        self._register_parsers()
    
    def _register_parsers(self):
        """Register all available parsers."""
        # Lazy import to avoid circular dependencies
        
        # LaTeX parser (passthrough - already in LaTeX format)
        from .latex_parser import LaTeXParser
        self._parsers[ResumeFormat.LATEX] = LaTeXParser
        
        # PDF parser (Phase 15)
        # from .pdf_parser import PDFParser
        # self._parsers[ResumeFormat.PDF] = PDFParser
        
        # DOCX parser (Phase 15)
        # from .docx_parser import DOCXParser
        # self._parsers[ResumeFormat.DOCX] = DOCXParser
        
        # Markdown parser (Phase 16)
        # from .markdown_parser import MarkdownParser
        # self._parsers[ResumeFormat.MARKDOWN] = MarkdownParser
        
        # Text parser (Phase 16)
        # from .text_parser import TextParser
        # self._parsers[ResumeFormat.TEXT] = TextParser
        
        # HTML parser (Phase 16)
        # from .html_parser import HTMLParser
        # self._parsers[ResumeFormat.HTML] = HTMLParser
        
        # JSON parser (Phase 17)
        # from .json_parser import JSONParser
        # self._parsers[ResumeFormat.JSON] = JSONParser
        
        # YAML parser (Phase 17)
        # from .yaml_parser import YAMLParser
        # self._parsers[ResumeFormat.YAML] = YAMLParser
        
        logger.info(f"Registered {len(self._parsers)} parsers")
    
    def get_parser(self, format_type: ResumeFormat) -> Optional[AbstractParser]:
        """
        Get parser instance for given format.
        
        Args:
            format_type: The resume format
            
        Returns:
            Parser instance or None if not supported
        """
        if format_type not in self._parsers:
            logger.warning(f"No parser registered for format: {format_type.value}")
            return None
        
        parser_class = self._parsers[format_type]
        return parser_class()
    
    def get_parser_for_file(self, filename: str, mime_type: Optional[str] = None,
                           content: Optional[bytes] = None) -> Optional[AbstractParser]:
        """
        Detect format and get appropriate parser.
        
        Args:
            filename: File name
            mime_type: Optional MIME type
            content: Optional file content for better detection
            
        Returns:
            Parser instance or None if format not supported
        """
        format_type = format_detection_service.detect_format(filename, mime_type, content)
        
        if format_type == ResumeFormat.UNKNOWN:
            logger.error(f"Could not detect format for file: {filename}")
            return None
        
        return self.get_parser(format_type)
    
    def is_format_supported(self, format_type: ResumeFormat) -> bool:
        """Check if format has a registered parser."""
        return format_type in self._parsers
    
    def get_supported_formats(self) -> list[ResumeFormat]:
        """Get list of supported formats."""
        return list(self._parsers.keys())


# Global factory instance
parser_factory = ParserFactory()

