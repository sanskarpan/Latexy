"""LinkedIn COMPLIANT import service (Feature 1 Phase 3 — external sources to resume).

COMPLIANCE CONSTRAINT (read before touching this module):
    This module NEVER scrapes LinkedIn, NEVER calls any LinkedIn URL or API, and
    NEVER buys or fetches LinkedIn data. The ONLY supported input is a file the
    USER uploads themselves — either

      1. their official LinkedIn **data export** (a ZIP of CSV files the user
         downloads from LinkedIn → Settings → "Get a copy of your data"), or
      2. their own resume file (PDF/DOCX).

    Every function here operates purely on in-memory ``bytes`` the caller already
    holds. There is ZERO outbound network to LinkedIn (or anywhere else) in this
    module, by design and by construction. Do not add one.

The parsed output matches the shared ``ProjectEvidence`` dict shape used by the
GitHub importer (``github_projects_service.build_project_evidence``) so the same
frontend review UI renders LinkedIn-sourced evidence (``source="linkedin"``):

    {source, title, description, tech[], metrics{}, dates{last_active},
     url, suggested_bullets[], raw_excerpt}

All ZIP handling is defensive against malformed archives and zip bombs: entry
count, per-member uncompressed size, and total uncompressed bytes read are all
capped; non-CSV members are ignored.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from typing import Any, Dict, List, Optional

from ..core.logging import get_logger

logger = get_logger(__name__)

# ── Defensive caps (zip-bomb / DoS guards) ────────────────────────────────────

# Never inspect more than this many members in an uploaded ZIP.
_MAX_ZIP_ENTRIES = 200
# Skip any single member whose DECLARED uncompressed size exceeds this, and stop
# reading a member once this many bytes have actually been read.
_MAX_MEMBER_BYTES = 5 * 1024 * 1024  # 5 MB
# Hard ceiling on TOTAL uncompressed bytes read across all members. Guards against
# a zip bomb of many individually-small-but-collectively-huge members.
_MAX_TOTAL_UNCOMPRESSED = 20 * 1024 * 1024  # 20 MB
# Cap rows parsed per CSV so a giant CSV cannot exhaust memory/CPU.
_MAX_ROWS_PER_CSV = 1000
# Truncate any single field to this many characters.
_MAX_FIELD_CHARS = 20_000
# Cap the number of evidence records returned regardless of source.
_MAX_EVIDENCE = 100
# Cap suggested bullets per evidence record.
_MAX_BULLETS = 8

# CSV files we care about (matched case-insensitively against the member name).
_PROJECTS_CSV = "projects.csv"
_POSITIONS_CSV = "positions.csv"

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


# ── Small helpers ─────────────────────────────────────────────────────────────


def _clip(value: Any) -> str:
    """Coerce a CSV value to a stripped, length-capped string."""
    if value is None:
        return ""
    return str(value).strip()[:_MAX_FIELD_CHARS]


def _lc_row(row: Dict[str, Any]) -> Dict[str, str]:
    """Return a row keyed by lower-cased/stripped header → clipped string value."""
    out: Dict[str, str] = {}
    for key, val in row.items():
        if key is None:
            continue
        out[str(key).strip().lower()] = _clip(val)
    return out


def _get(row_lc: Dict[str, str], *names: str) -> str:
    """First non-empty value among the given (case-insensitive) column names."""
    for name in names:
        val = row_lc.get(name.lower())
        if val:
            return val
    return ""


def _split_bullets(description: str) -> List[str]:
    """Turn a free-text description into sentence-ish resume bullets.

    Splits on newlines first (LinkedIn descriptions are often newline-delimited),
    then on sentence boundaries. Falls back to the whole description as a single
    bullet. Never invents content — this is pure segmentation.
    """
    description = (description or "").strip()
    if not description:
        return []

    # Prefer explicit line breaks / bullet glyphs the user already authored.
    lines = [
        re.sub(r"^[\-•\*▪●\s]+", "", ln).strip()
        for ln in re.split(r"[\r\n]+", description)
    ]
    lines = [ln for ln in lines if ln]

    if len(lines) > 1:
        bullets = lines
    else:
        # Single blob — split into sentences.
        single = lines[0] if lines else description
        sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(single) if s.strip()]
        bullets = sentences or [single]

    return bullets[:_MAX_BULLETS]


def _build_evidence(
    *,
    title: str,
    description: str,
    suggested_bullets: List[str],
    tech: Optional[List[str]] = None,
    url: Optional[str] = None,
    last_active: Optional[str] = None,
    raw_excerpt: str = "",
) -> Dict[str, Any]:
    """Assemble a ``ProjectEvidence`` dict for a LinkedIn-sourced record.

    Mirrors ``github_projects_service.build_project_evidence`` exactly, with
    ``source="linkedin"``. LinkedIn has no stars/forks, so ``metrics`` is an
    empty dict (the same key the GitHub path fills).
    """
    return {
        "source": "linkedin",
        "title": (title or "").strip(),
        "description": (description or "").strip(),
        "tech": tech or [],
        "metrics": {},
        "dates": {"last_active": last_active or None},
        "url": (url or None),
        "suggested_bullets": suggested_bullets or [],
        "raw_excerpt": (raw_excerpt or "")[:2000],
    }


# ── LinkedIn data-export (ZIP of CSVs) parsing ────────────────────────────────


def _row_to_project_evidence(row_lc: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Map one ``Projects.csv`` row → ProjectEvidence (None if unusable)."""
    title = _get(row_lc, "title", "name", "project name")
    description = _get(row_lc, "description", "summary")
    if not title and not description:
        return None
    url = _get(row_lc, "url", "link")
    started = _get(row_lc, "started on", "start date", "started")
    finished = _get(row_lc, "finished on", "end date", "finished")
    return _build_evidence(
        title=title or "Project",
        description=description,
        suggested_bullets=_split_bullets(description) if description else [],
        tech=[],
        url=url,
        last_active=finished or started,
        raw_excerpt=description,
    )


