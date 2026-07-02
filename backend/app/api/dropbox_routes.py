"""Dropbox OAuth + sync routes (Feature 77)."""

import secrets
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import cache_manager
from ..database.connection import get_db
from ..database.models import Resume, User
from ..middleware.auth_middleware import get_current_user_required
from ..services.dropbox_sync_service import dropbox_sync_service
from ..services.encryption_service import encryption_service

logger = get_logger(__name__)

router = APIRouter(prefix="/dropbox", tags=["dropbox"])

# ── Schemas ───────────────────────────────────────────────────────────────────


class DropboxStatusResponse(BaseModel):
    connected: bool
    display_name: Optional[str] = None
    account_id: Optional[str] = None


class DropboxResumeStatus(BaseModel):
    dropbox_sync_enabled: bool
    dropbox_folder_path: Optional[str] = None
    dropbox_last_sync_at: Optional[str] = None


class DropboxSyncResponse(BaseModel):
    success: bool
    message: str
    file_path: Optional[str] = None


class DropboxPullResponse(BaseModel):
    success: bool
    latex_content: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _resume_status(resume: Resume) -> DropboxResumeStatus:
    return DropboxResumeStatus(
        dropbox_sync_enabled=resume.dropbox_sync_enabled,
        dropbox_folder_path=resume.dropbox_folder_path,
        dropbox_last_sync_at=(
            resume.dropbox_last_sync_at.isoformat() if resume.dropbox_last_sync_at else None
        ),
    )


def _decrypt_access_token(user: User) -> str:
    """Return the decrypted stored Dropbox access token."""
    if not user.dropbox_access_token:
        raise HTTPException(
            status_code=400,
            detail="Dropbox not connected. Go to Settings → Dropbox Integration to connect.",
        )
    return encryption_service.decrypt(user.dropbox_access_token)


async def _refresh_dropbox_token(user: User, db: AsyncSession) -> str:
    """Refresh the Dropbox access token and persist it back to the user row.

    Called lazily only when the stored access token is rejected (401), so the
    common path pays no extra round-trip and the new token is reused next time.
    """
    if not user.dropbox_refresh_token:
        raise HTTPException(
            status_code=401,
            detail="Dropbox session expired. Please reconnect in Settings → Dropbox Integration.",
        )
    try:
        refresh_tok = encryption_service.decrypt(user.dropbox_refresh_token)
        new_access = await dropbox_sync_service.refresh_access_token(refresh_tok)
    except httpx.HTTPStatusError:
        raise HTTPException(
            status_code=401,
            detail="Dropbox session expired. Please reconnect in Settings → Dropbox Integration.",
        )
    except httpx.RequestError as exc:
        logger.error(f"Dropbox connection error during token refresh: {exc}")
        raise HTTPException(status_code=502, detail="Dropbox is unavailable, please try again")

    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(dropbox_access_token=encryption_service.encrypt(new_access))
    )
    await db.commit()
    return new_access


async def _run_with_dropbox_token(user: User, db: AsyncSession, op):
    """Run ``op(token)``; on a 401 refresh the token once and retry."""
    token = _decrypt_access_token(user)
    try:
        return await op(token)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 401:
            raise
        token = await _refresh_dropbox_token(user, db)
        return await op(token)


# ── OAuth flow ────────────────────────────────────────────────────────────────


@router.get("/connect")
async def dropbox_connect(
    user_id: str = Depends(get_current_user_required),
):
    """Redirect user to Dropbox OAuth 2.0 authorization URL."""
    if not settings.DROPBOX_APP_KEY or not settings.DROPBOX_APP_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Dropbox integration is not configured. Set DROPBOX_APP_KEY and DROPBOX_APP_SECRET.",
        )

    # CSRF nonce — stored in Redis for 10 minutes
    nonce = secrets.token_urlsafe(32)
    await cache_manager.set(f"dbx:oauth:{nonce}", user_id, ttl=600)

    params = urllib.parse.urlencode({
        "client_id": settings.DROPBOX_APP_KEY,
        "redirect_uri": settings.DROPBOX_REDIRECT_URI,
        "response_type": "code",
        "token_access_type": "offline",  # request a refresh token
        "state": nonce,
    })
    return RedirectResponse(f"https://www.dropbox.com/oauth2/authorize?{params}")


