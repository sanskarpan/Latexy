"""Prevent generated resume bullets from fabricating unsupported metrics."""

from __future__ import annotations

import re

_METRIC_RE = re.compile(
    r"(?<![\w\[])"
    r"(?P<prefix>[$£€₹])?"
    r"(?P<number>\d++(?:[.,]\d++)*)"
    r"(?P<suffix>[kKmMbB](?:\+)?|\+|\\?%)?"
    r"(?![\w\]])"
)

# Consume complete candidates first, even if their trailing word boundary is
# invalid. A direct search with that boundary would restart at every comma in
# a rejected long chain. The anchored match below preserves the original
# longest-valid-prefix behavior without repeatedly scanning those suffixes.
_METRIC_TOKEN_RE = re.compile(
    r"(?<![\w\[])[$£€₹]?\d++(?:[.,]\d++)*+"
    r"(?:[kKmMbB](?:\+)?|\+|\\?%)?"
)


def _metric_matches(text: str):
    for token in _METRIC_TOKEN_RE.finditer(text):
        match = _METRIC_RE.match(text, token.start(), min(len(text), token.end() + 1))
        if match:
            yield match


def _evidence_numbers(evidence: str) -> set[str]:
    return {match.group("number") for match in _metric_matches(evidence)}


def replace_unverified_metrics(text: str, evidence: str = "") -> str:
    """Replace every numeric claim not present in user evidence with literal ``[X]``."""
    allowed = _evidence_numbers(evidence)

    def replace(match: re.Match[str]) -> str:
        if match.group("number") in allowed:
            return match.group(0)
        prefix = match.group("prefix") or ""
        suffix = match.group("suffix") or ""
        return f"{prefix}[X]{suffix}"

    parts = []
    cursor = 0
    for match in _metric_matches(text):
        parts.extend((text[cursor:match.start()], replace(match)))
        cursor = match.end()
    parts.append(text[cursor:])
    return "".join(parts)