def _row_to_position_evidence(row_lc: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Map one ``Positions.csv`` row → ProjectEvidence (None if unusable)."""
    role = _get(row_lc, "title", "position", "role")
    company = _get(row_lc, "company name", "company", "organization")
    description = _get(row_lc, "description", "summary")
    if not role and not company and not description:
        return None
    if role and company:
        title = f"{role} at {company}"
    else:
        title = role or company or "Experience"
    started = _get(row_lc, "started on", "start date", "started")
    finished = _get(row_lc, "finished on", "end date", "finished")
    return _build_evidence(
        title=title,
        description=description,
        suggested_bullets=_split_bullets(description) if description else [],
        tech=[],
        url=None,
        last_active=finished or started,
        raw_excerpt=description,
    )


def _read_member_text(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> Optional[str]:
    """Safely read+decode a single ZIP member, honoring the size caps.

    Returns None if the member is too large or cannot be decoded. The read is
    bounded to ``_MAX_MEMBER_BYTES`` regardless of the declared size (a lying
    header cannot make us read more).
    """
    # Refuse members whose declared uncompressed size already blows the cap.
    if info.file_size and info.file_size > _MAX_MEMBER_BYTES:
        logger.warning(
            "linkedin_import: skipping oversized member %s (%d bytes declared)",
            info.filename,
            info.file_size,
        )
        return None
    try:
        with zf.open(info, "r") as fh:
            raw = fh.read(_MAX_MEMBER_BYTES + 1)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        logger.warning("linkedin_import: failed reading %s: %s", info.filename, exc)
        return None
    if len(raw) > _MAX_MEMBER_BYTES:
        logger.warning("linkedin_import: member %s exceeded read cap", info.filename)
        return None
    # utf-8-sig strips a BOM if present; replace undecodable bytes rather than fail.
    return raw.decode("utf-8-sig", errors="replace")


def _parse_csv_rows(text: str) -> List[Dict[str, str]]:
    """Parse CSV text into a list of lower-cased-key rows, capped in count."""
    rows: List[Dict[str, str]] = []
    reader = csv.DictReader(io.StringIO(text))
    for i, raw_row in enumerate(reader):
        if i >= _MAX_ROWS_PER_CSV:
            logger.warning("linkedin_import: row cap reached, truncating CSV")
            break
        rows.append(_lc_row(raw_row))
    return rows


def parse_linkedin_export(zip_bytes: bytes) -> List[Dict[str, Any]]:
    """Parse a user-uploaded LinkedIn data-export ZIP into ProjectEvidence dicts.

    COMPLIANCE: ``zip_bytes`` must be the user's OWN LinkedIn export (downloaded
    by them from LinkedIn's data-export tool). Nothing here contacts LinkedIn.

    Finds ``Projects.csv`` and ``Positions.csv`` case-insensitively anywhere in
    the archive, parses them defensively, and maps each row to a ProjectEvidence
    record (``source="linkedin"``). Missing files and malformed rows are
    tolerated — the function returns whatever it could extract (possibly empty),
    and only raises ``ValueError`` when the bytes are not a valid ZIP at all.
    """
    if not zip_bytes:
        raise ValueError("Empty upload: no LinkedIn export data provided.")

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("Uploaded file is not a valid ZIP archive.") from exc

    evidence: List[Dict[str, Any]] = []
    total_read = 0

    try:
        infos = zf.infolist()[:_MAX_ZIP_ENTRIES]
        for info in infos:
            if len(evidence) >= _MAX_EVIDENCE:
                break
            if info.is_dir():
                continue
            base = info.filename.rsplit("/", 1)[-1].lower()
            if base not in (_PROJECTS_CSV, _POSITIONS_CSV):
                continue  # ignore non-CSV / irrelevant members
            if total_read >= _MAX_TOTAL_UNCOMPRESSED:
                logger.warning("linkedin_import: total uncompressed cap reached")
                break

            text = _read_member_text(zf, info)
            if text is None:
                continue
            total_read += len(text)

            try:
                rows = _parse_csv_rows(text)
            except (csv.Error, ValueError) as exc:
                logger.warning("linkedin_import: CSV parse error in %s: %s", base, exc)
                continue

            mapper = (
                _row_to_project_evidence
                if base == _PROJECTS_CSV
                else _row_to_position_evidence
            )
            for row in rows:
                if len(evidence) >= _MAX_EVIDENCE:
                    break
                try:
                    record = mapper(row)
                except Exception as exc:  # one bad row never fails the whole import
                    logger.warning("linkedin_import: bad row skipped: %s", exc)
                    continue
                if record:
                    evidence.append(record)
    finally:
        zf.close()

    return evidence


# ── Resume-file (PDF/DOCX) parsing ────────────────────────────────────────────


def _parsed_resume_to_evidence(parsed: Any) -> List[Dict[str, Any]]:
    """Map a ``ParsedResume`` (experience + projects) → ProjectEvidence dicts."""
    evidence: List[Dict[str, Any]] = []

    for proj in getattr(parsed, "projects", None) or []:
        if len(evidence) >= _MAX_EVIDENCE:
            break
        description = (getattr(proj, "description", "") or "").strip()
        name = (getattr(proj, "name", "") or "").strip()
        if not name and not description:
            continue
        end = getattr(proj, "end_date", None)
        start = getattr(proj, "start_date", None)
        evidence.append(
            _build_evidence(
                title=name or "Project",
                description=description,
                suggested_bullets=_split_bullets(description) if description else [],
                tech=list(getattr(proj, "technologies", None) or []),
                url=getattr(proj, "url", None),
                last_active=end or start,
                raw_excerpt=description,
            )
        )

    for exp in getattr(parsed, "experience", None) or []:
        if len(evidence) >= _MAX_EVIDENCE:
            break
        role = (getattr(exp, "title", "") or "").strip()
        company = (getattr(exp, "company", "") or "").strip()
        desc_lines = [
            str(d).strip() for d in (getattr(exp, "description", None) or []) if str(d).strip()
        ]
        if not role and not company and not desc_lines:
            continue
        if role and company:
            title = f"{role} at {company}"
        else:
            title = role or company or "Experience"
        description = " ".join(desc_lines)
        end = getattr(exp, "end_date", None)
        start = getattr(exp, "start_date", None)
        evidence.append(
            _build_evidence(
                title=title,
                description=description,
                suggested_bullets=desc_lines[:_MAX_BULLETS],
                tech=list(getattr(exp, "technologies", None) or []),
                url=None,
                last_active=end or start,
                raw_excerpt=description,
            )
        )

    return evidence[:_MAX_EVIDENCE]


async def parse_resume_file(file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    """Parse a user-uploaded resume file (PDF/DOCX/...) into ProjectEvidence dicts.

    COMPLIANCE: this operates ONLY on the bytes the user uploaded — their own
    resume. No network, no LinkedIn. Uses the existing ``ParserFactory`` to turn
    the file into a ``ParsedResume``, then best-effort maps its experience and
    project sections to ProjectEvidence records (``source="linkedin"`` because
    the entry point is the LinkedIn-import flow).

    Raises ``ValueError`` if the file format is unsupported or unparseable.
    """
    if not file_bytes:
        raise ValueError("Empty upload: no resume file provided.")

    # Local import keeps module import cheap and avoids a heavy parser import at
    # startup for callers that only use the ZIP path.
    from ..parsers.parser_factory import parser_factory  # noqa: PLC0415

    parser = parser_factory.get_parser_for_file(filename, content=file_bytes)
    if parser is None:
        raise ValueError(f"Unsupported resume file format: {filename!r}")

    try:
        parsed = await parser.parse(file_bytes, filename)
    except Exception as exc:  # normalize parser failures to a 4xx-friendly error
        logger.warning("linkedin_import: resume parse failed for %s: %s", filename, exc)
        raise ValueError(f"Could not parse resume file: {exc}") from exc

    return _parsed_resume_to_evidence(parsed)
