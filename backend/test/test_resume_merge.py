"""Tests for POST /resumes/merge (Feature 69 — Multi-Resume Merge)."""

import pytest
from httpx import AsyncClient


LATEX_A = r"""
\documentclass[11pt]{article}
\usepackage{geometry}
\geometry{margin=1in}
\begin{document}
\begin{center}\textbf{Alice}\end{center}
\section*{Experience}
Software Engineer at Acme Corp, 2020--2023.
\section*{Skills}
Python, FastAPI, PostgreSQL.
\section*{Education}
B.Sc. Computer Science, MIT, 2020.
\end{document}
""".strip()

LATEX_B = r"""
\documentclass[11pt]{article}
\begin{document}
\begin{center}\textbf{Bob}\end{center}
\section*{Experience}
Data Scientist at DataCo, 2021--2023.
\section*{Skills}
Python, TensorFlow, PyTorch, Scikit-learn.
\section*{Projects}
Built an ML pipeline handling 10M events/day.
\end{document}
""".strip()

LATEX_C = r"""
\documentclass[11pt]{article}
\begin{document}
\begin{center}\textbf{Carol}\end{center}
\section*{Education}
M.Sc. Machine Learning, Stanford, 2022.
\section*{Skills}
Rust, Go, Kubernetes.
\end{document}
""".strip()


