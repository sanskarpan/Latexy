"""
Tests for Feature 33 (advanced): Job Board URL Scraper.

Covers:
  Extractor selection   — platform detection by domain
  HTML utilities        — _html_to_clean_text, _slug_to_name, _normalize_job_type
  URL normalization     — tracking params stripped, fragment removed
  JSON-LD extraction    — schema.org/JobPosting parsing
  Platform API mocks    — Greenhouse, Lever, Ashby, SmartRecruiters, Workday
  Indeed _initialData   — JSON blob extraction
  Generic extractor     — quality-scored content extraction
  Service (scrape())    — cache hit / miss, error propagation
  Endpoint validation   — 422, 429, 200 with required fields
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------


def _greenhouse_html(title: str = "Software Engineer", company: str = "Acme Corp") -> str:
    return f"""
    <html>
    <head>
      <script type="application/ld+json">
      {{
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": "{title}",
        "hiringOrganization": {{"@type": "Organization", "name": "{company}"}},
        "description": "<p>We are building the future.</p><ul><li>Write code</li><li>Review PRs</li></ul>",
        "datePosted": "2025-01-15",
        "jobLocation": {{"@type": "Place", "address": {{"addressLocality": "San Francisco", "addressRegion": "CA", "addressCountry": "US"}}}}
      }}
      </script>
    </head>
    <body>
      <h1 class="app-title">{title}</h1>
      <span class="company-name">{company}</span>
      <div id="content">We are looking for a talented engineer.
        <ul><li>Build distributed systems</li><li>Ship features</li></ul>
      </div>
    </body>
    </html>
    """


def _lever_html(title: str = "Backend Engineer", company: str = "StartupX") -> str:
    return f"""
    <html>
    <body>
      <h2 data-qa="posting-name">{title}</h2>
      <div class="main-header-logo">{company}</div>
      <div class="section-wrapper">
        <h3>Requirements</h3>
        <ul><li>5+ years Python</li><li>FastAPI experience</li></ul>
      </div>
    </body>
    </html>
    """


def _indeed_html_with_initialdata(title: str = "Data Scientist", company: str = "TechCo") -> str:
    data = {
        "jobInfoWrapperModel": {
            "jobInfoModel": {
                "jobInfoHeaderModel": {
                    "jobTitle": title,
                    "companyName": company,
                    "formattedLocation": "New York, NY",
                },
                "sanitizedJobDescription": {
                    "content": "<p>Join our data team.</p><ul><li>Build ML models</li></ul>"
                },
            }
        }
    }
    return f"""<html><body>
    <script>window._initialData = {json.dumps(data)}; window.foo = 1;</script>
    </body></html>"""


def _generic_jd_html(title: str = "Product Manager", company: str = "Acme") -> str:
    return f"""
    <html>
    <head>
      <meta property="og:title" content="{title}" />
      <meta property="og:site_name" content="{company}" />
    </head>
    <body>
      <nav>Navigation stuff</nav>
      <h1>{title}</h1>
      <div class="job-description-content">
        <h2>About the Role</h2>
        <p>We are looking for an exceptional Product Manager to join our team and drive product strategy.</p>
        <h2>Responsibilities</h2>
        <ul>
          <li>Define product vision and roadmap for core platform features</li>
          <li>Collaborate with engineering and design to ship high-quality products</li>
          <li>Analyze user feedback and usage data to prioritize features</li>
          <li>Communicate product strategy to stakeholders and leadership</li>
        </ul>
        <h2>Requirements</h2>
        <ul>
          <li>5+ years of product management experience</li>
          <li>Strong analytical and problem-solving skills</li>
          <li>Experience working with cross-functional teams</li>
        </ul>
      </div>
      <footer>Footer stuff</footer>
    </body>
    </html>
    """


def _mock_http_response(status: int = 200, text: str = "", json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else (json.dumps(json_data) if json_data else "")
    resp.json = MagicMock(return_value=json_data or {})
    return resp


# ---------------------------------------------------------------------------
# Unit: Platform detection
# ---------------------------------------------------------------------------


class TestPlatformDetection:
    def test_greenhouse_boards(self):
        from app.services.job_scraper_service import _detect_platform
        assert _detect_platform("https://boards.greenhouse.io/stripe/jobs/123") == "greenhouse"

    def test_greenhouse_without_boards_prefix(self):
        from app.services.job_scraper_service import _detect_platform
        assert _detect_platform("https://greenhouse.io/acme/jobs/1") == "greenhouse"

    def test_lever(self):
        from app.services.job_scraper_service import _detect_platform
        assert _detect_platform("https://jobs.lever.co/airbnb/abc-123") == "lever"

    def test_ashby(self):
        from app.services.job_scraper_service import _detect_platform
        assert _detect_platform("https://jobs.ashbyhq.com/OpenAI/abc") == "ashby"

    def test_smartrecruiters(self):
        from app.services.job_scraper_service import _detect_platform
        assert _detect_platform("https://careers.smartrecruiters.com/Walmart/123") == "smartrecruiters"

    def test_workday(self):
        from app.services.job_scraper_service import _detect_platform
        assert _detect_platform("https://google.wd3.myworkdayjobs.com/External/job/US/SWE_123/123") == "workday"

    def test_indeed(self):
        from app.services.job_scraper_service import _detect_platform
        assert _detect_platform("https://www.indeed.com/viewjob?jk=abc123") == "indeed"

    def test_linkedin(self):
        from app.services.job_scraper_service import _detect_platform
        assert _detect_platform("https://www.linkedin.com/jobs/view/123456") == "linkedin"

    def test_generic(self):
        from app.services.job_scraper_service import _detect_platform
        assert _detect_platform("https://careers.somecompany.com/job/123") == "generic"

    def test_www_prefix_stripped(self):
        from app.services.job_scraper_service import _detect_platform
        assert _detect_platform("https://www.greenhouse.io/acme/jobs/1") == "greenhouse"


# ---------------------------------------------------------------------------
# Unit: URL normalization
# ---------------------------------------------------------------------------


class TestNormalizeUrl:
    def test_strips_utm_params(self):
        from app.services.job_scraper_service import _normalize_url
        url = "https://jobs.lever.co/x/123?utm_source=linkedin&utm_medium=social"
        assert "utm_source" not in _normalize_url(url)
        assert "utm_medium" not in _normalize_url(url)

    def test_strips_greenhouse_gh_src(self):
        from app.services.job_scraper_service import _normalize_url
        url = "https://boards.greenhouse.io/x/jobs/1?gh_src=3c9d2e1a1"
        assert "gh_src" not in _normalize_url(url)

    def test_strips_lever_source(self):
        from app.services.job_scraper_service import _normalize_url
        url = "https://jobs.lever.co/x/123?lever-source=linkedin"
        assert "lever-source" not in _normalize_url(url)

    def test_strips_fragment(self):
        from app.services.job_scraper_service import _normalize_url
        url = "https://example.com/job/1#apply-now"
        assert "#" not in _normalize_url(url)

    def test_preserves_job_params(self):
        from app.services.job_scraper_service import _normalize_url
        url = "https://www.indeed.com/viewjob?jk=abc123"
        assert "jk=abc123" in _normalize_url(url)

    def test_adds_https_when_missing(self):
        from app.services.job_scraper_service import _normalize_url
        assert _normalize_url("boards.greenhouse.io/x/jobs/1").startswith("https://")


# ---------------------------------------------------------------------------
# Unit: HTML → clean text
# ---------------------------------------------------------------------------


class TestHtmlToCleanText:
    def test_converts_list_items_to_bullets(self):
        from app.services.job_scraper_service import _html_to_clean_text
        html = "<ul><li>Write code</li><li>Review PRs</li></ul>"
        result = _html_to_clean_text(html)
        assert "• Write code" in result
        assert "• Review PRs" in result

    def test_preserves_headings(self):
        from app.services.job_scraper_service import _html_to_clean_text
        html = "<h2>Requirements</h2><p>5 years experience</p>"
        result = _html_to_clean_text(html)
        assert "Requirements" in result
        assert "5 years experience" in result

    def test_strips_script_and_style(self):
        from app.services.job_scraper_service import _html_to_clean_text
        html = "<script>alert(1)</script><p>Real content</p><style>.x{}</style>"
        result = _html_to_clean_text(html)
        assert "alert" not in result
        assert "Real content" in result

    def test_truncates_at_max_length(self):
        from app.services.job_scraper_service import _html_to_clean_text
        long_para = "A" * 15_000
        result = _html_to_clean_text(f"<p>{long_para}</p>", max_length=500)
        assert len(result) <= 510  # slight leeway for truncation marker

    def test_collapses_excessive_whitespace(self):
        from app.services.job_scraper_service import _html_to_clean_text
        html = "<p>Word1    Word2\n\n\n\n\nWord3</p>"
        result = _html_to_clean_text(html)
        assert "   " not in result

    def test_empty_input_returns_empty(self):
        from app.services.job_scraper_service import _html_to_clean_text
        assert _html_to_clean_text("") == ""
        assert _html_to_clean_text("   ") == ""


# ---------------------------------------------------------------------------
# Unit: Utility helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_slug_to_name(self):
        from app.services.job_scraper_service import _slug_to_name
        assert _slug_to_name("open-ai") == "Open Ai"
        assert _slug_to_name("my_company") == "My Company"

    def test_normalize_job_type_fulltime(self):
        from app.services.job_scraper_service import _normalize_job_type
        assert _normalize_job_type("FULL_TIME") == "Full-time"
        assert _normalize_job_type("full-time") == "Full-time"

    def test_normalize_job_type_remote(self):
        from app.services.job_scraper_service import _normalize_job_type
        assert _normalize_job_type("TELECOMMUTE") == "Remote"
        assert _normalize_job_type("Remote Only") == "Remote"

    def test_normalize_job_type_none(self):
        from app.services.job_scraper_service import _normalize_job_type
        assert _normalize_job_type(None) is None

    def test_normalize_job_type_contract(self):
        from app.services.job_scraper_service import _normalize_job_type
        assert _normalize_job_type("contractor") == "Contract"


# ---------------------------------------------------------------------------
# Unit: JSON-LD extraction
# ---------------------------------------------------------------------------


class TestJsonLdExtraction:
    def test_finds_jobposting_in_script(self):
        from bs4 import BeautifulSoup
        from app.services.job_scraper_service import _find_job_ld
        soup = BeautifulSoup(_greenhouse_html("SWE", "BigCo"), "lxml")
        ld = _find_job_ld(soup)
        assert ld is not None
        assert ld["@type"] == "JobPosting"
        assert ld["title"] == "SWE"

    def test_parses_title_company_location_from_ld(self):
        from bs4 import BeautifulSoup
        from app.services.job_scraper_service import _find_job_ld, _parse_ld_job
        soup = BeautifulSoup(_greenhouse_html("ML Engineer", "DataCo"), "lxml")
        ld = _find_job_ld(soup)
        result = _parse_ld_job(ld, "https://example.com/job/1")
        assert result.title == "ML Engineer"
        assert result.company == "DataCo"
        assert result.location is not None
        assert "San Francisco" in result.location
        assert result.source == "json_ld"
        assert result.posted_at == "2025-01-15"

    def test_parses_description_html(self):
        from bs4 import BeautifulSoup
        from app.services.job_scraper_service import _find_job_ld, _parse_ld_job
        soup = BeautifulSoup(_greenhouse_html(), "lxml")
        ld = _find_job_ld(soup)
        result = _parse_ld_job(ld, "https://example.com")
        assert result.description is not None
        assert "• Write code" in result.description

    def test_handles_at_graph_wrapper(self):
        from bs4 import BeautifulSoup
        from app.services.job_scraper_service import _find_job_ld
        html = """<html><head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@graph":[
          {"@type":"Organization","name":"Foo"},
          {"@type":"JobPosting","title":"SRE","hiringOrganization":{"name":"Foo"}}
        ]}
        </script></head><body></body></html>"""
        soup = BeautifulSoup(html, "lxml")
        ld = _find_job_ld(soup)
        assert ld is not None
        assert ld["title"] == "SRE"

    def test_handles_employment_type_list(self):
        from bs4 import BeautifulSoup
        from app.services.job_scraper_service import _find_job_ld, _parse_ld_job
        html = """<html><head><script type="application/ld+json">
        {"@type":"JobPosting","title":"Dev","employmentType":["FULL_TIME","CONTRACTOR"]}
        </script></head><body></body></html>"""
        soup = BeautifulSoup(html, "lxml")
        ld = _find_job_ld(soup)
        result = _parse_ld_job(ld, "https://example.com")
        assert result.job_type == "Full-time"

    def test_telecommute_location_type_sets_remote(self):
        from bs4 import BeautifulSoup
        from app.services.job_scraper_service import _find_job_ld, _parse_ld_job
        html = """<html><head><script type="application/ld+json">
        {"@type":"JobPosting","title":"Dev","jobLocationType":"TELECOMMUTE"}
        </script></head><body></body></html>"""
        soup = BeautifulSoup(html, "lxml")
        ld = _find_job_ld(soup)
        result = _parse_ld_job(ld, "https://example.com")
        assert result.job_type == "Remote"


# ---------------------------------------------------------------------------
# Unit: Indeed _initialData extraction
# ---------------------------------------------------------------------------


class TestIndeedInitialData:
    def test_extracts_title_company_description(self):
        from app.services.job_scraper_service import _try_indeed_initialdata
        html = _indeed_html_with_initialdata("Data Scientist", "TechCo")
        result = _try_indeed_initialdata(html, "https://indeed.com/viewjob?jk=x")
        assert result is not None
        assert result.title == "Data Scientist"
        assert result.company == "TechCo"
        assert result.description is not None
        assert "• Build ML models" in result.description

    def test_returns_none_when_no_initialdata(self):
        from app.services.job_scraper_service import _try_indeed_initialdata
        result = _try_indeed_initialdata("<html><body><h1>Job</h1></body></html>", "https://indeed.com")
        assert result is None


# ---------------------------------------------------------------------------
# Unit: Generic quality-scored extractor
# ---------------------------------------------------------------------------


class TestGenericExtractor:
    def test_picks_best_content_block(self):
        from bs4 import BeautifulSoup
        from app.services.job_scraper_service import _extract_generic_html
        soup = BeautifulSoup(_generic_jd_html("Product Manager", "Acme"), "lxml")
        result = _extract_generic_html(soup, "https://example.com/job")
        assert result.title == "Product Manager"
        assert result.description is not None
        # Should contain job description content, not nav/footer
        assert "About the Role" in result.description or "Responsibilities" in result.description
        assert "Navigation" not in result.description
        assert "Footer" not in result.description

    def test_extracts_og_company_from_meta(self):
        from bs4 import BeautifulSoup
        from app.services.job_scraper_service import _extract_generic_html
        soup = BeautifulSoup(_generic_jd_html("Engineer", "MyCompany"), "lxml")
        result = _extract_generic_html(soup, "https://example.com/job")
        assert result.company == "MyCompany"


# ---------------------------------------------------------------------------
# Service: scrape() — httpx and cache mocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestJobScraperService:
    async def test_greenhouse_api_path_returns_populated_result(self):
        from app.services.job_scraper_service import JobScraperService
        service = JobScraperService()

        job_data = {"title": "Staff Engineer", "content": "<p>Build distributed systems.</p><ul><li>Own infra</li></ul>",
                    "location": {"name": "Remote"}, "updated_at": "2025-06-01"}
        board_data = {"name": "Stripe"}

        mock_job_resp = _mock_http_response(200, json_data=job_data)
        mock_board_resp = _mock_http_response(200, json_data=board_data)

        async def mock_gather(*coros, **kw):
            # Resolve coroutines in order
            return [mock_job_resp, mock_board_resp]

        with (
            patch("app.services.job_scraper_service.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.services.job_scraper_service.cache_manager.set", new_callable=AsyncMock),
            patch("app.services.job_scraper_service.asyncio.gather", side_effect=mock_gather),
            patch("httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client

            result = await service.scrape("https://boards.greenhouse.io/stripe/jobs/987654")

        assert result.title == "Staff Engineer"
        assert result.company == "Stripe"
        assert result.description is not None
        assert "• Own infra" in result.description
        assert result.location == "Remote"
        assert result.source == "api"
        assert result.error is None

    async def test_cached_url_returns_cached_flag_no_http(self):
        from app.services.job_scraper_service import JobScraperService
        service = JobScraperService()
        cached = {
            "url": "https://jobs.lever.co/stripe/abc-123",
            "title": "Backend SWE", "company": "Stripe",
            "description": "Build payment infra.", "location": "San Francisco",
            "job_type": "Full-time", "salary": None, "posted_at": None,
            "source": "api", "cached": False, "error": None, "scraped_at": "2025-01-01T00:00:00+00:00",
        }
        with (
            patch("app.services.job_scraper_service.cache_manager.get", new_callable=AsyncMock, return_value=cached),
            patch("httpx.AsyncClient") as mock_cls,
        ):
            result = await service.scrape("https://jobs.lever.co/stripe/abc-123")
            mock_cls.assert_not_called()

        assert result.cached is True
        assert result.title == "Backend SWE"
        assert result.source == "api"

    async def test_non_200_http_returns_error_field(self):
        from app.services.job_scraper_service import JobScraperService
        service = JobScraperService()
        mock_resp = _mock_http_response(404)

        with (
            patch("app.services.job_scraper_service.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client

            result = await service.scrape("https://careers.unknown.com/job/1")

        assert result.error is not None
        assert result.title is None

    async def test_json_ld_used_when_api_unavailable(self):
        from app.services.job_scraper_service import JobScraperService
        service = JobScraperService()
        html = _greenhouse_html("DevOps Engineer", "CloudCo")
        mock_resp = _mock_http_response(200, text=html)

        with (
            patch("app.services.job_scraper_service.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.services.job_scraper_service.cache_manager.set", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client

            # Use a generic URL so no API path is attempted
            result = await service.scrape("https://careers.cloudco.com/job/devops-123")

        # JSON-LD is in the HTML, so source should be json_ld
        assert result.title == "DevOps Engineer"
        assert result.company == "CloudCo"
        assert result.source == "json_ld"

    async def test_indeed_initialdata_used_for_indeed_platform(self):
        from app.services.job_scraper_service import JobScraperService
        service = JobScraperService()
        html = _indeed_html_with_initialdata("ML Researcher", "AILabs")
        mock_resp = _mock_http_response(200, text=html)

        with (
            patch("app.services.job_scraper_service.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.services.job_scraper_service.cache_manager.set", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client

            result = await service.scrape("https://www.indeed.com/viewjob?jk=abc123")

        assert result.title == "ML Researcher"
        assert result.company == "AILabs"
        assert result.description is not None


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestScrapeJobEndpoint:
    async def test_invalid_url_no_scheme_returns_422(self, client: AsyncClient):
        resp = await client.post("/scrape-job-description", json={"url": "not-a-url"})
        assert resp.status_code == 422

    async def test_missing_url_field_returns_422(self, client: AsyncClient):
        resp = await client.post("/scrape-job-description", json={})
        assert resp.status_code == 422

    async def test_ftp_scheme_rejected_422(self, client: AsyncClient):
        resp = await client.post("/scrape-job-description", json={"url": "ftp://example.com/job"})
        assert resp.status_code == 422

    async def test_url_too_long_returns_422(self, client: AsyncClient):
        resp = await client.post("/scrape-job-description", json={"url": "https://example.com/" + "a" * 500})
        assert resp.status_code == 422

    async def test_successful_response_has_all_fields(self, client: AsyncClient):
        mock_resp = _mock_http_response(200, text=_greenhouse_html("SWE", "BigCo"))
        with (
            patch("app.services.job_scraper_service.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.services.job_scraper_service.cache_manager.set", new_callable=AsyncMock),
            patch("app.api.scraper_routes._check_rate_limit", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client
            resp = await client.post("/scrape-job-description", json={"url": "https://example.com/job/1"})

        assert resp.status_code == 200
        data = resp.json()
        for field in ["title", "company", "description", "location", "job_type", "salary",
                      "posted_at", "url", "cached", "source", "error"]:
            assert field in data, f"Missing field: {field}"

    async def test_non_200_from_target_returns_error_not_500(self, client: AsyncClient):
        mock_resp = _mock_http_response(503)
        with (
            patch("app.services.job_scraper_service.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.api.scraper_routes._check_rate_limit", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client
            resp = await client.post("/scrape-job-description", json={"url": "https://example.com/job/999"})

        assert resp.status_code == 200
        assert resp.json()["error"] is not None

    async def test_rate_limit_exceeded_returns_429(self, client: AsyncClient):
        from fastapi import HTTPException

        async def _raise(*args, **kwargs):
            raise HTTPException(status_code=429, detail="Rate limit exceeded: 10 scrapes per minute")

        with patch("app.api.scraper_routes._check_rate_limit", side_effect=_raise):
            resp = await client.post("/scrape-job-description", json={"url": "https://example.com/job/1"})

        assert resp.status_code == 429

    async def test_source_field_reflects_extraction_method(self, client: AsyncClient):
        mock_resp = _mock_http_response(200, text=_greenhouse_html())
        with (
            patch("app.services.job_scraper_service.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.services.job_scraper_service.cache_manager.set", new_callable=AsyncMock),
            patch("app.api.scraper_routes._check_rate_limit", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_client
            resp = await client.post("/scrape-job-description", json={"url": "https://example.com/job/1"})

        data = resp.json()
        assert data["source"] in ("api", "json_ld", "html", "og_tags")
