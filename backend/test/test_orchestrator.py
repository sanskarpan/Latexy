"""
Unit tests for app.workers.orchestrator.

Tests the individual stage helpers (_run_ats_stage, JSON parse logic) and the
main task entry-point guards (missing API key, cancellation).  OpenAI and
subprocess.Popen are mocked so no live services are required.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.celery_app import celery_app
from app.workers.orchestrator import (
    _run_ats_stage,
    optimize_and_compile_task,
    submit_optimize_and_compile,
)

GOOD_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\begin{document}
\section*{Experience}
Software Engineer at Acme. Built distributed systems with Python and AWS.
\end{document}
"""
JD = "Software engineer role requiring Python, AWS, Docker, Kubernetes."


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def eager_celery():
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


@pytest.fixture
def mock_publish():
    with patch("app.workers.orchestrator.publish_event") as m:
        yield m


@pytest.fixture
def mock_result_store():
    with patch("app.workers.orchestrator.publish_job_result") as m:
        yield m


@pytest.fixture
def mock_not_cancelled():
    with patch("app.workers.orchestrator.is_cancelled", return_value=False) as m:
        yield m


@pytest.fixture
def mock_cancelled():
    with patch("app.workers.orchestrator.is_cancelled", return_value=True) as m:
        yield m


@pytest.fixture
def mock_scoring_service():
    fake = MagicMock()
    fake.overall_score = 78.0
    fake.category_scores = {"formatting": 80, "content": 76}
    fake.recommendations = ["Add more keywords"]
    fake.strengths = ["Good structure"]
    fake.warnings = []
    with patch(
        "app.workers.orchestrator.ats_scoring_service.score_resume",
        new_callable=AsyncMock,
        return_value=fake,
    ):
        yield fake


def _make_openai_stream(tokens: list[str], tokens_total: int = 100):
    """Build a fake OpenAI streaming iterator."""
    chunks = []
    for token in tokens:
        chunk = MagicMock()
        chunk.usage = None
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = token
        chunks.append(chunk)

    # Final usage chunk
    usage_chunk = MagicMock()
    usage_chunk.usage = MagicMock(total_tokens=tokens_total)
    usage_chunk.choices = []
    chunks.append(usage_chunk)

    return iter(chunks)


def _make_popen(returncode: int = 0, stdout_lines: list[str] | None = None):
    """Build a mock subprocess.Popen object."""
    mock_proc = MagicMock()
    mock_proc.returncode = returncode
    mock_proc.stdout = iter(stdout_lines or ["This is pdflatex output\n"])
    mock_proc.wait.return_value = None
    mock_proc.kill.return_value = None
    return mock_proc


# ── _run_ats_stage ─────────────────────────────────────────────────────────────

class TestRunAtsStage:

    def test_returns_score_and_details_on_success(self, mock_scoring_service):
        score, details = _run_ats_stage(str(uuid.uuid4()), GOOD_LATEX, JD)
        assert score == 78.0
        assert isinstance(details, dict)

    def test_score_is_float(self, mock_scoring_service):
        score, _ = _run_ats_stage(str(uuid.uuid4()), GOOD_LATEX, JD)
        assert isinstance(score, float)

    def test_details_has_category_scores(self, mock_scoring_service):
        _, details = _run_ats_stage(str(uuid.uuid4()), GOOD_LATEX, JD)
        assert "category_scores" in details

    def test_details_has_recommendations(self, mock_scoring_service):
        _, details = _run_ats_stage(str(uuid.uuid4()), GOOD_LATEX, JD)
        assert "recommendations" in details

    def test_details_has_strengths(self, mock_scoring_service):
        _, details = _run_ats_stage(str(uuid.uuid4()), GOOD_LATEX, JD)
        assert "strengths" in details

    def test_details_has_warnings(self, mock_scoring_service):
        _, details = _run_ats_stage(str(uuid.uuid4()), GOOD_LATEX, JD)
        assert "warnings" in details

    def test_none_job_description_accepted(self, mock_scoring_service):
        score, details = _run_ats_stage(str(uuid.uuid4()), GOOD_LATEX, None)
        assert score == 78.0

    def test_scoring_exception_returns_zero_score(self):
        with patch(
            "app.workers.orchestrator.ats_scoring_service.score_resume",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Scoring broke"),
        ):
            score, details = _run_ats_stage(str(uuid.uuid4()), GOOD_LATEX, JD)
        assert score == 0.0
        assert details == {}

    def test_scoring_exception_does_not_propagate(self):
        with patch(
            "app.workers.orchestrator.ats_scoring_service.score_resume",
            new_callable=AsyncMock,
            side_effect=ValueError("Unexpected"),
        ):
            try:
                _run_ats_stage(str(uuid.uuid4()), GOOD_LATEX, JD)
            except Exception as exc:
                pytest.fail(f"_run_ats_stage raised unexpectedly: {exc}")

    def test_scoring_service_receives_latex_content(self, mock_scoring_service):
        job_id = str(uuid.uuid4())
        _run_ats_stage(job_id, GOOD_LATEX, JD)
        # Check the AsyncMock was called with the right latex_content
        with patch(
            "app.workers.orchestrator.ats_scoring_service.score_resume",
            new_callable=AsyncMock,
            return_value=mock_scoring_service,
        ) as m:
            _run_ats_stage(job_id, GOOD_LATEX, JD)
            call_kwargs = m.call_args[1]
            assert call_kwargs.get("latex_content") == GOOD_LATEX


