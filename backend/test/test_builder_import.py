"""
Tests for Feature 72 — Smart Import from Resume Builders.

Covers:
  72A: Platform-specific prompt hints injected into build_conversion_prompt
  72A: Unknown source_platform silently falls back to generic
  72B: /formats/parse returns structured preview data
  72B: /formats/upload accepts source_platform query param
  72C: Kickresume JSON with nested skills → prompt contains skill context
  72C: Unknown source_platform → no error (generic fallback)
  72C: Malformed JSON → 422
"""

import io
import json

import pytest
from httpx import AsyncClient

from app.services.document_converter_service import (
    ALLOWED_SOURCE_PLATFORMS,
    DocumentConverterService,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────

# Kickresume-style JSON with nested skill categories
_KICKRESUME_JSON = json.dumps({
    "basics": {
        "name": "Jane Smith",
        "email": "jane@example.com",
        "phone": "+1-555-0100",
        "summary": "Senior software engineer with 6 years experience.",
    },
    "work": [
        {
            "company": "Acme Corp",
            "position": "Senior Engineer",
            "startDate": "2020-01",
            "endDate": "Present",
            "highlights": ["Built distributed systems", "Led a team of 4"],
        }
    ],
    "education": [
        {
            "institution": "State University",
            "studyType": "B.S.",
            "area": "Computer Science",
            "endDate": "2018-05",
        }
    ],
    # Kickresume nests skills in categories
    "skills": [
        {"name": "Programming", "keywords": ["Python", "Go", "TypeScript"]},
        {"name": "Infrastructure", "keywords": ["Docker", "Kubernetes", "Terraform"]},
    ],
})

# Novoresume-style JSON with YYYY/MM dates
_NOVORESUME_JSON = json.dumps({
    "basics": {"name": "Alex Lee", "email": "alex@example.com"},
    "work": [
        {
            "company": "Tech Ltd",
            "position": "Engineer",
            "startDate": "2021/03",
            "endDate": "2023/08",
        }
    ],
    "skills": [{"name": "Languages", "keywords": ["Python", "Rust"]}],
})

# Structurally valid JSON Resume (unknown source_platform)
_GENERIC_JSON = json.dumps({
    "basics": {"name": "Bob Jones", "email": "bob@example.com"},
    "work": [],
    "skills": [{"name": "Tools", "keywords": ["Git", "Linux"]}],
})

# Malformed — not valid JSON
_MALFORMED = b"{ this is not valid json !!!"


# ── Service unit tests ─────────────────────────────────────────────────────────


class TestDocumentConverterServicePlatforms:
    def _svc(self) -> DocumentConverterService:
        return DocumentConverterService()

    def _minimal_structure(self, skills: list[str] | None = None) -> dict:
        return {
            "contact": {"name": "Test User", "email": "test@example.com"},
            "experience": [],
            "education": [],
            "skills": skills or ["Python", "Go"],
            "projects": [],
            "summary": None,
            "raw_text": "",
            "metadata": {},
        }

    def test_allowed_platforms_set(self):
        assert "kickresume" in ALLOWED_SOURCE_PLATFORMS
        assert "resumeio" in ALLOWED_SOURCE_PLATFORMS
        assert "novoresume" in ALLOWED_SOURCE_PLATFORMS

    def test_kickresume_hint_injected_in_system_prompt(self):
        svc = self._svc()
        msgs = svc.build_conversion_prompt(
            self._minimal_structure(), "json", source_platform="kickresume"
        )
        system = msgs[0]["content"]
        assert "Kickresume" in system
        assert "nested" in system.lower() or "skill" in system.lower()

    def test_resumeio_hint_injected_in_system_prompt(self):
        svc = self._svc()
        msgs = svc.build_conversion_prompt(
            self._minimal_structure(), "json", source_platform="resumeio"
        )
        system = msgs[0]["content"]
        assert "Resume.io" in system or "resumeio" in system.lower()

    def test_novoresume_hint_injected_in_system_prompt(self):
        svc = self._svc()
        msgs = svc.build_conversion_prompt(
            self._minimal_structure(), "json", source_platform="novoresume"
        )
        system = msgs[0]["content"]
        assert "Novoresume" in system
        assert "YYYY/MM" in system or "date" in system.lower()

    def test_unknown_platform_no_hint_injected(self):
        svc = self._svc()
        msgs = svc.build_conversion_prompt(
            self._minimal_structure(), "json", source_platform="unknown_builder_xyz"
        )
        system = msgs[0]["content"]
        # Should not contain any platform-specific jargon
        assert "Kickresume" not in system
        assert "Resume.io" not in system
        assert "Novoresume" not in system

    def test_no_platform_uses_generic_prompt(self):
        svc = self._svc()
        msgs = svc.build_conversion_prompt(self._minimal_structure(), "json")
        system = msgs[0]["content"]
        assert "LaTeX resume generator" in system

    def test_skills_present_in_user_message(self):
        """Skills from the structure dict appear in the user message."""
        svc = self._svc()
        skills = ["Python", "Go", "Docker"]
        msgs = svc.build_conversion_prompt(
            self._minimal_structure(skills=skills), "json", source_platform="kickresume"
        )
        user = msgs[1]["content"]
        assert "Python" in user


# ── Endpoint tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestBuilderImportEndpoints:
    async def test_parse_endpoint_returns_preview_for_json_resume(self, client: AsyncClient):
        """/formats/parse returns structured preview for a valid JSON Resume file."""
        resp = await client.post(
            "/formats/parse",
            files={"file": ("resume.json", _KICKRESUME_JSON.encode(), "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["format"] == "json"
        assert data["name"] == "Jane Smith"
        assert data["experience_count"] == 1
        assert data["education_count"] == 1
        assert isinstance(data["skills"], list)
        assert len(data["skills"]) > 0

    async def test_parse_endpoint_malformed_json_returns_422(self, client: AsyncClient):
        """/formats/parse rejects malformed JSON files."""
        resp = await client.post(
            "/formats/parse",
            files={"file": ("bad.json", _MALFORMED, "application/json")},
        )
        assert resp.status_code == 422

    async def test_upload_accepts_known_source_platform(self, client: AsyncClient):
        """/formats/upload accepts source_platform=kickresume without error."""
        resp = await client.post(
            "/formats/upload?source_platform=kickresume",
            files={"file": ("resume.json", _KICKRESUME_JSON.encode(), "application/json")},
        )
        # Should succeed — returns direct or queued job
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    async def test_upload_unknown_source_platform_falls_back_to_generic(self, client: AsyncClient):
        """Unknown source_platform is silently ignored — no error raised."""
        resp = await client.post(
            "/formats/upload?source_platform=some_unknown_builder",
            files={"file": ("resume.json", _GENERIC_JSON.encode(), "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    async def test_upload_malformed_json_returns_422(self, client: AsyncClient):
        """Malformed JSON file to /formats/upload returns 422."""
        resp = await client.post(
            "/formats/upload",
            files={"file": ("bad.json", _MALFORMED, "application/json")},
        )
        assert resp.status_code == 422
