"""GitHub OAuth + sync routes (Feature 37)."""

import json
import secrets
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ..core.config import resolve_plan_family, settings
from ..core.logging import get_logger
from ..core.redis import cache_manager, get_redis_client
from ..database.connection import get_db
from ..database.models import Resume, User
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.entitlements import require_feature
from ..services import github_projects_service as gh_projects
from ..services.encryption_service import encryption_service
from ..services.entitlement_service import entitlement_service
from ..services.external_budget_service import enforce_external_budget
from ..services.github_sync_service import GitHubSyncConflict, github_sync_service
from ..services.job_result_recovery import recover_terminal_job
from ..utils.uuid_guard import ensure_uuid
from ..workers.github_import_worker import submit_github_import
from ..workers.job_lifecycle import lifecycle_key
from .job_routes import (
    _delete_initial_redis_state,
    _mark_dispatch_accepted,
    _mark_dispatch_started,
    _new_finalization_row,
    _write_initial_redis_state,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/github", tags=["github"])

_GITHUB_IMPORTS_PER_USER_HOUR = 20
_GITHUB_IMPORTS_GLOBAL_PER_HOUR = 500
_GITHUB_SYNC_SHA_KEY = "github_sync_sha"
_MAX_SYNCED_LATEX_LENGTH = 1_000_000

# ── Schemas ──────────────────────────────────────────────────────────────────


class GitHubStatusResponse(BaseModel):
    connected: bool
    username: Optional[str] = None
    public_import: bool = False
    private_sync: bool = False


class GitHubOAuthStartResponse(BaseModel):
    authorization_url: str


class GitHubOAuthCompleteRequest(BaseModel):
    ticket: str = Field(max_length=256)


class GitHubSyncResponse(BaseModel):
    success: bool
    message: str
    commit_url: Optional[str] = None


class GitHubPullResponse(BaseModel):
    success: bool
    latex_content: str


class GitHubEnableRequest(BaseModel):
    repo_name: str = Field(
        default="latexy-resumes",
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )


class GitHubResumeStatus(BaseModel):
    github_sync_enabled: bool
    github_repo_name: Optional[str] = None
    github_last_sync_at: Optional[str] = None


class GitHubImportStartResponse(BaseModel):
    job_id: str


class GitHubImportResultResponse(BaseModel):
    status: str  # pending | completed | failed
    projects: List[dict] = []
    error: Optional[str] = None


# ── OAuth flow ───────────────────────────────────────────────────────────────


def _safe_github_return_to(value: Optional[str]) -> Optional[str]:
    """Allow only same-origin paths through the OAuth round trip."""
    if not value or len(value) > 1024 or not value.startswith("/"):
        return None
    if value.startswith("//") or "\\" in value:
        return None
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return None
    return value


def _github_granted_scopes(user: User) -> set[str]:
    """Return stored OAuth scopes, preserving legacy repo grants safely."""
    metadata = user.user_metadata or {}
    grant = metadata.get("github_oauth")
    if isinstance(grant, dict) and isinstance(grant.get("scopes"), list):
        return {str(scope).strip() for scope in grant["scopes"] if str(scope).strip()}
    # Before scope metadata was recorded, every Latexy GitHub connection
    # requested ``repo``. Treat those existing grants as sync-capable.
    return {"repo"} if user.github_access_token else set()


@router.post(
    "/connect",
    response_model=GitHubOAuthStartResponse,
    dependencies=[Depends(require_feature("integration_github"))],
)
async def github_connect(
    purpose: Literal["import", "sync"] = "import",
    return_to: Optional[str] = None,
    user_id: str = Depends(get_current_user_required),
):
    """Create a purpose-scoped OAuth state for the authenticated user."""
    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail="GitHub integration is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET.",
        )

    # The state is opaque in the browser and consumed atomically by the callback.
    nonce = secrets.token_urlsafe(32)
    safe_return_to = _safe_github_return_to(return_to)
    await cache_manager.set(
        f"gh:oauth:{nonce}",
        {
            "user_id": user_id,
            "purpose": purpose,
            "return_to": safe_return_to,
        },
        ttl=600,
    )

    params_data = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
        "state": nonce,
    }
    # Public profile/repository data needs no OAuth scope. The broad ``repo``
    # grant is requested only when the user explicitly enables private sync.
    if purpose == "sync":
        params_data["scope"] = "repo"
    params = urllib.parse.urlencode(params_data)
    return GitHubOAuthStartResponse(authorization_url=f"https://github.com/login/oauth/authorize?{params}")