# ── main task — missing API key guard ─────────────────────────────────────────

class TestOrchestratorMissingApiKey:

    def test_no_api_key_publishes_job_failed(self, mock_publish, mock_result_store):
        with patch("app.workers.orchestrator.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.OPENAI_MODEL = "gpt-4o-mini"
            mock_settings.OPENAI_MAX_TOKENS = 4000
            mock_settings.OPENAI_TEMPERATURE = 0.7
            mock_settings.TEMP_DIR = MagicMock()
            mock_settings.LATEX_DOCKER_IMAGE = "texlive/texlive:latest"
            res = optimize_and_compile_task.apply(
                args=[GOOD_LATEX, JD], kwargs={"job_id": str(uuid.uuid4()), "user_api_key": None}
            ).result
        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.failed" in types

    def test_no_api_key_returns_failure(self, mock_publish, mock_result_store):
        with patch("app.workers.orchestrator.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.OPENAI_MODEL = "gpt-4o-mini"
            mock_settings.OPENAI_MAX_TOKENS = 4000
            mock_settings.OPENAI_TEMPERATURE = 0.7
            mock_settings.TEMP_DIR = MagicMock()
            mock_settings.LATEX_DOCKER_IMAGE = "texlive/texlive:latest"
            res = optimize_and_compile_task.apply(
                args=[GOOD_LATEX, JD], kwargs={"job_id": str(uuid.uuid4()), "user_api_key": None}
            ).result
        assert res["success"] is False

    def test_no_api_key_does_not_publish_job_started(self, mock_publish, mock_result_store):
        with patch("app.workers.orchestrator.settings") as mock_settings:
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.OPENAI_MODEL = "gpt-4o-mini"
            mock_settings.OPENAI_MAX_TOKENS = 4000
            mock_settings.OPENAI_TEMPERATURE = 0.7
            mock_settings.TEMP_DIR = MagicMock()
            mock_settings.LATEX_DOCKER_IMAGE = "texlive/texlive:latest"
            optimize_and_compile_task.apply(
                args=[GOOD_LATEX, JD], kwargs={"job_id": str(uuid.uuid4()), "user_api_key": None}
            )
        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.started" not in types

    def test_user_api_key_overrides_missing_default(
        self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service
    ):
        """If user_api_key is provided, the task should proceed past the key guard."""
        # Build a minimal LLM response: JSON-parseable LaTeX
        llm_response_json = json.dumps({"optimized_latex": GOOD_LATEX, "changes": []})
        tokens = list(llm_response_json)

        mock_proc = _make_popen(returncode=0)
        with (
            patch("app.workers.orchestrator.settings") as mock_settings,
            patch("app.workers.orchestrator.openai.OpenAI") as mock_openai_cls,
            patch("app.workers.orchestrator.subprocess.Popen", return_value=mock_proc),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            mock_settings.OPENAI_API_KEY = ""
            mock_settings.OPENAI_MODEL = "gpt-4o-mini"
            mock_settings.OPENAI_MAX_TOKENS = 4000
            mock_settings.OPENAI_TEMPERATURE = 0.7
            mock_settings.TEMP_DIR = MagicMock()
            mock_settings.TEMP_DIR.__truediv__ = lambda self, x: MagicMock()
            mock_settings.LATEX_DOCKER_IMAGE = "texlive/texlive:latest"

            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = _make_openai_stream(tokens)

            res = optimize_and_compile_task.apply(
                args=[GOOD_LATEX, JD],
                kwargs={"job_id": str(uuid.uuid4()), "user_api_key": "sk-real-key"},
            ).result

        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.started" in types


# ── full pipeline with all mocks ──────────────────────────────────────────────

class TestOrchestratorFullPipeline:

    def _run_full(self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service, cancelled=False):
        """Helper to run the orchestrator with all external deps mocked."""
        job_id = str(uuid.uuid4())
        llm_response = json.dumps({"optimized_latex": GOOD_LATEX, "changes": [
            {"section": "summary", "change_type": "added", "reason": "Added summary"}
        ]})
        tokens = list(llm_response)

        mock_proc = _make_popen(
            returncode=0,
            stdout_lines=["pdflatex output line\n", "No errors\n"],
        )

        # Use return_value=False when not testing cancellation to avoid
        # StopIteration from an exhausted iterator (token list can be long).
        if cancelled:
            cancel_flag = [False] * 5 + [True] + [False] * 100
            cancel_iter = iter(cancel_flag)
            is_cancelled_patch = patch(
                "app.workers.orchestrator.is_cancelled",
                side_effect=lambda _: next(cancel_iter),
            )
        else:
            is_cancelled_patch = patch(
                "app.workers.orchestrator.is_cancelled",
                return_value=False,
            )

        with (
            patch("app.workers.orchestrator.openai.OpenAI") as mock_openai_cls,
            patch("app.workers.orchestrator.subprocess.Popen", return_value=mock_proc),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=12345)),
            is_cancelled_patch,
        ):
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = _make_openai_stream(tokens)

            res = optimize_and_compile_task.apply(
                args=[GOOD_LATEX, JD],
                kwargs={"job_id": job_id, "user_api_key": "sk-test-key"},
            ).result
        return res, mock_publish.call_args_list

    def test_successful_pipeline_returns_success(
        self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service
    ):
        res, _ = self._run_full(mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service)
        assert res["success"] is True

    def test_successful_pipeline_has_job_id(
        self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service
    ):
        res, _ = self._run_full(mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service)
        uuid.UUID(res["job_id"])

    def test_successful_pipeline_has_ats_score(
        self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service
    ):
        res, _ = self._run_full(mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service)
        assert "ats_score" in res
        assert isinstance(res["ats_score"], float)

    def test_successful_pipeline_has_optimized_latex(
        self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service
    ):
        res, _ = self._run_full(mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service)
        assert "optimized_latex" in res
        assert len(res["optimized_latex"]) > 0

    def test_successful_pipeline_has_tokens_used(
        self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service
    ):
        res, _ = self._run_full(mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service)
        assert "tokens_used" in res
        assert isinstance(res["tokens_used"], int)

    def test_successful_pipeline_has_compilation_time(
        self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service
    ):
        res, _ = self._run_full(mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service)
        assert "compilation_time" in res
        assert res["compilation_time"] >= 0

    def test_successful_pipeline_result_stored(
        self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service
    ):
        self._run_full(mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service)
        mock_result_store.assert_called_once()

    def test_successful_pipeline_publishes_job_started(
        self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service
    ):
        _, calls = self._run_full(mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service)
        types = [c.args[1] for c in calls]
        assert "job.started" in types

    def test_successful_pipeline_publishes_job_completed(
        self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service
    ):
        _, calls = self._run_full(mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service)
        types = [c.args[1] for c in calls]
        assert "job.completed" in types

    def test_successful_pipeline_publishes_job_progress(
        self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service
    ):
        _, calls = self._run_full(mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service)
        types = [c.args[1] for c in calls]
        assert "job.progress" in types

    def test_successful_pipeline_publishes_llm_complete(
        self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service
    ):
        _, calls = self._run_full(mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service)
        types = [c.args[1] for c in calls]
        assert "llm.complete" in types

    def test_pdf_job_id_matches_job_id(
        self, mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service
    ):
        res, _ = self._run_full(mock_publish, mock_result_store, mock_not_cancelled, mock_scoring_service)
        assert res["pdf_job_id"] == res["job_id"]


# ── JSON parse fallback ───────────────────────────────────────────────────────

class TestLLMJsonParsing:
    """The orchestrator tries JSON first, then regex fallback."""

    def _run_with_tokens(self, tokens, mock_publish, mock_result_store, mock_scoring_service):
        job_id = str(uuid.uuid4())
        mock_proc = _make_popen(returncode=0)
        with (
            patch("app.workers.orchestrator.openai.OpenAI") as mock_openai_cls,
            patch("app.workers.orchestrator.subprocess.Popen", return_value=mock_proc),
            patch("app.workers.orchestrator.is_cancelled", return_value=False),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = _make_openai_stream(tokens)
            res = optimize_and_compile_task.apply(
                args=[GOOD_LATEX, JD],
                kwargs={"job_id": job_id, "user_api_key": "sk-test"},
            ).result
        return res

    def test_valid_json_response_uses_optimized_latex(
        self, mock_publish, mock_result_store, mock_scoring_service
    ):
        target_latex = "\\documentclass{article}\\begin{document}Optimized\\end{document}"
        payload = json.dumps({"optimized_latex": target_latex, "changes": []})
        res = self._run_with_tokens(list(payload), mock_publish, mock_result_store, mock_scoring_service)
        assert res["optimized_latex"] == target_latex

    def test_valid_json_response_extracts_changes(
        self, mock_publish, mock_result_store, mock_scoring_service
    ):
        changes = [{"section": "summary", "change_type": "added", "reason": "Better ATS"}]
        payload = json.dumps({"optimized_latex": GOOD_LATEX, "changes": changes})
        res = self._run_with_tokens(list(payload), mock_publish, mock_result_store, mock_scoring_service)
        assert len(res["changes_made"]) == 1
        assert res["changes_made"][0]["section"] == "summary"

    def test_invalid_json_falls_back_to_original(
        self, mock_publish, mock_result_store, mock_scoring_service
    ):
        # Pure garbage — not parseable as JSON and no regex match
        res = self._run_with_tokens(list("not json at all"), mock_publish, mock_result_store, mock_scoring_service)
        # Falls back to original latex_content
        assert res["success"] is True  # pipeline continues
        assert res["optimized_latex"] == GOOD_LATEX


# ── submit_optimize_and_compile ───────────────────────────────────────────────

class TestSubmitOptimizeAndCompile:

    def test_dispatches_task(self):
        job_id = str(uuid.uuid4())
        with patch.object(optimize_and_compile_task, "apply_async") as mock_apply:
            submit_optimize_and_compile(
                latex_content=GOOD_LATEX,
                job_description=JD,
                job_id=job_id,
            )
            mock_apply.assert_called_once()

    def test_returns_job_id(self):
        job_id = str(uuid.uuid4())
        with patch.object(optimize_and_compile_task, "apply_async"):
            result = submit_optimize_and_compile(
                latex_content=GOOD_LATEX,
                job_description=JD,
                job_id=job_id,
            )
            assert result == job_id

    def test_queues_to_combined_queue(self):
        job_id = str(uuid.uuid4())
        with patch.object(optimize_and_compile_task, "apply_async") as mock_apply:
            submit_optimize_and_compile(
                latex_content=GOOD_LATEX,
                job_description=JD,
                job_id=job_id,
            )
            kwargs = mock_apply.call_args[1]
            assert kwargs["queue"] == "combined"

    def test_kwargs_include_job_id(self):
        job_id = str(uuid.uuid4())
        with patch.object(optimize_and_compile_task, "apply_async") as mock_apply:
            submit_optimize_and_compile(
                latex_content=GOOD_LATEX,
                job_description=JD,
                job_id=job_id,
            )
            kwargs = mock_apply.call_args[1]["kwargs"]
            assert kwargs["job_id"] == job_id

    def test_kwargs_include_user_id(self):
        job_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        with patch.object(optimize_and_compile_task, "apply_async") as mock_apply:
            submit_optimize_and_compile(
                latex_content=GOOD_LATEX,
                job_description=JD,
                job_id=job_id,
                user_id=user_id,
            )
            kwargs = mock_apply.call_args[1]["kwargs"]
            assert kwargs["user_id"] == user_id
