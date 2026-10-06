"""Loss-aware JSON Resume v1.0.0 interchange for the guided builder.

Latexy's structured document remains authoritative.  This adapter maps the
overlapping fields explicitly and reports standard sections that the builder
cannot represent instead of silently pretending an import was lossless.
"""

from __future__ import annotations

import re
from typing import Any

from .resume_builder_service import StructuredResume

JSON_RESUME_SCHEMA_URL = "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json"
_ROOT_FIELDS = {
    "$schema",
    "basics",
    "work",
    "volunteer",
    "education",
    "awards",
    "certificates",
    "publications",
    "skills",
    "languages",
    "interests",
    "references",
    "projects",
    "meta",
}
_DATE_PATTERN = re.compile(r"^[12][0-9]{3}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12][0-9]|3[01]))?)?$")
_MAX_ITEMS = 200
_MAX_TEXT = 20_000

_SECTION_FIELDS: dict[str, set[str]] = {
    "basics": {"name", "label", "image", "email", "phone", "url", "summary", "location", "profiles"},
    "work": {
        "id", "name", "position", "url", "startDate", "endDate", "summary", "highlights",
        "location", "description", "keywords",
    },
    "volunteer": {"id", "organization", "position", "url", "startDate", "endDate", "summary", "highlights"},
    "education": {
        "id", "institution", "url", "area", "studyType", "startDate", "endDate", "score", "courses",
        "location",
    },
    "awards": {"id", "title", "date", "awarder", "summary"},
    "certificates": {"id", "name", "date", "issuer", "url"},
    "publications": {"id", "name", "publisher", "releaseDate", "url", "summary"},
    "skills": {"id", "name", "level", "keywords"},
    "languages": {"id", "language", "fluency"},
    "interests": {"id", "name", "keywords"},
    "references": {"id", "name", "reference"},
    "projects": {
        "id", "name", "description", "highlights", "keywords", "startDate", "endDate", "url", "roles",
        "entity", "type",
    },
}
_BASICS_LOCATION_FIELDS = {"address", "postalCode", "city", "countryCode", "region"}
_PROFILE_FIELDS = {"network", "username", "url"}
_META_FIELDS = {"canonical", "version", "lastModified", "url", "latexy"}
_LATEXY_META_FIELDS = {"sectionOrder", "hiddenSections"}


def _object(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"JSON Resume field '{label}' must be an object")
    return value


def _items(document: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = document.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"JSON Resume field '{key}' must be an array")
    if len(value) > _MAX_ITEMS:
        raise ValueError(f"JSON Resume field '{key}' exceeds {_MAX_ITEMS} entries")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Every JSON Resume '{key}' entry must be an object")
    return value


def _reject_unknown_fields(document: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(document) - allowed)
    if unknown:
        path = f"{label}.{unknown[0]}" if label else unknown[0]
        raise ValueError(f"Unsupported JSON Resume field '{path}'")


def _text(document: dict[str, Any], key: str, label: str | None = None) -> str:
    value = document.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"JSON Resume field '{label or key}' must be a string")
    if len(value) > _MAX_TEXT:
        raise ValueError(f"JSON Resume field '{label or key}' exceeds {_MAX_TEXT} characters")
    return value.strip()


def _strings(document: dict[str, Any], key: str, label: str) -> list[str]:
    value = document.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > _MAX_ITEMS:
        raise ValueError(f"JSON Resume field '{label}' must be an array of at most {_MAX_ITEMS} strings")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"JSON Resume field '{label}[{index}]' must be a string")
        if len(item) > _MAX_TEXT:
            raise ValueError(f"JSON Resume field '{label}[{index}]' is too long")
        if item.strip():
            result.append(item.strip())
    return result


def _date(document: dict[str, Any], key: str, label: str, *, full: bool = False) -> str:
    value = _text(document, key, label)
    if value and (not _DATE_PATTERN.fullmatch(value) or (full and len(value) != 10)):
        expected = "YYYY-MM-DD" if full else "YYYY, YYYY-MM, or YYYY-MM-DD"
        raise ValueError(f"JSON Resume field '{label}' must use {expected}")
    return value


