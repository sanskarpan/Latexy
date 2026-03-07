"""
Unit tests for app.models.event_schemas.

Covers all Pydantic event models and the status_from_event_type helper.
No external dependencies — pure unit tests.
"""
from __future__ import annotations

import time
import uuid

import pytest

from app.models.event_schemas import (
    BaseEvent,
    HeartbeatEvent,
    JobCancelledEvent,
    JobCompletedEvent,
    JobFailedEvent,
    JobProgressEvent,
    JobQueuedEvent,
    JobStartedEvent,
    LLMStreamCompleteEvent,
    LLMTokenEvent,
    LogLineEvent,
    SystemErrorEvent,
    status_from_event_type,
)

JOB_ID = str(uuid.uuid4())


# ── status_from_event_type ────────────────────────────────────────────────────

class TestStatusFromEventType:

    @pytest.mark.parametrize("event_type, expected", [
        ("job.queued", "queued"),
        ("job.started", "processing"),
        ("job.progress", "processing"),
        ("job.completed", "completed"),
        ("job.failed", "failed"),
        ("job.cancelled", "cancelled"),
    ])
    def test_known_event_types(self, event_type, expected):
        assert status_from_event_type(event_type) == expected

    def test_unknown_type_returns_processing(self):
        assert status_from_event_type("llm.token") == "processing"

    def test_unknown_type_garbage_returns_processing(self):
        assert status_from_event_type("not_a_real_event_type_xyz") == "processing"

    def test_empty_string_returns_processing(self):
        assert status_from_event_type("") == "processing"

    def test_log_line_returns_processing(self):
        assert status_from_event_type("log.line") == "processing"

    def test_llm_complete_returns_processing(self):
        assert status_from_event_type("llm.complete") == "processing"

    def test_sys_heartbeat_returns_processing(self):
        assert status_from_event_type("sys.heartbeat") == "processing"


# ── BaseEvent ─────────────────────────────────────────────────────────────────

class TestBaseEvent:

    def test_event_id_auto_generated(self):
        e = BaseEvent(job_id=JOB_ID, sequence=0)
        uuid.UUID(e.event_id)  # raises ValueError if not a valid UUID

    def test_event_id_is_unique_per_instance(self):
        e1 = BaseEvent(job_id=JOB_ID, sequence=0)
        e2 = BaseEvent(job_id=JOB_ID, sequence=0)
        assert e1.event_id != e2.event_id

    def test_timestamp_auto_set(self):
        before = time.time()
        e = BaseEvent(job_id=JOB_ID, sequence=0)
        after = time.time()
        assert before <= e.timestamp <= after

    def test_job_id_stored(self):
        e = BaseEvent(job_id=JOB_ID, sequence=0)
        assert e.job_id == JOB_ID

    def test_sequence_stored(self):
        e = BaseEvent(job_id=JOB_ID, sequence=42)
        assert e.sequence == 42

    def test_custom_event_id_accepted(self):
        custom_id = str(uuid.uuid4())
        e = BaseEvent(job_id=JOB_ID, sequence=0, event_id=custom_id)
        assert e.event_id == custom_id

    def test_custom_timestamp_accepted(self):
        ts = 1700000000.0
        e = BaseEvent(job_id=JOB_ID, sequence=0, timestamp=ts)
        assert e.timestamp == ts


# ── JobQueuedEvent ────────────────────────────────────────────────────────────

class TestJobQueuedEvent:

    def test_type_literal(self):
        e = JobQueuedEvent(job_id=JOB_ID, sequence=1, job_type="combined")
        assert e.type == "job.queued"

    def test_job_type_stored(self):
        e = JobQueuedEvent(job_id=JOB_ID, sequence=1, job_type="latex_compilation")
        assert e.job_type == "latex_compilation"

    def test_default_estimated_seconds(self):
        e = JobQueuedEvent(job_id=JOB_ID, sequence=1, job_type="combined")
        assert e.estimated_seconds == 60

    def test_custom_estimated_seconds(self):
        e = JobQueuedEvent(job_id=JOB_ID, sequence=1, job_type="combined", estimated_seconds=90)
        assert e.estimated_seconds == 90

    def test_user_id_defaults_to_none(self):
        e = JobQueuedEvent(job_id=JOB_ID, sequence=1, job_type="combined")
        assert e.user_id is None

    def test_user_id_accepted(self):
        uid = str(uuid.uuid4())
        e = JobQueuedEvent(job_id=JOB_ID, sequence=1, job_type="combined", user_id=uid)
        assert e.user_id == uid


