"""
ATS Simulator Service — Feature 50.

Simulates how major ATS platforms parse a LaTeX résumé.  For each target
ATS system we maintain a profile describing:

  - ``label``   — human-readable display name
  - ``tier``    — "good" | "medium" | "poor"  (parsing quality)
  - ``issues``  — structural patterns the ATS struggles with

The ``simulate()`` method:
  1. Extracts plain prose from LaTeX (reuses the Feature 35 extractor).
  2. Detects structural issues in the LaTeX source.
  3. For "poor"-tier parsers applies distortions to the plain-text view.
  4. Computes a 0–100 compatibility score.
  5. Returns the plain-text view, detected issues, score, and recommendations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List

from .latex_text_extractor import ProseSegment, extract_prose

# ── ATS profiles ──────────────────────────────────────────────────────────────

ATS_PROFILES: Dict[str, dict] = {
    "greenhouse": {
        "label": "Greenhouse",
        "tier": "good",
        "issues": ["multi_column"],
    },
    "lever": {
        "label": "Lever",
        "tier": "good",
        "issues": [],
    },
    "ashby": {
        "label": "Ashby",
        "tier": "good",
        "issues": [],
    },
    "workday": {
        "label": "Workday",
        "tier": "medium",
        "issues": ["custom_sections", "tables"],
    },
    "smartrecruiters": {
        "label": "SmartRecruiters",
        "tier": "medium",
        "issues": ["decorative_elements"],
    },
    "taleo": {
        "label": "Taleo (Oracle)",
        "tier": "poor",
        "issues": ["tables", "multi_column", "pdf_formatting"],
    },
    "icims": {
        "label": "iCIMS",
        "tier": "medium",
        "issues": ["complex_layouts"],
    },
}

# ── Issue detection patterns ───────────────────────────────────────────────────

# Regex patterns to detect LaTeX constructs that cause issues
_ISSUE_PATTERNS: Dict[str, re.Pattern] = {
    "multi_column": re.compile(
        r"\\begin\s*\{(?:multicol|minipage|tabular|longtable|supertabular)",
        re.IGNORECASE,
    ),
    "tables": re.compile(r"\\begin\s*\{(?:tabular|longtable|tabbing)", re.IGNORECASE),
    "custom_sections": re.compile(r"\\section\*?\s*\{", re.IGNORECASE),
    "decorative_elements": re.compile(
        r"\\(?:hrule|vspace|hspace|rule|tikz|pgfpicture|includegraphics)",
        re.IGNORECASE,
    ),
    "pdf_formatting": re.compile(
        r"\\(?:textcolor|colorbox|fboxrule|columnwidth|textwidth|geometry)",
        re.IGNORECASE,
    ),
    "complex_layouts": re.compile(
        r"\\begin\s*\{(?:multicol|minipage|wrapfig|floatrow)",
        re.IGNORECASE,
    ),
}

# Per-issue severity and description
_ISSUE_META: Dict[str, dict] = {
    "multi_column": {
        "severity": "high",
        "description": "Multi-column layout detected. This ATS may merge columns into a single "
                       "stream, causing experience entries to be garbled.",
    },
    "tables": {
        "severity": "high",
        "description": "LaTeX tabular/table environment detected. Many ATS systems cannot parse "
                       "table cells correctly, merging or dropping content.",
    },
    "custom_sections": {
        "severity": "medium",
        "description": "Custom section headers using \\section{} may not be recognised as "
                       "standard resume sections by this ATS.",
    },
    "decorative_elements": {
        "severity": "low",
        "description": "Decorative elements (rules, coloured boxes, graphics) are ignored by "
                       "most ATS systems. They add no value for parsing.",
    },
    "pdf_formatting": {
        "severity": "medium",
        "description": "Complex PDF-level formatting commands detected. Taleo's legacy parser "
                       "may misinterpret positioning, shifting text out of order.",
    },
    "complex_layouts": {
        "severity": "high",
        "description": "Complex layout environments (minipage, wrapfig) detected. Content "
                       "inside these may be parsed out-of-order.",
    },
    # Universal résumé-quality issues (Textkernel parser codes) — see below.
    "contact_not_at_top": {
        "severity": "medium",
        "description": "Contact details (email/phone) are not near the top. Many parsers only "
                       "scan the header region for contact info and may miss them (Textkernel 311).",
    },
    "vertical_dates": {
        "severity": "high",
        "description": "Employment dates appear stacked on their own lines. Parsers expect the "
                       "date range on the same line as the role/company and may drop or misread "
                       "vertically-split dates (Textkernel 418).",
    },
    "missing_section_headers": {
        "severity": "high",
        "description": "No standard section header (Experience, Education, Skills, …) was found "
                       "on its own line. Parsers rely on headers to segment the résumé; without "
                       "them content is mislabeled or lost (Textkernel 325 / 412–414).",
    },
}

# Per-issue recommendation
_ISSUE_RECOMMENDATIONS: Dict[str, str] = {
    "multi_column": "Use a single-column layout. Remove \\begin{multicol} and minipage environments.",
    "tables": "Replace tabular environments with plain \\item lists for skills and experience entries.",
    "custom_sections": "Use common section names: Experience, Education, Skills, Projects, Summary.",
    "decorative_elements": "Remove decorative rules, coloured boxes, and embedded graphics.",
    "pdf_formatting": "Simplify the preamble. Avoid complex spacing/geometry beyond basic margins.",
    "complex_layouts": "Flatten the layout. Avoid wrapfig, minipage side-by-side arrangements.",
    "contact_not_at_top": "Put your email and phone in the header, at the very top of the résumé.",
    "vertical_dates": "Keep each date range on the same line as its job title/company "
                      "(e.g. 'Software Engineer, Acme  2020–2023').",
    "missing_section_headers": "Add clear, standard section headers on their own lines: "
                               "Experience, Education, Skills.",
}


# ── Universal résumé-quality checks (Textkernel parser codes) ──────────────────
# Textkernel (a major résumé-parsing vendor) publishes exactly what breaks parsing.
# Unlike the per-ATS structural checks above, these apply to EVERY résumé and run
# against the extracted plain text — what a parser actually sees. Each is
# deliberately conservative so a clean résumé stays at zero issues; Textkernel's own
# guidance is to surface ranked, actionable fixes, not a wall of codes that
# frustrates candidates.
#
# Code 112 ("skills in a separate section rather than in work-history context") is
# intentionally NOT implemented: a standalone Skills section is near-universal and
# only "Suggested" severity, so flagging it would be noise on almost every résumé.

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
_DATE_ONLY_LINE_RE = re.compile(
    r"^\s*(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?"
    r"(?:19|20)\d{2}"
    r"(?:\s*(?:[-–—]+|to)\s*(?:present|current|"
    r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?(?:19|20)\d{2}))?"
    r"\s*$",
    re.IGNORECASE,
)
_SECTION_HEADER_LINE_RE = re.compile(
    r"^\s*(?:work\s+|professional\s+)?"
    r"(?:experience|employment|education|skills|projects?|"
    r"summary|objective|certifications?|publications?|awards?|work\s+history)"
    r"\s*:?\s*$",
    re.IGNORECASE,
)


def _detect_contact_not_at_top(lines: List[str]) -> bool:
    """Textkernel 311 (Major): contact details exist but are not near the top."""
    idx = None
    for i, ln in enumerate(lines):
        if _EMAIL_RE.search(ln) or _PHONE_RE.search(ln):
            idx = i
            break
    if idx is None:
        return False  # no contact at all is a different (fatal) code, not this one
    top_window = max(3, len(lines) // 5)
    return idx >= top_window


def _detect_vertical_dates(lines: List[str]) -> bool:
    """Textkernel 418 (Fatal): date ranges stacked vertically — 2+ date-only lines."""
    date_only = sum(1 for ln in lines if _DATE_ONLY_LINE_RE.match(ln))
    return date_only >= 2


def _detect_missing_section_headers(lines: List[str]) -> bool:
    """Textkernel 325 / 412–414 (Fatal): no standard section header on its own line."""
    if len(lines) < 4:
        return False  # too little content to judge
    return not any(_SECTION_HEADER_LINE_RE.match(ln) for ln in lines)


def _detect_quality_issues(plain_text: str) -> List[str]:
    """Run the universal Textkernel résumé-quality checks over the extracted text."""
    lines = [ln for ln in plain_text.splitlines() if ln.strip()]
    issues: List[str] = []
    if _detect_contact_not_at_top(lines):
        issues.append("contact_not_at_top")
    if _detect_vertical_dates(lines):
        issues.append("vertical_dates")
    if _detect_missing_section_headers(lines):
        issues.append("missing_section_headers")
    return issues

# Generic recommendations by tier
_TIER_RECOMMENDATIONS: Dict[str, List[str]] = {
    "good": [
        "Keep file size under 2 MB.",
        "Save as PDF/A (archival PDF) for best compatibility.",
    ],
    "medium": [
        "Keep file size under 2 MB.",
        "Avoid headers/footers — some parsers strip them.",
        "Use standard, ATS-friendly fonts (Arial, Helvetica, Calibri).",
    ],
    "poor": [
        "Use a plain, single-column layout with no tables.",
        "Submit as plain-text (.txt) if the portal allows it.",
        "Keep file size under 1 MB.",
        "Avoid any LaTeX-specific typography (em-dashes as \\textemdash, etc.).",
        "Test by pasting plain text of your résumé into the portal's text box.",
    ],
}


# ── Distortions for poor-tier parsers ─────────────────────────────────────────

def _apply_poor_tier_distortions(plain_text: str, detected_issues: List[str]) -> str:
    """
    Simulate what a poor-tier ATS does to the text:
      - "multi_column": interleave alternate lines (simulates merged columns)
      - "tables": remove lines that look like column separators
      - "pdf_formatting": collapse multiple spaces (loss of positional formatting)
    """
    lines = plain_text.splitlines()

    if "multi_column" in detected_issues:
        # Simulate column merge: odd lines get indented with ">> " marker
        merged: List[str] = []
        for i, line in enumerate(lines):
            if i % 2 == 0:
                merged.append(line)
            else:
                merged.append(f">> {line}")
        lines = merged

    if "tables" in detected_issues:
        # Remove short lines that look like table separator artifacts
        lines = [ln for ln in lines if len(ln.strip()) > 3]

    if "pdf_formatting" in detected_issues:
        # Collapse excessive whitespace
        lines = [re.sub(r"  +", " ", ln) for ln in lines]

    return "\n".join(lines)


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class IssueEntry:
    type: str
    severity: str
    description: str
    line_range: str = ""


@dataclass
class AtsSimulationResult:
    ats_label: str
    plain_text_view: str
    issues: List[IssueEntry]
    score: int            # 0–100 compatibility
    recommendations: List[str]


# ── Service ───────────────────────────────────────────────────────────────────

class AtsSimulatorService:
    """Simulate how a named ATS system parses a LaTeX résumé."""

    def simulate(self, latex_content: str, ats_name: str) -> AtsSimulationResult:
        """
        Run the ATS simulation.

        Args:
            latex_content: Raw LaTeX source of the résumé.
            ats_name: Key from ATS_PROFILES (e.g. "taleo").

        Returns:
            AtsSimulationResult with plain-text view, issues, score, and
            recommendations.

        Raises:
            ValueError: If ``ats_name`` is not in ATS_PROFILES.
        """
        if ats_name not in ATS_PROFILES:
            raise ValueError(f"Unknown ATS: {ats_name!r}. Valid: {list(ATS_PROFILES)}")

        profile = ATS_PROFILES[ats_name]

        # 1. Extract plain text
        segments: List[ProseSegment] = extract_prose(latex_content)
        plain_text = "\n".join(seg.text for seg in segments if seg.text.strip())
        if not plain_text.strip():
            # Fallback: strip common LaTeX commands with a simple regex
            plain_text = self._naive_strip(latex_content)

        # 2. Detect issues: per-ATS structural issues + universal Textkernel
        #    résumé-quality issues (the latter always run, on the undistorted text).
        detected_issue_types = self._detect_issues(latex_content, profile["issues"])
        for quality_issue in _detect_quality_issues(plain_text):
            if quality_issue not in detected_issue_types:
                detected_issue_types.append(quality_issue)

        # 3. Apply distortions for poor-tier parsers
        if profile["tier"] == "poor":
            plain_text = _apply_poor_tier_distortions(plain_text, detected_issue_types)

        # 4. Build issue entries with approximate line ranges
        issues = self._build_issue_entries(latex_content, detected_issue_types)

        # 5. Compute score
        score = self._compute_score(profile, detected_issue_types)

        # 6. Build recommendations
        recommendations = self._build_recommendations(detected_issue_types, profile["tier"])

        return AtsSimulationResult(
            ats_label=profile["label"],
            plain_text_view=plain_text,
            issues=issues,
            score=score,
            recommendations=recommendations,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _detect_issues(self, latex: str, ats_issue_types: List[str]) -> List[str]:
        """Return the subset of ats_issue_types that are actually present in the LaTeX."""
        found = []
        for issue_type in ats_issue_types:
            pattern = _ISSUE_PATTERNS.get(issue_type)
            if pattern and pattern.search(latex):
                found.append(issue_type)
        return found

    def _build_issue_entries(
        self, latex: str, detected_issue_types: List[str]
    ) -> List[IssueEntry]:
        """Build IssueEntry objects with line ranges for each detected issue."""
        entries: List[IssueEntry] = []
        lines = latex.splitlines()
        for issue_type in detected_issue_types:
            pattern = _ISSUE_PATTERNS.get(issue_type)
            meta = _ISSUE_META.get(issue_type, {})
            line_range = ""
            if pattern:
                for i, line in enumerate(lines, 1):
                    if pattern.search(line):
                        line_range = f"line {i}"
                        break
            entries.append(
                IssueEntry(
                    type=issue_type,
                    severity=meta.get("severity", "medium"),
                    description=meta.get("description", ""),
                    line_range=line_range,
                )
            )
        return entries

    def _compute_score(self, profile: dict, detected_issue_types: List[str]) -> int:
        """
        Score formula:
          - Start with a tier base: good=90, medium=70, poor=50
          - Deduct per detected issue: high=-15, medium=-8, low=-4
          - Clamp to [0, 100]
        """
        tier_base = {"good": 90, "medium": 70, "poor": 50}
        score = tier_base.get(profile["tier"], 60)

        severity_penalty = {"high": 15, "medium": 8, "low": 4}
        for issue_type in detected_issue_types:
            meta = _ISSUE_META.get(issue_type, {})
            severity = meta.get("severity", "medium")
            score -= severity_penalty.get(severity, 8)

        return max(0, min(100, score))

    def _build_recommendations(
        self, detected_issue_types: List[str], tier: str
    ) -> List[str]:
        """Combine issue-specific + tier-generic recommendations (deduped)."""
        seen: set = set()
        recs: List[str] = []

        # Issue-specific first (most actionable)
        for issue_type in detected_issue_types:
            rec = _ISSUE_RECOMMENDATIONS.get(issue_type, "")
            if rec and rec not in seen:
                recs.append(rec)
                seen.add(rec)

        # Tier-generic recommendations
        for rec in _TIER_RECOMMENDATIONS.get(tier, []):
            if rec not in seen:
                recs.append(rec)
                seen.add(rec)

        return recs

    @staticmethod
    def _naive_strip(latex: str) -> str:
        """Minimal fallback: remove LaTeX commands and return readable text."""
        # Remove preamble (everything before \begin{document})
        doc_start = latex.find(r"\begin{document}")
        if doc_start != -1:
            latex = latex[doc_start + len(r"\begin{document}"):]
        # Remove \end{document}
        doc_end = latex.find(r"\end{document}")
        if doc_end != -1:
            latex = latex[:doc_end]
        # Strip LaTeX commands
        text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])*(?:\{[^{}]*\})*", " ", latex)
        # Strip remaining braces, math
        text = re.sub(r"[{}$\\]", " ", text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text)
        return text.strip()


# Singleton
ats_simulator_service = AtsSimulatorService()
