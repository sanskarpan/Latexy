"""
JSON Parser - Parse JSON resume files (JSON Resume schema and generic).
"""
import json
import logging
from typing import Optional

from .base_parser import AbstractParser, ContactInfo, Education, Experience, ParsedResume

logger = logging.getLogger(__name__)

# JSON Resume schema keys (https://jsonresume.org/schema)
JSON_RESUME_KEYS = {'basics', 'work', 'education', 'skills'}


class JSONParser(AbstractParser):
    """Parser for JSON resume files."""

    async def parse(self, file_content: bytes, filename: str = "") -> ParsedResume:
        if not file_content:
            raise ValueError("JSON file is empty")
        try:
            # Try strict UTF-8 first; fall back to latin-1 (preserves all bytes without dropping)
            try:
                text = file_content.decode('utf-8')
            except UnicodeDecodeError:
                text = file_content.decode('latin-1')
            data = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid JSON file: {e}")

        try:
            # Check if it follows JSON Resume schema
            if isinstance(data, dict) and JSON_RESUME_KEYS.intersection(data.keys()):
                return self._parse_json_resume_schema(data, filename)
            else:
                # Generic JSON — stringify for LLM
                raw = json.dumps(data, indent=2, ensure_ascii=False)
                return self._build_parsed_resume(raw, filename)
        except Exception as e:
            logger.error(f"Error parsing JSON: {e}")
            raise ValueError(f"Failed to parse JSON: {str(e)}")

    def _parse_json_resume_schema(self, data: dict, filename: str) -> ParsedResume:
        """Parse JSON Resume standard schema directly into ParsedResume."""
        basics = data.get('basics', {})
        contact = ContactInfo(
            name=basics.get('name'),
            email=basics.get('email'),
            phone=basics.get('phone'),
            location=basics.get('location', {}).get('city') if isinstance(basics.get('location'), dict) else None,
            linkedin=next(
                (p.get('url') for p in basics.get('profiles', []) if 'linkedin' in p.get('network', '').lower()),
                None
            ),
            github=next(
                (p.get('url') for p in basics.get('profiles', []) if 'github' in p.get('network', '').lower()),
                None
            ),
            website=basics.get('url'),
        )

        # Build raw text representation for LLM context
        lines = [basics.get('name', ''), basics.get('email', ''), basics.get('phone', ''), '']
        if basics.get('summary'):
            lines.extend(['SUMMARY', basics['summary'], ''])

        for job in data.get('work', []):
            lines.extend([
                f"{job.get('position', '')} at {job.get('name', '')}",
                f"{job.get('startDate', '')} - {job.get('endDate') or 'Present'}",
            ])
            for hi in job.get('highlights', []):
                lines.append(f"  - {hi}")
            lines.append('')

        lines.append('EDUCATION')
        for edu in data.get('education', []):
            lines.append(f"{edu.get('studyType', '')} {edu.get('area', '')} - {edu.get('institution', '')} ({edu.get('endDate', '')})")
        lines.append('')

        lines.append('SKILLS')
        for skill in data.get('skills', []):
            lines.append(f"{skill.get('name', '')}: {', '.join(skill.get('keywords', []))}")

        raw_text = '\n'.join(lines)
        # Populate structured fields so callers can use counts/lists directly
        experience = [
            Experience(
                title=job.get('position') or job.get('title') or '',
                company=job.get('name') or job.get('company') or '',
                start_date=job.get('startDate'),
                end_date=job.get('endDate'),
                current=not job.get('endDate') or job.get('endDate', '').lower() == 'present',
                description=job.get('highlights') or [],
            )
            for job in data.get('work', [])
        ]
        education = [
            Education(
                degree=f"{edu.get('studyType', '')} {edu.get('area', '')}".strip() or edu.get('degree', ''),
                institution=edu.get('institution', ''),
                graduation_date=edu.get('endDate'),
            )
            for edu in data.get('education', [])
        ]
        # Flatten nested skill categories into a simple list
        skills: list[str] = []
        for skill in data.get('skills', []):
            skills.extend(skill.get('keywords', []))

        parsed = ParsedResume(
            contact=contact,
            summary=basics.get('summary'),
            experience=experience,
            education=education,
            skills=skills,
            raw_text=raw_text,
            metadata={
                "filename": filename,
                "parser": "JSONParser",
                "schema": "json_resume",
                "is_structured": True,
            }
        )
        return parsed

    def validate(self, file_content: bytes) -> tuple[bool, Optional[str]]:
        if not file_content:
            return False, "File is empty"
        try:
            try:
                text = file_content.decode('utf-8')
            except UnicodeDecodeError:
                text = file_content.decode('latin-1')
            json.loads(text)
            return True, None
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON: {e}"
        except Exception as e:
            return False, str(e)
