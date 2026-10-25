"""Exercise OpenAI 3's actual HTTP transport without external sockets."""

import openai
import pytest

from app.core.config import settings

from .test_converter_failure_ledger_integration import VALID_LATEX, provider_transport


@pytest.mark.parametrize("outcome", ["model_404", "timeout", "invalid_output", "success"])
def test_sdk_transport_seam_captures_one_real_request_without_sockets(monkeypatch, outcome):
    requests = provider_transport(monkeypatch, outcome)
    with openai.OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL,
                       timeout=60.0, max_retries=0) as client:
        def create():
            return client.chat.completions.create(
                model=settings.OPENAI_MODEL, messages=[{"role": "user", "content": "Synthetic resume"}],
            )

        if outcome in {"model_404", "timeout"}:
            expected = openai.NotFoundError if outcome == "model_404" else openai.APITimeoutError
            with pytest.raises(expected):
                create()
        else:
            response = create()
            assert response.choices[0].message.content == ("invalid output" if outcome == "invalid_output" else VALID_LATEX)
    assert len(requests) == 1


