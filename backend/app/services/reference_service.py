"""
Reference Service — fetches BibTeX from DOI (Crossref) and arXiv identifiers.

Supports:
  - DOI: Crossref API (free, polite pool with User-Agent)
  - arXiv: Atom API + manual BibTeX construction
  - Redis caching: DOI 30 days, arXiv 7 days
"""

import re
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import quote

import httpx

from ..core.logging import get_logger
from ..core.redis import cache_manager

logger = get_logger(__name__)

# Atom namespace
_ATOM_NS = "http://www.w3.org/2005/Atom"

# DOI: starts with "10." followed by 4+ digits then "/"
_DOI_BARE_RE = re.compile(r"^10\.\d{4,}/\S+$")
# DOI embedded in URL
_DOI_URL_RE = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)(10\.\d{4,}/\S+)", re.I)

# arXiv new-style: YYMM.NNNNN (optionally vN)
_ARXIV_RE = re.compile(r"^\d{4}\.\d{4,}(?:v\d+)?$")
# arXiv old-style: category/YYMMNNN
_ARXIV_OLD_RE = re.compile(r"^[a-z][\w.-]*/\d{7}(?:v\d+)?$", re.I)
# arXiv in URL
_ARXIV_URL_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,}(?:v\d+)?|[a-z][\w.-]*/\d{7}(?:v\d+)?)",
    re.I,
)