def _compact(document: dict[str, Any]) -> dict[str, Any]:
    """Omit empty optional strings, which fail URI/date/email schema formats."""
    return {key: value for key, value in document.items() if value != ""}


def _entry_id(item: dict[str, Any], prefix: str, index: int) -> str:
    value = item.get("id")
    if value is not None:
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise ValueError(
                f"JSON Resume field '{prefix}[{index}].id' must be a non-empty string of at most 128 characters"
            )
        return value.strip()
    return f"json-{prefix}-{index + 1}"


def _location(value: Any) -> str:
    location = _object(value, "basics.location")
    _reject_unknown_fields(location, _BASICS_LOCATION_FIELDS, "basics.location")
    parts: list[str] = []
    for key in ("address", "city", "region", "postalCode", "countryCode"):
        part = _text(location, key, f"basics.location.{key}")
        if part and part not in parts:
            parts.append(part)
    return ", ".join(parts)


class JSONResumeInterchangeService:
    """Map the common JSON Resume fields to and from ``StructuredResume``."""

    def from_json_resume(self, payload: Any) -> tuple[dict[str, Any], list[str]]:
        document = _object(payload, "root")
        unknown = sorted(set(document) - _ROOT_FIELDS)
        if unknown:
            raise ValueError(f"Unsupported top-level JSON Resume field(s): {', '.join(unknown)}")

        schema = document.get("$schema")
        if schema is not None and not isinstance(schema, str):
            raise ValueError("JSON Resume field '$schema' must be a string")

        basics = _object(document.get("basics"), "basics")
        _reject_unknown_fields(basics, _SECTION_FIELDS["basics"], "basics")
        profiles = basics.get("profiles", []) or []
        if not isinstance(profiles, list) or len(profiles) > _MAX_ITEMS:
            raise ValueError("JSON Resume field 'basics.profiles' must be a bounded array")
        linkedin = ""
        github = ""
        extra_profiles = 0
        for index, raw_profile in enumerate(profiles):
            profile = _object(raw_profile, f"basics.profiles[{index}]")
            _reject_unknown_fields(profile, _PROFILE_FIELDS, f"basics.profiles[{index}]")
            network = _text(profile, "network", f"basics.profiles[{index}].network").lower()
            url = _text(profile, "url", f"basics.profiles[{index}].url")
            if network == "linkedin" and not linkedin:
                linkedin = url
            elif network == "github" and not github:
                github = url
            elif url or network:
                extra_profiles += 1

        section_items = {key: _items(document, key) for key in _SECTION_FIELDS if key != "basics"}
        for section, items in section_items.items():
            for index, item in enumerate(items):
                _reject_unknown_fields(item, _SECTION_FIELDS[section], f"{section}[{index}]")

        structured = StructuredResume(
            basics={
                "name": _text(basics, "name", "basics.name"),
                "label": _text(basics, "label", "basics.label"),
                "email": _text(basics, "email", "basics.email"),
                "phone": _text(basics, "phone", "basics.phone"),
                "location": _location(basics.get("location")),
                "website": _text(basics, "url", "basics.url"),
                "linkedin": linkedin,
                "github": github,
                "summary": _text(basics, "summary", "basics.summary"),
            },
            experience=[
                {
                    "id": _entry_id(item, "work", index),
                    "title": _text(item, "position", f"work[{index}].position"),
                    "company": _text(item, "name", f"work[{index}].name"),
                    "location": _text(item, "location", f"work[{index}].location"),
                    "start_date": _date(item, "startDate", f"work[{index}].startDate"),
                    "end_date": _date(item, "endDate", f"work[{index}].endDate"),
                    "current": not _date(item, "endDate", f"work[{index}].endDate"),
                    "summary": _text(item, "summary", f"work[{index}].summary"),
                    "bullets": _strings(item, "highlights", f"work[{index}].highlights"),
                    "technologies": _strings(item, "keywords", f"work[{index}].keywords"),
                }
                for index, item in enumerate(section_items["work"])
            ],
            education=[
                {
                    "id": _entry_id(item, "education", index),
                    "institution": _text(item, "institution", f"education[{index}].institution"),
                    "degree": _text(item, "studyType", f"education[{index}].studyType"),
                    "field": _text(item, "area", f"education[{index}].area"),
                    "location": _text(item, "location", f"education[{index}].location"),
                    "start_date": _date(item, "startDate", f"education[{index}].startDate"),
                    "end_date": _date(item, "endDate", f"education[{index}].endDate"),
                    "gpa": _text(item, "score", f"education[{index}].score"),
                    "highlights": _strings(item, "courses", f"education[{index}].courses"),
                }
                for index, item in enumerate(section_items["education"])
            ],
            projects=[
                {
                    "id": _entry_id(item, "project", index),
                    "name": _text(item, "name", f"projects[{index}].name"),
                    "role": ", ".join(_strings(item, "roles", f"projects[{index}].roles")),
                    "url": _text(item, "url", f"projects[{index}].url"),
                    "start_date": _date(item, "startDate", f"projects[{index}].startDate"),
                    "end_date": _date(item, "endDate", f"projects[{index}].endDate"),
                    "description": _text(item, "description", f"projects[{index}].description"),
                    "bullets": _strings(item, "highlights", f"projects[{index}].highlights"),
                    "technologies": _strings(item, "keywords", f"projects[{index}].keywords"),
                }
                for index, item in enumerate(section_items["projects"])
            ],
            skills=[
                {
                    "id": _entry_id(item, "skill", index),
                    "name": _text(item, "name", f"skills[{index}].name"),
                    "keywords": _strings(item, "keywords", f"skills[{index}].keywords"),
                }
                for index, item in enumerate(section_items["skills"])
            ],
            certifications=[
                {
                    "id": _entry_id(item, "certificate", index),
                    "name": _text(item, "name", f"certificates[{index}].name"),
                    "issuer": _text(item, "issuer", f"certificates[{index}].issuer"),
                    "date": _date(item, "date", f"certificates[{index}].date", full=True),
                    "url": _text(item, "url", f"certificates[{index}].url"),
                }
                for index, item in enumerate(section_items["certificates"])
            ],
            awards=[
                {
                    "id": _entry_id(item, "award", index),
                    "name": _text(item, "title", f"awards[{index}].title"),
                    "detail": " · ".join(
                        part
                        for part in (
                            _text(item, "awarder", f"awards[{index}].awarder"),
                            _date(item, "date", f"awards[{index}].date"),
                            _text(item, "summary", f"awards[{index}].summary"),
                        )
                        if part
                    ),
                }
                for index, item in enumerate(section_items["awards"])
            ],
            languages=[
                {
                    "id": _entry_id(item, "language", index),
                    "name": _text(item, "language", f"languages[{index}].language"),
                    "detail": _text(item, "fluency", f"languages[{index}].fluency"),
                }
                for index, item in enumerate(section_items["languages"])
            ],
            interests=[
                {
                    "id": _entry_id(item, "interest", index),
                    "name": _text(item, "name", f"interests[{index}].name"),
                    "detail": ", ".join(_strings(item, "keywords", f"interests[{index}].keywords")),
                }
                for index, item in enumerate(section_items["interests"])
            ],
        )

        meta = _object(document.get("meta"), "meta")
        _reject_unknown_fields(meta, _META_FIELDS, "meta")
        latexy_meta = _object(meta.get("latexy"), "meta.latexy")
        _reject_unknown_fields(latexy_meta, _LATEXY_META_FIELDS, "meta.latexy")
        if "sectionOrder" in latexy_meta:
            structured.section_order = _strings(latexy_meta, "sectionOrder", "meta.latexy.sectionOrder")
        if "hiddenSections" in latexy_meta:
            structured.hidden_sections = _strings(latexy_meta, "hiddenSections", "meta.latexy.hiddenSections")

        warnings: list[str] = []
        if schema and "v1.0.0" not in schema:
            warnings.append("The file declares a schema other than JSON Resume v1.0.0; common fields were imported.")
        if extra_profiles:
            warnings.append(f"{extra_profiles} non-LinkedIn/GitHub profile(s) are not editable in the guided builder.")
        for key in ("volunteer", "publications", "references"):
            if section_items[key]:
                warnings.append(
                    f"The JSON Resume '{key}' section is not editable in the guided builder and was omitted."
                )
        return structured.model_dump(), warnings

    def to_json_resume(self, structured_raw: dict[str, Any]) -> dict[str, Any]:
        structured = StructuredResume.model_validate(structured_raw)
        profiles = []
        if structured.basics.linkedin:
            profiles.append({"network": "LinkedIn", "url": structured.basics.linkedin})
        if structured.basics.github:
            profiles.append({"network": "GitHub", "url": structured.basics.github})

        def export_date(value: str, label: str, *, full: bool = False) -> str:
            return _date({"value": value}, "value", label, full=full)

        return {
            "$schema": JSON_RESUME_SCHEMA_URL,
            "basics": _compact(
                {
                    "name": structured.basics.name,
                    "label": structured.basics.label,
                    "email": structured.basics.email,
                    "phone": structured.basics.phone,
                    "url": structured.basics.website,
                    "summary": structured.basics.summary,
                    "location": {"address": structured.basics.location},
                    "profiles": profiles,
                }
            ),
            "work": [
                _compact(
                    {
                        "id": item.id,
                        "name": item.company,
                        "position": item.title,
                        "location": item.location,
                        "startDate": export_date(item.start_date, f"experience '{item.id}' start date"),
                        "endDate": ""
                        if item.current
                        else export_date(item.end_date, f"experience '{item.id}' end date"),
                        "summary": item.summary,
                        "highlights": item.bullets,
                        "keywords": item.technologies,
                    }
                )
                for item in structured.experience
            ],
            "education": [
                _compact(
                    {
                        "id": item.id,
                        "institution": item.institution,
                        "studyType": item.degree,
                        "area": item.field,
                        "location": item.location,
                        "startDate": export_date(item.start_date, f"education '{item.id}' start date"),
                        "endDate": export_date(item.end_date, f"education '{item.id}' end date"),
                        "score": item.gpa,
                        "courses": item.highlights,
                    }
                )
                for item in structured.education
            ],
            "projects": [
                _compact(
                    {
                        "id": item.id,
                        "name": item.name,
                        "description": item.description,
                        "highlights": item.bullets,
                        "keywords": item.technologies,
                        "startDate": export_date(item.start_date, f"project '{item.id}' start date"),
                        "endDate": export_date(item.end_date, f"project '{item.id}' end date"),
                        "url": item.url,
                        "roles": [item.role] if item.role else [],
                    }
                )
                for item in structured.projects
            ],
            "skills": [{"id": item.id, "name": item.name, "keywords": item.keywords} for item in structured.skills],
            "certificates": [
                _compact(
                    {
                        "id": item.id,
                        "name": item.name,
                        "issuer": item.issuer,
                        "date": export_date(item.date, f"certificate '{item.id}' date", full=True),
                        "url": item.url,
                    }
                )
                for item in structured.certifications
            ],
            "awards": [{"id": item.id, "title": item.name, "summary": item.detail} for item in structured.awards],
            "languages": [
                {"id": item.id, "language": item.name, "fluency": item.detail} for item in structured.languages
            ],
            "interests": [
                {"id": item.id, "name": item.name, "keywords": [item.detail] if item.detail else []}
                for item in structured.interests
            ],
            "volunteer": [],
            "publications": [],
            "references": [],
            "meta": {
                "version": "v1.0.0",
                "latexy": {
                    "sectionOrder": structured.section_order,
                    "hiddenSections": structured.hidden_sections,
                },
            },
        }


json_resume_interchange_service = JSONResumeInterchangeService()