@pytest.mark.asyncio
class TestResumeMerge:

    async def _create_resume(
        self, client: AsyncClient, headers: dict, title: str, latex: str
    ) -> str:
        resp = await client.post(
            "/resumes/",
            headers=headers,
            json={"title": title, "latex_content": latex},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    # ── Happy path ────────────────────────────────────────────────────────────

    async def test_merge_two_resumes_no_choices(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Merge 2 resumes with empty section_choices — all sections from resume A."""
        id_a = await self._create_resume(client, auth_headers, "Resume A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "Resume B", LATEX_B)

        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={"resume_ids": [id_a, id_b], "section_choices": {}},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "merged_latex" in data
        assert "new_resume_id" in data
        assert data["new_resume_id"] != id_a
        assert data["new_resume_id"] != id_b

    async def test_merge_section_from_second_resume(
        self, client: AsyncClient, auth_headers: dict
    ):
        """section_choices picks Skills from resume B."""
        id_a = await self._create_resume(client, auth_headers, "Resume A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "Resume B", LATEX_B)

        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={
                "resume_ids": [id_a, id_b],
                "section_choices": {"Skills": id_b},
            },
        )
        assert resp.status_code == 201, resp.text
        merged = resp.json()["merged_latex"]
        # Should contain B's Skills content
        assert "TensorFlow" in merged or "PyTorch" in merged
        # Should NOT contain A's Skills
        assert "PostgreSQL" not in merged

    async def test_merge_section_from_third_resume(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Merge 3 resumes, picking Education from C."""
        id_a = await self._create_resume(client, auth_headers, "Resume A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "Resume B", LATEX_B)
        id_c = await self._create_resume(client, auth_headers, "Resume C", LATEX_C)

        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={
                "resume_ids": [id_a, id_b, id_c],
                "section_choices": {"Education": id_c, "Skills": id_b},
            },
        )
        assert resp.status_code == 201, resp.text
        merged = resp.json()["merged_latex"]
        assert "Stanford" in merged  # C's Education
        assert "TensorFlow" in merged or "PyTorch" in merged  # B's Skills

    async def test_merge_includes_extra_sections_from_other_resumes(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Sections in B but not A (e.g. Projects) appear in merged result from B."""
        id_a = await self._create_resume(client, auth_headers, "Resume A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "Resume B", LATEX_B)

        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={
                "resume_ids": [id_a, id_b],
                "section_choices": {"Projects": id_b},
            },
        )
        assert resp.status_code == 201, resp.text
        merged = resp.json()["merged_latex"]
        assert "Projects" in merged
        assert "ML pipeline" in merged

    async def test_merged_resume_saved_with_correct_metadata(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Merged resume is persisted and fetchable; title is 'Merged Resume'."""
        id_a = await self._create_resume(client, auth_headers, "Resume A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "Resume B", LATEX_B)

        merge_resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={"resume_ids": [id_a, id_b], "section_choices": {}},
        )
        assert merge_resp.status_code == 201
        new_id = merge_resp.json()["new_resume_id"]

        fetch_resp = await client.get(f"/resumes/{new_id}", headers=auth_headers)
        assert fetch_resp.status_code == 200
        fetched = fetch_resp.json()
        assert fetched["title"] == "Merged Resume"
        assert fetched["parent_resume_id"] == id_a

    async def test_merged_latex_has_valid_structure(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Merged LaTeX must contain \\begin{document} and \\end{document}."""
        id_a = await self._create_resume(client, auth_headers, "Resume A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "Resume B", LATEX_B)

        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={"resume_ids": [id_a, id_b], "section_choices": {}},
        )
        assert resp.status_code == 201
        merged = resp.json()["merged_latex"]
        assert "\\begin{document}" in merged
        assert "\\end{document}" in merged

    async def test_preamble_from_primary_resume(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Merged preamble comes from resume_ids[0]."""
        id_a = await self._create_resume(client, auth_headers, "Resume A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "Resume B", LATEX_B)

        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={"resume_ids": [id_a, id_b], "section_choices": {}},
        )
        assert resp.status_code == 201
        merged = resp.json()["merged_latex"]
        # A has \geometry{margin=1in}, B does not
        assert "\\geometry{margin=1in}" in merged

    # ── Authorization ─────────────────────────────────────────────────────────

    async def test_nonowned_resume_returns_403(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict
    ):
        """Including a resume owned by another user returns 403."""
        id_a = await self._create_resume(client, auth_headers, "Mine A", LATEX_A)
        id_other = await self._create_resume(
            client, auth_headers2, "Not Mine", LATEX_B
        )

        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={"resume_ids": [id_a, id_other], "section_choices": {}},
        )
        assert resp.status_code == 403

    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        """No auth header → 401."""
        resp = await client.post(
            "/resumes/merge",
            json={"resume_ids": ["a", "b"], "section_choices": {}},
        )
        assert resp.status_code == 401

    # ── Validation ────────────────────────────────────────────────────────────

    async def test_single_resume_id_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """resume_ids with only 1 entry → 422 (min_length=2)."""
        id_a = await self._create_resume(client, auth_headers, "Solo", LATEX_A)
        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={"resume_ids": [id_a], "section_choices": {}},
        )
        assert resp.status_code == 422

    async def test_five_resume_ids_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """resume_ids with 5 entries → 422 (max_length=4)."""
        ids = []
        for i in range(5):
            rid = await self._create_resume(
                client, auth_headers, f"R{i}", LATEX_A
            )
            ids.append(rid)
        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={"resume_ids": ids, "section_choices": {}},
        )
        assert resp.status_code == 422

    async def test_empty_resume_ids_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """resume_ids empty → 422."""
        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={"resume_ids": [], "section_choices": {}},
        )
        assert resp.status_code == 422

    # ── Edge cases ────────────────────────────────────────────────────────────

    async def test_merge_four_resumes(
        self, client: AsyncClient, auth_headers: dict
    ):
        """4 resumes (max allowed) can be merged together without error."""
        latex_d = r"""
\documentclass[11pt]{article}
\begin{document}
\begin{center}\textbf{Dave}\end{center}
\section*{Certifications}
AWS Solutions Architect, GCP Professional.
\end{document}
""".strip()
        id_a = await self._create_resume(client, auth_headers, "R A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "R B", LATEX_B)
        id_c = await self._create_resume(client, auth_headers, "R C", LATEX_C)
        id_d = await self._create_resume(client, auth_headers, "R D", latex_d)

        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={"resume_ids": [id_a, id_b, id_c, id_d], "section_choices": {}},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "merged_latex" in data
        assert "new_resume_id" in data

    async def test_duplicate_resume_ids_deduplicated(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Duplicate IDs in resume_ids are silently deduplicated."""
        id_a = await self._create_resume(client, auth_headers, "R A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "R B", LATEX_B)

        # id_a appears twice — should be treated as [id_a, id_b]
        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={"resume_ids": [id_a, id_b, id_a], "section_choices": {}},
        )
        assert resp.status_code == 201

    async def test_section_choice_invalid_source_falls_back_to_primary(
        self, client: AsyncClient, auth_headers: dict
    ):
        """section_choices pointing to an ID absent from resume_ids falls back to primary."""
        id_a = await self._create_resume(client, auth_headers, "R A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "R B", LATEX_B)

        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={
                "resume_ids": [id_a, id_b],
                "section_choices": {"Skills": "non-existent-resume-id"},
            },
        )
        assert resp.status_code == 201
        merged = resp.json()["merged_latex"]
        # Falls back to A's Skills
        assert "PostgreSQL" in merged

    async def test_resume_with_no_sections_merges_cleanly(
        self, client: AsyncClient, auth_headers: dict
    ):
        """A resume with no \\section commands merges without error."""
        latex_no_sec = r"""
\documentclass[11pt]{article}
\begin{document}
\begin{center}\textbf{No Sections}\end{center}
Plain text only, no section markers here.
\end{document}
""".strip()
        id_nosec = await self._create_resume(client, auth_headers, "No Sec", latex_no_sec)
        id_b = await self._create_resume(client, auth_headers, "R B", LATEX_B)

        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={"resume_ids": [id_nosec, id_b], "section_choices": {}},
        )
        assert resp.status_code == 201
        merged = resp.json()["merged_latex"]
        assert "\\begin{document}" in merged
        assert "\\end{document}" in merged

    async def test_all_sections_from_secondary_with_fallback(
        self, client: AsyncClient, auth_headers: dict
    ):
        """All sections routed to B; section not in B falls back to A."""
        id_a = await self._create_resume(client, auth_headers, "R A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "R B", LATEX_B)

        # Route all of A's sections to B
        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={
                "resume_ids": [id_a, id_b],
                "section_choices": {
                    "Experience": id_b,
                    "Skills": id_b,
                    "Education": id_b,  # B has no Education → falls back to A
                },
            },
        )
        assert resp.status_code == 201
        merged = resp.json()["merged_latex"]
        assert "DataCo" in merged           # B's Experience
        assert "TensorFlow" in merged       # B's Skills
        assert "MIT" in merged              # A's Education (B has none)

    async def test_merged_resume_appears_in_listing(
        self, client: AsyncClient, auth_headers: dict
    ):
        """After merge, the new resume is visible via GET /resumes/."""
        id_a = await self._create_resume(client, auth_headers, "R A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "R B", LATEX_B)

        merge_resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={"resume_ids": [id_a, id_b], "section_choices": {}},
        )
        assert merge_resp.status_code == 201
        new_id = merge_resp.json()["new_resume_id"]

        list_resp = await client.get("/resumes/", headers=auth_headers)
        assert list_resp.status_code == 200
        ids_in_list = [r["id"] for r in list_resp.json()["resumes"]]
        assert new_id in ids_in_list

    async def test_unknown_section_name_in_choices_ignored(
        self, client: AsyncClient, auth_headers: dict
    ):
        """section_choices referencing a section absent from all resumes is silently ignored."""
        id_a = await self._create_resume(client, auth_headers, "R A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "R B", LATEX_B)

        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={
                "resume_ids": [id_a, id_b],
                "section_choices": {"GhostSection": id_b},
            },
        )
        assert resp.status_code == 201
        assert "merged_latex" in resp.json()

    async def test_presection_content_from_primary(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Name block (content before first \\section) comes from primary (A), not secondary (B)."""
        id_a = await self._create_resume(client, auth_headers, "R A", LATEX_A)
        id_b = await self._create_resume(client, auth_headers, "R B", LATEX_B)

        resp = await client.post(
            "/resumes/merge",
            headers=auth_headers,
            json={"resume_ids": [id_a, id_b], "section_choices": {"Skills": id_b}},
        )
        assert resp.status_code == 201
        merged = resp.json()["merged_latex"]
        # A's presection has "Alice", B's has "Bob"
        assert "Alice" in merged
        assert "Bob" not in merged


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for private LaTeX helper functions
# ─────────────────────────────────────────────────────────────────────────────

from app.api.resume_routes import (
    _extract_latex_preamble,
    _extract_latex_sections,
    _extract_latex_presection,
)


class TestLatexHelpers:
    """Direct unit tests for _extract_latex_preamble, _extract_latex_sections,
    and _extract_latex_presection to ensure correctness independent of HTTP."""

    # ── _extract_latex_preamble ──────────────────────────────────────────────

    def test_preamble_stops_at_begin_document(self):
        latex = r"\documentclass{article}\usepackage{x}\begin{document}\section*{A}foo\end{document}"
        result = _extract_latex_preamble(latex)
        assert result.endswith("\\begin{document}")
        assert "\\section" not in result

    def test_preamble_includes_begin_document_token(self):
        latex = r"\documentclass{article}\begin{document}"
        assert _extract_latex_preamble(latex) == r"\documentclass{article}\begin{document}"

    def test_preamble_returns_full_string_when_no_begin_document(self):
        latex = r"\documentclass{article}"
        assert _extract_latex_preamble(latex) == latex

    def test_preamble_empty_string(self):
        assert _extract_latex_preamble("") == ""

    # ── _extract_latex_sections ──────────────────────────────────────────────

    def test_sections_basic_star_format(self):
        latex = "\\begin{document}\n\\section*{Experience}\nAcme.\n\\section*{Skills}\nPython.\n\\end{document}"
        result = _extract_latex_sections(latex)
        assert set(result.keys()) == {"Experience", "Skills"}
        assert "Acme." in result["Experience"]
        assert "Python." in result["Skills"]

    def test_sections_unnumbered_and_numbered(self):
        latex = "\\begin{document}\\section{Work}Acme.\\section*{Skills}Python.\\end{document}"
        result = _extract_latex_sections(latex)
        assert "Work" in result
        assert "Skills" in result

    def test_sections_empty_document_returns_empty_dict(self):
        latex = r"\begin{document}Hello\end{document}"
        assert _extract_latex_sections(latex) == {}

    def test_sections_no_begin_document_returns_empty_dict(self):
        assert _extract_latex_sections(r"\section*{Skills}Python") == {}

    def test_sections_block_contains_header_line(self):
        latex = "\\begin{document}\\section*{Experience}\nAccme Corp.\n\\end{document}"
        result = _extract_latex_sections(latex)
        assert "Experience" in result["Experience"]

    def test_sections_last_section_captured_to_end(self):
        latex = "\\begin{document}\\section*{A}First.\\section*{B}Last content here.\\end{document}"
        result = _extract_latex_sections(latex)
        assert "Last content here." in result["B"]

    def test_sections_order_matches_source(self):
        latex = (
            "\\begin{document}"
            "\\section*{Z}z content."
            "\\section*{A}a content."
            "\\end{document}"
        )
        result = _extract_latex_sections(latex)
        assert list(result.keys()) == ["Z", "A"]

    # ── _extract_latex_presection ────────────────────────────────────────────

    def test_presection_returns_content_before_first_section(self):
        latex = "\\begin{document}\n\\begin{center}Name\\end{center}\n\\section*{Experience}\nContent.\n\\end{document}"
        result = _extract_latex_presection(latex)
        assert "Name" in result
        assert "Experience" not in result

    def test_presection_no_sections_returns_entire_body(self):
        latex = r"\begin{document}Just plain text here.\end{document}"
        result = _extract_latex_presection(latex)
        assert "Just plain text here." in result

    def test_presection_no_begin_document_returns_empty_string(self):
        assert _extract_latex_presection(r"\section*{Skills}Python") == ""

    def test_presection_empty_body_before_first_section(self):
        latex = "\\begin{document}\\section*{A}content.\\end{document}"
        result = _extract_latex_presection(latex)
        # Body before first section is empty
        assert result == ""