# ── JobStartedEvent ───────────────────────────────────────────────────────────

class TestJobStartedEvent:

    def test_type_literal(self):
        e = JobStartedEvent(job_id=JOB_ID, sequence=2, worker_id="w1", stage="llm_optimization")
        assert e.type == "job.started"

    def test_worker_id_stored(self):
        e = JobStartedEvent(job_id=JOB_ID, sequence=2, worker_id="orchestrator-abc", stage="llm")
        assert e.worker_id == "orchestrator-abc"

    def test_stage_stored(self):
        e = JobStartedEvent(job_id=JOB_ID, sequence=2, worker_id="w1", stage="ats_scoring")
        assert e.stage == "ats_scoring"


# ── JobProgressEvent ──────────────────────────────────────────────────────────

class TestJobProgressEvent:

    def test_type_literal(self):
        e = JobProgressEvent(job_id=JOB_ID, sequence=3, percent=40, stage="llm", message="hi")
        assert e.type == "job.progress"

    def test_percent_stored(self):
        e = JobProgressEvent(job_id=JOB_ID, sequence=3, percent=75, stage="ats", message="x")
        assert e.percent == 75

    def test_message_stored(self):
        e = JobProgressEvent(job_id=JOB_ID, sequence=3, percent=40, stage="llm", message="Building prompt")
        assert e.message == "Building prompt"

    def test_stage_stored(self):
        e = JobProgressEvent(job_id=JOB_ID, sequence=3, percent=40, stage="latex_compilation", message="x")
        assert e.stage == "latex_compilation"


# ── JobCompletedEvent ─────────────────────────────────────────────────────────

class TestJobCompletedEvent:

    def _make(self, **kwargs) -> JobCompletedEvent:
        defaults = dict(
            job_id=JOB_ID, sequence=10, pdf_job_id=JOB_ID,
            ats_score=80.0, ats_details={}, changes_made=[],
            compilation_time=5.0, optimization_time=10.0, tokens_used=200,
        )
        defaults.update(kwargs)
        return JobCompletedEvent(**defaults)

    def test_type_literal(self):
        assert self._make().type == "job.completed"

    def test_ats_score_stored(self):
        assert self._make(ats_score=92.5).ats_score == 92.5

    def test_pdf_job_id_stored(self):
        e = self._make(pdf_job_id=JOB_ID)
        assert e.pdf_job_id == JOB_ID

    def test_tokens_used_stored(self):
        e = self._make(tokens_used=500)
        assert e.tokens_used == 500

    def test_ats_details_stored(self):
        details = {"category_scores": {"formatting": 80}}
        e = self._make(ats_details=details)
        assert e.ats_details["category_scores"]["formatting"] == 80

    def test_changes_made_list(self):
        changes = [{"section": "summary", "change_type": "modified"}]
        e = self._make(changes_made=changes)
        assert len(e.changes_made) == 1

    def test_compilation_time_stored(self):
        e = self._make(compilation_time=12.5)
        assert e.compilation_time == 12.5

    def test_optimization_time_stored(self):
        e = self._make(optimization_time=30.0)
        assert e.optimization_time == 30.0


# ── JobFailedEvent ────────────────────────────────────────────────────────────

class TestJobFailedEvent:

    def _make(self, **kwargs) -> JobFailedEvent:
        defaults = dict(
            job_id=JOB_ID, sequence=5,
            stage="llm_optimization", error_code="internal",
            error_message="Something went wrong", retryable=True,
        )
        defaults.update(kwargs)
        return JobFailedEvent(**defaults)

    def test_type_literal(self):
        assert self._make().type == "job.failed"

    def test_retryable_true(self):
        assert self._make(retryable=True).retryable is True

    def test_retryable_false(self):
        assert self._make(retryable=False).retryable is False

    def test_error_code_latex_error(self):
        e = self._make(error_code="latex_error")
        assert e.error_code == "latex_error"

    def test_error_code_llm_error(self):
        e = self._make(error_code="llm_error")
        assert e.error_code == "llm_error"

    def test_error_code_timeout(self):
        e = self._make(error_code="timeout")
        assert e.error_code == "timeout"

    def test_error_message_stored(self):
        e = self._make(error_message="pdflatex exited with code 1")
        assert e.error_message == "pdflatex exited with code 1"

    def test_stage_stored(self):
        e = self._make(stage="latex_compilation")
        assert e.stage == "latex_compilation"


