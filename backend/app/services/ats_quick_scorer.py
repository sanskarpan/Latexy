"""
ATS Quick Scorer — lightweight, pure-Python ATS scoring (<50ms target).
No network calls, no DB writes, no Celery. Used by POST /ats/quick-score.
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class QuickScoreResult:
    score: int               # 0-100
    grade: str               # A/B/C/D/F
    sections_found: List[str]
    missing_sections: List[str]
    keyword_match_percent: Optional[float]


# ── Constants ──────────────────────────────────────────────────────────────

REQUIRED_SECTIONS = ["contact_info", "experience", "education", "skills"]

SECTION_PATTERNS: Dict[str, List[str]] = {
    "contact_info": [],  # detected via email/phone regex
    "experience": [r"experience", r"work\s+history", r"employment", r"career", r"positions?(?:\s|$)"],
    "education": [r"education", r"academic", r"degree", r"university", r"college"],
    "skills": [r"skills", r"competenc", r"technologies", r"technical\s+skills", r"proficienc", r"software"],
}

OPTIONAL_SECTIONS: Dict[str, List[str]] = {
    "projects": [r"projects?"],
    "certifications": [r"certif", r"licens"],
    "summary": [r"summary", r"objective", r"profile", r"about\s+me"],
    "publications": [r"publications?", r"papers?"],
}

ACTION_VERBS = {
    "led", "managed", "directed", "supervised", "oversaw", "spearheaded",
    "championed", "orchestrated", "mentored", "coached", "guided",
    "achieved", "delivered", "exceeded", "surpassed", "accomplished",
    "improved", "increased", "reduced", "optimized", "streamlined",
    "generated", "saved", "boosted", "accelerated", "enhanced",
    "developed", "built", "designed", "implemented", "engineered",
    "architected", "created", "deployed", "migrated", "integrated",
    "automated", "refactored", "debugged", "tested", "maintained",
    "collaborated", "coordinated", "partnered", "facilitated",
    "communicated", "presented", "negotiated", "consulted",
    "analyzed", "evaluated", "assessed", "researched", "identified",
    "investigated", "measured", "monitored", "tracked", "audited",
    "launched", "executed", "established", "initiated", "transformed",
    "modernized", "scaled", "expanded", "drove", "pioneered",
}

STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "get", "has", "him", "his", "how",
    "its", "may", "new", "now", "old", "see", "two", "who", "did", "she",
    "use", "way", "many", "will", "with", "that", "this", "from", "have",
    "they", "been", "work", "your", "more", "also", "able", "each",
    "what", "when", "which", "where", "there", "their", "about", "would",
}

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"[\+\(]?[1-9][0-9 .\-\(\)]{8,}[0-9]")
_QUANT_RE = re.compile(r"\d+\s*%|\$\s*[\d,.]+|\d+\s*(?:million|thousand|k\b)", re.IGNORECASE)


# ── Text extraction ───────────────────────────────────────────────────────

def _extract_text(latex: str) -> str:
    """Strip LaTeX commands, keep meaningful text."""
    text = latex
    # Extract inner text from formatting commands
    for cmd in ("textbf", "textit", "emph", "underline", "texttt",
                "text", "mbox", "textrm", "textsc", "textsl"):
        text = re.sub(rf"\\{cmd}\{{([^}}]*)\}}", r"\1", text)
    # Preserve section headers
    text = re.sub(
        r"\\(?:section|subsection|subsubsection)\*?\{([^}]*)\}",
        r"\n\1\n", text,
    )
    # href display text
    text = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", text)
    # title/author
    text = re.sub(r"\\(?:title|author|date)\{([^}]*)\}", r"\1\n", text)
    # Remove environments markers
    text = re.sub(r"\\(?:begin|end)\{[^}]*\}", "", text)
    # Remove remaining commands
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})*", "", text)
    # Comments
    text = re.sub(r"%.*$", "", text, flags=re.MULTILINE)
    # Leftover braces/backslashes
    text = re.sub(r"[{}\\]", " ", text)
    # Normalise whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_section_names(latex: str) -> List[str]:
    """Get section names from \\section{...} commands."""
    return re.findall(r"\\(?:section|subsection|subsubsection)\*?\{([^}]*)\}", latex)


# ── Scoring layers ────────────────────────────────────────────────────────

def _score_sections(latex: str, plain_text: str) -> tuple[int, List[str], List[str]]:
    """
    SECTION DETECTION — 40 pts max.
    Required: contact_info, experience, education, skills (10 pts each).
    """
    section_names = [s.lower() for s in _extract_section_names(latex)]
    found: List[str] = []
    missing: List[str] = []

    # Contact info — special: detect via email/phone in raw LaTeX
    if _EMAIL_RE.search(latex) or _PHONE_RE.search(latex):
        found.append("contact_info")
    else:
        missing.append("contact_info")

    # Other required sections
    for section_key in ["experience", "education", "skills"]:
        patterns = SECTION_PATTERNS[section_key]
        detected = any(
            re.search(pat, name) for pat in patterns for name in section_names
        ) or any(
            re.search(pat, plain_text, re.IGNORECASE) for pat in patterns
        )
        if detected:
            found.append(section_key)
        else:
            missing.append(section_key)

    # Optional sections (don't affect score, but report)
    for section_key, patterns in OPTIONAL_SECTIONS.items():
        detected = any(
            re.search(pat, name) for pat in patterns for name in section_names
        ) or any(
            re.search(pat, plain_text, re.IGNORECASE) for pat in patterns
        )
        if detected:
            found.append(section_key)

    required_found = sum(1 for s in REQUIRED_SECTIONS if s in found)
    score = int((required_found / 4) * 40)
    return score, found, missing


def _score_contact(latex: str) -> int:
    """CONTACT INFO CHECK — 10 pts max (5 email + 5 phone)."""
    pts = 0
    if _EMAIL_RE.search(latex):
        pts += 5
    if _PHONE_RE.search(latex):
        pts += 5
    return pts


def _score_quality(plain_text: str) -> int:
    """CONTENT QUALITY — 20 pts max (action verbs + quantification)."""
    words = plain_text.lower().split()
    if not words:
        return 0

    # Action verb ratio → up to 10 pts
    verb_count = sum(1 for w in words if w in ACTION_VERBS)
    verb_ratio = verb_count / len(words)
    verb_pts = min(10, int(verb_ratio * 200))  # 5% ratio → 10 pts

    # Quantification → up to 10 pts
    quant_matches = len(_QUANT_RE.findall(plain_text))
    quant_pts = min(10, quant_matches * 3)  # ~3 quantified achievements → 9 pts

    return verb_pts + quant_pts


def _score_keywords(plain_text: str, job_description: Optional[str]) -> tuple[int, Optional[float]]:
    """
    KEYWORD SCORE — 30 pts max.
    If JD provided: tokenize, remove stopwords, match top 30 JD keywords.
    If no JD: award 15 pts baseline.
    """
    if not job_description:
        return 15, None

    # Tokenize JD
    jd_words = re.findall(r"[a-zA-Z]{3,}", job_description.lower())
    jd_words = [w for w in jd_words if w not in STOPWORDS]

    # Frequency count → top 30
    freq: Dict[str, int] = {}
    for w in jd_words:
        freq[w] = freq.get(w, 0) + 1
    top_keywords = sorted(freq, key=freq.get, reverse=True)[:30]  # type: ignore[arg-type]

    if not top_keywords:
        return 15, None

    # Match against resume text
    resume_words_set = set(re.findall(r"[a-zA-Z]{3,}", plain_text.lower()))
    matched = sum(1 for kw in top_keywords if kw in resume_words_set)
    match_pct = matched / len(top_keywords) * 100
    score = int(match_pct / 100 * 30)

    return score, round(match_pct, 1)


def _compute_grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


# ── Public API ─────────────────────────────────────────────────────────────

def quick_score_latex(
    latex_content: str,
    job_description: Optional[str] = None,
) -> QuickScoreResult:
    """
    Compute a quick ATS score from LaTeX content.
    Pure Python, no I/O, target < 50ms.
    Returns QuickScoreResult dataclass.
    """
    plain_text = _extract_text(latex_content)

    section_score, sections_found, missing_sections = _score_sections(latex_content, plain_text)
    contact_score = _score_contact(latex_content)
    quality_score = _score_quality(plain_text)
    keyword_score, keyword_match_pct = _score_keywords(plain_text, job_description)

    total = min(100, section_score + contact_score + quality_score + keyword_score)
    grade = _compute_grade(total)

    return QuickScoreResult(
        score=total,
        grade=grade,
        sections_found=sections_found,
        missing_sections=missing_sections,
        keyword_match_percent=keyword_match_pct,
    )