def _github_error_redirect(reason: str) -> RedirectResponse:
    """Send the browser back to the settings page with a friendly error flag."""
    return RedirectResponse(f"{settings.FRONTEND_URL}/settings?github=error&reason={urllib.parse.quote(reason)}")


@router.get("/callback")
async def github_callback(
    code: Optional[str] = Query(None, max_length=2048),
    state: str = Query("", max_length=256),
    error: Optional[str] = Query(None, max_length=128),
):
    """Convert a provider callback into a short-lived completion ticket.

    This public endpoint deliberately does not exchange the code or persist a
    token. The browser must present the ticket through the authenticated
    ``/complete`` endpoint, which proves it is still signed in as the Latexy
    user who initiated the flow.
    """
    if not state:
        return _github_error_redirect("missing_state")

    oauth_state = await cache_manager.pop(f"gh:oauth:{state}")
    if not isinstance(oauth_state, dict) or not oauth_state.get("user_id"):
        return _github_error_redirect("invalid_state")

    if error:
        reason = "access_denied" if error == "access_denied" else "provider_error"
        return _github_error_redirect(reason)
    if not code:
        return _github_error_redirect("missing_code")

    ticket = secrets.token_urlsafe(32)
    purpose = "sync" if oauth_state.get("purpose") == "sync" else "import"
    return_to = _safe_github_return_to(oauth_state.get("return_to"))
    await cache_manager.set(
        f"gh:complete:{ticket}",
        {
            "user_id": str(oauth_state["user_id"]),
            "code": code,
            "purpose": purpose,
            "return_to": return_to,
        },
        ttl=300,
    )
    callback_params = {"github": "complete", "ticket": ticket}
    if return_to:
        callback_params["return_to"] = return_to
    query = urllib.parse.urlencode(callback_params)
    return RedirectResponse(f"{settings.FRONTEND_URL}/settings?{query}")


