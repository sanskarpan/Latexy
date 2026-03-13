"""Tests for cover letter worker — prompt building and task event flow."""

import uuid
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

import app.workers.cover_letter_worker as clw
from app.workers.cover_letter_worker import (
    _LATEX_RE,
    _build_cover_letter_prompt,
)

# ── Celery eager mode ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _celery_eager():
    from app.core.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


# ── Helpers ───────────────────────────────────────────────────────────────────

RESUME_LATEX = r"\documentclass{article}\begin{document}Resume\end{document}"
JOB_DESC = "We need a Python developer with Django experience"

LATEX_WITH_DELIMITERS = (
    r"<<<LATEX>>>\documentclass{article}\begin{document}"
    r"Dear Manager\end{document}<<<END_LATEX>>>"
)


def _make_stream(text: str, tokens_total: int = 500) -> Iterator:
    """Build a fake OpenAI streaming response from a string."""
    chunks = []
    for char in text:
        chunk = MagicMock()
        chunk.usage = None
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = char
        chunks.append(chunk)
    # Final usage chunk
    usage_chunk = MagicMock()
    usage_chunk.usage = MagicMock(total_tokens=tokens_total)
    usage_chunk.choices = []
    chunks.append(usage_chunk)
    return iter(chunks)


def _mock_settings(ms):
    ms.OPENAI_API_KEY = "sk-test-key"
    ms.OPENAI_MODEL = "gpt-4o-mini"
    ms.OPENAI_MAX_TOKENS = 4000


@pytest.fixture
def mock_publish():
    with patch("app.workers.cover_letter_worker.publish_event") as m:
        yield m


@pytest.fixture
def mock_job_result():
    with patch("app.workers.cover_letter_worker.publish_job_result") as m:
        yield m


@pytest.fixture
def mock_cancelled():
    with patch("app.workers.cover_letter_worker.is_cancelled", return_value=False):
        yield


@pytest.fixture
def mock_save():
    with patch("app.workers.cover_letter_worker._save_cover_letter_content") as m:
        yield m


@pytest.fixture
def mock_openai():
    with patch("app.workers.cover_letter_worker.openai.OpenAI") as MockOpenAI:
        yield MockOpenAI


# ── Prompt building tests ────────────────────────────────────────────────


class TestBuildCoverLetterPrompt:
    def test_basic_prompt(self):
        system, user = _build_cover_letter_prompt(
            resume_latex=RESUME_LATEX,
            job_description=JOB_DESC,
            company_name="Acme Corp",
            role_title="Senior Engineer",
            tone="formal",
            length_preference="3_paragraphs",
        )

        assert "expert career coach" in system
        assert "professional and formal" in system
        assert "3 focused paragraphs" in system
        assert "<<<LATEX>>>" in system
        assert "Company: Acme Corp" in user
        assert "Role: Senior Engineer" in user
        assert JOB_DESC in user

    def test_conversational_tone(self):
        system, _ = _build_cover_letter_prompt(
            resume_latex="test", job_description="test",
            company_name=None, role_title=None,
            tone="conversational", length_preference="4_paragraphs",
        )
        assert "warm, approachable" in system
        assert "4 paragraphs" in system

    def test_enthusiastic_tone(self):
        system, _ = _build_cover_letter_prompt(
            resume_latex="test", job_description="test",
            company_name=None, role_title=None,
            tone="enthusiastic", length_preference="detailed",
        )
        assert "energetic, passionate" in system
        assert "5+ paragraphs" in system

    def test_no_company_or_role(self):
        _, user = _build_cover_letter_prompt(
            resume_latex="test", job_description="test jd",
            company_name=None, role_title=None,
            tone="formal", length_preference="3_paragraphs",
        )
        assert "Company:" not in user
        assert "Role:" not in user


# ── LaTeX extraction regex ───────────────────────────────────────────────


class TestLatexExtraction:
    def test_extract_latex(self):
        text = "Preamble <<<LATEX>>>\\documentclass{article}<<<END_LATEX>>> done"
        match = _LATEX_RE.search(text)
        assert match is not None

    def test_no_delimiters(self):
        text = "\\documentclass{article}\\begin{document}Hi\\end{document}"
        assert _LATEX_RE.search(text) is None

    def test_multiline_content(self):
        text = "<<<LATEX>>>\nHello\n<<<END_LATEX>>>"
        match = _LATEX_RE.search(text)
        assert match is not None
        assert "Hello" in match.group(1)


# ── Task event flow ──────────────────────────────────────────────────────


