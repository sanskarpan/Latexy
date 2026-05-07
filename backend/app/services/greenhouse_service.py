"""
Greenhouse Job Board integration service (Feature 87).

Uses the public Greenhouse Job Board API:
  - Read: GET https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}
  - Apply: POST https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}

No API key is needed for reading or applying — the Greenhouse embedded job
application endpoints accept anonymous multipart submissions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import httpx

from ..core.logging import get_logger

logger = get_logger(__name__)

# ── Regex to extract company slug and job_id from common Greenhouse URLs ──────
# Handles:
#   https://boards.greenhouse.io/acme/jobs/12345
#   https://job-boards.greenhouse.io/acme/jobs/12345
#   https://grnh.se/... (short links — not resolvable without redirect)

_GH_URL_RE = re.compile(
    r"(?:boards|job-boards)\.greenhouse\.io/(?P<company>[^/]+)/jobs/(?P<job_id>\d+)",
    re.IGNORECASE,
)

_GH_API_BASE = "https://boards-api.greenhouse.io/v1/boards"

_TIMEOUT = httpx.Timeout(15.0)


@dataclass
class JobDetails:
    company: str
    job_id: str
    title: str
    location: str
    apply_url: str
    description_html: str


@dataclass
class ApplicantData:
    first_name: str
    last_name: str
    email: str
    phone: str
    resume_bytes: bytes
    resume_filename: str = "resume.pdf"
    cover_letter_text: Optional[str] = None


class GreenhouseService:
    """Client for the Greenhouse Job Board API."""

    # ── URL parsing ──────────────────────────────────────────────────────────

    @staticmethod
    def parse_url(job_url: str) -> tuple[str, str]:
        """
        Extract (company_slug, job_id) from a Greenhouse job URL.
        Raises ValueError if the URL is not recognizable.
        """
        m = _GH_URL_RE.search(job_url)
        if not m:
            raise ValueError(
                f"Cannot parse Greenhouse job URL — expected "
                f"boards.greenhouse.io/<company>/jobs/<id>. Got: {job_url!r}"
            )
        return m.group("company"), m.group("job_id")

    # ── Job details ──────────────────────────────────────────────────────────

    async def get_job_details(self, company: str, job_id: str) -> JobDetails:
        """
        Fetch job title, location, and apply URL from the Greenhouse board API.
        Raises httpx.HTTPStatusError on upstream 4xx/5xx.
        """
        url = f"{_GH_API_BASE}/{company}/jobs/{job_id}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url)

        if resp.status_code == 404:
            raise ValueError(f"Greenhouse job not found: company={company!r} job_id={job_id!r}")
        resp.raise_for_status()

        data = resp.json()
        location = ""
        if data.get("location") and data["location"].get("name"):
            location = data["location"]["name"]

        # Greenhouse returns an `absolute_url` for the public apply page
        apply_url = data.get("absolute_url", f"https://boards.greenhouse.io/{company}/jobs/{job_id}")

        return JobDetails(
            company=company,
            job_id=job_id,
            title=data.get("title", ""),
            location=location,
            apply_url=apply_url,
            description_html=data.get("content", ""),
        )

    # ── Submit application ───────────────────────────────────────────────────

    async def submit_application(
        self,
        company: str,
        job_id: str,
        applicant: ApplicantData,
    ) -> dict:
        """
        Submit an application to the Greenhouse job board endpoint.

        Greenhouse's embedded application endpoint accepts a multipart POST
        to the same URL as the job listing.  The required fields are:
          - first_name, last_name, email, phone
          - resume (file)
          - cover_letter (optional file or text)

        Returns the parsed JSON response dict.
        Raises ValueError on validation errors; httpx.HTTPStatusError on HTTP errors.
        """
        url = f"{_GH_API_BASE}/{company}/jobs/{job_id}"

        files: dict = {
            "first_name": (None, applicant.first_name),
            "last_name": (None, applicant.last_name),
            "email": (None, applicant.email),
            "phone": (None, applicant.phone),
            "resume": (
                applicant.resume_filename,
                applicant.resume_bytes,
                "application/pdf",
            ),
        }
        if applicant.cover_letter_text:
            files["cover_letter"] = (
                "cover_letter.txt",
                applicant.cover_letter_text.encode(),
                "text/plain",
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, files=files)

        if resp.status_code in (400, 422):
            body = _safe_json(resp)
            raise ValueError(f"Greenhouse rejected application: {body}")

        resp.raise_for_status()
        return _safe_json(resp) or {"status": "submitted"}


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {}


# Module-level singleton
greenhouse_service = GreenhouseService()
