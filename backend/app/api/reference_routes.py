"""
Reference routes — fetch BibTeX from DOI (Crossref) and arXiv identifiers.
"""

import asyncio
import re
import time
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_optional
from ..services.reference_service import reference_service

logger = get_logger(__name__)

router = APIRouter(prefix="/references", tags=["references"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class BibTeXEntry(BaseModel):
    identifier: str
    bibtex: Optional[str] = None
    cite_key: str
    title: Optional[str] = None
    authors: Optional[str] = None
    year: Optional[int] = None
    source_type: Optional[str] = None  # "doi" | "arxiv" | "unknown"
    cached: bool = False
    error: Optional[str] = None


class FetchReferencesRequest(BaseModel):
    identifiers: List[str] = Field(..., min_length=1, max_length=20)


class FetchReferencesResponse(BaseModel):
    entries: List[BibTeXEntry]
    total: int
    successful: int
    processing_time: float


class DetectIdentifierResult(BaseModel):
    raw: str
    normalized: str
    type: Optional[str] = None  # "doi" | "arxiv"


class DetectReferencesRequest(BaseModel):
    text: str = Field(..., max_length=10000)


class DetectReferencesResponse(BaseModel):
    detected: List[DetectIdentifierResult]
    count: int


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _fetch_one(identifier: str) -> BibTeXEntry:
    """Fetch BibTeX for a single identifier. Never raises — errors go into the entry."""
    normalized, id_type = reference_service.normalize_identifier(identifier)

    if id_type is None:
        return BibTeXEntry(
            identifier=identifier,
            cite_key=f"ref_{identifier[:16].replace('/', '_')}",
            source_type="unknown",
            error=(
                "Could not determine identifier type. "
                "Expected a DOI (e.g. 10.1145/3386569.3392408) "
                "or an arXiv ID (e.g. 1706.03762)."
            ),
        )

    try:
        if id_type == "doi":
            result = await reference_service.fetch_doi(normalized)
        else:
            result = await reference_service.fetch_arxiv(normalized)

        return BibTeXEntry(
            identifier=identifier,
            bibtex=result["bibtex"],
            cite_key=result["cite_key"],
            title=result.get("title"),
            authors=result.get("authors"),
            year=result.get("year"),
            source_type=id_type,
            cached=result.get("cached", False),
        )

    except ValueError as exc:
        return BibTeXEntry(
            identifier=identifier,
            cite_key=f"ref_{normalized[:16].replace('/', '_')}",
            source_type=id_type,
            error=str(exc),
        )
    except Exception as exc:
        logger.error(f"Unexpected error fetching reference '{identifier}': {exc}")
        return BibTeXEntry(
            identifier=identifier,
            cite_key=f"ref_{normalized[:16].replace('/', '_')}",
            source_type=id_type,
            error=f"Unexpected error: {type(exc).__name__}",
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/fetch", response_model=FetchReferencesResponse)
async def fetch_references(
    request: FetchReferencesRequest,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Fetch BibTeX for a list of DOI or arXiv identifiers (max 20, concurrent)."""
    start = time.monotonic()

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_ids: list[str] = []
    for ident in request.identifiers:
        stripped = ident.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            unique_ids.append(stripped)

    tasks = [asyncio.create_task(_fetch_one(ident)) for ident in unique_ids]
    done, pending = await asyncio.wait(tasks, timeout=30.0)

    # Cancel tasks that did not finish in time
    for t in pending:
        t.cancel()

    # Collect results in original order
    task_index = {t: i for i, t in enumerate(tasks)}
    entries: list[BibTeXEntry] = [None] * len(tasks)  # type: ignore[list-item]
    for t in done:
        i = task_index[t]
        exc = t.exception()
        if exc is not None:
            ident = unique_ids[i]
            entries[i] = BibTeXEntry(
                identifier=ident,
                cite_key=f"ref_{ident[:16].replace('/', '_')}",
                error=f"Unexpected error: {type(exc).__name__}",
            )
        else:
            entries[i] = t.result()
    for t in pending:
        i = task_index[t]
        ident = unique_ids[i]
        entries[i] = BibTeXEntry(
            identifier=ident,
            cite_key=f"ref_{ident[:16].replace('/', '_')}",
            error="Request timed out",
        )

    successful = sum(1 for e in entries if e.bibtex is not None)

    return FetchReferencesResponse(
        entries=entries,
        total=len(entries),
        successful=successful,
        processing_time=round(time.monotonic() - start, 3),
    )


# ── ORCID helpers ─────────────────────────────────────────────────────────────

_ORCID_BIB_TYPE: dict[str, str] = {
    "journalarticle": "article",
    "conferencepaper": "inproceedings",
    "bookchapter": "incollection",
    "book": "book",
    "dissertation": "phdthesis",
    "report": "techreport",
    "preprint": "misc",
    "workingpaper": "unpublished",
}


def _bibtex_from_orcid_work(work: dict, idx: int) -> tuple[str, str]:
    """Build minimal BibTeX from ORCID work metadata. Returns (bibtex, cite_key)."""
    bib_type = _ORCID_BIB_TYPE.get(work.get("work_type", "misc"), "misc")
    title = work.get("title") or "Untitled"
    year = work.get("year")
    journal = work.get("journal") or ""
    url = work.get("url") or ""

    # Cite key: first word of title + year
    first_word = re.sub(r"[^a-zA-Z]", "", title.split()[0]).lower() if title else "work"
    cite_key = f"{first_word}{year or 'nd'}"

    lines = [f"@{bib_type}{{{cite_key},"]
    lines.append(f"  title = {{{{{title}}}}},")
    if year:
        lines.append(f"  year = {{{year}}},")
    if journal:
        field = "journal" if bib_type == "article" else "booktitle"
        lines.append(f"  {field} = {{{{{journal}}}}},")
    if url:
        lines.append(f"  url = {{{url}}},")
    lines.append("  note = {Via ORCID},")
    lines.append("}")
    return "\n".join(lines), cite_key


# ── ORCID endpoint ─────────────────────────────────────────────────────────────


class FetchOrcidRequest(BaseModel):
    orcid_id: str = Field(..., description="Bare ORCID ID (XXXX-XXXX-XXXX-XXXX) or ORCID URL")
    max_results: int = Field(default=20, ge=1, le=50)


@router.post("/fetch-orcid", response_model=FetchReferencesResponse)
async def fetch_orcid_publications(
    request: FetchOrcidRequest,
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """
    Fetch publications from a public ORCID profile.
    Works with DOIs are enriched via Crossref; others get minimal BibTeX from ORCID metadata.
    """
    start = time.monotonic()

    # Normalize ORCID ID (accept URLs too)
    normalized = reference_service.normalize_orcid(request.orcid_id)
    if normalized is None:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail="Invalid ORCID identifier. Expected format: 0000-0001-2345-6789 or https://orcid.org/...",
        )

    try:
        works = await reference_service.fetch_orcid_works(normalized, request.max_results)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(exc))

    if not works:
        return FetchReferencesResponse(entries=[], total=0, successful=0, processing_time=0.0)

    # Separate DOI-bearing works (fetch Crossref BibTeX, up to 10) from others
    doi_indices = [i for i, w in enumerate(works) if w.get("doi")][:10]
    entries: list[Optional[BibTeXEntry]] = [None] * len(works)

    # Concurrent Crossref fetches for works with DOI
    if doi_indices:
        doi_tasks = [asyncio.create_task(_fetch_one(works[i]["doi"])) for i in doi_indices]
        done, pending = await asyncio.wait(doi_tasks, timeout=25.0)
        for t in pending:
            t.cancel()

        task_map = {t: doi_indices[j] for j, t in enumerate(doi_tasks)}
        for t in done:
            orig_i = task_map[t]
            work = works[orig_i]
            exc = t.exception()
            fetched = None if exc else t.result()
            if fetched and fetched.bibtex and not fetched.error:
                fetched.source_type = "orcid"
                entries[orig_i] = fetched
            else:
                # Crossref failed → fall back to ORCID-built BibTeX
                bibtex, cite_key = _bibtex_from_orcid_work(work, orig_i)
                entries[orig_i] = BibTeXEntry(
                    identifier=work["doi"],
                    bibtex=bibtex,
                    cite_key=cite_key,
                    title=work.get("title"),
                    year=work.get("year"),
                    source_type="orcid",
                )
        for t in pending:
            orig_i = task_map[t]
            work = works[orig_i]
            bibtex, cite_key = _bibtex_from_orcid_work(work, orig_i)
            entries[orig_i] = BibTeXEntry(
                identifier=work.get("doi", f"orcid_{orig_i}"),
                bibtex=bibtex, cite_key=cite_key,
                title=work.get("title"), year=work.get("year"),
                source_type="orcid",
            )

    # All remaining works (no DOI, or DOI beyond first 10)
    for i, work in enumerate(works):
        if entries[i] is not None:
            continue
        bibtex, cite_key = _bibtex_from_orcid_work(work, i)
        entries[i] = BibTeXEntry(
            identifier=work.get("doi") or f"orcid_{i}",
            bibtex=bibtex, cite_key=cite_key,
            title=work.get("title"), year=work.get("year"),
            source_type="orcid",
        )

    valid = [e for e in entries if e is not None]
    successful = sum(1 for e in valid if e.bibtex is not None)

    return FetchReferencesResponse(
        entries=valid,
        total=len(valid),
        successful=successful,
        processing_time=round(time.monotonic() - start, 3),
    )


@router.post("/detect", response_model=DetectReferencesResponse)
async def detect_references(request: DetectReferencesRequest):
    """Extract DOI and arXiv identifiers from raw pasted text."""
    detected: list[DetectIdentifierResult] = []
    seen: set[str] = set()

    # DOI in URL
    for m in re.finditer(r"https?://(?:dx\.)?doi\.org/(10\.\d{4,}/\S+)", request.text, re.I):
        doi = m.group(1).rstrip(".,;)")
        if doi not in seen:
            seen.add(doi)
            detected.append(DetectIdentifierResult(raw=m.group(0), normalized=doi, type="doi"))

    # Bare DOI
    for m in re.finditer(r"\b(10\.\d{4,}/\S+)", request.text):
        doi = m.group(1).rstrip(".,;)")
        if doi not in seen:
            seen.add(doi)
            detected.append(DetectIdentifierResult(raw=m.group(0), normalized=doi, type="doi"))

    # arXiv in URL (new-style and old-style)
    for m in re.finditer(
        r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,}(?:v\d+)?|[a-z][\w.-]*/\d{7}(?:v\d+)?)",
        request.text,
        re.I,
    ):
        arxiv_id = re.sub(r"v\d+$", "", m.group(1), flags=re.I)
        if arxiv_id not in seen:
            seen.add(arxiv_id)
            detected.append(DetectIdentifierResult(raw=m.group(0), normalized=arxiv_id, type="arxiv"))

    # Bare arXiv new-style
    for m in re.finditer(r"\b(\d{4}\.\d{4,})(?:v\d+)?\b", request.text):
        arxiv_id = m.group(1)
        if arxiv_id not in seen:
            seen.add(arxiv_id)
            detected.append(DetectIdentifierResult(raw=m.group(0), normalized=arxiv_id, type="arxiv"))

    # Bare arXiv old-style (e.g. solv-int/9901001v2)
    for m in re.finditer(r"\b([a-z][\w.-]*/\d{7})(?:v\d+)?\b", request.text, re.I):
        arxiv_id = m.group(1)
        if arxiv_id not in seen:
            seen.add(arxiv_id)
            detected.append(DetectIdentifierResult(raw=m.group(0), normalized=arxiv_id, type="arxiv"))

    return DetectReferencesResponse(detected=detected, count=len(detected))
