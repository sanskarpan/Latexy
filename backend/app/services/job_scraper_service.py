"""
Job Board URL Scraper — Feature 33 (production-grade).

Extraction priority per request:
  1. Platform-native JSON API  (Greenhouse, Lever, Ashby, SmartRecruiters, Workday CXS)
  2. schema.org/JobPosting JSON-LD embedded in page HTML
  3. Platform-specific HTML extraction  (Indeed _initialData, Workday selectors, etc.)
  4. Quality-scored generic content extraction  (readability-inspired)
  5. Open Graph / meta tag fallback

Results are cached in Redis for 24 h.  Tracking params stripped before hashing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from ..core.logging import get_logger
from ..core.redis import cache_manager

logger = get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_TIMEOUT = 15.0
_MAX_DESC_LEN = 10_000  # chars — truncated at sentence boundary

# Chrome 120 browser headers (consistent set — mismatched headers are a bot signal)
_BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Sec-CH-UA": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
}

# Headers for programmatic JSON API calls (same-origin XHR fingerprint)
_JSON_HEADERS: dict[str, str] = {
    "User-Agent": _BROWSER_HEADERS["User-Agent"],
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Sec-CH-UA": _BROWSER_HEADERS["Sec-CH-UA"],
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
}

# Query params that must not affect cache key (tracking / attribution)
_TRACKING_PARAMS: frozenset[str] = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "ref", "refid", "referId", "trk", "trkInfo", "gh_src",
    "lever-source", "lever-origin", "source", "sr", "trackingId",
    "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid",
})

# Domain → platform identifier
_PLATFORM_MAP: dict[str, str] = {
    "boards.greenhouse.io": "greenhouse",
    "greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "lever.co": "lever",
    "indeed.com": "indeed",
    "myworkdayjobs.com": "workday",
    "workday.com": "workday",
    "linkedin.com": "linkedin",
    "jobs.ashbyhq.com": "ashby",
    "ashbyhq.com": "ashby",
    "careers.smartrecruiters.com": "smartrecruiters",
    "smartrecruiters.com": "smartrecruiters",
    "workable.com": "workable",
    "apply.workable.com": "workable",
    "jobs.jobvite.com": "jobvite",
    "app.jazz.hr": "jazzhr",
    "recruitingbypaycor.com": "jazzhr",
    "careers.icims.com": "icims",
    "bamboohr.com": "bamboohr",
    "breezy.hr": "breezyhr",
    "recruitee.com": "recruitee",
    "taleo.net": "taleo",
    "oraclecloud.com": "oracle",
    "jobvite.com": "jobvite",
}

# ── Data model ───────────────────────────────────────────────────────────────


@dataclass
class JobScraperResult:
    url: str
    title: Optional[str] = None
    company: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[str] = None   # "Full-time" | "Part-time" | "Contract" | "Remote" | "Hybrid"
    salary: Optional[str] = None
    posted_at: Optional[str] = None
    source: str = "html"             # "api" | "json_ld" | "html" | "og_tags"
    cached: bool = False
    error: Optional[str] = None
    scraped_at: Optional[str] = None

    def is_useful(self) -> bool:
        return bool(self.title or self.description) and not self.error


# ── URL normalization ─────────────────────────────────────────────────────────


def _normalize_url(url: str) -> str:
    """Strip tracking params and fragment; ensure scheme present."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    clean_qs = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
    return urlunparse(parsed._replace(query=urlencode(clean_qs, doseq=True), fragment=""))


def _detect_platform(url: str) -> str:
    domain = urlparse(url).netloc.lstrip("www.").lower()
    for pattern, platform in _PLATFORM_MAP.items():
        if domain == pattern or domain.endswith("." + pattern):
            return platform
    return "generic"


# ── HTML → clean text ─────────────────────────────────────────────────────────


