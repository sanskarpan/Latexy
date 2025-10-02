"""
Format Detection Service for Multi-Format Resume Upload
Detects and validates various resume file formats.
"""

import mimetypes
from typing import Optional, Dict
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ResumeFormat(Enum):
    """Supported resume formats."""
    LATEX = "latex"
    PDF = "pdf"
    DOCX = "docx"
    DOC = "doc"
    MARKDOWN = "markdown"
    TEXT = "text"
    HTML = "html"
    JSON = "json"
    YAML = "yaml"
    UNKNOWN = "unknown"


class FormatDetectionService:
    """Service for detecting and validating resume file formats."""
    
    # Format configurations
    FORMAT_CONFIG = {
        ResumeFormat.LATEX: {
            "extensions": [".tex", ".latex"],
            "mime_types": ["text/x-tex", "application/x-tex", "application/x-latex"],
            "max_size": 2 * 1024 * 1024,  # 2 MB
            "magic_bytes": None
        },
        ResumeFormat.PDF: {
            "extensions": [".pdf"],
            "mime_types": ["application/pdf"],
            "max_size": 10 * 1024 * 1024,  # 10 MB
            "magic_bytes": b"%PDF"
        },
        ResumeFormat.DOCX: {
            "extensions": [".docx"],
            "mime_types": [
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ],
            "max_size": 5 * 1024 * 1024,  # 5 MB
            "magic_bytes": b"PK"  # ZIP archive
        },
        ResumeFormat.DOC: {
            "extensions": [".doc"],
            "mime_types": ["application/msword"],
            "max_size": 5 * 1024 * 1024,  # 5 MB
            "magic_bytes": b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"  # OLE2
        },
        ResumeFormat.MARKDOWN: {
            "extensions": [".md", ".markdown"],
            "mime_types": ["text/markdown", "text/x-markdown"],
            "max_size": 1 * 1024 * 1024,  # 1 MB
            "magic_bytes": None
        },
        ResumeFormat.TEXT: {
            "extensions": [".txt", ".text"],
            "mime_types": ["text/plain"],
            "max_size": 1 * 1024 * 1024,  # 1 MB
            "magic_bytes": None
        },
        ResumeFormat.HTML: {
            "extensions": [".html", ".htm"],
            "mime_types": ["text/html", "application/xhtml+xml"],
            "max_size": 2 * 1024 * 1024,  # 2 MB
            "magic_bytes": None
        },
        ResumeFormat.JSON: {
            "extensions": [".json"],
            "mime_types": ["application/json"],
            "max_size": 1 * 1024 * 1024,  # 1 MB
            "magic_bytes": b"{"
        },
        ResumeFormat.YAML: {
            "extensions": [".yaml", ".yml"],
            "mime_types": ["text/yaml", "application/x-yaml", "text/x-yaml"],
            "max_size": 1 * 1024 * 1024,  # 1 MB
            "magic_bytes": None
        }
    }
    
    def detect_format_from_filename(self, filename: str) -> ResumeFormat:
        """Detect format based on file extension."""
        if not filename:
            return ResumeFormat.UNKNOWN
        
        filename_lower = filename.lower()
        
        for format_type, config in self.FORMAT_CONFIG.items():
            for ext in config["extensions"]:
                if filename_lower.endswith(ext):
                    logger.info(f"Detected format {format_type.value} from extension {ext}")
                    return format_type
        
        return ResumeFormat.UNKNOWN
    
    def detect_format_from_mime(self, mime_type: str) -> ResumeFormat:
        """Detect format based on MIME type."""
        if not mime_type:
            return ResumeFormat.UNKNOWN
        
        mime_lower = mime_type.lower()
        
        for format_type, config in self.FORMAT_CONFIG.items():
            if mime_lower in [m.lower() for m in config["mime_types"]]:
                logger.info(f"Detected format {format_type.value} from MIME type {mime_type}")
                return format_type
        
        return ResumeFormat.UNKNOWN
    
    def detect_format_from_content(self, content: bytes, filename: str = "") -> ResumeFormat:
        """Detect format based on magic bytes in content."""
        if not content:
            return ResumeFormat.UNKNOWN
        
        # Check magic bytes
        for format_type, config in self.FORMAT_CONFIG.items():
            if config["magic_bytes"]:
                if content.startswith(config["magic_bytes"]):
                    logger.info(f"Detected format {format_type.value} from magic bytes")
                    return format_type
        
        # Fallback to filename detection
        if filename:
            return self.detect_format_from_filename(filename)
        
        # Try to detect text-based formats by content analysis
        try:
            text_content = content.decode('utf-8', errors='ignore')[:1000]
            
            # Check for LaTeX
            if '\\documentclass' in text_content or '\\begin{document}' in text_content:
                return ResumeFormat.LATEX
            
            # Check for HTML
            if '<html' in text_content.lower() or '<!doctype html' in text_content.lower():
                return ResumeFormat.HTML
            
            # Check for Markdown (headers)
            if text_content.startswith('#') or '\n#' in text_content[:200]:
                return ResumeFormat.MARKDOWN
            
            # Check for JSON
            text_stripped = text_content.strip()
            if text_stripped.startswith('{') and '"' in text_stripped:
                return ResumeFormat.JSON
            
            # Check for YAML
            if ':' in text_content and ('\n' in text_content[:100]):
                # Simple heuristic: YAML typically has key: value format
                lines = text_content.split('\n')[:5]
                yaml_like = sum(1 for line in lines if ':' in line and not line.strip().startswith('#'))
                if yaml_like >= 2:
                    return ResumeFormat.YAML
            
        except Exception as e:
            logger.warning(f"Error in content-based detection: {e}")
        
        return ResumeFormat.UNKNOWN
    
    def detect_format(self, filename: str, mime_type: Optional[str] = None, 
                     content: Optional[bytes] = None) -> ResumeFormat:
        """
        Detect format using multiple detection methods.
        Priority: magic bytes > MIME type > file extension > content analysis
        """
        # Try content-based detection first (most reliable)
        if content:
            format_from_content = self.detect_format_from_content(content, filename)
            if format_from_content != ResumeFormat.UNKNOWN:
                return format_from_content
        
        # Try MIME type
        if mime_type:
            format_from_mime = self.detect_format_from_mime(mime_type)
            if format_from_mime != ResumeFormat.UNKNOWN:
                return format_from_mime
        
        # Fallback to extension
        format_from_filename = self.detect_format_from_filename(filename)
        if format_from_filename != ResumeFormat.UNKNOWN:
            return format_from_filename
        
        logger.warning(f"Could not detect format for {filename}")
        return ResumeFormat.UNKNOWN
    
    def validate_format(self, format_type: ResumeFormat) -> bool:
        """Check if format is supported."""
        return format_type in self.FORMAT_CONFIG and format_type != ResumeFormat.UNKNOWN
    
    def validate_file_size(self, file_size: int, format_type: ResumeFormat) -> tuple[bool, Optional[str]]:
        """Validate file size for given format."""
        if format_type not in self.FORMAT_CONFIG:
            return False, "Unsupported format"
        
        max_size = self.FORMAT_CONFIG[format_type]["max_size"]
        
        if file_size > max_size:
            max_size_mb = max_size / (1024 * 1024)
            return False, f"File size exceeds maximum allowed size of {max_size_mb}MB for {format_type.value} files"
        
        return True, None
    
    def get_format_info(self, format_type: ResumeFormat) -> Dict:
        """Get configuration information for a format."""
        if format_type not in self.FORMAT_CONFIG:
            return {}
        
        config = self.FORMAT_CONFIG[format_type]
        return {
            "format": format_type.value,
            "extensions": config["extensions"],
            "mime_types": config["mime_types"],
            "max_size_mb": config["max_size"] / (1024 * 1024),
            "max_size_bytes": config["max_size"]
        }
    
    def get_supported_formats(self) -> list[Dict]:
        """Get list of all supported formats with their info."""
        return [
            self.get_format_info(format_type)
            for format_type in self.FORMAT_CONFIG.keys()
            if format_type != ResumeFormat.UNKNOWN
        ]
    
    def is_text_based(self, format_type: ResumeFormat) -> bool:
        """Check if format is text-based (can be directly edited)."""
        return format_type in [
            ResumeFormat.LATEX,
            ResumeFormat.MARKDOWN,
            ResumeFormat.TEXT,
            ResumeFormat.HTML,
            ResumeFormat.JSON,
            ResumeFormat.YAML
        ]
    
    def requires_parsing(self, format_type: ResumeFormat) -> bool:
        """Check if format requires special parsing (not LaTeX)."""
        return format_type != ResumeFormat.LATEX


# Global instance
format_detection_service = FormatDetectionService()

