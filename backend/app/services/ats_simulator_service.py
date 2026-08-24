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
from typing import Dict, List, Optional

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
}

# Per-issue recommendation
_ISSUE_RECOMMENDATIONS: Dict[str, str] = {
    "multi_column": "Use a single-column layout. Remove \\begin{multicol} and minipage environments.",
    "tables": "Replace tabular environments with plain \\item lists for skills and experience entries.",
    "custom_sections": "Use common section names: Experience, Education, Skills, Projects, Summary.",
    "decorative_elements": "Remove decorative rules, coloured boxes, and embedded graphics.",
    "pdf_formatting": "Simplify the preamble. Avoid complex spacing/geometry beyond basic margins.",
    "complex_layouts": "Flatten the layout. Avoid wrapfig, minipage side-by-side arrangements.",
}

# ── Document-quality checks (parser-vendor derived) ───────────────────────────
#
# The checks above are ATS-SPECIFIC: each profile opts into the subset it is
# known to choke on. The checks below are UNIVERSAL — they describe résumé
# construction that degrades parsing everywhere, so they run for every profile.
#
# They are modelled on Textkernel's published ResumeQuality code table
# (developer.textkernel.com/tx-platform/v10/resume-parser/overview/parser-output/),
# which is a major parser vendor stating in its own words what breaks its
# parser. Our code names map to theirs as noted, so the mapping stays auditable.
#
# Deliberately NOT implemented from that table:
#   - 433 (columnar data) — already covered by "multi_column" above.
#   - 300 ("the document was PDF") — not actionable for a LaTeX product, and
#     what actually matters is whether the text layer is well-formed, which is
#     verified separately by the pdffonts/pdftotext contract.
#   - 417 (CV-style, only first work-history section parsed) — needs reliable
#     multi-section work-history detection we do not have yet.
#
# Textkernel's own caution shapes how these surface: "You should not use the
# Resume Quality section to communicate problems/suggestions to candidates
# unless you have a very sophisticated workflow and step-by-step improvement
# process. Otherwise, you will frustrate candidates and do more harm than
# good." Hence severities are conservative and each carries a concrete,
# single-action recommendation rather than a raw code.

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Deliberately permissive: international formats, spaces, dashes, parens.
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")

# A line that is ONLY a date token — the signature of a vertical date column.
_BARE_DATE_RE = re.compile(
    r"^\s*(?:"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*'?\d{2,4}"
    r"|\d{1,2}\s*/\s*\d{4}"
    r"|(?:19|20)\d{2}"
    r"|present|current|now|ongoing"
    r")\s*[-–—]?\s*$",
    re.IGNORECASE,
)

# Section headers a parser is likely to recognise (Textkernel code 151 wants a
# "clear, unambiguous, commonly-used header").
_STANDARD_SECTION_WORDS = {
    "experience", "work experience", "employment", "work history",
    "professional experience", "education", "skills", "technical skills",
    "projects", "summary", "profile", "objective", "certifications",
    "publications", "awards", "achievements", "languages", "interests",
    "volunteer", "references", "coursework", "research",
}

_SECTION_CMD_RE = re.compile(r"\\(?:section|subsection)\*?\s*\{([^}]{1,80})\}")
# Matches any command whose name ENDS in "section", so user-defined wrappers
# (\ressection, \cvsection, \resumeSection) are picked up without a hard-coded list.
_SECTION_LIKE_CMD_RE = re.compile(r"\\[a-zA-Z]*section\*?\s*\{([^}]{1,80})\}", re.IGNORECASE)
# Not every résumé marks sections with \section. Two other conventions are
# common in this template set and are perfectly ATS-friendly — arguably more so:
#   ats_plain.tex     bare uppercase lines ("WORK EXPERIENCE")
#   ultra_minimal.tex \textbf{Experience} on its own line
# Treating only \section as a heading reported "no section headings" against our
# own ATS-safe templates, which is the worst possible false positive.
_BOLD_HEADING_RE = re.compile(
    r"^\s*(?:\\noindent\s*)?\\(?:textbf|textsc|bf)\s*\{((?:[^{}]|\\[a-zA-Z]+){1,60})\}\s*\\*\s*$",
    re.M,
)
# Bare-line headings must be ALL CAPS. Allowing Title Case here matched the
# candidate's own name ("Chloe Adams" in two_col_creative) and then reported it
# as a non-standard section heading. Every template in this repo that uses bare
# lines for headings uppercases them ("WORK EXPERIENCE" in ats_plain).
_TEXT_HEADING_RE = re.compile(r"^\s*([A-Z][A-Z&/ ]{2,40})\s*$")
# \newcommand / \renewcommand / \def bodies declare markup, not document content.
_MACRO_DEF_RE = re.compile(
    r"\\(?:(?:re)?newcommand|def)\*?\s*\{?\\[a-zA-Z]+\}?(?:\[\d+\])?\s*\{[^\n]*\}",
)
_SKILLS_SECTION_RE = re.compile(
    r"\\(?:section|subsection)\*?\s*\{[^}]*\bskills?\b[^}]*\}", re.IGNORECASE
)

