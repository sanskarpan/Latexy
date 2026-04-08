"""Zotero OAuth 1.0a integration + BibTeX import (Feature 42)."""

import base64
import hashlib
import hmac
import secrets
import time
import urllib.parse
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
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

router = APIRouter(prefix="/zotero", tags=["zotero"])

_ZOTERO_REQUEST_TOKEN_URL = "https://www.zotero.org/oauth/request"
_ZOTERO_AUTHORIZE_URL = "https://www.zotero.org/oauth/authorize"
_ZOTERO_ACCESS_TOKEN_URL = "https://www.zotero.org/oauth/access"
_ZOTERO_API_BASE = "https://api.zotero.org"

# ── OAuth 1.0a helpers ───────────────────────────────────────────────────────


def _penc(s: str) -> str:
    """Percent-encode per RFC 3986."""
    return urllib.parse.quote(str(s), safe="")


def _oauth1_signature(
    method: str,
    url: str,
    oauth_params: dict,
    extra_params: dict,
    consumer_secret: str,
    token_secret: str = "",
) -> str:
    """Compute HMAC-SHA1 OAuth 1.0a signature."""
    all_params = {**oauth_params, **extra_params}
    normalized = "&".join(
        f"{_penc(k)}={_penc(v)}" for k, v in sorted(all_params.items())
    )
    base = "&".join([_penc(method.upper()), _penc(url), _penc(normalized)])
    signing_key = f"{_penc(consumer_secret)}&{_penc(token_secret)}"
    sig = hmac.new(signing_key.encode(), base.encode(), hashlib.sha1)
    return base64.b64encode(sig.digest()).decode()


