"""Parse JSON Resume and Reactive Resume v4/v5 exports."""

import html
import json
import logging
import re
from html.parser import HTMLParser as StdlibHTMLParser
from typing import Any, Optional

from .base_parser import (
    AbstractParser,
    Certification,
    ContactInfo,
    Education,
    Experience,
    Language,
    ParsedResume,
    Project,
    Publication,
)

logger = logging.getLogger(__name__)

JSON_RESUME_KEYS = {"basics", "work", "education", "skills"}
MAX_ITEMS_PER_SECTION = 500
MAX_TEXT_CHARS = 20_000
MAX_GENERIC_TEXT_CHARS = 100_000


class _RichTextExtractor(StdlibHTMLParser):
    """Turn builder HTML into plain text without retaining markup."""

    _BLOCK_TAGS = {"br", "div", "li", "ol", "p", "tr", "ul"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _text(value: Any, *, limit: int = MAX_TEXT_CHARS) -> str:
    if value is None or not isinstance(value, (str, int, float, bool)):
        return ""
    parser = _RichTextExtractor()
    try:
        parser.feed(str(value))
        parser.close()
        result = "".join(parser.parts)
    except Exception:
        result = html.unescape(str(value))
    result = re.sub(r"[ \t\r\f\v]+", " ", result)
    result = re.sub(r" *\n *", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result[:limit]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(section: Any, *, v4: bool) -> list[dict[str, Any]]:
    section_data = _dict(section)
    if (v4 and section_data.get("visible") is False) or (
        not v4 and section_data.get("hidden") is True
    ):
        return []
    values = section_data.get("items")
    if not isinstance(values, list):
        return []
    visible: list[dict[str, Any]] = []
    for value in values[:MAX_ITEMS_PER_SECTION]:
        if not isinstance(value, dict):
            continue
        if (v4 and value.get("visible") is False) or (
            not v4 and value.get("hidden") is True
        ):
            continue
        visible.append(value)
    return visible


def _url(value: Any, *, v4: bool = False) -> str:
    data = _dict(value)
    return _text(data.get("href" if v4 else "url"))


def _split_period(value: Any) -> tuple[Optional[str], Optional[str], bool]:
    period = _text(value, limit=500)
    if not period:
        return None, None, False
    parts = re.split(r"\s+(?:-|–|—|to)\s+", period, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        end = parts[1].strip()
        current = end.lower() in {"present", "current", "now"}
        return parts[0].strip() or None, None if current else end or None, current
    return period, None, False


def _description(value: Any) -> list[str]:
    plain = _text(value)
    return [line.lstrip("•-* ").strip() for line in plain.splitlines() if line.strip()][
        :MAX_ITEMS_PER_SECTION
    ]


def _is_reactive_v4(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    sections = _dict(data.get("sections"))
    return bool(_dict(data.get("basics")) and _dict(data.get("metadata")) and "summary" in sections)


def _is_reactive_v5(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    sections = _dict(data.get("sections"))
    summary = _dict(data.get("summary"))
    return bool(
        _dict(data.get("basics"))
        and sections
        and ("content" in summary or "customSections" in data)
    )


class JSONParser(AbstractParser):
    """Parser for standard JSON Resume and Reactive Resume exports."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        if not file_content:
            raise ValueError("JSON file is empty")
        try:
            text = file_content.decode("utf-8-sig")
            data = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid JSON file") from exc

        try:
            if _is_reactive_v4(data):
                return self._parse_reactive_resume(data, filename, v4=True)
            if _is_reactive_v5(data):
                return self._parse_reactive_resume(data, filename, v4=False)
            if isinstance(data, dict) and JSON_RESUME_KEYS.intersection(data):
                return self._parse_json_resume_schema(data, filename)

            raw = json.dumps(data, indent=2, ensure_ascii=False)
            if len(raw) > MAX_GENERIC_TEXT_CHARS:
                raw = raw[:MAX_GENERIC_TEXT_CHARS] + "\n[Generic JSON truncated]"
            return self._build_parsed_resume(raw, filename)
        except ValueError:
            raise
        except Exception as exc:
            logger.exception("Error parsing JSON resume")
            raise ValueError("Failed to parse JSON resume") from exc

    def _parse_reactive_resume(
        self, data: dict[str, Any], filename: str, *, v4: bool
    ) -> ParsedResume:
        basics = _dict(data.get("basics"))
        sections = _dict(data.get("sections"))
        profiles = _items(sections.get("profiles"), v4=v4)

        def profile_url(network: str) -> Optional[str]:
            for profile in profiles:
                if network in _text(profile.get("network")).lower():
                    return _url(profile.get("url" if v4 else "website"), v4=v4) or None
            return None

        contact = ContactInfo(
            name=_text(basics.get("name")) or None,
            email=_text(basics.get("email")) or None,
            phone=_text(basics.get("phone")) or None,
            location=_text(basics.get("location")) or None,
            linkedin=profile_url("linkedin"),
            github=profile_url("github"),
            website=(
                _url(basics.get("url"), v4=True)
                if v4
                else _url(basics.get("website"))
            ) or None,
        )

        if v4:
            summary_section = _dict(sections.get("summary"))
            summary = "" if summary_section.get("visible") is False else _text(summary_section.get("content"))
        else:
            summary_section = _dict(data.get("summary"))
            summary = "" if summary_section.get("hidden") is True else _text(summary_section.get("content"))

        experience: list[Experience] = []
        for item in _items(sections.get("experience"), v4=v4):
            start, end, current = _split_period(item.get("date" if v4 else "period"))
            roles = item.get("roles") if isinstance(item.get("roles"), list) else []
            visible_roles = [r for r in roles[:MAX_ITEMS_PER_SECTION] if isinstance(r, dict)]
            if not v4 and visible_roles:
                parent_description = _description(item.get("description"))
                for index, role in enumerate(visible_roles):
                    role_start, role_end, role_current = _split_period(role.get("period"))
                    experience.append(Experience(
                        title=_text(role.get("position") or item.get("position")),
                        company=_text(item.get("company")),
                        location=_text(item.get("location")) or None,
                        start_date=role_start or start,
                        end_date=role_end if role_start else end,
                        current=role_current if role_start else current,
                        description=(parent_description if index == 0 else [])
                        + _description(role.get("description")),
                    ))
                continue
            experience.append(Experience(
                title=_text(item.get("position")),
                company=_text(item.get("company")),
                location=_text(item.get("location")) or None,
                start_date=start,
                end_date=end,
                current=current,
                description=_description(item.get("summary" if v4 else "description")),
            ))

        education = []
        for item in _items(sections.get("education"), v4=v4):
            period = item.get("date" if v4 else "period")
            _, graduation, _ = _split_period(period)
            education.append(Education(
                degree=" ".join(filter(None, [
                    _text(item.get("studyType" if v4 else "degree")),
                    _text(item.get("area")),
                ])),
                institution=_text(item.get("institution" if v4 else "school")),
                location=_text(item.get("location")) or None,
                graduation_date=graduation or _text(period) or None,
                gpa=_text(item.get("score" if v4 else "grade")) or None,
            ))

        skills: list[str] = []
        categorized: dict[str, list[str]] = {}
        for item in _items(sections.get("skills"), v4=v4):
            name = _text(item.get("name"))
            keywords = [
                _text(keyword, limit=500)
                for keyword in (item.get("keywords") or [])[:MAX_ITEMS_PER_SECTION]
                if _text(keyword, limit=500)
            ] if isinstance(item.get("keywords"), list) else []
            values = keywords or ([name] if name else [])
            skills.extend(values)
            if name and keywords:
                categorized[name] = keywords

        projects = [Project(
            name=_text(item.get("name")),
            description=_text(item.get("summary" if v4 else "description")),
            technologies=[_text(k, limit=500) for k in (item.get("keywords") or [])[:MAX_ITEMS_PER_SECTION]]
            if v4 and isinstance(item.get("keywords"), list) else [],
            url=_url(item.get("url" if v4 else "website"), v4=v4) or None,
            start_date=_text(item.get("date" if v4 else "period")) or None,
        ) for item in _items(sections.get("projects"), v4=v4)]

        certifications = [Certification(
            name=_text(item.get("name" if v4 else "title")),
            issuer=_text(item.get("issuer")),
            date=_text(item.get("date")) or None,
            url=_url(item.get("url" if v4 else "website"), v4=v4) or None,
        ) for item in _items(sections.get("certifications"), v4=v4)]

        languages = [Language(
            language=_text(item.get("name" if v4 else "language")),
            proficiency=_text(item.get("description" if v4 else "fluency")) or None,
        ) for item in _items(sections.get("languages"), v4=v4)]

        publications = [Publication(
            title=_text(item.get("name" if v4 else "title")),
            venue=_text(item.get("publisher")) or None,
            date=_text(item.get("date")) or None,
            url=_url(item.get("url" if v4 else "website"), v4=v4) or None,
        ) for item in _items(sections.get("publications"), v4=v4)]

        awards = []
        for item in _items(sections.get("awards"), v4=v4):
            title = _text(item.get("title"))
            details = " — ".join(filter(None, [
                _text(item.get("awarder")),
                _text(item.get("date")),
                _text(item.get("summary" if v4 else "description")),
            ]))
            if title:
                awards.append(f"{title}: {details}" if details else title)

        volunteer = []
        for item in _items(sections.get("volunteer"), v4=v4):
            volunteer.append({
                "organization": _text(item.get("organization")),
                "position": _text(item.get("position")),
                "location": _text(item.get("location")),
                "period": _text(item.get("date" if v4 else "period")),
                "description": _text(item.get("summary" if v4 else "description")),
            })

        references = []
        for item in _items(sections.get("references"), v4=v4):
            references.append({
                "name": _text(item.get("name")),
                "position": _text(item.get("description" if v4 else "position")),
                "phone": _text(item.get("phone")),
                "description": _text(item.get("summary" if v4 else "description")),
            })

        custom_sections: list[dict[str, Any]] = []
        if v4:
            custom = sections.get("custom")
            custom_iterable = list(custom.values()) if isinstance(custom, dict) else []
        else:
            custom = data.get("customSections")
            custom_iterable = custom if isinstance(custom, list) else []
        for section in custom_iterable[:MAX_ITEMS_PER_SECTION]:
            if not isinstance(section, dict):
                continue
            section_items = _items(section, v4=v4)
            custom_sections.append({
                "title": _text(section.get("name" if v4 else "title")) or "Additional",
                "items": [
                    {key: _text(value) for key, value in item.items()
                     if key not in {"id", "hidden", "visible"} and _text(value)}
                    for item in section_items
                ],
            })

        parsed = ParsedResume(
            contact=contact,
            summary=summary or None,
            experience=experience,
            education=education,
            skills=list(dict.fromkeys(skills))[:MAX_ITEMS_PER_SECTION],
            skills_categorized=categorized,
            projects=projects,
            certifications=certifications,
            languages=languages,
            publications=publications,
            awards=awards,
            volunteer=volunteer,
            interests=[_text(item.get("name")) for item in _items(sections.get("interests"), v4=v4) if _text(item.get("name"))],
            references=references,
            metadata={
                "filename": filename,
                "parser": "JSONParser",
                "schema": f"reactive_resume_v{4 if v4 else 5}",
                "is_structured": True,
                "custom_sections": custom_sections,
            },
        )
        parsed.raw_text = self._structured_text(parsed)
        return parsed

    def _parse_json_resume_schema(self, data: dict[str, Any], filename: str) -> ParsedResume:
        basics = _dict(data.get("basics"))
        profiles = basics.get("profiles") if isinstance(basics.get("profiles"), list) else []

        def profile_url(network: str) -> Optional[str]:
            return next((
                _text(profile.get("url"))
                for profile in profiles[:MAX_ITEMS_PER_SECTION]
                if isinstance(profile, dict) and network in _text(profile.get("network")).lower()
            ), None)

        location = basics.get("location")
        if isinstance(location, dict):
            location = ", ".join(filter(None, [
                _text(location.get("city")), _text(location.get("region")), _text(location.get("countryCode")),
            ]))
        contact = ContactInfo(
            name=_text(basics.get("name")) or None,
            email=_text(basics.get("email")) or None,
            phone=_text(basics.get("phone")) or None,
            location=_text(location) or None,
            linkedin=profile_url("linkedin"),
            github=profile_url("github"),
            website=_text(basics.get("url")) or None,
        )

        work = data.get("work") if isinstance(data.get("work"), list) else []
        experience = []
        for job in work[:MAX_ITEMS_PER_SECTION]:
            if not isinstance(job, dict):
                continue
            highlights = job.get("highlights") if isinstance(job.get("highlights"), list) else []
            experience.append(Experience(
                title=_text(job.get("position") or job.get("title")),
                company=_text(job.get("name") or job.get("company")),
                start_date=_text(job.get("startDate")) or None,
                end_date=_text(job.get("endDate")) or None,
                current=not bool(job.get("endDate")) or _text(job.get("endDate")).lower() == "present",
                description=[_text(item) for item in highlights[:MAX_ITEMS_PER_SECTION] if _text(item)],
            ))

        education_data = data.get("education") if isinstance(data.get("education"), list) else []
        education = [Education(
            degree=" ".join(filter(None, [_text(item.get("studyType")), _text(item.get("area"))])),
            institution=_text(item.get("institution")),
            graduation_date=_text(item.get("endDate")) or None,
        ) for item in education_data[:MAX_ITEMS_PER_SECTION] if isinstance(item, dict)]

        skills: list[str] = []
        categorized: dict[str, list[str]] = {}
        skills_data = data.get("skills") if isinstance(data.get("skills"), list) else []
        for item in skills_data[:MAX_ITEMS_PER_SECTION]:
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name"))
            keywords = item.get("keywords") if isinstance(item.get("keywords"), list) else []
            clean = [_text(keyword, limit=500) for keyword in keywords[:MAX_ITEMS_PER_SECTION] if _text(keyword, limit=500)]
            skills.extend(clean or ([name] if name else []))
            if name and clean:
                categorized[name] = clean

        projects_data = data.get("projects") if isinstance(data.get("projects"), list) else []
        projects = []
        for item in projects_data[:MAX_ITEMS_PER_SECTION]:
            if not isinstance(item, dict):
                continue
            highlights = item.get("highlights") if isinstance(item.get("highlights"), list) else []
            keywords = item.get("keywords") if isinstance(item.get("keywords"), list) else []
            description = "\n".join(filter(None, [
                _text(item.get("description")),
                *[_text(value) for value in highlights[:MAX_ITEMS_PER_SECTION]],
            ]))
            projects.append(Project(
                name=_text(item.get("name")),
                description=description,
                technologies=[_text(value, limit=500) for value in keywords[:MAX_ITEMS_PER_SECTION] if _text(value, limit=500)],
                url=_text(item.get("url")) or None,
                start_date=_text(item.get("startDate")) or None,
                end_date=_text(item.get("endDate")) or None,
            ))

        certificates_data = data.get("certificates") if isinstance(data.get("certificates"), list) else []
        certifications = [Certification(
            name=_text(item.get("name")),
            issuer=_text(item.get("issuer")),
            date=_text(item.get("date")) or None,
            url=_text(item.get("url")) or None,
        ) for item in certificates_data[:MAX_ITEMS_PER_SECTION] if isinstance(item, dict)]

        languages_data = data.get("languages") if isinstance(data.get("languages"), list) else []
        languages = [Language(
            language=_text(item.get("language")),
            proficiency=_text(item.get("fluency")) or None,
        ) for item in languages_data[:MAX_ITEMS_PER_SECTION] if isinstance(item, dict)]

        publications_data = data.get("publications") if isinstance(data.get("publications"), list) else []
        publications = [Publication(
            title=_text(item.get("name")),
            venue=_text(item.get("publisher")) or None,
            date=_text(item.get("releaseDate")) or None,
            url=_text(item.get("url")) or None,
        ) for item in publications_data[:MAX_ITEMS_PER_SECTION] if isinstance(item, dict)]

        awards_data = data.get("awards") if isinstance(data.get("awards"), list) else []
        awards = []
        for item in awards_data[:MAX_ITEMS_PER_SECTION]:
            if not isinstance(item, dict):
                continue
            title = _text(item.get("title"))
            details = " — ".join(filter(None, [
                _text(item.get("awarder")), _text(item.get("date")), _text(item.get("summary")),
            ]))
            if title:
                awards.append(f"{title}: {details}" if details else title)

        volunteer_data = data.get("volunteer") if isinstance(data.get("volunteer"), list) else []
        volunteer = [{
            "organization": _text(item.get("organization")),
            "position": _text(item.get("position")),
            "period": " - ".join(filter(None, [
                _text(item.get("startDate")), _text(item.get("endDate")),
            ])),
            "description": "\n".join(
                _text(value) for value in (item.get("highlights") or [])[:MAX_ITEMS_PER_SECTION]
            ) if isinstance(item.get("highlights"), list) else _text(item.get("summary")),
        } for item in volunteer_data[:MAX_ITEMS_PER_SECTION] if isinstance(item, dict)]

        interests_data = data.get("interests") if isinstance(data.get("interests"), list) else []
        interests = [_text(item.get("name")) for item in interests_data[:MAX_ITEMS_PER_SECTION]
                     if isinstance(item, dict) and _text(item.get("name"))]
        references_data = data.get("references") if isinstance(data.get("references"), list) else []
        references = [{
            "name": _text(item.get("name")),
            "description": _text(item.get("reference")),
        } for item in references_data[:MAX_ITEMS_PER_SECTION] if isinstance(item, dict)]

        parsed = ParsedResume(
            contact=contact,
            summary=_text(basics.get("summary")) or None,
            experience=experience,
            education=education,
            skills=list(dict.fromkeys(skills))[:MAX_ITEMS_PER_SECTION],
            skills_categorized=categorized,
            projects=projects,
            certifications=certifications,
            languages=languages,
            publications=publications,
            awards=awards,
            volunteer=volunteer,
            interests=interests,
            references=references,
            metadata={
                "filename": filename,
                "parser": "JSONParser",
                "schema": "json_resume",
                "is_structured": True,
            },
        )
        parsed.raw_text = self._structured_text(parsed)
        return parsed

    @staticmethod
    def _structured_text(parsed: ParsedResume) -> str:
        lines = [parsed.contact.name or "", parsed.contact.email or "", parsed.contact.phone or ""]
        if parsed.summary:
            lines.extend(["", "SUMMARY", parsed.summary])
        if parsed.experience:
            lines.extend(["", "EXPERIENCE"])
            for item in parsed.experience:
                lines.append(f"{item.title} at {item.company}".strip())
                lines.append(" - ".join(filter(None, [item.start_date, item.end_date or ("Present" if item.current else None)])))
                lines.extend(f"- {description}" for description in item.description)
        if parsed.education:
            lines.extend(["", "EDUCATION"])
            for item in parsed.education:
                lines.append(" - ".join(filter(None, [item.degree, item.institution, item.graduation_date])))
        if parsed.skills:
            lines.extend(["", "SKILLS", ", ".join(parsed.skills)])
        if parsed.projects:
            lines.extend(["", "PROJECTS"])
            lines.extend(f"{item.name}: {item.description}" for item in parsed.projects)
        if parsed.certifications:
            lines.extend(["", "CERTIFICATIONS"])
            lines.extend(" — ".join(filter(None, [item.name, item.issuer, item.date])) for item in parsed.certifications)
        if parsed.languages:
            lines.extend(["", "LANGUAGES"])
            lines.extend(" — ".join(filter(None, [item.language, item.proficiency])) for item in parsed.languages)
        if parsed.publications:
            lines.extend(["", "PUBLICATIONS"])
            lines.extend(" — ".join(filter(None, [item.title, item.venue, item.date])) for item in parsed.publications)
        if parsed.awards:
            lines.extend(["", "AWARDS", *parsed.awards])
        if parsed.volunteer:
            lines.extend(["", "VOLUNTEERING"])
            lines.extend(" — ".join(str(value) for value in item.values() if value) for item in parsed.volunteer)
        if parsed.interests:
            lines.extend(["", "INTERESTS", ", ".join(parsed.interests)])
        if parsed.references:
            lines.extend(["", "REFERENCES"])
            lines.extend(" — ".join(str(value) for value in item.values() if value) for item in parsed.references)
        custom_sections = parsed.metadata.get("custom_sections")
        if isinstance(custom_sections, list):
            for section in custom_sections:
                if not isinstance(section, dict):
                    continue
                lines.extend(["", _text(section.get("title")).upper()])
                for item in section.get("items", [])[:MAX_ITEMS_PER_SECTION]:
                    if isinstance(item, dict):
                        lines.append(" — ".join(str(value) for value in item.values() if value))
        return "\n".join(line for line in lines if line is not None)[:MAX_GENERIC_TEXT_CHARS]

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        if not file_content:
            return False, "File is empty"
        try:
            json.loads(file_content.decode("utf-8-sig"))
            return True, None
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False, "Invalid JSON input"
        except Exception:
            return False, "JSON validation failed"