def _html_to_clean_text(html: str, max_length: int = _MAX_DESC_LEN) -> str:
    """
    Convert HTML to clean structured plain text.
    Preserves bullet points (• …), headings, and paragraph breaks.
    Strips navigation, scripts, and boilerplate.
    """
    if not html or not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")
    for dead in soup.find_all(["script", "style", "noscript", "meta", "head"]):
        dead.decompose()

    parts: list[str] = []

    def walk(node: Tag | NavigableString) -> None:
        if isinstance(node, NavigableString):
            t = str(node)
            stripped = t.strip()
            if stripped:
                # Preserve a trailing space so adjacent inline text joins properly
                parts.append(stripped + (" " if t.endswith((" ", "\n", "\t")) else " "))
            return

        if not isinstance(node, Tag):
            return

        tag = (node.name or "").lower()

        if tag in ("h1", "h2", "h3"):
            text = node.get_text(separator=" ", strip=True)
            if text:
                parts.append(f"\n\n{text}\n")
            return

        if tag in ("h4", "h5", "h6"):
            text = node.get_text(separator=" ", strip=True)
            if text:
                parts.append(f"\n{text}\n")
            return

        if tag == "li":
            text = node.get_text(separator=" ", strip=True)
            if text:
                parts.append(f"\n• {text}")
            return

        if tag in ("ul", "ol"):
            for child in node.children:
                walk(child)
            parts.append("\n")
            return

        if tag == "br":
            parts.append("\n")
            return

        if tag in ("p", "div", "section", "article", "main"):
            inner = node.get_text(separator=" ", strip=True)
            if inner:
                parts.append("\n")
                for child in node.children:
                    walk(child)
                parts.append("\n")
            return

        # Inline / passthrough
        for child in node.children:
            walk(child)

    walk(soup)

    text = "".join(parts)
    text = re.sub(r"[ \t]+", " ", text)          # multiple spaces → one
    text = re.sub(r" *\n *", "\n", text)          # trim around newlines
    text = re.sub(r"\n{3,}", "\n\n", text)        # max two blank lines
    text = text.strip()

    if len(text) > max_length:
        clipped = text[:max_length]
        # Truncate at last sentence boundary (≥70 % of max_length)
        for end in (".\n", "!\n", "?\n", ". ", "! ", "? "):
            pos = clipped.rfind(end)
            if pos > max_length * 0.7:
                text = clipped[: pos + 1].rstrip()
                break
        else:
            text = clipped.rstrip() + "…"

    return text


# ── Helpers ───────────────────────────────────────────────────────────────────


def _text(tag: Optional[Tag]) -> Optional[str]:
    val = tag.get_text(separator=" ", strip=True) if tag else None
    return val or None


def _meta(soup: BeautifulSoup, prop: str, name: str = "") -> Optional[str]:
    t = soup.find("meta", property=prop)
    if not t:
        t = soup.find("meta", attrs={"name": name or prop})
    if isinstance(t, Tag):
        val = t.get("content")
        return str(val).strip() or None if val else None
    return None


