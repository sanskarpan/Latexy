"""GitHub project-import worker (Feature 1 — external sources to resume).

Runs the fetch → rank → (README + languages per top repo) → summarize → evidence
pipeline as an async job, publishes progress events, and stores the resulting
candidate ``ProjectEvidence`` list in Redis for the frontend to review.

PRIVACY: only PUBLIC repository data is read (see github_projects_service).

Runs on the 'llm' queue (the work is LLM-bound). On Modal there is no Celery
worker, so ``submit_github_import`` routes to the ``run_github_import_task``
Modal function instead of enqueueing to a broker with no consumer.
"""

import asyncio
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
from celery.exceptions import SoftTimeLimitExceeded

from ..core.celery_app import celery_app, get_task_priority
from ..core.logging import get_logger
from ..services import github_projects_service as gh
from ..workers.event_publisher import (
    get_worker_redis,
    is_cancelled,
    publish_event,
    publish_owned_result,
)
from ..workers.job_lifecycle import admit_worker, clear_current_owner, stop_lease_heartbeat
from ..workers.quota_refund import clear_quota_refund_receipt, refund_quota_once

logger = get_logger(__name__)


async def _resolve_import_credentials(
    user_id: str,
    session_factory=None,
) -> tuple[Optional[str], Optional[str]]:
    """Decrypt current credentials only inside the worker execution boundary."""
    from sqlalchemy import select

    from ..database.models import User, UserAPIKey
    from ..services.api_key_service import api_key_service
    from ..services.encryption_service import encryption_service

    engine = None
    if session_factory is None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from ..core.config import settings
        from ..utils.db_url import normalize_database_url

        if not settings.DATABASE_URL:
            raise RuntimeError("Database is unavailable for credential resolution")
        engine = create_async_engine(normalize_database_url(settings.DATABASE_URL), echo=False)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as db:
            encrypted_github_token = await db.scalar(
                select(User.github_access_token).where(User.id == user_id)
            )
            if not encrypted_github_token:
                return None, None
            github_token = encryption_service.decrypt(encrypted_github_token)

            byok_result = await db.execute(
                select(UserAPIKey.encrypted_key)
                .where(
                    UserAPIKey.user_id == user_id,
                    UserAPIKey.provider == "openai",
                    UserAPIKey.is_active,
                )
                .order_by(UserAPIKey.created_at.desc())
                .limit(1)
            )
            encrypted_api_key = byok_result.scalar_one_or_none()
            api_key = None
            if encrypted_api_key:
                try:
                    api_key = api_key_service.encryption.decrypt(encrypted_api_key)
                except Exception:
                    # A broken/revoked BYOK key must not prevent the documented
                    # platform-key fallback from serving the import.
                    logger.warning(
                        "Could not decrypt OpenAI BYOK key for GitHub import user %s; using platform fallback",
                        user_id,
                    )
            return github_token, api_key
    finally:
        if engine is not None:
            await engine.dispose()


def _store_result(
    job_id: str,
    user_id: str,
    payload: Dict[str, Any],
    *,
    owner: Optional[str] = None,
    terminal_status: Optional[str] = None,
) -> bool:
    """Persist an import result, fenced to the admitted worker when metered."""
    owned_payload = {**payload, "user_id": user_id}
    resolved_status = terminal_status or (
        "completed" if payload.get("status") == "completed" else "failed"
    )
    # The custom import envelope historically used ``status`` without the
    # canonical success flag. The shared arbiter requires an explicit success
    # decision before accepting a completed terminal write.
    owned_payload.setdefault("success", resolved_status == "completed")
    # The shared helper permits a direct write only when no lifecycle exists;
    # even a malformed/missing metering payload cannot bypass an existing
    # metered lifecycle without an owner and an unexpired lease.
    return publish_owned_result(
        job_id,
        gh.import_result_key(job_id),
        owned_payload,
        terminal_status=resolved_status,
        ttl=gh.IMPORT_RESULT_TTL,
        serialized_result=gh.encode_result(owned_payload),
    )


