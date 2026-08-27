"""External-source import routes (Feature 1 — external sources to resume).

Turns external sources into resume-ready ``ProjectEvidence`` records (the SAME
shape as the GitHub import) for the existing frontend review UI:

  * POST /sources/import-url      — Phase 2: a public portfolio / personal-site
    URL. One SSRF-guarded static fetch (no JS execution) + one LLM call, all
    in-request (like the ``/ai/*`` endpoints). Public pages only.
  * POST /sources/import-linkedin — Phase 3: a user-uploaded LinkedIn data-export
    ZIP or resume file. Parsed locally on the uploaded bytes.

COMPLIANCE CONSTRAINT (LinkedIn): the LinkedIn import NEVER scrapes LinkedIn,
NEVER calls any LinkedIn URL/API, and NEVER buys LinkedIn data. It parses ONLY a
file the USER uploads themselves — their official LinkedIn **data export** ZIP
(from LinkedIn → Settings → "Get a copy of your data") OR their own resume file
(PDF/DOCX). See ``linkedin_import_service`` for the constraint in full.

LLM summarization (URL path) uses the caller's own key (BYOK) when present, else
the platform key.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import User
from ..middleware.entitlements import require_feature
from ..services import linkedin_import_service
from ..services import url_projects_service as url_import
from ..services.api_key_service import api_key_service
from ..services.entitlement_service import QuotaTicket, entitlement_service
from ..services.external_budget_service import enforce_external_budget
from ..services.job_scraper_service import SSRFError

logger = get_logger(__name__)

router = APIRouter(prefix="/sources", tags=["sources"])

_IMPORT_BUDGET_WINDOW = 3600
_IMPORT_GLOBAL_LIMIT = 500
_IMPORT_CLIENT_LIMITS = {
    "url": 20,
    "linkedin": 40,
}


async def _enforce_import_budget(source: str, user_id: str) -> None:
    await enforce_external_budget(
        f"import-{source}",
        client_id=f"user:{user_id}",
        cost=1,
        client_limit=_IMPORT_CLIENT_LIMITS[source],
        global_limit=_IMPORT_GLOBAL_LIMIT,
        window_seconds=_IMPORT_BUDGET_WINDOW,
    )


# ── URL import (Phase 2) ─────────────────────────────────────────────────────


class ImportUrlRequest(BaseModel):
    url: str = Field(..., max_length=2000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class ImportUrlResponse(BaseModel):
    projects: List[dict] = []


@router.post("/import-url", response_model=ImportUrlResponse)
async def import_from_url(
    body: ImportUrlRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(require_feature("ai_import_url")),
) -> ImportUrlResponse:
    """Import projects from a public portfolio / personal-site URL.

    Reads PUBLIC page content only via a single SSRF-guarded static fetch (no JS
    execution), then extracts up to 5 ``ProjectEvidence`` records with one LLM
    call. Runs synchronously in-request. Summarization uses the user's own LLM
    key when present (BYOK), otherwise the platform key.
    """
    plan_result = await db.execute(
        select(User.subscription_plan).where(User.id == user_id)
    )
    user_plan = plan_result.scalar_one_or_none() or "free"
    quota_ticket: QuotaTicket = await entitlement_service.enforce_quota(
        "ai_assists", user_id=user_id, plan=user_plan
    )
    try:
        await _enforce_import_budget("url", user_id)
    except Exception:
        await entitlement_service.refund_quota(quota_ticket)
        raise

    # Resolve the LLM key the same way optimize / GitHub import do: the user's
    # own OpenAI key (BYOK) when present, else the platform key (api_key=None →
    # extract_projects uses settings.OPENAI_API_KEY via the lazy openai client).
    api_key: Optional[str] = None
    try:
        api_key = await api_key_service.get_user_provider(db, user_id, "openai")
    except Exception:
        api_key = None

    # 1) Static, SSRF-guarded fetch → cleaned page text.
    try:
        page_text = await url_import.fetch_url_text(body.url)
    except SSRFError as exc:
        await entitlement_service.refund_quota(quota_ticket)
        logger.warning(f"Blocked URL import (SSRF/invalid) for user {user_id}: {exc}")
        raise HTTPException(status_code=400, detail="Invalid or disallowed URL")
    except ValueError as exc:
        await entitlement_service.refund_quota(quota_ticket)
        logger.info(f"URL import fetch failed for {body.url!r}: {exc}")
        raise HTTPException(status_code=502, detail="Could not fetch the page. Check the URL and try again.")
    except Exception as exc:  # noqa: BLE001 — last-resort guard around the fetch
        await entitlement_service.refund_quota(quota_ticket)
        logger.error(f"Unexpected error fetching {body.url!r}: {exc}")
        raise HTTPException(status_code=500, detail="Unexpected error while fetching the page.")

    # 2) One LLM call → ProjectEvidence records (degrades to metadata on error).
    try:
        projects = url_import.extract_projects(page_text, body.url, api_key)
    except Exception as exc:  # noqa: BLE001 — extract_projects already degrades, belt-and-braces
        await entitlement_service.refund_quota(quota_ticket)
        logger.error(f"Unexpected error extracting projects from {body.url!r}: {exc}")
        raise HTTPException(status_code=500, detail="Unexpected error while extracting projects.")

    return ImportUrlResponse(projects=projects)


# ── LinkedIn / resume-file import (Phase 3) ──────────────────────────────────

# Reject uploads larger than this before reading them into memory (defence in
# depth on top of the service's own zip-bomb caps). LinkedIn exports and resumes
# are comfortably under this.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

_ZIP_CONTENT_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/x-zip",
    "multipart/x-zip",
}


class LinkedInImportResponse(BaseModel):
    """Candidate ProjectEvidence records parsed from the uploaded file."""

    projects: List[dict] = []


def _looks_like_zip(filename: str, content_type: str, head: bytes) -> bool:
    """Best-effort ZIP sniff by extension, content-type, or magic bytes."""
    if filename.lower().endswith(".zip"):
        return True
    if (content_type or "").lower().split(";")[0].strip() in _ZIP_CONTENT_TYPES:
        return True
    # ZIP local-file-header magic ("PK\x03\x04"). A DOCX is also a ZIP, but DOCX
    # is routed to the resume parser by its .docx extension check above, so this
    # only fires for genuine LinkedIn export archives.
    return head[:4] == b"PK\x03\x04" and not filename.lower().endswith(
        (".docx", ".doc")
    )


@router.post("/import-linkedin", response_model=LinkedInImportResponse)
async def import_linkedin(
    file: UploadFile = File(...),
    user_id: str = Depends(require_feature("ai_import_linkedin")),
) -> LinkedInImportResponse:
    """Import ProjectEvidence from a user-uploaded LinkedIn export ZIP or resume.

    COMPLIANCE: the ONLY input is the file the user uploads themselves — their
    own LinkedIn data export (``.zip``) or their own resume (``.pdf``/``.docx``).
    Nothing in this handler contacts LinkedIn.

    - ``.zip`` (LinkedIn export)  → ``parse_linkedin_export``
    - anything else (resume file) → ``parse_resume_file``

    Returns ``{projects: [ProjectEvidence]}``. A bad/unparseable file yields 422;
    an oversized upload yields 413.
    """
    await _enforce_import_budget("linkedin", user_id)

    filename = file.filename or "upload"
    content_type = file.content_type or ""

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {_MAX_UPLOAD_BYTES} bytes.",
        )

    try:
        if _looks_like_zip(filename, content_type, content):
            projects = linkedin_import_service.parse_linkedin_export(content)
        else:
            projects = await linkedin_import_service.parse_resume_file(content, filename)
    except ValueError as exc:
        # Malformed ZIP / unsupported or unparseable resume → client error.
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # unexpected → 500, but never leak internals
        logger.error("sources/import-linkedin failed for %s: %s", filename, exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to import from the uploaded file. Please try again.",
        )

    return LinkedInImportResponse(projects=projects)
