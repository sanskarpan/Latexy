"""Mendeley OAuth 2.0 integration + BibTeX import (Feature 42)."""

import secrets
import urllib.parse
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import cache_manager
from ..database.connection import get_db
from ..database.models import Resume, User
from ..middleware.auth_middleware import get_current_user_required
from ..services.encryption_service import encryption_service

logger = get_logger(__name__)

router = APIRouter(prefix="/mendeley", tags=["mendeley"])

_MENDELEY_AUTH_URL = "https://api.mendeley.com/oauth/authorize"
_MENDELEY_TOKEN_URL = "https://api.mendeley.com/oauth/token"
_MENDELEY_DOCS_URL = "https://api.mendeley.com/documents"

# ── Schemas ──────────────────────────────────────────────────────────────────


class MendeleyStatusResponse(BaseModel):
    connected: bool
    name: Optional[str] = None


class MendeleyImportRequest(BaseModel):
    resume_id: str
    group_id: Optional[str] = None


class MendeleyImportResponse(BaseModel):
    success: bool
    entries_count: int
    bibtex: str
    message: str


# ── OAuth flow ───────────────────────────────────────────────────────────────


@router.get("/connect")
async def mendeley_connect(
    user_id: str = Depends(get_current_user_required),
):
    """Redirect to Mendeley OAuth 2.0 authorization."""
    if not settings.MENDELEY_CLIENT_ID or not settings.MENDELEY_CLIENT_SECRET or not settings.MENDELEY_REDIRECT_URI:
        raise HTTPException(
            status_code=503,
            detail="Mendeley integration is not configured. Set MENDELEY_CLIENT_ID, MENDELEY_CLIENT_SECRET, and MENDELEY_REDIRECT_URI.",
        )

    state = secrets.token_urlsafe(32)
    await cache_manager.set(f"mendeley:state:{state}", user_id, ttl=600)

    params = urllib.parse.urlencode({
        "client_id": settings.MENDELEY_CLIENT_ID,
        "redirect_uri": settings.MENDELEY_REDIRECT_URI,
        "response_type": "code",
        "scope": "all",
        "state": state,
    })
    return RedirectResponse(f"{_MENDELEY_AUTH_URL}?{params}")


