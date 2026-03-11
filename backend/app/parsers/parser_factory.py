"""
Parser Factory - Creates appropriate parser based on file format.
"""

import logging
from typing import Optional

from ..services.format_detection import ResumeFormat, format_detection_service
from .base_parser import AbstractParser

logger = logging.getLogger(__name__)


class ParserFactory:
    """Factory for creating format-specific parsers."""

    def __init__(self):
        self._parsers = {}
        self._register_parsers()

    def _register_parsers(self):
        """Register all available parsers."""
        from .docx_parser import DOCXParser
        from .html_parser import HTMLParser
        from .image_parser import ImageParser
        from .json_parser import JSONParser
        from .latex_parser import LaTeXParser
        from .markdown_parser import MarkdownParser
        from .pdf_parser import PDFParser
        from .text_parser import TextParser
        from .toml_parser import TOMLParser
        from .xml_parser import XMLParser
        from .yaml_parser import YAMLParser

        self._parsers[ResumeFormat.LATEX] = LaTeXParser
        self._parsers[ResumeFormat.PDF] = PDFParser
        self._parsers[ResumeFormat.DOCX] = DOCXParser
        # NOTE: .doc (OLE2 binary) is distinct from .docx (ZIP/OOXML).
        # DOCXParser.validate() will reject OLE2 content with a clear error.
        # This mapping provides a best-effort attempt for modern .doc files that
        # are actually OOXML internally; true legacy OLE2 .doc will fail gracefully.
        self._parsers[ResumeFormat.DOC] = DOCXParser
        self._parsers[ResumeFormat.MARKDOWN] = MarkdownParser
        self._parsers[ResumeFormat.TEXT] = TextParser
        self._parsers[ResumeFormat.HTML] = HTMLParser
        self._parsers[ResumeFormat.JSON] = JSONParser
        self._parsers[ResumeFormat.YAML] = YAMLParser
        self._parsers[ResumeFormat.TOML] = TOMLParser
        self._parsers[ResumeFormat.XML] = XMLParser
        self._parsers[ResumeFormat.IMAGE] = ImageParser

        logger.info(f"Registered {len(self._parsers)} parsers: {list(self._parsers.keys())}")

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

