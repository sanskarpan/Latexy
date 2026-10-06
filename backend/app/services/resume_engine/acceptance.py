"""Authoritative candidate export receipt, separate from preview readiness."""

from datetime import datetime, timezone

from sqlalchemy import func, select

from ...database.models import JobFinalization, Resume, ResumeOptimizationRun
from .document import digest
from .stages import stage_fingerprint


def valid_run_result(result) -> bool:
    if not isinstance(result, dict):
        return False
    try:
        return result.get("result_sha256") == stage_fingerprint(
            {key: value for key, value in result.items() if key != "result_sha256"}
        )
    except (TypeError, ValueError):
        return False


async def is_candidate_export_accepted(db, run_id: str, user_id: str, source_sha256: str) -> bool:
    row = (
        await db.execute(
            select(ResumeOptimizationRun, Resume, JobFinalization)
            .join(Resume, Resume.id == ResumeOptimizationRun.resume_id)
            .join(JobFinalization, JobFinalization.job_id == ResumeOptimizationRun.job_id)
            .where(
                ResumeOptimizationRun.id == run_id, ResumeOptimizationRun.user_id == user_id, Resume.user_id == user_id
            )
            .where(JobFinalization.expires_at > func.clock_timestamp())
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if not row:
        return False
    run, resume, arbiter = row
    receipt = run.decisions or {}
    return (
        receipt.get("complete_acceptance") is True
        and valid_run_result(run.result)
        and arbiter.state == "completed"
        and not arbiter.cancel_requested
        and run.expires_at > datetime.now(timezone.utc)
        and run.status in {"completed", "partial"}
        and receipt.get("accepted_source_sha256") == source_sha256
        and (run.result or {}).get("candidate_source_sha256") == source_sha256
        and receipt.get("accepted_content_revision") == resume.content_revision
        and digest(resume.latex_content) == source_sha256
    )
