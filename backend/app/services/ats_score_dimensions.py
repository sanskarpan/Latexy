"""Bounded ATS score dimensions shared by writers and admin reports.

Only known industry profile keys and persona keys are persisted or exposed.
Free-text values are discarded so operator-entered or user-entered text can
never become an analytics dimension.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from .industry_ats_profiles import INDUSTRY_PROFILES
from .optimization_personas import VALID_PERSONA_KEYS

UNKNOWN = "unknown"

_LEGACY_INDUSTRY_KEYS = {
    "technology": "tech_saas",
    "finance": "finance_banking",
    "healthcare": "healthcare",
    "consulting": "consulting",
}


def normalize_score(value: Any) -> Optional[float]:
    """Return a finite 0..100 score, or ``None`` for unusable values."""
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score) or score < 0 or score > 100:
        return None
    return round(score, 2)


def normalize_industry(value: Any) -> Optional[str]:
    """Map a supplied/stored industry to a known profile key."""
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    normalized = _LEGACY_INDUSTRY_KEYS.get(normalized, normalized)
    return normalized if normalized in INDUSTRY_PROFILES else None


def normalize_profile(value: Any) -> Optional[str]:
    """Map a supplied/stored persona to a known profile key."""
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized if normalized in VALID_PERSONA_KEYS else None
