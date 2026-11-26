"""Bounded document-complexity helpers for compile analytics.

Only counts leave this module. LaTeX source is inspected at admission solely
to count section commands; the source itself is never persisted or returned.
Page counts come from the compiler summary line and are normalized before they
reach the database.
"""

from __future__ import annotations

import math
import re
from typing import Any, Optional

MIN_PAGE_COUNT = 1
MAX_PAGE_COUNT = 10_000
MIN_SECTION_COUNT = 0
MAX_SECTION_COUNT = 500

# Lower bound inclusive. ``upper`` is inclusive for the final bucket (``None``
# means no upper bound within the persisted cap).
PAGE_BUCKETS: tuple[tuple[int, Optional[int], str], ...] = (
    (1, 1, "1"),
    (2, 2, "2"),
    (3, 4, "3-4"),
    (5, 6, "5-6"),
    (7, 10, "7-10"),
    (11, 20, "11-20"),
    (21, 50, "21-50"),
    (51, 100, "51-100"),
    (101, 250, "101-250"),
    (251, None, "251+"),
)

SECTION_BUCKETS: tuple[tuple[int, Optional[int], str], ...] = (
    (0, 0, "0"),
    (1, 2, "1-2"),
    (3, 5, "3-5"),
    (6, 10, "6-10"),
    (11, 20, "11-20"),
    (21, 50, "21-50"),
    (51, None, "51+"),
)

# Lower bound inclusive, upper bound exclusive except the final open bucket.
LATENCY_BUCKETS: tuple[tuple[float, Optional[float], str], ...] = (
    (0.0, 1.0, "<1s"),
    (1.0, 2.0, "1-2s"),
    (2.0, 5.0, "2-5s"),
    (5.0, 10.0, "5-10s"),
    (10.0, 30.0, "10-30s"),
    (30.0, 60.0, "30-60s"),
    (60.0, None, "60s+"),
)

OVERFLOW_PAGE_THRESHOLDS: tuple[int, ...] = (2, 5, 10)

# A comment starts at an unescaped percent sign. ``\%`` is a literal percent
# and must not hide the remainder of the line from the section count.
_SECTION_RE = re.compile(r"\\section\*?\s*\{")


def _strip_latex_comments(text: str) -> str:
    """Remove unescaped LaTeX comments in one linear pass.

    A regex with a variable-length lookbehind is unnecessary here and can be
    superlinear on hostile input; scanning each line keeps the admission path
    bounded regardless of source size.
    """

    cleaned: list[str] = []
    for line in text.splitlines():
        cut = len(line)
        index = 0
        while True:
            index = line.find("%", index)
            if index < 0:
                break
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                cut = index
                break
            index += 1
        cleaned.append(line[:cut])
    return "\n".join(cleaned)


def _integral(value: Any) -> Optional[int]:
    if value is None or isinstance(value, (bool, str)):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or not numeric.is_integer():
        return None
    return int(numeric)


def normalize_page_count(value: Any) -> Optional[int]:
    """Return a persisted page count, or ``None`` when outside the bound."""
    count = _integral(value)
    if count is None or count < MIN_PAGE_COUNT or count > MAX_PAGE_COUNT:
        return None
    return count


def normalize_section_count(value: Any) -> Optional[int]:
    """Return a persisted section count, or ``None`` when outside the bound."""
    count = _integral(value)
    if count is None or count < MIN_SECTION_COUNT or count > MAX_SECTION_COUNT:
        return None
    return count


def count_sections(latex_content: Optional[str]) -> Optional[int]:
    """Count section commands in submitted source without persisting content.

    Commented-out sections are ignored. The result is capped at
    :data:`MAX_SECTION_COUNT` so a hostile or malformed input cannot create an
    unbounded persisted value. ``None`` means the source was absent, so "not
    derivable" is distinct from a genuine zero-section document.
    """
    if not isinstance(latex_content, str) or not latex_content.strip():
        return None
    without_comments = _strip_latex_comments(latex_content)
    count = len(_SECTION_RE.findall(without_comments))
    return min(count, MAX_SECTION_COUNT)


def page_bucket(value: Any) -> Optional[str]:
    count = normalize_page_count(value)
    if count is None:
        return None
    for lower, upper, label in PAGE_BUCKETS:
        if count < lower:
            continue
        if upper is None or count <= upper:
            return label
    return None


def section_bucket(value: Any) -> Optional[str]:
    count = normalize_section_count(value)
    if count is None:
        return None
    for lower, upper, label in SECTION_BUCKETS:
        if count < lower:
            continue
        if upper is None or count <= upper:
            return label
    return None


def latency_bucket(value: Any) -> Optional[str]:
    if value is None or isinstance(value, (bool, str)):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    for lower, upper, label in LATENCY_BUCKETS:
        if seconds < lower:
            continue
        if upper is None or seconds < upper:
            return label
    return None


def finite_seconds(value: Any) -> Optional[float]:
    """Return a finite non-negative duration for aggregate math."""
    if value is None or isinstance(value, (bool, str)):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


__all__ = [
    "LATENCY_BUCKETS",
    "MAX_PAGE_COUNT",
    "MAX_SECTION_COUNT",
    "MIN_PAGE_COUNT",
    "MIN_SECTION_COUNT",
    "OVERFLOW_PAGE_THRESHOLDS",
    "PAGE_BUCKETS",
    "SECTION_BUCKETS",
    "count_sections",
    "finite_seconds",
    "latency_bucket",
    "normalize_page_count",
    "normalize_section_count",
    "page_bucket",
    "section_bucket",
]
