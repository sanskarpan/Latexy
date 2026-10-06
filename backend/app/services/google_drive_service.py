"""Small, bounded Google Drive API client used by the export integration.

The client deliberately uses ``drive.file`` only.  That scope permits files
created by this app without granting Latexy access to a user's existing Drive
library.  Tokens are supplied by the route layer and are never logged or
returned by this module.
"""

from __future__ import annotations

import json
import re
import secrets
from typing import Any

import httpx

GOOGLE_DRIVE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_DRIVE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_DRIVE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
GOOGLE_DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_DRIVE_APP_PROPERTY = "latexy_resume_id"

_SAFE_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_SAFE_PROPERTY_VALUE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_RESPONSE_BYTES = 512 * 1024


class GoogleDriveProviderError(RuntimeError):
    """Provider failure with only safe, metadata-level details."""

    def __init__(self, operation: str, status_code: int | None = None):
        super().__init__(operation)
        self.operation = operation
        self.status_code = status_code


class GoogleDriveService:
    """Async wrapper for the narrow Google Drive files API surface."""

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _json_response(response: httpx.Response, operation: str) -> dict[str, Any]:
        if response.status_code < 200 or response.status_code >= 300:
            raise GoogleDriveProviderError(operation, response.status_code)
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise GoogleDriveProviderError(f"{operation}_response_too_large", response.status_code)
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise GoogleDriveProviderError(f"{operation}_invalid_response", response.status_code) from exc
        if not isinstance(payload, dict):
            raise GoogleDriveProviderError(f"{operation}_invalid_response", response.status_code)
        return payload

    async def exchange_code(
        self,
        code: str,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        """Exchange an authorization code without exposing provider details."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    GOOGLE_DRIVE_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
        except httpx.RequestError as exc:
            raise GoogleDriveProviderError("token_exchange_network") from exc
        payload = self._json_response(response, "token_exchange")
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise GoogleDriveProviderError("token_exchange_missing_access_token", response.status_code)
        return payload

    async def refresh_access_token(
        self,
        refresh_token: str,
        *,
        client_id: str,
        client_secret: str,
    ) -> str:
        """Refresh an expired access token."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    GOOGLE_DRIVE_TOKEN_URL,
                    data={
                        "refresh_token": refresh_token,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "grant_type": "refresh_token",
                    },
                )
        except httpx.RequestError as exc:
            raise GoogleDriveProviderError("token_refresh_network") from exc
        payload = self._json_response(response, "token_refresh")
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise GoogleDriveProviderError("token_refresh_missing_access_token", response.status_code)
        return access_token

    async def revoke_token(self, token: str) -> None:
        """Ask Google to revoke a grant; no response body is retained."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    GOOGLE_DRIVE_REVOKE_URL,
                    data={"token": token},
                )
        except httpx.RequestError as exc:
            raise GoogleDriveProviderError("token_revoke_network") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise GoogleDriveProviderError("token_revoke", response.status_code)

    @staticmethod
    def _multipart_body(metadata: dict[str, Any], pdf_bytes: bytes) -> tuple[bytes, str]:
        # A per-request boundary prevents a PDF containing a predictable marker
        # from being interpreted as a second MIME part.
        boundary = f"latexy-drive-{secrets.token_hex(16)}"
        metadata_bytes = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
        body = b"".join(
            (
                f"--{boundary}\r\n".encode(),
                b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
                metadata_bytes,
                b"\r\n",
                f"--{boundary}\r\n".encode(),
                b"Content-Type: application/pdf\r\n\r\n",
                pdf_bytes,
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            )
        )
        return body, f"multipart/related; boundary={boundary}"

    async def upload_pdf(
        self,
        token: str,
        *,
        filename: str,
        pdf_bytes: bytes,
        resume_key: str,
    ) -> str:
        """Create or update the app-owned file for one resume.

        Searching by an app property makes retries update the same Drive file.
        Multiple matches are rejected instead of guessing, so a prior race or
        manually-created duplicate cannot silently produce an ambiguous export.
        """
        if not filename or any(char in filename for char in "\\/\r\n") or len(filename) > 255:
            raise ValueError("invalid export filename")
        if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError("invalid PDF bytes")
        if not _SAFE_PROPERTY_VALUE.fullmatch(resume_key):
            raise ValueError("invalid resume key")

        query = (
            "trashed = false and appProperties has "
            f"{{ key='{GOOGLE_DRIVE_APP_PROPERTY}' and value='{resume_key}' }}"
        )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                listing = await client.get(
                    GOOGLE_DRIVE_FILES_URL,
                    headers=self._headers(token),
                    params={"q": query, "spaces": "drive", "pageSize": 2, "fields": "files(id)"},
                )
                files_payload = self._json_response(listing, "file_lookup")
                files = files_payload.get("files")
                if not isinstance(files, list):
                    raise GoogleDriveProviderError("file_lookup_invalid_response", listing.status_code)
                if len(files) > 1:
                    raise GoogleDriveProviderError("duplicate_resume_files", 409)

                metadata = {
                    "name": filename,
                    "mimeType": "application/pdf",
                    "appProperties": {GOOGLE_DRIVE_APP_PROPERTY: resume_key},
                }
                body, content_type = self._multipart_body(metadata, pdf_bytes)
                headers = {**self._headers(token), "Content-Type": content_type}
                if files:
                    file_id = files[0].get("id") if isinstance(files[0], dict) else None
                    if not isinstance(file_id, str) or not _SAFE_FILE_ID.fullmatch(file_id):
                        raise GoogleDriveProviderError("file_lookup_invalid_id", 502)
                    response = await client.patch(
                        f"{GOOGLE_DRIVE_UPLOAD_URL}/{file_id}",
                        params={"uploadType": "multipart"},
                        headers=headers,
                        content=body,
                    )
                    self._json_response(response, "file_update")
                    return "updated"

                response = await client.post(
                    GOOGLE_DRIVE_UPLOAD_URL,
                    params={"uploadType": "multipart"},
                    headers=headers,
                    content=body,
                )
                payload = self._json_response(response, "file_create")
                file_id = payload.get("id")
                if not isinstance(file_id, str) or not _SAFE_FILE_ID.fullmatch(file_id):
                    raise GoogleDriveProviderError("file_create_invalid_id", response.status_code)
                return "created"
        except httpx.RequestError as exc:
            raise GoogleDriveProviderError("file_upload_network") from exc


google_drive_service = GoogleDriveService()
