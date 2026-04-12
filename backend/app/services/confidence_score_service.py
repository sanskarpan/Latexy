"""
Resume Confidence Score Service — Feature 59.

Holistic 0-100 quality score across five dimensions (no LLM):
  writing_quality  30%  — weak verbs, buzzwords, passive voice
  completeness     20%  — expected sections present
  quantification   20%  — % of \\item lines containing numbers
  formatting       15%  — date format consistency
  section_order    15%  — appropriate section ordering
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from .proofreader_service import proofread_latex

# ── Types ─────────────────────────────────────────────────────────────────────


@dataclass
class ConfidenceScore:
    writing_quality: int   # 30% weight
    completeness: int      # 20% weight
    quantification: int    # 20% weight
    formatting: int        # 15% weight
    section_order: int     # 15% weight

    @property
    def overall(self) -> int:
        return round(
            self.writing_quality * 0.30
            + self.completeness * 0.20
            + self.quantification * 0.20
            + self.formatting * 0.15
            + self.section_order * 0.15
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

_SECTION_RE = re.compile(r'\\section\*?\{([^}]+)\}', re.I)

# Four pillars of a complete resume
_COMPLETENESS_PATTERNS = [
    re.compile(r'contact|personal|info|phone|email', re.I),
    re.compile(r'experience|work|employment|career|position', re.I),
    re.compile(r'education|degree|academic|university|college|school', re.I),
    re.compile(r'skills?|technologies|languages|tools|competenc', re.I),
]

# Date format families — inconsistency across families is penalized
_DATE_FORMAT_FAMILIES = [
    (re.compile(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{4}\b', re.I), 'abbr_month'),
    (re.compile(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b', re.I), 'full_month'),
    (re.compile(r'\b\d{1,2}/\d{4}\b'), 'slash'),
    (re.compile(r'\b\d{4}-\d{2}\b'), 'iso'),
]


# ── Service ───────────────────────────────────────────────────────────────────


class ConfidenceScoreService:
    def score(self, latex_content: str) -> ConfidenceScore:
        """Compute all five dimension scores and return a ConfidenceScore."""
        section_names = _SECTION_RE.findall(latex_content)
        return ConfidenceScore(
            writing_quality=self._score_writing(latex_content),
            completeness=self._score_completeness(latex_content, section_names),
            quantification=self._score_quantification(latex_content),
            formatting=self._score_formatting(latex_content),
            section_order=self._score_section_order(section_names),
        )

    # ── Dimension scorers ──────────────────────────────────────────────────────

    def _score_writing(self, latex_content: str) -> int:
        if not latex_content.strip():
            return 0
        return proofread_latex(latex_content).overall_score

    def _score_completeness(self, latex_content: str, section_names: List[str]) -> int:
        # Check section names + first 2000 chars of content (for header-embedded contact)
        search_text = " ".join(section_names) + " " + latex_content[:2000]
        found = sum(1 for pat in _COMPLETENESS_PATTERNS if pat.search(search_text))
        return round(found / len(_COMPLETENESS_PATTERNS) * 100)

    def _score_quantification(self, latex_content: str) -> int:
        item_lines = [ln for ln in latex_content.splitlines() if r'\item' in ln]
        if not item_lines:
            return 50  # neutral — no bullet items
        with_numbers = sum(1 for ln in item_lines if re.search(r'\d+', ln))
        return round(with_numbers / len(item_lines) * 100)

    def _score_formatting(self, latex_content: str) -> int:
        formats_found: set[str] = set()
        for pattern, name in _DATE_FORMAT_FAMILIES:
            if pattern.search(latex_content):
                formats_found.add(name)
        if not formats_found:
            return 90  # no dates found — can't penalize
        if len(formats_found) == 1:
            return 100  # perfectly consistent
        if len(formats_found) == 2:
            return 60   # one inconsistency
        return 30       # multiple inconsistencies

    def _score_section_order(self, section_names: List[str]) -> int:
        if len(section_names) < 2:
            return 80  # can't assess with fewer than 2 sections

        lower = [n.lower() for n in section_names]

        exp_idx = next(
            (i for i, n in enumerate(lower) if re.search(r'experience|work|employment', n)), None
        )
        edu_idx = next(
            (i for i, n in enumerate(lower) if re.search(r'education|degree|academic', n)), None
        )

        if exp_idx is None or edu_idx is None:
            return 80  # can't determine order without both sections

        score = 70  # baseline

        # Experience before Education is canonical for experienced professionals
        if exp_idx < edu_idx:
            score += 20

        # Summary/Profile/Objective as first section is good practice
        if re.search(r'summary|objective|profile|about', lower[0]):
            score += 10

        return min(100, score)

    # ── Derived metrics ────────────────────────────────────────────────────────

    def grade(self, overall: int) -> str:
        if overall >= 90:
            return 'A'
        if overall >= 80:
            return 'B'
        if overall >= 70:
            return 'C'
        if overall >= 60:
            return 'D'
        return 'F'

    def get_improvements(self, cs: ConfidenceScore, latex_content: str) -> List[str]:
        improvements: List[str] = []

        if cs.writing_quality < 80:
            improvements.append(
                "Replace weak verbs ('responsible for', 'helped with') with "
                "strong action verbs (Led, Engineered, Delivered)"
            )
        if cs.quantification < 60:
            improvements.append(
                "Add metrics to bullet points — include numbers, percentages, "
                "and scales (e.g. 'Reduced load time by 40%')"
            )
        if cs.completeness < 75:
            improvements.append(
                "Add missing sections — a complete resume should have "
                "Experience, Education, Skills, and Contact information"
            )
        if cs.formatting < 80:
            improvements.append(
                "Standardize date formats — use the same style throughout "
                "(e.g. 'Jan 2020' everywhere)"
            )
        if cs.section_order < 80:
            improvements.append(
                "Reorder sections — for most roles, put Experience first, "
                "followed by Skills, then Education"
            )

        _generic = [
            "Quantify achievements with specific numbers and metrics to demonstrate impact",
            "Use strong action verbs at the start of each bullet point",
            "Keep the resume to one page for fewer than 10 years of experience",
        ]
        for g in _generic:
            if len(improvements) >= 3:
                break
            if g not in improvements:
                improvements.append(g)

        return improvements[:3]


confidence_score_service = ConfidenceScoreService()
