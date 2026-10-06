"""Authenticated Google Drive export (B50a).

Only files created by Latexy are in scope.  The OAuth grant requests Google's
``drive.file`` scope, credentials are encrypted inside the user's existing
metadata column, and export always resolves the latest completed PDF owned by
the authenticated user.  No caller-supplied path, token, or Drive file ID is
accepted.
"""

from __future__ import annotations

import secrets
import urllib.parse
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import cache_manager, get_redis_cache_client
from ..database.connection import get_db
from ..database.models import User
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.entitlements import require_feature
from ..services.encryption_service import encryption_service
from ..services.google_drive_service import (
    GOOGLE_DRIVE_AUTH_URL,
    GOOGLE_DRIVE_SCOPE,
    GoogleDriveProviderError,
    google_drive_service,
)
from ..utils.uuid_guard import ensure_uuid
from .document_delivery_routes import _owned_compiled_pdf

logger = get_logger(__name__)

router = APIRouter(prefix="/google-drive", tags=["google-drive"])

_METADATA_KEY = "google_drive_oauth"
_STATE_TTL_SECONDS = 600
_TICKET_TTL_SECONDS = 300
# Keep one bounded upload size for the Drive API path.  Eight MiB is below
# common request/proxy limits and bounds both memory use and multipart overhead;
# larger documents should be downloaded or shared through the existing flow.
MAX_DRIVE_PDF_BYTES = 8 * 1024 * 1024
# Provider lookup/upload can take 30s, with one 15s refresh and a retried
# upload; leave scheduling/network headroom so the lease cannot expire while
# the first request is still able to create a file.
_EXPORT_LOCK_TTL_SECONDS = 180
_RELEASE_EXPORT_LOCK = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class GoogleDriveStatusResponse(BaseModel):
    connected: bool
    scope: Optional[Literal["drive.file"]] = None


class GoogleDriveOAuthStartResponse(BaseModel):
    authorization_url: str


class GoogleDriveOAuthCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket: str = Field(max_length=256)


class GoogleDriveExportRequest(BaseModel):
    """Empty body: the resume and destination are always server-derived."""

    model_config = ConfigDict(extra="forbid")


class GoogleDriveExportResponse(BaseModel):
    success: Literal[True]
    provider: Literal["google_drive"]
    action: Literal["created", "updated"]
    retry_behavior: Literal["same_file_for_resume"]


def _drive_grant(user: User) -> dict:
    metadata = user.user_metadata
    if not isinstance(metadata, dict):
        return {}
    grant = metadata.get(_METADATA_KEY)
    return dict(grant) if isinstance(grant, dict) else {}


def _stored_access_token(user: User) -> str:
    grant = _drive_grant(user)
    scopes = grant.get("scopes") if isinstance(grant.get("scopes"), list) else []
    if GOOGLE_DRIVE_SCOPE not in scopes:
        raise HTTPException(status_code=400, detail="Google Drive permission is missing; please reconnect")
    encrypted = grant.get("access_token")
    if not isinstance(encrypted, str) or not encrypted:
        raise HTTPException(status_code=400, detail="Google Drive is not connected")
    try:
        token = encryption_service.decrypt(encrypted)
    except Exception as exc:
        logger.warning("Google Drive credential decrypt failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Google Drive session expired; please reconnect") from exc
    if not token:
        raise HTTPException(status_code=401, detail="Google Drive session expired; please reconnect")
    return token


def _persist_drive_access_token(user: User, db: AsyncSession, access_token: str) -> None:
    metadata = dict(user.user_metadata or {}) if isinstance(user.user_metadata, dict) else {}
    grant = dict(metadata.get(_METADATA_KEY) or {})
    grant["access_token"] = encryption_service.encrypt(access_token)
    metadata[_METADATA_KEY] = grant
    user.user_metadata = metadata