@router.post("/complete")
async def github_complete(
    body: GitHubOAuthCompleteRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Exchange and persist a GitHub code only for its initiating user."""
    ticket = body.ticket.strip()
    if not ticket:
        raise HTTPException(status_code=400, detail="Missing GitHub completion ticket")

    completion = await cache_manager.pop(f"gh:complete:{ticket}")
    if not isinstance(completion, dict):
        raise HTTPException(status_code=400, detail="GitHub completion ticket is invalid or expired")

    intended_user_id = str(completion.get("user_id") or "")
    code = str(completion.get("code") or "")
    if not intended_user_id or not code:
        raise HTTPException(status_code=400, detail="GitHub completion ticket is invalid or expired")
    if not secrets.compare_digest(intended_user_id, user_id):
        logger.warning("Rejected cross-user GitHub OAuth completion")
        raise HTTPException(status_code=403, detail="GitHub connection belongs to a different user")

    # Exchange code for token
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error(f"GitHub token exchange failed: {exc.response.status_code}")
        raise HTTPException(status_code=502, detail="GitHub token exchange failed") from exc
    except httpx.RequestError as exc:
        logger.error("GitHub connection error during token exchange (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="GitHub is unavailable, please try again") from exc

    access_token = data.get("access_token")
    if not access_token:
        error = data.get("error", "token_exchange_failed")
        logger.error("GitHub OAuth returned no access token (%s)", type(error).__name__)
        raise HTTPException(status_code=400, detail=f"GitHub authorization failed: {error}")

    # Get GitHub username
    try:
        gh_user = await github_sync_service.get_github_user(access_token)
    except httpx.HTTPStatusError as exc:
        logger.error(f"GitHub profile fetch failed: {exc.response.status_code}")
        raise HTTPException(status_code=502, detail="GitHub profile fetch failed") from exc
    except httpx.RequestError as exc:
        logger.error("GitHub connection error during profile fetch (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="GitHub is unavailable, please try again") from exc

    username = (gh_user.get("login") or "").strip()
    if not username:
        # Without a login every later push/pull would build an invalid URL and
        # 404; refuse to persist a half-connected account.
        logger.error("GitHub profile returned no login; aborting connect")
        raise HTTPException(status_code=502, detail="GitHub profile did not include a username")

    # Encrypt token before storing
    encrypted_token = encryption_service.encrypt(access_token)

    raw_scopes = str(data.get("scope") or "")
    granted_scopes = sorted({scope.strip() for scope in raw_scopes.replace(",", " ").split() if scope.strip()})

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    metadata = dict(user.user_metadata or {})
    metadata["github_oauth"] = {
        "scopes": granted_scopes,
        "purpose": "sync" if completion.get("purpose") == "sync" else "import",
    }
    user.github_access_token = encrypted_token
    user.github_username = username
    user.user_metadata = metadata
    await db.commit()

    return {"success": True, "message": "GitHub account connected"}


# ── Status + Disconnect ──────────────────────────────────────────────────────


@router.get("/status", response_model=GitHubStatusResponse)
async def github_status(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Check if the user has a connected GitHub account."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return GitHubStatusResponse(
        connected=bool(user.github_access_token),
        username=user.github_username,
        public_import=bool(user.github_access_token),
        private_sync="repo" in _github_granted_scopes(user),
    )


@router.delete("/disconnect")
async def github_disconnect(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Revoke the GitHub grant, then clear local credentials and sync state."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.github_access_token:
        try:
            token = encryption_service.decrypt(user.github_access_token)
            await github_sync_service.revoke_oauth_grant(
                token,
                settings.GITHUB_CLIENT_ID,
                settings.GITHUB_CLIENT_SECRET,
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "GitHub grant revocation failed with status %s",
                exc.response.status_code,
            )
            raise HTTPException(
                status_code=502,
                detail="GitHub access could not be revoked; nothing was disconnected. Please try again.",
            ) from exc
        except httpx.RequestError as exc:
            logger.error("GitHub is unavailable during grant revocation")
            raise HTTPException(
                status_code=502,
                detail="GitHub is unavailable; nothing was disconnected. Please try again.",
            ) from exc

    metadata = dict(user.user_metadata or {})
    metadata.pop("github_oauth", None)
    user.github_access_token = None
    user.github_username = None
    user.user_metadata = metadata
    await db.execute(update(Resume).where(Resume.user_id == user_id).values(github_sync_enabled=False))
    await db.commit()
    return {
        "success": True,
        "message": "GitHub authorization revoked and account disconnected",
    }


# ── Per-resume sync endpoints ────────────────────────────────────────────────


@router.post("/resumes/{resume_id}/enable", response_model=GitHubResumeStatus)
async def enable_github_sync(
    resume_id: str,
    body: GitHubEnableRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Enable GitHub sync for a resume — creates the repo if needed."""
    ensure_uuid(resume_id, "Resume not found")
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.github_access_token:
        raise HTTPException(
            status_code=400,
            detail="GitHub not connected. Go to Settings → GitHub Integration to connect your account.",
        )
    if not user.github_username:
        raise HTTPException(status_code=400, detail="GitHub connection is incomplete. Reconnect GitHub.")
    if "repo" not in _github_granted_scopes(user):
        raise HTTPException(
            status_code=403,
            detail="Private GitHub sync permission is not enabled. Reconnect GitHub for private sync.",
        )

    resume_result = await db.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Decrypt token for API calls
    token = encryption_service.decrypt(user.github_access_token)

    # Create the repo
    try:
        await github_sync_service.ensure_repo(token, user.github_username, body.repo_name)
    except httpx.HTTPStatusError as exc:
        logger.error("Failed to create GitHub repo (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to create GitHub repo: {exc.response.status_code}",
        )
    except httpx.RequestError as exc:
        logger.error("GitHub connection error (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="GitHub is unavailable, please try again")

    resume.github_sync_enabled = True
    if resume.github_repo_name != body.repo_name:
        metadata = dict(resume.resume_settings or {})
        metadata.pop(_GITHUB_SYNC_SHA_KEY, None)
        resume.resume_settings = metadata
        flag_modified(resume, "resume_settings")
    resume.github_repo_name = body.repo_name
    await db.commit()
    await db.refresh(resume)

    return GitHubResumeStatus(
        github_sync_enabled=resume.github_sync_enabled,
        github_repo_name=resume.github_repo_name,
        github_last_sync_at=resume.github_last_sync_at.isoformat() if resume.github_last_sync_at else None,
    )


@router.post("/resumes/{resume_id}/disable", response_model=GitHubResumeStatus)
async def disable_github_sync(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Disable GitHub sync for a resume."""
    ensure_uuid(resume_id, "Resume not found")
    resume_result = await db.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    resume.github_sync_enabled = False
    await db.commit()
    await db.refresh(resume)

    return GitHubResumeStatus(
        github_sync_enabled=resume.github_sync_enabled,
        github_repo_name=resume.github_repo_name,
        github_last_sync_at=resume.github_last_sync_at.isoformat() if resume.github_last_sync_at else None,
    )


@router.post("/resumes/{resume_id}/push", response_model=GitHubSyncResponse)
async def push_to_github(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Push the resume's LaTeX content to GitHub."""
    ensure_uuid(resume_id, "Resume not found")
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.github_access_token:
        raise HTTPException(status_code=400, detail="GitHub not connected")
    if not user.github_username:
        raise HTTPException(status_code=400, detail="GitHub connection is incomplete. Reconnect GitHub.")
    if "repo" not in _github_granted_scopes(user):
        raise HTTPException(
            status_code=403,
            detail="Private GitHub sync permission is not enabled. Reconnect GitHub for private sync.",
        )

    resume_result = await db.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if not resume.github_sync_enabled or not resume.github_repo_name:
        raise HTTPException(status_code=400, detail="GitHub sync is not enabled for this resume")

    # Use stable resume.id as filename so renames don't break sync
    file_path = f"{resume.id}.tex"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    commit_message = f"Latexy: {resume.title} — {timestamp}"

    # Decrypt token for API calls
    token = encryption_service.decrypt(user.github_access_token)
    metadata = dict(resume.resume_settings or {})
    expected_sha = metadata.get(_GITHUB_SYNC_SHA_KEY)
    if not isinstance(expected_sha, str) or not expected_sha:
        expected_sha = None

    try:
        result = await github_sync_service.push_file(
            token=token,
            owner=user.github_username,
            repo=resume.github_repo_name,
            path=file_path,
            content=resume.latex_content,
            commit_message=commit_message,
            expected_sha=expected_sha,
        )
        commit_url = result.get("commit", {}).get("html_url")
        synced_sha = result.get("content", {}).get("sha")
        if not isinstance(synced_sha, str) or not synced_sha:
            raise ValueError("GitHub push response did not include the new blob SHA")
    except GitHubSyncConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="The GitHub file changed since the last sync. Pull it first, review the result, then push again.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        logger.error("GitHub push failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail=f"GitHub push failed: {exc.response.status_code}",
        )
    except httpx.RequestError as exc:
        logger.error("GitHub connection error during push (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="GitHub is unavailable, please try again")
    except ValueError as exc:
        logger.error("GitHub returned an invalid push response (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="GitHub returned an invalid response") from exc

    metadata[_GITHUB_SYNC_SHA_KEY] = synced_sha
    resume.resume_settings = metadata
    flag_modified(resume, "resume_settings")
    resume.github_last_sync_at = datetime.now(timezone.utc)
    await db.commit()

    return GitHubSyncResponse(
        success=True,
        message=f"Pushed {file_path} to {resume.github_repo_name}",
        commit_url=commit_url,
    )


@router.post("/resumes/{resume_id}/pull", response_model=GitHubPullResponse)
async def pull_from_github(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Pull the latest LaTeX content from GitHub."""
    ensure_uuid(resume_id, "Resume not found")
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.github_access_token:
        raise HTTPException(status_code=400, detail="GitHub not connected")
    if not user.github_username:
        raise HTTPException(status_code=400, detail="GitHub connection is incomplete. Reconnect GitHub.")
    if "repo" not in _github_granted_scopes(user):
        raise HTTPException(
            status_code=403,
            detail="Private GitHub sync permission is not enabled. Reconnect GitHub for private sync.",
        )

    resume_result = await db.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if not resume.github_sync_enabled or not resume.github_repo_name:
        raise HTTPException(status_code=400, detail="GitHub sync is not enabled for this resume")

    # Use stable resume.id as filename (matches push)
    file_path = f"{resume.id}.tex"

    # Decrypt token for API calls
    token = encryption_service.decrypt(user.github_access_token)

    try:
        remote = await github_sync_service.pull_file(
            token=token,
            owner=user.github_username,
            repo=resume.github_repo_name,
            path=file_path,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="File not found on GitHub")
        logger.error("GitHub pull failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail=f"GitHub pull failed: {exc.response.status_code}",
        )
    except httpx.RequestError as exc:
        logger.error("GitHub connection error during pull (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="GitHub is unavailable, please try again")
    except ValueError as exc:
        logger.error("GitHub returned invalid file content (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="The GitHub file is not valid UTF-8 LaTeX source") from exc

    content = remote["content"]
    if len(content) > _MAX_SYNCED_LATEX_LENGTH:
        raise HTTPException(status_code=413, detail="The GitHub LaTeX file exceeds the 1 MB document limit")
    if "\x00" in content:
        raise HTTPException(status_code=422, detail="The GitHub LaTeX file contains unsupported null bytes")
    metadata = dict(resume.resume_settings or {})
    metadata[_GITHUB_SYNC_SHA_KEY] = remote["sha"]
    # A pulled source file invalidates a compiled anonymous share artifact in
    # exactly the same way as a normal editor save.
    metadata.pop("share_anonymous_job_id", None)
    metadata.pop("share_anonymous_pending", None)
    resume.resume_settings = metadata
    flag_modified(resume, "resume_settings")
    if content != resume.latex_content and resume.selected_template_id and resume.structured_content:
        resume.builder_status = "detached"
        resume.content_source = "manual_latex"
    resume.latex_content = content
    resume.github_last_sync_at = datetime.now(timezone.utc)
    resume.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return GitHubPullResponse(success=True, latex_content=content)


# ── Resume GitHub status ─────────────────────────────────────────────────────


@router.post("/import-projects", response_model=GitHubImportStartResponse)
async def import_github_projects(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_feature("ai_import_github")),
):
    """Enqueue an async import of the user's top PUBLIC GitHub projects.

    Reads public repository data only (see github_projects_service). Requires a
    connected GitHub account; summarization runs on the user's own LLM key when
    they have one (BYOK), otherwise on the platform key.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.github_access_token:
        raise HTTPException(
            status_code=400,
            detail="GitHub not connected. Go to Settings → GitHub Integration to connect your account.",
        )

    user_plan = "free"
    if isinstance(user.subscription_plan, str) and user.subscription_plan:
        user_plan = user.subscription_plan

    job_id = str(uuid.uuid4())
    finalization_record = _new_finalization_row(job_id, "github_import", user_id, {})
    db.add(finalization_record)
    await db.commit()
    try:
        quota_ticket = await entitlement_service.enforce_quota(
            "ai_assists", user_id=user_id, plan=user_plan, job_id=job_id
        )
    except Exception:
        await db.delete(finalization_record)
        await db.commit()
        raise
    try:
        await enforce_external_budget(
            "import-github",
            client_id=f"user:{user_id}",
            cost=1,
            client_limit=_GITHUB_IMPORTS_PER_USER_HOUR,
            global_limit=_GITHUB_IMPORTS_GLOBAL_PER_HOUR,
            window_seconds=3600,
        )
    except Exception:
        await entitlement_service.refund_quota(quota_ticket)
        try:
            await db.delete(finalization_record)
            await db.commit()
        except Exception:
            await db.rollback()
        raise

    redis = None
    result_key = gh_projects.import_result_key(job_id)
    dispatched = False
    dispatch_attempted = False
    try:
        redis = await get_redis_client()
        # Establish ownership before dispatch. Without this marker an arbitrary
        # UUID looked like a legitimate pending job, and there was no owner to
        # check until (or even after) the worker wrote its result.
        await redis.set(
            result_key,
            gh_projects.encode_result(
                {
                    "user_id": user_id,
                    "status": "pending",
                    "projects": [],
                }
            ),
            ex=gh_projects.IMPORT_RESULT_TTL,
        )
        await _write_initial_redis_state(job_id, "github_import", user_id, 120)
        # Lifecycle initialization is still pre-dispatch. Only mark the call
        # ambiguous immediately before invoking the broker/Modal submit helper.
        await _mark_dispatch_started(job_id)
        dispatch_attempted = True
        submit_github_import(
            job_id=job_id,
            user_id=user_id,
            user_plan=resolve_plan_family(user_plan),
            quota_refund=quota_ticket.refund_payload(),
        )
        await _mark_dispatch_accepted(job_id)
        dispatched = True
    except Exception as exc:
        if dispatched or dispatch_attempted:
            logger.error(
                "Ambiguous GitHub import dispatch for job %s; preserving lifecycle",
                job_id,
                extra={"error_type": type(exc).__name__},
            )
            return GitHubImportStartResponse(job_id=job_id)
        await entitlement_service.refund_quota(quota_ticket)
        try:
            await db.delete(finalization_record)
            await db.commit()
        except Exception:
            await db.rollback()
        logger.error("Failed to submit GitHub import job %s (%s)", job_id, type(exc).__name__)
        try:
            if redis is not None:
                await redis.delete(result_key)
                if not dispatch_attempted:
                    # No broker call occurred, so a partially-created
                    # dispatch lifecycle cannot protect work that was never
                    # submitted. Remove it before compensating the receipt.
                    await redis.delete(lifecycle_key(job_id))
            await _delete_initial_redis_state(job_id, user_id)
        except Exception as cleanup_exc:
            logger.warning(
                "Failed to remove undispatched GitHub import marker %s: %s",
                job_id,
                cleanup_exc,
            )
        raise HTTPException(
            status_code=503,
            detail="Failed to start GitHub import. Please try again.",
        )

    return GitHubImportStartResponse(job_id=job_id)


@router.get("/import-projects/{job_id}", response_model=GitHubImportResultResponse)
async def get_github_import_result(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_feature("ai_import_github")),
):
    """Return the candidate ProjectEvidence for an import job.

    ``status`` is ``pending`` until the worker writes a result (~1h TTL),
    then ``completed`` or ``failed``.
    """
    try:
        redis = await get_redis_client()
        raw = await redis.get(gh_projects.import_result_key(job_id))
    except Exception as exc:
        # A Redis outage is not evidence that the import is absent.  Do not
        # turn an unavailable transport into a durable-result bypass, because
        # the fallback is intentionally only for a successful cache miss.
        logger.warning("GitHub import result lookup unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Import status temporarily unavailable") from exc
    envelope = gh_projects.decode_result(raw)
    # A miss, malformed/legacy ownerless envelope, and another user's job are
    # deliberately indistinguishable so this endpoint cannot enumerate jobs.
    if envelope is None:
        recovery = await recover_terminal_job(
            db,
            job_id=job_id,
            user_id=user_id,
            expected_type="github_import",
        )
        if recovery is not None:
            payload = recovery["payload"]
            return GitHubImportResultResponse(
                status=recovery["state"],
                projects=payload.get("projects", []),
                error=recovery["error"],
            )
        raise HTTPException(status_code=404, detail="Import job not found")
    if envelope.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Import job not found")

    # The worker can commit the durable terminal decision and then die before
    # replacing the import-specific pending marker.  Reconcile that case from
    # the same bounded, owner-scoped row; a still-pending DB row simply falls
    # through to the existing pending response below.
    if envelope.get("status") == "pending":
        recovery = await recover_terminal_job(
            db,
            job_id=job_id,
            user_id=user_id,
            expected_type="github_import",
        )
        if recovery is not None:
            payload = recovery["payload"]
            return GitHubImportResultResponse(
                status=recovery["state"],
                projects=payload.get("projects", []),
                error=recovery["error"],
            )

    # Generic lifecycle cleanup writes a canonical failure result when a worker
    # dies after admission. Surface that terminal evidence even if the
    # import-specific pending envelope is still present; otherwise a crashed
    # import remains ``pending`` forever from this endpoint's perspective.
    if envelope.get("status") == "pending":
        terminal_raw = await redis.get(f"latexy:job:{job_id}:result")
        try:
            terminal = json.loads(terminal_raw) if terminal_raw else None
        except (TypeError, ValueError, json.JSONDecodeError):
            terminal = None
        if isinstance(terminal, dict) and terminal.get("success") is False:
            return GitHubImportResultResponse(
                status="failed",
                projects=[],
                error=terminal.get("error") or "GitHub import failed",
            )
        state_raw = await redis.get(f"latexy:job:{job_id}:state")
        try:
            state = json.loads(state_raw) if state_raw else None
        except (TypeError, ValueError, json.JSONDecodeError):
            state = None
        if isinstance(state, dict) and state.get("status") in {"failed", "cancelled"}:
            return GitHubImportResultResponse(
                status="failed",
                projects=[],
                error="GitHub import cancelled" if state["status"] == "cancelled" else "GitHub import failed",
            )

    return GitHubImportResultResponse(
        status=envelope.get("status", "pending"),
        projects=envelope.get("projects", []),
        error=envelope.get("error"),
    )


@router.get("/resumes/{resume_id}/status", response_model=GitHubResumeStatus)
async def get_resume_github_status(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Get GitHub sync status for a resume."""
    ensure_uuid(resume_id, "Resume not found")
    resume_result = await db.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    return GitHubResumeStatus(
        github_sync_enabled=resume.github_sync_enabled,
        github_repo_name=resume.github_repo_name,
        github_last_sync_at=resume.github_last_sync_at.isoformat() if resume.github_last_sync_at else None,
    )
