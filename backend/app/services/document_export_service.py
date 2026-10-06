"""
Document Export Service - Converts LaTeX resume content to other formats.
All conversions are rule-based (no LLM), synchronous, and fast (<200ms).
"""
import html as _html
import io
import logging
import re as _stdlib_re
import zipfile
from typing import Any, Dict, List, Tuple
from xml.etree import ElementTree as ET

from ..utils import safe_regex as re

logger = logging.getLogger(__name__)


class DocumentExportService:
    """Service for exporting LaTeX resumes to other file formats."""

    _INLINE_MD_RE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\t)")

    def _linearize_resume_layout(self, text: str) -> str:
        """Collapse common multi-column layout helpers into a single reading order."""
        text = re.sub(r"\\begin\{multicols\}\{[^}]+\}", "", text)
        text = re.sub(r"\\end\{multicols\}", "", text)
        text = re.sub(r"\\columnbreak\b", "\n", text)
        text = re.sub(r"\\begin\{minipage\}\{[^}]+\}", "", text)
        text = re.sub(r"\\end\{minipage\}", "", text)
        return text

    def _replace_resume_macros(self, text: str) -> str:
        """Expand popular resume macros into markdown-friendly text before generic stripping."""
        text = self._linearize_resume_layout(text)

        def _resume_subheading(match: re.Match[str]) -> str:
            company, dates, title, location = [g.strip() for g in match.groups()]
            first = f"**{company}**\t{dates}" if dates else f"**{company}**"
            second_parts = [f"*{title}*" if title else "", location]
            second = " — ".join(part for part in second_parts if part)
            return f"\n{first}\n{second}\n"

        def _resume_item(match: re.Match[str]) -> str:
            return f"\n- {match.group(1).strip()}\n"

        def _resume_subitem(match: re.Match[str]) -> str:
            key, value = [g.strip() for g in match.groups()]
            return f"\n- **{key}:** {value}\n"

        def _cv_entry(match: re.Match[str]) -> str:
            year, title, org, location, detail_a, detail_b = [g.strip() for g in match.groups()]
            first = " — ".join(part for part in (title, org) if part)
            if year:
                first = f"**{first}**\t{year}" if first else f"**{year}**"
            else:
                first = f"**{first}**" if first else ""
            lines = [first]
            if location:
                lines.append(location)
            for detail in (detail_a, detail_b):
                if detail:
                    lines.append(f"- {detail}")
            return "\n" + "\n".join(line for line in lines if line) + "\n"

        def _cv_event(match: re.Match[str]) -> str:
            title, org, dates, location = [g.strip() for g in match.groups()]
            first = " — ".join(part for part in (title, org) if part)
            first = f"**{first}**\t{dates}" if dates else f"**{first}**"
            second = location
            return f"\n{first}\n{second}\n" if second else f"\n{first}\n"

        def _job(match: re.Match[str]) -> str:
            company, title, dates, location = [g.strip() for g in match.groups()]
            first = f"**{company}**\t{dates}" if dates else f"**{company}**"
            second = " — ".join(part for part in (title, location) if part)
            return f"\n{first}\n{second}\n" if second else f"\n{first}\n"

        replacements: List[Tuple[str, Any]] = [
            (r"\\resumeSubheading\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}", _resume_subheading),
            (r"\\resumeItem\{([^}]*)\}", _resume_item),
            (r"\\resumeSubItem\{([^}]*)\}\{([^}]*)\}", _resume_subitem),
            (r"\\cventry\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}", _cv_entry),
            (r"\\cvevent\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}", _cv_event),
            (r"\\job\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}", _job),
        ]
        for pattern, repl in replacements:
            text = re.sub(pattern, repl, text)

        text = re.sub(r"\\resumeItemListStart\b", "", text)
        text = re.sub(r"\\resumeItemListEnd\b", "", text)
        return text

    def _add_inline_markdown_runs(self, paragraph: Any, text: str) -> None:
        """Render a tiny subset of markdown markers into python-docx runs."""
        parts = [part for part in self._INLINE_MD_RE.split(text) if part]
        for part in parts:
            if part == "\t":
                paragraph.add_run("\t")
                continue
            run = paragraph.add_run(part)
            if part.startswith("**") and part.endswith("**"):
                run.text = part[2:-2]
                run.bold = True
            elif part.startswith("*") and part.endswith("*"):
                run.text = part[1:-1]
                run.italic = True
            elif part.startswith("`") and part.endswith("`"):
                run.text = part[1:-1]
                run.font.name = "Courier New"

    # ─── Text Extraction ────────────────────────────────────────────────────

    def to_text(self, latex_content: str) -> str:
        """Convert LaTeX to plain text, preserving structure via newlines."""
        # Convert through markdown (which handles LaTeX → structured text),
        # then strip markdown formatting markers.
        md = self.to_markdown(latex_content)

        # Strip markdown heading markers (## → UPPERCASE line)
        def heading_replacer(m):
            level = len(m.group(1))
            title = m.group(2).strip()
            if level == 2:
                return f'\n{title.upper()}\n{"─" * len(title)}'
            return f'\n{title}'

        text = re.sub(r'^(#{1,4})\s+(.+)$', heading_replacer, md, flags=re.MULTILINE)

        # Strip bold/italic markers but keep text
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'`(.+?)`', r'\1', text)
        text = re.sub(r'<u>(.+?)</u>', r'\1', text)

        # Markdown links → text only
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'<(https?://[^>]+)>', r'\1', text)

        # List bullets → •
        text = re.sub(r'^-\s+', '• ', text, flags=re.MULTILINE)

        # Collapse 3+ blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()

    # ─── Markdown ───────────────────────────────────────────────────────────

    def to_markdown(self, latex_content: str) -> str:
        """Convert LaTeX resume to Markdown."""
        text = self._replace_resume_macros(latex_content)

        # Escaped special characters → plain text (before any other processing)
        text = text.replace(r'\%', '%')
        text = text.replace(r'\&', '&')
        text = text.replace(r'\$', '$')
        text = text.replace(r'\#', '#')
        text = text.replace(r'\_', '_')
        text = text.replace(r'\~', '~')
        text = text.replace(r'\^', '^')

        # Remove font size commands inside textbf/textit before processing formatting
        text = re.sub(r'\\(?:Large|large|LARGE|huge|Huge|small|footnotesize|normalsize)\b\s*', '', text)

        # Section headings (must be before generic command removal)
        text = re.sub(r'\\section\*?\{([^}]*)\}', r'\n## \1\n', text)
        text = re.sub(r'\\subsection\*?\{([^}]*)\}', r'\n### \1\n', text)
        text = re.sub(r'\\subsubsection\*?\{([^}]*)\}', r'\n#### \1\n', text)

        # Text formatting (must be before generic removal)
        # Strip inner whitespace so **  Jane  ** → **Jane**
        text = re.sub(r'\\textbf\{\s*([^}]*?)\s*\}', lambda m: f'**{m.group(1).strip()}**', text)
        text = re.sub(r'\\textit\{\s*([^}]*?)\s*\}', lambda m: f'*{m.group(1).strip()}*', text)
        text = re.sub(r'\\emph\{\s*([^}]*?)\s*\}', lambda m: f'*{m.group(1).strip()}*', text)
        text = re.sub(r'\\underline\{\s*([^}]*?)\s*\}', lambda m: f'<u>{m.group(1).strip()}</u>', text)
        text = re.sub(r'\\texttt\{\s*([^}]*?)\s*\}', lambda m: f'`{m.group(1).strip()}`', text)

        # Links (before generic removal)
        text = re.sub(r'\\href\{([^}]*)\}\{([^}]*)\}', r'[\2](\1)', text)
        text = re.sub(r'\\url\{([^}]*)\}', r'<\1>', text)

        # Lists
        text = re.sub(r'\\begin\{itemize\}', '', text)
        text = re.sub(r'\\end\{itemize\}', '', text)
        text = re.sub(r'\\begin\{enumerate\}', '', text)
        text = re.sub(r'\\end\{enumerate\}', '', text)
        text = re.sub(r'[ \t]*\\item\s+', '- ', text)

        # LaTeX line breaks (\\) → actual newline
        text = re.sub(r'\\\\', '\n', text)

        # Horizontal fill → separator, spacing commands → remove
        text = re.sub(r'\\hfill\b', '  —  ', text)
        text = re.sub(r'\\vspace\*?\{[^}]*\}', '', text)
        text = re.sub(r'\\hspace\*?\{[^}]*\}', ' ', text)
        text = re.sub(r'\\noindent\b', '', text)
        text = re.sub(r'\\centering\b', '', text)

        # Em-dash and en-dash
        text = text.replace('---', '—')
        text = text.replace('--', '–')

        # Remove document structure
        text = re.sub(r'\\begin\{document\}', '', text)
        text = re.sub(r'\\end\{document\}', '', text)
        text = re.sub(r'\\documentclass[^\n]*\n?', '', text)
        text = re.sub(r'\\usepackage[^\n]*\n?', '', text)
        text = re.sub(r'\\geometry[^\n]*\n?', '', text)

        # Remove begin/end environments
        text = re.sub(r'\\begin\{[^}]*\}', '', text)
        text = re.sub(r'\\end\{[^}]*\}', '', text)

        # Remove LaTeX command names but KEEP their brace-enclosed arguments.
        # e.g. \resumeSubheading{Company}{Role} → "Company Role"
        # Pattern: strip \cmdname and optional [...] arg, but leave the {...} content.
        text = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?', '', text)
        # Remove lone backslashes
        text = re.sub(r'\\', '', text)

        # Clean up braces, extra whitespace
        text = re.sub(r'[{}]', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        # Clean trailing spaces on lines
        text = re.sub(r' +\n', '\n', text)

        return text.strip()

    # ─── HTML ────────────────────────────────────────────────────────────────

    def to_html(self, latex_content: str) -> str:
        """Convert LaTeX resume to HTML."""
        try:
            import mistune
            md_content = self.to_markdown(latex_content)
            # escape=True renders any raw HTML in the (LaTeX-derived, potentially
            # attacker-controlled) markdown as escaped text instead of passing it
            # through verbatim — preventing stored/reflected XSS via <script>/
            # <img onerror> payloads. Matches the ImportError fallback's guarantee.
            markdown = mistune.create_markdown(escape=True)
            body = markdown(md_content)
        except ImportError:
            # Fallback: basic HTML from text — escape to prevent XSS
            import html as _html
            text = self.to_text(latex_content)
            paragraphs = [f'<p>{_html.escape(p)}</p>' for p in text.split('\n\n') if p.strip()]
            body = '\n'.join(paragraphs)

        return (
            '<!DOCTYPE html>\n'
            '<html lang="en">\n'
            '<head>\n'
            '  <meta charset="UTF-8">\n'
            '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            '  <title>Resume</title>\n'
            '  <style>\n'
            '    body { font-family: Arial, sans-serif; max-width: 800px; margin: 2rem auto; '
            'padding: 0 1rem; line-height: 1.6; color: #333; }\n'
            '    h2 { border-bottom: 1px solid #ccc; padding-bottom: 0.3rem; margin-top: 2rem; }\n'
            '    ul { margin: 0.5rem 0; padding-left: 1.5rem; }\n'
            '    a { color: #0066cc; }\n'
            '  </style>\n'
            '</head>\n'
            '<body>\n'
            f'{body}\n'
            '</body>\n'
            '</html>'
        )

    # ─── JSON Resume ─────────────────────────────────────────────────────────

    def _to_plain_text(self, latex_content: str) -> str:
        """Internal: plain text without decorative section rulers, for structured parsing."""
        md = self.to_markdown(latex_content)
        # Strip markdown markers, keep text
        text = re.sub(r'^#{1,4}\s+(.+)$', r'\1', md, flags=re.MULTILINE)
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'`(.+?)`', r'\1', text)
        text = re.sub(r'<u>(.+?)</u>', r'\1', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'^-\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def to_json(self, latex_content: str) -> Dict[str, Any]:
        """Convert LaTeX resume to JSON Resume schema (https://jsonresume.org/schema)."""
        text = self._to_plain_text(latex_content)
        lines = [line.strip() for line in text.split('\n') if line.strip()]

        # Extract basic contact info
        from ..utils import safe_regex as _re
        email = ''
        phone = ''
        name = lines[0] if lines else ''

        email_match = _re.search(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', text)
        if email_match:
            email = email_match.group(0)

        phone_match = _re.search(r'(?:\+?1[-.\s]?)?(?:\(?[2-9]\d{2}\)?[-.\s]?)[2-9]\d{2}[-.\s]?\d{4}', text)
        if phone_match:
            phone = phone_match.group(0)

        linkedin_match = _re.search(r'linkedin\.com/in/([a-zA-Z0-9\-]+)', text)
        linkedin_url = f"https://linkedin.com/in/{linkedin_match.group(1)}" if linkedin_match else ''

        github_match = _re.search(r'github\.com/([a-zA-Z0-9\-]+)', text)
        github_url = f"https://github.com/{github_match.group(1)}" if github_match else ''

        # Build section-based content
        SECTION_RE = _re.compile(
            r'^(?:EXPERIENCE|WORK|EDUCATION|SKILLS|PROJECTS|CERTIFICATIONS|'
            r'SUMMARY|OBJECTIVE|AWARDS|PUBLICATIONS)\b',
            _re.IGNORECASE
        )
        current_section = None
        sections: Dict[str, List[str]] = {}
        for line in lines:
            if SECTION_RE.match(line):
                current_section = line.upper().split()[0]
                sections[current_section] = []
            elif current_section:
                sections[current_section].append(line)

        # Skills extraction
        skills_list = []
        if 'SKILLS' in sections:
            skills_text = ' '.join(sections['SKILLS'])
            skills_list = [s.strip() for s in _re.split(r'[,;|•·]', skills_text) if s.strip()]

        result = {
            "$schema": "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json",
            "basics": {
                "name": name,
                "email": email,
                "phone": phone,
                "url": "",
                "summary": ' '.join(sections.get('SUMMARY', sections.get('OBJECTIVE', []))),
                "profiles": [],
            },
            "work": [],
            "education": [],
            "skills": [{"name": s} for s in skills_list[:20]],
            "projects": [],
            "awards": [],
            "certificates": [],
        }

        if linkedin_url:
            result["basics"]["profiles"].append({"network": "LinkedIn", "url": linkedin_url})
        if github_url:
            result["basics"]["profiles"].append({"network": "GitHub", "url": github_url})

        return result

    # ─── Canva (Feature 90A) ─────────────────────────────────────────────────

    # Regex for detecting date-range lines (e.g. "Jan 2020 – May 2023")
    _DATE_RE = re.compile(
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{4})'
        r'[^A-Za-z]*(?:–|--|—|to|–|present)',
        re.IGNORECASE,
    )

    def to_canva(self, latex_content: str) -> dict:
        """
        Convert LaTeX resume to Canva Content Import API format.

        Returns a dict with:
          type: "DESIGN"
          elements: list of CanvaElement dicts
            {type: "HEADING"|"TEXT"|"DIVIDER", text: str, style: dict}
        """
        md = self.to_markdown(latex_content)
        elements: list[dict] = []

        for raw_line in md.split('\n'):
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith('## '):
                # Section heading → HEADING + DIVIDER
                elements.append({
                    "type": "HEADING",
                    "text": line[3:].strip(),
                    "style": {"bold": True, "fontSize": 14},
                })
                elements.append({"type": "DIVIDER", "text": "", "style": {}})

            elif line.startswith('### '):
                elements.append({
                    "type": "TEXT",
                    "text": line[4:].strip(),
                    "style": {"bold": True, "fontSize": 11},
                })

            elif line.startswith('- '):
                elements.append({
                    "type": "TEXT",
                    "text": "• " + line[2:].strip(),
                    "style": {"fontSize": 10, "indent": True},
                })

            elif '**' in line:
                # Bold company/role line — check before date regex so that
                # combined lines like "**Acme Corp**  —  **2021–2024**" are
                # rendered bold rather than as a date line.
                clean = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
                clean = re.sub(r'\*(.+?)\*', r'\1', clean)
                elements.append({
                    "type": "TEXT",
                    "text": clean,
                    "style": {"bold": True, "fontSize": 11},
                })

            elif self._DATE_RE.search(line):
                # Date range line (plain text, no bold markers) → smaller italic text
                clean = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
                clean = re.sub(r'\*(.+?)\*', r'\1', clean)
                elements.append({
                    "type": "TEXT",
                    "text": clean,
                    "style": {"italic": True, "fontSize": 9},
                })

            else:
                clean = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
                clean = re.sub(r'\*(.+?)\*', r'\1', clean)
                if clean:
                    elements.append({
                        "type": "TEXT",
                        "text": clean,
                        "style": {"fontSize": 10},
                    })

        return {"type": "DESIGN", "elements": elements}

    # ─── Figma (Feature 90B) ─────────────────────────────────────────────────

    def to_figma(self, latex_content: str) -> dict:
        """
        Convert LaTeX resume to Figma plugin JSON format.

        Returns a dict with:
          sections: list of {title, entries: [{heading, subheading, date, bullets}]}
        """
        md = self.to_markdown(latex_content)
        lines = md.split('\n')

        sections: list[dict] = []
        current_section: dict | None = None
        current_entry: dict | None = None

        def _flush_entry():
            if current_entry and current_section is not None:
                # Only add if entry has any real content
                if any([
                    current_entry["heading"],
                    current_entry["subheading"],
                    current_entry["date"],
                    current_entry["bullets"],
                ]):
                    current_section["entries"].append(current_entry)

        def _new_entry() -> dict:
            return {"heading": "", "subheading": "", "date": "", "bullets": []}

        for raw_line in lines:
            line = raw_line.strip()

            if line.startswith('## '):
                _flush_entry()
                current_entry = None
                current_section = {"title": line[3:].strip(), "entries": []}
                sections.append(current_section)

            elif current_section is None:
                continue  # Skip preamble before first section

            elif line.startswith('### '):
                _flush_entry()
                current_entry = _new_entry()
                current_entry["heading"] = line[4:].strip()

            elif line.startswith('- '):
                if current_entry is None:
                    current_entry = _new_entry()
                current_entry["bullets"].append(line[2:].strip())

            elif '**' in line and line.count('**') >= 2:
                # Bold line → heading (company) or subheading (role).
                # Must come before date regex: combined lines like
                # "**Acme Corp**  —  **2021–2024**" should populate heading,
                # not date.
                if current_entry is None:
                    current_entry = _new_entry()
                clean = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
                clean = re.sub(r'\*(.+?)\*', r'\1', clean)
                if not current_entry["heading"]:
                    current_entry["heading"] = clean
                else:
                    current_entry["subheading"] = clean

            elif self._DATE_RE.search(line):
                # Plain-text date range (no bold markers)
                if current_entry is None:
                    current_entry = _new_entry()
                clean = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
                clean = re.sub(r'\*(.+?)\*', r'\1', clean)
                current_entry["date"] = clean

            elif line and not line.startswith('#'):
                if current_entry is None:
                    current_entry = _new_entry()
                clean = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
                clean = re.sub(r'\*(.+?)\*', r'\1', clean)
                if not current_entry["subheading"]:
                    current_entry["subheading"] = clean

        _flush_entry()
        return {"sections": sections}

    # ─── YAML ────────────────────────────────────────────────────────────────

    def to_yaml(self, latex_content: str) -> str:
        """Convert LaTeX resume to YAML (JSON Resume schema)."""
        import yaml
        data = self.to_json(latex_content)
        return yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)

    # ─── XML ─────────────────────────────────────────────────────────────────

    def to_xml(self, latex_content: str) -> str:
        """Convert LaTeX resume to XML."""
        data = self.to_json(latex_content)
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<resume>']

        def dict_to_xml(d: Any, indent: int = 2) -> List[str]:
            result = []
            pad = ' ' * indent
            if isinstance(d, dict):
                for k, v in d.items():
                    tag = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(k))
                    if isinstance(v, (dict, list)):
                        result.append(f'{pad}<{tag}>')
                        result.extend(dict_to_xml(v, indent + 2))
                        result.append(f'{pad}</{tag}>')
                    else:
                        safe_v = str(v).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        result.append(f'{pad}<{tag}>{safe_v}</{tag}>')
            elif isinstance(d, list):
                for i, item in enumerate(d):
                    result.append(f'{pad}<item>')
                    result.extend(dict_to_xml(item, indent + 2))
                    result.append(f'{pad}</item>')
            return result

        lines.extend(dict_to_xml(data))
        lines.append('</resume>')
        return '\n'.join(lines)

    # ─── ePub / ODF / DocBook (B50c) ───────────────────────────────────────

    def _structured_markdown_blocks(self, latex_content: str) -> list[tuple[str, str]]:
        """Build a bounded block model from the service's Markdown output."""
        blocks: list[tuple[str, str]] = []
        paragraph: list[str] = []
        bullets: list[str] = []

        def flush_paragraph() -> None:
            if paragraph:
                blocks.append(("paragraph", " ".join(paragraph).strip()))
                paragraph.clear()

        def flush_bullets() -> None:
            if bullets:
                blocks.append(("list", "\n".join(bullets)))
                bullets.clear()

        for raw in self.to_markdown(latex_content).splitlines():
            line = raw.strip()
            if not line:
                flush_paragraph()
                flush_bullets()
            elif line.startswith("#### "):
                flush_paragraph()
                flush_bullets()
                blocks.append(("heading4", line[5:].strip()))
            elif line.startswith("### "):
                flush_paragraph()
                flush_bullets()
                blocks.append(("heading3", line[4:].strip()))
            elif line.startswith("## "):
                flush_paragraph()
                flush_bullets()
                blocks.append(("heading2", line[3:].strip()))
            elif line.startswith("# "):
                flush_paragraph()
                flush_bullets()
                blocks.append(("heading1", line[2:].strip()))
            elif line.startswith("- "):
                flush_paragraph()
                bullets.append(line[2:].strip())
            else:
                flush_bullets()
                paragraph.append(line)
        flush_paragraph()
        flush_bullets()
        return [(kind, value) for kind, value in blocks if value]

    @staticmethod
    def _inline_xhtml(value: str) -> str:
        """Escape text before allowing only generated bold/italic markers."""
        escaped = _html.escape(value, quote=False)
        escaped = _stdlib_re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        return _stdlib_re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<em>\1</em>", escaped)

    def to_epub(self, latex_content: str) -> bytes:
        """Create a standards-valid EPUB 3 package containing one XHTML page."""
        blocks = self._structured_markdown_blocks(latex_content)
        title = next((value for kind, value in blocks if kind.startswith("heading")), "Resume")
        body = [f"<h1>{self._inline_xhtml(title)}</h1>"]
        first_heading = True
        for kind, value in blocks:
            if kind.startswith("heading"):
                if first_heading and value == title:
                    first_heading = False
                    continue
                first_heading = False
                level = min(int(kind[-1]) + 1, 6)
                body.append(f"<h{level}>{self._inline_xhtml(value)}</h{level}>")
            elif kind == "list":
                items = "".join(f"<li>{self._inline_xhtml(item)}</li>" for item in value.splitlines())
                body.append(f"<ul>{items}</ul>")
            else:
                body.append(f"<p>{self._inline_xhtml(value)}</p>")
        escaped_title = _html.escape(title, quote=True)
        xhtml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" lang="en">'
            f'<head><title>{escaped_title}</title><meta charset="utf-8"/></head>'
            f'<body>{"".join(body)}</body></html>'
        ).encode("utf-8")
        opf = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/">'
            '<dc:identifier id="book-id">urn:latexy:resume</dc:identifier>'
            f'<dc:title>{escaped_title}</dc:title><dc:language>en</dc:language>'
            '<meta property="dcterms:modified">2000-01-01T00:00:00Z</meta></metadata>'
            '<manifest><item id="content" href="content.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest>'
            '<spine><itemref idref="content"/></spine></package>'
        ).encode("utf-8")
        nav = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
            f'<head><title>{escaped_title}</title></head><body><nav epub:type="toc"><ol>'
            '<li><a href="content.xhtml">Resume</a></li></ol></nav></body></html>'
        ).encode("utf-8")
        container = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            '</rootfiles></container>'
        ).encode("utf-8")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            info = zipfile.ZipInfo("mimetype")
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, "application/epub+zip")
            archive.writestr("META-INF/container.xml", container)
            archive.writestr("OEBPS/content.opf", opf)
            archive.writestr("OEBPS/content.xhtml", xhtml)
            archive.writestr("OEBPS/nav.xhtml", nav)
        return output.getvalue()

    def to_odf(self, latex_content: str) -> bytes:
        """Create a valid ODF text document (ODT) package."""
        ns = {
            "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
            "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
            "manifest": "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0",
        }
        for prefix, uri in ns.items():
            ET.register_namespace(prefix, uri)
        root = ET.Element(f"{{{ns['office']}}}document-content", {f"{{{ns['office']}}}version": "1.3"})
        text_root = ET.SubElement(ET.SubElement(root, f"{{{ns['office']}}}body"), f"{{{ns['office']}}}text")
        for kind, value in self._structured_markdown_blocks(latex_content):
            if kind == "list":
                listing = ET.SubElement(text_root, f"{{{ns['text']}}}list")
                for item in value.splitlines():
                    item_element = ET.SubElement(listing, f"{{{ns['text']}}}list-item")
                    ET.SubElement(item_element, f"{{{ns['text']}}}p").text = item
            else:
                tag = "h" if kind.startswith("heading") else "p"
                element = ET.SubElement(text_root, f"{{{ns['text']}}}{tag}")
                if tag == "h":
                    element.set(f"{{{ns['text']}}}outline-level", str(min(int(kind[-1]), 6)))
                element.text = value
        content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        manifest = ET.Element(f"{{{ns['manifest']}}}manifest", {f"{{{ns['manifest']}}}version": "1.3"})
        ET.SubElement(manifest, f"{{{ns['manifest']}}}file-entry", {f"{{{ns['manifest']}}}full-path": "/", f"{{{ns['manifest']}}}media-type": "application/vnd.oasis.opendocument.text"})
        ET.SubElement(manifest, f"{{{ns['manifest']}}}file-entry", {f"{{{ns['manifest']}}}full-path": "content.xml", f"{{{ns['manifest']}}}media-type": "text/xml"})
        manifest_bytes = ET.tostring(manifest, encoding="utf-8", xml_declaration=True)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            info = zipfile.ZipInfo("mimetype")
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, "application/vnd.oasis.opendocument.text")
            archive.writestr("META-INF/manifest.xml", manifest_bytes)
            archive.writestr("content.xml", content)
        return output.getvalue()

    def to_docbook(self, latex_content: str) -> str:
        """Create DocBook 5 XML, rather than labelling generic XML as DocBook."""
        namespace = "http://docbook.org/ns/docbook"
        ET.register_namespace("", namespace)
        article = ET.Element(f"{{{namespace}}}article", {"version": "5.2"})
        info = ET.SubElement(article, f"{{{namespace}}}info")
        ET.SubElement(info, f"{{{namespace}}}title").text = "Resume"
        current_section: ET.Element | None = None
        for kind, value in self._structured_markdown_blocks(latex_content):
            if kind.startswith("heading"):
                current_section = ET.SubElement(article, f"{{{namespace}}}section")
                ET.SubElement(current_section, f"{{{namespace}}}title").text = value
            elif kind == "list":
                parent = current_section or article
                listing = ET.SubElement(parent, f"{{{namespace}}}itemizedlist")
                for item in value.splitlines():
                    list_item = ET.SubElement(listing, f"{{{namespace}}}listitem")
                    ET.SubElement(list_item, f"{{{namespace}}}para").text = item
            else:
                ET.SubElement(current_section or article, f"{{{namespace}}}para").text = value
        return ET.tostring(article, encoding="unicode", xml_declaration=True)

    # ─── DOCX ────────────────────────────────────────────────────────────────

    def to_docx(self, latex_content: str) -> bytes:
        """Convert LaTeX resume to DOCX format."""
        try:
            from docx import Document
            from docx.shared import Inches, Pt, RGBColor
        except ImportError:
            raise ValueError("python-docx not installed. Run: pip install python-docx")

        doc = Document()

        # Set page margins
        for section in doc.sections:
            section.left_margin = Inches(0.75)
            section.right_margin = Inches(0.75)
            section.top_margin = Inches(0.75)
            section.bottom_margin = Inches(0.75)

        # Remove default empty paragraph
        for para in doc.paragraphs:
            p = para._element
            p.getparent().remove(p)

        # Extract content structure from LaTeX
        md_content = self.to_markdown(latex_content)
        lines = md_content.split('\n')

        for line in lines:
            line = line.rstrip()
            if not line:
                continue
            elif line.startswith('## '):
                # Section heading
                heading_text = line[3:].strip()
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(12)
                run = p.add_run(heading_text.upper())
                run.bold = True
                run.font.size = Pt(12)
                run.font.color.rgb = RGBColor(0, 0, 0)
                # Add underline rule
                p.paragraph_format.border_bottom = True if hasattr(p.paragraph_format, 'border_bottom') else None
                doc.add_paragraph().paragraph_format.space_after = Pt(2)
            elif line.startswith('### '):
                p = doc.add_paragraph()
                self._add_inline_markdown_runs(p, line[4:].strip())
                for run in p.runs:
                    run.bold = True if run.bold is None else run.bold
                    run.font.size = Pt(11)
            elif line.startswith('- '):
                # Bullet point
                p = doc.add_paragraph(style='List Bullet')
                self._add_inline_markdown_runs(p, line[2:].strip())
                p.paragraph_format.space_after = Pt(2)
            elif line.startswith('**') and line.endswith('**'):
                p = doc.add_paragraph()
                self._add_inline_markdown_runs(p, line)
                for run in p.runs:
                    run.bold = True
            else:
                p = doc.add_paragraph()
                self._add_inline_markdown_runs(p, line)
                p.paragraph_format.space_after = Pt(2)

        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()


document_export_service = DocumentExportService()
