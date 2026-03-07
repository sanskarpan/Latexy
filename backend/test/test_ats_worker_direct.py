"""
Direct unit tests for ATS Celery worker tasks.

Uses Celery eager mode so tasks run synchronously in-process.
All Redis I/O is mocked at the module level (publish_event, publish_job_result,
is_cancelled).  The ATS scoring service is mocked via AsyncMock since
score_resume() is async.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.celery_app import celery_app
from app.workers.ats_worker import (
    analyze_job_description_ats_task,
    score_resume_ats_task,
)

GOOD_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\usepackage[empty]{fullpage}
\begin{document}
\begin{center}\textbf{\Large Jane Smith}\\jane@example.com\end{center}
\section*{Experience}
Software Engineer at Acme Corp. Built distributed systems.
Python, AWS, Kubernetes, Docker experience required.
\end{document}
"""

TECH_JD = (
    "Required: Python, AWS. Must have: 5 years experience in software development. "
    "Preferred: Docker, Kubernetes. Nice to have: Go, Rust."
)

FINANCE_JD = "Seeking a financial analyst specializing in banking and investment accounting."


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
    with patch("app.workers.ats_worker.publish_event") as m:
        yield m


@pytest.fixture
def mock_result_store():
    with patch("app.workers.ats_worker.publish_job_result") as m:
        yield m


@pytest.fixture
def mock_scoring():
    """Mock ats_scoring_service.score_resume to return a predictable result."""
    fake = MagicMock()
    fake.overall_score = 72.5
    fake.category_scores = {"formatting": 70, "structure": 75, "content": 72}
    fake.recommendations = ["Add more technical keywords", "Quantify achievements"]
    fake.strengths = ["Clear formatting", "Relevant experience"]
    fake.warnings = ["Missing summary section"]
    fake.detailed_analysis = {"word_count": 200, "sections_found": 3}

    with patch(
        "app.workers.ats_worker.ats_scoring_service.score_resume",
        new_callable=AsyncMock,
        return_value=fake,
    ):
        yield fake


# ── score_resume_ats_task — happy path ────────────────────────────────────────

