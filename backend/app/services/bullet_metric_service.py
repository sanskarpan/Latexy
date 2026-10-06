"""Prevent generated resume bullets from fabricating unsupported metrics."""

from __future__ import annotations

import re

_METRIC_RE = re.compile(
    r"(?<![\w\[])"
    r"(?P<prefix>[$£€₹])?"
    r"(?P<number>\d+(?:[.,]\d+)*)"
    r"(?P<suffix>[kKmMbB](?:\+)?|\+|\\?%)?"
    r"(?![\w\]])"
)


def _evidence_numbers(evidence: str) -> set[str]:
    return {match.group("number") for match in _METRIC_RE.finditer(evidence)}


def replace_unverified_metrics(text: str, evidence: str = "") -> str:
    """Replace every numeric claim not present in user evidence with literal ``[X]``."""
    allowed = _evidence_numbers(evidence)

    def replace(match: re.Match[str]) -> str:
        if match.group("number") in allowed:
            return match.group(0)
        prefix = match.group("prefix") or ""
        suffix = match.group("suffix") or ""
        return f"{prefix}[X]{suffix}"

    return _METRIC_RE.sub(replace, text)