def _dropbox_error_redirect(reason: str) -> RedirectResponse:
    """Send the browser back to the settings page with a friendly error flag."""
    return RedirectResponse(
        f"{settings.FRONTEND_URL}/settings?dropbox=error&reason={urllib.parse.quote(reason)}"
    )


@router.get("/callback")
async def dropbox_callback(
    code: str = Query(...),
    state: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """Exchange the authorization code for access + refresh tokens."""
    if not state:
        return _dropbox_error_redirect("missing_state")

    # Validate CSRF nonce
    user_id = await cache_manager.get(f"dbx:oauth:{state}")
    if not user_id:
        return _dropbox_error_redirect("invalid_state")
    await cache_manager.delete(f"dbx:oauth:{state}")

    # Exchange code for tokens
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.dropboxapi.com/oauth2/token",
                data={
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": settings.DROPBOX_REDIRECT_URI,
                    "client_id": settings.DROPBOX_APP_KEY,
                    "client_secret": settings.DROPBOX_APP_SECRET,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error(f"Dropbox token exchange failed: {exc.response.status_code}")
        return _dropbox_error_redirect("token_exchange_failed")
    except httpx.RequestError as exc:
        logger.error(f"Dropbox connection error during token exchange: {exc}")
        return _dropbox_error_redirect("dropbox_unavailable")

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    if not access_token:
        error = data.get("error", "token_exchange_failed")
        logger.error(f"Dropbox OAuth returned no access token: {error}")
        return _dropbox_error_redirect(str(error))

    # Fetch account info (for a human-readable display name)
    account_id = ""
    display_name = ""
    try:
        account = await dropbox_sync_service.get_account(access_token)
        account_id = account.get("account_id", "")
        display_name = (account.get("name") or {}).get("display_name", "")
    except Exception as exc:
        logger.error(f"Failed to fetch Dropbox account info: {exc}")

    # Encrypt tokens before storing
    encrypted_access = encryption_service.encrypt(access_token)
    encrypted_refresh = encryption_service.encrypt(refresh_token) if refresh_token else None

    # Persist the display name in user_metadata (no dedicated column exists) so
    # the status endpoint can show a real name instead of the opaque account id.
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return _dropbox_error_redirect("user_not_found")

    user.dropbox_access_token = encrypted_access
    user.dropbox_refresh_token = encrypted_refresh
    user.dropbox_account_id = account_id
    meta = dict(user.user_metadata or {})
    if display_name:
        meta["dropbox_display_name"] = display_name
    else:
        meta.pop("dropbox_display_name", None)
    user.user_metadata = meta
    await db.commit()

    logger.info(f"Dropbox connected for user {user_id} (account: {account_id})")
    return RedirectResponse(f"{settings.FRONTEND_URL}/settings?dropbox=connected")


# ── Status + Disconnect ───────────────────────────────────────────────────────


@router.get("/status", response_model=DropboxStatusResponse)
async def dropbox_status(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Return whether the user has a connected Dropbox account."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    meta = user.user_metadata or {}
    return DropboxStatusResponse(
        connected=bool(user.dropbox_access_token),
        # Prefer the human-readable display name captured at connect time; fall
        # back to the account id for accounts connected before that was stored.
        display_name=meta.get("dropbox_display_name") or user.dropbox_account_id,
        account_id=user.dropbox_account_id,
    )


@router.delete("/disconnect")
async def dropbox_disconnect(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Clear Dropbox tokens and disable sync on all resumes."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.dropbox_access_token = None
        user.dropbox_refresh_token = None
        user.dropbox_account_id = None
        meta = dict(user.user_metadata or {})
        meta.pop("dropbox_display_name", None)
        user.user_metadata = meta
    await db.execute(
        update(Resume)
        .where(Resume.user_id == user_id)
        .values(dropbox_sync_enabled=False)
    )
    await db.commit()
    return {"success": True, "message": "Dropbox disconnected"}


# ── Per-resume sync endpoints ─────────────────────────────────────────────────


@router.post("/resumes/{resume_id}/enable", response_model=DropboxResumeStatus)
async def enable_dropbox_sync(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Enable Dropbox sync for a resume and do an initial push."""
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.dropbox_access_token:
        raise HTTPException(
            status_code=400,
            detail="Dropbox not connected. Go to Settings → Dropbox Integration to connect.",
        )

    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Build deterministic path — use resume ID so renames don't break sync
    folder_path = f"/Latexy/{resume.id}.tex"

    try:
        await _run_with_dropbox_token(
            user, db,
            lambda t: dropbox_sync_service.upload_file(t, folder_path, resume.latex_content),
        )
    except httpx.HTTPStatusError as exc:
        logger.error(f"Dropbox initial push failed: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"Dropbox upload failed ({exc.response.status_code}). Check your Dropbox permissions.",
        )
    except httpx.RequestError as exc:
        logger.error(f"Dropbox connection error on enable: {exc}")
        raise HTTPException(status_code=502, detail="Dropbox is unavailable, please try again")

    resume.dropbox_sync_enabled = True
    resume.dropbox_folder_path = folder_path
    resume.dropbox_last_sync_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(resume)

    return _resume_status(resume)


@router.post("/resumes/{resume_id}/disable", response_model=DropboxResumeStatus)
async def disable_dropbox_sync(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Disable Dropbox sync for a resume (does not delete the Dropbox file)."""
    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    resume.dropbox_sync_enabled = False
    await db.commit()
    await db.refresh(resume)
    return _resume_status(resume)


@router.post("/resumes/{resume_id}/push", response_model=DropboxSyncResponse)
async def push_to_dropbox(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Upload the resume's current LaTeX content to Dropbox."""
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.dropbox_access_token:
        raise HTTPException(status_code=400, detail="Dropbox not connected")

    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if not resume.dropbox_sync_enabled or not resume.dropbox_folder_path:
        raise HTTPException(status_code=400, detail="Dropbox sync is not enabled for this resume")

    try:
        await _run_with_dropbox_token(
            user, db,
            lambda t: dropbox_sync_service.upload_file(t, resume.dropbox_folder_path, resume.latex_content),
        )
    except httpx.HTTPStatusError as exc:
        logger.error(f"Dropbox push failed: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"Dropbox upload failed ({exc.response.status_code})",
        )
    except httpx.RequestError as exc:
        logger.error(f"Dropbox connection error during push: {exc}")
        raise HTTPException(status_code=502, detail="Dropbox is unavailable, please try again")

    resume.dropbox_last_sync_at = datetime.now(timezone.utc)
    await db.commit()

    return DropboxSyncResponse(
        success=True,
        message=f"Pushed to {resume.dropbox_folder_path}",
        file_path=resume.dropbox_folder_path,
    )


@router.post("/resumes/{resume_id}/pull", response_model=DropboxPullResponse)
async def pull_from_dropbox(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Download the latest LaTeX content from Dropbox."""
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.dropbox_access_token:
        raise HTTPException(status_code=400, detail="Dropbox not connected")

    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if not resume.dropbox_sync_enabled or not resume.dropbox_folder_path:
        raise HTTPException(status_code=400, detail="Dropbox sync is not enabled for this resume")

    try:
        content = await _run_with_dropbox_token(
            user, db,
            lambda t: dropbox_sync_service.download_file(t, resume.dropbox_folder_path),
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            # Dropbox returns 409 when path is not found (path_not_found error)
            raise HTTPException(status_code=404, detail="File not found on Dropbox")
        logger.error(f"Dropbox pull failed: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"Dropbox download failed ({exc.response.status_code})",
        )
    except httpx.RequestError as exc:
        logger.error(f"Dropbox connection error during pull: {exc}")
        raise HTTPException(status_code=502, detail="Dropbox is unavailable, please try again")

    return DropboxPullResponse(success=True, latex_content=content)


@router.get("/resumes/{resume_id}/status", response_model=DropboxResumeStatus)
async def get_resume_dropbox_status(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Get Dropbox sync status for a specific resume."""
    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return _resume_status(resume)