async def _refresh_drive_token(user: User, db: AsyncSession) -> str:
    encrypted_refresh = _drive_grant(user).get("refresh_token")
    if not isinstance(encrypted_refresh, str) or not encrypted_refresh:
        raise HTTPException(status_code=401, detail="Google Drive session expired; please reconnect")
    try:
        refresh_token = encryption_service.decrypt(encrypted_refresh)
        access_token = await google_drive_service.refresh_access_token(
            refresh_token,
            client_id=settings.GOOGLE_DRIVE_CLIENT_ID,
            client_secret=settings.GOOGLE_DRIVE_CLIENT_SECRET,
        )
    except GoogleDriveProviderError as exc:
        if exc.status_code in (400, 401, 403):
            raise HTTPException(status_code=401, detail="Google Drive session expired; please reconnect") from exc
        raise HTTPException(status_code=503, detail="Google Drive is temporarily unavailable") from exc
    except Exception as exc:
        logger.warning("Google Drive token refresh failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Google Drive session expired; please reconnect") from exc

    _persist_drive_access_token(user, db, access_token)
    await db.commit()
    return access_token


async def _run_with_drive_token(user: User, db: AsyncSession, operation):
    token = _stored_access_token(user)
    try:
        return await operation(token)
    except GoogleDriveProviderError as exc:
        if exc.status_code != 401:
            raise
        token = await _refresh_drive_token(user, db)
        return await operation(token)


def _provider_failure(exc: GoogleDriveProviderError) -> HTTPException:
    if exc.status_code in (401, 403):
        return HTTPException(status_code=502, detail="Google Drive authorization failed; please reconnect")
    if exc.status_code == 429 or (exc.status_code is not None and exc.status_code >= 500):
        return HTTPException(status_code=503, detail="Google Drive is temporarily unavailable; please retry")
    return HTTPException(status_code=502, detail="Google Drive rejected the export; please retry")


async def _acquire_export_lock(user_id: str, resume_id: str) -> tuple[str, str]:
    """Claim one user/resume export without holding a database lock."""
    key = f"latexy:google-drive:export:{user_id}:{resume_id}"
    token = secrets.token_urlsafe(24)
    try:
        redis = await get_redis_cache_client()
        acquired = await redis.set(key, token, nx=True, ex=_EXPORT_LOCK_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Google Drive export lock unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Google Drive export is temporarily unavailable") from exc
    if not acquired:
        raise HTTPException(status_code=409, detail="An export for this resume is already in progress")
    return key, token


async def _release_export_lock(key: str, token: str) -> None:
    """Release only our lease; an expired/replaced lease must survive."""
    try:
        redis = await get_redis_cache_client()
        await redis.eval(_RELEASE_EXPORT_LOCK, 1, key, token)
    except Exception as exc:  # pragma: no cover - lease expiry is the fallback
        logger.warning("Google Drive export lock release failed (%s)", type(exc).__name__)


def _error_redirect(reason: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.FRONTEND_URL}/settings?google_drive=error&reason={urllib.parse.quote(reason)}"
    )


