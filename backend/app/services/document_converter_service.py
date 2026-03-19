"""
Document Converter Service - Builds LLM prompts for converting extracted resume
content to LaTeX. Uses hybrid approach: structured extraction + raw text.
"""
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

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


class DocumentConverterService:
    """Service for converting parsed resume data to LaTeX via LLM."""

    def build_conversion_prompt(
        self, structure: dict, source_format: str, source_hint: Optional[str] = None
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
        raw_text = (structure.get('raw_text') or '')[:4000]  # cap at 4K chars

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
