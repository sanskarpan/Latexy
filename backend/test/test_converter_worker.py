"""Terminal-state guarantees for the document conversion worker (issue #1863).

The worker must publish a canonical terminal result through the finalization
arbiter before its terminal event, and it must do so for every exit path:
provider errors/timeouts, invalid output, missing credentials, and unexpected
exceptions. These are unit tests with an in-memory terminal recorder; they do
not require Redis or PostgreSQL.
"""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from app.workers import converter_worker as worker
from app.workers import job_lifecycle

JOB_ID = "synthetic-conversion-job"
VALID_LATEX = r"\documentclass{article}\begin{document}Synthetic resume\end{document}"


class TerminalRecorder:
    """Minimal finalization-arbiter stand-in that records the terminal state."""

    def __init__(self, order, *, fail_first=False, require_owner=False):
        self.order = order
        self.fail_first = fail_first
        self.require_owner = require_owner
        self.attempts = []
        self.results = []
        self.status = "processing"

    def __call__(self, job_id, result):
        self.attempts.append(result)
        self.order.append("result_attempt")
        if self.require_owner and job_lifecycle.current_owner(job_id) is None:
            return False
        if self.fail_first:
            self.fail_first = False
            raise ConnectionError("synthetic canonical result transport failure")
        self.results.append(result)
        self.status = "completed" if result.get("success") is True else "failed"
        self.order.append("result")
        return True


class EventRecorder:
    def __init__(self, order):
        self.order = order
        self.events = []

    def __call__(self, job_id, event_type, payload):
        self.events.append((event_type, payload))
        self.order.append(event_type)
        return "1-0"


def run_conversion(
    *,
    byok=None,
    platform_key="synthetic-platform-key",
    content=VALID_LATEX,
    create_error=None,
    prompt_error=None,
    terminal=None,
):
    order = []
    client = MagicMock()
    if create_error is not None:
        client.chat.completions.create.side_effect = create_error
    else:
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(total_tokens=42),
        )
    constructor = MagicMock(return_value=client)
    terminal = terminal or TerminalRecorder(order)
    events = EventRecorder(order)
    prompt = (
        MagicMock(side_effect=prompt_error)
        if prompt_error is not None
        else MagicMock(return_value=[{"role": "user", "content": "Synthetic resume"}])
    )
    refund = MagicMock()
    clear_receipt = MagicMock()
    released = []

    def admit(_redis, job_id, owner, _quota_refund, _user_id):
        job_lifecycle.set_current_capability(job_id, owner, 1)
        return True

    def release(job_id):
        released.append(job_id)
        job_lifecycle.clear_current_owner(job_id)

    try:
        with ExitStack() as stack:
            for name, value in {
                "get_worker_redis": MagicMock(),
                "admit_worker": admit,
                "publish_event": events,
                "publish_job_result": terminal,
                "is_cancelled": MagicMock(return_value=False),
                "refund_quota_once": refund,
                "clear_quota_refund_receipt": clear_receipt,
                "stop_lease_heartbeat": MagicMock(),
                "clear_current_owner": release,
            }.items():
                stack.enter_context(patch.object(worker, name, value))
            stack.enter_context(
                patch.object(worker.document_converter_service, "build_conversion_prompt", prompt)
            )
            stack.enter_context(patch.object(worker.openai, "OpenAI", constructor))
            stack.enter_context(patch.object(worker.settings, "OPENAI_API_KEY", platform_key))
            stack.enter_context(
                patch.object(worker.settings, "OPENAI_BASE_URL", "https://platform.example.test/v1")
            )
            stack.enter_context(patch.object(worker.settings, "OPENAI_MODEL", "configured-platform-model"))
            result = worker.convert_document_task.run(
                extracted_data={"raw_text": "Synthetic resume"},
                source_format="text",
                job_id=JOB_ID,
                user_id="synthetic-owner",
                user_api_key=byok,
                quota_refund={"dimension": "ai_assists", "user_id": "synthetic-owner", "cost": 1},
            )
    finally:
        job_lifecycle.clear_current_owner(JOB_ID)

    return SimpleNamespace(
        result=result,
        client=client,
        constructor=constructor,
        create=client.chat.completions.create,
        events=events.events,
        order=order,
        refund=refund,
        clear_receipt=clear_receipt,
        released=released,
        terminal=terminal,
    )


