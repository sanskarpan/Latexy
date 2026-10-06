"""Malformed provider output must not become a fabricated zero-score success."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.services.deep_ats_response import DeepATSResponse
from app.workers import ats_worker

VALID = {
    "overall_score": 75, "overall_feedback": "Clear experience; quantify impact.",
    "sections": [{"name": "Experience", "score": 70, "strengths": ["Specific skills"],
                  "improvements": ["Add evidence"], "rewrite_suggestion": None}],
    "ats_compatibility": {"score": 80, "issues": [], "keyword_gaps": []},
    "job_match": None,
}


@pytest.mark.parametrize("score", [-1, 101, True, "75", float("inf"), float("nan")])
def test_deep_scores_are_finite_bounded_numbers(score):
    with pytest.raises(ValidationError):
        DeepATSResponse.model_validate({**VALID, "overall_score": score})


@pytest.mark.parametrize("output", [[], {}, {**VALID, "sections": ["not an object"]},
                                    {**VALID, "ats_compatibility": {"score": 80}},
                                    {**VALID, "sections": VALID["sections"] * 31},
                                    {**VALID, "overall_feedback": 123},
                                    {**VALID, "ats_compatibility": {
                                        "score": 80, "issues": "not a list", "keyword_gaps": [],
                                    }}])
def test_deep_analysis_requires_the_displayed_shape(output):
    with pytest.raises(ValidationError):
        DeepATSResponse.model_validate(output)


def test_valid_analysis_preserves_real_scores():
    assert DeepATSResponse.model_validate(VALID).model_dump() == VALID


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["not JSON", "[]", '{"overall_score": 0}', json.dumps(VALID)])
async def test_deep_worker_invalid_output_never_publishes_success(monkeypatch, content):
    provider = MagicMock()
    provider.chat.completions.create = AsyncMock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(total_tokens=10),
    ))
    provider.__aenter__ = AsyncMock(return_value=provider)
    provider.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=provider)
    monkeypatch.setattr("openai.AsyncOpenAI", factory)
    events = MagicMock(return_value="1-0")
    results = MagicMock(return_value=True)
    monkeypatch.setattr(ats_worker, "publish_event", events)
    monkeypatch.setattr(ats_worker, "publish_job_result", results)
    monkeypatch.setattr(ats_worker.ats_scoring_service, "_extract_text_from_latex", lambda *_: "Engineer")
    monkeypatch.setattr(ats_worker.ats_scoring_service, "score_resume", AsyncMock(return_value=SimpleNamespace(
        multi_dim_scores={"grammar": 92}, industry_key="tech_saas", industry_label="Technology / SaaS",
    )))
    success = await ats_worker._async_deep_analyze(None, "source", "deep-test", None, "test-key")
    expected_success = content == json.dumps(VALID)
    assert success is expected_success
    terminal = [call.args[1] for call in events.call_args_list
                if call.args[1] in {"job.failed", "job.completed", "ats.deep_complete"}]
    assert terminal == (["ats.deep_complete", "job.completed"] if expected_success else ["job.failed"])
    assert results.call_args.args[1]["success"] is expected_success
    if expected_success:
        durable_analysis = results.call_args.args[1]["deep_analysis"]
        assert durable_analysis["multi_dim_scores"] == {"grammar": 92}
        assert durable_analysis["industry_key"] == "tech_saas"
        assert durable_analysis["industry_label"] == "Technology / SaaS"
        assert durable_analysis["tokens_used"] == 10
        assert durable_analysis["analysis_time"] >= 0
        completed = next(call for call in events.call_args_list if call.args[1] == "job.completed")
        assert completed.args[2]["pdf_job_id"] is None
    provider.__aexit__.assert_awaited_once()
    factory.assert_called_once_with(api_key="test-key", timeout=60.0, max_retries=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("controlled failure"), asyncio.CancelledError()])
async def test_provider_error_still_closes_transport(monkeypatch, failure):
    provider = MagicMock()
    provider.__aenter__ = AsyncMock(return_value=provider)
    provider.__aexit__ = AsyncMock(return_value=False)
    provider.chat.completions.create = AsyncMock(side_effect=failure)
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **_: provider)
    monkeypatch.setattr(ats_worker, "publish_event", MagicMock())
    monkeypatch.setattr(ats_worker.ats_scoring_service, "_extract_text_from_latex", lambda *_: "Engineer")
    with pytest.raises(type(failure)):
        await ats_worker._async_deep_analyze(None, "source", "deep-test", None, "test-key")
    provider.__aexit__.assert_awaited_once()