def _oauth1_header(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    token: str = "",
    token_secret: str = "",
    extra_params: Optional[dict] = None,
) -> str:
    """Build OAuth Authorization header string."""
    oauth_params: dict = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_version": "1.0",
    }
    if token:
        oauth_params["oauth_token"] = token

    sig = _oauth1_signature(
        method, url, oauth_params, extra_params or {}, consumer_secret, token_secret
    )
    oauth_params["oauth_signature"] = sig

    parts = ", ".join(
        f'{k}="{_penc(v)}"' for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {parts}"


# ── Schemas ──────────────────────────────────────────────────────────────────


class ZoteroStatusResponse(BaseModel):
    connected: bool
    username: Optional[str] = None
    user_id: Optional[str] = None


class ZoteroImportRequest(BaseModel):
    resume_id: str
    collection_key: Optional[str] = Field(None, max_length=20)


class ZoteroImportResponse(BaseModel):
    success: bool
    entries_count: int
    bibtex: str
    message: str


class ZoteroCollectionsResponse(BaseModel):
    collections: list


# ── OAuth flow ───────────────────────────────────────────────────────────────


@router.get("/connect")
async def zotero_connect(
    user_id: str = Depends(get_current_user_required),
):
    """Step 1: Get request token and redirect to Zotero authorization."""
    if not settings.ZOTERO_CLIENT_KEY or not settings.ZOTERO_CLIENT_SECRET or not settings.ZOTERO_REDIRECT_URI:
        raise HTTPException(
            status_code=503,
            detail="Zotero integration is not configured. Set ZOTERO_CLIENT_KEY, ZOTERO_CLIENT_SECRET, and ZOTERO_REDIRECT_URI.",
        )

    # Build OAuth header for request-token call (callback in extra_params for signature)
    callback_url = settings.ZOTERO_REDIRECT_URI
    extra = {"oauth_callback": callback_url}
    auth_header = _oauth1_header(
        "POST",
        _ZOTERO_REQUEST_TOKEN_URL,
        settings.ZOTERO_CLIENT_KEY,
        settings.ZOTERO_CLIENT_SECRET,
        extra_params=extra,
    )
    # Also include callback in the body
    body = {"oauth_callback": callback_url}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(
                _ZOTERO_REQUEST_TOKEN_URL,
                data=body,
                headers={"Authorization": auth_header},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(f"Zotero request token error: {exc.response.text}")
            raise HTTPException(
                status_code=502, detail="Failed to get Zotero request token"
            )
        except httpx.RequestError as exc:
            logger.error(f"Zotero connection error: {exc}")
            raise HTTPException(
                status_code=502, detail="Zotero is unavailable, please try again"
            )

    params = dict(urllib.parse.parse_qsl(resp.text))
    request_token = params.get("oauth_token", "")
    request_token_secret = params.get("oauth_token_secret", "")

    if not request_token:
        logger.error(f"Zotero returned no request_token: {resp.text}")
        raise HTTPException(status_code=502, detail="Invalid response from Zotero OAuth")

    # Store (user_id, token_secret) in Redis — 10-min TTL
    await cache_manager.set(
        f"zotero:reqsecret:{request_token}",
        f"{user_id}:{request_token_secret}",
        ttl=600,
    )

    return RedirectResponse(
        f"{_ZOTERO_AUTHORIZE_URL}?oauth_token={request_token}"
    )


@router.get("/callback")
async def zotero_callback(
    oauth_token: str = Query(...),
    oauth_verifier: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Step 2: Exchange verifier for access token, store on user."""
    cached = await cache_manager.get(f"zotero:reqsecret:{oauth_token}")
    if not cached:
        raise HTTPException(
            status_code=400, detail="Invalid or expired Zotero OAuth state"
        )
    await cache_manager.delete(f"zotero:reqsecret:{oauth_token}")

    user_id, request_token_secret = cached.split(":", 1)

    # Build OAuth header for access-token exchange
    extra = {"oauth_verifier": oauth_verifier}
    auth_header = _oauth1_header(
        "POST",
        _ZOTERO_ACCESS_TOKEN_URL,
        settings.ZOTERO_CLIENT_KEY,
        settings.ZOTERO_CLIENT_SECRET,
        token=oauth_token,
        token_secret=request_token_secret,
        extra_params=extra,
    )

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(
                _ZOTERO_ACCESS_TOKEN_URL,
                data={"oauth_verifier": oauth_verifier},
                headers={"Authorization": auth_header},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(f"Zotero access token error: {exc.response.text}")
            raise HTTPException(
                status_code=502, detail="Failed to exchange Zotero access token"
            )
        except httpx.RequestError as exc:
            logger.error(f"Zotero connection error during token exchange: {exc}")
            raise HTTPException(status_code=502, detail="Zotero is unavailable, please try again")

    params = dict(urllib.parse.parse_qsl(resp.text))
    access_token = params.get("oauth_token", "")
    # token_secret not used for Zotero API (it uses just the token as API key)
    zotero_user_id = params.get("userID", "")
    zotero_username = params.get("username", "")

    if not access_token or not zotero_user_id:
        raise HTTPException(status_code=502, detail="Invalid Zotero access token response")

    # Encrypt and store in user.user_metadata
    encrypted_token = encryption_service.encrypt(access_token)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    meta = dict(user.user_metadata or {})
    meta["zotero_token"] = encrypted_token
    meta["zotero_user_id"] = zotero_user_id
    meta["zotero_username"] = zotero_username
    user.user_metadata = meta
    await db.commit()

    return RedirectResponse(f"{settings.FRONTEND_URL}/settings?zotero=connected")


@router.get("/status", response_model=ZoteroStatusResponse)
async def zotero_status(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Check if the user has a connected Zotero account."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    meta = user.user_metadata or {}
    connected = bool(meta.get("zotero_token"))
    return ZoteroStatusResponse(
        connected=connected,
        username=meta.get("zotero_username") if connected else None,
        user_id=meta.get("zotero_user_id") if connected else None,
    )


@router.delete("/disconnect")
async def zotero_disconnect(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Clear Zotero token."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    meta = dict(user.user_metadata or {})
    meta.pop("zotero_token", None)
    meta.pop("zotero_user_id", None)
    meta.pop("zotero_username", None)
    user.user_metadata = meta
    await db.commit()
    return {"success": True, "message": "Zotero disconnected"}


@router.get("/collections", response_model=ZoteroCollectionsResponse)
async def zotero_collections(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """List user's Zotero collections."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    meta = user.user_metadata or {} if user else {}
    encrypted = meta.get("zotero_token")
    if not encrypted:
        raise HTTPException(status_code=401, detail="Zotero not connected")

    try:
        token = encryption_service.decrypt(encrypted)
    except Exception:
        raise HTTPException(status_code=401, detail="Zotero token is corrupted. Please reconnect in Settings.")
    zotero_user_id = meta.get("zotero_user_id", "")

    # Paginate collections — Zotero caps each page at 100
    collections: list[dict] = []
    start = 0
    limit = 100
    async with httpx.AsyncClient(timeout=15) as client:
        while True:
            url = f"{_ZOTERO_API_BASE}/users/{zotero_user_id}/collections?limit={limit}&start={start}"
            try:
                resp = await client.get(url, headers={"Zotero-API-Key": token})
                if resp.status_code == 403:
                    raise HTTPException(status_code=401, detail="Zotero token is invalid or expired. Please reconnect.")
                resp.raise_for_status()
            except HTTPException:
                raise
            except httpx.HTTPStatusError as exc:
                raise HTTPException(status_code=502, detail=f"Zotero API error: {exc.response.status_code}")
            except httpx.RequestError:
                raise HTTPException(status_code=502, detail="Zotero is unavailable")

            page = resp.json()
            collections.extend(
                {"key": c["key"], "name": c["data"]["name"]}
                for c in page
                if isinstance(c, dict) and "key" in c
            )
            total = int(resp.headers.get("Total-Results", len(page)))
            start += limit
            if start >= total:
                break
    return ZoteroCollectionsResponse(collections=collections)


@router.post("/import", response_model=ZoteroImportResponse)
async def zotero_import(
    body: ZoteroImportRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Import BibTeX from Zotero and store in resume metadata."""
    # Auth check
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    meta = user.user_metadata or {} if user else {}
    encrypted = meta.get("zotero_token")
    if not encrypted:
        raise HTTPException(status_code=401, detail="Zotero not connected. Go to Settings → Zotero to connect.")

    try:
        token = encryption_service.decrypt(encrypted)
    except Exception:
        raise HTTPException(status_code=401, detail="Zotero token is corrupted. Please reconnect in Settings.")
    zotero_user_id = meta.get("zotero_user_id", "")

    # Verify resume ownership
    resume_result = await db.execute(
        select(Resume).where(Resume.id == body.resume_id, Resume.user_id == user_id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Paginate items — Zotero BibTeX endpoint accepts start+limit
    base_path = (
        f"/users/{zotero_user_id}/collections/{body.collection_key}/items"
        if body.collection_key
        else f"/users/{zotero_user_id}/items"
    )
    bibtex_pages: list[str] = []
    start = 0
    limit = 100

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            url = f"{_ZOTERO_API_BASE}{base_path}?format=bibtex&limit={limit}&start={start}"
            try:
                resp = await client.get(url, headers={"Zotero-API-Key": token})
                if resp.status_code == 403:
                    raise HTTPException(
                        status_code=401,
                        detail="Zotero token is invalid or expired. Please reconnect in Settings.",
                    )
                if resp.status_code == 404:
                    raise HTTPException(status_code=404, detail="Zotero collection not found.")
                resp.raise_for_status()
            except HTTPException:
                raise
            except httpx.HTTPStatusError as exc:
                logger.error(f"Zotero API error during import: {exc.response.status_code} {exc.response.text[:200]}")
                raise HTTPException(
                    status_code=502,
                    detail=f"Zotero API returned error {exc.response.status_code}",
                )
            except httpx.RequestError as exc:
                logger.error(f"Zotero connection error: {exc}")
                raise HTTPException(status_code=502, detail="Zotero is unavailable, please try again")

            page_text = resp.text.strip()
            if page_text:
                bibtex_pages.append(page_text)
            total = int(resp.headers.get("Total-Results", len(bibtex_pages) * limit))
            start += limit
            if start >= total:
                break

    bibtex = "\n\n".join(bibtex_pages)
    # Count entries by counting @-type lines
    entry_count = bibtex.count("\n@") + (1 if bibtex.startswith("@") else 0)

    # Store in resume metadata
    rm = dict(resume.resume_settings or {})
    rm["bibtex"] = bibtex
    resume.resume_settings = rm
    await db.commit()

    return ZoteroImportResponse(
        success=True,
        entries_count=entry_count,
        bibtex=bibtex,
        message=f"Imported {entry_count} BibTeX entries from Zotero",
    )


@router.delete("/bibtex/{resume_id}")
async def clear_bibtex(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Remove stored BibTeX from a resume's metadata."""
    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    rm = dict(resume.resume_settings or {})
    rm.pop("bibtex", None)
    resume.resume_settings = rm
    await db.commit()
    return {"success": True}
