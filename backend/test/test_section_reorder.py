"""
Tests for Feature 53 — AI Section Reordering.

Covers:
  53A — extract_sections() identifies sections and returns correct preamble
  53A — reorder_sections() preserves all content, only changes order
  53B — POST /ai/reorder-sections returns reordered_latex with sections in
         suggested_order sequence (LLM mocked)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.services.latex_section_parser import (
    extract_sections,
    reorder_sections,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_FOUR_SECTION_LATEX = r"""
\documentclass{article}
\begin{document}

\section{Experience}
\begin{itemize}
  \item Software Engineer at Acme Corp, 2020--2023
\end{itemize}

\section{Education}
\begin{itemize}
  \item B.Sc. Computer Science, MIT, 2020
\end{itemize}

\section{Skills}
Python, FastAPI, PostgreSQL

\section{Projects}
\begin{itemize}
  \item Built a resume parser
\end{itemize}

\end{document}
""".strip()


# ---------------------------------------------------------------------------
# 53A — extract_sections
# ---------------------------------------------------------------------------


class TestExtractSections:
    def test_identifies_four_sections(self):
        preamble, sections = extract_sections(_FOUR_SECTION_LATEX)
        assert len(sections) == 4
        names = [s.name for s in sections]
        assert names == ["Experience", "Education", "Skills", "Projects"]

    def test_preamble_contains_documentclass(self):
        preamble, _ = extract_sections(_FOUR_SECTION_LATEX)
        assert "\\documentclass" in preamble
        assert "\\begin{document}" in preamble

    def test_section_content_includes_header_line(self):
        _, sections = extract_sections(_FOUR_SECTION_LATEX)
        for s in sections:
            assert s.content.startswith(f"\\section{{{s.name}}}")

    def test_line_numbers_are_positive(self):
        _, sections = extract_sections(_FOUR_SECTION_LATEX)
        for s in sections:
            assert s.start_line >= 1
            assert s.end_line >= s.start_line

    def test_no_section_returns_full_source_as_preamble(self):
        latex = r"\documentclass{article}\begin{document}Hello\end{document}"
        preamble, sections = extract_sections(latex)
        assert sections == []
        assert preamble == latex

    def test_star_section_is_detected(self):
        latex = (
            "\\documentclass{article}\n\\begin{document}\n"
            "\\section*{Objective}\nSome text\n\\end{document}"
        )
        _, sections = extract_sections(latex)
        assert len(sections) == 1
        assert sections[0].name == "Objective"

    def test_commented_section_not_detected(self):
        latex = (
            "\\documentclass{article}\n\\begin{document}\n"
            "% \\section{Hidden}\n"
            "\\section{Visible}\nContent\n\\end{document}"
        )
        _, sections = extract_sections(latex)
        names = [s.name for s in sections]
        assert "Hidden" not in names
        assert "Visible" in names


# ---------------------------------------------------------------------------
# 53A — reorder_sections
# ---------------------------------------------------------------------------


class TestReorderSections:
    def test_basic_reorder_changes_order(self):
        new_order = ["Education", "Skills", "Experience", "Projects"]
        result = reorder_sections(_FOUR_SECTION_LATEX, new_order)
        _, sections = extract_sections(result)
        names = [s.name for s in sections]
        assert names == new_order

    def test_all_content_preserved(self):
        new_order = ["Skills", "Projects", "Education", "Experience"]
        result = reorder_sections(_FOUR_SECTION_LATEX, new_order)
        # Every section header should still appear
        for name in ["Experience", "Education", "Skills", "Projects"]:
            assert f"\\section{{{name}}}" in result
        # Key content fragments must survive
        assert "Acme Corp" in result
        assert "MIT" in result
        assert "FastAPI" in result

    def test_end_document_present(self):
        result = reorder_sections(_FOUR_SECTION_LATEX, ["Skills", "Experience", "Education", "Projects"])
        assert "\\end{document}" in result

    def test_missing_sections_appended_in_original_order(self):
        # Only specify 2 out of 4
        new_order = ["Skills", "Experience"]
        result = reorder_sections(_FOUR_SECTION_LATEX, new_order)
        _, sections = extract_sections(result)
        names = [s.name for s in sections]
        # Skills and Experience first, then Education + Projects in original order
        assert names[:2] == ["Skills", "Experience"]
        assert set(names[2:]) == {"Education", "Projects"}

    def test_no_sections_returns_original(self):
        latex = r"\documentclass{article}\begin{document}Hello\end{document}"
        result = reorder_sections(latex, ["Experience"])
        assert result == latex

    def test_case_insensitive_name_matching(self):
        new_order = ["experience", "SKILLS", "Education", "projects"]
        result = reorder_sections(_FOUR_SECTION_LATEX, new_order)
        _, sections = extract_sections(result)
        # All 4 sections should be present regardless of case mismatch
        assert len(sections) == 4

    def test_idempotent_with_same_order(self):
        original_order = ["Experience", "Education", "Skills", "Projects"]
        result = reorder_sections(_FOUR_SECTION_LATEX, original_order)
        _, sections = extract_sections(result)
        assert [s.name for s in sections] == original_order


# ---------------------------------------------------------------------------
# 53B — POST /ai/reorder-sections endpoint
# ---------------------------------------------------------------------------


def _make_llm_response(suggested: list[str], rationale: str = "Test rationale.") -> MagicMock:
    """Build a mock OpenAI chat completion response."""
    choice = MagicMock()
    choice.message.content = json.dumps({"suggested_order": suggested, "rationale": rationale})
    mock_resp = MagicMock()
    mock_resp.choices = [choice]
    return mock_resp


@pytest.mark.asyncio
class TestReorderSectionsEndpoint:
    async def test_returns_reordered_latex_in_suggested_order(
        self, client: AsyncClient
    ):
        """Endpoint returns reordered_latex whose sections match suggested_order."""
        suggested = ["Education", "Skills", "Experience", "Projects"]
        mock_resp = _make_llm_response(suggested, "Education first for entry-level.")

        with (
            patch("openai.AsyncOpenAI") as mock_openai,
            patch("app.api.ai_routes.settings") as mock_settings,
        ):
            mock_settings.OPENAI_API_KEY = "sk-test-key"
            mock_settings.OPENAI_MODEL = "gpt-4o-mini"
            instance = MagicMock()
            instance.chat.completions.create = AsyncMock(return_value=mock_resp)
            mock_openai.return_value = instance

            resp = await client.post(
                "/ai/reorder-sections",
                json={"resume_latex": _FOUR_SECTION_LATEX},
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["current_order"] == ["Experience", "Education", "Skills", "Projects"]
        assert data["suggested_order"] == suggested
        assert "Education" in data["rationale"]
        # Verify the reordered LaTeX actually has sections in suggested order
        _, sections = extract_sections(data["reordered_latex"])
        assert [s.name for s in sections] == suggested

    async def test_with_job_description_and_career_stage(
        self, client: AsyncClient
    ):
        """Endpoint forwards career_stage and job_description to LLM."""
        suggested = ["Experience", "Skills", "Education", "Projects"]
        mock_resp = _make_llm_response(suggested, "Senior engineer: Experience first.")

        captured_prompt: list[str] = []

        async def _capture(*args, **kwargs):
            msgs = kwargs.get("messages", [])
            for m in msgs:
                if m.get("role") == "user":
                    captured_prompt.append(m["content"])
            return mock_resp

        with (
            patch("openai.AsyncOpenAI") as mock_openai,
            patch("app.api.ai_routes.settings") as mock_settings,
        ):
            mock_settings.OPENAI_API_KEY = "sk-test-key"
            mock_settings.OPENAI_MODEL = "gpt-4o-mini"
            instance = MagicMock()
            instance.chat.completions.create = _capture
            mock_openai.return_value = instance

            resp = await client.post(
                "/ai/reorder-sections",
                json={
                    "resume_latex": _FOUR_SECTION_LATEX,
                    "job_description": "Senior backend engineer role.",
                    "career_stage": "senior",
                },
            )

        assert resp.status_code == 200
        assert len(captured_prompt) == 1
        assert "senior" in captured_prompt[0].lower()
        assert "Senior backend engineer" in captured_prompt[0]

    async def test_no_sections_returns_empty_lists(self, client: AsyncClient):
        """Latex with no \\section{} should return empty lists without LLM call."""
        latex = r"\documentclass{article}\begin{document}Hello world\end{document}"
        with patch("openai.AsyncOpenAI") as mock_openai:
            resp = await client.post(
                "/ai/reorder-sections",
                json={"resume_latex": latex},
            )
            mock_openai.assert_not_called()

        assert resp.status_code == 200
        data = resp.json()
        assert data["current_order"] == []
        assert data["suggested_order"] == []
        assert data["reordered_latex"] == latex

    async def test_llm_omits_section_it_still_appears_in_output(
        self, client: AsyncClient
    ):
        """If LLM omits a section, endpoint appends it at end."""
        # LLM only mentions 3 of the 4 sections
        suggested_partial = ["Skills", "Education", "Experience"]  # Projects missing
        mock_resp = _make_llm_response(suggested_partial)

        with (
            patch("openai.AsyncOpenAI") as mock_openai,
            patch("app.api.ai_routes.settings") as mock_settings,
        ):
            mock_settings.OPENAI_API_KEY = "sk-test-key"
            mock_settings.OPENAI_MODEL = "gpt-4o-mini"
            instance = MagicMock()
            instance.chat.completions.create = AsyncMock(return_value=mock_resp)
            mock_openai.return_value = instance

            resp = await client.post(
                "/ai/reorder-sections",
                json={"resume_latex": _FOUR_SECTION_LATEX},
            )

        assert resp.status_code == 200
        data = resp.json()
        # All 4 sections must be in the output — endpoint normalises missing ones
        assert len(data["suggested_order"]) == 4
        _, out_sections = extract_sections(data["reordered_latex"])
        assert len(out_sections) == 4
        # Projects was omitted by LLM but must appear at the end
        assert data["suggested_order"][-1] == "Projects"

    async def test_cached_flag_false_on_first_call(self, client: AsyncClient):
        """First call (cache miss) should return cached=False."""
        mock_resp = _make_llm_response(["Experience", "Education", "Skills", "Projects"])

        with (
            patch("openai.AsyncOpenAI") as mock_openai,
            patch("app.api.ai_routes.settings") as mock_settings,
            patch("app.core.redis.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.core.redis.cache_manager.set", new_callable=AsyncMock),
        ):
            mock_settings.OPENAI_API_KEY = "sk-test-key"
            mock_settings.OPENAI_MODEL = "gpt-4o-mini"
            instance = MagicMock()
            instance.chat.completions.create = AsyncMock(return_value=mock_resp)
            mock_openai.return_value = instance

            resp = await client.post(
                "/ai/reorder-sections",
                json={"resume_latex": _FOUR_SECTION_LATEX},
            )

        assert resp.status_code == 200
        assert resp.json()["cached"] is False