# ── JobCancelledEvent ─────────────────────────────────────────────────────────

class TestJobCancelledEvent:

    def test_type_literal(self):
        e = JobCancelledEvent(job_id=JOB_ID, sequence=6)
        assert e.type == "job.cancelled"

    def test_inherits_base_fields(self):
        e = JobCancelledEvent(job_id=JOB_ID, sequence=6)
        assert e.job_id == JOB_ID


# ── LLMTokenEvent ─────────────────────────────────────────────────────────────

class TestLLMTokenEvent:

    def test_type_literal(self):
        e = LLMTokenEvent(job_id=JOB_ID, sequence=7, token="hello")
        assert e.type == "llm.token"

    def test_token_stored(self):
        e = LLMTokenEvent(job_id=JOB_ID, sequence=7, token=" world")
        assert e.token == " world"

    def test_empty_token_accepted(self):
        # Empty tokens can occur in streaming (whitespace deltas)
        e = LLMTokenEvent(job_id=JOB_ID, sequence=7, token="")
        assert e.token == ""

    def test_multichar_token(self):
        e = LLMTokenEvent(job_id=JOB_ID, sequence=7, token="\\begin{document}")
        assert e.token == "\\begin{document}"


# ── LLMStreamCompleteEvent ────────────────────────────────────────────────────

class TestLLMStreamCompleteEvent:

    def test_type_literal(self):
        e = LLMStreamCompleteEvent(job_id=JOB_ID, sequence=8, full_content="\\documentclass{article}", tokens_total=100)
        assert e.type == "llm.complete"

    def test_full_content_stored(self):
        latex = "\\begin{document}Hello\\end{document}"
        e = LLMStreamCompleteEvent(job_id=JOB_ID, sequence=8, full_content=latex, tokens_total=50)
        assert e.full_content == latex

    def test_tokens_total_stored(self):
        e = LLMStreamCompleteEvent(job_id=JOB_ID, sequence=8, full_content="x", tokens_total=500)
        assert e.tokens_total == 500

    def test_zero_tokens_accepted(self):
        e = LLMStreamCompleteEvent(job_id=JOB_ID, sequence=8, full_content="x", tokens_total=0)
        assert e.tokens_total == 0


# ── LogLineEvent ──────────────────────────────────────────────────────────────

class TestLogLineEvent:

    def test_type_literal(self):
        e = LogLineEvent(job_id=JOB_ID, sequence=9, source="pdflatex", line="Warning", is_error=False)
        assert e.type == "log.line"

    def test_is_error_false(self):
        e = LogLineEvent(job_id=JOB_ID, sequence=9, source="pdflatex", line="ok", is_error=False)
        assert e.is_error is False

    def test_is_error_true(self):
        e = LogLineEvent(job_id=JOB_ID, sequence=9, source="pdflatex", line="ERROR: undefined", is_error=True)
        assert e.is_error is True

    def test_source_stored(self):
        e = LogLineEvent(job_id=JOB_ID, sequence=9, source="lualatex", line="ok", is_error=False)
        assert e.source == "lualatex"

    def test_line_stored(self):
        e = LogLineEvent(job_id=JOB_ID, sequence=9, source="pdflatex", line="This is a log line", is_error=False)
        assert e.line == "This is a log line"


# ── HeartbeatEvent ────────────────────────────────────────────────────────────

class TestHeartbeatEvent:

    def test_type_literal(self):
        e = HeartbeatEvent(job_id=JOB_ID, sequence=0)
        assert e.type == "sys.heartbeat"

    def test_server_time_auto_set(self):
        before = time.time()
        e = HeartbeatEvent(job_id=JOB_ID, sequence=0)
        after = time.time()
        assert before <= e.server_time <= after

    def test_server_time_is_float(self):
        e = HeartbeatEvent(job_id=JOB_ID, sequence=0)
        assert isinstance(e.server_time, float)


# ── SystemErrorEvent ──────────────────────────────────────────────────────────

class TestSystemErrorEvent:

    def test_type_literal(self):
        e = SystemErrorEvent(job_id=JOB_ID, sequence=0, message="Redis unavailable")
        assert e.type == "sys.error"

    def test_message_stored(self):
        e = SystemErrorEvent(job_id=JOB_ID, sequence=0, message="Connection timeout")
        assert e.message == "Connection timeout"
