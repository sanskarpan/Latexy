"""Text/image to LaTeX math generation contract (#1346)."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from PIL import Image

from app.api.ai_routes import _render_math


def _response(latex: object) -> MagicMock:
    choice = MagicMock()
    choice.message.content = json.dumps({"latex": latex})
    response = MagicMock()
    response.choices = [choice]
    return response


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (80, 40), "white").save(output, format="PNG")
    return output.getvalue()


def _settings(mock: MagicMock) -> None:
    mock.OPENAI_API_KEY = "sk-test-dummy"
    mock.OPENAI_MODEL = "gpt-4o-mini"
    mock.RATE_LIMIT_ENABLED = False


def test_rendered_math_modes_compile_with_pdflatex(tmp_path) -> None:
    compiler = shutil.which("pdflatex")
    if compiler is None:
        pytest.skip("pdflatex is not installed")
    fragments = [
        _render_math(r"x_1 + y^2", mode, source="text", cached=False).latex
        for mode in ("inline", "display", "equation")
    ]
    source = "\\documentclass{article}\n\\begin{document}\n" + "\n".join(fragments) + "\n\\end{document}\n"
    (tmp_path / "math.tex").write_text(source, encoding="utf-8")
    result = subprocess.run(
        [compiler, "-no-shell-escape", "-halt-on-error", "math.tex"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "math.pdf").read_bytes().startswith(b"%PDF-")


@pytest.mark.asyncio
class TestGenerateMathFromText:
    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(
            "/ai/generate-math",
            json={"math_text": "x squared"},
        )
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "payload",
        [
            {"math_text": " "},
            {"math_text": "x" * 5001},
            {"math_text": "x squared", "display_mode": "invalid"},
        ],
    )
    async def test_validates_request(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
        payload: dict,
    ) -> None:
        response = await client.post(
            "/ai/generate-math",
            headers=pro_auth_headers,
            json=payload,
        )
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "mode,provider_value,expected",
        [
            ("inline", "$x^2$", "$x^2$"),
            ("display", "\\[x^2\\]", "\\[\nx^2\n\\]"),
            (
                "equation",
                "\\begin{equation}x^2\\end{equation}",
                "\\begin{equation}\nx^2\n\\end{equation}",
            ),
        ],
    )
    async def test_normalizes_provider_wrappers_and_applies_requested_mode(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
        mode: str,
        provider_value: str,
        expected: str,
    ) -> None:
        with patch("app.api.ai_routes.settings") as settings, patch(
            "app.api.ai_routes.openai.AsyncOpenAI"
        ) as client_class, patch(
            "app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None
        ), patch(
            "app.api.ai_routes.cache_manager.set", new_callable=AsyncMock
        ):
            _settings(settings)
            openai_client = AsyncMock()
            openai_client.chat.completions.create = AsyncMock(return_value=_response(provider_value))
            client_class.return_value = openai_client
            response = await client.post(
                "/ai/generate-math",
                headers=pro_auth_headers,
                json={"math_text": "x squared", "display_mode": mode},
            )

        assert response.status_code == 200
        assert response.json() == {
            "latex": expected,
            "display_mode": mode,
            "source": "text",
            "cached": False,
        }
        call = openai_client.chat.completions.create.call_args.kwargs
        assert call["messages"][1]["content"] == "x squared"
        assert call["response_format"] == {"type": "json_object"}

    async def test_valid_cache_skips_provider(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        with patch(
            "app.api.ai_routes.cache_manager.get",
            new_callable=AsyncMock,
            return_value={"body": r"\frac{a}{b}"},
        ), patch("app.api.ai_routes.openai.AsyncOpenAI") as client_class:
            response = await client.post(
                "/ai/generate-math",
                headers=pro_auth_headers,
                json={"math_text": "a divided by b"},
            )
        assert response.status_code == 200
        assert response.json()["cached"] is True
        assert response.json()["latex"] == "\\[\n\\frac{a}{b}\n\\]"
        client_class.assert_not_called()

    @pytest.mark.parametrize(
        "provider_value",
        [
            r"\documentclass{article}",
            r"\input{secret.tex}",
            r"\frac{a}{b",
            "$x$ and $y$",
        ],
    )
    async def test_rejects_malformed_or_non_fragment_output_and_refunds(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
        provider_value: str,
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
            openai_client.chat.completions.create = AsyncMock(return_value=_response(provider_value))
            client_class.return_value = openai_client
            response = await client.post(
                "/ai/generate-math",
                headers=pro_auth_headers,
                json={"math_text": "make math"},
            )

        assert response.status_code == 502
        refund.assert_awaited_once_with(ticket)


@pytest.mark.asyncio
class TestGenerateMathFromImage:
    async def test_transcribes_image_without_solving_and_wraps_result(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        with patch("app.api.ai_routes.settings") as settings, patch(
            "app.api.ai_routes.openai.AsyncOpenAI"
        ) as client_class:
            _settings(settings)
            openai_client = AsyncMock()
            openai_client.chat.completions.create = AsyncMock(return_value=_response(r"E = mc^2"))
            client_class.return_value = openai_client
            response = await client.post(
                "/ai/generate-math-image",
                headers=pro_auth_headers,
                files={"file": ("equation.png", _png_bytes(), "image/png")},
                data={"display_mode": "equation"},
            )

        assert response.status_code == 200
        assert response.json() == {
            "latex": "\\begin{equation}\nE = mc^2\n\\end{equation}",
            "display_mode": "equation",
            "source": "image",
            "cached": False,
        }
        call = openai_client.chat.completions.create.call_args.kwargs
        assert "do not solve" in call["messages"][0]["content"].lower()
        image_url = call["messages"][1]["content"][1]["image_url"]["url"]
        assert image_url.startswith("data:image/jpeg;base64,")

    async def test_rejects_invalid_image_before_provider_call(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        with patch("app.api.ai_routes.openai.AsyncOpenAI") as client_class:
            response = await client.post(
                "/ai/generate-math-image",
                headers=pro_auth_headers,
                files={"file": ("equation.png", b"not an image", "image/png")},
            )
        assert response.status_code == 415
        client_class.assert_not_called()

    async def test_invalid_display_mode_is_rejected(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        response = await client.post(
            "/ai/generate-math-image",
            headers=pro_auth_headers,
            files={"file": ("equation.png", _png_bytes(), "image/png")},
            data={"display_mode": "align"},
        )
        assert response.status_code == 422
