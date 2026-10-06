"""Red regression for publishing cover-letter completion content only after commit."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

import app.workers.cover_letter_worker as cover_worker


def _stream(text: str):
    for char in text:
        chunk = MagicMock()
        chunk.usage = None
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = char
        yield chunk
    usage = MagicMock()
    usage.usage = SimpleNamespace(total_tokens=12)
    usage.choices = []
    yield usage


_VALID_LATEX = r"<<<LATEX>>>\documentclass{article}\begin{document}Letter\end{document}<<<END_LATEX>>>"


def _run_valid_generation(
    *, lifecycle_exists: bool, published: bool, committed: bool
) -> tuple[dict, list[str], list[str], MagicMock, MagicMock, MagicMock]:
    """Run one successful model response with controllable terminal fences."""

    job_id = f"cover-event-order-{uuid4().hex}"
    events: list[str] = []
    timeline: list[str] = []
    redis = MagicMock()
    redis.exists.return_value = 1 if lifecycle_exists else 0
    redis.hget.return_value = b"1"

    def record_event(_job_id, event_type, _payload):
        events.append(event_type)
        timeline.append(f"event:{event_type}")
        return "stream-id"

    def record_result(*_args, **_kwargs):
        timeline.append("result")
        return published

    def record_commit(*_args, **_kwargs):
        timeline.append("commit")
        return committed

    with (
        patch("app.workers.cover_letter_worker.get_worker_redis", return_value=redis),
        patch("app.workers.cover_letter_worker.admit_worker", return_value=True),
        patch("app.workers.cover_letter_worker.is_cancelled", return_value=False),
        patch("app.workers.cover_letter_worker.publish_event", side_effect=record_event),
        patch("app.workers.cover_letter_worker.publish_job_result", side_effect=record_result) as result_mock,
        patch("app.workers.cover_letter_worker._commit_cover_letter_finalization", side_effect=record_commit) as commit_mock,
        patch("app.workers.cover_letter_worker._save_cover_letter_content") as save_mock,
        patch("app.workers.cover_letter_worker.document_converter_service.validate_latex_output", return_value=(True, "")),
        patch("app.workers.cover_letter_worker.settings") as settings,
        patch("app.workers.cover_letter_worker.openai.OpenAI") as openai_client,
    ):
        settings.OPENAI_API_KEY = "test-key"
        settings.OPENAI_MODEL = "test-model"
        settings.OPENAI_MAX_TOKENS = 100
        openai_client.return_value.chat.completions.create.return_value = _stream(_VALID_LATEX)
        result = cover_worker.generate_cover_letter_task(
            r"\documentclass{article}\begin{document}Resume\end{document}",
            "Need an engineer",
            job_id=job_id,
            user_id="test-user",
            cover_letter_id="test-cover-letter",
        )
    return result, events, timeline, result_mock, commit_mock, save_mock


@pytest.mark.parametrize("owner_epoch", [b"1", b"not-an-epoch"])
def test_valid_cover_output_is_not_emitted_before_rejected_arbiter_or_owner_commit(owner_epoch):
    latex = r"<<<LATEX>>>\documentclass{article}\begin{document}Letter\end{document}<<<END_LATEX>>>"
    events: list[str] = []
    redis = MagicMock()
    redis.exists.return_value = 1
    redis.hget.return_value = owner_epoch

    def record_event(_job_id, event_type, _payload):
        events.append(event_type)
        return "stream-id"

    with (
        patch("app.workers.cover_letter_worker.get_worker_redis", return_value=redis),
        patch("app.workers.cover_letter_worker.admit_worker", return_value=True),
        patch("app.workers.cover_letter_worker.is_cancelled", return_value=False),
        patch("app.workers.cover_letter_worker.publish_event", side_effect=record_event),
        patch("app.workers.cover_letter_worker.publish_job_result", return_value=True),
        patch("app.workers.cover_letter_worker._commit_cover_letter_finalization", return_value=False),
        patch("app.workers.cover_letter_worker.document_converter_service.validate_latex_output", return_value=(True, "")),
        patch("app.workers.cover_letter_worker.settings") as settings,
        patch("app.workers.cover_letter_worker.openai.OpenAI") as openai_client,
    ):
        settings.OPENAI_API_KEY = "test-key"
        settings.OPENAI_MODEL = "test-model"
        settings.OPENAI_MAX_TOKENS = 100
        openai_client.return_value.chat.completions.create.return_value = _stream(latex)
        result = cover_worker.generate_cover_letter_task(
            r"\documentclass{article}\begin{document}Resume\end{document}",
            "Need an engineer",
            job_id="test-cover-event-acceptance",
            user_id="test-user",
            cover_letter_id="test-cover-letter",
        )

    assert result["success"] is False
    assert "llm.complete" not in events
    assert "job.completed" not in events
    assert "job.failed" in events


def test_publisher_rejection_suppresses_final_content_after_successful_db_commit():
    result, events, timeline, result_mock, commit_mock, _save_mock = _run_valid_generation(
        lifecycle_exists=True, published=False, committed=True
    )

    assert result["success"] is False
    assert result["error"] == "Job ownership expired"
    assert commit_mock.call_count == 1
    assert result_mock.call_count == 1
    assert "llm.complete" not in events
    assert "job.completed" not in events
    assert timeline.index("commit") < timeline.index("result")


def test_legacy_publisher_rejection_suppresses_final_content():
    result, events, timeline, result_mock, commit_mock, save_mock = _run_valid_generation(
        lifecycle_exists=False, published=False, committed=True
    )

    assert result["success"] is False
    assert result_mock.call_count == 1
    commit_mock.assert_not_called()
    save_mock.assert_called_once()
    assert "llm.complete" not in events
    assert "job.completed" not in events
    assert timeline[-1] == "result"


def test_accepted_db_commit_and_result_publish_final_content_before_completion():
    result, events, timeline, result_mock, commit_mock, _save_mock = _run_valid_generation(
        lifecycle_exists=True, published=True, committed=True
    )

    assert result["success"] is True
    assert result_mock.call_count == 1
    assert commit_mock.call_count == 1
    assert timeline.index("commit") < timeline.index("result")
    assert timeline.index("result") < timeline.index("event:llm.complete")
    assert timeline.index("event:llm.complete") < timeline.index("event:job.completed")
