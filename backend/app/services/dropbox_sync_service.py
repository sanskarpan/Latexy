"""Dropbox sync service — uploads and downloads LaTeX files via the Dropbox API (Feature 77)."""

import json

import httpx

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)

DROPBOX_API_URL = "https://api.dropboxapi.com/2"
DROPBOX_CONTENT_URL = "https://content.dropboxapi.com/2"
DROPBOX_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"


class DropboxSyncService:
    """Thin async wrapper around the Dropbox API v2."""

    # ── Auth headers ─────────────────────────────────────────────────────────

    def _auth_headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    # ── Token management ─────────────────────────────────────────────────────

    async def refresh_access_token(self, refresh_token: str) -> str:
        """Exchange a refresh token for a new short-lived access token.

        Dropbox access tokens (when issued with token_access_type=offline) expire
        after 4 hours.  Call this before any API operation when the stored access
        token may be stale.  Returns the new access_token string.
        """
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                DROPBOX_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": settings.DROPBOX_APP_KEY,
                    "client_secret": settings.DROPBOX_APP_SECRET,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["access_token"]

    # ── Account info ─────────────────────────────────────────────────────────

    async def get_account(self, token: str) -> dict:
        """Fetch the authenticated Dropbox user's account info.

        Returns a dict with at least:
            account_id   — unique user identifier (e.g. "dbid:AAH…")
            name         — sub-dict with display_name, given_name, etc.
            email        — user email
        """
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{DROPBOX_API_URL}/users/get_current_account",
                headers={**self._auth_headers(token), "Content-Type": "application/json"},
                content=b"null",
            )
            resp.raise_for_status()
            return resp.json()

    # ── File upload ──────────────────────────────────────────────────────────

    async def upload_file(self, token: str, path: str, content: str) -> dict:
        """Upload (create or overwrite) a file at *path* in the user's Dropbox.

        Args:
            token:   valid Dropbox access token
            path:    absolute Dropbox path, e.g. "/Latexy/abc123.tex"
            content: UTF-8 text content to write

        Returns the Dropbox file metadata dict on success.
        """
        api_arg = json.dumps({
            "path": path,
            "mode": "overwrite",
            "autorename": False,
            "mute": True,   # suppress desktop notifications for the user
        })
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{DROPBOX_CONTENT_URL}/files/upload",
                headers={
                    **self._auth_headers(token),
                    "Content-Type": "application/octet-stream",
                    "Dropbox-API-Arg": api_arg,
                },
                content=content.encode("utf-8"),
            )
            resp.raise_for_status()
            return resp.json()

    # ── File download ────────────────────────────────────────────────────────

    async def download_file(self, token: str, path: str) -> str:
        """Download a file from the user's Dropbox and return its text content.

        Args:
            token: valid Dropbox access token
            path:  absolute Dropbox path, e.g. "/Latexy/abc123.tex"

        Returns the decoded UTF-8 file content string.
        Raises httpx.HTTPStatusError (404) if the file does not exist.
        """
        api_arg = json.dumps({"path": path})
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{DROPBOX_CONTENT_URL}/files/download",
                headers={
                    **self._auth_headers(token),
                    "Dropbox-API-Arg": api_arg,
                },
            )
            resp.raise_for_status()
            return resp.text


dropbox_sync_service = DropboxSyncService()
