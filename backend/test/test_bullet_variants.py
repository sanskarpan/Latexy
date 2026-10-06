"""Persisted, per-job bullet rewrite library (#1286)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

SOURCE = r"\item Led platform migration for 20 teams."
LATEX = rf"""\documentclass{{article}}
\begin{{document}}
\begin{{itemize}}
{SOURCE}
\end{{itemize}}
\end{{document}}"""
OPTIONS = [
    r"\item Directed platform migration across 20 teams.",
    r"\item Orchestrated a platform migration serving 20 teams.",
    r"\item Guided 20 teams through a platform migration.",
]


def _openai_response(options: list[str]) -> MagicMock:
    import json

    choice = MagicMock()
    choice.message.content = json.dumps({"variants": options})
    response = MagicMock()
    response.choices = [choice]
    return response


async def _create_resume(client: AsyncClient, headers: dict) -> str:
    response = await client.post(
        "/resumes/",
        headers=headers,
        json={"title": "test_bullet_library", "latex_content": LATEX},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _mock_provider(options: list[str]):
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_openai_response(options)
    )
    return patch(
        "app.api.ai_routes.openai.AsyncOpenAI", return_value=mock_client
    )


@pytest.mark.asyncio
async def test_generate_list_regenerate_and_delete_variant_set(
    client: AsyncClient,
    pro_auth_headers: dict,
) -> None:
    resume_id = await _create_resume(client, pro_auth_headers)
    request = {
        "resume_id": resume_id,
        "source_text": SOURCE,
        "job_description": "Lead a platform organization through migrations.",
        "target_label": "Acme — Staff Engineer",
    }

    with patch("app.api.ai_routes.settings") as mock_settings, _mock_provider(OPTIONS):
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        created = await client.post(
            "/ai/bullet-variants", headers=pro_auth_headers, json=request
        )

    assert created.status_code == 200, created.text
    data = created.json()
    assert data["options"] == OPTIONS
    assert data["target_label"] == "Acme — Staff Engineer"
    assert "job_description" not in data

    listed = await client.get(
        f"/ai/bullet-variants?resume_id={resume_id}", headers=pro_auth_headers
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [data["id"]]

    regenerated_options = [option.replace("migration", "transition") for option in OPTIONS]
    with patch("app.api.ai_routes.settings") as mock_settings, _mock_provider(regenerated_options):
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        regenerated = await client.post(
            "/ai/bullet-variants", headers=pro_auth_headers, json=request
        )

    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["id"] == data["id"]
    assert regenerated.json()["options"] == regenerated_options

    deleted = await client.delete(
        f"/ai/bullet-variants/{data['id']}", headers=pro_auth_headers
    )
    assert deleted.status_code == 204
    listed_after_delete = await client.get(
        f"/ai/bullet-variants?resume_id={resume_id}", headers=pro_auth_headers
    )
    assert listed_after_delete.json() == []


@pytest.mark.asyncio
async def test_variant_library_is_private_to_resume_owner(
    client: AsyncClient,
    pro_auth_headers: dict,
    auth_headers2: dict,
) -> None:
    resume_id = await _create_resume(client, pro_auth_headers)
    response = await client.get(
        f"/ai/bullet-variants?resume_id={resume_id}", headers=auth_headers2
    )
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options",
    [
        OPTIONS[:2],
        [OPTIONS[0], OPTIONS[0], OPTIONS[2]],
        [OPTIONS[0].removeprefix(r"\item "), OPTIONS[1], OPTIONS[2]],
        [OPTIONS[0], OPTIONS[1], SOURCE],
    ],
)
async def test_rejects_incomplete_duplicate_or_format_breaking_provider_output(
    client: AsyncClient,
    pro_auth_headers: dict,
    options: list[str],
) -> None:
    resume_id = await _create_resume(client, pro_auth_headers)
    with patch("app.api.ai_routes.settings") as mock_settings, _mock_provider(options):
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        response = await client.post(
            "/ai/bullet-variants",
            headers=pro_auth_headers,
            json={"resume_id": resume_id, "source_text": SOURCE},
        )

    assert response.status_code == 502
    listed = await client.get(
        f"/ai/bullet-variants?resume_id={resume_id}", headers=pro_auth_headers
    )
    assert listed.json() == []


@pytest.mark.asyncio
async def test_rejects_a_variant_already_present_in_resume(
    client: AsyncClient,
    pro_auth_headers: dict,
) -> None:
    resume_id = await _create_resume(client, pro_auth_headers)
    duplicate = OPTIONS[2]
    options = [OPTIONS[0], OPTIONS[1], duplicate]
    await client.put(
        f"/resumes/{resume_id}",
        headers=pro_auth_headers,
        json={
            "title": "test_bullet_library",
            "latex_content": f"{LATEX}\n{duplicate}",
            "expected_latex_content": LATEX,
        },
    )

    with patch("app.api.ai_routes.settings") as mock_settings, _mock_provider(options):
        mock_settings.OPENAI_API_KEY = "sk-test"
        mock_settings.OPENAI_MODEL = "gpt-4o-mini"
        response = await client.post(
            "/ai/bullet-variants",
            headers=pro_auth_headers,
            json={"resume_id": resume_id, "source_text": SOURCE},
        )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_variant_generation_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/ai/bullet-variants",
        json={"resume_id": "00000000-0000-0000-0000-000000000000", "source_text": SOURCE},
    )
    assert response.status_code == 401