@celery_app.task(
    bind=True,
    name="app.workers.github_import_worker.import_github_projects_task",
    max_retries=1,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=270,
    queue="llm",
)
def import_github_projects_task(
    self,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    quota_refund: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Import + summarize a user's top public GitHub projects.

    Current credentials are loaded from the database and decrypted here, never
    serialized into the Celery/Modal payload.

    Publishes: job.started, job.progress (per stage), job.completed / job.failed.
    Stores the result at ``latexy:github_import:{job_id}``.
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    def _terminal_failure(
        result: Dict[str, Any],
        *,
        terminal_accepted: bool = False,
    ) -> Dict[str, Any]:
        # Refund only an accepted failed/cancelled terminal result.  A rejected
        # result means this worker lost its fence; cleanup owns reconciliation
        # and must not race it with a refund.  Completed custom-key results are
        # never refunded, even when their completion event was rejected.
        if terminal_accepted:
            refund_quota_once(
                job_id,
                quota_refund,
                expected_dimension="ai_assists",
            )
        return result

    if not user_id:
        logger.error("Refusing ownerless GitHub import job %s", job_id)
        return {"success": False, "job_id": job_id, "error": "user_id is required"}

    task_id = self.request.id
    worker_id = f"github-import-{task_id}"
    lifecycle_owner = f"{worker_id}:{uuid.uuid4()}"
    queue_redis = get_worker_redis()
    if not admit_worker(queue_redis, job_id, lifecycle_owner, quota_refund, user_id):
        # A duplicate delivery must not refund the receipt while the admitted
        # owner may still be running. Cleanup or that owner owns the eventual
        # terminal/refund decision.
        return {
            "success": False,
            "job_id": job_id,
            "error": "Job ownership unavailable",
            }
    def _release_owner() -> None:
        stop_lease_heartbeat(job_id)
        clear_current_owner(job_id)

    logger.info(f"GitHub import task {task_id} starting for job {job_id}")

    def _cancelled_result(projects: List[Dict[str, Any]]) -> Dict[str, Any]:
        result = {"success": False, "job_id": job_id, "cancelled": True}
        stored = _store_result(
            job_id,
            user_id,
            {"status": "failed", "projects": projects, "error": "cancelled"},
            owner=lifecycle_owner if quota_refund else None,
            terminal_status="cancelled",
        )
        if stored:
            try:
                publish_event(job_id, "job.cancelled", {})
            finally:
                _terminal_failure(result, terminal_accepted=True)
            return result
        return _terminal_failure(result, terminal_accepted=stored)

    try:
        publish_event(
            job_id,
            "job.started",
            {"worker_id": worker_id, "stage": "github_import"},
        )
    except Exception:
        _release_owner()
        raise

    # One HTTP client for every GitHub call → serial requests keep us clear of
    # GitHub's secondary rate limits.
    client = None
    try:
        github_token, api_key = asyncio.run(_resolve_import_credentials(user_id))
        if not github_token:
            stored = _store_result(
                job_id,
                user_id,
                {"status": "failed", "projects": [], "error": "GitHub not connected"},
                owner=lifecycle_owner if quota_refund else None,
            )
            if stored:
                try:
                    publish_event(
                        job_id,
                        "job.failed",
                        {
                            "stage": "github_import",
                            "error_code": "github_not_connected",
                            "error_message": "No GitHub token available for this import.",
                            "retryable": False,
                        },
                    )
                finally:
                    _terminal_failure(
                        {"success": False, "job_id": job_id, "error": "GitHub not connected"},
                        terminal_accepted=True,
                    )
                return {"success": False, "job_id": job_id, "error": "GitHub not connected"}
            return _terminal_failure(
                {"success": False, "job_id": job_id, "error": "GitHub not connected"},
                terminal_accepted=stored,
            )

        client = httpx.Client(timeout=20)
        publish_event(
            job_id,
            "job.progress",
            {
                "percent": 10,
                "stage": "github_import",
                "message": "Fetching your GitHub projects",
            },
        )
        candidates = gh.fetch_candidate_repos(github_token, client=client)

        publish_event(
            job_id,
            "job.progress",
            {
                "percent": 25,
                "stage": "github_import",
                "message": "Ranking your top projects",
            },
        )
        top = gh.rank_repos(candidates)

        if not top:
            stored = _store_result(
                job_id,
                user_id,
                {"status": "completed", "projects": []},
                owner=lifecycle_owner if quota_refund else None,
            )
            if not stored:
                if is_cancelled(job_id):
                    return _cancelled_result([])
                return _terminal_failure(
                    {"success": False, "job_id": job_id, "error": "Job ownership expired"},
                )
            entry_id = publish_event(
                job_id,
                "job.completed",
                {
                    "stage": "github_import",
                    "project_count": 0,
                },
            )
            if quota_refund and not entry_id:
                return {"success": False, "job_id": job_id, "error": "Job ownership expired"}
            if quota_refund:
                clear_quota_refund_receipt(job_id)
            logger.info(f"GitHub import job {job_id}: no eligible projects")
            return {"success": True, "job_id": job_id, "project_count": 0}

        projects: List[Dict[str, Any]] = []
        total = len(top)
        for idx, repo in enumerate(top):
            if is_cancelled(job_id):
                return _cancelled_result(projects)

            owner, name = repo["owner"], repo["name"]
            readme = gh.fetch_repo_readme(github_token, owner, name, client=client)
            if not readme:
                # rank_repos already excludes short READMEs via GraphQL byteSize;
                # a miss here means the file is unreadable — skip rather than
                # summarize nothing.
                continue
            languages = gh.fetch_repo_languages(github_token, owner, name, client=client)
            repo["raw_excerpt"] = readme[:2000]

            summary = gh.summarize_project(repo, readme, languages, api_key)
            projects.append(gh.build_project_evidence(repo, summary))

            percent = 25 + int(70 * (idx + 1) / total)
            publish_event(
                job_id,
                "job.progress",
                {
                    "percent": percent,
                    "stage": "github_import",
                    "message": f"Summarized {name}",
                },
            )

        stored = _store_result(
            job_id,
            user_id,
            {"status": "completed", "projects": projects},
            owner=lifecycle_owner if quota_refund else None,
        )
        if not stored:
            if is_cancelled(job_id):
                return _cancelled_result(projects)
            return _terminal_failure(
                {"success": False, "job_id": job_id, "error": "Job ownership expired"},
            )
        entry_id = publish_event(
            job_id,
            "job.completed",
            {
                "stage": "github_import",
                "project_count": len(projects),
            },
        )
        if quota_refund and not entry_id:
            return {"success": False, "job_id": job_id, "error": "Job ownership expired"}
        if quota_refund:
            clear_quota_refund_receipt(job_id)
        logger.info(f"GitHub import job {job_id}: {len(projects)} projects imported")
        return {"success": True, "job_id": job_id, "project_count": len(projects)}

    except SoftTimeLimitExceeded:
        logger.error(f"GitHub import task {task_id} exceeded soft time limit for job {job_id}")
        stored = _store_result(
            job_id,
            user_id,
            {"status": "failed", "projects": [], "error": "timeout"},
            owner=lifecycle_owner if quota_refund else None,
        )
        if stored:
            try:
                publish_event(
                    job_id,
                    "job.failed",
                    {
                        "stage": "github_import",
                        "error_code": "timeout",
                        "error_message": "Import exceeded time limit",
                        "retryable": False,
                    },
                )
            finally:
                _terminal_failure(
                    {"success": False, "job_id": job_id, "error": "Task exceeded time limit"},
                    terminal_accepted=True,
                )
            return {"success": False, "job_id": job_id, "error": "Task exceeded time limit"}
        return _terminal_failure(
            {"success": False, "job_id": job_id, "error": "Task exceeded time limit"},
            terminal_accepted=stored,
        )

    except Exception as exc:
        from celery.exceptions import Retry

        if isinstance(exc, Retry):
            _release_owner()
            raise
        logger.error("GitHub import task %s raised", task_id, extra={"error_type": type(exc).__name__})
        has_retries_left = self.request.retries < self.max_retries
        if has_retries_left:
            publish_event(
                job_id,
                "job.retrying",
                {
                    "stage": "github_import",
                    "worker_id": worker_id,
                    "attempt": self.request.retries + 2,
                    "error_message": "GitHub import is retrying",
                },
            )
            raise self.retry(countdown=60, exc=exc)
        stored = _store_result(
            job_id,
            user_id,
            {"status": "failed", "projects": [], "error": "GitHub import failed"},
            owner=lifecycle_owner if quota_refund else None,
        )
        if stored:
            try:
                publish_event(
                    job_id,
                    "job.failed",
                    {
                        "stage": "github_import",
                        "error_code": "github_import_error",
                        "error_message": "GitHub import failed",
                        "retryable": False,
                    },
                )
            finally:
                _terminal_failure(
                    {"success": False, "job_id": job_id, "error": "GitHub import failed"},
                    terminal_accepted=True,
                )
            return {"success": False, "job_id": job_id, "error": "GitHub import failed"}
        return _terminal_failure(
            {"success": False, "job_id": job_id, "error": "GitHub import failed"},
            terminal_accepted=stored,
        )

    finally:
        _release_owner()
        if client is not None:
            client.close()


# ------------------------------------------------------------------ #
#  Submission helper                                                   #
# ------------------------------------------------------------------ #


def submit_github_import(
    job_id: str,
    user_id: str,
    user_plan: str = "free",
    quota_refund: Optional[Dict[str, Any]] = None,
) -> str:
    """Enqueue import_github_projects_task on the llm queue (or Modal spawn)."""
    priority = get_task_priority(user_plan)
    payload: Dict[str, Any] = {
        "job_id": job_id,
        "user_id": user_id,
    }
    if quota_refund is not None:
        payload["quota_refund"] = quota_refund

    # On Modal there is no Celery worker consuming the llm queue, so an
    # unconditional apply_async() would hand back a job id for work nothing runs.
    if os.environ.get("DEPLOY_TARGET") == "modal":
        from ..core.modal_dispatch import spawn

        spawn(
            "run_github_import_task",
            payload,
        )
        logger.info(f"Dispatched GitHub import to Modal for job {job_id}")
        return job_id

    import_github_projects_task.apply_async(
        kwargs=payload,
        priority=priority,
        queue="llm",
    )
    logger.info(f"Submitted GitHub import for job {job_id}")
    return job_id