# How many leading non-empty lines still count as "the top" for contact info.
_CONTACT_TOP_LINES = 6

_QUALITY_META: Dict[str, dict] = {
    "contact_missing": {
        "severity": "high",
        "description": "No email address or phone number was found in the extracted text. "
                       "Most parsers treat a résumé with neither as unroutable and drop it "
                       "(Textkernel code 441, fatal).",
    },
    "contact_not_at_top": {
        "severity": "medium",
        "description": "Contact details were found, but not near the top of the document. "
                       "Parsers look for them in the first few lines and may attach them to "
                       "the wrong record when they appear lower (Textkernel code 311).",
    },
    "vertical_dates": {
        "severity": "high",
        "description": "Date ranges appear to be written vertically across multiple lines. "
                       "Parsers read a flat text stream and cannot pair a start date on one "
                       "line with an end date on the next (Textkernel code 418, fatal).",
    },
    "nonstandard_section_headers": {
        "severity": "suggestion",
        "description": "One or more section headers use wording a parser is unlikely to "
                       "recognise. Section boundaries are inferred from these headings, so "
                       "unusual names can merge two sections into one (Textkernel code 151).",
    },
    "no_section_headers": {
        "severity": "high",
        "description": "No section headings were detected. Without them a parser cannot tell "
                       "where work history ends and education begins (Textkernel codes "
                       "325/412, fatal).",
    },
    "skills_not_in_context": {
        "severity": "suggestion",
        "description": "Skills appear only in a standalone list, not inside work-history "
                       "descriptions. Textkernel recommends skills be evidenced in context "
                       "(code 112) — and Greenhouse, SmartRecruiters and Ashby have no skills "
                       "field at all, so a bare list may never reach the recruiter.",
    },
}

_QUALITY_RECOMMENDATIONS: Dict[str, str] = {
    "contact_missing": "Add an email address and a phone number to the header of the résumé.",
    "contact_not_at_top": "Move your name, email and phone to the first two lines of the document.",
    "vertical_dates": "Write each date range on one line, e.g. 'Jan 2022 – Present', not stacked.",
    "nonstandard_section_headers": "Rename sections to common headings: Experience, Education, Skills, Projects.",
    "no_section_headers": "Add clear section headings (Experience, Education, Skills) on their own lines.",
    "skills_not_in_context": "Work your key skills into the experience bullets, not only a skills list.",
}


