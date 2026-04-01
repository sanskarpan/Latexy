"""GitHub OAuth + sync routes (Feature 37)."""

import urllib.parse
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import Resume, User
from ..middleware.auth_middleware import get_current_user_required
from ..services.github_sync_service import github_sync_service

logger = get_logger(__name__)

router = APIRouter(prefix="/github", tags=["github"])

# ── Schemas ──────────────────────────────────────────────────────────────────

class GitHubStatusResponse(BaseModel):
    connected: bool
    username: Optional[str] = None


class GitHubSyncResponse(BaseModel):
    success: bool
    message: str
    commit_url: Optional[str] = None


class GitHubPullResponse(BaseModel):
    success: bool
    latex_content: str


class GitHubEnableRequest(BaseModel):
    repo_name: str = "latexy-resumes"


class GitHubResumeStatus(BaseModel):
    github_sync_enabled: bool
    github_repo_name: Optional[str] = None
    github_last_sync_at: Optional[str] = None


# ── OAuth flow ───────────────────────────────────────────────────────────────

@router.get("/connect")
async def github_connect(
    user_id: str = Depends(get_current_user_required),
):
    """Redirect to GitHub OAuth authorization URL."""
    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail="GitHub integration is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET.",
        )

    params = urllib.parse.urlencode({
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
        "scope": "repo",
        "state": user_id,  # pass user_id through state
    })
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{params}")


@router.get("/callback")
async def github_callback(
    code: str = Query(...),
    state: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """Exchange code for access token and store it on the user."""
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter")

    user_id = state

    # Exchange code for token
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

    access_token = data.get("access_token")
    if not access_token:
        error = data.get("error_description", data.get("error", "Unknown error"))
        raise HTTPException(status_code=400, detail=f"GitHub OAuth failed: {error}")

    # Get GitHub username
    gh_user = await github_sync_service.get_github_user(access_token)
    username = gh_user.get("login", "")

    # Store on user
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(github_access_token=access_token, github_username=username)
    )
    await db.commit()

    # Redirect to frontend settings page
    return RedirectResponse(f"{settings.FRONTEND_URL}/settings?github=connected")


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
    )


@router.delete("/disconnect")
async def github_disconnect(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Clear GitHub token and disable sync on all resumes."""
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(github_access_token=None, github_username=None)
    )
    await db.execute(
        update(Resume)
        .where(Resume.user_id == user_id)
        .values(github_sync_enabled=False)
    )
    await db.commit()
    return {"success": True, "message": "GitHub disconnected"}


# ── Per-resume sync endpoints ────────────────────────────────────────────────

@router.post("/resumes/{resume_id}/enable", response_model=GitHubResumeStatus)
async def enable_github_sync(
    resume_id: str,
    body: GitHubEnableRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Enable GitHub sync for a resume — creates the repo if needed."""
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.github_access_token:
        raise HTTPException(
            status_code=400,
            detail="GitHub not connected. Go to Settings → GitHub Integration to connect your account.",
        )

    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Create the repo
    try:
        await github_sync_service.ensure_repo(
            user.github_access_token, user.github_username, body.repo_name
        )
    except httpx.HTTPStatusError as exc:
        logger.error(f"Failed to create GitHub repo: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to create GitHub repo: {exc.response.status_code}",
        )

    resume.github_sync_enabled = True
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
    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
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
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.github_access_token:
        raise HTTPException(status_code=400, detail="GitHub not connected")

    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if not resume.github_sync_enabled or not resume.github_repo_name:
        raise HTTPException(status_code=400, detail="GitHub sync is not enabled for this resume")

    # Sanitise title for file name
    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in resume.title).strip() or "resume"
    file_path = f"{safe_title}.tex"
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    commit_message = f"Latexy: {resume.title} — {timestamp}"

    try:
        result = await github_sync_service.push_file(
            token=user.github_access_token,
            owner=user.github_username,
            repo=resume.github_repo_name,
            path=file_path,
            content=resume.latex_content,
            commit_message=commit_message,
        )
        commit_url = result.get("commit", {}).get("html_url")
    except httpx.HTTPStatusError as exc:
        logger.error(f"GitHub push failed: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"GitHub push failed: {exc.response.status_code}",
        )

    resume.github_last_sync_at = datetime.utcnow()
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
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.github_access_token:
        raise HTTPException(status_code=400, detail="GitHub not connected")

    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if not resume.github_sync_enabled or not resume.github_repo_name:
        raise HTTPException(status_code=400, detail="GitHub sync is not enabled for this resume")

    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in resume.title).strip() or "resume"
    file_path = f"{safe_title}.tex"

    try:
        content = await github_sync_service.pull_file(
            token=user.github_access_token,
            owner=user.github_username,
            repo=resume.github_repo_name,
            path=file_path,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="File not found on GitHub")
        logger.error(f"GitHub pull failed: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"GitHub pull failed: {exc.response.status_code}",
        )

    return GitHubPullResponse(success=True, latex_content=content)


# ── Resume GitHub status ─────────────────────────────────────────────────────

@router.get("/resumes/{resume_id}/status", response_model=GitHubResumeStatus)
async def get_resume_github_status(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Get GitHub sync status for a resume."""
    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    return GitHubResumeStatus(
        github_sync_enabled=resume.github_sync_enabled,
        github_repo_name=resume.github_repo_name,
        github_last_sync_at=resume.github_last_sync_at.isoformat() if resume.github_last_sync_at else None,
    )
