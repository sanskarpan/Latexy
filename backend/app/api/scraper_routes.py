"""
Job Board URL Scraper routes — Feature 33.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..core.redis import cache_manager
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


async def _check_rate_limit(request: Request) -> None:
    """10 scrape requests per IP per minute (Redis counter)."""
    ip = (request.client.host if request.client else None) or "unknown"
    key = f"ratelimit:scrape:{ip}"
    count = await cache_manager.get(key)
    if count is None:
        await cache_manager.set(key, 1, ttl=60)
    elif int(count) >= 10:
        raise HTTPException(status_code=429, detail="Rate limit exceeded: 10 scrapes per minute")
    else:
        await cache_manager.set(key, int(count) + 1, ttl=60)


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
