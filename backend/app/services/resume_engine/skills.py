"""Literal source mentions and declared aliases; never semantic fact verification."""
from __future__ import annotations

import re

from .requirements import ALIASES

_NEGATED_SCOPE = re.compile(r"\b(?:not|never|no|without|neither|nor|except|lack|lacks|lacking)\b", re.I)
_CLAUSES = re.compile(r"(?<=[.!?;])\s+|\n+")


def canonical_skill(term: str) -> str:
    lower = term.casefold()
    return ALIASES.get(lower, lower)


def skill_mention(term: str, text: str) -> str:
    """Return positive/ambiguous/absent; negation scope is deliberately conservative.

    Any negated sentence containing the term is ambiguous, including mixed
    relations such as 'Python, not Java'. It cannot count as positive evidence.
    An unrelated sentence's negation does not invalidate a positive mention.
    """
    canonical = canonical_skill(term)
    variants = {canonical, *(alias for alias, target in ALIASES.items() if target == canonical)}
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True)) + r")(?!\w)", re.I)
    positive = False
    for clause in _CLAUSES.split(text):
        if pattern.search(clause):
            if canonical == "golang" and not re.search(r"(?<!\w)golang(?!\w)", clause, re.I):
                # 'go' is also an ordinary verb/marketing phrase. Only an
                # isolated skill or explicit software context disambiguates it.
                isolated = clause.strip(" \t.,;:-").casefold() == "go"
                technical = re.search(r"\b(?:programming|language|developer|backend|microservices|compiler|stdlib|goroutines)\b", clause, re.I)
                ordinary_phrase = re.search(r"\bgo[\s-]+to[\s-]+market\b|\bgo\s+(?:to|beyond|ahead|live)\b", clause, re.I)
                if ordinary_phrase or not isolated and not technical:
                    return "ambiguous"
            if _NEGATED_SCOPE.search(clause):
                return "ambiguous"
            positive = True
    return "positive" if positive else "absent"


def positive_skill_mention(term: str, text: str) -> bool:
    return skill_mention(term, text) == "positive"