def _detect_quality_issues(plain_text: str, latex: str) -> List[str]:
    """
    Universal résumé-construction problems, independent of which ATS is targeted.

    Args:
        plain_text: Text as a parser would extract it (post-distortion is wrong
            here — pass the undistorted extraction so we report on the document,
            not on the simulated parser's mangling of it).
        latex: Raw LaTeX source, for structure that does not survive extraction.

    Returns:
        List of quality issue keys present in ``_QUALITY_META``.
    """
    found: List[str] = []
    lines = [ln for ln in plain_text.splitlines() if ln.strip()]

    # 441 / 311 — contact information presence and placement.
    # Search the LaTeX source too: \href{mailto:me@x.com}{...} and similar do
    # not always survive prose extraction, and reporting "no contact details"
    # on a résumé that plainly has them is worse than not checking at all.
    haystack = plain_text + "\n" + latex
    has_email = bool(_EMAIL_RE.search(haystack))
    has_phone = bool(_PHONE_RE.search(haystack))
    if not has_email and not has_phone:
        found.append("contact_missing")
    else:
        head = "\n".join(lines[:_CONTACT_TOP_LINES])
        latex_head = "\n".join(latex.splitlines()[:40])
        if not (
            _EMAIL_RE.search(head)
            or _PHONE_RE.search(head)
            or _EMAIL_RE.search(latex_head)
            or _PHONE_RE.search(latex_head)
        ):
            found.append("contact_not_at_top")

    # 418 — vertical date columns: two consecutive bare-date lines.
    for first, second in zip(lines, lines[1:]):
        if _BARE_DATE_RE.match(first) and _BARE_DATE_RE.match(second):
            found.append("vertical_dates")
            break

    # 325 / 151 — are there section headings, and can a parser recognise one?
    #
    # Two independent signals must BOTH come up empty before we say anything.
    # The structural pass over-matches by design (it accepts any command ending
    # in "section", any lone bold run), so on its own it reported
    # "unrecognisable headings" against templates that plainly carry "DESIGN
    # SKILLS" and "EDUCATION". The semantic pass is the veto.
    #
    # Flagging individually-unusual headings was also tried and abandoned: an
    # academic CV legitimately carries "Test Scores" or "Awards & Honors"
    # alongside standard sections, and a parser that finds "Education" and
    # "Experience" already has the anchors it needs. The only failure mode worth
    # reporting is a document where nothing at all is recognisable.
    headers = _collect_headings(plain_text, latex)
    if not _has_recognisable_section(plain_text, latex):
        if not headers:
            found.append("no_section_headers")
        else:
            found.append("nonstandard_section_headers")

    # 112 — skills listed but never evidenced in the experience prose.
    if _SKILLS_SECTION_RE.search(latex):
        skills_body = _extract_skills_body(latex)
        terms = [
            t.strip().lower()
            for t in re.split(r"[,;|•\n]", skills_body)
            if 2 < len(t.strip()) < 30
        ]
        if terms:
            # Prose outside the skills section — where evidence should appear.
            elsewhere = _SKILLS_SECTION_RE.sub(" ", latex)
            elsewhere = elsewhere.replace(skills_body, " ").lower()
            if not any(term in elsewhere for term in terms):
                found.append("skills_not_in_context")

    return found


def _collect_headings(plain_text: str, latex: str) -> List[str]:
    r"""
    Return headings detected from *markup*, whatever wording they use.

    Kept separate from :func:`_is_standard_heading` on purpose. Mixing the two
    collapses "this résumé has no headings at all" (fatal) into "its headings
    are worded unusually" (a suggestion) — two different findings with two
    different severities.

    Conventions in this template set, all legitimate:
        \section{Experience}                  most templates
        \ressection{Professional Summary}     ats_modern, via \newcommand
        \textbf{\large EXPERIENCE}            swe_clean
        WORK EXPERIENCE                       ats_plain, a bare line
    """
    headings: List[str] = []

    # Macro definitions declare markup, not content. Without stripping them,
    # \newcommand{\x}[1]{\textbf{\small #1}} contributes a heading of "\small #1".
    body = _MACRO_DEF_RE.sub(" ", latex)

    # Any command whose name ends in "section" — covers \section, \subsection
    # and user-defined wrappers like \ressection without hard-coding each.
    headings += [h.strip() for h in _SECTION_LIKE_CMD_RE.findall(body)]

    # A bold/small-caps run alone on its line, optionally with sizing commands.
    headings += [h.strip() for h in _BOLD_HEADING_RE.findall(body)]

    # A short standalone line in the extracted text.
    for line in plain_text.splitlines():
        stripped = line.strip()
        if stripped and len(stripped) <= 40 and _TEXT_HEADING_RE.match(stripped):
            headings.append(stripped)

    return [h for h in headings if h]


def _has_recognisable_section(plain_text: str, latex: str) -> bool:
    """
    Last-resort check that *some* standard section name is present anywhere.

    Used only to suppress a false "no section headings" alarm when a template
    wraps its headings in markup we failed to recognise. Deliberately biased
    toward staying quiet: crying wolf on a well-built résumé costs more than
    occasionally missing a genuinely header-less one.
    """
    for group in re.findall(r"\{([^{}]{2,60})\}", latex):
        if _is_standard_heading(group):
            return True
    for line in plain_text.splitlines():
        if _is_standard_heading(line.strip()[:40]):
            return True
    return False


