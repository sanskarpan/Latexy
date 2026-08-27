"""URL project-import service (Feature 1 Phase 2 — external sources to resume).

Turn a public portfolio / personal-site / project URL into resume-ready
``ProjectEvidence`` records (the SAME shape produced by the GitHub import), so
the existing frontend review UI can render them unchanged:

    fetch_url_text → extract_projects → build_project_evidence

PRIVACY / SAFETY: this module reads PUBLIC pages only. The fetch is a single
static HTTP GET — no JavaScript execution, no headless browser — and every
request (including redirect hops) is validated by the shared SSRF guard so it
can never reach internal/private/link-local addresses (localhost, RFC1918,
cloud metadata at 169.254.169.254, etc.). No credentials are sent.

All network + LLM calls are injectable (pass a ``client``) so tests can mock
them without touching the network or an LLM provider.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import httpx

from ..core.config import settings
from ..core.logging import get_logger

# Reuse the GitHub import's tolerant LLM-JSON parsing helpers so both import
# paths share the exact same normalization semantics.
from .github_projects_service import _extract_json_object, _normalize_str_list

# Reuse the job scraper's SSRF guard + clean-text helpers rather than
# re-implementing them — one hardened implementation, one place to audit.
from .job_scraper_service import (
    SSRFError,
    _assert_public_url,
    _html_to_clean_text,
    _SSRFGuardTransport,
)

logger = get_logger(__name__)

# Chars of cleaned page text handed to the LLM. ~4 chars/token → ~2000 tokens.
_PAGE_TEXT_MAX_CHARS = 8000

# Maximum decoded response bytes read from an upstream page.  This is enforced
# while streaming, so a missing/dishonest Content-Length header or a compressed
# response cannot make the importer buffer an unbounded body.
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024

# URL import is intentionally a static text-page importer, not a generic file
# downloader.  Keep this allow-list explicit so PDFs, images, archives, and
# arbitrary binary downloads never reach the HTML parser or LLM.
_ACCEPTED_CONTENT_TYPES = frozenset(
    {
        "application/xhtml+xml",
        "application/xml",
        "text/html",
        "text/plain",
        "text/xml",
    }
)

# Timeout for the single static GET.
_TIMEOUT = 15.0

# Never emit more than this many projects from one page.
_MAX_PROJECTS = 5

_BROWSER_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Static fetch ─────────────────────────────────────────────────────────────


def _validate_response_metadata(resp: httpx.Response) -> None:
    """Reject non-textual or declared-oversized responses before reading."""
    content_type = resp.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type not in _ACCEPTED_CONTENT_TYPES:
        raise ValueError("URL returned a missing or unsupported Content-Type")

    content_length = resp.headers.get("content-length")
    if content_length:
        try:
            declared_bytes = int(content_length)
        except ValueError:
            declared_bytes = -1
        if declared_bytes > _MAX_RESPONSE_BYTES:
            raise ValueError(f"URL response exceeds the {_MAX_RESPONSE_BYTES}-byte limit")


async def _read_response_body(resp: httpx.Response) -> str:
    """Read and decode a response without exceeding ``_MAX_RESPONSE_BYTES``."""
    body = bytearray()
    async for chunk in resp.aiter_bytes():
        if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
            raise ValueError(f"URL response exceeds the {_MAX_RESPONSE_BYTES}-byte limit")
        body.extend(chunk)

    encoding = resp.charset_encoding or "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


async def fetch_url_text(url: str, *, client: Optional[httpx.AsyncClient] = None) -> str:
    """Fetch a public URL and return its cleaned, plain-text body.

    Performs ONE SSRF-guarded static HTTP GET (public pages only — no JS
    execution) and converts the HTML to structured plain text capped at
    ``_PAGE_TEXT_MAX_CHARS``.

    Raises:
        SSRFError: the URL scheme is not http(s) or the host is not public.
        ValueError: the page could not be fetched or returned a non-2xx status.
    """
    # Pre-flight guard so an obviously-internal URL fails fast with SSRFError
    # (the transport guard below is the real enforcement, incl. redirects).
    _assert_public_url(url)

    owns_client = client is None
    client = client or httpx.AsyncClient(
        headers=_BROWSER_HEADERS,
        follow_redirects=True,
        timeout=_TIMEOUT,
        transport=_SSRFGuardTransport(),
    )
    try:
        async with client.stream("GET", url, headers=_BROWSER_HEADERS) as resp:
            if resp.status_code != 200:
                raise ValueError(f"URL returned HTTP {resp.status_code}")
            _validate_response_metadata(resp)
            response_text = await _read_response_body(resp)
    except (httpx.ConnectError, httpx.UnsupportedProtocol) as exc:
        # The guard transport raises these when it blocks a non-public host or
        # a non-http(s) redirect hop — surface as an SSRF rejection.
        raise SSRFError(f"Blocked or unreachable host for {url!r}: {exc}") from exc
    except httpx.HTTPError as exc:
        raise ValueError(f"Failed to fetch URL {url!r}: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

    return _html_to_clean_text(response_text, max_length=_PAGE_TEXT_MAX_CHARS)


# ── LLM extraction ───────────────────────────────────────────────────────────

_EXTRACT_SYSTEM_PROMPT = (
    "You are a resume-writing assistant. Given the plain text of a person's "
    "portfolio or personal website, identify the concrete software/technical "
    "PROJECTS they built. Respond with ONLY a JSON array (no prose, no markdown "
    "fences) of up to 5 objects, each of the exact shape:\n"
    '{"title": "Project name", '
    '"description": "one or two sentences on what it does and its impact", '
    '"tech": ["Key", "Technologies"], '
    '"suggested_bullets": ["achievement-oriented resume bullet", "..."], '
    '"url": "project link if the page shows one, else empty string"}\n'
    "Rules: 2-4 suggested_bullets per project, each starting with a strong "
    "action verb; never invent metrics, numbers, or facts not present in the "
    "text; tech is the concrete stack (languages, frameworks, infra) only. If "
    "the page has no real projects, return an empty array []."
)

# Fallback title mining from raw HTML when the LLM yields nothing usable.
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HEADING_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _first_page_title(page_text: str) -> str:
    """Best-effort project title from the page's <title>/<h1>/first line.

    ``page_text`` is already cleaned plain text (headings preserved), so the
    first non-empty line is the most reliable signal; the regexes are a safety
    net for callers that pass raw HTML.
    """
    for line in page_text.splitlines():
        stripped = line.strip().lstrip("•").strip()
        if stripped:
            return stripped[:120]
    for pattern in (_TITLE_RE, _HEADING_RE):
        m = pattern.search(page_text)
        if m:
            cleaned = _TAG_STRIP_RE.sub("", m.group(1)).strip()
            if cleaned:
                return cleaned[:120]
    return ""


def build_project_evidence(project: Dict[str, Any], source_url: str) -> Dict[str, Any]:
    """Normalize one extracted project into a ``ProjectEvidence`` record.

    Mirrors ``github_projects_service.build_project_evidence`` exactly so the
    frontend review UI renders URL and GitHub imports identically. A page-scraped
    project has no repo metrics, so stars/forks are 0 and ``last_active`` is null.
    """
    project_url = str(project.get("url") or "").strip() or source_url
    return {
        "source": "url",
        "title": (str(project.get("title")).strip() if project.get("title") else "")
        or "Untitled project",
        "description": str(project.get("description") or "").strip(),
        "tech": _normalize_str_list(project.get("tech")),
        "metrics": {"stars": 0, "forks": 0},
        "dates": {"last_active": None},
        "url": project_url,
        "suggested_bullets": _normalize_str_list(project.get("suggested_bullets")),
        "raw_excerpt": "",
    }


def _degrade_to_metadata(page_text: str, source_url: str) -> List[Dict[str, Any]]:
    """Single metadata-only project from the page title, or ``[]`` if none."""
    title = _first_page_title(page_text)
    if not title:
        return []
    return [build_project_evidence({"title": title, "url": source_url}, source_url)]


def extract_projects(
    page_text: str,
    source_url: str,
    api_key: Optional[str],
    *,
    client: Any = None,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract up to 5 ``ProjectEvidence`` records from page text via ONE LLM call.

    On any LLM error, missing key, or unparseable output the function degrades to
    a single metadata-only project mined from the page title (or ``[]`` when even
    that is absent) rather than raising — a flaky provider never fails the import.
    """
    truncated = (page_text or "")[:_PAGE_TEXT_MAX_CHARS]
    if not truncated.strip():
        return []

    if not api_key:
        logger.info("extract_projects: no LLM key, degrading to page metadata")
        return _degrade_to_metadata(truncated, source_url)

    user_prompt = f"Source URL: {source_url}\n\nPage text:\n{truncated}"

    try:
        if client is None:
            import openai  # noqa: PLC0415 — lazy so import stays cheap/offline-safe

            client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model or settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1200,
            temperature=0.4,
        )
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        logger.warning(f"extract_projects LLM call failed for {source_url}: {exc}")
        return _degrade_to_metadata(truncated, source_url)

    projects = _parse_project_array(raw)
    if not projects:
        return _degrade_to_metadata(truncated, source_url)

    evidence = [build_project_evidence(p, source_url) for p in projects[:_MAX_PROJECTS]]
    # Drop entries that carry no usable signal (no title AND no description).
    return [e for e in evidence if e["title"] != "Untitled project" or e["description"]]


def _parse_project_array(text: str) -> List[Dict[str, Any]]:
    """Best-effort parse of an LLM JSON array of project objects.

    Tolerates markdown fences and a single-object response; reuses the GitHub
    import's object parser as a last resort. Returns ``[]`` when unparseable.
    """
    if not text:
        return []
    import json  # noqa: PLC0415 — local, cheap

    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
    else:
        start = candidate.find("[")
        end = candidate.rfind("]")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]

    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        # Maybe the model returned a bare object — reuse the object parser.
        obj = _extract_json_object(text)
        return [obj] if obj else []

    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [p for p in parsed if isinstance(p, dict)]
    return []
