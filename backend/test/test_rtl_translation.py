"""Authenticated translation endpoint coverage for Arabic and Hebrew."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

SOURCE = r"""\documentclass{article}
\begin{document}
\section{Experience}
\textbf{Senior Engineer} at Acme Corp\\
\begin{itemize}
\item Built systems with Python and PostgreSQL
\end{itemize}
\end{document}"""


def _response(text: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = text
    result = MagicMock()
    result.choices = [choice]
    return result


async def _create_resume(client: AsyncClient, headers: dict) -> str:
    response = await client.post(
        "/resumes/",
        headers=headers,
        json={"title": "RTL translation test", "latex_content": SOURCE},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "target", "text", "font_command", "font"),
    [
        ("ar", "Arabic", "السيرة الذاتية", r"\arabicfont", "Noto Naskh Arabic"),
        ("he", "Hebrew", "קורות חיים", r"\hebrewfont", "Noto Sans Hebrew"),
    ],
)
async def test_rtl_translation_selects_safe_lualatex_stack(
    client: AsyncClient,
    auth_headers: dict,
    code: str,
    target: str,
    text: str,
    font_command: str,
    font: str,
) -> None:
    resume_id = await _create_resume(client, auth_headers)
    translated = SOURCE.replace("Experience", text).replace(
        r"\textbf{Senior Engineer} at Acme Corp",
        rf"\textbf{{{text}}} at \textenglish{{Acme Corp}}",
    )
    with (
        patch("app.api.ai_routes.settings") as settings,
        patch("app.api.ai_routes.openai.AsyncOpenAI") as openai_cls,
        patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None),
        patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock),
    ):
        settings.OPENAI_API_KEY = "sk-test-dummy"
        settings.OPENAI_MODEL = "gpt-4o-mini"
        openai = AsyncMock()
        openai.chat.completions.create = AsyncMock(return_value=_response(translated))
        openai_cls.return_value = openai
        response = await client.post(
            "/ai/translate",
            headers=auth_headers,
            json={"resume_id": resume_id, "target_language": target, "language_code": code},
        )

    assert response.status_code == 200, response.text
    variant = await client.get(
        f"/resumes/{response.json()['variant_resume_id']}", headers=auth_headers
    )
    assert variant.status_code == 200, variant.text
    body = variant.json()
    assert body["metadata"]["compiler"] == "lualatex"
    latex = body["latex_content"]
    assert r"\usepackage{polyglossia}" in latex
    assert rf"\setmainlanguage{{{target.lower()}}}" in latex
    assert r"\setotherlanguage{english}" in latex
    assert rf"\newfontfamily{font_command}[Script={target},RawFeature={{fallback=latexy-rtl-latin}}" in latex
    assert text in latex
    assert r"\textenglish{Acme Corp}" in latex
    system_message = openai.chat.completions.create.await_args.kwargs["messages"][0]["content"]
    assert r"\textenglish{...}" in system_message


@pytest.mark.asyncio
async def test_rtl_translation_rejects_target_code_mismatch(
    client: AsyncClient, auth_headers: dict
) -> None:
    resume_id = await _create_resume(client, auth_headers)
    response = await client.post(
        "/ai/translate",
        headers=auth_headers,
        json={"resume_id": resume_id, "target_language": "French", "language_code": "he"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rtl_translation_rejects_arbitrary_locale(
    client: AsyncClient, auth_headers: dict
) -> None:
    resume_id = await _create_resume(client, auth_headers)
    response = await client.post(
        "/ai/translate",
        headers=auth_headers,
        json={
            "resume_id": resume_id,
            "target_language": "Arabic",
            "language_code": "ar-SA",
        },
    )
    assert response.status_code != 200
    assert response.status_code in (400, 422)
