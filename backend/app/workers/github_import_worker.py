"""GitHub project-import worker (Feature 1 — external sources to resume).

Runs the fetch → rank → (README + languages per top repo) → summarize → evidence
pipeline as an async job, publishes progress events, and stores the resulting
candidate ``ProjectEvidence`` list in Redis for the frontend to review.

PRIVACY: only PUBLIC repository data is read (see github_projects_service).

Runs on the 'llm' queue (the work is LLM-bound). On Modal there is no Celery
worker, so ``submit_github_import`` routes to the ``run_github_import_task``
Modal function instead of enqueueing to a broker with no consumer.
"""

import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
from celery.exceptions import SoftTimeLimitExceeded

from ..core.celery_app import celery_app, get_task_priority
from ..core.logging import get_logger
from ..services import github_projects_service as gh
from ..workers.event_publisher import get_worker_redis, is_cancelled, publish_event

logger = get_logger(__name__)


def _store_result(job_id: str, payload: Dict[str, Any]) -> None:
    """Persist the import result envelope to Redis with a ~1h TTL."""
    r = get_worker_redis()
    r.setex(
        gh.import_result_key(job_id),
        gh.IMPORT_RESULT_TTL,
        gh.encode_result(payload),
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
    github_token: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Import + summarize a user's top public GitHub projects.

    ``github_token`` authenticates the (public-only) GitHub reads; ``api_key`` is
    the user's LLM key when BYOK, else the platform key, for README summarization.

    Publishes: job.started, job.progress (per stage), job.completed / job.failed.
    Stores the result at ``latexy:github_import:{job_id}``.
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    task_id = self.request.id
    worker_id = f"github-import-{task_id}"
    logger.info(f"GitHub import task {task_id} starting for job {job_id}")

    if not github_token:
        publish_event(job_id, "job.failed", {
            "stage": "github_import",
            "error_code": "github_not_connected",
            "error_message": "No GitHub token available for this import.",
            "retryable": False,
        })
        _store_result(job_id, {"status": "failed", "projects": [],
                               "error": "GitHub not connected"})
        return {"success": False, "job_id": job_id, "error": "GitHub not connected"}

    publish_event(job_id, "job.started", {"worker_id": worker_id, "stage": "github_import"})

    # One HTTP client for every GitHub call → serial requests keep us clear of
    # GitHub's secondary rate limits.
    client = httpx.Client(timeout=20)
    try:
        publish_event(job_id, "job.progress", {
            "percent": 10, "stage": "github_import",
            "message": "Fetching your GitHub projects",
        })
        candidates = gh.fetch_candidate_repos(github_token, client=client)

        publish_event(job_id, "job.progress", {
            "percent": 25, "stage": "github_import",
            "message": "Ranking your top projects",
        })
        top = gh.rank_repos(candidates)

        if not top:
            _store_result(job_id, {"status": "completed", "projects": []})
            publish_event(job_id, "job.completed", {
                "stage": "github_import", "project_count": 0,
            })
            logger.info(f"GitHub import job {job_id}: no eligible projects")
            return {"success": True, "job_id": job_id, "project_count": 0}

        projects: List[Dict[str, Any]] = []
        total = len(top)
        for idx, repo in enumerate(top):
            if is_cancelled(job_id):
                publish_event(job_id, "job.cancelled", {})
                _store_result(job_id, {"status": "failed", "projects": projects,
                                       "error": "cancelled"})
                return {"success": False, "job_id": job_id, "cancelled": True}

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
            publish_event(job_id, "job.progress", {
                "percent": percent, "stage": "github_import",
                "message": f"Summarized {name}",
            })

        _store_result(job_id, {"status": "completed", "projects": projects})
        publish_event(job_id, "job.completed", {
            "stage": "github_import", "project_count": len(projects),
        })
        logger.info(f"GitHub import job {job_id}: {len(projects)} projects imported")
        return {"success": True, "job_id": job_id, "project_count": len(projects)}

    except SoftTimeLimitExceeded:
        logger.error(f"GitHub import task {task_id} exceeded soft time limit for job {job_id}")
        publish_event(job_id, "job.failed", {
            "stage": "github_import",
            "error_code": "timeout",
            "error_message": "Import exceeded time limit",
            "retryable": False,
        })
        _store_result(job_id, {"status": "failed", "projects": [], "error": "timeout"})
        return {"success": False, "job_id": job_id, "error": "Task exceeded time limit"}

    except Exception as exc:
        from celery.exceptions import Retry
        if isinstance(exc, Retry):
            raise
        logger.error(f"GitHub import task {task_id} raised: {exc}")
        has_retries_left = self.request.retries < self.max_retries
        publish_event(job_id, "job.failed", {
            "stage": "github_import",
            "error_code": "github_import_error",
            "error_message": str(exc),
            "retryable": has_retries_left,
        })
        if has_retries_left:
            raise self.retry(countdown=60, exc=exc)
        _store_result(job_id, {"status": "failed", "projects": [], "error": str(exc)})
        return {"success": False, "job_id": job_id, "error": str(exc)}

    finally:
        client.close()


# ------------------------------------------------------------------ #
#  Submission helper                                                   #
# ------------------------------------------------------------------ #

def submit_github_import(
    job_id: str,
    user_id: str,
    github_token: str,
    api_key: Optional[str] = None,
    user_plan: str = "free",
) -> str:
    """Enqueue import_github_projects_task on the llm queue (or Modal spawn)."""
    priority = get_task_priority(user_plan)

    # On Modal there is no Celery worker consuming the llm queue, so an
    # unconditional apply_async() would hand back a job id for work nothing runs.
    if os.environ.get("DEPLOY_TARGET") == "modal":
        from ..core.modal_dispatch import spawn
        spawn("run_github_import_task", {
            "job_id": job_id,
            "user_id": user_id,
            "github_token": github_token,
            "api_key": api_key,
        })
        logger.info(f"Dispatched GitHub import to Modal for job {job_id}")
        return job_id

    import_github_projects_task.apply_async(
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "github_token": github_token,
            "api_key": api_key,
        },
        priority=priority,
        queue="llm",
    )
    logger.info(f"Submitted GitHub import for job {job_id}")
    return job_id
