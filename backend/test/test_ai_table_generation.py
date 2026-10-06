"""Text/image to LaTeX table conversion contract (#1345)."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from PIL import Image

from app.api.ai_routes import _build_latex_table, _parse_delimited_table


def _openai_response(rows: object) -> MagicMock:
    choice = MagicMock()
    choice.message.content = json.dumps({"rows": rows})
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


def test_generated_table_compiles_with_pdflatex(tmp_path) -> None:
    compiler = shutil.which("pdflatex")
    if compiler is None:
        pytest.skip("pdflatex is not installed")
    table = _build_latex_table(
        _parse_delimited_table("Name,Score\nR&D,50%"),
        first_row_header=True,
        source="text",
    ).latex
    source = "\\documentclass{article}\n\\begin{document}\n" + table + "\n\\end{document}\n"
    (tmp_path / "table.tex").write_text(source, encoding="utf-8")
    result = subprocess.run(
        [compiler, "-no-shell-escape", "-halt-on-error", "table.tex"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "table.pdf").read_bytes().startswith(b"%PDF-")


@pytest.mark.asyncio
class TestGenerateTableFromText:
    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(
            "/ai/generate-table",
            json={"table_text": "Name,Score\nAda,99"},
        )
        assert response.status_code == 401

    async def test_csv_becomes_portable_tabular(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        response = await client.post(
            "/ai/generate-table",
            headers=pro_auth_headers,
            json={"table_text": "Name,Score\nAda,99\nLinus,87"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["rows"] == 3
        assert data["columns"] == 2
        assert data["source"] == "text"
        assert r"\begin{tabular}{lr}" in data["latex"]
        assert r"\textbf{Name} & \textbf{Score} \\" in data["latex"]
        assert "Ada & 99" in data["latex"]
        assert r"\usepackage" not in data["latex"]

    async def test_tsv_without_header_and_ragged_rows_is_rectangular(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        response = await client.post(
            "/ai/generate-table",
            headers=pro_auth_headers,
            json={
                "table_text": "Alpha\t1\nBeta\t2\textra",
                "first_row_header": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["columns"] == 3
        assert r"\textbf" not in data["latex"]
        assert r"Alpha & 1 &  \\" in data["latex"]

    async def test_escapes_latex_special_characters(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        response = await client.post(
            "/ai/generate-table",
            headers=pro_auth_headers,
            json={"table_text": "Key,Value\nR&D,50%\nuser_name,$5"},
        )
        latex = response.json()["latex"]
        assert r"R\&D & 50\%" in latex
        assert r"user\_name & \$5" in latex

    @pytest.mark.parametrize(
        "table_text,detail",
        [
            ("one column only", "at least two"),
            ("a,b\n" + "\n".join(f"{i},{i}" for i in range(100)), "100 rows"),
            (",".join(f"c{i}" for i in range(21)), "20 columns"),
            ("a,b\n" + "x" * 501 + ",y", "500 characters"),
        ],
    )
    async def test_rejects_unbounded_or_non_tabular_input(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
        table_text: str,
        detail: str,
    ) -> None:
        response = await client.post(
            "/ai/generate-table",
            headers=pro_auth_headers,
            json={"table_text": table_text},
        )
        assert response.status_code == 422
        assert detail in response.json()["detail"]


@pytest.mark.asyncio
class TestGenerateTableFromImage:
    async def test_transcribes_cells_then_renders_table(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        with patch("app.api.ai_routes.settings") as settings, patch(
            "app.api.ai_routes.openai.AsyncOpenAI"
        ) as client_class:
            _settings(settings)
            openai_client = AsyncMock()
            openai_client.chat.completions.create = AsyncMock(
                return_value=_openai_response([["Name", "Score"], ["Ada", "99"]])
            )
            client_class.return_value = openai_client
            response = await client.post(
                "/ai/generate-table-image",
                headers=pro_auth_headers,
                files={"file": ("table.png", _png_bytes(), "image/png")},
                data={"first_row_header": "true"},
            )

        assert response.status_code == 200
        assert response.json()["source"] == "image"
        assert "Ada & 99" in response.json()["latex"]
        call = openai_client.chat.completions.create.call_args.kwargs
        image_url = call["messages"][1]["content"][1]["image_url"]["url"]
        assert image_url.startswith("data:image/jpeg;base64,")
        assert call["response_format"] == {"type": "json_object"}

    async def test_rejects_non_image_before_provider_call(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        with patch("app.api.ai_routes.openai.AsyncOpenAI") as client_class:
            response = await client.post(
                "/ai/generate-table-image",
                headers=pro_auth_headers,
                files={"file": ("table.png", b"not an image", "image/png")},
            )
        assert response.status_code == 415
        client_class.assert_not_called()

    async def test_enforces_streamed_upload_limit(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        response = await client.post(
            "/ai/generate-table-image",
            headers=pro_auth_headers,
            files={"file": ("table.png", b"x" * 5_000_001, "image/png")},
        )
        assert response.status_code == 413

    async def test_invalid_provider_matrix_refunds_quota(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        ticket = object()
        with patch("app.api.ai_routes.settings") as settings, patch(
            "app.api.ai_routes.openai.AsyncOpenAI"
        ) as client_class, patch(
            "app.api.ai_routes._charge_ai_assist", new_callable=AsyncMock, return_value=ticket
        ), patch(
            "app.api.ai_routes.entitlement_service.refund_quota", new_callable=AsyncMock
        ) as refund:
            _settings(settings)
            openai_client = AsyncMock()
            openai_client.chat.completions.create = AsyncMock(
                return_value=_openai_response([["only one column"]])
            )
            client_class.return_value = openai_client
            response = await client.post(
                "/ai/generate-table-image",
                headers=pro_auth_headers,
                files={"file": ("table.png", _png_bytes(), "image/png")},
            )

        assert response.status_code == 422
        refund.assert_awaited_once_with(ticket)

    async def test_no_key_reports_unavailable(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
    ) -> None:
        with patch("app.api.ai_routes.settings") as settings:
            settings.OPENAI_API_KEY = ""
            settings.RATE_LIMIT_ENABLED = False
            response = await client.post(
                "/ai/generate-table-image",
                headers=pro_auth_headers,
                files={"file": ("table.png", _png_bytes(), "image/png")},
            )
        assert response.status_code == 503
