"""Tests for Feature 71: Watermark Control."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.workers.latex_worker import _WATERMARK_MAX_LEN, _WATERMARK_RE, _inject_watermark

SIMPLE_LATEX = r"""
\documentclass{article}
\begin{document}
Hello world.
\end{document}
"""


# ─── Unit tests for _inject_watermark ───────────────────────────────────────

class TestInjectWatermark:
    def test_injects_usepackage(self):
        result = _inject_watermark(SIMPLE_LATEX, "DRAFT")
        assert r"\usepackage{draftwatermark}" in result

    def test_injects_set_watermark_text(self):
        result = _inject_watermark(SIMPLE_LATEX, "DRAFT")
        assert r"\SetWatermarkText{DRAFT}" in result

    def test_injects_before_begin_document(self):
        result = _inject_watermark(SIMPLE_LATEX, "DRAFT")
        pkg_pos = result.find(r"\usepackage{draftwatermark}")
        begin_pos = result.find(r"\begin{document}")
        assert pkg_pos < begin_pos, "watermark block must appear before \\begin{document}"

    def test_custom_text_injected(self):
        result = _inject_watermark(SIMPLE_LATEX, "CONFIDENTIAL")
        assert r"\SetWatermarkText{CONFIDENTIAL}" in result

    def test_no_begin_document_unchanged(self):
        """If no \\begin{document}, content returned unchanged (defensive)."""
        bad = r"\documentclass{article} Hello."
        result = _inject_watermark(bad, "DRAFT")
        assert result == bad

    def test_scale_and_color_injected(self):
        result = _inject_watermark(SIMPLE_LATEX, "DRAFT")
        assert r"\SetWatermarkScale{1.2}" in result
        assert r"\SetWatermarkColor[gray]{0.94}" in result


# ─── Watermark validation regex ─────────────────────────────────────────────

class TestWatermarkValidation:
    def test_valid_preset(self):
        assert _WATERMARK_RE.match("DRAFT")
        assert _WATERMARK_RE.match("CONFIDENTIAL")
        assert _WATERMARK_RE.match("FOR REVIEW ONLY")

    def test_valid_with_hyphen_and_dot(self):
        assert _WATERMARK_RE.match("v1.0-BETA")

    def test_invalid_shell_injection(self):
        assert not _WATERMARK_RE.match("rm -rf /")

    def test_invalid_semicolons(self):
        assert not _WATERMARK_RE.match("A;B")

    def test_invalid_backslash(self):
        assert not _WATERMARK_RE.match(r"A\B")

    def test_max_length(self):
        assert len("A" * _WATERMARK_MAX_LEN) == _WATERMARK_MAX_LEN
        assert len("A" * (_WATERMARK_MAX_LEN + 1)) > _WATERMARK_MAX_LEN


# ─── API endpoint tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestCompileWatermarkedEndpoint:

    @patch("app.api.job_routes.submit_latex_compilation")
    async def test_valid_watermark_returns_job_id(
        self, mock_submit, client: AsyncClient
    ):
        """Valid watermark + latex_content → 200 with job_id."""
        mock_submit.return_value = "test-job-id"
        resp = await client.post(
            "/jobs/compile-watermarked",
            json={
                "latex_content": SIMPLE_LATEX,
                "watermark": "DRAFT",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "job_id" in data
        assert data["job_id"]  # non-empty

    @patch("app.api.job_routes.submit_latex_compilation")
    async def test_watermarked_job_id_differs_from_canonical(
        self, mock_submit, client: AsyncClient
    ):
        """Two separate calls produce two different job IDs."""
        mock_submit.return_value = "unused"
        resp1 = await client.post(
            "/jobs/compile-watermarked",
            json={"latex_content": SIMPLE_LATEX, "watermark": "DRAFT"},
        )
        resp2 = await client.post(
            "/jobs/compile-watermarked",
            json={"latex_content": SIMPLE_LATEX, "watermark": "DRAFT"},
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["job_id"] != resp2.json()["job_id"]

    async def test_shell_injection_rejected(self, client: AsyncClient):
        """watermark='rm -rf /' → 422 Unprocessable Entity."""
        resp = await client.post(
            "/jobs/compile-watermarked",
            json={
                "latex_content": SIMPLE_LATEX,
                "watermark": "rm -rf /",
            },
        )
        assert resp.status_code == 422

    async def test_31_char_watermark_rejected(self, client: AsyncClient):
        """Watermark of 31 chars → 422."""
        resp = await client.post(
            "/jobs/compile-watermarked",
            json={
                "latex_content": SIMPLE_LATEX,
                "watermark": "A" * 31,
            },
        )
        assert resp.status_code == 422

    async def test_empty_watermark_rejected(self, client: AsyncClient):
        """Empty watermark → 422."""
        resp = await client.post(
            "/jobs/compile-watermarked",
            json={
                "latex_content": SIMPLE_LATEX,
                "watermark": "",
            },
        )
        assert resp.status_code == 422

    async def test_empty_latex_content_rejected(self, client: AsyncClient):
        """Empty latex_content → 422."""
        resp = await client.post(
            "/jobs/compile-watermarked",
            json={
                "latex_content": "   ",
                "watermark": "DRAFT",
            },
        )
        assert resp.status_code == 422

    @patch("app.api.job_routes.submit_latex_compilation")
    async def test_watermark_passed_to_worker(
        self, mock_submit, client: AsyncClient
    ):
        """Ensure submit_latex_compilation is called with the watermark kwarg."""
        mock_submit.return_value = "job-123"
        await client.post(
            "/jobs/compile-watermarked",
            json={
                "latex_content": SIMPLE_LATEX,
                "watermark": "CONFIDENTIAL",
            },
        )
        mock_submit.assert_called_once()
        call_kwargs = mock_submit.call_args.kwargs
        assert call_kwargs.get("watermark") == "CONFIDENTIAL"
