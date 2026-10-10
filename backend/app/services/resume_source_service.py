"""Explicit bookkeeping for authoritative non-builder source mutations."""

from datetime import datetime, timezone

from sqlalchemy.orm.attributes import flag_modified

from ..database.models import Resume


def invalidate_anonymous_share_pdf(resume: Resume) -> None:
    metadata = dict(resume.resume_settings or {})
    had_cached_share = "share_anonymous_job_id" in metadata or "share_anonymous_pending" in metadata
    metadata.pop("share_anonymous_job_id", None)
    metadata.pop("share_anonymous_pending", None)
    if had_cached_share:
        resume.resume_settings = metadata
        flag_modified(resume, "resume_settings")


def apply_source_change(resume: Resume, latex_content: str) -> bool:
    """Apply changed source under the caller's resume-row lock/transaction.

    External source writers cannot keep claiming their LaTeX matches the old
    structured builder data. Preserve that data for explicit reattachment, but
    stop builder saves and linked-variant regeneration from overwriting source.
    Identical source/replays intentionally leave builder state and caches alone.
    """
    if latex_content == resume.latex_content:
        return False
    if resume.content_source in {"builder", "builder_variant"} or (
        resume.selected_template_id and resume.structured_content
    ):
        resume.builder_status = "detached"
        resume.content_source = "manual_latex"
        resume.variant_visibility = None
    invalidate_anonymous_share_pdf(resume)
    resume.latex_content = latex_content
    resume.updated_at = datetime.now(timezone.utc)
    return True
