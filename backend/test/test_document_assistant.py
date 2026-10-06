"""Contract tests for B31 document-aware conversational editing."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.api.ai_routes import (
    ResolvedAIKey,
    _validated_document_assistant_response,
)

LATEX = r"\documentclass{article}\begin{document}Built APIs.\end{document}"


def _openai_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(payload)
    return response


def test_validator_accepts_one_unique_reviewable_edit() -> None:
    result = _validated_document_assistant_response(
        json.dumps({
            "message": "This makes the action more specific.",
            "proposed_edit": {
                "target_text": "Built APIs.",
                "replacement_text": r"Designed and delivered APIs.",
            },
        }),
        LATEX,
    )
    assert result.proposed_edit is not None
    assert result.proposed_edit.target_text == "Built APIs."


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "bad target", "proposed_edit": {"target_text": "missing", "replacement_text": "Safe"}},
        {"message": "unsafe", "proposed_edit": {"target_text": "Built APIs.", "replacement_text": r"\input{/etc/passwd}"}},
    ],
)
def test_validator_rejects_missing_or_unsafe_edits(payload: dict) -> None:
    with pytest.raises(HTTPException) as exc:
        _validated_document_assistant_response(json.dumps(payload), LATEX)
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_document_assistant_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/ai/document-assistant",
        json={
            "resume_id": "123e4567-e89b-42d3-a456-426614174000",
            "latex_content": LATEX,
            "message": "Improve this",
        },
    )
    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_document_assistant_returns_reviewable_edit_for_owned_resume(
    client: AsyncClient,
    auth_headers: dict,
) -> None:
    created = await client.post(
        "/resumes/",
        headers=auth_headers,
        json={"title": "Assistant Resume", "latex_content": LATEX},
    )
    resume_id = created.json()["id"]
    completion = _openai_response({
        "message": "I proposed a more specific action verb.",
        "proposed_edit": {
            "target_text": "Built APIs.",
            "replacement_text": "Designed and delivered APIs.",
        },
    })
    openai_client = MagicMock()
    openai_client.chat.completions.create = AsyncMock(return_value=completion)

    with (
        patch(
            "app.api.ai_routes._resolve_ai_api_key",
            AsyncMock(return_value=ResolvedAIKey("sk-test", True)),
        ),
        patch("app.api.ai_routes.openai.AsyncOpenAI", return_value=openai_client),
    ):
        response = await client.post(
            "/ai/document-assistant",
            headers=auth_headers,
            json={
                "resume_id": resume_id,
                "latex_content": LATEX,
                "message": "Improve the opening statement",
                "history": [{"role": "user", "content": "Keep it concise"}],
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["proposed_edit"]["replacement_text"] == "Designed and delivered APIs."
    call = openai_client.chat.completions.create.await_args.kwargs
    assert call["response_format"] == {"type": "json_object"}
    assert "CURRENT LATEX DOCUMENT" in call["messages"][1]["content"]
