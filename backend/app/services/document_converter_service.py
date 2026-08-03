"""
Document Converter Service - Builds LLM prompts for converting extracted resume
content to LaTeX. Uses hybrid approach: structured extraction + raw text.
"""
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

ALLOWED_SOURCE_PLATFORMS = {"kickresume", "resumeio", "novoresume"}

# Per-platform supplemental instructions injected into the generic system prompt
_PLATFORM_HINTS: dict[str, str] = {
    "kickresume": (
        "NOTE — This resume was exported from Kickresume. "
        "Kickresume stores skills in nested categories (e.g. {\"Programming\": [\"Python\", \"Go\"]}); "
        "flatten them into a single \\section*{Skills} grouped list. "
        "'Summary' and 'Objective' fields may both appear — prefer 'Summary', discard 'Objective' if redundant."
    ),
    "resumeio": (
        "NOTE — This resume was exported from Resume.io. "
        "Resume.io uses 'position' instead of 'title' for job roles; "
        "map 'position' → job title in Experience entries. "
        "Dates may be stored as ISO strings (2022-01) — convert to 'Jan 2022' format."
    ),
    "novoresume": (
        "NOTE — This resume was exported from Novoresume. "
        "Novoresume stores dates as 'YYYY/MM' (e.g. 2021/03) — convert to 'Month YYYY' (e.g. Mar 2021). "
        "Skill proficiency levels (1-5 stars) should be omitted from LaTeX output."
    ),
}

LINKEDIN_SYSTEM_PROMPT = """You are parsing a LinkedIn profile PDF export. LinkedIn PDFs follow a strict structure:
- Name and headline at top
- "About" section (summary)
- "Experience" section: each entry has Company, Title, Dates (Month Year – Month Year or Present), Location, Description bullets
- "Education" section: Institution, Degree, Field, Dates, Activities
- "Skills" section: list of skills with endorsement counts
- "Certifications": Name, Issuing org, Date
- "Languages": Language, Proficiency level
- "Recommendations": ignore these (not part of resume)
- "Honors & Awards", "Publications", "Projects" (if present)

Map these to LaTeX resume sections:
- Experience → \\section{Experience} with \\resumeSubheading{Company}{Dates}{Title}{Location} (or equivalent \\textbf / \\textit layout)
- Education → \\section{Education} similarly
- Skills → \\section{Skills} as comma-separated or grouped list
- Certifications → \\section{Certifications}
- Languages → add to Skills section

Use \\documentclass[11pt,letterpaper]{article} with geometry, enumitem, titlesec, fontenc (T1), inputenc (utf8), hyperref packages.
Set margins: geometry{left=0.75in, right=0.75in, top=0.75in, bottom=0.75in}.

IMPORTANT:
- Preserve all dates exactly as written
- Keep all bullet points verbatim (improve formatting but not content)
- Omit the Recommendations section entirely
- Return ONLY valid compilable LaTeX code — no markdown, no explanations, no code fences"""



# gpt-4o-mini has a 128k-token context and the conversion asks for at most 4096
# output tokens, so the input budget here is bounded by cost and abuse, not by
# the model. The previous 4000-CHARACTER cap was far below both: a one-page
# resume is ~1000 chars but a dense two-page one runs 4000-6000, so those were
# cut mid-sentence. For a PDF that mattered doubly, because PDFParser fills only
# raw_text — the structured-sections block is empty, so this excerpt is the ONLY
# content the model receives.
#
# 24k chars is roughly 6k tokens: comfortably more than any real resume, still a
# hard bound on a hostile upload.
RAW_TEXT_CHAR_BUDGET = 24_000


def _clip_raw_text(raw_text: str) -> tuple[str, int]:
    """Clip *raw_text* to the prompt budget, returning (text, chars_dropped).

    Cuts on a line boundary where one is reasonably close to the limit, so the
    excerpt does not end mid-word. Callers surface the dropped count to the model
    (and the log) instead of silently pretending the resume ended there.
    """
    if len(raw_text) <= RAW_TEXT_CHAR_BUDGET:
        return raw_text, 0

    dropped = len(raw_text) - RAW_TEXT_CHAR_BUDGET
    head = raw_text[:RAW_TEXT_CHAR_BUDGET]
    boundary = head.rfind("\n")
    # Only honour the boundary if it is not throwing away a lot of the budget.
    if boundary > RAW_TEXT_CHAR_BUDGET * 0.9:
        dropped += len(head) - boundary
        head = head[:boundary]

    logger.warning(
        "Resume text exceeded the conversion prompt budget: %d chars supplied, "
        "%d dropped. The generated LaTeX will be missing content.",
        len(head),
        dropped,
    )
    return head, dropped

