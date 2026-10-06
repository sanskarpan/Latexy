"""Vendor-neutral projection of resume data onto the convergent ATS core."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_ISO_RE = re.compile(r"^(?:19|20)\d{2}(?:-(\d{2})(?:-(\d{2}))?)?$")
_NAMED_MONTH_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\b",
    re.IGNORECASE,
)
_CURRENT_VALUES = frozenset({"present", "current", "now", "ongoing"})


class ATSPartialDate(BaseModel):
    value: str | None = None
    is_current: bool = False
    found_year: bool = False
    found_month: bool = False
    found_day: bool = False


class ATSIdentity(BaseModel):
    given_name: str = ""
    family_name: str = ""


class ATSContact(BaseModel):
    email: str = ""
    phone: str = ""
    city: str = ""
    region: str = ""
    country: str = ""


class ATSLinks(BaseModel):
    linkedin: str = ""
    personal_site: str = ""


class ATSWorkEntry(BaseModel):
    employer: str = ""
    job_title: str = ""
    start_date: ATSPartialDate = Field(default_factory=ATSPartialDate)
    end_date: ATSPartialDate = Field(default_factory=ATSPartialDate)
    is_current: bool = False
    description: str = ""


class ATSEducationEntry(BaseModel):
    institution: str = ""
    degree: str = ""
    field: str = ""
    start_date: ATSPartialDate = Field(default_factory=ATSPartialDate)
    end_date: ATSPartialDate = Field(default_factory=ATSPartialDate)


class CanonicalATSResume(BaseModel):
    identity: ATSIdentity = Field(default_factory=ATSIdentity)
    contact: ATSContact = Field(default_factory=ATSContact)
    links: ATSLinks = Field(default_factory=ATSLinks)
    work: list[ATSWorkEntry] = Field(default_factory=list)
    education: list[ATSEducationEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


def partial_date(value: Any, *, current: bool = False) -> ATSPartialDate:
    """Represent observed precision without inventing a missing month or day."""

    raw = str(value or "").strip()
    is_current = current or raw.lower() in _CURRENT_VALUES
    if is_current:
        return ATSPartialDate(value="Present", is_current=True)
    if not raw:
        return ATSPartialDate()

    iso = _ISO_RE.fullmatch(raw)
    found_year = bool(_YEAR_RE.search(raw))
    found_month = bool(iso and iso.group(1)) or bool(_NAMED_MONTH_RE.search(raw))
    found_day = bool(iso and iso.group(2)) or bool(
        re.search(r"(?<!\d)(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?[ /-]", raw)
    )
    return ATSPartialDate(
        value=raw,
        found_year=found_year,
        found_month=found_month,
        found_day=found_day,
    )


def _split_name(name: str) -> ATSIdentity:
    parts = name.split()
    if len(parts) < 2:
        return ATSIdentity(given_name=name.strip())
    return ATSIdentity(given_name=" ".join(parts[:-1]), family_name=parts[-1])


def _split_location(location: str) -> ATSContact:
    parts = [part.strip() for part in location.split(",") if part.strip()]
    if not parts:
        return ATSContact()
    if len(parts) == 1:
        return ATSContact(city=parts[0])
    if len(parts) == 2:
        return ATSContact(city=parts[0], country=parts[1])
    return ATSContact(city=parts[0], region=", ".join(parts[1:-1]), country=parts[-1])


def from_structured_resume(structured: dict[str, Any]) -> CanonicalATSResume:
    """Project persisted builder content without duplicating mutable ATS data."""

    basics = structured.get("basics") or {}
    identity = _split_name(str(basics.get("name") or ""))
    location = _split_location(str(basics.get("location") or ""))
    contact = ATSContact(
        email=str(basics.get("email") or "").strip(),
        phone=str(basics.get("phone") or "").strip(),
        city=location.city,
        region=location.region,
        country=location.country,
    )

    work = []
    for entry in structured.get("experience") or []:
        is_current = bool(entry.get("current"))
        description_parts = [entry.get("summary") or "", *(entry.get("bullets") or [])]
        work.append(
            ATSWorkEntry(
                employer=str(entry.get("company") or "").strip(),
                job_title=str(entry.get("title") or "").strip(),
                start_date=partial_date(entry.get("start_date")),
                end_date=partial_date(entry.get("end_date"), current=is_current),
                is_current=is_current,
                description="\n".join(str(part).strip() for part in description_parts if str(part).strip()),
            )
        )

    education = [
        ATSEducationEntry(
            institution=str(entry.get("institution") or "").strip(),
            degree=str(entry.get("degree") or "").strip(),
            field=str(entry.get("field") or "").strip(),
            start_date=partial_date(entry.get("start_date")),
            end_date=partial_date(entry.get("end_date")),
        )
        for entry in (structured.get("education") or [])
    ]

    skills: list[str] = []
    seen: set[str] = set()
    for group in structured.get("skills") or []:
        for raw_skill in group.get("keywords") or []:
            skill = str(raw_skill).strip()
            folded = skill.casefold()
            if skill and folded not in seen:
                skills.append(skill)
                seen.add(folded)

    return CanonicalATSResume(
        identity=identity,
        contact=contact,
        links=ATSLinks(
            linkedin=str(basics.get("linkedin") or "").strip(),
            personal_site=str(basics.get("website") or "").strip(),
        ),
        work=work,
        education=education,
        skills=skills,
    )
