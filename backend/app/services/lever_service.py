"""
Lever Job Postings integration service (Feature 87).

Uses the public Lever Postings API v0:
  - Read: GET https://api.lever.co/v0/postings/{company}/{posting_id}
  - Apply: POST https://api.lever.co/v0/postings/{company}/{posting_id}/apply

No API key required for job-board submissions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote, urlsplit

import httpx

from ..core.logging import get_logger

logger = get_logger(__name__)

# ── Regex for Lever job URLs ──────────────────────────────────────────────────
# Handles:
#   https://jobs.lever.co/acme/abc-def-123
#   https://jobs.lever.co/acme/abc-def-123/apply

_COMPANY_RE = re.compile(r"[A-Za-z0-9_-]{1,100}")
_POSTING_ID_RE = re.compile(
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
    re.IGNORECASE,
)

_LEVER_API_BASE = "https://api.lever.co/v0/postings"
_TIMEOUT = httpx.Timeout(15.0)


@dataclass
class LeverJobDetails:
    company: str
    posting_id: str
    title: str
    team: str
    location: str
    apply_url: str
    description_plain: str


@dataclass
class ApplicantData:
    name: str
    email: str
    phone: str
    resume_bytes: bytes
    resume_filename: str = "resume.pdf"
    org: Optional[str] = None
    cover_letter_text: Optional[str] = None


class LeverService:
    """Client for the Lever public Postings API v0."""

    # ── URL parsing ──────────────────────────────────────────────────────────

    @staticmethod
    def parse_url(job_url: str) -> tuple[str, str]:
        """
        Extract (company_slug, posting_id) from a Lever job URL.
        Raises ValueError if the URL is not recognizable.
        """
        parsed = urlsplit(job_url)
        parts = [part for part in parsed.path.split("/") if part]
        if (
            parsed.scheme not in {"http", "https"}
            or (parsed.hostname or "").lower() != "jobs.lever.co"
            or len(parts) not in {2, 3}
            or (len(parts) == 3 and parts[2].lower() != "apply")
            or not _COMPANY_RE.fullmatch(parts[0])
            or not _POSTING_ID_RE.fullmatch(parts[1])
        ):
            raise ValueError(
                f"Cannot parse Lever job URL — expected "
                f"jobs.lever.co/<company>/<uuid>. Got: {job_url!r}"
            )
        return parts[0], parts[1]

    @staticmethod
    def _api_url(company: str, posting_id: str, *, apply: bool = False) -> str:
        if not _COMPANY_RE.fullmatch(company) or not _POSTING_ID_RE.fullmatch(posting_id):
            raise ValueError("Invalid Lever company or posting identifier")
        suffix = "/apply" if apply else ""
        return (
            f"{_LEVER_API_BASE}/{quote(company, safe='')}/"
            f"{quote(posting_id, safe='')}{suffix}"
        )

    # ── Job details ──────────────────────────────────────────────────────────

    async def get_posting(self, company: str, posting_id: str) -> LeverJobDetails:
        """
        Fetch posting details from the Lever public API.
        Raises ValueError on 404; httpx.HTTPStatusError on other HTTP errors.
        """
        url = self._api_url(company, posting_id)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url)

        if resp.status_code == 404:
            raise ValueError(f"Lever posting not found: company={company!r} posting_id={posting_id!r}")
        resp.raise_for_status()

        data = resp.json()
        categories = data.get("categories") or {}
        apply_url = data.get("applyUrl", f"https://jobs.lever.co/{company}/{posting_id}/apply")

        return LeverJobDetails(
            company=company,
            posting_id=posting_id,
            title=data.get("text", ""),
            team=categories.get("team", ""),
            location=categories.get("location", ""),
            apply_url=apply_url,
            description_plain=data.get("descriptionPlain", ""),
        )

    # ── Submit application ───────────────────────────────────────────────────

    async def apply(
        self,
        company: str,
        posting_id: str,
        applicant: ApplicantData,
    ) -> dict:
        """
        Submit application via the Lever Postings apply endpoint.

        Lever expects multipart/form-data with:
          - name, email, phone, org (company/school)
          - resume (file)
          - comments (cover letter)

        Returns the parsed JSON response dict.
        Raises ValueError on validation errors; httpx.HTTPStatusError on HTTP errors.
        """
        url = self._api_url(company, posting_id, apply=True)

        files: dict = {
            "name": (None, applicant.name),
            "email": (None, applicant.email),
            "phone": (None, applicant.phone),
            "resume": (
                applicant.resume_filename,
                applicant.resume_bytes,
                "application/pdf",
            ),
        }
        if applicant.org:
            files["org"] = (None, applicant.org)
        if applicant.cover_letter_text:
            files["comments"] = (None, applicant.cover_letter_text)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, files=files)

        if resp.status_code in (400, 422):
            raise ValueError("Lever rejected application")

        resp.raise_for_status()
        return _safe_json(resp) or {"status": "submitted"}


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {}


# Module-level singleton
lever_service = LeverService()