class TestScoreResumeAtsTaskSuccess:

    def test_returns_success_true(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        res = score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": job_id}).result
        assert res["success"] is True

    def test_result_contains_job_id(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        res = score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": job_id}).result
        assert res["job_id"] == job_id

    def test_result_contains_ats_score(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        res = score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": job_id}).result
        assert res["ats_score"] == 72.5

    def test_result_contains_ats_details(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        res = score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": job_id}).result
        assert "ats_details" in res
        assert "category_scores" in res["ats_details"]

    def test_ats_details_has_recommendations(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        res = score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": job_id}).result
        assert "recommendations" in res["ats_details"]
        assert isinstance(res["ats_details"]["recommendations"], list)

    def test_result_has_scoring_time(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        res = score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": job_id}).result
        assert "scoring_time" in res
        assert isinstance(res["scoring_time"], float)
        assert res["scoring_time"] >= 0

    def test_user_id_preserved_in_result(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        res = score_resume_ats_task.apply(
            args=[GOOD_LATEX], kwargs={"job_id": job_id, "user_id": user_id}
        ).result
        assert res["user_id"] == user_id

    def test_industry_preserved_in_result(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        res = score_resume_ats_task.apply(
            args=[GOOD_LATEX], kwargs={"job_id": job_id, "industry": "technology"}
        ).result
        assert res["industry"] == "technology"

    def test_device_fingerprint_preserved_in_result(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        fp = "device_abc123"
        res = score_resume_ats_task.apply(
            args=[GOOD_LATEX], kwargs={"job_id": job_id, "device_fingerprint": fp}
        ).result
        assert res["device_fingerprint"] == fp

    def test_job_id_auto_generated_when_none(self, mock_publish, mock_result_store, mock_scoring):
        res = score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={}).result
        assert "job_id" in res
        uuid.UUID(res["job_id"])  # must be valid UUID

    def test_detailed_analysis_in_result(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        res = score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": job_id}).result
        assert "detailed_analysis" in res

    def test_publish_job_result_called_once(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": job_id})
        mock_result_store.assert_called_once()

    def test_publish_job_result_receives_job_id(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": job_id})
        result_arg = mock_result_store.call_args[0][1]
        assert result_arg["job_id"] == job_id


# ── score_resume_ats_task — event sequence ────────────────────────────────────

class TestScoreResumeAtsTaskEvents:

    def _event_types(self, mock_publish):
        return [c.args[1] for c in mock_publish.call_args_list]

    def test_job_started_event_published(self, mock_publish, mock_result_store, mock_scoring):
        score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": str(uuid.uuid4())})
        assert "job.started" in self._event_types(mock_publish)

    def test_job_progress_event_published(self, mock_publish, mock_result_store, mock_scoring):
        score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": str(uuid.uuid4())})
        assert "job.progress" in self._event_types(mock_publish)

    def test_job_completed_event_published(self, mock_publish, mock_result_store, mock_scoring):
        score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": str(uuid.uuid4())})
        assert "job.completed" in self._event_types(mock_publish)

    def test_started_before_completed(self, mock_publish, mock_result_store, mock_scoring):
        score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": str(uuid.uuid4())})
        types = self._event_types(mock_publish)
        assert types.index("job.started") < types.index("job.completed")

    def test_progress_at_20_percent(self, mock_publish, mock_result_store, mock_scoring):
        score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": str(uuid.uuid4())})
        progress_calls = [c for c in mock_publish.call_args_list if c.args[1] == "job.progress"]
        percents = [c.args[2].get("percent") for c in progress_calls]
        assert 20 in percents

    def test_progress_at_90_percent(self, mock_publish, mock_result_store, mock_scoring):
        score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": str(uuid.uuid4())})
        progress_calls = [c for c in mock_publish.call_args_list if c.args[1] == "job.progress"]
        percents = [c.args[2].get("percent") for c in progress_calls]
        assert 90 in percents

    def test_completed_event_includes_ats_score(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": job_id})
        completed = next(c for c in mock_publish.call_args_list if c.args[1] == "job.completed")
        assert completed.args[2]["ats_score"] == 72.5

    def test_started_event_has_stage(self, mock_publish, mock_result_store, mock_scoring):
        score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": str(uuid.uuid4())})
        started = next(c for c in mock_publish.call_args_list if c.args[1] == "job.started")
        assert "stage" in started.args[2]

    def test_job_ids_match_across_all_events(self, mock_publish, mock_result_store, mock_scoring):
        job_id = str(uuid.uuid4())
        score_resume_ats_task.apply(args=[GOOD_LATEX], kwargs={"job_id": job_id})
        for c in mock_publish.call_args_list:
            assert c.args[0] == job_id, f"Event for wrong job: {c.args[0]}"


# ── score_resume_ats_task — validation failures ───────────────────────────────

class TestScoreResumeAtsTaskValidation:

    def test_empty_latex_returns_failure(self, mock_publish, mock_result_store):
        res = score_resume_ats_task.apply(args=[""], kwargs={"job_id": str(uuid.uuid4())}).result
        assert res["success"] is False

    def test_whitespace_only_latex_returns_failure(self, mock_publish, mock_result_store):
        res = score_resume_ats_task.apply(
            args=["  \n\t  "], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert res["success"] is False

    def test_empty_latex_publishes_job_failed(self, mock_publish, mock_result_store):
        score_resume_ats_task.apply(args=[""], kwargs={"job_id": str(uuid.uuid4())})
        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.failed" in types
        assert "job.completed" not in types

    def test_empty_latex_job_failed_not_retryable(self, mock_publish, mock_result_store):
        score_resume_ats_task.apply(args=[""], kwargs={"job_id": str(uuid.uuid4())})
        failed = next(c for c in mock_publish.call_args_list if c.args[1] == "job.failed")
        assert failed.args[2]["retryable"] is False

    def test_empty_latex_error_message_non_empty(self, mock_publish, mock_result_store):
        score_resume_ats_task.apply(args=[""], kwargs={"job_id": str(uuid.uuid4())})
        failed = next(c for c in mock_publish.call_args_list if c.args[1] == "job.failed")
        assert len(failed.args[2].get("error_message", "")) > 0

    def test_empty_latex_error_code_set(self, mock_publish, mock_result_store):
        score_resume_ats_task.apply(args=[""], kwargs={"job_id": str(uuid.uuid4())})
        failed = next(c for c in mock_publish.call_args_list if c.args[1] == "job.failed")
        assert "error_code" in failed.args[2]

    def test_empty_latex_no_result_stored(self, mock_publish, mock_result_store):
        score_resume_ats_task.apply(args=[""], kwargs={"job_id": str(uuid.uuid4())})
        mock_result_store.assert_not_called()

    def test_scoring_exception_publishes_job_failed(self, mock_publish, mock_result_store):
        celery_app.conf.task_eager_propagates = False
        try:
            with patch(
                "app.workers.ats_worker.ats_scoring_service.score_resume",
                new_callable=AsyncMock,
                side_effect=ValueError("Scoring engine failed"),
            ):
                res = score_resume_ats_task.apply(
                    args=[GOOD_LATEX], kwargs={"job_id": str(uuid.uuid4())}
                ).result
        finally:
            celery_app.conf.task_eager_propagates = True
        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.failed" in types

    def test_scoring_exception_result_not_stored(self, mock_publish, mock_result_store):
        celery_app.conf.task_eager_propagates = False
        try:
            with patch(
                "app.workers.ats_worker.ats_scoring_service.score_resume",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Unexpected error"),
            ):
                score_resume_ats_task.apply(
                    args=[GOOD_LATEX], kwargs={"job_id": str(uuid.uuid4())}
                )
        finally:
            celery_app.conf.task_eager_propagates = True
        mock_result_store.assert_not_called()


# ── analyze_job_description_ats_task ──────────────────────────────────────────

class TestAnalyzeJobDescriptionAtsTask:

    def test_returns_success_true(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert res["success"] is True

    def test_result_contains_job_id(self, mock_publish, mock_result_store):
        job_id = str(uuid.uuid4())
        res = analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": job_id}
        ).result
        assert res["job_id"] == job_id

    def test_keywords_is_list(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert isinstance(res["keywords"], list)

    def test_requirements_is_list(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert isinstance(res["requirements"], list)

    def test_requirements_not_empty_for_rich_jd(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert len(res["requirements"]) > 0

    def test_preferred_qualifications_is_list(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert isinstance(res["preferred_qualifications"], list)

    def test_detected_industry_technology(self, mock_publish, mock_result_store):
        tech_jd = "Looking for a software development engineer with programming skills in Python."
        res = analyze_job_description_ats_task.apply(
            args=[tech_jd], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert res["detected_industry"] == "technology"

    def test_detected_industry_finance(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=[FINANCE_JD], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert res["detected_industry"] == "finance"

    def test_detected_industry_general_for_unknown(self, mock_publish, mock_result_store):
        jd = "Seeking a candidate who has background in philosophy and metaphysics."
        res = analyze_job_description_ats_task.apply(
            args=[jd], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert res["detected_industry"] == "general"

    def test_analysis_metrics_present(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert "analysis_metrics" in res
        metrics = res["analysis_metrics"]
        assert "word_count" in metrics
        assert "sentence_count" in metrics
        assert "keyword_count" in metrics

    def test_word_count_is_positive(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert res["analysis_metrics"]["word_count"] > 0

    def test_keywords_capped_at_15(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert len(res["keywords"]) <= 15

    def test_requirements_capped_at_10(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert len(res["requirements"]) <= 10

    def test_preferred_capped_at_10(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert len(res["preferred_qualifications"]) <= 10

    def test_analysis_time_non_negative(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert res["analysis_time"] >= 0.0

    def test_job_id_auto_generated_when_none(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(args=[TECH_JD], kwargs={}).result
        assert "job_id" in res
        uuid.UUID(res["job_id"])

    def test_empty_jd_returns_failure(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=[""], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert res["success"] is False

    def test_whitespace_only_jd_returns_failure(self, mock_publish, mock_result_store):
        res = analyze_job_description_ats_task.apply(
            args=["  \n  "], kwargs={"job_id": str(uuid.uuid4())}
        ).result
        assert res["success"] is False

    def test_empty_jd_publishes_job_failed(self, mock_publish, mock_result_store):
        analyze_job_description_ats_task.apply(
            args=[""], kwargs={"job_id": str(uuid.uuid4())}
        )
        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.failed" in types
        assert "job.completed" not in types

    def test_empty_jd_no_result_stored(self, mock_publish, mock_result_store):
        analyze_job_description_ats_task.apply(
            args=[""], kwargs={"job_id": str(uuid.uuid4())}
        )
        mock_result_store.assert_not_called()

    def test_job_started_published(self, mock_publish, mock_result_store):
        analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        )
        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.started" in types

    def test_job_completed_published(self, mock_publish, mock_result_store):
        analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        )
        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.completed" in types

    def test_publish_result_called_on_success(self, mock_publish, mock_result_store):
        analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4())}
        )
        mock_result_store.assert_called_once()

    def test_user_id_preserved_in_result(self, mock_publish, mock_result_store):
        user_id = str(uuid.uuid4())
        res = analyze_job_description_ats_task.apply(
            args=[TECH_JD], kwargs={"job_id": str(uuid.uuid4()), "user_id": user_id}
        ).result
        assert res["user_id"] == user_id
