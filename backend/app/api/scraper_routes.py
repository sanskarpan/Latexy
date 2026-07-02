"""
Job Board URL Scraper routes — Feature 33.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..core.redis import get_redis_cache_client
from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_optional
from ..services.job_scraper_service import job_scraper_service

logger = get_logger(__name__)

router = APIRouter(tags=["scraper"])


class ScrapeJobRequest(BaseModel):
    url: str = Field(..., max_length=500)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class ScrapeJobResponse(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[str] = None
    salary: Optional[str] = None
    posted_at: Optional[str] = None
    url: str
    cached: bool = False
    source: str = "html"   # "api" | "json_ld" | "html" | "og_tags"
    error: Optional[str] = None


_RATE_LIMIT = 10
_RATE_WINDOW = 60


def _client_ip(request: Request) -> str:
    """Best-effort client IP.

    Behind a reverse proxy ``request.client.host`` is the proxy address, which
    would collapse every user into one bucket, so prefer the first hop of the
    ``X-Forwarded-For`` chain (the original client) when present.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return (request.client.host if request.client else None) or "unknown"


async def _check_rate_limit(request: Request) -> None:
    """10 scrape requests per IP per minute via an atomic Redis INCR counter."""
    ip = _client_ip(request)
    key = f"cache:ratelimit:scrape:{ip}"
    try:
        client = await get_redis_cache_client()
        # INCR is atomic, so concurrent requests can't race past the limit.
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, _RATE_WINDOW)
    except Exception as exc:
        # Fail open on a cache outage rather than 500ing every scrape request.
        logger.warning(f"Scrape rate-limit check skipped (cache error): {exc}")
        return

    if count > _RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded: 10 scrapes per minute")


@router.post("/scrape-job-description", response_model=ScrapeJobResponse)
async def scrape_job_description(
    body: ScrapeJobRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    """
    Scrape a job posting URL and return structured job data.

    Extraction priority:
      1. Platform-native JSON API  (Greenhouse, Lever, Ashby, SmartRecruiters, Workday)
      2. schema.org/JobPosting JSON-LD
      3. Platform-specific HTML  (Indeed _initialData, etc.)
      4. Quality-scored generic content extraction

    Supports: Greenhouse, Lever, Ashby, SmartRecruiters, Workday,
              Indeed, LinkedIn, Workable, BambooHR, Jobvite, and generic URLs.
    Results cached 24 h.  Works for anonymous and authenticated users.
    """
    await _check_rate_limit(request)
    result = await job_scraper_service.scrape(body.url)

    return ScrapeJobResponse(
        title=result.title,
        company=result.company,
        description=result.description,
        location=result.location,
        job_type=result.job_type,
        salary=result.salary,
        posted_at=result.posted_at,
        url=result.url,
        cached=result.cached,
        source=result.source,
        error=result.error,
    )
