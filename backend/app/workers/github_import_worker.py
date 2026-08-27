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
from ..workers.event_publisher import get_worker_redis, is_cancelled, publish_event
from ..workers.quota_refund import refund_quota_once

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


def _store_result(job_id: str, user_id: str, payload: Dict[str, Any]) -> None:
    """Persist an owner-bound import result envelope with a ~1h TTL."""
    r = get_worker_redis()
    owned_payload = {**payload, "user_id": user_id}
    r.setex(
        gh.import_result_key(job_id),
        gh.IMPORT_RESULT_TTL,
        gh.encode_result(owned_payload),
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

    def _terminal_failure(result: Dict[str, Any]) -> Dict[str, Any]:
        refund_quota_once(
            job_id,
            quota_refund,
            expected_dimension="ai_assists",
        )
        return result

    if not user_id:
        logger.error("Refusing ownerless GitHub import job %s", job_id)
        return _terminal_failure(
            {"success": False, "job_id": job_id, "error": "user_id is required"}
        )

    task_id = self.request.id
    worker_id = f"github-import-{task_id}"
    logger.info(f"GitHub import task {task_id} starting for job {job_id}")

    publish_event(job_id, "job.started", {"worker_id": worker_id, "stage": "github_import"})

    # One HTTP client for every GitHub call → serial requests keep us clear of
    # GitHub's secondary rate limits.
    client = None
    try:
        github_token, api_key = asyncio.run(_resolve_import_credentials(user_id))
        if not github_token:
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
            _store_result(
                job_id,
                user_id,
                {"status": "failed", "projects": [], "error": "GitHub not connected"},
            )
            return _terminal_failure(
                {"success": False, "job_id": job_id, "error": "GitHub not connected"}
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
            _store_result(job_id, user_id, {"status": "completed", "projects": []})
            publish_event(
                job_id,
                "job.completed",
                {
                    "stage": "github_import",
                    "project_count": 0,
                },
            )
            logger.info(f"GitHub import job {job_id}: no eligible projects")
            return {"success": True, "job_id": job_id, "project_count": 0}

        projects: List[Dict[str, Any]] = []
        total = len(top)
        for idx, repo in enumerate(top):
            if is_cancelled(job_id):
                publish_event(job_id, "job.cancelled", {})
                _store_result(job_id, user_id, {"status": "failed", "projects": projects, "error": "cancelled"})
                return _terminal_failure(
                    {"success": False, "job_id": job_id, "cancelled": True}
                )

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

        _store_result(job_id, user_id, {"status": "completed", "projects": projects})
        publish_event(
            job_id,
            "job.completed",
            {
                "stage": "github_import",
                "project_count": len(projects),
            },
        )
        logger.info(f"GitHub import job {job_id}: {len(projects)} projects imported")
        return {"success": True, "job_id": job_id, "project_count": len(projects)}

    except SoftTimeLimitExceeded:
        logger.error(f"GitHub import task {task_id} exceeded soft time limit for job {job_id}")
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
        _store_result(job_id, user_id, {"status": "failed", "projects": [], "error": "timeout"})
        return _terminal_failure(
            {"success": False, "job_id": job_id, "error": "Task exceeded time limit"}
        )

    except Exception as exc:
        from celery.exceptions import Retry

        if isinstance(exc, Retry):
            raise
        logger.error(f"GitHub import task {task_id} raised: {exc}")
        has_retries_left = self.request.retries < self.max_retries
        publish_event(
            job_id,
            "job.failed",
            {
                "stage": "github_import",
                "error_code": "github_import_error",
                "error_message": str(exc),
                "retryable": has_retries_left,
            },
        )
        if has_retries_left:
            raise self.retry(countdown=60, exc=exc)
        _store_result(job_id, user_id, {"status": "failed", "projects": [], "error": str(exc)})
        return _terminal_failure(
            {"success": False, "job_id": job_id, "error": str(exc)}
        )

    finally:
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
