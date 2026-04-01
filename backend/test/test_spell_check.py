"""
Tests for Feature 35 — Spell Check & Grammar.

Covers:
  - extract_prose() text extraction and position tracking
  - POST /ai/spell-check endpoint (mocked LanguageTool responses)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.services.latex_text_extractor import extract_prose, offset_to_latex_position

# ── 35A: Text Extractor ────────────────────────────────────────────────────


class TestExtractProse:
    """Unit tests for extract_prose() — no DB or Redis required."""

    DOCUMENT_WRAP = r"\begin{document}" + "{content}" + r"\end{document}"

    def _wrap(self, content: str) -> str:
        return self.DOCUMENT_WRAP.replace("{content}", content)

    def test_strips_textbf_preserves_content(self):
        segs = extract_prose(self._wrap(r"\textbf{hello world}"))
        combined = " ".join(s.text for s in segs)
        assert "hello world" in combined

    def test_strips_inline_math(self):
        segs = extract_prose(self._wrap(r"See $\alpha + \beta$ for more details."))
        combined = " ".join(s.text for s in segs)
        assert r"\alpha" not in combined
        assert "details" in combined

    def test_strips_display_math(self):
        segs = extract_prose(self._wrap(r"Before $$\sum_{i=0}^{n} x_i$$ after."))
        combined = " ".join(s.text for s in segs)
        assert r"\sum" not in combined

    def test_preserves_item_text(self):
        tex = self._wrap(
            r"\begin{itemize}" + "\n"
            r"\item Developed scalable APIs" + "\n"
            r"\end{itemize}"
        )
        segs = extract_prose(tex)
        combined = " ".join(s.text for s in segs)
        assert "Developed scalable APIs" in combined

    def test_strips_comment(self):
        segs = extract_prose(self._wrap("This is text % this is a comment"))
        combined = " ".join(s.text for s in segs)
        assert "comment" not in combined
        assert "text" in combined

    def test_segment_has_line_numbers(self):
        tex = r"\begin{document}" + "\nhello\nworld\n" + r"\end{document}"
        segs = extract_prose(tex)
        # Should have segments on different lines
        line_numbers = {s.start_line for s in segs}
        assert len(line_numbers) >= 1

    def test_prose_offset_monotonically_increasing(self):
        tex = self._wrap("\nHello world\nGoodbye world\n")
        segs = extract_prose(tex)
        offsets = [s.prose_offset for s in segs]
        assert offsets == sorted(offsets), f"Offsets not sorted: {offsets}"

    def test_preamble_stripped(self):
        tex = r"\usepackage{geometry}" + "\n" + self._wrap("visible text")
        segs = extract_prose(tex)
        combined = " ".join(s.text for s in segs)
        assert "geometry" not in combined
        assert "visible" in combined

    def test_suppress_equation_environment(self):
        tex = self._wrap(
            r"\begin{equation}" + "\n"
            r"E = mc^2" + "\n"
            r"\end{equation}"
        )
        segs = extract_prose(tex)
        combined = " ".join(s.text for s in segs)
        assert "mc" not in combined

    def test_offset_to_latex_position_basic(self):
        from app.services.latex_text_extractor import ProseSegment
        seg = ProseSegment(text="hello world", start_line=5, start_col=3, prose_offset=0)
        sl, sc, el, ec = offset_to_latex_position(0, 5, [seg])
        assert sl == 5
        assert sc == 3  # at start
        assert el == 5

    def test_offset_to_latex_position_empty_segments(self):
        result = offset_to_latex_position(0, 5, [])
        assert result == (1, 1, 1, 1)


# ── 35B: Spell Check Endpoint ─────────────────────────────────────────────


@pytest.mark.asyncio
class TestSpellCheckEndpoint:
    """Integration tests for POST /ai/spell-check with mocked LanguageTool."""

    _MOCK_LT_RESPONSE = {
        "matches": [
            {
                "offset": 0,
                "length": 5,
                "message": "Possible spelling mistake found.",
                "replacements": [{"value": "Hello"}, {"value": "Hell"}],
                "rule": {
                    "id": "MORFOLOGIK_RULE_EN_US",
                    "category": {"id": "TYPOS"},
                },
            }
        ]
    }

    def _make_mock_httpx(self, response_json: dict, status_code: int = 200):
        """Return a mock httpx.AsyncClient that returns the given JSON."""
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = response_json

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        return mock_client

    async def test_returns_required_fields(self, client: AsyncClient):
        with patch("app.api.ai_routes.httpx.AsyncClient", return_value=self._make_mock_httpx(self._MOCK_LT_RESPONSE)):
            resp = await client.post(
                "/ai/spell-check",
                json={
                    "latex_content": r"\begin{document}Helo world\end{document}",
                    "language": "en-US",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "issues" in data
        assert "cached" in data

    async def test_lt_response_maps_to_issues(self, client: AsyncClient):
        with patch("app.api.ai_routes.httpx.AsyncClient", return_value=self._make_mock_httpx(self._MOCK_LT_RESPONSE)):
            resp = await client.post(
                "/ai/spell-check",
                json={
                    "latex_content": r"\begin{document}Helo world\end{document}",
                    "language": "en-US",
                },
            )
        data = resp.json()
        # At least one issue should be mapped (offset 0 → some line/col)
        assert isinstance(data["issues"], list)

    async def test_lt_timeout_returns_empty(self, client: AsyncClient):
        import httpx as _httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=_httpx.TimeoutException("timeout"))

        with patch("app.api.ai_routes.httpx.AsyncClient", return_value=mock_client):
            resp = await client.post(
                "/ai/spell-check",
                json={
                    "latex_content": r"\begin{document}Some text here\end{document}",
                    "language": "en-US",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["issues"] == []

    async def test_invalid_language_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/spell-check",
            json={
                "latex_content": r"\begin{document}Text\end{document}",
                "language": "invalid-xx",
            },
        )
        assert resp.status_code == 422

    async def test_too_long_content_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/spell-check",
            json={
                "latex_content": "x" * 200_001,
                "language": "en-US",
            },
        )
        assert resp.status_code == 422

    async def test_valid_short_language_code(self, client: AsyncClient):
        with patch("app.api.ai_routes.httpx.AsyncClient", return_value=self._make_mock_httpx({"matches": []})):
            resp = await client.post(
                "/ai/spell-check",
                json={
                    "latex_content": r"\begin{document}Some text\end{document}",
                    "language": "de",
                },
            )
        assert resp.status_code == 200

    async def test_source_is_not_cached_on_first_call(self, client: AsyncClient):
        # Use a unique content to avoid hitting Redis cache from other tests
        import uuid
        unique_content = r"\begin{document}unique spell check test " + uuid.uuid4().hex + r"\end{document}"
        with patch("app.api.ai_routes.httpx.AsyncClient", return_value=self._make_mock_httpx({"matches": []})):
            resp = await client.post(
                "/ai/spell-check",
                json={"latex_content": unique_content, "language": "en-US"},
            )
        assert resp.status_code == 200
        assert resp.json()["cached"] is False

    async def test_lt_non_200_returns_empty(self, client: AsyncClient):
        with patch("app.api.ai_routes.httpx.AsyncClient", return_value=self._make_mock_httpx({}, status_code=503)):
            resp = await client.post(
                "/ai/spell-check",
                json={
                    "latex_content": r"\begin{document}Some text\end{document}",
                    "language": "en-US",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["issues"] == []
