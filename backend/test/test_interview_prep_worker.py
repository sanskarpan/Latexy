"""Contract tests for AI-screening interview-prep model output."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import Retry

from app.workers.interview_prep_worker import (
    _QUESTION_COUNTS,
    _SYSTEM_PROMPT,
    _validate_questions,
    generate_interview_prep_task,
)


def _question(category: str, index: int) -> dict:
    return {
        "category": category,
        "question": f"{category.title()} screening question {index}?",
        "what_interviewer_assesses": "Relevant evidence and a clear, structured response.",
        "star_hint": (
            "Situation: context | Task: responsibility | Action: steps | Result: outcome"
            if category == "behavioral"
            else None
        ),
        "ideal_response_outline": [
            "State the relevant experience from the resume.",
            "Connect concrete evidence to the role requirement.",
        ],
        "spoken_answer_tip": "Lead with the answer, then support it with one example.",
        "recommended_seconds": 75,
    }


def _valid_payload() -> dict:
    questions = []
    for category, count in _QUESTION_COUNTS.items():
        questions.extend(_question(category, index) for index in range(count))
    return {"questions": questions}


def test_validates_complete_screening_question_contract():
    questions = _validate_questions(_valid_payload())

    assert len(questions) == 15
    assert sum(q["recommended_seconds"] for q in questions) == 15 * 75
    assert all(2 <= len(q["ideal_response_outline"]) <= 4 for q in questions)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda payload: payload["questions"].pop(), "exactly 15"),
        (
            lambda payload: payload["questions"][5].update(category="motivational"),
            "categories must match",
        ),
        (
            lambda payload: payload["questions"][1].update(question=payload["questions"][0]["question"]),
            "duplicate questions",
        ),
        (
            lambda payload: payload["questions"][0].update(ideal_response_outline=["Only one point"]),
            "2 to 4 points",
        ),
        (
            lambda payload: payload["questions"][0].update(recommended_seconds=181),
            "30 to 180",
        ),
        (
            lambda payload: payload["questions"][5].update(star_hint="Not applicable"),
            "must be null",
        ),
    ],
)
def test_rejects_malformed_model_output(mutation, match: str):
    payload = deepcopy(_valid_payload())
    mutation(payload)

    with pytest.raises(ValueError, match=match):
        _validate_questions(payload)


def test_prompt_marks_resume_and_job_description_as_untrusted():
    assert "untrusted source material" in _SYSTEM_PROMPT
    assert "Ground every candidate-specific claim in the resume" in _SYSTEM_PROMPT


def test_invalid_model_output_publishes_retrying_not_terminal_failure():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"questions": []}'))],
        usage=None,
    )
    client = MagicMock()
    client.chat.completions.create.return_value = response

    with (
        patch("app.workers.interview_prep_worker.openai.OpenAI", return_value=client),
        patch("app.workers.interview_prep_worker.is_cancelled", return_value=False),
        patch("app.workers.interview_prep_worker.publish_event") as publish,
        patch.object(generate_interview_prep_task, "retry", side_effect=Retry()),
        pytest.raises(Retry),
    ):
        generate_interview_prep_task.run(
            "resume source",
            "00000000-0000-0000-0000-000000000001",
            job_id="00000000-0000-0000-0000-000000000002",
            user_api_key="test-key",
        )

    event_types = [call.args[1] for call in publish.call_args_list]
    assert "job.retrying" in event_types
    assert "job.failed" not in event_types


def test_exhausted_invalid_model_output_publishes_terminal_failure():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"questions": []}'))],
        usage=None,
    )
    client = MagicMock()
    client.chat.completions.create.return_value = response

    generate_interview_prep_task.push_request(
        id="final-attempt",
        retries=generate_interview_prep_task.max_retries,
    )
    try:
        with (
            patch("app.workers.interview_prep_worker.openai.OpenAI", return_value=client),
            patch("app.workers.interview_prep_worker.is_cancelled", return_value=False),
            patch("app.workers.interview_prep_worker.publish_event") as publish,
        ):
            result = generate_interview_prep_task.run(
                "resume source",
                "00000000-0000-0000-0000-000000000001",
                job_id="00000000-0000-0000-0000-000000000002",
                user_api_key="test-key",
            )
    finally:
        generate_interview_prep_task.pop_request()

    event_types = [call.args[1] for call in publish.call_args_list]
    assert "job.failed" in event_types
    assert "job.retrying" not in event_types
    assert result["success"] is False