def _event_types(case):
    return [event_type for event_type, _payload in case.events]


def test_unexpected_prompt_exception_terminalizes_without_staying_processing():
    case = run_conversion(prompt_error=RuntimeError("synthetic prompt failure"))

    assert case.result["success"] is False
    assert case.terminal.status == "failed"
    assert case.terminal.results and case.terminal.results[-1]["success"] is False
    assert _event_types(case).count("job.failed") == 1
    assert "job.completed" not in _event_types(case)
    assert case.order.index("result") < case.order.index("job.failed")

    failed = next(payload for event_type, payload in case.events if event_type == "job.failed")
    assert failed["stage"] == "document_conversion"
    assert failed["error_code"] == "internal"
    assert failed["retryable"] is False
    case.refund.assert_called_once()
    assert case.released == [JOB_ID]


def test_provider_timeout_is_bounded_and_terminalizes_once():
    request = httpx.Request("POST", "https://platform.example.test/v1/chat/completions")
    case = run_conversion(create_error=openai.APITimeoutError(request=request))

    assert case.result["success"] is False
    assert case.create.call_count == 1
    assert case.constructor.call_args.kwargs == {
        "api_key": "synthetic-platform-key",
        "base_url": "https://platform.example.test/v1",
        "timeout": 60.0,
        "max_retries": 0,
    }
    assert worker.convert_document_task.time_limit == 120
    assert worker.convert_document_task.soft_time_limit == 100
    assert worker.convert_document_task.max_retries == 0

    assert case.terminal.status == "failed"
    assert _event_types(case).count("job.failed") == 1
    assert "job.retrying" not in _event_types(case)
    failed = next(payload for event_type, payload in case.events if event_type == "job.failed")
    assert failed["error_code"] == "llm_error"
    assert failed["retryable"] is False
    case.refund.assert_called_once()


def test_configured_provider_404_terminalizes_without_retry():
    request = httpx.Request("POST", "https://platform.example.test/v1/chat/completions")
    error = openai.NotFoundError(
        "Synthetic model not found",
        response=httpx.Response(404, request=request),
        body={},
    )
    case = run_conversion(create_error=error)

    assert case.result["success"] is False
    assert case.create.call_count == 1
    assert case.terminal.status == "failed"
    assert _event_types(case).count("job.failed") == 1
    assert "job.retrying" not in _event_types(case)
    failed = next(payload for event_type, payload in case.events if event_type == "job.failed")
    assert failed["error_code"] == "llm_error"
    assert failed["retryable"] is False
    case.refund.assert_called_once()


def test_missing_api_key_terminalizes_before_any_provider_call():
    case = run_conversion(platform_key="")

    assert case.result["success"] is False
    case.constructor.assert_not_called()
    case.create.assert_not_called()
    assert _event_types(case).count("job.failed") == 1
    assert "job.started" not in _event_types(case)
    assert "job.progress" not in _event_types(case)
    assert case.terminal.status == "failed"
    failed = next(payload for event_type, payload in case.events if event_type == "job.failed")
    assert failed["error_code"] == "no_api_key"
    assert failed["retryable"] is False
    case.refund.assert_called_once()


def test_transient_result_transport_failure_retries_with_the_owner_lease():
    order = []
    terminal = TerminalRecorder(order, fail_first=True, require_owner=True)
    case = run_conversion(content="invalid output", terminal=terminal)

    # The first canonical write fails; the worker retries the same terminal
    # decision while it still owns the lease. Releasing first would make the
    # retry ownerless and leave the Redis job snapshot at processing.
    assert len(terminal.attempts) == 2
    assert terminal.status == "failed"
    assert case.result["success"] is False
    assert _event_types(case).count("job.failed") == 1
    assert "job.completed" not in _event_types(case)
    case.refund.assert_called_once()
    assert case.released == [JOB_ID]


@pytest.mark.parametrize("error", [TimeoutError("synthetic socket timeout"), OSError("synthetic socket")])
def test_non_openai_transport_error_terminalizes_as_internal_failure(error):
    case = run_conversion(create_error=error)

    assert case.result["success"] is False
    assert case.terminal.status == "failed"
    assert _event_types(case).count("job.failed") == 1
    failed = next(payload for event_type, payload in case.events if event_type == "job.failed")
    assert failed["error_code"] == "internal"
    assert failed["retryable"] is False
