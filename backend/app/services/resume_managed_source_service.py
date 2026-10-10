"""Shared save-token bookkeeping for managed semantic document writers."""

from datetime import datetime, timezone

from ..database.models import Resume
from .resume_source_service import invalidate_anonymous_share_pdf


def apply_managed_document_change(
    resume: Resume, latex_content: str, structured_content: dict, *, previous_structured: dict
) -> bool:
    """Apply an actual managed mutation under the caller's resume-row lock.

    Compare with the projected pre-mutation snapshot, which may materialize
    defaults absent from older stored JSON. A semantic no-op must not persist
    those defaults or advance either revision. Managed writers keep their
    builder attachment, but invalidate stale builder saves exactly once.
    """
    source_changed = latex_content != resume.latex_content
    if not source_changed and structured_content == previous_structured:
        return False
    if source_changed:
        invalidate_anonymous_share_pdf(resume)
    resume.latex_content = latex_content
    resume.structured_content = structured_content
    resume.structured_version = (resume.structured_version or 1) + 1
    resume.updated_at = datetime.now(timezone.utc)
    return True