class ReferenceService:
    @staticmethod
    def _strip_arxiv_version(identifier: str) -> str:
        """Strip trailing version suffix (v1, v2, …) from an arXiv ID.

        Uses a regex anchored at end-of-string so archive names that contain
        the letter 'v' (e.g. 'solv-int/9901001v2') are not mangled.
        """
        return re.sub(r"v\d+$", "", identifier, flags=re.I)

    # ── Identifier detection ──────────────────────────────────────────────────

    def detect_type(self, identifier: str) -> Optional[str]:
        """Return 'doi', 'arxiv', or None."""
        identifier = identifier.strip()
        if _DOI_URL_RE.search(identifier) or _DOI_BARE_RE.match(identifier):
            return "doi"
        if _ARXIV_URL_RE.search(identifier) or _ARXIV_RE.match(identifier) or _ARXIV_OLD_RE.match(identifier):
            return "arxiv"
        return None

    def normalize_identifier(self, identifier: str) -> tuple[str, Optional[str]]:
        """Return (normalized_id, type). Strips URLs and version suffixes."""
        identifier = identifier.strip()

        # DOI in URL
        m = _DOI_URL_RE.search(identifier)
        if m:
            return m.group(1).rstrip(".,;)"), "doi"

        # arXiv in URL
        m = _ARXIV_URL_RE.search(identifier)
        if m:
            return self._strip_arxiv_version(m.group(1)), "arxiv"

        # Bare DOI
        if _DOI_BARE_RE.match(identifier):
            return identifier.rstrip(".,;)"), "doi"

        # Bare arXiv (new style)
        if _ARXIV_RE.match(identifier):
            return self._strip_arxiv_version(identifier), "arxiv"

        # Bare arXiv (old style)
        if _ARXIV_OLD_RE.match(identifier):
            return self._strip_arxiv_version(identifier), "arxiv"

        return identifier, None

    # ── DOI fetcher ───────────────────────────────────────────────────────────

    async def fetch_doi(self, doi: str) -> dict:
        """Fetch BibTeX for a DOI via Crossref; cache 30 days."""
        cache_key = f"bibtex:doi:{doi}"
        try:
            cached = await cache_manager.get(cache_key)
        except Exception as exc:
            logger.warning("Reference cache read failed for %s: %s", cache_key, exc)
            cached = None
        if cached:
            return {**cached, "cached": True}

        encoded_doi = quote(doi, safe="")
        url = f"https://api.crossref.org/works/{encoded_doi}/transform/application/x-bibtex"
        headers = {
            "User-Agent": "Latexy/1.0 (mailto:support@latexy.io; https://latexy.io)",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)

            if response.status_code == 200:
                bibtex = response.text
                cite_key = self._extract_cite_key(bibtex) or f"ref_{doi[:12].replace('/', '_')}"
                title = self._extract_bibtex_field(bibtex, "title")
                authors = self._extract_bibtex_field(bibtex, "author")
                year_str = self._extract_bibtex_field(bibtex, "year")

                result = {
                    "bibtex": bibtex,
                    "cite_key": cite_key,
                    "title": title,
                    "authors": authors,
                    "year": int(year_str) if year_str and year_str.isdigit() else None,
                    "cached": False,
                }
                try:
                    await cache_manager.set(cache_key, result, ttl=86400 * 30)
                except Exception as exc:
                    logger.warning("Reference cache write failed for %s: %s", cache_key, exc)
                return result

            raise ValueError(f"DOI not found: {doi} (HTTP {response.status_code})")

        except httpx.TimeoutException:
            raise ValueError(f"Timeout fetching DOI: {doi}")
        except httpx.RequestError as exc:
            raise ValueError(f"Network error fetching DOI {doi}: {exc}")

    # ── arXiv fetcher ─────────────────────────────────────────────────────────

    async def fetch_arxiv(self, arxiv_id: str) -> dict:
        """Fetch metadata from arXiv Atom API and build BibTeX; cache 7 days."""
        clean_id = self._strip_arxiv_version(arxiv_id)
        cache_key = f"bibtex:arxiv:{clean_id}"
        try:
            cached = await cache_manager.get(cache_key)
        except Exception as exc:
            logger.warning("Reference cache read failed for %s: %s", cache_key, exc)
            cached = None
        if cached:
            return {**cached, "cached": True}

        url = f"https://export.arxiv.org/api/query?id_list={clean_id}"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0)

            if response.status_code != 200:
                raise ValueError(f"arXiv API error: HTTP {response.status_code}")

            bibtex, meta = self._parse_arxiv_xml(response.text, clean_id)
            result = {
                "bibtex": bibtex,
                "cite_key": meta["cite_key"],
                "title": meta.get("title"),
                "authors": meta.get("authors"),
                "year": meta.get("year"),
                "cached": False,
            }
            try:
                await cache_manager.set(cache_key, result, ttl=86400 * 7)
            except Exception as exc:
                logger.warning("Reference cache write failed for %s: %s", cache_key, exc)
            return result

        except httpx.TimeoutException:
            raise ValueError(f"Timeout fetching arXiv: {arxiv_id}")
        except httpx.RequestError as exc:
            raise ValueError(f"Network error fetching arXiv {arxiv_id}: {exc}")

    # ── arXiv XML parser ──────────────────────────────────────────────────────

    def _parse_arxiv_xml(self, xml_text: str, arxiv_id: str) -> tuple[str, dict]:
        root = ET.fromstring(xml_text)
        entries = root.findall(f"{{{_ATOM_NS}}}entry")
        if not entries:
            raise ValueError(f"arXiv ID not found: {arxiv_id}")

        entry = entries[0]

        title_el = entry.find(f"{{{_ATOM_NS}}}title")
        title = title_el.text.strip() if title_el is not None else ""
        if title.lower() == "error":
            raise ValueError(f"arXiv ID not found: {arxiv_id}")

        # Authors
        author_names: list[str] = []
        for a in entry.findall(f"{{{_ATOM_NS}}}author"):
            name_el = a.find(f"{{{_ATOM_NS}}}name")
            if name_el is not None and name_el.text:
                author_names.append(name_el.text.strip())

        bibtex_authors = " and ".join(
            self._format_author_bibtex(n) for n in author_names
        )

        # Year
        year: Optional[int] = None
        pub_el = entry.find(f"{{{_ATOM_NS}}}published")
        if pub_el is not None and pub_el.text:
            try:
                year = int(pub_el.text.strip()[:4])
            except ValueError:
                pass

        # Primary category
        primary_class: Optional[str] = None
        for cat_el in entry.findall(f"{{{_ATOM_NS}}}category"):
            term = cat_el.get("term", "")
            if term:
                primary_class = term
                break

        # Cite key: FirstAuthorLastName + Year, fallback to arxiv_YYMM_NNNNN
        safe_id = arxiv_id.replace(".", "_")
        cite_key = f"arxiv_{safe_id}"
        if author_names and year:
            last = re.sub(r"[^A-Za-z]", "", author_names[0].split()[-1])
            if last:
                cite_key = f"{last}{year}"

        # Build BibTeX
        lines = [f"@misc{{{cite_key},"]
        lines.append(f"  title = {{{{{title}}}}},")
        if bibtex_authors:
            lines.append(f"  author = {{{bibtex_authors}}},")
        if year:
            lines.append(f"  year = {{{year}}},")
        lines.append(f"  eprint = {{{arxiv_id}}},")
        lines.append("  archivePrefix = {arXiv},")
        if primary_class:
            lines.append(f"  primaryClass = {{{primary_class}}},")
        lines.append(f"  url = {{https://arxiv.org/abs/{arxiv_id}}},")
        lines.append("}")

        display_authors = (
            ", ".join(author_names[:3]) + (" et al." if len(author_names) > 3 else "")
            if author_names else None
        )

        meta = {
            "cite_key": cite_key,
            "title": title,
            "authors": display_authors,
            "year": year,
        }
        return "\n".join(lines), meta

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _format_author_bibtex(self, name: str) -> str:
        """Convert 'First Last' → 'Last, First'."""
        parts = name.strip().split()
        if len(parts) <= 1:
            return name
        return f"{parts[-1]}, {' '.join(parts[:-1])}"

    def _extract_bibtex_field(self, bibtex: str, field: str) -> Optional[str]:
        """Extract a named field value from a BibTeX entry string."""
        pattern = re.compile(rf"^\s*{re.escape(field)}\s*=\s*", re.I | re.M)
        m = pattern.search(bibtex)
        if not m:
            return None
        rest = bibtex[m.end():].lstrip()
        if rest.startswith("{"):
            depth = 0
            for i, ch in enumerate(rest):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return rest[1:i].strip()
        elif rest.startswith('"'):
            end = rest.find('"', 1)
            if end != -1:
                return rest[1:end].strip()
        else:
            end = rest.find(",")
            if end == -1:
                end = rest.find("\n")
            return rest[:end].strip() if end != -1 else rest.strip()
        return None

    def _extract_cite_key(self, bibtex: str) -> Optional[str]:
        """Extract cite key from '@type{key,' pattern."""
        m = re.match(r"@\w+\{([^,\s]+)", bibtex.strip())
        return m.group(1) if m else None


reference_service = ReferenceService()
