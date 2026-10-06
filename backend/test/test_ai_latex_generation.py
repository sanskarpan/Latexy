"""Natural-language to LaTeX generation contract (#1344)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


def _response(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def _settings(mock: MagicMock) -> None:
    mock.OPENAI_API_KEY = "sk-test-dummy"
    mock.OPENAI_MODEL = "gpt-4o-mini"
    mock.RATE_LIMIT_ENABLED = False


@pytest.mark.asyncio
class TestGenerateLatex:
    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(
            "/ai/generate-latex",
            json={"intent": "Create a skills section"},
        )
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "payload",
        [
            {"intent": "    "},
            {"intent": "x" * 2001},
            {"intent": "Create a section", "document_context": "x" * 20_001},
        ],
    )
    async def test_rejects_invalid_input(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
        payload: dict,
    ) -> None:
        response = await client.post(
            "/ai/generate-latex",
            headers=pro_auth_headers,
            json=payload,
        )
        assert response.status_code == 422

    async def test_generates_and_caches_insertable_fragment(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        generated = "```latex\n\\section{Skills}\n\\begin{itemize}\n\\item Python\n\\end{itemize}\n```"
        with patch("app.api.ai_routes.settings") as settings, patch(
            "app.api.ai_routes.openai.AsyncOpenAI"
        ) as client_class, patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(
            "app.api.ai_routes.cache_manager.set", new_callable=AsyncMock
        ) as cache_set:
            _settings(settings)
            openai_client = AsyncMock()
            openai_client.chat.completions.create = AsyncMock(return_value=_response(generated))
            client_class.return_value = openai_client

            response = await client.post(
                "/ai/generate-latex",
                headers=pro_auth_headers,
                json={
                    "intent": "  Create   a skills section with Python  ",
                    "document_context": "\\section{Experience}",
                },
            )

        assert response.status_code == 200
        assert response.json() == {
            "latex": "\\section{Skills}\n\\begin{itemize}\n\\item Python\n\\end{itemize}",
            "cached": False,
        }
        call = openai_client.chat.completions.create.call_args.kwargs
        assert "Create a skills section with Python" in call["messages"][1]["content"]
        assert "\\section{Experience}" in call["messages"][1]["content"]
        cache_set.assert_awaited_once()

    async def test_valid_cache_skips_provider(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        with patch(
            "app.api.ai_routes.cache_manager.get",
            new_callable=AsyncMock,
            return_value={"latex": "\\section{Projects}"},
        ), patch("app.api.ai_routes.openai.AsyncOpenAI") as client_class:
            response = await client.post(
                "/ai/generate-latex",
                headers=pro_auth_headers,
                json={"intent": "Create a projects section"},
            )
        assert response.status_code == 200
        assert response.json() == {"latex": "\\section{Projects}", "cached": True}
        client_class.assert_not_called()

    @pytest.mark.parametrize(
        "generated,detail",
        [
            (
                "\\documentclass{article}\\begin{document}Hi\\end{document}",
                "full document",
            ),
            ("\\input{another-file.tex}", "file-loading"),
            ("\\input{/etc/passwd}", "file-loading"),
            ("\\section{Broken", "unsafe or malformed"),
            ("\\begin{itemize}\\item One\\end{enumerate}", "unbalanced"),
        ],
    )
    async def test_rejects_non_insertable_provider_output_and_refunds(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
        generated: str,
        detail: str,
    ) -> None:
        ticket = object()
        with patch("app.api.ai_routes.settings") as settings, patch(
            "app.api.ai_routes.openai.AsyncOpenAI"
        ) as client_class, patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(
            "app.api.ai_routes._charge_ai_assist", new_callable=AsyncMock, return_value=ticket
        ), patch(
            "app.api.ai_routes.entitlement_service.refund_quota", new_callable=AsyncMock
        ) as refund:
            _settings(settings)
            openai_client = AsyncMock()
            openai_client.chat.completions.create = AsyncMock(return_value=_response(generated))
            client_class.return_value = openai_client
            response = await client.post(
                "/ai/generate-latex",
                headers=pro_auth_headers,
                json={"intent": "Create a safe section"},
            )

        assert response.status_code == 502
        assert detail in response.json()["detail"]
        refund.assert_awaited_once_with(ticket)

    async def test_no_key_reports_unavailable(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        with patch("app.api.ai_routes.settings") as settings, patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ):
            settings.OPENAI_API_KEY = ""
            settings.RATE_LIMIT_ENABLED = False
            response = await client.post(
                "/ai/generate-latex",
                headers=pro_auth_headers,
                json={"intent": "Create a skills section"},
            )
        assert response.status_code == 503

    async def test_provider_failure_refunds_platform_quota(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        ticket = object()
        with patch("app.api.ai_routes.settings") as settings, patch(
            "app.api.ai_routes.openai.AsyncOpenAI"
        ) as client_class, patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(
            "app.api.ai_routes._charge_ai_assist", new_callable=AsyncMock, return_value=ticket
        ), patch(
            "app.api.ai_routes.entitlement_service.refund_quota", new_callable=AsyncMock
        ) as refund:
            _settings(settings)
            openai_client = AsyncMock()
            openai_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("down"))
            client_class.return_value = openai_client
            response = await client.post(
                "/ai/generate-latex",
                headers=pro_auth_headers,
                json={"intent": "Create a skills section"},
            )

        assert response.status_code == 502
        refund.assert_awaited_once_with(ticket)