def _slug_to_name(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


def _normalize_job_type(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = raw.lower().strip()
    if "remote" in s or "telecommut" in s:
        return "Remote"
    if "hybrid" in s:
        return "Hybrid"
    if "full" in s:
        return "Full-time"
    if "part" in s:
        return "Part-time"
    if "contract" in s or "freelance" in s:
        return "Contract"
    if "intern" in s:
        return "Internship"
    if "temporary" in s or "temp" in s:
        return "Temporary"
    return raw.strip().title()


def _format_salary_lever(d: dict) -> Optional[str]:
    cur = d.get("currency", "")
    interval = d.get("interval", "")
    lo, hi = d.get("min"), d.get("max")
    if lo and hi:
        return f"{cur}{lo:,}–{cur}{hi:,} / {interval}"
    if lo:
        return f"From {cur}{lo:,} / {interval}"
    if hi:
        return f"Up to {cur}{hi:,} / {interval}"
    return None


def _format_salary_ld(base_salary: object) -> Optional[str]:
    if not isinstance(base_salary, dict):
        return None
    cur = base_salary.get("currency", "")
    val = base_salary.get("value", {})
    if isinstance(val, dict):
        lo, hi = val.get("minValue"), val.get("maxValue")
        unit = (val.get("unitText") or "").lower()
        if lo and hi:
            return f"{cur}{float(lo):,.0f}–{cur}{float(hi):,.0f} / {unit}"
        if lo:
            return f"From {cur}{float(lo):,.0f} / {unit}"
    return None


# ── JSON-LD / schema.org extraction ──────────────────────────────────────────


def _find_job_ld(soup: BeautifulSoup) -> Optional[dict]:
    """Find first schema.org/JobPosting node in any ld+json block."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            raw = script.string
            if not raw or "JobPosting" not in raw:
                continue
            data = json.loads(raw)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "JobPosting":
                    return item
                # @graph wrapper
                for node in item.get("@graph", []):
                    if isinstance(node, dict) and node.get("@type") == "JobPosting":
                        return node
        except (json.JSONDecodeError, AttributeError):
            pass
    return None


def _parse_ld_job(ld: dict, url: str) -> JobScraperResult:
    title = ld.get("title")

    hiring_org = ld.get("hiringOrganization") or {}
    company = (hiring_org.get("name") if isinstance(hiring_org, dict) else None)

    desc_html = ld.get("description", "")
    description = _html_to_clean_text(desc_html) if desc_html else None

    # Location
    job_location = ld.get("jobLocation") or {}
    if isinstance(job_location, list):
        job_location = job_location[0] if job_location else {}
    address = (job_location.get("address") or {}) if isinstance(job_location, dict) else {}
    if isinstance(address, dict):
        parts = [address.get("addressLocality", ""), address.get("addressRegion", ""), address.get("addressCountry", "")]
        location = ", ".join(p for p in parts if p) or None
    else:
        location = str(address) if address else None

    # Job type
    emp_type = ld.get("employmentType")
    loc_type = ld.get("jobLocationType")  # "TELECOMMUTE" → remote
    if isinstance(emp_type, list):
        emp_type = emp_type[0] if emp_type else None
    job_type = "Remote" if loc_type == "TELECOMMUTE" else _normalize_job_type(str(emp_type) if emp_type else None)

    salary = _format_salary_ld(ld.get("baseSalary"))
    posted_at = ld.get("datePosted")

    return JobScraperResult(
        url=url, title=title, company=company, description=description,
        location=location, job_type=job_type, salary=salary,
        posted_at=posted_at, source="json_ld",
    )


# ── Platform API extractors ────────────────────────────────────────────────────


async def _try_greenhouse_api(url: str, client: httpx.AsyncClient) -> Optional[JobScraperResult]:
    """
    Greenhouse public Board API (no auth required).
    https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}
    https://boards-api.greenhouse.io/v1/boards/{board}   → company name
    """
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    # Expect: /{board}/jobs/{id}[/slug]
    if len(parts) < 3 or parts[1] != "jobs":
        return None

    board, job_id = parts[0], parts[2]
    base = "https://boards-api.greenhouse.io/v1/boards"

    try:
        job_resp, board_resp = await asyncio.gather(
            client.get(f"{base}/{board}/jobs/{job_id}", headers=_JSON_HEADERS),
            client.get(f"{base}/{board}", headers=_JSON_HEADERS),
            return_exceptions=True,
        )

        if isinstance(job_resp, Exception) or job_resp.status_code != 200:
            return None

        job = job_resp.json()
        company = None
        if not isinstance(board_resp, Exception) and board_resp.status_code == 200:
            company = board_resp.json().get("name")

        title = job.get("title")
        content_html = job.get("content", "")
        description = _html_to_clean_text(content_html) if content_html else None

        loc_obj = job.get("location") or {}
        location = loc_obj.get("name") if isinstance(loc_obj, dict) else None

        return JobScraperResult(
            url=url, title=title, company=company, description=description,
            location=location, posted_at=job.get("updated_at"), source="api",
        )
    except Exception as exc:
        logger.debug("Greenhouse API error for %s: %s", url, exc)
        return None


async def _try_lever_api(url: str, client: httpx.AsyncClient) -> Optional[JobScraperResult]:
    """
    Lever public Postings API (no auth required).
    https://api.lever.co/v0/postings/{company}/{uuid}
    Response includes descriptionPlain, lists (sections), additionalPlain, salaryRange.
    """
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None

    company_slug, posting_id = parts[0], parts[1]

    for host in ("https://api.lever.co", "https://api.eu.lever.co"):
        try:
            resp = await client.get(
                f"{host}/v0/postings/{company_slug}/{posting_id}",
                headers={**_JSON_HEADERS, "Origin": "https://jobs.lever.co"},
            )
            if resp.status_code != 200:
                continue

            d = resp.json()

            title = d.get("text")
            cats = d.get("categories") or {}
            location = cats.get("location") or (cats.get("allLocations") or [None])[0]
            workplace = d.get("workplaceType") or cats.get("commitment")

            # Build description from plain-text fields (no HTML parsing needed!)
            desc_parts: list[str] = []
            plain = d.get("descriptionPlain") or d.get("descriptionBodyPlain")
            html = d.get("description") or d.get("descriptionBody")
            if plain:
                desc_parts.append(plain.strip())
            elif html:
                desc_parts.append(_html_to_clean_text(html))

            for lst in d.get("lists") or []:
                heading = lst.get("text", "")
                content_html = lst.get("content", "")
                if content_html:
                    cleaned = _html_to_clean_text(content_html)
                    desc_parts.append(f"{heading}\n{cleaned}" if heading else cleaned)

            add_plain = d.get("additionalPlain")
            add_html = d.get("additional")
            if add_plain:
                desc_parts.append(add_plain.strip())
            elif add_html:
                desc_parts.append(_html_to_clean_text(add_html))

            description = "\n\n".join(p for p in desc_parts if p.strip()) or None

            return JobScraperResult(
                url=url, title=title, company=_slug_to_name(company_slug),
                description=description, location=location,
                job_type=_normalize_job_type(workplace),
                salary=_format_salary_lever(d["salaryRange"]) if d.get("salaryRange") else None,
                source="api",
            )
        except Exception as exc:
            logger.debug("Lever API error (%s) for %s: %s", host, url, exc)
            continue

    return None


async def _try_ashby_api(url: str, client: httpx.AsyncClient) -> Optional[JobScraperResult]:
    """
    Ashby public jobPosting.info endpoint (no auth required).
    POST https://api.ashbyhq.com/jobPosting.info  { jobPostingId: uuid }
    """
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None

    org_slug, posting_id = parts[0], parts[1]

    try:
        resp = await client.post(
            "https://api.ashbyhq.com/jobPosting.info",
            json={"jobPostingId": posting_id},
            headers={**_JSON_HEADERS, "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        if not data.get("success"):
            return None

        job = data.get("results") or {}
        title = job.get("title")
        desc_html = job.get("descriptionHtml") or job.get("description") or ""
        description = _html_to_clean_text(desc_html) if desc_html else None

        loc_obj = job.get("location") or {}
        location = (loc_obj.get("name") if isinstance(loc_obj, dict) else str(loc_obj)) if loc_obj else None

        workplace = job.get("workplaceType") or ("Remote" if job.get("isRemote") else job.get("employmentType"))

        salary = None
        comp = job.get("compensation") or {}
        if comp:
            salary = comp.get("scrapeableCompensationSalarySummary") or comp.get("compensationTierSummary")

        return JobScraperResult(
            url=url, title=title, company=_slug_to_name(org_slug),
            description=description, location=location,
            job_type=_normalize_job_type(workplace), salary=salary, source="api",
        )
    except Exception as exc:
        logger.debug("Ashby API error for %s: %s", url, exc)
        return None


async def _try_smartrecruiters_api(url: str, client: httpx.AsyncClient) -> Optional[JobScraperResult]:
    """
    SmartRecruiters public posting API (no auth required for published jobs).
    https://api.smartrecruiters.com/v1/companies/{company}/postings/{jobId}
    """
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None

    company, job_id = parts[0], parts[1]

    try:
        resp = await client.get(
            f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{job_id}",
            headers=_JSON_HEADERS,
        )
        if resp.status_code != 200:
            return None

        d = resp.json()
        title = d.get("name")
        company_name = (d.get("company") or {}).get("name") or _slug_to_name(company)

        loc = d.get("location") or {}
        city = loc.get("city", "")
        region = loc.get("region", "")
        country = loc.get("country", "")
        is_remote = loc.get("remote", False)
        location = ", ".join(p for p in [city, region, country] if p) or ("Remote" if is_remote else None)

        job_ad = d.get("jobAd") or {}
        desc_sections = [job_ad.get("jobDescription", ""), job_ad.get("qualifications", ""), job_ad.get("additionalInformation", "")]
        desc_parts = [_html_to_clean_text(s) for s in desc_sections if s and s.strip()]
        description = "\n\n".join(desc_parts) or None

        emp_type = (d.get("typeOfEmployment") or {}).get("label")

        return JobScraperResult(
            url=url, title=title, company=company_name, description=description,
            location=location, job_type=_normalize_job_type(emp_type), source="api",
        )
    except Exception as exc:
        logger.debug("SmartRecruiters API error for %s: %s", url, exc)
        return None


async def _try_workday_cxs_api(url: str, client: httpx.AsyncClient) -> Optional[JobScraperResult]:
    """
    Workday internal CXS API (reverse-engineered, widely used by scrapers).
    URL:  https://{company}.wd{N}.myworkdayjobs.com/{site}/job/{slug}/{external_id}
    API:  https://{company}.wd{N}.myworkdayjobs.com/wday/cxs/{company}/{site}/job/{external_id}/details
    """
    parsed = urlparse(url)
    m = re.match(r"^([\w-]+)\.(wd\d+)\.myworkdayjobs\.com$", parsed.netloc, re.IGNORECASE)
    if not m:
        return None

    company, wd = m.group(1), m.group(2)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    # parts: [site, "job", slug, external_id]
    if len(parts) < 4 or parts[1] != "job":
        return None

    site, external_id = parts[0], parts[3]
    api_url = f"https://{company}.{wd}.myworkdayjobs.com/wday/cxs/{company}/{site}/job/{external_id}/details"

    try:
        resp = await client.get(
            api_url,
            headers={**_JSON_HEADERS, "Sec-Fetch-Site": "same-origin"},
        )
        if resp.status_code != 200:
            return None

        d = resp.json()
        info = d.get("jobPostingInfo") or d

        title = info.get("title")
        desc_html = info.get("jobDescription") or ""
        description = _html_to_clean_text(desc_html) if desc_html else None

        loc_obj = info.get("jobRequisitionLocation") or {}
        location = (loc_obj.get("descriptor") if isinstance(loc_obj, dict) else None) or info.get("location")

        remote_obj = info.get("remoteType") or {}
        time_obj = info.get("timeType") or {}
        workplace = (remote_obj.get("descriptor") if isinstance(remote_obj, dict) else None) or \
                    (time_obj.get("descriptor") if isinstance(time_obj, dict) else None)

        return JobScraperResult(
            url=url, title=title, company=_slug_to_name(company), description=description,
            location=location, job_type=_normalize_job_type(workplace), source="api",
        )
    except Exception as exc:
        logger.debug("Workday CXS API error for %s: %s", url, exc)
        return None


# ── Platform-specific HTML extractors ─────────────────────────────────────────


def _try_indeed_initialdata(html: str, url: str) -> Optional[JobScraperResult]:
    """
    Extract job data from Indeed's embedded window._initialData JSON blob.
    Avoids fragile CSS selectors entirely; works regardless of DOM changes.
    """
    m = re.search(r"window\._initialData\s*=\s*(\{.+?\});\s*window", html, re.DOTALL)
    if not m:
        m = re.search(r"_initialData\s*=\s*(\{.+?\});", html, re.DOTALL)
    if not m:
        return None

    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None

    try:
        job_info = data["jobInfoWrapperModel"]["jobInfoModel"]
        header = job_info.get("jobInfoHeaderModel") or {}
        title = header.get("jobTitle")
        company = header.get("companyName")

        sanitized = job_info.get("sanitizedJobDescription") or {}
        desc_html = sanitized.get("content") if isinstance(sanitized, dict) else None
        description = _html_to_clean_text(desc_html) if desc_html else None

        loc = header.get("formattedLocation") or header.get("jobLocationText")
        return JobScraperResult(
            url=url, title=title, company=company, description=description,
            location=loc, source="html",
        )
    except (KeyError, TypeError):
        pass

    return None


def _extract_indeed_html(soup: BeautifulSoup, url: str) -> Optional[JobScraperResult]:
    """CSS fallback for Indeed (fragile — use only if _initialData fails)."""
    title = (
        _text(soup.find(attrs={"data-testid": "jobsearch-JobInfoHeader-title"}))
        or _text(soup.find("h1"))
    )
    company = (
        _text(soup.find(attrs={"data-testid": "inlineHeader-companyName"}))
        or _text(soup.find(class_=re.compile(r"company.*name|employer.*name", re.IGNORECASE)))
    )
    desc_div = (
        soup.find(id="jobDescriptionText")
        or soup.find(class_=re.compile(r"jobsearch-jobDescriptionText"))
    )
    description = _html_to_clean_text(str(desc_div)) if desc_div else None
    if not (title or description):
        return None
    return JobScraperResult(url=url, title=title, company=company, description=description, source="html")


# ── Generic quality-scored content extraction ─────────────────────────────────

_JUNK_PATTERN = re.compile(
    r"\b(nav|sidebar|footer|header|menu|banner|cookie|promo|advertisement"
    r"|widget|share|social|breadcrumb|related|comment|discuss)\b",
    re.IGNORECASE,
)
_JD_SIGNALS = re.compile(
    r"responsib|qualif|requirement|experience|skill|benefit|about\b|team\b"
    r"|role\b|candidate|compensat|offer\b|must\b|degree\b|year[s]?\b",
    re.IGNORECASE,
)


def _score_block(el: Tag) -> float:
    text = el.get_text(separator=" ", strip=True)
    n = len(text)
    if n < 150:
        return 0.0

    score = min(6.0, n / 300)
    score += min(5.0, text.count(",") * 0.3)
    score += len(_JD_SIGNALS.findall(text)) * 1.2
    score += min(8.0, len(el.find_all("li")) * 0.4)
    score += len(el.find_all(["h2", "h3", "h4", "h5"])) * 1.5

    # Link density penalty — high density → navigation/menu
    link_chars = sum(len(a.get_text()) for a in el.find_all("a"))
    if n and link_chars / n > 0.3:
        score *= 0.35

    return score


def _extract_generic_html(soup: BeautifulSoup, url: str) -> JobScraperResult:
    """
    Readability-inspired extraction: remove junk, score remaining content blocks,
    pick highest-scoring candidate.
    """
    # Remove obvious non-content
    for tag in ["script", "style", "noscript", "nav", "footer", "header", "aside"]:
        for el in soup.find_all(tag):
            el.decompose()
    for el in soup.find_all(attrs={"role": re.compile(r"navigation|banner|contentinfo", re.I)}):
        el.decompose()
    for el in soup.find_all(True):
        attrs = " ".join([" ".join(el.get("class") or []), el.get("id") or ""])
        if _JUNK_PATTERN.search(attrs):
            el.decompose()

    candidates = [(score, el) for el in soup.find_all(["div", "section", "article", "main"])
                  if (score := _score_block(el)) > 2]

    title = _text(soup.find("h1")) or _meta(soup, "og:title")
    company = _meta(soup, "og:site_name")
    location = None

    if not candidates:
        return JobScraperResult(
            url=url, title=title, company=company,
            description=_meta(soup, "og:description"), source="og_tags",
        )

    best = max(candidates, key=lambda x: x[0])[1]
    description = _html_to_clean_text(str(best))

    # Try to pull location from structured attributes in the best block
    loc_el = (
        best.find(attrs={"itemprop": "jobLocation"})
        or best.find(class_=re.compile(r"\blocation\b", re.IGNORECASE))
        or best.find(attrs={"data-testid": re.compile(r"location", re.IGNORECASE)})
    )
    if loc_el:
        location = _text(loc_el)

    return JobScraperResult(
        url=url, title=title, company=company, description=description,
        location=location, source="html",
    )


# ── HTTP with retry ───────────────────────────────────────────────────────────


async def _fetch_html(url: str, client: httpx.AsyncClient, retries: int = 2) -> Optional[str]:
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, headers=_BROWSER_HEADERS)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 429 and attempt < retries:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code in (403, 404, 410, 451):
                return None
            if attempt < retries:
                await asyncio.sleep(1.0)
                continue
            return None
        except httpx.TimeoutException:
            if attempt < retries:
                await asyncio.sleep(1.5 ** attempt)
                continue
        except httpx.RequestError as exc:
            logger.debug("HTTP error fetching %s: %s", url, exc)
            return None
    return None


# ── Main service ──────────────────────────────────────────────────────────────


class JobScraperService:
    async def scrape(self, url: str) -> JobScraperResult:
        url = _normalize_url(url)
        cache_key = f"job_scrape:{hashlib.md5(url.encode()).hexdigest()}"

        cached = await cache_manager.get(cache_key)
        if cached:
            try:
                result = JobScraperResult(**{k: cached.get(k) for k in JobScraperResult.__dataclass_fields__})
                result.cached = True
                return result
            except Exception:
                pass  # stale cache shape — re-scrape

        result = await self._do_scrape(url)
        result.scraped_at = datetime.now(timezone.utc).isoformat()

        if result.is_useful():
            await cache_manager.set(cache_key, asdict(result), ttl=86400)

        return result

    async def _do_scrape(self, url: str) -> JobScraperResult:
        platform = _detect_platform(url)

        async with httpx.AsyncClient(
            headers=_BROWSER_HEADERS,
            follow_redirects=True,
            timeout=_TIMEOUT,
        ) as client:

            # ── Stage 1: Platform-native JSON API ────────────────────────────
            api_fn = {
                "greenhouse": _try_greenhouse_api,
                "lever": _try_lever_api,
                "ashby": _try_ashby_api,
                "smartrecruiters": _try_smartrecruiters_api,
                "workday": _try_workday_cxs_api,
            }.get(platform)

            if api_fn:
                r = await api_fn(url, client)
                if r and r.is_useful():
                    logger.info("Scraped %s via API (%s)", url, platform)
                    return r

            # ── Stage 2: Fetch HTML ───────────────────────────────────────────
            html = await _fetch_html(url, client)
            if not html:
                return JobScraperResult(url=url, error="Page unavailable (blocked or not found)")

            soup = BeautifulSoup(html, "lxml")

            # ── Stage 3: schema.org/JobPosting JSON-LD ───────────────────────
            ld = _find_job_ld(soup)
            if ld:
                r = _parse_ld_job(ld, url)
                if r.is_useful():
                    logger.info("Scraped %s via JSON-LD", url)
                    return r

            # ── Stage 4: Platform-specific HTML ──────────────────────────────
            r = None
            if platform == "indeed":
                r = _try_indeed_initialdata(html, url) or _extract_indeed_html(soup, url)
            elif platform in ("greenhouse", "lever", "workday"):
                # API succeeded partially or had no description — let generic handle
                pass

            if r and r.is_useful():
                return r

            # ── Stage 5: Quality-scored generic extraction ────────────────────
            r = _extract_generic_html(soup, url)
            logger.info("Scraped %s via generic extractor (platform=%s)", url, platform)
            return r


job_scraper_service = JobScraperService()
