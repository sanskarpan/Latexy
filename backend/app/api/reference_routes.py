"""
Reference routes — fetch BibTeX from DOI (Crossref) and arXiv identifiers.
"""

import asyncio
import re
import time
import unicodedata
from difflib import SequenceMatcher
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..core.logging import get_logger
from ..middleware.entitlements import require_feature_optional
from ..middleware.rate_limiting import client_ip_id
from ..services.external_budget_service import enforce_external_budget
from ..services.publications_service import latex_escape
from ..services.reference_service import reference_service

logger = get_logger(__name__)

router = APIRouter(prefix="/references", tags=["references"])

# Per-process backpressure for the local httpx pool. The Redis budget below is
# the cross-container authority; this semaphore only prevents one process from
# opening too many outbound sockets at once.
_OUTBOUND_FETCH_SEMAPHORE = asyncio.Semaphore(20)

_REFERENCE_CLIENT_UNITS_PER_MINUTE = 60
_REFERENCE_GLOBAL_UNITS_PER_MINUTE = 600
_REFERENCE_BUDGET_WINDOW = 60


async def _cancel_and_wait(tasks: set[asyncio.Task]) -> None:
    """Cancel timed-out upstream calls and await their client cleanup."""
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _enforce_reference_budget(request: Request, cost: int) -> None:
    if cost < 1:
        return
    await enforce_external_budget(
        "references",
        # This endpoint is intentionally public, so an arbitrary unverified
        # Bearer header must not mint a fresh bucket. Use the trusted peer/proxy
        # identity until authentication has produced a verified user id.
        client_id=client_ip_id(request),
        cost=cost,
        client_limit=_REFERENCE_CLIENT_UNITS_PER_MINUTE,
        global_limit=_REFERENCE_GLOBAL_UNITS_PER_MINUTE,
        window_seconds=_REFERENCE_BUDGET_WINDOW,
    )


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


class VerifyCitationsRequest(BaseModel):
    bibtex: str = Field(..., min_length=1, max_length=200_000)


class CitationVerification(BaseModel):
    cite_key: str
    status: Literal["verified", "mismatch", "not_found", "error"]
    source: Literal["crossref", "arxiv"]
    identifier: Optional[str] = None
    matched_title: Optional[str] = None
    matched_authors: Optional[str] = None
    matched_year: Optional[int] = None
    title_similarity: Optional[float] = None
    issues: list[str] = Field(default_factory=list)


class VerifyCitationsResponse(BaseModel):
    results: list[CitationVerification]
    total: int
    verified: int
    mismatched: int
    processing_time: float


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
        async with _OUTBOUND_FETCH_SEMAPHORE:
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
            error=_safe_reference_error(exc),
        )
    except Exception as exc:
        logger.error("Unexpected error fetching reference (%s)", type(exc).__name__)
        return BibTeXEntry(
            identifier=identifier,
            cite_key=f"ref_{normalized[:16].replace('/', '_')}",
            source_type=id_type,
            error=f"Unexpected error: {type(exc).__name__}",
        )


def _plain_metadata(value: Optional[str]) -> str:
    if not value:
        return ""
    value = re.sub(r"\\[A-Za-z]+\*?", " ", value)
    value = value.replace("{", "").replace("}", "")
    value = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _safe_reference_error(exc: ValueError) -> str:
    """Keep provider/network exception details out of reference responses."""
    message = str(exc).casefold()
    if "not found" in message or "no scholarly match" in message:
        return "Reference not found."
    return "Reference provider request failed. Please try again."


def _author_surnames(value: Optional[str]) -> set[str]:
    surnames: set[str] = set()
    for author in re.split(r"\s+and\s+", value or "", flags=re.I):
        plain = _plain_metadata(author)
        if not plain:
            continue
        if "," in author:
            surname = _plain_metadata(author.split(",", 1)[0])
        else:
            surname = plain.split()[-1]
        if surname:
            surnames.add(surname)
    return surnames


def _compare_citation(
    entry: dict, matched: dict, source: Literal["crossref", "arxiv"]
) -> CitationVerification:
    issues: list[str] = []
    supplied_title = _plain_metadata(entry.get("title"))
    matched_title = _plain_metadata(matched.get("title"))
    similarity = None
    if supplied_title and matched_title:
        similarity = round(SequenceMatcher(None, supplied_title, matched_title).ratio(), 3)
        if similarity < 0.82:
            issues.append("Title does not closely match the scholarly record")

    supplied_year = entry.get("year")
    try:
        if supplied_year and not re.fullmatch(r"\d{4}", str(supplied_year).strip()):
            raise ValueError
        supplied_year_int = int(supplied_year) if supplied_year else None
    except (TypeError, ValueError):
        supplied_year_int = None
        issues.append("Year is not a valid four-digit number")
    matched_year = matched.get("year")
    if supplied_year_int and matched_year and supplied_year_int != matched_year:
        issues.append(f"Year differs: BibTeX has {supplied_year_int}, record has {matched_year}")

    supplied_authors = _author_surnames(entry.get("authors"))
    matched_authors = _author_surnames(matched.get("authors"))
    if supplied_authors and matched_authors and not supplied_authors.intersection(matched_authors):
        issues.append("Authors do not overlap with the scholarly record")

    return CitationVerification(
        cite_key=entry["cite_key"],
        status="mismatch" if issues else "verified",
        source=source,
        identifier=matched.get("identifier"),
        matched_title=matched.get("title"),
        matched_authors=matched.get("authors"),
        matched_year=matched_year,
        title_similarity=similarity,
        issues=issues,
    )


