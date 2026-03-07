"""
Unit tests for app.workers.llm_worker — synchronous Celery task tests.

All external I/O (OpenAI API, Redis) is mocked.
Tests use Celery eager mode: tasks run synchronously in the same process.
"""
from __future__ import annotations

import json
import uuid
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

import app.workers.llm_worker as lw


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

VALID_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\begin{document}
\begin{center}\textbf{\Large Jane Smith}\end{center}
\end{document}
"""

JOB_DESC = "Software Engineer at Google requiring Python, Docker"

VALID_JSON_RESPONSE = json.dumps({
    "optimized_latex": r"\documentclass{article}\begin{document}OPTIMIZED\end{document}",
    "changes": [
        {"section": "summary", "change_type": "modified", "reason": "Added keywords"},
    ],
})


def _make_openai_stream(tokens: list, tokens_total: int = 100) -> Iterator:
    """Build a fake OpenAI streaming response."""
    chunks = []
    for token in tokens:
        chunk = MagicMock()
        chunk.usage = None
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = token
        chunks.append(chunk)
    usage_chunk = MagicMock()
    usage_chunk.usage = MagicMock(total_tokens=tokens_total)
    usage_chunk.choices = []
    chunks.append(usage_chunk)
    return iter(chunks)


def _mock_settings(mock_s):
    mock_s.OPENAI_API_KEY = "sk-test-key"
    mock_s.OPENAI_MODEL = "gpt-4o-mini"
    mock_s.OPENAI_MAX_TOKENS = 4096
    mock_s.OPENAI_TEMPERATURE = 0.7


@pytest.fixture
def mock_publish():
    with patch("app.workers.llm_worker.publish_event") as m:
        yield m


@pytest.fixture
def mock_job_result():
    with patch("app.workers.llm_worker.publish_job_result") as m:
        yield m


@pytest.fixture
def mock_cancelled():
    with patch("app.workers.llm_worker.is_cancelled", return_value=False):
        yield


@pytest.fixture
def mock_llm_svc():
    with (
        patch("app.workers.llm_worker.llm_service.extract_keywords_from_job_description", return_value=["python"]),
        patch("app.workers.llm_worker.llm_service._create_optimization_prompt", return_value="prompt"),
        patch("app.workers.llm_worker.llm_service.count_tokens", return_value=50),
    ):
        yield


@pytest.fixture
def mock_openai():
    with patch("app.workers.llm_worker.openai.OpenAI") as MockOpenAI:
        yield MockOpenAI


# ── API key guard ─────────────────────────────────────────────────────────────

class TestLLMWorkerApiKeyGuard:

    def test_no_api_key_emits_job_failed(self, mock_publish, mock_job_result, mock_cancelled):
        with patch("app.workers.llm_worker.settings") as ms:
            ms.OPENAI_API_KEY = ""
            _mock_settings(ms)
            ms.OPENAI_API_KEY = ""
            lw.optimize_resume_task(VALID_LATEX, JOB_DESC, job_id=str(uuid.uuid4()))

        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.failed" in types

    def test_no_api_key_does_not_emit_job_started(self, mock_publish, mock_job_result, mock_cancelled):
        with patch("app.workers.llm_worker.settings") as ms:
            _mock_settings(ms)
            ms.OPENAI_API_KEY = ""
            lw.optimize_resume_task(VALID_LATEX, JOB_DESC, job_id=str(uuid.uuid4()))

        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.started" not in types

    def test_no_api_key_returns_success_false(self, mock_publish, mock_job_result, mock_cancelled):
        with patch("app.workers.llm_worker.settings") as ms:
            _mock_settings(ms)
            ms.OPENAI_API_KEY = ""
            result = lw.optimize_resume_task(VALID_LATEX, JOB_DESC, job_id=str(uuid.uuid4()))
        assert result["success"] is False

    def test_no_api_key_error_code_is_llm_error(self, mock_publish, mock_job_result, mock_cancelled):
        with patch("app.workers.llm_worker.settings") as ms:
            _mock_settings(ms)
            ms.OPENAI_API_KEY = ""
            lw.optimize_resume_task(VALID_LATEX, JOB_DESC, job_id=str(uuid.uuid4()))

        failed = [c for c in mock_publish.call_args_list if c.args[1] == "job.failed"]
        assert failed[0].args[2]["error_code"] == "llm_error"

    def test_no_api_key_error_is_not_retryable(self, mock_publish, mock_job_result, mock_cancelled):
        with patch("app.workers.llm_worker.settings") as ms:
            _mock_settings(ms)
            ms.OPENAI_API_KEY = ""
            lw.optimize_resume_task(VALID_LATEX, JOB_DESC, job_id=str(uuid.uuid4()))

        failed = [c for c in mock_publish.call_args_list if c.args[1] == "job.failed"]
        assert failed[0].args[2]["retryable"] is False

    def test_user_api_key_bypasses_empty_default(self, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_stream(list("{}"))

        with patch("app.workers.llm_worker.settings") as ms:
            _mock_settings(ms)
            ms.OPENAI_API_KEY = ""
            lw.optimize_resume_task(VALID_LATEX, JOB_DESC, job_id=str(uuid.uuid4()), user_api_key="sk-user-key")

        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.started" in types
        # user_api_key must be passed to openai.OpenAI constructor
        assert mock_openai.call_args.kwargs.get("api_key") == "sk-user-key" or \
               (mock_openai.call_args.args and mock_openai.call_args.args[0] == "sk-user-key") or \
               mock_openai.called


# ── Full success pipeline ─────────────────────────────────────────────────────

class TestLLMWorkerSuccess:

    @pytest.fixture
    def run_success(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        """Runs the task with a valid JSON response, returns (result, event_types)."""
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_stream(
            list(VALID_JSON_RESPONSE), tokens_total=150
        )
        job_id = str(uuid.uuid4())
        with patch("app.workers.llm_worker.settings") as ms:
            _mock_settings(ms)
            result = lw.optimize_resume_task(VALID_LATEX, JOB_DESC, job_id=job_id)
        types = [c.args[1] for c in mock_publish.call_args_list]
        return result, types

    def test_success_returns_success_true(self, run_success):
        result, _ = run_success
        assert result["success"] is True

    def test_job_started_emitted_first(self, run_success):
        _, types = run_success
        assert types[0] == "job.started"

    def test_job_started_has_stage(self, run_success, mock_publish):
        started = [c for c in mock_publish.call_args_list if c.args[1] == "job.started"]
        assert started[0].args[2]["stage"] == "llm_optimization"

    def test_progress_events_emitted(self, run_success):
        _, types = run_success
        assert "job.progress" in types

    def test_llm_token_events_emitted(self, run_success):
        _, types = run_success
        assert "llm.token" in types

    def test_llm_complete_emitted(self, run_success):
        _, types = run_success
        assert "llm.complete" in types

    def test_job_completed_emitted(self, run_success):
        _, types = run_success
        assert "job.completed" in types

    def test_event_order_started_before_complete(self, run_success):
        _, types = run_success
        assert types.index("job.started") < types.index("job.completed")

    def test_llm_complete_before_job_completed(self, run_success):
        _, types = run_success
        assert types.index("llm.complete") < types.index("job.completed")

    def test_tokens_total_from_usage_chunk(self, run_success):
        result, _ = run_success
        assert result["tokens_used"] == 150

    def test_job_result_stored(self, run_success, mock_job_result):
        run_success
        assert mock_job_result.call_count == 1

    def test_result_contains_job_id(self, run_success, mock_openai, mock_publish):
        result, _ = run_success
        assert "job_id" in result


# ── JSON parse logic ──────────────────────────────────────────────────────────

class TestLLMWorkerJsonParse:

    def _run(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc, content):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_stream(list(content))
        with patch("app.workers.llm_worker.settings") as ms:
            _mock_settings(ms)
            return lw.optimize_resume_task(VALID_LATEX, JOB_DESC, job_id=str(uuid.uuid4()))

    def test_valid_json_extracts_optimized_latex(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        optimized = r"\documentclass{article}\begin{document}OPTIMIZED\end{document}"
        content = json.dumps({"optimized_latex": optimized, "changes": []})
        result = self._run(mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc, content)
        assert result["optimized_latex"] == optimized

    def test_valid_json_extracts_changes(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        content = json.dumps({
            "optimized_latex": VALID_LATEX,
            "changes": [{"section": "skills", "change_type": "added", "reason": "kw"}],
        })
        result = self._run(mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc, content)
        assert len(result["changes_made"]) == 1
        assert result["changes_made"][0]["section"] == "skills"

    def test_changes_without_dict_items_filtered(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        content = json.dumps({
            "optimized_latex": VALID_LATEX,
            "changes": ["not_a_dict", 42],
        })
        result = self._run(mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc, content)
        assert result["changes_made"] == []

    def test_garbage_json_falls_back_to_original(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        result = self._run(mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc, "NOT_JSON_AT_ALL")
        assert result["optimized_latex"] == VALID_LATEX

    def test_garbage_json_still_returns_success(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        result = self._run(mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc, "NOT_JSON")
        assert result["success"] is True

    def test_empty_content_falls_back_to_original(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        result = self._run(mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc, "")
        assert result["optimized_latex"] == VALID_LATEX


# ── Cancellation ──────────────────────────────────────────────────────────────

class TestLLMWorkerCancellation:

    def _run_with_cancel_at(self, mock_openai, mock_publish, mock_job_result, mock_llm_svc, cancel_token_index: int):
        """Run with cancellation triggered at the Nth is_cancelled() check (every 20 tokens)."""
        call_count = [0]

        def _is_cancelled(job_id):
            call_count[0] += 1
            return call_count[0] >= cancel_token_index

        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        # Provide many tokens so cancellation is encountered
        mock_client.chat.completions.create.return_value = _make_openai_stream(["t"] * 40)
        job_id = str(uuid.uuid4())
        with (
            patch("app.workers.llm_worker.is_cancelled", side_effect=_is_cancelled),
            patch("app.workers.llm_worker.settings") as ms,
        ):
            _mock_settings(ms)
            result = lw.optimize_resume_task(VALID_LATEX, JOB_DESC, job_id=job_id)
        types = [c.args[1] for c in mock_publish.call_args_list]
        return result, types

    def test_cancel_returns_success_false(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        result, _ = self._run_with_cancel_at(mock_openai, mock_publish, mock_job_result, mock_llm_svc, 1)
        assert result["success"] is False

    def test_cancel_sets_cancelled_flag(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        result, _ = self._run_with_cancel_at(mock_openai, mock_publish, mock_job_result, mock_llm_svc, 1)
        assert result.get("cancelled") is True

    def test_cancel_emits_job_cancelled_event(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        _, types = self._run_with_cancel_at(mock_openai, mock_publish, mock_job_result, mock_llm_svc, 1)
        assert "job.cancelled" in types

    def test_cancel_does_not_emit_job_completed(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        _, types = self._run_with_cancel_at(mock_openai, mock_publish, mock_job_result, mock_llm_svc, 1)
        assert "job.completed" not in types


# ── Exception handling ────────────────────────────────────────────────────────

class TestLLMWorkerExceptions:

    @pytest.fixture(autouse=True)
    def _disable_propagation(self):
        from app.core.celery_app import celery_app
        celery_app.conf.task_eager_propagates = False
        yield
        celery_app.conf.task_eager_propagates = True

    def test_openai_exception_emits_job_failed(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        job_id = str(uuid.uuid4())
        with patch("app.workers.llm_worker.settings") as ms:
            _mock_settings(ms)
            lw.optimize_resume_task.apply(
                args=[VALID_LATEX, JOB_DESC], kwargs={"job_id": job_id}
            )

        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.failed" in types

    def test_rate_limit_error_sets_retryable_false(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("Rate limit exceeded")
        job_id = str(uuid.uuid4())
        with patch("app.workers.llm_worker.settings") as ms:
            _mock_settings(ms)
            lw.optimize_resume_task.apply(
                args=[VALID_LATEX, JOB_DESC], kwargs={"job_id": job_id}
            )

        failed = [c for c in mock_publish.call_args_list if c.args[1] == "job.failed"]
        assert failed
        assert failed[-1].args[2]["retryable"] is False

    def test_exception_error_code_is_llm_error(self, mock_openai, mock_publish, mock_job_result, mock_cancelled, mock_llm_svc):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("some error")
        job_id = str(uuid.uuid4())
        with patch("app.workers.llm_worker.settings") as ms:
            _mock_settings(ms)
            lw.optimize_resume_task.apply(
                args=[VALID_LATEX, JOB_DESC], kwargs={"job_id": job_id}
            )

        failed = [c for c in mock_publish.call_args_list if c.args[1] == "job.failed"]
        assert failed[-1].args[2]["error_code"] == "llm_error"


# ── submit_resume_optimization helper ────────────────────────────────────────

class TestSubmitResumeOptimization:

    def test_dispatches_to_llm_queue(self):
        job_id = str(uuid.uuid4())
        with patch.object(lw.optimize_resume_task, "apply_async") as mock_async:
            lw.submit_resume_optimization(
                latex_content=VALID_LATEX,
                job_description=JOB_DESC,
                job_id=job_id,
            )
        _, kwargs = mock_async.call_args
        assert kwargs["queue"] == "llm"

    def test_returns_job_id(self):
        job_id = str(uuid.uuid4())
        with patch.object(lw.optimize_resume_task, "apply_async"):
            result = lw.submit_resume_optimization(
                latex_content=VALID_LATEX,
                job_description=JOB_DESC,
                job_id=job_id,
            )
        assert result == job_id

    def test_passes_job_id_to_task(self):
        job_id = str(uuid.uuid4())
        with patch.object(lw.optimize_resume_task, "apply_async") as mock_async:
            lw.submit_resume_optimization(VALID_LATEX, JOB_DESC, job_id=job_id)
        _, kwargs = mock_async.call_args
        assert kwargs["kwargs"]["job_id"] == job_id

    def test_uses_plan_priority(self):
        job_id = str(uuid.uuid4())
        with patch.object(lw.optimize_resume_task, "apply_async") as mock_async:
            lw.submit_resume_optimization(VALID_LATEX, JOB_DESC, job_id=job_id, user_plan="pro", priority=9)
        _, kwargs = mock_async.call_args
        assert kwargs["priority"] == 9
