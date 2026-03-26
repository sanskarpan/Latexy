"""
Rule-based resume proofreader service — Feature 25.

Analyzes resume LaTeX content for writing quality issues:
- Weak verbs (responsible for, helped with, worked on…)
- Passive voice (was improved by, has been…)
- Buzzwords (synergy, leveraging, proactive…)
- Vague language (various, multiple, several…)

No LLM — purely regex-based, fast and deterministic.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

# ── Response schemas ──────────────────────────────────────────────────────────


class ProofreadIssue(BaseModel):
    line: int           # 1-indexed, matches Monaco line numbers
    column_start: int   # 1-indexed
    column_end: int     # 1-indexed, exclusive (matches Monaco Range endColumn)
    category: str       # "weak_verb" | "passive_voice" | "buzzword" | "vague"
    severity: str       # "error" | "warning" | "info"
    message: str
    suggestion: Optional[str] = None
    original_text: str
    suggested_text: Optional[str] = None


class ProofreadResponse(BaseModel):
    issues: List[ProofreadIssue]
    summary: Dict[str, int]   # { "weak_verb": 5, "buzzword": 2, … }
    overall_score: int         # 0-100


# ── Pattern tables ────────────────────────────────────────────────────────────
# Each tuple: (regex_str, message, suggested_replacement_or_None)

_WEAK_VERB_PATTERNS: List[Tuple[str, str, Optional[str]]] = [
    (r'\bresponsible for\b', 'Replace with an action verb (Led, Managed, Owned)', 'Led'),
    (r'\bhelped(?: to)?\b', 'Replace with a direct action verb', 'Supported'),
    (r'\bworked on\b', 'Replace with a specific action verb', 'Developed'),
    (r'\bwas involved in\b', 'Replace with an action verb showing ownership', 'Led'),
    (r'\bassisted (?:with|in)\b', 'Replace with a stronger action verb', 'Led'),
    (r'\bparticipated in\b', 'Replace with your specific contribution', 'Contributed to'),
    (r'\bcontributed to\b', 'Replace with a specific action verb', 'Drove'),
]

_PASSIVE_VOICE_PATTERNS: List[Tuple[str, str, Optional[str]]] = [
    (
        r'\bwas (?:improved|optimized|reduced|increased|built|created|developed) by\b',
        'Rewrite in active voice',
        None,
    ),
    (r'\bwere (?:responsible|required|expected)\b', 'Rewrite in active voice', None),
    (r'\bhas been\b', 'Consider rewriting in active voice', None),
    (r'\bhave been\b', 'Consider rewriting in active voice', None),
    (r'\bbeing (?:used|developed|maintained|managed)\b', 'Rewrite in active voice', None),
]

_BUZZWORD_PATTERNS: List[Tuple[str, str, Optional[str]]] = [
    (r'\bsynergy\b', 'Remove buzzword or replace with a specific collaboration example', None),
    (r'\bleverag(?:e|ed|ing)\b', 'Replace with a specific action (Used, Applied, Deployed)', 'Used'),
    (r'\bproactive(?:ly)?\b', 'Remove buzzword; show proactiveness through actions', None),
    (r'\bpassionate about\b', 'Remove; show passion through achievements', None),
    (r'\bteam player\b', 'Remove; show teamwork through collaboration examples', None),
    (r'\bhard[- ]?working\b', 'Remove; let achievements speak for themselves', None),
    (r'\bself[- ]?starter\b', 'Remove; show initiative through examples', None),
    (r'\bthought leader\b', 'Remove; too vague', None),
    (r'\bgo[- ]?getter\b', 'Remove; too informal', None),
    (r'\boutside[- ]the[- ]box\b', 'Remove; too cliché', None),
    (r'\bresults[- ]?driven\b', 'Remove; show results through quantified achievements', None),
    (r'\bdetail[- ]?oriented\b', 'Remove; demonstrate through specific examples', None),
    (r'\bdynamic\b', 'Remove buzzword; describe specific qualities instead', None),
    (r'\binnovative\b', 'Remove buzzword; describe the innovation specifically', None),
]

_VAGUE_PATTERNS: List[Tuple[str, str, Optional[str]]] = [
    (r'\bvarious\b', 'Be specific — name the technologies or projects', None),
    (r'\bmultiple\b', 'Be specific — use an exact number', None),
    (r'\bseveral\b', 'Be specific — use an exact number', None),
    (r'\bnumerous\b', 'Be specific — use an exact number', None),
    (r'\bmany\b', 'Be specific — quantify with a number', None),
]

# Category → (severity, css_class)
_CATEGORY_META: Dict[str, str] = {
    "weak_verb": "warning",
    "passive_voice": "warning",
    "buzzword": "warning",
    "vague": "info",
}

# Flat list: (compiled_re, message, suggestion, category)
_COMPILED_PATTERNS = (
    [(re.compile(pat, re.IGNORECASE), msg, sug, "weak_verb") for pat, msg, sug in _WEAK_VERB_PATTERNS]
    + [(re.compile(pat, re.IGNORECASE), msg, sug, "passive_voice") for pat, msg, sug in _PASSIVE_VOICE_PATTERNS]
    + [(re.compile(pat, re.IGNORECASE), msg, sug, "buzzword") for pat, msg, sug in _BUZZWORD_PATTERNS]
    + [(re.compile(pat, re.IGNORECASE), msg, sug, "vague") for pat, msg, sug in _VAGUE_PATTERNS]
)


# ── LaTeX line filtering ───────────────────────────────────────────────────────

# Commands that produce no user-visible text — skip these lines entirely
_SKIP_LINE_RE = re.compile(
    r'^\s*\\(?:'
    r'documentclass|usepackage|geometry|newcommand|renewcommand|providecommand|'
    r'setlength|setcounter|definecolor|colorlet|lstset|graphicspath|'
    r'begin|end|hspace|vspace|hrule|hline|noindent|newpage|clearpage|pagebreak|'
    r'maketitle|tableofcontents|bibliographystyle|bibliography|'
    r'centering|raggedright|raggedleft|'
    r'section\*?|subsection\*?|subsubsection\*?|chapter\*?|part\*?'
    r')[\[{\s]',
    re.IGNORECASE,
)


def _body_lines(latex_content: str) -> List[Tuple[int, str]]:
    """
    Yield (1-indexed line_number, raw line text) for lines in the document body.
    - Skips preamble (before \\begin{document})
    - Skips comment-only lines and blank lines
    - Skips purely structural LaTeX commands
    """
    lines = latex_content.split('\n')
    in_body = False
    result: List[Tuple[int, str]] = []

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()

        if r'\begin{document}' in line:
            in_body = True
            continue

        if not in_body:
            continue

        if r'\end{document}' in line:
            break

        # Skip comment-only lines
        if stripped.startswith('%'):
            continue

        # Strip inline comments (% ...) while preserving escaped \%
        content = re.sub(r'(?<!\\)%.*$', '', line).rstrip()
        if not content.strip():
            continue

        # Skip purely structural / non-text command lines
        if _SKIP_LINE_RE.match(content):
            continue

        result.append((idx, content))

    return result


# ── Score calculation ─────────────────────────────────────────────────────────


def _compute_score(issues: List[ProofreadIssue], body_line_count: int) -> int:
    """Return 0-100 writing quality score based on issue density."""
    if not issues:
        return 100

    penalty = sum(
        5 if i.severity == 'error' else 3 if i.severity == 'warning' else 1
        for i in issues
    )

    # Normalise against the document size
    max_penalty = max(50, body_line_count * 3)
    ratio = min(1.0, penalty / max_penalty)
    return max(0, int(100 * (1 - ratio)))


# ── Public API ────────────────────────────────────────────────────────────────


def proofread_latex(latex_content: str) -> ProofreadResponse:
    """
    Analyse LaTeX resume content for writing quality issues.

    Returns a ProofreadResponse with:
    - issues: list of located ProofreadIssue objects
    - summary: counts per category
    - overall_score: 0-100 quality score
    """
    body = _body_lines(latex_content)
    issues: List[ProofreadIssue] = []

    for line_number, line_text in body:
        for compiled_re, message, suggestion, category in _COMPILED_PATTERNS:
            for match in compiled_re.finditer(line_text):
                severity = _CATEGORY_META[category]
                issues.append(
                    ProofreadIssue(
                        line=line_number,
                        column_start=match.start() + 1,   # 0→1-indexed
                        column_end=match.end() + 1,        # 0→1-indexed exclusive
                        category=category,
                        severity=severity,
                        message=message,
                        suggestion=suggestion,
                        original_text=match.group(0),
                        suggested_text=suggestion,
                    )
                )

    summary: Dict[str, int] = {}
    for issue in issues:
        summary[issue.category] = summary.get(issue.category, 0) + 1

    return ProofreadResponse(
        issues=issues,
        summary=summary,
        overall_score=_compute_score(issues, len(body)),
    )
