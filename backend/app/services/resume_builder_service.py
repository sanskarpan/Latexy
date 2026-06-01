"""Structured resume builder service."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from ..parsers.base_parser import ParsedResume

SUPPORTED_BUILDER_CATEGORIES = frozenset(
    {"ats_safe", "minimal", "software_engineering", "executive", "graduate"}
)


class BuilderBasics(BaseModel):
    name: str = ""
    label: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    website: str = ""
    linkedin: str = ""
    github: str = ""
    summary: str = ""


class BuilderExperienceEntry(BaseModel):
    id: str
    title: str = ""
    company: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    current: bool = False
    summary: str = ""
    bullets: List[str] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)


class BuilderEducationEntry(BaseModel):
    id: str
    institution: str = ""
    degree: str = ""
    field: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    gpa: str = ""
    highlights: List[str] = Field(default_factory=list)


class BuilderProjectEntry(BaseModel):
    id: str
    name: str = ""
    role: str = ""
    url: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""
    bullets: List[str] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)


class BuilderSkillGroup(BaseModel):
    id: str
    name: str = ""
    keywords: List[str] = Field(default_factory=list)


class BuilderCertificationEntry(BaseModel):
    id: str
    name: str = ""
    issuer: str = ""
    date: str = ""
    url: str = ""


class BuilderNamedEntry(BaseModel):
    id: str
    name: str = ""
    detail: str = ""


class StructuredResume(BaseModel):
    basics: BuilderBasics = Field(default_factory=BuilderBasics)
    experience: List[BuilderExperienceEntry] = Field(default_factory=list)
    education: List[BuilderEducationEntry] = Field(default_factory=list)
    projects: List[BuilderProjectEntry] = Field(default_factory=list)
    skills: List[BuilderSkillGroup] = Field(default_factory=list)
    certifications: List[BuilderCertificationEntry] = Field(default_factory=list)
    awards: List[BuilderNamedEntry] = Field(default_factory=list)
    languages: List[BuilderNamedEntry] = Field(default_factory=list)
    interests: List[BuilderNamedEntry] = Field(default_factory=list)
    section_order: List[str] = Field(
        default_factory=lambda: [
            "summary",
            "experience",
            "education",
            "skills",
            "projects",
            "certifications",
            "awards",
            "languages",
            "interests",
        ]
    )
    hidden_sections: List[str] = Field(default_factory=list)

    @field_validator("section_order")
    @classmethod
    def validate_section_order(cls, v: List[str]) -> List[str]:
        allowed = {
            "summary",
            "experience",
            "education",
            "skills",
            "projects",
            "certifications",
            "awards",
            "languages",
            "interests",
        }
        seen: list[str] = []
        for section in v:
            if section in allowed and section not in seen:
                seen.append(section)
        for section in allowed:
            if section not in seen:
                seen.append(section)
        return seen

    @field_validator("hidden_sections")
    @classmethod
    def validate_hidden_sections(cls, v: List[str]) -> List[str]:
        return [section for section in v if section]


class BuilderMetrics(BaseModel):
    completeness_score: int
    page_estimate: int
    warnings: List[str] = Field(default_factory=list)
    missing_sections: List[str] = Field(default_factory=list)


class BuilderRenderResult(BaseModel):
    latex_content: str
    template_family: str
    metrics: BuilderMetrics


class ResumeBuilderService:
    _escape_table = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }

    def empty_document(self) -> Dict[str, Any]:
        return StructuredResume().model_dump()

    def normalize(self, raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        data = StructuredResume.model_validate(raw or {}).model_dump()
        return data

    def from_parsed_resume(self, parsed: ParsedResume) -> Dict[str, Any]:
        basics = BuilderBasics(
            name=parsed.contact.name or "",
            email=parsed.contact.email or "",
            phone=parsed.contact.phone or "",
            location=parsed.contact.location or parsed.contact.address or "",
            website=parsed.contact.website or "",
            linkedin=parsed.contact.linkedin or "",
            github=parsed.contact.github or "",
            summary=parsed.summary or parsed.objective or "",
        )
        structured = StructuredResume(
            basics=basics,
            experience=[
                BuilderExperienceEntry(
                    id=f"exp-{idx + 1}",
                    title=item.title,
                    company=item.company,
                    location=item.location or "",
                    start_date=item.start_date or "",
                    end_date=item.end_date or "",
                    current=item.current,
                    bullets=list(item.description or []),
                    technologies=list(item.technologies or []),
                )
                for idx, item in enumerate(parsed.experience)
            ],
            education=[
                BuilderEducationEntry(
                    id=f"edu-{idx + 1}",
                    institution=item.institution,
                    degree=item.degree,
                    field="",
                    location=item.location or "",
                    end_date=item.graduation_date or "",
                    gpa=item.gpa or "",
                    highlights=[*item.honors, *item.courses],
                )
                for idx, item in enumerate(parsed.education)
            ],
            projects=[
                BuilderProjectEntry(
                    id=f"proj-{idx + 1}",
                    name=item.name,
                    url=item.url or "",
                    start_date=item.start_date or "",
                    end_date=item.end_date or "",
                    description=item.description,
                    technologies=list(item.technologies or []),
                )
                for idx, item in enumerate(parsed.projects)
            ],
            skills=self._skills_from_parsed(parsed),
            certifications=[
                BuilderCertificationEntry(
                    id=f"cert-{idx + 1}",
                    name=item.name,
                    issuer=item.issuer,
                    date=item.date or "",
                    url=item.url or "",
                )
                for idx, item in enumerate(parsed.certifications)
            ],
            awards=[
                BuilderNamedEntry(id=f"award-{idx + 1}", name=award)
                for idx, award in enumerate(parsed.awards)
            ],
            languages=[
                BuilderNamedEntry(
                    id=f"lang-{idx + 1}",
                    name=item.language,
                    detail=item.proficiency or "",
                )
                for idx, item in enumerate(parsed.languages)
            ],
            interests=[
                BuilderNamedEntry(id=f"interest-{idx + 1}", name=item)
                for idx, item in enumerate(parsed.interests)
            ],
        )
        if parsed.contact.name and not basics.label and parsed.experience:
            structured.basics.label = parsed.experience[0].title
        return structured.model_dump()

    def render(self, structured_raw: Dict[str, Any], category: str) -> BuilderRenderResult:
        structured = StructuredResume.model_validate(structured_raw)
        family = self.template_family(category)
        metrics = self._build_metrics(structured)
        latex = self._render_latex(structured, family)
        return BuilderRenderResult(
            latex_content=latex,
            template_family=family,
            metrics=metrics,
        )

    def build_preview(self, structured_raw: Dict[str, Any], category: str) -> Dict[str, Any]:
        structured = StructuredResume.model_validate(structured_raw)
        return {
            "template_family": self.template_family(category),
            "sections": self._preview_sections(structured),
        }

    def template_family(self, category: str) -> str:
        if category == "executive":
            return "executive"
        if category == "ats_safe":
            return "ats"
        if category == "minimal":
            return "minimal"
        return "professional"

    def is_supported_category(self, category: str, document_type: str = "resume") -> bool:
        return document_type == "resume" and category in SUPPORTED_BUILDER_CATEGORIES

    def _skills_from_parsed(self, parsed: ParsedResume) -> List[BuilderSkillGroup]:
        if parsed.skills_categorized:
            return [
                BuilderSkillGroup(id=f"skill-{idx + 1}", name=name, keywords=keywords)
                for idx, (name, keywords) in enumerate(parsed.skills_categorized.items())
            ]
        if parsed.skills:
            return [BuilderSkillGroup(id="skill-1", name="Core Skills", keywords=parsed.skills)]
        return []

    def _build_metrics(self, structured: StructuredResume) -> BuilderMetrics:
        score = 0
        missing: list[str] = []
        warnings: list[str] = []

        if structured.basics.name:
            score += 15
        else:
            missing.append("name")
        if structured.basics.email:
            score += 10
        else:
            missing.append("email")
        if structured.basics.summary.strip():
            score += 10
        else:
            missing.append("summary")
        if structured.experience:
            score += 25
        else:
            missing.append("experience")
        if structured.education:
            score += 15
        else:
            missing.append("education")
        if any(group.keywords for group in structured.skills):
            score += 15
        else:
            missing.append("skills")
        if structured.projects:
            score += 10

        total_lines = 6
        total_lines += len([1 for value in structured.basics.model_dump().values() if isinstance(value, str) and value.strip()])
        total_lines += len(structured.basics.summary.splitlines())
        total_lines += sum(max(3, len(entry.bullets) + 2) for entry in structured.experience)
        total_lines += sum(max(2, len(entry.highlights) + 1) for entry in structured.education)
        total_lines += sum(max(2, len(group.keywords) // 5 + 1) for group in structured.skills)
        total_lines += sum(max(2, len(item.bullets) + 2) for item in structured.projects)
        page_estimate = max(1, (total_lines + 37) // 38)
        if page_estimate > 1:
            warnings.append("Content likely exceeds one page in compact templates.")
        if structured.experience and any(len(entry.bullets) > 6 for entry in structured.experience):
            warnings.append("Some experience entries are dense; consider trimming bullets.")
        if not structured.basics.label:
            warnings.append("Add a headline to improve clarity at the top of the resume.")
        return BuilderMetrics(
            completeness_score=min(score, 100),
            page_estimate=page_estimate,
            warnings=warnings,
            missing_sections=missing,
        )

    def _preview_sections(self, structured: StructuredResume) -> List[Dict[str, Any]]:
        hidden = set(structured.hidden_sections)
        sections: list[dict[str, Any]] = []
        for section in structured.section_order:
            if section in hidden:
                continue
            if section == "summary" and structured.basics.summary.strip():
                sections.append({"key": "summary", "title": "Summary", "items": [structured.basics.summary.strip()]})
            elif section == "experience" and structured.experience:
                sections.append({
                    "key": "experience",
                    "title": "Experience",
                    "items": [
                        {
                            "title": f"{item.title} — {item.company}".strip(" —"),
                            "meta": self._join_meta(item.location, self._date_range(item.start_date, item.end_date, item.current)),
                            "bullets": [b for b in item.bullets if b.strip()],
                        }
                        for item in structured.experience
                    ],
                })
            elif section == "education" and structured.education:
                sections.append({
                    "key": "education",
                    "title": "Education",
                    "items": [
                        {
                            "title": f"{item.degree} — {item.institution}".strip(" —"),
                            "meta": self._join_meta(item.location, self._date_range(item.start_date, item.end_date, False)),
                            "bullets": [b for b in item.highlights if b.strip()],
                        }
                        for item in structured.education
                    ],
                })
            elif section == "skills" and structured.skills:
                sections.append({
                    "key": "skills",
                    "title": "Skills",
                    "items": [{"title": item.name, "meta": ", ".join(item.keywords)} for item in structured.skills if item.keywords],
                })
            elif section == "projects" and structured.projects:
                sections.append({
                    "key": "projects",
                    "title": "Projects",
                    "items": [
                        {
                            "title": item.name,
                            "meta": self._join_meta(item.role, item.url),
                            "bullets": ([item.description] if item.description else []) + [b for b in item.bullets if b.strip()],
                        }
                        for item in structured.projects
                    ],
                })
            elif section == "certifications" and structured.certifications:
                sections.append({
                    "key": "certifications",
                    "title": "Certifications",
                    "items": [{"title": item.name, "meta": self._join_meta(item.issuer, item.date)} for item in structured.certifications],
                })
            elif section == "awards" and structured.awards:
                sections.append({
                    "key": "awards",
                    "title": "Awards",
                    "items": [{"title": item.name, "meta": item.detail} for item in structured.awards if item.name or item.detail],
                })
            elif section == "languages" and structured.languages:
                sections.append({
                    "key": "languages",
                    "title": "Languages",
                    "items": [{"title": item.name, "meta": item.detail} for item in structured.languages if item.name or item.detail],
                })
            elif section == "interests" and structured.interests:
                sections.append({
                    "key": "interests",
                    "title": "Interests",
                    "items": [{"title": item.name, "meta": item.detail} for item in structured.interests if item.name or item.detail],
                })
        return sections

    def _render_latex(self, structured: StructuredResume, family: str) -> str:
        hidden = set(structured.hidden_sections)
        header = self._render_header(structured.basics, family)
        body: list[str] = [header]

        for section in structured.section_order:
            if section in hidden:
                continue
            rendered = ""
            if section == "summary" and structured.basics.summary.strip():
                rendered = self._section_block("Summary", [self._escape(structured.basics.summary.strip())], family)
            elif section == "experience" and structured.experience:
                rendered = self._experience_section(structured.experience, family)
            elif section == "education" and structured.education:
                rendered = self._education_section(structured.education, family)
            elif section == "skills" and structured.skills:
                rendered = self._skills_section(structured.skills, family)
            elif section == "projects" and structured.projects:
                rendered = self._projects_section(structured.projects, family)
            elif section == "certifications" and structured.certifications:
                rendered = self._named_list_section(
                    "Certifications",
                    [self._join_meta(item.name, item.issuer, item.date) for item in structured.certifications],
                    family,
                )
            elif section == "awards" and structured.awards:
                rendered = self._named_list_section(
                    "Awards",
                    [self._join_meta(item.name, item.detail) for item in structured.awards],
                    family,
                )
            elif section == "languages" and structured.languages:
                rendered = self._named_list_section(
                    "Languages",
                    [self._join_meta(item.name, item.detail) for item in structured.languages],
                    family,
                )
            elif section == "interests" and structured.interests:
                rendered = self._named_list_section(
                    "Interests",
                    [self._join_meta(item.name, item.detail) for item in structured.interests],
                    family,
                )
            if rendered:
                body.append(rendered)

        document = [
            r"\documentclass[11pt,letterpaper]{article}",
            r"\usepackage[margin=0.65in]{geometry}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage{enumitem}",
            r"\usepackage[hidelinks]{hyperref}",
            r"\usepackage{xcolor}",
            r"\setlist[itemize]{leftmargin=1.2em, itemsep=0.15em, topsep=0.15em}",
            r"\pagestyle{empty}",
            r"\setlength{\parindent}{0pt}",
            r"\begin{document}",
            *body,
            r"\end{document}",
        ]
        return "\n".join(document)

    def _render_header(self, basics: BuilderBasics, family: str) -> str:
        name = self._escape(basics.name or "Your Name")
        label = self._escape(basics.label)
        parts = [part for part in [basics.email, basics.phone, basics.location, basics.website, basics.linkedin, basics.github] if part]
        escaped_parts = [self._escape(part) for part in parts]
        if family == "executive":
            lines = [
                rf"{{\Huge\bfseries {name}}}\\[4pt]",
                rf"{{\large {label}}}\\[6pt]" if label else "",
                r"\color{gray}",
                r" \quad $|$ \quad ".join(escaped_parts) + r"\\[2pt]" if escaped_parts else "",
                r"\color{black}",
            ]
            return "\n".join(line for line in lines if line)
        if family == "ats":
            lines = [rf"{{\Large\textbf{{{name}}}}}\\[2pt]"]
            if label:
                lines.append(self._escape(label) + r"\\[2pt]")
            if escaped_parts:
                lines.append(r" \quad | \quad ".join(escaped_parts) + r"\\[4pt]")
            return "\n".join(lines)
        lines = [
            r"\begin{center}",
            rf"{{\LARGE\textbf{{{name}}}}}\\[2pt]",
            rf"{{\small {label}}}\\[2pt]" if label else "",
            r" \quad • \quad ".join(escaped_parts) + r"\\" if escaped_parts else "",
            r"\end{center}",
        ]
        return "\n".join(line for line in lines if line)

    def _section_block(self, title: str, lines: List[str], family: str) -> str:
        heading = self._section_heading(title, family)
        return "\n".join([heading, *lines, ""])

    def _section_heading(self, title: str, family: str) -> str:
        escaped = self._escape(title)
        if family == "executive":
            return rf"\vspace{{0.7em}}\textcolor{{gray}}{{\textbf{{{escaped}}}}}\\[-0.3em]\hrule\vspace{{0.35em}}"
        return rf"\section*{{{escaped}}}\vspace{{-0.4em}}\hrule\vspace{{0.25em}}"

    def _experience_section(self, items: List[BuilderExperienceEntry], family: str) -> str:
        lines = [self._section_heading("Experience", family)]
        for item in items:
            title = self._escape(item.title)
            company = self._escape(item.company)
            date_range = self._escape(self._date_range(item.start_date, item.end_date, item.current))
            location = self._escape(item.location)
            lines.append(rf"\textbf{{{title}}} \hfill {date_range}\\")
            secondary = self._join_meta(company, location)
            if secondary:
                lines.append(rf"\textit{{{self._escape(secondary)}}}\\")
            if item.summary.strip():
                lines.append(self._escape(item.summary.strip()) + r"\\")
            bullets = [bullet for bullet in item.bullets if bullet.strip()]
            if bullets:
                lines.append(r"\begin{itemize}")
                lines.extend(rf"  \item {self._escape(bullet)}" for bullet in bullets)
                lines.append(r"\end{itemize}")
            elif item.technologies:
                lines.append(rf"\textit{{Technologies:}} {self._escape(', '.join(item.technologies))}\\")
            lines.append("")
        return "\n".join(lines)

    def _education_section(self, items: List[BuilderEducationEntry], family: str) -> str:
        lines = [self._section_heading("Education", family)]
        for item in items:
            primary = self._join_meta(item.degree, item.field)
            lines.append(rf"\textbf{{{self._escape(item.institution)}}} \hfill {self._escape(self._date_range(item.start_date, item.end_date, False))}\\")
            if primary:
                lines.append(self._escape(primary) + r"\\")
            detail = self._join_meta(item.location, f"GPA {item.gpa}" if item.gpa else "")
            if detail:
                lines.append(self._escape(detail) + r"\\")
            if item.highlights:
                lines.append(r"\begin{itemize}")
                lines.extend(rf"  \item {self._escape(highlight)}" for highlight in item.highlights if highlight.strip())
                lines.append(r"\end{itemize}")
            lines.append("")
        return "\n".join(lines)

    def _skills_section(self, items: List[BuilderSkillGroup], family: str) -> str:
        lines = [self._section_heading("Skills", family)]
        for group in items:
            if not group.keywords:
                continue
            name = self._escape(group.name or "Skills")
            keywords = self._escape(", ".join(group.keywords))
            lines.append(rf"\textbf{{{name}:}} {keywords}\\")
        lines.append("")
        return "\n".join(lines)

    def _projects_section(self, items: List[BuilderProjectEntry], family: str) -> str:
        lines = [self._section_heading("Projects", family)]
        for item in items:
            lines.append(rf"\textbf{{{self._escape(item.name)}}} \hfill {self._escape(self._date_range(item.start_date, item.end_date, False))}\\")
            secondary = self._join_meta(item.role, item.url)
            if secondary:
                lines.append(self._escape(secondary) + r"\\")
            details = ([item.description] if item.description.strip() else []) + [bullet for bullet in item.bullets if bullet.strip()]
            if details:
                lines.append(r"\begin{itemize}")
                lines.extend(rf"  \item {self._escape(detail)}" for detail in details)
                lines.append(r"\end{itemize}")
            if item.technologies:
                lines.append(rf"\textit{{Technologies:}} {self._escape(', '.join(item.technologies))}\\")
            lines.append("")
        return "\n".join(lines)

    def _named_list_section(self, title: str, entries: List[str], family: str) -> str:
        values = [entry for entry in entries if entry.strip()]
        if not values:
            return ""
        lines = [self._section_heading(title, family), r"\begin{itemize}"]
        lines.extend(rf"  \item {self._escape(entry)}" for entry in values)
        lines.append(r"\end{itemize}")
        lines.append("")
        return "\n".join(lines)

    def _date_range(self, start_date: str, end_date: str, current: bool) -> str:
        if start_date and (end_date or current):
            return f"{start_date} - {'Present' if current else end_date}"
        return start_date or end_date or ""

    def _join_meta(self, *parts: str) -> str:
        cleaned = [part.strip() for part in parts if part and part.strip()]
        return " | ".join(cleaned)

    def _escape(self, text: str) -> str:
        if not text:
            return ""
        escaped = text
        for src, target in self._escape_table.items():
            escaped = escaped.replace(src, target)
        escaped = re.sub(r"\s+", " ", escaped)
        return escaped.strip()


resume_builder_service = ResumeBuilderService()
