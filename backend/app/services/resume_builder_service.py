"""Structured resume builder service."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from ..parsers.base_parser import ParsedResume
from .render_engine.managed_preamble import MANAGED_ENGLISH_PREAMBLE_LINES

SUPPORTED_BUILDER_CATEGORIES = frozenset(
    {"ats_safe", "minimal", "software_engineering", "executive", "graduate"}
)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
SECTION_TITLES = {"summary": "Summary", "experience": "Experience", "education": "Education",
                  "skills": "Skills", "projects": "Projects", "certifications": "Certifications",
                  "awards": "Awards", "languages": "Languages", "interests": "Interests"}


def _safe_identity(value: str, *, fallback: str, max_length: int) -> str:
    """Keep imported IDs usable in version keys without trusting raw input."""
    raw = str(value or "").strip()
    if _SAFE_ID_RE.fullmatch(raw) and len(raw) <= max_length:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    prefix = re.sub(r"[^A-Za-z0-9._:-]+", "-", raw).strip(".-:_")
    prefix = (prefix or fallback)[: max_length - len(digest) - 1].rstrip(".-:_")
    return f"{prefix}-{digest}"


def _bullet_id(entry_id: str, index: int, used: set[str]) -> str:
    slot = f"-bullet-{index}"
    safe_entry = _safe_identity(entry_id, fallback="entry", max_length=max(1, 96 - len(slot)))
    base = f"{safe_entry}{slot}"
    candidate = base
    if candidate in used:
        suffix = hashlib.sha256(f"{entry_id}:{index}".encode("utf-8")).hexdigest()[:10]
        candidate = f"{base[:96 - len(suffix) - 1]}-{suffix}"
    counter = 2
    while candidate in used:
        suffix = f"-{counter}"
        candidate = f"{base[:96 - len(suffix)]}{suffix}"
        counter += 1
    return candidate


def _stable_item_ids(entry_id: str, field: str, items: list[str], existing: list[str]) -> list[str]:
    seen: set[str] = set()
    identities = []
    for index in range(len(items)):
        candidate = existing[index].strip() if index < len(existing) else ""
        if not _SAFE_ID_RE.fullmatch(candidate) or candidate in seen:
            candidate = _bullet_id(entry_id + "-" + field, index, seen)
        seen.add(candidate)
        identities.append(candidate)
    return identities


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
    # Persisted IDs keep element history attached when bullet text changes.
    # Existing documents are backfilled deterministically during validation.
    bullet_ids: List[str] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)
    technology_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_bullet_ids(self) -> "BuilderExperienceEntry":
        seen: set[str] = set()
        ids: list[str] = []
        for index in range(len(self.bullets)):
            candidate = self.bullet_ids[index].strip() if index < len(self.bullet_ids) else ""
            if not _SAFE_ID_RE.fullmatch(candidate) or candidate in seen:
                candidate = _bullet_id(self.id, index, seen)
            seen.add(candidate)
            ids.append(candidate)
        self.bullet_ids = ids
        self.technology_ids = _stable_item_ids(self.id, "technology", self.technologies, self.technology_ids)
        return self


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
    highlight_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_highlight_ids(self) -> "BuilderEducationEntry":
        self.highlight_ids = _stable_item_ids(self.id, "highlight", self.highlights, self.highlight_ids)
        return self


class BuilderProjectEntry(BaseModel):
    id: str
    name: str = ""
    role: str = ""
    url: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""
    bullets: List[str] = Field(default_factory=list)
    bullet_ids: List[str] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)
    technology_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_bullet_ids(self) -> "BuilderProjectEntry":
        seen: set[str] = set()
        ids: list[str] = []
        for index in range(len(self.bullets)):
            candidate = self.bullet_ids[index].strip() if index < len(self.bullet_ids) else ""
            if not _SAFE_ID_RE.fullmatch(candidate) or candidate in seen:
                candidate = _bullet_id(self.id, index, seen)
            seen.add(candidate)
            ids.append(candidate)
        self.bullet_ids = ids
        self.technology_ids = _stable_item_ids(self.id, "technology", self.technologies, self.technology_ids)
        return self


class BuilderSkillGroup(BaseModel):
    id: str
    name: str = ""
    keywords: List[str] = Field(default_factory=list)
    keyword_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_keyword_ids(self) -> "BuilderSkillGroup":
        self.keyword_ids = _stable_item_ids(self.id, "keyword", self.keywords, self.keyword_ids)
        return self


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
    section_titles: Dict[str, str] = Field(default_factory=dict)

    @field_validator("section_titles", mode="before")
    @classmethod
    def validate_section_titles(cls, value):
        if not isinstance(value, dict) or any(key not in SECTION_TITLES for key in value):
            raise ValueError("Section headings require canonical section keys")
        for title in value.values():
            if (not isinstance(title, str) or not 1 <= len(title) <= 80 or not title.strip()
                    or any(unicodedata.category(char).startswith("C") or unicodedata.category(char) in {"Zl", "Zp"} for char in title)):
                raise ValueError("Section headings require 1–80 visible single-line characters")
        return value

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
        # Incoming builder payloads are an API contract: reject coercion and
        # unknown keys rather than silently discarding misspelled user data.
        # Historical persisted documents remain readable through the model's
        # compatibility behavior in render()/build_preview().
        data = StructuredResume.model_validate(
            raw or {}, strict=True, extra="forbid"
        ).model_dump()
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

    def _experience_has_content(self, entry: BuilderExperienceEntry) -> bool:
        return any(value.strip() for value in [entry.title, entry.company, entry.summary, *entry.bullets, *entry.technologies])

    def _education_has_content(self, entry: BuilderEducationEntry) -> bool:
        return any(value.strip() for value in [entry.institution, entry.degree, entry.field, *entry.highlights])

    def _project_has_content(self, entry: BuilderProjectEntry) -> bool:
        return any(value.strip() for value in [entry.name, entry.description, *entry.bullets, *entry.technologies])

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
        hidden = set(structured.hidden_sections)
        experience = [entry for entry in structured.experience if self._experience_has_content(entry)] if "experience" not in hidden else []
        education = [entry for entry in structured.education if self._education_has_content(entry)] if "education" not in hidden else []
        skills = [group for group in structured.skills if any(word.strip() for word in group.keywords)] if "skills" not in hidden else []
        projects = [entry for entry in structured.projects if self._project_has_content(entry)] if "projects" not in hidden else []

        if structured.basics.name.strip():
            score += 15
        else:
            missing.append("name")
        if structured.basics.email.strip():
            score += 10
        else:
            missing.append("email")
        if "summary" not in hidden:
            if structured.basics.summary.strip():
                score += 10
            else:
                missing.append("summary")
        for section, entries, weight in (
            ("experience", experience, 25), ("education", education, 15), ("skills", skills, 15),
        ):
            if section not in hidden:
                if entries:
                    score += weight
                else:
                    missing.append(section)
        if projects:
            score += 10

        total_lines = 6
        total_lines += sum(bool(value.strip()) for key, value in structured.basics.model_dump().items() if key != "summary")
        if "summary" not in hidden:
            total_lines += sum(bool(line.strip()) for line in structured.basics.summary.splitlines())
        total_lines += sum(max(3, sum(bool(b.strip()) for b in entry.bullets) + 2) for entry in experience)
        total_lines += sum(max(2, sum(bool(b.strip()) for b in entry.highlights) + 1) for entry in education)
        total_lines += sum(max(2, (sum(bool(word.strip()) for word in group.keywords) + 4) // 5 + 1) for group in skills)
        total_lines += sum(max(2, sum(bool(b.strip()) for b in item.bullets) + 2) for item in projects)
        if "certifications" not in hidden:
            total_lines += sum(any(value.strip() for value in (item.name, item.issuer, item.date, item.url)) for item in structured.certifications)
        for section in ("awards", "languages", "interests"):
            if section not in hidden:
                total_lines += sum(bool(item.name.strip() or item.detail.strip()) for item in getattr(structured, section))
        page_estimate = max(1, (total_lines + 37) // 38)
        if page_estimate > 1:
            warnings.append("Content likely exceeds one page in compact templates.")
        if any(sum(bool(b.strip()) for b in entry.bullets) > 6 for entry in experience):
            warnings.append("Some experience entries are dense; consider trimming bullets.")
        if not structured.basics.label.strip():
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
        experience = [entry for entry in structured.experience if self._experience_has_content(entry)]
        education = [entry for entry in structured.education if self._education_has_content(entry)]
        projects = [entry for entry in structured.projects if self._project_has_content(entry)]
        skills = [group for group in structured.skills if any(word.strip() for word in group.keywords)]
        certifications = [entry for entry in structured.certifications if any(value.strip() for value in (entry.name, entry.issuer, entry.date, entry.url))]
        awards = [entry for entry in structured.awards if entry.name.strip() or entry.detail.strip()]
        languages = [entry for entry in structured.languages if entry.name.strip() or entry.detail.strip()]
        interests = [entry for entry in structured.interests if entry.name.strip() or entry.detail.strip()]
        for section in structured.section_order:
            if section in hidden:
                continue
            if section == "summary" and structured.basics.summary.strip():
                sections.append({"key": "summary", "title": "Summary", "items": [structured.basics.summary.strip()]})
            elif section == "experience" and experience:
                sections.append({
                    "key": "experience",
                    "title": "Experience",
                    "items": [
                        {
                            "title": f"{item.title} — {item.company}".strip(" —"),
                            "meta": self._join_meta(
                                item.location,
                                self._date_range(item.start_date, item.end_date, item.current),
                                f"Technologies: {', '.join(word for word in item.technologies if word.strip())}" if any(word.strip() for word in item.technologies) else "",
                            ),
                            "bullets": ([item.summary] if item.summary.strip() else []) + [b for b in item.bullets if b.strip()],
                        }
                        for item in experience
                    ],
                })
            elif section == "education" and education:
                sections.append({
                    "key": "education",
                    "title": "Education",
                    "items": [
                        {
                            "title": f"{self._join_meta(item.degree, item.field)} — {item.institution}".strip(" —"),
                            "meta": self._join_meta(
                                item.location,
                                self._date_range(item.start_date, item.end_date, False),
                                f"GPA {item.gpa}" if item.gpa else "",
                            ),
                            "bullets": [b for b in item.highlights if b.strip()],
                        }
                        for item in education
                    ],
                })
            elif section == "skills" and skills:
                sections.append({
                    "key": "skills",
                    "title": "Skills",
                    "items": [{"title": item.name, "meta": ", ".join(word for word in item.keywords if word.strip())} for item in skills],
                })
            elif section == "projects" and projects:
                sections.append({
                    "key": "projects",
                    "title": "Projects",
                    "items": [
                        {
                            "title": item.name,
                            "meta": self._join_meta(
                                item.role, item.url, self._date_range(item.start_date, item.end_date, False),
                                f"Technologies: {', '.join(word for word in item.technologies if word.strip())}" if any(word.strip() for word in item.technologies) else "",
                            ),
                            "bullets": ([item.description] if item.description else []) + [b for b in item.bullets if b.strip()],
                        }
                        for item in projects
                    ],
                })
            elif section == "certifications" and certifications:
                sections.append({
                    "key": "certifications",
                    "title": "Certifications",
                    "items": [{"title": item.name, "meta": self._join_meta(item.issuer, item.date, item.url)} for item in certifications],
                })
            elif section == "awards" and awards:
                sections.append({
                    "key": "awards",
                    "title": "Awards",
                    "items": [{"title": item.name, "meta": item.detail} for item in awards],
                })
            elif section == "languages" and languages:
                sections.append({
                    "key": "languages",
                    "title": "Languages",
                    "items": [{"title": item.name, "meta": item.detail} for item in languages],
                })
            elif section == "interests" and interests:
                sections.append({
                    "key": "interests",
                    "title": "Interests",
                    "items": [{"title": item.name, "meta": item.detail} for item in interests],
                })
        for section in sections:
            section["title"] = structured.section_titles.get(section["key"], section["title"])
        return sections

    def _render_latex(self, structured: StructuredResume, family: str) -> str:
        hidden = set(structured.hidden_sections)
        header = self._render_header(structured.basics, family)
        body: list[str] = [header]

        for section in structured.section_order:
            if section in hidden:
                continue
            rendered = ""
            title = structured.section_titles.get(section, SECTION_TITLES[section])
            if section == "summary" and structured.basics.summary.strip():
                rendered = self._section_block(title, [self._escape(structured.basics.summary.strip())], family)
            elif section == "experience" and structured.experience:
                rendered = self._experience_section(structured.experience, family, title)
            elif section == "education" and structured.education:
                rendered = self._education_section(structured.education, family, title)
            elif section == "skills" and structured.skills:
                rendered = self._skills_section(structured.skills, family, title)
            elif section == "projects" and structured.projects:
                rendered = self._projects_section(structured.projects, family, title)
            elif section == "certifications" and structured.certifications:
                rendered = self._named_list_section(
                    title,
                    [self._join_meta(item.name, item.issuer, item.date, item.url) for item in structured.certifications],
                    family,
                )
            elif section == "awards" and structured.awards:
                rendered = self._named_list_section(
                    title,
                    [self._join_meta(item.name, item.detail) for item in structured.awards],
                    family,
                )
            elif section == "languages" and structured.languages:
                rendered = self._named_list_section(
                    title,
                    [self._join_meta(item.name, item.detail) for item in structured.languages],
                    family,
                )
            elif section == "interests" and structured.interests:
                rendered = self._named_list_section(
                    title,
                    [self._join_meta(item.name, item.detail) for item in structured.interests],
                    family,
                )
            if rendered:
                body.append(rendered)

        document = [
            *MANAGED_ENGLISH_PREAMBLE_LINES,
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
                lines.append(label + r"\\[2pt]")
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

    def _experience_section(self, items: List[BuilderExperienceEntry], family: str, title: str = "Experience") -> str:
        items = [item for item in items if self._experience_has_content(item)]
        if not items:
            return ""
        lines = [self._section_heading(title, family)]
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
            technologies = [word for word in item.technologies if word.strip()]
            if technologies:
                lines.append(rf"\textit{{Technologies:}} {self._escape(', '.join(technologies))}\\")
            lines.append("")
        return "\n".join(lines)

    def _education_section(self, items: List[BuilderEducationEntry], family: str, title: str = "Education") -> str:
        items = [item for item in items if self._education_has_content(item)]
        if not items:
            return ""
        lines = [self._section_heading(title, family)]
        for item in items:
            primary = self._join_meta(item.degree, item.field)
            lines.append(rf"\textbf{{{self._escape(item.institution)}}} \hfill {self._escape(self._date_range(item.start_date, item.end_date, False))}\\")
            if primary:
                lines.append(self._escape(primary) + r"\\")
            detail = self._join_meta(item.location, f"GPA {item.gpa}" if item.gpa else "")
            if detail:
                lines.append(self._escape(detail) + r"\\")
            highlights = [highlight for highlight in item.highlights if highlight.strip()]
            if highlights:
                lines.append(r"\begin{itemize}")
                lines.extend(rf"  \item {self._escape(highlight)}" for highlight in highlights)
                lines.append(r"\end{itemize}")
            lines.append("")
        return "\n".join(lines)

    def _skills_section(self, items: List[BuilderSkillGroup], family: str, title: str = "Skills") -> str:
        items = [item for item in items if any(word.strip() for word in item.keywords)]
        if not items:
            return ""
        lines = [self._section_heading(title, family)]
        for group in items:
            if not group.keywords:
                continue
            name = self._escape(group.name or "Skills")
            keywords = self._escape(", ".join(word for word in group.keywords if word.strip()))
            lines.append(rf"\textbf{{{name}:}} {keywords}\\")
        lines.append("")
        return "\n".join(lines)

    def _projects_section(self, items: List[BuilderProjectEntry], family: str, title: str = "Projects") -> str:
        items = [item for item in items if self._project_has_content(item)]
        if not items:
            return ""
        lines = [self._section_heading(title, family)]
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
            technologies = [word for word in item.technologies if word.strip()]
            if technologies:
                lines.append(rf"\textit{{Technologies:}} {self._escape(', '.join(technologies))}\\")
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
        # Replace original characters once: recursive replacement corrupts the
        # braces inside generated commands such as \textbackslash{}.
        escaped = "".join(self._escape_table.get(char, char) for char in text)
        escaped = re.sub(r"\s+", " ", escaped)
        return escaped.strip()


resume_builder_service = ResumeBuilderService()
