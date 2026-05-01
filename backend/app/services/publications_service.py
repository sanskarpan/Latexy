"""
Publications service for Feature 58 — Publication List Auto-Generator.

Fetches publications from ORCID (free public API) and formats them as
LaTeX bibliography entries inside a \\section{Publications} block.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import httpx

from ..core.logging import get_logger

logger = get_logger(__name__)

ORCID_API_BASE = "https://pub.orcid.org/v3.0"

_KNOWN_PUB_TYPES = {"journal", "conference", "preprint", "book_chapter"}


@dataclass
class Publication:
    title: str
    authors: List[str]
    venue: str          # journal name or conference
    year: Optional[int]
    doi: Optional[str]
    url: Optional[str]
    pub_type: str       # "journal" | "conference" | "preprint" | "book_chapter"


class PublicationsService:
    # ── ORCID fetch ──────────────────────────────────────────────────────────

    async def fetch_from_orcid(self, orcid_id: str) -> List[Publication]:
        """Fetch all works for an ORCID iD and return as Publication list."""
        url = f"{ORCID_API_BASE}/{orcid_id}/works"
        headers = {"Accept": "application/json"}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                raise ValueError(f"ORCID iD not found: {orcid_id}")
            resp.raise_for_status()
            data = resp.json()

        publications: List[Publication] = []
        for group in data.get("group", []):
            pub = self._parse_work_group(group)
            if pub:
                publications.append(pub)

        return publications

    def _parse_work_group(self, group: dict) -> Optional[Publication]:
        """Parse a single work-group from the ORCID /works summary response."""
        summaries = group.get("work-summary", [])
        if not summaries:
            return None

        # Use the first (preferred) summary
        summary = summaries[0]

        title_obj = summary.get("title", {}) or {}
        title_inner = title_obj.get("title", {}) or {}
        title = (title_inner.get("value") or "").strip()
        if not title:
            return None

        year_obj = (summary.get("publication-date") or {}).get("year") or {}
        year_raw = year_obj.get("value")
        year: Optional[int] = int(year_raw) if year_raw and year_raw.isdigit() else None

        journal_obj = summary.get("journal-title") or {}
        venue = (journal_obj.get("value") or "").strip()

        # Determine pub_type from work-type
        work_type = (summary.get("type") or "").lower()
        pub_type = self._map_work_type(work_type)

        # External IDs → DOI / URL
        doi: Optional[str] = None
        url: Optional[str] = None
        ext_ids = (summary.get("external-ids") or {}).get("external-id", []) or []
        for ext in ext_ids:
            id_type = (ext.get("external-id-type") or "").lower()
            id_value = (ext.get("external-id-value") or "").strip()
            id_url = (ext.get("external-id-url") or {}).get("value") or ""
            if id_type == "doi" and id_value:
                doi = id_value
                if not url and id_url:
                    url = id_url
            elif id_url and not url:
                url = id_url

        # Contributors come from the detailed work record; summaries only
        # include contributor count. We leave authors empty for the summary
        # endpoint — callers that need contributors should fetch the full work.
        authors: List[str] = []

        return Publication(
            title=title,
            authors=authors,
            venue=venue,
            year=year,
            doi=doi,
            url=url,
            pub_type=pub_type,
        )

    @staticmethod
    def _map_work_type(work_type: str) -> str:
        if "journal" in work_type:
            return "journal"
        if "conference" in work_type or "proceedings" in work_type:
            return "conference"
        if "preprint" in work_type or "working" in work_type:
            return "preprint"
        if "book" in work_type or "chapter" in work_type:
            return "book_chapter"
        return "journal"  # default

    # ── LaTeX formatter ───────────────────────────────────────────────────────

    def format_as_latex(
        self,
        pubs: List[Publication],
        sort_by: str = "year",
    ) -> str:
        """Return a complete \\section{Publications}\\begin{enumerate}...\\end{enumerate} block."""
        if not pubs:
            return ""

        if sort_by == "year":
            sorted_pubs = sorted(
                pubs,
                key=lambda p: p.year if p.year is not None else 0,
                reverse=True,
            )
        else:
            sorted_pubs = list(pubs)

        items: List[str] = []
        for pub in sorted_pubs:
            items.append(self._format_entry(pub))

        entries = "\n".join(f"  \\item {item}" for item in items)
        return (
            "\\section{Publications}\n"
            "\\begin{enumerate}\n"
            f"{entries}\n"
            "\\end{enumerate}"
        )

    @staticmethod
    def _format_entry(pub: Publication) -> str:
        """Format a single publication as a LaTeX \\item string."""
        # Authors
        if pub.authors:
            authors_str = ", ".join(pub.authors) + "."
        else:
            authors_str = ""

        # Title in double-quotes
        title_str = f"``{pub.title}.''"

        # Venue in italics
        venue_str = f"\\textit{{{pub.venue}}}" if pub.venue else ""

        # Year
        year_str = str(pub.year) if pub.year else ""

        # DOI hyperlink
        doi_str = ""
        if pub.doi:
            doi_str = f" \\href{{https://doi.org/{pub.doi}}}{{{pub.doi}}}"

        parts = [p for p in [authors_str, title_str, venue_str, year_str] if p]
        entry = " ".join(parts)
        if parts:
            entry = entry.rstrip(".") + "."
        if doi_str:
            entry += doi_str

        return entry


publications_service = PublicationsService()