async def _verify_one_citation(entry: dict) -> CitationVerification:
    source: Literal["crossref", "arxiv"] = "crossref"
    identifier = (entry.get("doi") or "").strip()
    try:
        normalized, identifier_type = reference_service.normalize_identifier(identifier)
        if identifier_type == "doi":
            result = await reference_service.fetch_doi(normalized)
            matched = {**result, "identifier": normalized}
        else:
            eprint = (entry.get("eprint") or "").strip()
            normalized_eprint, eprint_type = reference_service.normalize_identifier(eprint)
            if eprint_type == "arxiv":
                source = "arxiv"
                result = await reference_service.fetch_arxiv(normalized_eprint)
                matched = {**result, "identifier": normalized_eprint}
            elif entry.get("title"):
                matched = await reference_service.search_crossref(
                    entry["title"], entry.get("authors")
                )
            else:
                return CitationVerification(
                    cite_key=entry["cite_key"],
                    status="not_found",
                    source=source,
                    issues=["A DOI, arXiv ID, or title is required to find this work"],
                )
        return _compare_citation(entry, matched, source)
    except ValueError as exc:
        message = _safe_reference_error(exc)
        provider_message = str(exc).casefold()
        not_found = "not found" in provider_message or "no scholarly match" in provider_message
        return CitationVerification(
            cite_key=entry["cite_key"],
            status="not_found" if not_found else "error",
            source=source,
            identifier=identifier or None,
        issues=[message],
        )

# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/fetch",
    response_model=FetchReferencesResponse,
    dependencies=[Depends(require_feature_optional("references"))],
)
async def fetch_references(
    request: FetchReferencesRequest,
    http_request: Request,
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

    # Weight by actual upstream amplification, not by HTTP request count.
    fetch_units = sum(
        1
        for ident in unique_ids
        if reference_service.normalize_identifier(ident)[1] is not None
    )
    await _enforce_reference_budget(http_request, fetch_units)

    tasks = [asyncio.create_task(_fetch_one(ident)) for ident in unique_ids]
    done, pending = await asyncio.wait(tasks, timeout=30.0)

    # Cancel tasks that did not finish in time
    await _cancel_and_wait(pending)

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


@router.post(
    "/verify",
    response_model=VerifyCitationsResponse,
    dependencies=[Depends(require_feature_optional("references"))],
)
async def verify_citations(
    request: VerifyCitationsRequest,
    http_request: Request,
):
    """Check BibTeX works and metadata against Crossref or arXiv."""
    start = time.monotonic()
    try:
        entries = reference_service.parse_bibtex_entries(request.bibtex, limit=20)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="BibTeX input could not be parsed.") from exc

    await _enforce_reference_budget(http_request, len(entries))
    tasks = [asyncio.create_task(_verify_one_citation(entry)) for entry in entries]
    done, pending = await asyncio.wait(tasks, timeout=30.0)
    await _cancel_and_wait(pending)
    task_index = {task: index for index, task in enumerate(tasks)}
    results: list[Optional[CitationVerification]] = [None] * len(tasks)
    for task in done:
        index = task_index[task]
        exception = task.exception()
        if exception is None:
            results[index] = task.result()
        else:
            logger.error(
                "Unexpected citation verification failure for %s: %s",
                entries[index]["cite_key"],
                exception,
            )
            results[index] = CitationVerification(
                cite_key=entries[index]["cite_key"],
                status="error",
                source="crossref",
                issues=["Citation verification failed unexpectedly"],
            )
    for task in pending:
        index = task_index[task]
        results[index] = CitationVerification(
            cite_key=entries[index]["cite_key"],
            status="error",
            source="crossref",
            issues=["Citation verification timed out"],
        )

    complete_results = [result for result in results if result is not None]
    return VerifyCitationsResponse(
        results=complete_results,
        total=len(complete_results),
        verified=sum(result.status == "verified" for result in complete_results),
        mismatched=sum(result.status == "mismatch" for result in complete_results),
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

    # Cite key: first word of title + year + idx suffix to avoid collisions
    first_word = re.sub(r"[^a-zA-Z]", "", title.split()[0]).lower() if title else "work"
    cite_key = f"{first_word}{year or 'nd'}_{idx + 1}"

    # Escape TeX-special characters in third-party (ORCID) metadata so the
    # generated BibTeX cannot break compilation or inject LaTeX commands.
    safe_title = latex_escape(title)
    safe_journal = latex_escape(journal)

    lines = [f"@{bib_type}{{{cite_key},"]
    lines.append(f"  title = {{{{{safe_title}}}}},")
    if year:
        lines.append(f"  year = {{{year}}},")
    if journal:
        field = "journal" if bib_type == "article" else "booktitle"
        lines.append(f"  {field} = {{{{{safe_journal}}}}},")
    if url:
        lines.append(f"  url = {{{url}}},")
    lines.append("  note = {Via ORCID},")
    lines.append("}")
    return "\n".join(lines), cite_key


# ── ORCID endpoint ─────────────────────────────────────────────────────────────


class FetchOrcidRequest(BaseModel):
    orcid_id: str = Field(..., description="Bare ORCID ID (XXXX-XXXX-XXXX-XXXX) or ORCID URL")
    max_results: int = Field(default=20, ge=1, le=50)


@router.post(
    "/fetch-orcid",
    response_model=FetchReferencesResponse,
    dependencies=[Depends(require_feature_optional("references"))],
)
async def fetch_orcid_publications(
    request: FetchOrcidRequest,
    http_request: Request,
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

    # Reserve the ORCID profile request first; DOI enrichment is charged below
    # only after the returned work list tells us how many Crossref calls exist.
    await _enforce_reference_budget(http_request, 1)

    try:
        works = await reference_service.fetch_orcid_works(normalized, request.max_results)
    except ValueError as exc:
        from fastapi import HTTPException
        status = 404 if "not found" in str(exc).casefold() else 503
        detail = "ORCID profile not found" if status == 404 else "ORCID service temporarily unavailable"
        raise HTTPException(status_code=status, detail=detail) from exc

    if not works:
        return FetchReferencesResponse(entries=[], total=0, successful=0, processing_time=0.0)

    # Separate DOI-bearing works (fetch Crossref BibTeX, up to 10) from others
    doi_indices = [i for i, w in enumerate(works) if w.get("doi")][:10]
    entries: list[Optional[BibTeXEntry]] = [None] * len(works)

    # Concurrent Crossref fetches for works with DOI
    if doi_indices:
        await _enforce_reference_budget(http_request, len(doi_indices))
        doi_tasks = [asyncio.create_task(_fetch_one(works[i]["doi"])) for i in doi_indices]
        done, pending = await asyncio.wait(doi_tasks, timeout=25.0)
        await _cancel_and_wait(pending)

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

    # DOI in URL — quantifiers are upper-bounded to avoid pathological backtracking.
    for m in re.finditer(r"https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/\S{1,256})", request.text, re.I):
        doi = m.group(1).rstrip(".,;)")
        if doi not in seen:
            seen.add(doi)
            detected.append(DetectIdentifierResult(raw=m.group(0), normalized=doi, type="doi"))

    # Bare DOI
    for m in re.finditer(r"\b(10\.\d{4,9}/\S{1,256})", request.text):
        doi = m.group(1).rstrip(".,;)")
        if doi not in seen:
            seen.add(doi)
            detected.append(DetectIdentifierResult(raw=m.group(0), normalized=doi, type="doi"))

    # arXiv in URL (new-style and old-style)
    for m in re.finditer(
        r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,10}(?:v\d{1,4})?|[a-z][\w.-]{0,64}/\d{7}(?:v\d{1,4})?)",
        request.text,
        re.I,
    ):
        arxiv_id = re.sub(r"v\d+$", "", m.group(1), flags=re.I)
        if arxiv_id not in seen:
            seen.add(arxiv_id)
            detected.append(DetectIdentifierResult(raw=m.group(0), normalized=arxiv_id, type="arxiv"))

    # Bare arXiv new-style
    for m in re.finditer(r"\b(\d{4}\.\d{4,10})(?:v\d{1,4})?\b", request.text):
        arxiv_id = m.group(1)
        if arxiv_id not in seen:
            seen.add(arxiv_id)
            detected.append(DetectIdentifierResult(raw=m.group(0), normalized=arxiv_id, type="arxiv"))

    # Bare arXiv old-style (e.g. solv-int/9901001v2)
    for m in re.finditer(r"\b([a-z][\w.-]{0,64}/\d{7})(?:v\d{1,4})?\b", request.text, re.I):
        arxiv_id = m.group(1)
        if arxiv_id not in seen:
            seen.add(arxiv_id)
            detected.append(DetectIdentifierResult(raw=m.group(0), normalized=arxiv_id, type="arxiv"))

    return DetectReferencesResponse(detected=detected, count=len(detected))
