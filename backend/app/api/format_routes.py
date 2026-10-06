"""
Format Detection and Multi-Format Support API Routes
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.celery_app import get_task_priority
from ..core.logging import get_logger
from ..core.redis import get_redis_client
from ..database.connection import get_db
from ..database.models import User
from ..middleware.auth_middleware import get_current_user_optional
from ..parsers.parser_factory import parser_factory
from ..services.api_key_service import api_key_service
from ..services.document_converter_service import ALLOWED_SOURCE_PLATFORMS
from ..services.entitlement_service import entitlement_service
from ..services.format_detection import ResumeFormat, format_detection_service
from ..utils.file_utils import read_upload_capped
from ..workers.job_lifecycle import lifecycle_key

logger = get_logger(__name__)

router = APIRouter(prefix="/formats", tags=["formats"])

# Hard upper bound on any uploaded file, enforced BEFORE buffering the whole body
# into memory. Matches the largest per-format limit (PDF/image = 10 MB) so a single
# oversized upload to an unauthenticated endpoint cannot exhaust worker memory.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


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
        logger.error("Error getting supported formats (%s)", type(e).__name__)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/detect", response_model=DetectFormatResponse)
async def detect_file_format(file: UploadFile = File(...)):
    """
    Detect format of uploaded file.
    This endpoint doesn't parse the file, just detects its format.
    """
    try:
        # Read file content (capped to prevent OOM on unauthenticated endpoint)
        content = await read_upload_capped(file, _MAX_UPLOAD_BYTES)

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

    except HTTPException:
        raise
    except Exception as e:
        # Log the detailed exception server-side only; return a generic 500 so we
        # neither leak internals nor signal HTTP 200 on failure.
        logger.error("Error detecting format (%s)", type(e).__name__)
        raise HTTPException(status_code=500, detail="Internal server error")


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
        logger.error("Error getting format info (%s)", type(e).__name__)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/validate")
async def validate_file_format(file: UploadFile = File(...)):
    """
    Validate if file format is supported and can be processed.
    Returns detailed validation information.
    """
    try:
        # Read file content (capped to prevent OOM on unauthenticated endpoint)
        content = await read_upload_capped(file, _MAX_UPLOAD_BYTES)

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

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error validating file (%s)", type(e).__name__)
        raise HTTPException(status_code=500, detail="Internal server error")


class UploadForConversionResponse(BaseModel):
    """Response for file upload endpoint."""
    success: bool
    job_id: Optional[str] = None
    format: str
    filename: str
    is_direct: bool            # True = LaTeX passthrough or structured, no LLM needed
    latex_content: Optional[str] = None  # Only set when is_direct=True


class ParsePreviewResponse(BaseModel):
    """Lightweight parse-only response for wizard preview step."""
    success: bool
    format: str
    filename: str
    name: Optional[str] = None
    email: Optional[str] = None
    experience_count: int = 0
    education_count: int = 0
    skills: List[str] = []
    has_summary: bool = False


@router.post("/parse", response_model=ParsePreviewResponse)
async def parse_for_preview(file: UploadFile = File(...)):
    """
    Parse a resume file and return basic structured preview data.
    No LLM conversion — used by the import wizard to confirm content before converting.
    """
    try:
        content = await read_upload_capped(file, _MAX_UPLOAD_BYTES)
        filename = file.filename or "upload"

        detected_format = format_detection_service.detect_format(
            filename=filename, mime_type=file.content_type, content=content
        )
        if detected_format == ResumeFormat.UNKNOWN:
            raise HTTPException(status_code=415, detail=f"Unsupported file format: '{filename}'")

        is_valid_size, size_error = format_detection_service.validate_file_size(len(content), detected_format)
        if not is_valid_size:
            raise HTTPException(status_code=413, detail=size_error)

        parser = parser_factory.get_parser(detected_format)
        if not parser:
            raise HTTPException(status_code=415, detail=f"No parser for {detected_format.value}")

        try:
            parsed = await parser.parse(content, filename)
        except ValueError as ve:
            raise HTTPException(status_code=422, detail="Could not parse the uploaded file.") from ve

        contact = parsed.contact or {}
        return ParsePreviewResponse(
            success=True,
            format=detected_format.value,
            filename=filename,
            name=getattr(contact, "name", None) or (contact.get("name") if isinstance(contact, dict) else None),
            email=getattr(contact, "email", None) or (contact.get("email") if isinstance(contact, dict) else None),
            experience_count=len(parsed.experience or []),
            education_count=len(parsed.education or []),
            skills=(parsed.skills or [])[:10],
            has_summary=bool(parsed.summary),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error in parse_for_preview (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/upload", response_model=UploadForConversionResponse)
async def upload_for_conversion(
    file: UploadFile = File(...),
    source_hint: Optional[str] = Form(default=None),
    source_platform: Optional[str] = Query(default=None),
    user_id: Optional[str] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a resume file in any supported format.

    - LaTeX files (.tex/.latex/.ltx): returned directly (no conversion, no auth)
    - All other formats: queued as an LLM conversion job (requires authentication;
      the paid conversion is billed to the user's BYOK key when available).
    """
    try:
        # Validate source_platform early — unknown values are silently ignored (fall back to generic)
        if source_platform and source_platform not in ALLOWED_SOURCE_PLATFORMS:
            logger.warning(f"Unknown source_platform '{source_platform}'; ignoring")
            source_platform = None

        content = await read_upload_capped(file, _MAX_UPLOAD_BYTES)
        filename = file.filename or "upload"

        # Detect format
        detected_format = format_detection_service.detect_format(
            filename=filename,
            mime_type=file.content_type,
            content=content,
        )

        if detected_format == ResumeFormat.UNKNOWN:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file format. Could not detect format from '{filename}'",
            )

        # Validate file size
        is_valid_size, size_error = format_detection_service.validate_file_size(
            len(content), detected_format
        )
        if not is_valid_size:
            raise HTTPException(status_code=413, detail=size_error)

        # Get parser
        parser = parser_factory.get_parser(detected_format)
        if not parser:
            raise HTTPException(
                status_code=415,
                detail=f"No parser available for {detected_format.value} format",
            )

        # Parse the file (sync extraction, fast)
        try:
            parsed = await parser.parse(content, filename)
        except ValueError as ve:
            raise HTTPException(status_code=422, detail="Could not parse the uploaded file.") from ve

        # LaTeX passthrough — return content directly
        if detected_format == ResumeFormat.LATEX:
            return UploadForConversionResponse(
                success=True,
                format="latex",
                filename=filename,
                is_direct=True,
                latex_content=parsed.raw_text,
            )

        # Everything below consumes an LLM call — require authentication so
        # anonymous clients cannot force unlimited conversions billed to the
        # platform OpenAI key.
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Authentication required to convert this file format.",
            )

        # Resolve the user's plan (for queue priority) and BYOK key (so the
        # conversion is billed to the user's key when they have one).
        user_plan = "free"
        plan_result = await db.execute(
            select(User.subscription_plan).where(User.id == user_id)
        )
        stored_plan = plan_result.scalar_one_or_none()
        if isinstance(stored_plan, str) and stored_plan:
            user_plan = stored_plan

        user_api_key = None
        try:
            user_api_key = await api_key_service.get_user_provider(db, user_id, "openai")
        except Exception:
            user_api_key = None

        # The conversion burns an LLM call on the PLATFORM key, so it spends the
        # plan's ai_assists allowance. Charged here — after every validation has
        # passed and before the job is queued — and refunded if the enqueue
        # fails. A BYOK caller pays their own provider, so nothing is charged.
        job_id = str(uuid.uuid4())
        from ..api.job_routes import _new_finalization_row

        finalization_record = _new_finalization_row(job_id, "document_conversion", user_id, {})
        db.add(finalization_record)
        await db.commit()
        quota_ticket = None
        if not user_api_key:
            try:
                quota_ticket = await entitlement_service.enforce_quota(
                    "ai_assists", user_id=user_id, plan=user_plan, job_id=job_id
                )
            except Exception:
                await db.delete(finalization_record)
                await db.commit()
                raise

        # Queue LLM conversion job
        from ..api.job_routes import (
            _delete_initial_redis_state,
            _mark_dispatch_accepted,
            _mark_dispatch_started,
            _write_initial_redis_state,
        )
        from ..workers.converter_worker import submit_document_conversion

        estimated_seconds = 45
        dispatch_attempted = False
        try:
            await _write_initial_redis_state(job_id, "document_conversion", user_id, estimated_seconds)
            await _mark_dispatch_started(job_id)
            # Set this only immediately before the external broker/Modal call;
            # lifecycle initialization itself is still pre-dispatch.
            dispatch_attempted = True

            submit_document_conversion(
                extracted_data=parsed.to_dict(),
                source_format=detected_format.value,
                job_id=job_id,
                user_id=user_id,
                user_api_key=user_api_key,
                source_hint=source_hint,
                source_platform=source_platform,
                priority=get_task_priority(user_plan),
                quota_refund=quota_ticket.refund_payload() if quota_ticket else None,
            )
            await _mark_dispatch_accepted(job_id)
        except Exception:
            if dispatch_attempted:
                # A broker/Modal response can be lost after work was accepted;
                # preserve the job for worker/cleanup reconciliation.
                logger.error("Ambiguous document conversion dispatch for job %s", job_id, exc_info=True)
                return UploadForConversionResponse(
                    success=True,
                    job_id=job_id,
                    format=detected_format.value,
                    filename=filename,
                    is_direct=False,
                )
            if quota_ticket is not None:
                await entitlement_service.refund_quota(quota_ticket)
            try:
                await db.delete(finalization_record)
                await db.commit()
            except Exception:
                await db.rollback()
            try:
                redis = await get_redis_client()
                await redis.delete(lifecycle_key(job_id))
                await _delete_initial_redis_state(job_id, user_id)
            except Exception:
                logger.warning("Failed to clean undispatched conversion %s", job_id, exc_info=True)
            raise

        logger.info("Queued document conversion job %s (%s)", job_id, detected_format.value)
        return UploadForConversionResponse(
            success=True,
            job_id=job_id,
            format=detected_format.value,
            filename=filename,
            is_direct=False,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error in upload_for_conversion (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Internal server error")
