"""
LinkedIn Profile Import tests (Feature 16).

Tests cover:
- document_converter_service: source_hint="linkedin" uses LINKEDIN_SYSTEM_PROMPT
- source_hint=None / "resume" uses the default system prompt
- POST /formats/upload with source_hint="linkedin" routes correctly
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.services.document_converter_service import (
    LINKEDIN_SYSTEM_PROMPT,
    document_converter_service,
)

# ── Minimal resume structure fixture ──────────────────────────────────────────

STRUCTURE = {
    "contact": {"name": "Alice Lee", "email": "alice@example.com"},
    "raw_text": "Alice Lee\nalice@example.com\n\nExperience\n\nSenior Engineer at Acme (2020–Present)",
    "experience": [
        {
            "title": "Senior Engineer",
            "company": "Acme Corp",
            "start_date": "2020",
            "end_date": "Present",
            "current": True,
            "description": ["Owned backend systems"],
        }
    ],
    "education": [
        {
            "degree": "B.S. Computer Science",
            "institution": "State University",
            "graduation_date": "2019",
        }
    ],
    "skills": ["Python", "TypeScript", "Docker"],
}

SAMPLE_TEXT = b"Alice Lee\nalice@example.com\n\nExperience\nSenior Engineer at Acme\n2020 - Present\nBuilt things\n\nSkills\nPython"


# ── Service unit tests ─────────────────────────────────────────────────────────


class TestLinkedInPromptSelection:
    def test_linkedin_hint_uses_linkedin_system_prompt(self):
        """source_hint='linkedin' must inject LINKEDIN_SYSTEM_PROMPT as system message."""
        messages = document_converter_service.build_conversion_prompt(
            STRUCTURE, "pdf", source_hint="linkedin"
        )
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == LINKEDIN_SYSTEM_PROMPT

    def test_no_hint_uses_default_system_prompt(self):
        """source_hint=None must use the default system prompt (not LinkedIn)."""
        messages = document_converter_service.build_conversion_prompt(STRUCTURE, "pdf")
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] != LINKEDIN_SYSTEM_PROMPT
        assert "professional LaTeX resume generator" in messages[0]["content"]

    def test_resume_hint_uses_default_system_prompt(self):
        """source_hint='resume' must use the default system prompt (not LinkedIn)."""
        messages = document_converter_service.build_conversion_prompt(
            STRUCTURE, "pdf", source_hint="resume"
        )
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] != LINKEDIN_SYSTEM_PROMPT

    def test_unknown_hint_uses_default_system_prompt(self):
        """An unrecognised source_hint must fall back to the default prompt."""
        messages = document_converter_service.build_conversion_prompt(
            STRUCTURE, "pdf", source_hint="github"
        )
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] != LINKEDIN_SYSTEM_PROMPT

    def test_linkedin_prompt_mentions_recommendations(self):
        """LinkedIn prompt should instruct the LLM to ignore recommendations."""
        assert "Recommendations" in LINKEDIN_SYSTEM_PROMPT
        assert "ignore" in LINKEDIN_SYSTEM_PROMPT.lower()

    def test_linkedin_prompt_mentions_experience_section(self):
        """LinkedIn prompt should describe the Experience section structure."""
        assert "Experience" in LINKEDIN_SYSTEM_PROMPT

    def test_linkedin_prompt_mentions_skills(self):
        """LinkedIn prompt should handle Skills and Languages."""
        assert "Skills" in LINKEDIN_SYSTEM_PROMPT
        assert "Languages" in LINKEDIN_SYSTEM_PROMPT

    def test_linkedin_prompt_returns_two_messages(self):
        """build_conversion_prompt always returns exactly 2 messages."""
        messages = document_converter_service.build_conversion_prompt(
            STRUCTURE, "pdf", source_hint="linkedin"
        )
        assert len(messages) == 2
        assert messages[1]["role"] == "user"

    def test_default_prompt_returns_two_messages(self):
        """Default path also returns exactly 2 messages."""
        messages = document_converter_service.build_conversion_prompt(STRUCTURE, "pdf")
        assert len(messages) == 2


# ── Endpoint tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestUploadWithSourceHint:
    async def test_upload_with_linkedin_hint_queues_job(self, client: AsyncClient):
        """source_hint=linkedin for a text file queues a job (not direct)."""
        with patch(
            "app.workers.converter_worker.submit_document_conversion", return_value=None
        ) as mock_submit, patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ):
            resp = await client.post(
                "/formats/upload",
                files={"file": ("profile.txt", SAMPLE_TEXT, "text/plain")},
                data={"source_hint": "linkedin"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["is_direct"] is False
        assert data["job_id"] is not None

        # Verify source_hint reached the worker submission call
        call_kwargs = mock_submit.call_args.kwargs
        assert call_kwargs.get("source_hint") == "linkedin"

    async def test_upload_without_hint_passes_none_to_worker(self, client: AsyncClient):
        """Omitting source_hint should pass None to submit_document_conversion."""
        with patch(
            "app.workers.converter_worker.submit_document_conversion", return_value=None
        ) as mock_submit, patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ):
            resp = await client.post(
                "/formats/upload",
                files={"file": ("resume.txt", SAMPLE_TEXT, "text/plain")},
            )

        assert resp.status_code == 200
        call_kwargs = mock_submit.call_args.kwargs
        assert call_kwargs.get("source_hint") is None

    async def test_upload_with_resume_hint_passes_through(self, client: AsyncClient):
        """source_hint='resume' should be forwarded to the worker as-is."""
        with patch(
            "app.workers.converter_worker.submit_document_conversion", return_value=None
        ) as mock_submit, patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ):
            resp = await client.post(
                "/formats/upload",
                files={"file": ("resume.txt", SAMPLE_TEXT, "text/plain")},
                data={"source_hint": "resume"},
            )

        assert resp.status_code == 200
        call_kwargs = mock_submit.call_args.kwargs
        assert call_kwargs.get("source_hint") == "resume"

    async def test_latex_with_linkedin_hint_still_direct(self, client: AsyncClient):
        """LaTeX files always pass through directly, even with source_hint=linkedin."""
        LATEX = (
            rb"\documentclass{article}\begin{document}Alice Lee\end{document}"
        )
        resp = await client.post(
            "/formats/upload",
            files={"file": ("profile.tex", LATEX, "text/plain")},
            data={"source_hint": "linkedin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_direct"] is True
        assert data["latex_content"] is not None


# ── Converter worker unit test ─────────────────────────────────────────────────


class TestConverterWorkerSourceHint:
    def test_worker_run_passes_source_hint_to_service(self):
        """convert_document_task.run must pass source_hint to build_conversion_prompt."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(
            content=r"\documentclass{article}\begin{document}x\end{document}"
        ))]
        mock_response.usage = MagicMock(total_tokens=100)

        with patch("app.workers.converter_worker.publish_event"), \
             patch("app.workers.converter_worker.publish_job_result"), \
             patch("openai.OpenAI") as mock_openai_cls, \
             patch.object(
                 document_converter_service,
                 "build_conversion_prompt",
                 wraps=document_converter_service.build_conversion_prompt,
             ) as mock_build:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai_cls.return_value = mock_client

            from app.workers.converter_worker import convert_document_task
            # .run() calls the underlying function directly, bypassing Celery routing
            convert_document_task.run(
                extracted_data=STRUCTURE,
                source_format="pdf",
                job_id="test-job-123",
                user_id=None,
                user_api_key="sk-test",
                source_hint="linkedin",
            )

        mock_build.assert_called_once_with(STRUCTURE, "pdf", source_hint="linkedin")
