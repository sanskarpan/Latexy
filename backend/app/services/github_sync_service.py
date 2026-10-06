"""GitHub sync service — manages repos, pushes and pulls LaTeX files via GitHub API."""

import base64
from typing import Optional
from urllib.parse import quote

import httpx

from ..core.logging import get_logger

logger = get_logger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubSyncConflict(Exception):
    """The remote file changed since Latexy last observed it."""


class GitHubSyncService:
    """Thin wrapper around the GitHub Contents + Repos REST API."""

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @staticmethod
    def _repo_url(owner: str, repo: str, suffix: str = "") -> str:
        return (
            f"{GITHUB_API}/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
            f"{suffix}"
        )

    # ── Repo management ──────────────────────────────────────────────────

    async def ensure_repo(self, token: str, username: str, repo_name: str) -> None:
        """Create a private repo if it doesn't already exist."""
        async with httpx.AsyncClient(timeout=15) as client:
            # Check if repo exists
            resp = await client.get(
                self._repo_url(username, repo_name),
                headers=self._headers(token),
            )
            if resp.status_code == 200:
                return  # already exists

            # Create it
            resp = await client.post(
                f"{GITHUB_API}/user/repos",
                headers=self._headers(token),
                json={
                    "name": repo_name,
                    "private": True,
                    "description": "LaTeX resumes synced by Latexy",
                    "auto_init": True,
                },
            )
            if resp.status_code == 201:
                return
            if resp.status_code == 422:
                # GitHub returns 422 for many validation failures. Only treat it
                # as success when the specific reason is a name collision (the
                # repo already exists — e.g. a create/create race). Any other
                # 422 (invalid name, org limits, …) is a real failure.
                if self._is_name_already_exists(resp):
                    return
                logger.error("GitHub repo creation rejected with validation status 422")
            resp.raise_for_status()

    @staticmethod
    def _is_name_already_exists(resp: httpx.Response) -> bool:
        """True when a 422 body indicates the repo name is already taken."""
        try:
            errors = resp.json().get("errors", [])
        except Exception:
            return False
        for err in errors:
            if not isinstance(err, dict):
                continue
            message = (err.get("message") or "").lower()
            if err.get("field") == "name" and "already exists" in message:
                return True
        return False

    # ── Push (create or update) ──────────────────────────────────────────

    async def push_file(
        self,
        token: str,
        owner: str,
        repo: str,
        path: str,
        content: str,
        commit_message: str,
        expected_sha: Optional[str] = None,
    ) -> dict:
        """Create or update a file without overwriting an unseen revision.

        ``expected_sha`` is the blob revision remembered after the last Latexy
        push or pull. GitHub also checks the SHA during the PUT, which closes
        the race between our read and write.
        """
        url = self._repo_url(owner, repo, f"/contents/{quote(path, safe='/')}")
        headers = self._headers(token)
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

        async with httpx.AsyncClient(timeout=15) as client:
            get_resp = await client.get(url, headers=headers)
            remote_sha: Optional[str] = None
            if get_resp.status_code == 200:
                remote_sha = str(get_resp.json().get("sha") or "") or None
                if not remote_sha:
                    raise ValueError("GitHub file response did not include a blob SHA")
            elif get_resp.status_code != 404:
                get_resp.raise_for_status()

            if expected_sha:
                if remote_sha != expected_sha:
                    raise GitHubSyncConflict
            elif remote_sha:
                # This Latexy resume has never observed the existing file. Do
                # not claim it by overwriting content that may belong to a
                # previous installation or another client.
                raise GitHubSyncConflict

            payload: dict = {
                "message": commit_message,
                "content": encoded,
            }
            if remote_sha:
                payload["sha"] = remote_sha

            put_resp = await client.put(url, headers=headers, json=payload)
            if put_resp.status_code == 409:
                raise GitHubSyncConflict
            put_resp.raise_for_status()
            return put_resp.json()

    # ── Pull ─────────────────────────────────────────────────────────────

    async def pull_file(self, token: str, owner: str, repo: str, path: str) -> dict:
        """Fetch a file and return its decoded text plus immutable blob SHA."""
        url = self._repo_url(owner, repo, f"/contents/{quote(path, safe='/')}")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=self._headers(token))
            resp.raise_for_status()
            data = resp.json()
            if data.get("type") not in (None, "file"):
                raise ValueError("GitHub path is not a regular file")
            encoded = data.get("content")
            sha = str(data.get("sha") or "")
            if not isinstance(encoded, str) or not sha:
                raise ValueError("GitHub file response is incomplete")
            try:
                raw = base64.b64decode("".join(encoded.split()), validate=True)
                content = raw.decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError("GitHub file is not valid UTF-8 LaTeX source") from exc
            return {"content": content, "sha": sha}

    # ── User info ────────────────────────────────────────────────────────

    async def get_github_user(self, token: str) -> dict:
        """Fetch the authenticated GitHub user profile."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{GITHUB_API}/user", headers=self._headers(token)
            )
            resp.raise_for_status()
            return resp.json()

    async def revoke_oauth_grant(
        self,
        token: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        """Revoke this user's complete OAuth app authorization at GitHub.

        Revoking the grant (rather than only deleting Latexy's local token)
        invalidates every token this OAuth app holds for the user. A 404 is
        idempotent success: the user may already have revoked the app directly
        in GitHub settings.
        """
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.delete(
                f"{GITHUB_API}/applications/{quote(client_id, safe='')}/grant",
                auth=(client_id, client_secret),
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={"access_token": token},
            )
            if resp.status_code in (204, 404):
                return
            resp.raise_for_status()


github_sync_service = GitHubSyncService()
