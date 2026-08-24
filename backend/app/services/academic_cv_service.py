"""
Academic CV detection + conversion prompt builder.

Feature 7.1 from FEATURES.md is intentionally narrower than generic resume
optimization: it identifies academic CV signals, then produces targeted
instructions for reframing the document into an industry resume variant.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class AcademicCVReport:
    is_academic_cv: bool
    detected_sections: List[str]
    estimated_pages: int
    confidence: float
    reasons: List[str]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _section_re(*keywords: str) -> re.Pattern[str]:
    r"""
    Build a heading matcher for a section named by any of ``keywords``.

    Three things this gets right that a hand-written pattern kept getting wrong:

    1. **The alternation is grouped.** Writing
       ``r"\\section\*?\{publications?|conference papers?"`` parses as
       *"\section{publications" OR "conference papers"* — the second branch is
       not anchored to a section command at all, so a résumé that merely says
       "I reviewed conference papers for NeurIPS" was credited with a
       publications section.

    2. **The keyword may appear anywhere inside the braces.** Real headings are
       qualified: "Peer-Reviewed Publications", "Research Summary",
       "Teaching \& Mentorship". Requiring the keyword first made the detector
       miss our own ``academic/postdoc.tex``.

    3. **Any command ending in "section" counts**, so user-defined wrappers
       (``\ressection`` in ``ats_modern.tex``) are recognised alongside
       ``\section`` and ``\subsection``.
    """
    alternatives = "|".join(keywords)
    return re.compile(
        r"\\[a-zA-Z]*section\*?\s*\{[^}]*(?:" + alternatives + r")[^}]*\}",
        re.I,
    )


_SECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "publications": _section_re(r"publications?", r"conference papers?", r"journal papers?"),
    "teaching": _section_re(r"teaching", r"mentorship"),
    "grants": _section_re(r"grants?", r"fellowships?", r"awards?", r"honou?rs?"),
    "research": _section_re(r"research"),
    "presentations": _section_re(r"presentations?", r"talks?"),
    "references": _section_re(r"references?"),
    "service": _section_re(r"academic service", r"service"),
}

_BIBLIOGRAPHY_PATTERNS = [
    re.compile(r"\\bibliographystyle\b", re.I),
    re.compile(r"\\bibliography\b", re.I),
    re.compile(r"\\printbibliography\b", re.I),
    re.compile(r"\\cite[t|p]?\{", re.I),
]

_ACADEMIC_ROLE_RE = re.compile(
    r"\b(phd|doctoral|postdoc|postdoctoral|research assistant|teaching assistant|lecturer|professor|dissertation)\b",
    re.I,
)

_TARGET_INDUSTRY_LABELS = {
    "tech": "Software Engineering / Product Technology",
    "data_science": "Data Science / Machine Learning",
    "finance": "Finance / Quantitative Roles",
    "consulting": "Consulting / Strategy",
    "product": "Product Management",
    "other": "General Industry",
}


class AcademicCVService:
    def detect(self, latex_content: str, document_type: Optional[str] = None) -> AcademicCVReport:
        text = latex_content or ""
        lowered = text.lower()

        detected_sections: List[str] = []
        reasons: List[str] = []
        score = 0.0

        if document_type == "academic_cv":
            score += 0.35
            reasons.append("document_type is academic_cv")

        for key, pattern in _SECTION_PATTERNS.items():
            if pattern.search(text):
                detected_sections.append(key)
                score += 0.14
                reasons.append(f"found {key} section")

        for pattern in _BIBLIOGRAPHY_PATTERNS:
            if pattern.search(text):
                score += 0.1
                reasons.append("bibliography/citation markup present")
                break

        if _ACADEMIC_ROLE_RE.search(lowered):
            score += 0.08
            reasons.append("academic role terminology present")

        estimated_pages = self.estimate_pages(text, detected_sections)
        if estimated_pages > 2:
            score += 0.08
            reasons.append(f"estimated length is {estimated_pages} pages")

        confidence = max(0.0, min(1.0, round(score, 2)))
        is_academic = confidence >= 0.45 or (
            "publications" in detected_sections
            and any(section in detected_sections for section in ("research", "teaching", "grants"))
        )

        return AcademicCVReport(
            is_academic_cv=is_academic,
            detected_sections=detected_sections,
            estimated_pages=estimated_pages,
            confidence=confidence,
            reasons=reasons,
        )

    def estimate_pages(self, latex_content: str, detected_sections: Optional[List[str]] = None) -> int:
        text = latex_content or ""
        no_comments = re.sub(r"(?m)^\s*%.*$", "", text)
        lines = [line.strip() for line in no_comments.splitlines() if line.strip()]
        bullet_count = len(re.findall(r"\\item\b", text))
        section_count = len(re.findall(r"\\section\*?\{", text))
        publication_items = len(re.findall(r"\\bibitem\b|@", text))
        academic_bonus = 8 * len(detected_sections or [])

        weighted = len(lines) + bullet_count * 1.5 + section_count * 2 + publication_items * 2 + academic_bonus
        return max(1, min(6, int(round(weighted / 55.0))))

    def build_conversion_instructions(
        self,
        report: AcademicCVReport,
        target_industry: str,
        target_role_description: Optional[str] = None,
    ) -> str:
        industry_label = _TARGET_INDUSTRY_LABELS.get(target_industry, _TARGET_INDUSTRY_LABELS["other"])
        role_block = (
            f"Target role context:\n{target_role_description.strip()}\n"
            if target_role_description and target_role_description.strip()
            else ""
        )
        detected = ", ".join(report.detected_sections) if report.detected_sections else "none"
        target_pages = 1 if report.estimated_pages <= 4 else 2

        return (
            "Convert this academic CV into an industry-ready resume variant.\n"
            f"Target industry: {industry_label}.\n"
            f"Detected academic sections: {detected}.\n"
            f"Target output length: {target_pages} page(s).\n"
            f"{role_block}"
            "Strict rules:\n"
            "1. Preserve all factual claims, employers, institutions, dates, degrees, titles, and quantified results.\n"
            "2. Reframe academic accomplishments into industry outcomes, ownership, delivery, scale, leadership, and impact.\n"
            "3. Keep only the 2-3 strongest publications or talks if a publications/presentations section exists.\n"
            "4. Convert teaching to mentoring, leadership, communication, and stakeholder-facing experience.\n"
            "5. Convert grants/fellowships into quantified achievement and selectivity signals.\n"
            "6. Reduce bibliography detail: no co-author lists, page numbers, or DOI clutter unless mission-critical.\n"
            "7. Prefer recent/high-impact achievements; aggressively condense low-signal academic detail.\n"
            "8. Keep the output in valid compilable LaTeX and preserve the overall template structure where practical.\n"
            "9. Optimize for recruiter readability and ATS keyword alignment without inventing experience.\n"
            "10. Treat this as a new industry resume variant, not an academic CV polish pass.\n"
        )


academic_cv_service = AcademicCVService()
