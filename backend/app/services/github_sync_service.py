"""GitHub sync service — manages repos, pushes and pulls LaTeX files via GitHub API."""

import base64
from typing import Optional

import httpx

from ..core.logging import get_logger

logger = get_logger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubSyncService:
    """Thin wrapper around the GitHub Contents + Repos REST API."""

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ── Repo management ──────────────────────────────────────────────────

    async def ensure_repo(self, token: str, username: str, repo_name: str) -> None:
        """Create a private repo if it doesn't already exist."""
        async with httpx.AsyncClient(timeout=15) as client:
            # Check if repo exists
            resp = await client.get(
                f"{GITHUB_API}/repos/{username}/{repo_name}",
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
            if resp.status_code not in (201, 422):
                # 422 = already exists (race), treat as success
                resp.raise_for_status()

    # ── Push (create or update) ──────────────────────────────────────────

    async def push_file(
        self,
        token: str,
        owner: str,
        repo: str,
        path: str,
        content: str,
        commit_message: str,
    ) -> dict:
        """Push (create or update) a file via the GitHub Contents API."""
        url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
        headers = self._headers(token)
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

        async with httpx.AsyncClient(timeout=15) as client:
            # Get current SHA if file exists (required for updates)
            sha: Optional[str] = None
            get_resp = await client.get(url, headers=headers)
            if get_resp.status_code == 200:
                sha = get_resp.json().get("sha")

            payload: dict = {
                "message": commit_message,
                "content": encoded,
            }
            if sha:
                payload["sha"] = sha

            put_resp = await client.put(url, headers=headers, json=payload)
            put_resp.raise_for_status()
            return put_resp.json()

    # ── Pull ─────────────────────────────────────────────────────────────

    async def pull_file(
        self, token: str, owner: str, repo: str, path: str
    ) -> str:
        """Fetch a file from a GitHub repo and return its decoded text content."""
        url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=self._headers(token))
            resp.raise_for_status()
            data = resp.json()
            return base64.b64decode(data["content"]).decode("utf-8")

    # ── User info ────────────────────────────────────────────────────────

    async def get_github_user(self, token: str) -> dict:
        """Fetch the authenticated GitHub user profile."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{GITHUB_API}/user", headers=self._headers(token)
            )
            resp.raise_for_status()
            return resp.json()


github_sync_service = GitHubSyncService()