class TestCoverLetterTask:
    def test_success_flow(
        self, mock_publish, mock_job_result, mock_cancelled, mock_save, mock_openai
    ):
        with patch("app.workers.cover_letter_worker.settings") as ms:
            _mock_settings(ms)
            mock_openai.return_value.chat.completions.create.return_value = (
                _make_stream(LATEX_WITH_DELIMITERS)
            )

            result = clw.generate_cover_letter_task(
                RESUME_LATEX, JOB_DESC,
                job_id="test-job-123",
                user_id="test-user-456",
                cover_letter_id="test-cl-789",
                company_name="Test Corp",
                tone="formal",
                length_preference="3_paragraphs",
            )

        assert result["success"] is True
        assert result["job_id"] == "test-job-123"
        assert result["cover_letter_id"] == "test-cl-789"
        assert result["tokens_used"] == 500

        # Verify event sequence
        event_types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.started" in event_types
        assert "job.progress" in event_types
        assert "llm.token" in event_types
        assert "llm.complete" in event_types
        assert "job.completed" in event_types

        # Verify save was called with extracted LaTeX (without delimiters)
        mock_save.assert_called_once()
        saved_content = mock_save.call_args[0][1]
        assert "Dear Manager" in saved_content
        assert "<<<LATEX>>>" not in saved_content

    def test_no_api_key(self, mock_publish, mock_job_result, mock_cancelled):
        with patch("app.workers.cover_letter_worker.settings") as ms:
            _mock_settings(ms)
            ms.OPENAI_API_KEY = ""

            result = clw.generate_cover_letter_task(
                RESUME_LATEX, JOB_DESC, job_id="test-job",
            )

        assert result["success"] is False
        assert "API key" in result["error"]
        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.failed" in types
        assert "job.started" not in types

    def test_cancellation(
        self, mock_publish, mock_job_result, mock_save, mock_openai
    ):
        with (
            patch("app.workers.cover_letter_worker.settings") as ms,
            patch("app.workers.cover_letter_worker.is_cancelled", return_value=True),
        ):
            _mock_settings(ms)
            # Need 21+ tokens to trigger cancellation check at token 20
            mock_openai.return_value.chat.completions.create.return_value = (
                _make_stream("x" * 21)
            )

            result = clw.generate_cover_letter_task(
                RESUME_LATEX, JOB_DESC, job_id="test-job",
            )

        assert result["success"] is False
        assert result.get("cancelled") is True

    def test_no_delimiters_uses_full_text(
        self, mock_publish, mock_job_result, mock_cancelled, mock_save, mock_openai
    ):
        raw_text = r"\documentclass{article}\begin{document}No delimiters\end{document}"
        with patch("app.workers.cover_letter_worker.settings") as ms:
            _mock_settings(ms)
            mock_openai.return_value.chat.completions.create.return_value = (
                _make_stream(raw_text)
            )

            result = clw.generate_cover_letter_task(
                RESUME_LATEX, JOB_DESC,
                job_id="test-job",
                cover_letter_id="test-cl",
            )

        assert result["success"] is True
        mock_save.assert_called_once_with("test-cl", raw_text)

    def test_completed_event_has_null_pdf_job_id(
        self, mock_publish, mock_job_result, mock_cancelled, mock_save, mock_openai
    ):
        """job.completed event must emit pdf_job_id: None so the frontend auto-compiles."""
        with patch("app.workers.cover_letter_worker.settings") as ms:
            _mock_settings(ms)
            mock_openai.return_value.chat.completions.create.return_value = (
                _make_stream(LATEX_WITH_DELIMITERS)
            )

            clw.generate_cover_letter_task(
                RESUME_LATEX, JOB_DESC,
                job_id="test-pdf-null",
                cover_letter_id="test-cl",
            )

        completed_calls = [
            c for c in mock_publish.call_args_list if c.args[1] == "job.completed"
        ]
        assert len(completed_calls) == 1
        payload = completed_calls[0].args[2]
        assert payload["pdf_job_id"] is None

    def test_soft_time_limit(self, mock_publish, mock_job_result, mock_cancelled, mock_openai):
        from celery.exceptions import SoftTimeLimitExceeded

        with patch("app.workers.cover_letter_worker.settings") as ms:
            _mock_settings(ms)
            mock_openai.return_value.chat.completions.create.side_effect = (
                SoftTimeLimitExceeded()
            )

            result = clw.generate_cover_letter_task(
                RESUME_LATEX, JOB_DESC, job_id="test-job",
            )

        assert result["success"] is False
        assert "time limit" in result["error"]
        failed_calls = [
            c for c in mock_publish.call_args_list if c.args[1] == "job.failed"
        ]
        assert len(failed_calls) == 1
        assert failed_calls[0].args[2]["error_code"] == "timeout"