@router.post(
    "/connect",
    response_model=GoogleDriveOAuthStartResponse,
    dependencies=[Depends(require_feature("integration_google_drive"))],
)
async def google_drive_connect(user_id: str = Depends(get_current_user_required)):
    """Create an opaque OAuth state bound to the signed-in user."""
    if not all(
        (
            settings.GOOGLE_DRIVE_CLIENT_ID,
            settings.GOOGLE_DRIVE_CLIENT_SECRET,
            settings.GOOGLE_DRIVE_REDIRECT_URI,
        )
    ):
        raise HTTPException(
            status_code=503,
            detail="Google Drive integration is not configured. Set the Google Drive OAuth settings.",
        )

    state = secrets.token_urlsafe(32)
    await cache_manager.set(f"gdrive:oauth:{state}", {"user_id": user_id}, ttl=_STATE_TTL_SECONDS)
    params = urllib.parse.urlencode(
        {
            "client_id": settings.GOOGLE_DRIVE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_DRIVE_REDIRECT_URI,
            "response_type": "code",
            "scope": GOOGLE_DRIVE_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return GoogleDriveOAuthStartResponse(authorization_url=f"{GOOGLE_DRIVE_AUTH_URL}?{params}")


@router.get("/callback")
async def google_drive_callback(
    code: Optional[str] = Query(None, max_length=2048),
    state: str = Query("", max_length=256),
    error: Optional[str] = Query(None, max_length=128),
):
    """Consume OAuth state and issue a short-lived authenticated ticket."""
    if not state:
        return _error_redirect("missing_state")
    oauth_state = await cache_manager.pop(f"gdrive:oauth:{state}")
    if not isinstance(oauth_state, dict) or not oauth_state.get("user_id"):
        return _error_redirect("invalid_state")
    if error:
        return _error_redirect("access_denied" if error == "access_denied" else "provider_error")
    if not code:
        return _error_redirect("missing_code")

    ticket = secrets.token_urlsafe(32)
    await cache_manager.set(
        f"gdrive:complete:{ticket}",
        {"user_id": str(oauth_state["user_id"]), "code": code},
        ttl=_TICKET_TTL_SECONDS,
    )
    query = urllib.parse.urlencode({"google_drive": "complete", "ticket": ticket})
    return RedirectResponse(f"{settings.FRONTEND_URL}/settings?{query}")


@router.post("/complete")
async def google_drive_complete(
    body: GoogleDriveOAuthCompleteRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Exchange a ticket's code and persist encrypted credentials."""
    ticket = body.ticket.strip()
    if not ticket:
        raise HTTPException(status_code=400, detail="Missing Google Drive completion ticket")
    # Peek before consuming so a ticket stolen by a different authenticated
    # user is rejected without destroying the legitimate owner's one-time
    # completion. The ownership check is repeated after the atomic pop to
    # tolerate a concurrent legitimate completion racing this request.
    ticket_key = f"gdrive:complete:{ticket}"
    pending = await cache_manager.get(ticket_key)
    if not isinstance(pending, dict):
        raise HTTPException(status_code=400, detail="Google Drive completion ticket is invalid or expired")
    intended_user_id = str(pending.get("user_id") or "")
    if not intended_user_id or not secrets.compare_digest(intended_user_id, user_id):
        logger.warning("Rejected cross-user Google Drive OAuth completion")
        raise HTTPException(status_code=403, detail="Google Drive connection belongs to a different user")

    # Validate local configuration before consuming the one-time ticket. A
    # transiently incomplete deployment must not destroy a valid completion.
    if not all(
        (
            settings.GOOGLE_DRIVE_CLIENT_ID,
            settings.GOOGLE_DRIVE_CLIENT_SECRET,
            settings.GOOGLE_DRIVE_REDIRECT_URI,
        )
    ):
        raise HTTPException(status_code=503, detail="Google Drive integration is not configured")

    completion = await cache_manager.pop(ticket_key)
    if not isinstance(completion, dict):
        raise HTTPException(status_code=400, detail="Google Drive completion ticket is invalid or expired")
    intended_user_id = str(completion.get("user_id") or "")
    code = str(completion.get("code") or "")
    if not intended_user_id or not code:
        raise HTTPException(status_code=400, detail="Google Drive completion ticket is invalid or expired")
    if not secrets.compare_digest(intended_user_id, user_id):
        logger.warning("Rejected cross-user Google Drive OAuth completion")
        raise HTTPException(status_code=403, detail="Google Drive connection belongs to a different user")
    try:
        tokens = await google_drive_service.exchange_code(
            code,
            client_id=settings.GOOGLE_DRIVE_CLIENT_ID,
            client_secret=settings.GOOGLE_DRIVE_CLIENT_SECRET,
            redirect_uri=settings.GOOGLE_DRIVE_REDIRECT_URI,
        )
    except GoogleDriveProviderError as exc:
        raise _provider_failure(exc) from exc

    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise HTTPException(status_code=502, detail="Google Drive authorization returned no access token")
    raw_scope = tokens.get("scope")
    scopes = {part.strip() for part in str(raw_scope or "").replace(",", " ").split() if part.strip()}
    if GOOGLE_DRIVE_SCOPE not in scopes:
        raise HTTPException(status_code=502, detail="Google Drive authorization did not grant file export permission")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    previous = _drive_grant(user)
    new_refresh_token = tokens.get("refresh_token")
    if isinstance(new_refresh_token, str) and new_refresh_token:
        encrypted_refresh_token = encryption_service.encrypt(new_refresh_token)
    else:
        # Google omits refresh_token on some reconnects. Preserve the already
        # encrypted value verbatim; decrypting then re-encrypting it would
        # accidentally encrypt ciphertext and break future refreshes.
        encrypted_refresh_token = previous.get("refresh_token")
    if not isinstance(encrypted_refresh_token, str) or not encrypted_refresh_token:
        raise HTTPException(status_code=502, detail="Google Drive authorization did not return a refresh token")
    metadata = dict(user.user_metadata or {}) if isinstance(user.user_metadata, dict) else {}
    metadata[_METADATA_KEY] = {
        "access_token": encryption_service.encrypt(access_token),
        "refresh_token": encrypted_refresh_token,
        "scopes": [GOOGLE_DRIVE_SCOPE],
    }
    user.user_metadata = metadata
    await db.commit()
    return {"success": True, "message": "Google Drive connected"}


@router.get("/status", response_model=GoogleDriveStatusResponse)
async def google_drive_status(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    grant = _drive_grant(user)
    scopes = grant.get("scopes") if isinstance(grant.get("scopes"), list) else []
    connected = (
        isinstance(grant.get("access_token"), str)
        and bool(grant.get("access_token"))
        and GOOGLE_DRIVE_SCOPE in scopes
    )
    return GoogleDriveStatusResponse(
        connected=connected,
        scope="drive.file" if GOOGLE_DRIVE_SCOPE in scopes else None,
    )


@router.delete("/disconnect")
async def google_drive_disconnect(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Revoke the current grant when possible, then clear local credentials."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    grant = _drive_grant(user)
    encrypted_access = grant.get("access_token")
    if isinstance(encrypted_access, str) and encrypted_access:
        try:
            access_token = encryption_service.decrypt(encrypted_access)
            await google_drive_service.revoke_token(access_token)
        except GoogleDriveProviderError as exc:
            # An already-invalid grant is effectively revoked. Keep the local
            # disconnect idempotent while surfacing network/provider outages.
            if exc.status_code not in (400, 401, 403):
                raise HTTPException(status_code=503, detail="Google Drive is unavailable; please try again") from exc
        except Exception as exc:
            logger.warning("Google Drive disconnect cleanup failed (%s)", type(exc).__name__)

    metadata = dict(user.user_metadata or {}) if isinstance(user.user_metadata, dict) else {}
    metadata.pop(_METADATA_KEY, None)
    user.user_metadata = metadata
    await db.commit()
    return {"success": True, "message": "Google Drive disconnected"}


@router.post(
    "/resumes/{resume_id}/export",
    response_model=GoogleDriveExportResponse,
    dependencies=[Depends(require_feature("integration_google_drive"))],
)
async def export_resume_to_google_drive(
    resume_id: str,
    body: GoogleDriveExportRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Create/update one deterministic app-owned Drive PDF for this resume."""
    del body
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    # Fail before reading the compiled artifact when the user has not connected
    # Drive; this avoids unnecessary storage access and makes the boundary
    # explicit before any provider operation is attempted.
    _stored_access_token(user)
    ensure_uuid(resume_id, "Resume not found")
    lock_key, lock_token = await _acquire_export_lock(user_id, resume_id)
    try:
        resume, _compilation, pdf_bytes = await _owned_compiled_pdf(
            resume_id,
            user_id,
            db,
            max_bytes=MAX_DRIVE_PDF_BYTES,
            too_large_detail="Compiled PDF is too large to export",
        )
        filename = f"Latexy resume {resume.id}.pdf"
        try:
            action = await _run_with_drive_token(
                user,
                db,
                lambda token: google_drive_service.upload_pdf(
                    token,
                    filename=filename,
                    pdf_bytes=pdf_bytes,
                    resume_key=str(resume.id),
                ),
            )
        except GoogleDriveProviderError as exc:
            raise _provider_failure(exc) from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail="Google Drive is temporarily unavailable; please retry") from exc
    except GoogleDriveProviderError as exc:
        raise _provider_failure(exc) from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Google Drive is temporarily unavailable; please retry") from exc
    finally:
        await _release_export_lock(lock_key, lock_token)

    return GoogleDriveExportResponse(
        success=True,
        provider="google_drive",
        action=action,
        retry_behavior="same_file_for_resume",
    )
