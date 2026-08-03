"""External-source import routes (Feature 1 Phase 2 — URL project ingest).

Synchronous endpoint that turns a public portfolio / personal-site / project URL
into resume-ready ``ProjectEvidence`` records (the SAME shape as the GitHub
import) for the existing frontend review UI.

PRIVACY / SAFETY: public pages only. One static HTTP GET (no JS execution) behind
the shared SSRF guard, followed by one LLM call. Because it is a single fetch +
single summarization it runs in-request (like the ``/ai/*`` endpoints), not as an
async job. Summarization uses the caller's own LLM key (BYOK) when present, else
the platform key.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..middleware.entitlements import require_feature
from ..services import url_projects_service as url_import
from ..services.api_key_service import api_key_service
from ..services.job_scraper_service import SSRFError

logger = get_logger(__name__)

router = APIRouter(prefix="/sources", tags=["sources"])


# ── Schemas ──────────────────────────────────────────────────────────────────


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


# ── Endpoint ─────────────────────────────────────────────────────────────────


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
        logger.warning(f"Blocked URL import (SSRF/invalid) for user {user_id}: {exc}")
        raise HTTPException(status_code=400, detail="Invalid or disallowed URL")
    except ValueError as exc:
        logger.info(f"URL import fetch failed for {body.url!r}: {exc}")
        raise HTTPException(status_code=502, detail="Could not fetch the page. Check the URL and try again.")
    except Exception as exc:  # noqa: BLE001 — last-resort guard around the fetch
        logger.error(f"Unexpected error fetching {body.url!r}: {exc}")
        raise HTTPException(status_code=500, detail="Unexpected error while fetching the page.")

    # 2) One LLM call → ProjectEvidence records (degrades to metadata on error).
    try:
        projects = url_import.extract_projects(page_text, body.url, api_key)
    except Exception as exc:  # noqa: BLE001 — extract_projects already degrades, belt-and-braces
        logger.error(f"Unexpected error extracting projects from {body.url!r}: {exc}")
        raise HTTPException(status_code=500, detail="Unexpected error while extracting projects.")

    return ImportUrlResponse(projects=projects)
