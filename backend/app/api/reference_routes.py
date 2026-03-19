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

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*[_fetch_one(ident) for ident in unique_ids]),
            timeout=30.0,
        )
        entries = list(results)
    except asyncio.TimeoutError:
        entries = [
            BibTeXEntry(
                identifier=ident,
                cite_key=f"ref_{i}",
                error="Request timed out",
            )
            for i, ident in enumerate(unique_ids)
        ]

    successful = sum(1 for e in entries if e.bibtex is not None)

    return FetchReferencesResponse(
        entries=entries,
        total=len(entries),
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

    # arXiv in URL
    for m in re.finditer(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,}(?:v\d+)?)", request.text, re.I):
        arxiv_id = m.group(1).split("v")[0]
        if arxiv_id not in seen:
            seen.add(arxiv_id)
            detected.append(DetectIdentifierResult(raw=m.group(0), normalized=arxiv_id, type="arxiv"))

    # Bare arXiv new-style
    for m in re.finditer(r"\b(\d{4}\.\d{4,})(?:v\d+)?\b", request.text):
        arxiv_id = m.group(1)
        if arxiv_id not in seen:
            seen.add(arxiv_id)
            detected.append(DetectIdentifierResult(raw=m.group(0), normalized=arxiv_id, type="arxiv"))

    return DetectReferencesResponse(detected=detected, count=len(detected))
