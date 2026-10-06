"""
Reference Service — fetches BibTeX from DOI (Crossref) and arXiv identifiers.

Supports:
  - DOI: Crossref API (free, polite pool with User-Agent)
  - arXiv: Atom API + manual BibTeX construction
  - Redis caching: DOI 30 days, arXiv 7 days
"""

import hashlib
import re
from typing import Optional
from urllib.parse import quote, unquote, urlsplit

# ORCID identifier: XXXX-XXXX-XXXX-XXXX (last char may be X checksum digit)
_ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dXx]$")

import httpx
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from ..core.logging import get_logger
from ..core.redis import cache_manager

logger = get_logger(__name__)

# Atom namespace
_ATOM_NS = "http://www.w3.org/2005/Atom"

# DOI: starts with "10." followed by 4+ digits then "/"
_DOI_BARE_RE = re.compile(r"^10\.\d{4,}/\S+$")
_DOI_PREFIX_RE = re.compile(r"doi:\s*(10\.\d{4,}/\S+)", re.I)

# arXiv new-style: YYMM.NNNNN (optionally vN)
_ARXIV_RE = re.compile(r"^\d{4}\.\d{4,}(?:v\d+)?$")
# arXiv old-style: category/YYMMNNN
_ARXIV_OLD_RE = re.compile(r"^[a-z][\w.-]*/\d{7}(?:v\d+)?$", re.I)
class ReferenceService:
    @staticmethod
    def parse_bibtex_entries(bibtex: str, *, limit: int = 20) -> list[dict]:
        """Parse bounded BibTeX metadata without evaluating TeX.

        This deliberately extracts only the fields needed for scholarly-record
        verification. It is brace-aware, so nested title braces do not split an
        entry, and never interprets macros or executes content.
        """
        entries: list[dict] = []
        cursor = 0
        while cursor < len(bibtex):
            match = re.search(r"@(\w+)\s*([({])", bibtex[cursor:], re.I)
            if not match:
                break
            entry_start = cursor + match.start()
            body_start = cursor + match.end()
            opener = match.group(2)
            closer = "}" if opener == "{" else ")"
            depth = 1
            quoted = False
            escaped = False
            index = body_start
            while index < len(bibtex) and depth:
                char = bibtex[index]
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = not quoted
                elif not quoted and char == opener:
                    depth += 1
                elif not quoted and char == closer:
                    depth -= 1
                index += 1
            if depth:
                raise ValueError("BibTeX contains an unterminated entry")

            raw = bibtex[entry_start:index]
            if match.group(1).casefold() in {"comment", "preamble", "string"}:
                cursor = index
                continue
            key_match = re.match(r"@\w+\s*[({]\s*([^,\s]+)\s*,", raw, re.I)
            if not key_match:
                raise ValueError("BibTeX entry is missing a cite key")
            entries.append(
                {
                    "cite_key": key_match.group(1),
                    "title": ReferenceService._extract_bibtex_field(raw, "title"),
                    "authors": ReferenceService._extract_bibtex_field(raw, "author"),
                    "year": ReferenceService._extract_bibtex_field(raw, "year"),
                    "doi": ReferenceService._extract_bibtex_field(raw, "doi"),
                    "eprint": ReferenceService._extract_bibtex_field(raw, "eprint"),
                    "archive_prefix": ReferenceService._extract_bibtex_field(raw, "archivePrefix"),
                }
            )
            if len(entries) > limit:
                raise ValueError(f"At most {limit} BibTeX entries can be checked at once")
            cursor = index
        if not entries:
            raise ValueError("No BibTeX entries were found")
        return entries

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
        return self.normalize_identifier(identifier)[1]

    @staticmethod
    def _provider_url_parts(identifier: str) -> tuple[str, list[str]] | None:
        try:
            parsed = urlsplit(identifier)
        except ValueError:
            return None
        if parsed.scheme not in {"http", "https"} or parsed.username is not None:
            return None
        return (parsed.hostname or "").lower(), [
            unquote(part) for part in parsed.path.split("/") if part
        ]

    def normalize_identifier(self, identifier: str) -> tuple[str, Optional[str]]:
        """Return (normalized_id, type). Strips URLs and version suffixes."""
        identifier = identifier.strip()

        provider_url = self._provider_url_parts(identifier)
        if provider_url:
            host, parts = provider_url
            if host in {"doi.org", "dx.doi.org"} and parts:
                doi = "/".join(parts)
                if _DOI_BARE_RE.fullmatch(doi):
                    return doi.rstrip(".,;)"), "doi"
            if host == "arxiv.org" and len(parts) >= 2 and parts[0].lower() in {"abs", "pdf"}:
                arxiv_id = "/".join(parts[1:]).removesuffix(".pdf")
                if _ARXIV_RE.fullmatch(arxiv_id) or _ARXIV_OLD_RE.fullmatch(arxiv_id):
                    return self._strip_arxiv_version(arxiv_id), "arxiv"

        prefixed_doi = _DOI_PREFIX_RE.fullmatch(identifier)
        if prefixed_doi:
            return prefixed_doi.group(1).rstrip(".,;)"), "doi"

        # Bare DOI
        if _DOI_BARE_RE.fullmatch(identifier):
            return identifier.rstrip(".,;)"), "doi"

        # Bare arXiv (new style)
        if _ARXIV_RE.fullmatch(identifier):
            return self._strip_arxiv_version(identifier), "arxiv"

        # Bare arXiv (old style)
        if _ARXIV_OLD_RE.fullmatch(identifier):
            return self._strip_arxiv_version(identifier), "arxiv"

        return identifier, None

    # ── DOI fetcher ───────────────────────────────────────────────────────────

    async def fetch_doi(self, doi: str) -> dict:
        """Fetch BibTeX for a DOI via Crossref; cache 30 days."""
        cache_key = f"bibtex:doi:{doi}"
        try:
            cached = await cache_manager.get(cache_key)
        except Exception as exc:
            logger.warning("Reference cache read failed", extra={"error_type": type(exc).__name__})
            cached = None
        if cached:
            return {**cached, "cached": True}

        encoded_doi = quote(doi, safe="")
        url = f"https://api.crossref.org/works/{encoded_doi}/transform/application/x-bibtex"
        headers = {
            "User-Agent": "Latexy/1.0 (mailto:support@latexy.com; https://latexy.xyz)",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)

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
                    logger.warning("Reference cache write failed", extra={"error_type": type(exc).__name__})
                return result

            raise ValueError(f"DOI not found: {doi} (HTTP {response.status_code})")

        except httpx.TimeoutException:
            raise ValueError(f"Timeout fetching DOI: {doi}")
        except httpx.RequestError as exc:
            raise ValueError(f"Network error fetching DOI {doi}: {exc}")

    async def search_crossref(self, title: str, authors: Optional[str] = None) -> dict:
        """Return the best Crossref work for identifier-free citation metadata."""
        query = " ".join(part for part in (title.strip(), (authors or "").strip()) if part)
        digest = hashlib.sha256(query.casefold().encode()).hexdigest()[:32]
        cache_key = f"citation-search:crossref:{digest}"
        try:
            cached = await cache_manager.get(cache_key)
        except Exception as exc:
            logger.warning("Citation cache read failed", extra={"error_type": type(exc).__name__})
            cached = None
        if cached:
            return {**cached, "cached": True}

        headers = {
            "User-Agent": "Latexy/1.0 (mailto:support@latexy.com; https://latexy.xyz)",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.crossref.org/works",
                    params={
                        "query.bibliographic": query,
                        "rows": 1,
                        "select": "DOI,title,author,published-print,published-online,issued",
                    },
                    headers=headers,
                )
            if response.status_code != 200:
                raise ValueError(f"Crossref search failed (HTTP {response.status_code})")
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError
            message = payload.get("message")
            if not isinstance(message, dict):
                raise TypeError
            items = message.get("items", [])
            if not isinstance(items, list):
                raise TypeError
            if not items:
                raise ValueError("No scholarly match found")
            item = items[0]
            if not isinstance(item, dict):
                raise TypeError
            titles = item.get("title") or []
            author_names = [
                ", ".join(filter(None, (author.get("family"), author.get("given"))))
                for author in item.get("author") or []
                if isinstance(author, dict)
            ]
            date = (
                item.get("published-print")
                or item.get("published-online")
                or item.get("issued")
                or {}
            )
            parts = date.get("date-parts") or []
            year = parts[0][0] if parts and parts[0] else None
            result = {
                "identifier": item.get("DOI"),
                "title": titles[0] if titles else None,
                "authors": " and ".join(author_names) or None,
                "year": year,
                "cached": False,
            }
            try:
                await cache_manager.set(cache_key, result, ttl=86400 * 7)
            except Exception as exc:
                logger.warning("Citation cache write failed", extra={"error_type": type(exc).__name__})
            return result
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError("Crossref returned malformed citation metadata") from exc
        except httpx.TimeoutException:
            raise ValueError("Crossref citation search timed out")
        except httpx.RequestError as exc:
            raise ValueError(f"Crossref citation search failed: {exc}")

    # ── arXiv fetcher ─────────────────────────────────────────────────────────

    async def fetch_arxiv(self, arxiv_id: str) -> dict:
        """Fetch metadata from arXiv Atom API and build BibTeX; cache 7 days."""
        clean_id = self._strip_arxiv_version(arxiv_id)
        cache_key = f"bibtex:arxiv:{clean_id}"
        try:
            cached = await cache_manager.get(cache_key)
        except Exception as exc:
            logger.warning("Reference cache read failed", extra={"error_type": type(exc).__name__})
            cached = None
        if cached:
            return {**cached, "cached": True}

        url = "https://export.arxiv.org/api/query"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params={"id_list": clean_id})

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
                logger.warning("Reference cache write failed", extra={"error_type": type(exc).__name__})
            return result

        except httpx.TimeoutException:
            raise ValueError(f"Timeout fetching arXiv: {arxiv_id}")
        except httpx.RequestError as exc:
            raise ValueError(f"Network error fetching arXiv {arxiv_id}: {exc}")

    # ── arXiv XML parser ──────────────────────────────────────────────────────

    def _parse_arxiv_xml(self, xml_text: str, arxiv_id: str) -> tuple[str, dict]:
        try:
            root = ET.fromstring(xml_text)
        except (ET.ParseError, DefusedXmlException) as exc:
            raise ValueError("Invalid arXiv XML response") from exc
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

    @staticmethod
    def _extract_bibtex_field(bibtex: str, field: str) -> Optional[str]:
        """Extract a named field value from a BibTeX entry string."""
        pattern = re.compile(
            rf"(?:^|,)\s*{re.escape(field)}\s*=\s*", re.I | re.M
        )
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

    # ── ORCID fetcher ─────────────────────────────────────────────────────────

    def normalize_orcid(self, raw: str) -> Optional[str]:
        """Extract a bare ORCID ID from a URL or bare string, or return None."""
        raw = raw.strip()
        provider_url = self._provider_url_parts(raw)
        if provider_url:
            host, parts = provider_url
            if host == "orcid.org" and len(parts) == 1 and _ORCID_RE.fullmatch(parts[0]):
                return parts[0].upper().replace("x", "X")
        if _ORCID_RE.fullmatch(raw):
            return raw.upper().replace("x", "X")
        return None

    async def fetch_orcid_works(
        self, orcid_id: str, max_results: int = 20
    ) -> list[dict]:
        """
        Fetch publication summaries from ORCID public API.
        Returns a list of dicts with: title, year, journal, doi, url, work_type.
        Sorted by year descending. Cached in Redis for 24h.
        """
        if not _ORCID_RE.fullmatch(orcid_id):
            raise ValueError(f"Invalid ORCID identifier: {orcid_id}")

        cache_key = f"orcid:works:{orcid_id}"
        try:
            cached = await cache_manager.get(cache_key)
        except Exception as exc:
            logger.warning("ORCID cache read failed", extra={"error_type": type(exc).__name__})
            cached = None
        if isinstance(cached, list):
            return cached[:max_results]

        url = f"https://pub.orcid.org/v3.0/{quote(orcid_id, safe='')}/works"
        headers = {
            "Accept": "application/json",
            "User-Agent": "Latexy/1.0 (mailto:support@latexy.com; https://latexy.xyz)",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=headers)

            if response.status_code == 404:
                raise ValueError(f"ORCID profile not found: {orcid_id}")
            if response.status_code != 200:
                raise ValueError(f"ORCID API error: HTTP {response.status_code}")

            data = response.json()
            works = self._parse_orcid_response(data)

            try:
                await cache_manager.set(cache_key, works, ttl=86400)
            except Exception as exc:
                logger.warning("ORCID cache write failed", extra={"error_type": type(exc).__name__})

            return works[:max_results]

        except httpx.TimeoutException:
            raise ValueError(f"Timeout fetching ORCID profile: {orcid_id}")
        except httpx.RequestError as exc:
            raise ValueError(f"Network error fetching ORCID {orcid_id}: {exc}")

    def _parse_orcid_response(self, data: dict) -> list[dict]:
        """Parse ORCID /works JSON response into a normalized list of works."""
        groups = data.get("group", [])
        works: list[dict] = []

        for group in groups:
            summaries = group.get("work-summary", [])
            if not summaries:
                continue
            summary = summaries[0]  # prefer first (highest source priority)

            # Title
            title_obj = summary.get("title", {}) or {}
            title = (title_obj.get("title") or {}).get("value", "")

            # Year
            year: Optional[int] = None
            pub_date = summary.get("publication-date") or {}
            year_obj = pub_date.get("year") or {}
            if year_obj.get("value"):
                try:
                    year = int(year_obj["value"])
                except (ValueError, TypeError):
                    pass

            # Journal / venue
            jt = summary.get("journal-title") or {}
            journal = jt.get("value", "") if isinstance(jt, dict) else ""

            # Work type (normalize to lowercase no-separator)
            raw_type = summary.get("type", "misc") or "misc"
            work_type = raw_type.lower().replace("-", "").replace("_", "")

            # DOI (first one found)
            doi: Optional[str] = None
            ext_ids = (summary.get("external-ids") or {}).get("external-id", []) or []
            for ext in ext_ids:
                if ext.get("external-id-type") == "doi":
                    val = (ext.get("external-id-value") or "").strip()
                    if val:
                        doi = val
                        break

            # URL
            url_obj = summary.get("url") or {}
            url_val = url_obj.get("value", "") if isinstance(url_obj, dict) else ""

            works.append(
                {
                    "title": title,
                    "year": year,
                    "journal": journal,
                    "doi": doi,
                    "url": url_val,
                    "work_type": work_type,
                }
            )

        # Sort: year desc, then title asc
        works.sort(key=lambda w: (-(w["year"] or 0), w["title"] or ""))
        return works


reference_service = ReferenceService()
