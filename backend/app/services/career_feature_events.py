"""Privacy-safe first-party events for career-adjacent features.

Cover letters, interview preparation and career-path analysis already persist
their generated output in dedicated tables.  This module records only the fact
that a run started, in the existing ``usage_analytics`` JSONB column.  Event
metadata is deliberately limited to the registry feature key: generated
cover-letter text, interview questions, career gap analysis, job descriptions
and résumé source are never copied into analytics.

No schema migration is involved.  The helper commits on its own so analytics can
never turn a successful generation into a failed request.
"""

from __future__ import annotations

import inspect
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.models import UsageAnalytics

logger = get_logger(__name__)

COVER_LETTER_GENERATED_ACTION: Final = "cover_letter_generated"
INTERVIEW_PREP_GENERATED_ACTION: Final = "interview_prep_generated"
CAREER_ANALYSIS_GENERATED_ACTION: Final = "career_analysis_generated"

FEATURE_COVER_LETTERS: Final = "cover_letters"
FEATURE_INTERVIEW_PREP: Final = "interview_prep"
FEATURE_CAREER_PATHS: Final = "career_paths"

CANONICAL_EVENTS: Final[dict[str, str]] = {
    FEATURE_COVER_LETTERS: COVER_LETTER_GENERATED_ACTION,
    FEATURE_INTERVIEW_PREP: INTERVIEW_PREP_GENERATED_ACTION,
    FEATURE_CAREER_PATHS: CAREER_ANALYSIS_GENERATED_ACTION,
}

# Historical client labels and completion aliases accepted by the admin report.
# Only these explicit values are ever matched; arbitrary metadata stays out.
FEATURE_EVENT_ACTIONS: Final[dict[str, frozenset[str]]] = {
    FEATURE_COVER_LETTERS: frozenset(
        {
            COVER_LETTER_GENERATED_ACTION,
            "cover_letter_generation",
            "cover_letter_completed",
        }
    ),
    FEATURE_INTERVIEW_PREP: frozenset(
        {
            INTERVIEW_PREP_GENERATED_ACTION,
            "interview_prep_generation",
            "interview_prep_completed",
        }
    ),
    FEATURE_CAREER_PATHS: frozenset(
        {
            CAREER_ANALYSIS_GENERATED_ACTION,
            "career_analysis_completed",
            "career_path_generated",
            "career_path_completed",
        }
    ),
}

# The browser labels cover-letter completion as a generic ``feature_usage``
# event.  These are the only metadata values the report treats as a run.
FEATURE_METADATA_ALIASES: Final[dict[str, frozenset[str]]] = {
    FEATURE_COVER_LETTERS: frozenset(
        {"cover_letters", "cover_letter", "cover_letter_generation", COVER_LETTER_GENERATED_ACTION}
    ),
    FEATURE_INTERVIEW_PREP: frozenset(
        {
            "interview_prep",
            "interview_preparation",
            "interview_prep_generation",
            INTERVIEW_PREP_GENERATED_ACTION,
        }
    ),
    FEATURE_CAREER_PATHS: frozenset(
        {
            "career_paths",
            "career_path",
            "career_analysis",
            "career_analysis_generated",
            "career_analysis_completed",
        }
    ),
}

OPTIMIZATION_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "optimize",
        "optimization",
        "optimization_started",
        "optimization_completed",
        "optimization_generated",
        "optimization_tracked",
        "resume_optimized",
    }
)
OPTIMIZATION_METADATA_ALIASES: Final[frozenset[str]] = frozenset(
    {
        "llm_optimize",
        "ai_optimization",
        "optimize",
        "optimization",
        "resume_optimization",
    }
)


def event_metadata(feature: str) -> dict[str, Any]:
    """Return the complete allowlisted metadata payload for one feature event."""
    if feature not in CANONICAL_EVENTS:
        raise ValueError("unknown career feature")
    return {"feature": feature}


async def record_generation_event(
    db: AsyncSession,
    *,
    feature: str,
    user_id: str | None,
) -> bool:
    """Append one no-content generation event and commit it.

    Returns ``True`` when the event was stored.  Analytics is best-effort: a
    database error is logged and rolled back without surfacing to the caller.
    ``ip_address`` and ``user_agent`` are intentionally not stored for this
    event family.
    """
    if user_id is None:
        return False
    try:
        record = UsageAnalytics(
            user_id=user_id,
            action=CANONICAL_EVENTS[feature],
            resource_type="feature",
            event_metadata=event_metadata(feature),
            ip_address=None,
            user_agent=None,
        )
        added = db.add(record)
        if inspect.isawaitable(added):
            await added
        await db.commit()
        return True
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
        logger.warning(
            "Career feature analytics event failed for %s", feature, exc_info=True
        )
        return False
