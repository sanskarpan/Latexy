"""Production model mismatch and eager retry must not strand conversions."""
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from app.workers import converter_worker as worker


def run_conversion(*, byok=None, error=None, content=None, result_stored=True, terminal_event="1-0", event_error=False):
    client = MagicMock()
    client.chat.completions.create.side_effect = error
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content if content is not None else
            r"\documentclass{article}\begin{document}Synthetic resume\end{document}"))],
        usage=SimpleNamespace(total_tokens=100),
    )
    events = MagicMock(return_value=terminal_event)
    if event_error:
        def deliver_event(_job_id, event_type, _payload):
            if event_type == "job.failed":
                raise ConnectionError("Synthetic event transport failure")
            return terminal_event
        events.side_effect = deliver_event
    refund = MagicMock()
    constructor = MagicMock(return_value=client)
    stored = MagicMock(return_value=result_stored)
    if event_error:
        # The first accepted result closes the owner fence. A second terminal
        # write after event transport failure must not regain that capability.
        stored.side_effect = [True, False]
    with ExitStack() as stack:
        for name, value in {
            "get_worker_redis": MagicMock(), "admit_worker": MagicMock(return_value=True),
            "publish_event": events, "publish_job_result": stored,
            "is_cancelled": MagicMock(return_value=False), "refund_quota_once": refund,
            "clear_quota_refund_receipt": MagicMock(), "stop_lease_heartbeat": MagicMock(),
            "clear_current_owner": MagicMock(),
        }.items():
            stack.enter_context(patch.object(worker, name, value))
        stack.enter_context(patch.object(worker.openai, "OpenAI", constructor))
        stack.enter_context(patch.object(worker.settings, "OPENAI_API_KEY", "synthetic-platform-key"))
        stack.enter_context(patch.object(worker.settings, "OPENAI_BASE_URL", "https://platform.example.test/v1"))
        stack.enter_context(patch.object(worker.settings, "OPENAI_MODEL", "configured-platform-model"))
        result = worker.convert_document_task.apply(kwargs={
            "extracted_data": {"raw_text": "Synthetic resume"}, "source_format": "text",
            "job_id": "synthetic-conversion-job", "user_id": "synthetic-owner", "user_api_key": byok,
            "quota_refund": {"dimension": "ai_assists", "user_id": "synthetic-owner", "cost": 1},
        }, throw=True).get()
    return result, constructor, client.chat.completions.create, events, refund, stored


def test_platform_conversion_uses_configured_endpoint_model_and_one_provider_attempt():
    result, constructor, create, _, refund, _ = run_conversion()
    assert result["success"] is True
    assert constructor.call_args.kwargs == {
        "api_key": "synthetic-platform-key", "base_url": "https://platform.example.test/v1",
        "timeout": 60.0, "max_retries": 0,
    }
    assert create.call_args.kwargs["model"] == "configured-platform-model"
    create.assert_called_once()
    refund.assert_not_called()


def test_openai_byok_never_goes_to_platform_proxy_or_uses_its_model():
    result, constructor, create, _, _, _ = run_conversion(byok="synthetic-user-key")
    assert result["success"] is True
    assert constructor.call_args.kwargs["base_url"] == "https://api.openai.com/v1"
    assert constructor.call_args.kwargs["api_key"] == "synthetic-user-key"
    assert create.call_args.kwargs["model"] == "gpt-4o-mini"


@pytest.mark.parametrize("failure", ["model_404", "timeout", "invalid_output"])
def test_provider_failures_terminalize_without_eager_replay_and_refund_once(failure):
    request = httpx.Request("POST", "https://platform.example.test/v1/chat/completions")
    error = (openai.NotFoundError("Model not found", response=httpx.Response(404, request=request), body={})
             if failure == "model_404" else openai.APITimeoutError(request=request) if failure == "timeout" else None)
    result, _, create, events, refund, stored = run_conversion(error=error, content="invalid" if failure == "invalid_output" else None)
    assert result["success"] is False
    create.assert_called_once()
    stored.assert_called_once()
    assert [call.args[1] for call in events.call_args_list].count("job.failed") == 1
    assert "job.retrying" not in [call.args[1] for call in events.call_args_list]
    refund.assert_called_once()


def test_rejected_terminal_result_does_not_refund_another_owner():
    _, _, _, events, refund, _ = run_conversion(content="invalid", result_stored=False)
    refund.assert_not_called()
    assert "job.failed" not in [call.args[1] for call in events.call_args_list]


def test_accepted_failure_refunds_even_if_terminal_event_is_lost():
    run, _, _, _, refund, _ = run_conversion(content="invalid", terminal_event="")
    assert run["success"] is False
    refund.assert_called_once()


def test_accepted_failure_refunds_when_terminal_event_transport_raises():
    result, _, create, events, refund, stored = run_conversion(content="invalid", event_error=True)
    assert result["success"] is False
    create.assert_called_once()
    refund.assert_called_once()
    stored.assert_called_once()
    assert [call.args[1] for call in events.call_args_list].count("job.failed") == 1