def _is_standard_heading(header: str) -> bool:
    """True if a heading contains a section name parsers commonly recognise."""
    cleaned = re.sub(r"[^a-z\s]", " ", header.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned in _STANDARD_SECTION_WORDS:
        return True
    return any(word in cleaned for word in _STANDARD_SECTION_WORDS)


def _extract_skills_body(latex: str) -> str:
    """Return the text between a Skills heading and the next section heading."""
    match = _SKILLS_SECTION_RE.search(latex)
    if not match:
        return ""
    rest = latex[match.end():]
    next_section = _SECTION_CMD_RE.search(rest)
    return rest[: next_section.start()] if next_section else rest


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

        # 2. Detect structural issues this specific ATS is known to choke on
        detected_issue_types = self._detect_issues(latex_content, profile["issues"])

        # 2b. Detect universal document-quality problems. Run against the
        # UNDISTORTED extraction: distortions simulate the parser mangling the
        # document, and reporting on that would blame the author for the
        # parser's behaviour.
        quality_issue_types = _detect_quality_issues(plain_text, latex_content)

        # 3. Apply distortions for poor-tier parsers
        if profile["tier"] == "poor":
            plain_text = _apply_poor_tier_distortions(plain_text, detected_issue_types)

        # 4. Build issue entries with approximate line ranges
        issues = self._build_issue_entries(latex_content, detected_issue_types)
        issues.extend(self._build_quality_entries(latex_content, quality_issue_types))

        # 5. Compute score
        score = self._compute_score(profile, detected_issue_types, quality_issue_types)

        # 6. Build recommendations
        recommendations = self._build_recommendations(
            detected_issue_types, profile["tier"], quality_issue_types
        )

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

    def _build_quality_entries(
        self, latex: str, quality_issue_types: List[str]
    ) -> List[IssueEntry]:
        """Build IssueEntry objects for the universal document-quality checks."""
        entries: List[IssueEntry] = []
        for issue_type in quality_issue_types:
            meta = _QUALITY_META.get(issue_type, {})
            entries.append(
                IssueEntry(
                    type=issue_type,
                    severity=meta.get("severity", "medium"),
                    description=meta.get("description", ""),
                    # These are document-wide properties (a missing header, a
                    # date column) rather than a single offending construct, so
                    # there is no honest single line to point at.
                    line_range="",
                )
            )
        return entries

    def _compute_score(
        self,
        profile: dict,
        detected_issue_types: List[str],
        quality_issue_types: Optional[List[str]] = None,
    ) -> int:
        """
        Score formula:
          - Start with a tier base: good=90, medium=70, poor=50
          - Deduct per detected ATS issue: high=-15, medium=-8, low=-4
          - Deduct per document-quality issue at HALF weight, because these are
            author-fixable construction problems rather than "this parser will
            definitely mangle it".
          - Deduct NOTHING for "suggestion"-severity findings. They are surfaced
            as advice only, mirroring Textkernel's own Suggested grade.
          - Clamp to [0, 100]
        """
        tier_base = {"good": 90, "medium": 70, "poor": 50}
        score = tier_base.get(profile["tier"], 60)

        severity_penalty = {"high": 15, "medium": 8, "low": 4}
        for issue_type in detected_issue_types:
            meta = _ISSUE_META.get(issue_type, {})
            severity = meta.get("severity", "medium")
            score -= severity_penalty.get(severity, 8)

        # "suggestion" is deliberately absent from severity_penalty: Textkernel
        # grades codes 112 and 151 as Suggested, not defects, and docking points
        # for a stylistic preference is exactly the score theatre we argue
        # against elsewhere. Suggestions are reported, never scored.
        for issue_type in quality_issue_types or []:
            meta = _QUALITY_META.get(issue_type, {})
            severity = meta.get("severity", "medium")
            score -= severity_penalty.get(severity, 0) // 2

        return max(0, min(100, score))

    def _build_recommendations(
        self,
        detected_issue_types: List[str],
        tier: str,
        quality_issue_types: Optional[List[str]] = None,
    ) -> List[str]:
        """Combine issue-specific + quality + tier-generic advice (deduped, ranked)."""
        seen: set = set()
        recs: List[str] = []

        # Issue-specific first (most actionable)
        for issue_type in detected_issue_types:
            rec = _ISSUE_RECOMMENDATIONS.get(issue_type, "")
            if rec and rec not in seen:
                recs.append(rec)
                seen.add(rec)

        # Document-quality advice next: also concrete, and applies everywhere.
        # Ordered by severity so the fatal-class findings lead.
        _rank = {"high": 0, "medium": 1, "low": 2, "suggestion": 3}
        for issue_type in sorted(
            quality_issue_types or [],
            key=lambda t: _rank.get(_QUALITY_META.get(t, {}).get("severity", "medium"), 1),
        ):
            rec = _QUALITY_RECOMMENDATIONS.get(issue_type, "")
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