@router.get("/callback")
async def mendeley_callback(
    code: str = Query(...),
    state: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """Exchange code for access token and store on user."""
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter")

    user_id = await cache_manager.get(f"mendeley:state:{state}")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired Mendeley OAuth state")
    await cache_manager.delete(f"mendeley:state:{state}")

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(
                _MENDELEY_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.MENDELEY_REDIRECT_URI,
                },
                auth=(settings.MENDELEY_CLIENT_ID, settings.MENDELEY_CLIENT_SECRET),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(f"Mendeley token exchange error: {exc.response.text}")
            raise HTTPException(status_code=502, detail="Failed to exchange Mendeley access token")
        except httpx.RequestError as exc:
            logger.error(f"Mendeley connection error: {exc}")
            raise HTTPException(status_code=502, detail="Mendeley is unavailable")

    token_data = resp.json()
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")

    if not access_token:
        raise HTTPException(status_code=502, detail="Invalid Mendeley token response")

    # Get user profile for display name
    display_name = ""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            profile_resp = await client.get(
                "https://api.mendeley.com/profiles/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if profile_resp.status_code == 200:
                pdata = profile_resp.json()
                display_name = pdata.get("display_name", "")
    except Exception:
        pass

    # Encrypt and store
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    meta = dict(user.user_metadata or {})
    meta["mendeley_token"] = encryption_service.encrypt(access_token)
    if refresh_token:
        meta["mendeley_refresh_token"] = encryption_service.encrypt(refresh_token)
    if display_name:
        meta["mendeley_name"] = display_name
    user.user_metadata = meta
    await db.commit()

    return RedirectResponse(f"{settings.FRONTEND_URL}/settings?mendeley=connected")


@router.get("/status", response_model=MendeleyStatusResponse)
async def mendeley_status(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Check if the user has a connected Mendeley account."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    meta = user.user_metadata or {}
    connected = bool(meta.get("mendeley_token"))
    return MendeleyStatusResponse(
        connected=connected,
        name=meta.get("mendeley_name") if connected else None,
    )


@router.delete("/disconnect")
async def mendeley_disconnect(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Clear Mendeley token."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    meta = dict(user.user_metadata or {})
    meta.pop("mendeley_token", None)
    meta.pop("mendeley_refresh_token", None)
    meta.pop("mendeley_name", None)
    user.user_metadata = meta
    await db.commit()
    return {"success": True, "message": "Mendeley disconnected"}


async def _get_mendeley_token(user: User, db: AsyncSession) -> str:
    """Return a valid access token, refreshing if needed."""
    meta = dict(user.user_metadata or {})
    encrypted = meta.get("mendeley_token")
    if not encrypted:
        raise HTTPException(status_code=401, detail="Mendeley not connected")

    try:
        token = encryption_service.decrypt(encrypted)
    except Exception:
        raise HTTPException(status_code=401, detail="Mendeley token is corrupted. Please reconnect in Settings.")

    # Try a lightweight call to see if token is valid
    async with httpx.AsyncClient(timeout=10) as client:
        probe = await client.get(
            "https://api.mendeley.com/profiles/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    if probe.status_code == 401:
        # Attempt refresh
        encrypted_refresh = meta.get("mendeley_refresh_token")
        if not encrypted_refresh:
            raise HTTPException(
                status_code=401,
                detail="Mendeley token expired. Please reconnect in Settings.",
            )
        try:
            refresh_token = encryption_service.decrypt(encrypted_refresh)
        except Exception:
            raise HTTPException(status_code=401, detail="Mendeley token is corrupted. Please reconnect in Settings.")
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.post(
                    _MENDELEY_TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    auth=(settings.MENDELEY_CLIENT_ID, settings.MENDELEY_CLIENT_SECRET),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                raise HTTPException(
                    status_code=401,
                    detail="Mendeley token expired and refresh failed. Please reconnect in Settings.",
                )
            except httpx.RequestError as exc:
                logger.error(f"Mendeley connection error during token refresh: {exc}")
                raise HTTPException(status_code=502, detail="Mendeley is unavailable, please try again")

        data = resp.json()
        new_token = data.get("access_token", "")
        new_refresh = data.get("refresh_token", refresh_token)
        if not new_token:
            raise HTTPException(status_code=502, detail="Mendeley refresh returned no token")

        meta["mendeley_token"] = encryption_service.encrypt(new_token)
        meta["mendeley_refresh_token"] = encryption_service.encrypt(new_refresh)
        user.user_metadata = meta
        await db.commit()
        token = new_token

    return token


@router.post("/import", response_model=MendeleyImportResponse)
async def mendeley_import(
    body: MendeleyImportRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Import BibTeX from Mendeley and store in resume metadata."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    token = await _get_mendeley_token(user, db)

    # Verify resume ownership
    resume_result = await db.execute(
        select(Resume).where(Resume.id == body.resume_id, Resume.user_id == user_id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Fetch documents as BibTeX
    params: dict = {"limit": 500, "view": "bib"}
    if body.group_id:
        params["group_id"] = body.group_id

    bibtex_entries: list[str] = []

    async with httpx.AsyncClient(timeout=30) as client:
        url: Optional[str] = _MENDELEY_DOCS_URL
        while url:
            try:
                resp = await client.get(
                    url,
                    params=params if url == _MENDELEY_DOCS_URL else None,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/x-bibtex",
                    },
                )
                if resp.status_code == 403:
                    raise HTTPException(
                        status_code=401,
                        detail="Mendeley token invalid. Please reconnect in Settings.",
                    )
                resp.raise_for_status()
            except HTTPException:
                raise
            except httpx.HTTPStatusError as exc:
                logger.error(f"Mendeley API error: {exc.response.status_code}")
                raise HTTPException(
                    status_code=502,
                    detail=f"Mendeley API returned error {exc.response.status_code}",
                )
            except httpx.RequestError as exc:
                logger.error(f"Mendeley connection error: {exc}")
                raise HTTPException(status_code=502, detail="Mendeley is unavailable")

            page_bibtex = resp.text.strip()
            if page_bibtex:
                bibtex_entries.append(page_bibtex)

            # Mendeley pagination via Link header
            link_header = resp.headers.get("Link", "")
            url = None
            for part in link_header.split(","):
                part = part.strip()
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>")
                    break

    bibtex = "\n\n".join(bibtex_entries)
    entry_count = bibtex.count("\n@") + (1 if bibtex.startswith("@") else 0)

    rm = dict(resume.resume_settings or {})
    rm["bibtex"] = bibtex
    resume.resume_settings = rm
    await db.commit()

    return MendeleyImportResponse(
        success=True,
        entries_count=entry_count,
        bibtex=bibtex,
        message=f"Imported {entry_count} BibTeX entries from Mendeley",
    )
