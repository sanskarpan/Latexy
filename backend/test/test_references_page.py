"""Tests for Feature 70: Reference Page Generator."""
import pytest
from httpx import AsyncClient

_TWO_REFS = [
    {
        "name": "Jane Smith",
        "title": "Engineering Manager",
        "company": "Acme Corp",
        "email": "jane@acme.com",
        "phone": None,
        "relationship": "Direct Manager",
    },
    {
        "name": "Bob Johnson",
        "title": "Senior Engineer",
        "company": "Tech Inc",
        "email": None,
        "phone": None,
        "relationship": "Colleague",
    },
]


@pytest.mark.asyncio
class TestReferencesPageEndpoint:

    async def _create_resume(
        self, client: AsyncClient, auth_headers: dict, latex: str = None
    ) -> str:
        latex = latex or r"\documentclass{article}\begin{document}Hello\end{document}"
        resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "Ref Test Resume", "latex_content": latex},
        )
        assert resp.status_code == 201
        return resp.json()["id"]

    async def test_generates_latex_with_two_references(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Generates valid LaTeX containing all reference names."""
        resume_id = await self._create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{resume_id}/generate-references",
            headers=auth_headers,
            json={"references": _TWO_REFS},
        )
        assert resp.status_code == 200
        latex = resp.json()["latex_content"]
        assert "Jane Smith" in latex
        assert "Bob Johnson" in latex
        assert r"\documentclass" in latex
        assert r"\begin{document}" in latex
        assert r"\end{document}" in latex

    async def test_six_references_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """More than 5 references → 422 validation error."""
        resume_id = await self._create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{resume_id}/generate-references",
            headers=auth_headers,
            json={
                "references": [
                    {
                        "name": f"Person {i}",
                        "title": "Title",
                        "company": "Co",
                        "relationship": "Colleague",
                    }
                    for i in range(6)
                ]
            },
        )
        assert resp.status_code == 422

    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        """Unauthenticated request → 401."""
        resp = await client.post(
            "/resumes/fake-id/generate-references",
            json={
                "references": [
                    {
                        "name": "Test Person",
                        "title": "Engineer",
                        "company": "Co",
                        "relationship": "Colleague",
                    }
                ]
            },
        )
        assert resp.status_code == 401

    async def test_preserves_documentclass_from_resume(
        self, client: AsyncClient, auth_headers: dict
    ):
        """The generated LaTeX uses the same \\documentclass as the source resume."""
        resume_id = await self._create_resume(
            client,
            auth_headers,
            r"\documentclass[12pt,letterpaper]{article}\begin{document}x\end{document}",
        )
        resp = await client.post(
            f"/resumes/{resume_id}/generate-references",
            headers=auth_headers,
            json={
                "references": [
                    {
                        "name": "Alice",
                        "title": "PM",
                        "company": "Corp",
                        "relationship": "Manager",
                    }
                ]
            },
        )
        assert resp.status_code == 200
        assert r"\documentclass[12pt,letterpaper]{article}" in resp.json()["latex_content"]

    async def test_nonexistent_resume_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Generating references for a non-existent resume → 404."""
        resp = await client.post(
            "/resumes/00000000-0000-0000-0000-000000000000/generate-references",
            headers=auth_headers,
            json={"references": [_TWO_REFS[0]]},
        )
        assert resp.status_code == 404

    async def test_email_appears_in_output(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Email is rendered in the generated LaTeX."""
        resume_id = await self._create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{resume_id}/generate-references",
            headers=auth_headers,
            json={"references": [_TWO_REFS[0]]},  # Jane has email
        )
        assert resp.status_code == 200
        assert "jane@acme.com" in resp.json()["latex_content"]
