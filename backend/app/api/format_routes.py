"""
Format Detection and Multi-Format Support API Routes
"""

from typing import List, Dict
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from ..services.format_detection import format_detection_service, ResumeFormat
from ..parsers.parser_factory import parser_factory
from ..core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/formats", tags=["formats"])


class FormatInfo(BaseModel):
    """Format information response."""
    format: str
    extensions: List[str]
    mime_types: List[str]
    max_size_mb: float
    supported: bool


class DetectFormatResponse(BaseModel):
    """Format detection response."""
    success: bool
    detected_format: str
    confidence: str
    is_supported: bool
    error: str | None = None


class SupportedFormatsResponse(BaseModel):
    """Supported formats list response."""
    formats: List[FormatInfo]
    total_count: int


@router.get("/supported", response_model=SupportedFormatsResponse)
async def get_supported_formats():
    """Get list of all supported resume formats."""
    try:
        supported_format_types = parser_factory.get_supported_formats()
        formats_info = format_detection_service.get_supported_formats()
        
        # Mark which formats have parsers
        for format_info in formats_info:
            format_type = ResumeFormat(format_info["format"])
            format_info["supported"] = format_type in supported_format_types
        
        return SupportedFormatsResponse(
            formats=[FormatInfo(**info) for info in formats_info],
            total_count=len(formats_info)
        )
    except Exception as e:
        logger.error(f"Error getting supported formats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/detect", response_model=DetectFormatResponse)
async def detect_file_format(file: UploadFile = File(...)):
    """
    Detect format of uploaded file.
    This endpoint doesn't parse the file, just detects its format.
    """
    try:
        # Read file content
        content = await file.read()
        
        # Detect format
        detected_format = format_detection_service.detect_format(
            filename=file.filename or "",
            mime_type=file.content_type,
            content=content
        )
        
        # Check if format is supported (has a parser)
        is_supported = parser_factory.is_format_supported(detected_format)
        
        # Validate file size
        is_valid_size, size_error = format_detection_service.validate_file_size(
            len(content), detected_format
        )
        
        # Determine confidence based on detection method
        confidence = "high"  # Default
        if detected_format == ResumeFormat.UNKNOWN:
            confidence = "none"
        elif not content:
            confidence = "low"
        
        return DetectFormatResponse(
            success=detected_format != ResumeFormat.UNKNOWN,
            detected_format=detected_format.value,
            confidence=confidence,
            is_supported=is_supported,
            error=size_error if not is_valid_size else None
        )
        
    except Exception as e:
        logger.error(f"Error detecting format: {e}")
        return DetectFormatResponse(
            success=False,
            detected_format="unknown",
            confidence="none",
            is_supported=False,
            error=str(e)
        )


@router.get("/info/{format_name}", response_model=FormatInfo)
async def get_format_info(format_name: str):
    """Get detailed information about a specific format."""
    try:
        # Convert string to enum
        try:
            format_type = ResumeFormat(format_name.lower())
        except ValueError:
            raise HTTPException(
                status_code=404,
                detail=f"Format '{format_name}' not recognized"
            )
        
        # Get format info
        info = format_detection_service.get_format_info(format_type)
        
        if not info:
            raise HTTPException(
                status_code=404,
                detail=f"No information available for format '{format_name}'"
            )
        
        # Check if format has a parser
        info["supported"] = parser_factory.is_format_supported(format_type)
        
        return FormatInfo(**info)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting format info: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/validate")
async def validate_file_format(file: UploadFile = File(...)):
    """
    Validate if file format is supported and can be processed.
    Returns detailed validation information.
    """
    try:
        # Read file content
        content = await file.read()
        
        # Detect format
        detected_format = format_detection_service.detect_format(
            filename=file.filename or "",
            mime_type=file.content_type,
            content=content
        )
        
        # Validate format is supported
        is_supported = format_detection_service.validate_format(detected_format)
        
        # Check if parser exists
        has_parser = parser_factory.is_format_supported(detected_format)
        
        # Validate file size
        is_valid_size, size_error = format_detection_service.validate_file_size(
            len(content), detected_format
        )
        
        # Try to get parser and validate content
        content_valid = False
        content_error = None
        
        if has_parser:
            parser = parser_factory.get_parser(detected_format)
            if parser:
                content_valid, content_error = parser.validate(content)
        
        # Overall validation
        is_valid = (
            is_supported and
            has_parser and
            is_valid_size and
            content_valid
        )
        
        errors = []
        if not is_supported:
            errors.append(f"Format '{detected_format.value}' is not supported")
        if not has_parser:
            errors.append(f"No parser available for '{detected_format.value}' format")
        if size_error:
            errors.append(size_error)
        if content_error:
            errors.append(content_error)
        
        return {
            "valid": is_valid,
            "format": detected_format.value,
            "checks": {
                "format_supported": is_supported,
                "parser_available": has_parser,
                "size_valid": is_valid_size,
                "content_valid": content_valid
            },
            "errors": errors if errors else None,
            "file_info": {
                "filename": file.filename,
                "size_bytes": len(content),
                "size_mb": round(len(content) / (1024 * 1024), 2),
                "mime_type": file.content_type
            }
        }
        
    except Exception as e:
        logger.error(f"Error validating file: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

