"""Tests for Feature 47: Anonymous Resume Mode."""
import pytest

from app.services.latex_pii_redactor import redact

# ── Unit tests for redact() ────────────────────────────────────────────────


def test_redact_email():
    latex = r"\textbf{john.doe@example.com}"
    result = redact(latex)
    assert "john.doe@example.com" not in result
    assert "████@████" in result


def test_redact_linkedin():
    latex = r"linkedin.com/in/johndoe"
    result = redact(latex)
    assert "johndoe" not in result
    assert "linkedin.com/in/████" in result


def test_redact_github():
    latex = r"github.com/johndoe"
    result = redact(latex)
    assert "johndoe" not in result
    assert "github.com/████" in result


def test_redact_phone():
    latex = r"+1 555-123-4567"
    result = redact(latex)
    assert "555-123-4567" not in result


def test_redact_preserves_latex_structure():
    latex = r"""\documentclass{article}
\begin{document}
\textbf{John Doe}
john@example.com
\end{document}"""
    result = redact(latex)
    # LaTeX commands still intact
    assert r"\documentclass{article}" in result
    assert r"\textbf{John Doe}" in result
    assert r"\end{document}" in result
    # Email redacted
    assert "john@example.com" not in result


def test_redact_injects_watermark():
    latex = r"\documentclass{article}\begin{document}Hello\end{document}"
    result = redact(latex)
    assert r"\usepackage{draftwatermark}" in result
    assert "ANONYMIZED" in result


def test_redact_does_not_modify_input():
    latex = r"contact: user@example.com"
    original = latex  # same string ref
    redact(latex)
    assert latex == original


def test_redact_no_pii_unchanged_except_watermark():
    latex = r"\documentclass{article}\begin{document}No PII here.\end{document}"
    result = redact(latex)
    # Watermark injected
    assert r"\usepackage{draftwatermark}" in result
    # Non-PII content preserved
    assert "No PII here." in result


# ── Integration tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAnonymousShareEndpoint:

    async def test_share_link_anonymous_flag_stored(
        self, client, auth_headers: dict
    ):
        """Creating a share link with anonymous=True stores the flag."""
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={
                "title": "Anon Test Resume",
                "latex_content": r"\documentclass{article}\begin{document}Hello\end{document}",
            },
        )
        assert create_resp.status_code == 201
        resume_id = create_resp.json()["id"]

        resp = await client.post(
            f"/resumes/{resume_id}/share",
            headers=auth_headers,
            json={"anonymous": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["anonymous"] is True
        assert "share_token" in data

    async def test_share_link_non_anonymous_default(
        self, client, auth_headers: dict
    ):
        """Creating a share link without body defaults to anonymous=False."""
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={
                "title": "Normal Share Resume",
                "latex_content": r"\documentclass{article}\begin{document}Hi\end{document}",
            },
        )
        resume_id = create_resp.json()["id"]

        resp = await client.post(
            f"/resumes/{resume_id}/share",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["anonymous"] is False

    async def test_original_latex_unchanged_after_anonymous_share(
        self, client, auth_headers: dict
    ):
        """The resume's original latex_content is not modified by anonymous share."""
        original_latex = r"\documentclass{article}\begin{document}user@example.com\end{document}"
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "PII Resume", "latex_content": original_latex},
        )
        resume_id = create_resp.json()["id"]

        await client.post(
            f"/resumes/{resume_id}/share",
            headers=auth_headers,
            json={"anonymous": True},
        )

        get_resp = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert get_resp.status_code == 200
        # Original LaTeX must be preserved
        assert get_resp.json()["latex_content"] == original_latex