class DocumentConverterService:
    """Service for converting parsed resume data to LaTeX via LLM."""

    def build_conversion_prompt(
        self,
        structure: dict,
        source_format: str,
        source_hint: Optional[str] = None,
        source_platform: Optional[str] = None,
    ) -> List[Dict]:
        """
        Build LLM messages for converting parsed resume structure to LaTeX.

        Args:
            structure: ParsedResume.to_dict() output
            source_format: Original file format (e.g., 'pdf', 'docx')

        Returns:
            List of message dicts for OpenAI chat completions
        """
        contact = structure.get('contact') or {}
        raw_text, truncated_chars = _clip_raw_text(structure.get('raw_text') or '')

        # Build sections summary
        sections_text = self._format_sections(structure)

        # Build metadata context
        section_hints = []
        metadata = structure.get('metadata') or {}
        if metadata.get('section_hints'):
            section_hints = metadata['section_hints']

        if source_hint == "linkedin":
            system = LINKEDIN_SYSTEM_PROMPT
        else:
            system = (
                "You are a professional LaTeX resume generator. "
                "Convert the provided resume content into a complete, compilable LaTeX document.\n"
                "RULES:\n"
                "1. Use \\documentclass[11pt,letterpaper]{article}\n"
                "2. Use these packages: geometry, enumitem, titlesec, fontenc (T1), inputenc (utf8), hyperref, xcolor\n"
                "3. Set margins: geometry{left=0.75in, right=0.75in, top=0.75in, bottom=0.75in}\n"
                "4. Preserve ALL dates, companies, job titles, and achievements EXACTLY as given\n"
                "5. Organize sections in order: Contact Info, Summary/Objective (if present), "
                "Experience, Education, Skills, Projects, Certifications, Awards, Other\n"
                "6. Use \\section*{} for section headings with a \\hrule underneath\n"
                "7. Use itemize environments with \\item for bullet points\n"
                "8. Include \\href{mailto:email}{email} for email addresses\n"
                "9. Return ONLY valid compilable LaTeX code — no markdown, no explanations, no code fences"
            )
            # Append platform-specific hints when source is a known resume builder
            if source_platform and source_platform in _PLATFORM_HINTS:
                system += "\n\n" + _PLATFORM_HINTS[source_platform]

        user_parts = [
            f"Convert this {source_format.upper()} resume to professional LaTeX.\n",
            "=== EXTRACTED CONTACT INFO ===",
            f"Name: {contact.get('name') or 'N/A'}",
            f"Email: {contact.get('email') or ''}",
            f"Phone: {contact.get('phone') or ''}",
            f"LinkedIn: {contact.get('linkedin') or ''}",
            f"GitHub: {contact.get('github') or ''}",
            f"Website: {contact.get('website') or ''}",
            "",
        ]

        if section_hints:
            user_parts.extend([
                "=== DETECTED SECTIONS ===",
                ", ".join(section_hints),
                "",
            ])

        if sections_text:
            user_parts.extend([
                "=== STRUCTURED CONTENT ===",
                sections_text,
                "",
            ])

        user_parts.extend([
            "=== FULL RAW TEXT ===",
            raw_text,
        ])

        # Tell the model the input is incomplete rather than letting it treat a
        # mid-sentence cut as the end of the resume and invent a tidy ending.
        if truncated_chars:
            user_parts.extend([
                "",
                f"[NOTE: the resume was longer than this excerpt and {truncated_chars} "
                "characters were omitted. Convert only what is shown above; do not "
                "invent content to fill the gap.]",
            ])

        user = "\n".join(user_parts)

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _format_sections(self, structure: dict) -> str:
        """Format structured resume data as readable text."""
        lines = []

        # Summary
        if structure.get('summary'):
            lines.extend(["SUMMARY:", structure['summary'], ""])

        # Experience
        exp_list = structure.get('experience') or []
        if exp_list:
            lines.append("EXPERIENCE:")
            for exp in exp_list:
                if isinstance(exp, dict):
                    title = exp.get('title', '')
                    company = exp.get('company', '')
                    start = exp.get('start_date', '')
                    end = exp.get('end_date', 'Present') if not exp.get('current') else 'Present'
                    lines.append(f"  {title} at {company} ({start} - {end})")
                    for desc in (exp.get('description') or []):
                        lines.append(f"    - {desc}")
            lines.append("")

        # Education
        edu_list = structure.get('education') or []
        if edu_list:
            lines.append("EDUCATION:")
            for edu in edu_list:
                if isinstance(edu, dict):
                    degree = edu.get('degree', '')
                    inst = edu.get('institution', '')
                    grad = edu.get('graduation_date', '')
                    lines.append(f"  {degree} - {inst} ({grad})")
            lines.append("")

        # Skills
        skills = structure.get('skills') or []
        if skills:
            lines.append(f"SKILLS: {', '.join(skills[:50])}")
            lines.append("")

        # Projects
        proj_list = structure.get('projects') or []
        if proj_list:
            lines.append("PROJECTS:")
            for proj in proj_list:
                if isinstance(proj, dict):
                    lines.append(f"  {proj.get('name', '')}: {proj.get('description', '')}")
            lines.append("")

        return "\n".join(lines)

    def validate_latex_output(self, latex: str) -> tuple[bool, str]:
        """Validate that LLM output is valid LaTeX."""
        required = ['\\documentclass', '\\begin{document}', '\\end{document}']
        for req in required:
            if req not in latex:
                return False, f"Missing required LaTeX element: {req}"
        return True, ""

    def clean_latex_output(self, raw_output: str) -> str:
        """Strip markdown code fences and clean up LLM output."""
        text = raw_output.strip()
        # Remove ```latex ... ``` or ``` ... ``` fences
        text = re.sub(r'^```(?:latex|tex)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
        return text.strip()


document_converter_service = DocumentConverterService()
