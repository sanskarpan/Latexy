"""
Feature 88 — Compile Error History.

Aggregates failed Compilation records for a user, groups them by LaTeX error
type, and determines whether each recurring error has since been resolved.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Compilation, Resume

# ── Patterns for classifying error_message values ──────────────────────────

# pdflatex "! ..." lines — already stored verbatim after the worker enhancement
_BANG_RE = re.compile(r"^!\s+(.+)$", re.MULTILINE)

# Fallback human-readable category for non-"!" messages
_CATEGORY_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"timed? ?out", re.I), "Compilation Timeout"),
    (re.compile(r"exited with code", re.I), "LaTeX Compile Error"),
    (re.compile(r"internal", re.I), "Internal Error"),
]


def _extract_error_type(error_message: Optional[str]) -> str:
    """
    Return a short human-readable error type string from an error_message.

    For messages that begin with "! " (stored since Feature 88 worker change),
    extract the text after "!". For older/generic messages fall back to
    category matching.
    """
    if not error_message:
        return "Unknown Error"

    m = _BANG_RE.search(error_message)
    if m:
        # Normalise: strip trailing dot + period, collapse whitespace
        return re.sub(r"\s+", " ", m.group(1).rstrip(".")).strip()

    for pattern, label in _CATEGORY_MAP:
        if pattern.search(error_message):
            return label

    return error_message[:80].strip()


# ── Public dataclass ────────────────────────────────────────────────────────

@dataclass
class ErrorHistorySummary:
    error_type: str
    count: int
    last_seen: datetime
    last_resume_id: Optional[str]
    last_resume_title: Optional[str]
    example_line: str       # full error_message of the most-recent occurrence
    resolved: bool          # True if the offending resume compiled successfully afterwards


# ── Service ─────────────────────────────────────────────────────────────────

class ErrorHistoryService:

    async def get_error_history(
        self,
        user_id: str,
        db: AsyncSession,
        limit: int = 50,
    ) -> list[ErrorHistorySummary]:
        """
        Return up to *limit* grouped error summaries for *user_id*, sorted by
        count DESC then last_seen DESC.
        """
        # 1. All failed compilations for this user (most-recent first)
        failed_result = await db.execute(
            select(Compilation)
            .where(
                Compilation.user_id == user_id,
                Compilation.status == "failed",
                Compilation.error_message.isnot(None),
            )
            .order_by(Compilation.created_at.desc())
        )
        failed: list[Compilation] = list(failed_result.scalars().all())

        if not failed:
            return []

        # 2. All *successful* compilations for this user (keyed by resume_id)
        #    We only need to know if any success happened AFTER a failure for the
        #    same resume — so load them all and bucket by resume_id.
        success_result = await db.execute(
            select(Compilation.resume_id, Compilation.created_at)
            .where(
                Compilation.user_id == user_id,
                Compilation.status == "completed",
                Compilation.resume_id.isnot(None),
            )
        )
        # Map resume_id → max(created_at) of successful compiles
        latest_success: dict[str, datetime] = {}
        for row in success_result.all():
            rid, ts = row
            if rid and (rid not in latest_success or ts > latest_success[rid]):
                latest_success[rid] = ts

        # 3. Resolve resume titles in one bulk query
        resume_ids = {c.resume_id for c in failed if c.resume_id}
        title_map: dict[str, str] = {}
        if resume_ids:
            res_result = await db.execute(
                select(Resume.id, Resume.title).where(Resume.id.in_(resume_ids))
            )
            title_map = {r.id: r.title for r in res_result.all()}

        # 4. Group by error_type
        groups: dict[str, list[Compilation]] = {}
        for comp in failed:
            etype = _extract_error_type(comp.error_message)
            groups.setdefault(etype, []).append(comp)

        # 5. Build summaries
        summaries: list[ErrorHistorySummary] = []
        for error_type, compilations in groups.items():
            # compilations already sorted by created_at DESC (latest first)
            latest = compilations[0]
            rid = latest.resume_id
            resolved = False
            if rid and rid in latest_success:
                resolved = latest_success[rid] > latest.created_at

            summaries.append(ErrorHistorySummary(
                error_type=error_type,
                count=len(compilations),
                last_seen=latest.created_at,
                last_resume_id=rid,
                last_resume_title=title_map.get(rid) if rid else None,
                example_line=latest.error_message or "",
                resolved=resolved,
            ))

        # 6. Sort: count DESC, last_seen DESC
        summaries.sort(key=lambda s: (-s.count, -s.last_seen.timestamp()))
        return summaries[:limit]


error_history_service = ErrorHistoryService()
