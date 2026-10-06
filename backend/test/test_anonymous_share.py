"""Tests for Feature 47: Anonymous Resume Mode."""
from unittest.mock import patch

import pytest

from app.services.latex_pii_redactor import redact

# ── Unit tests for redact() ────────────────────────────────────────────────


def test_redact_email():
    latex = r"\textbf{john.doe@example.com}"
    result = redact(latex)
    assert "john.doe@example.com" not in result
    assert "redacted@example.invalid" in result


def test_redact_linkedin():
    latex = r"linkedin.com/in/johndoe"
    result = redact(latex)
    assert "johndoe" not in result
    assert "linkedin.com/in/redacted" in result


def test_redact_github():
    latex = r"github.com/johndoe"
    result = redact(latex)
    assert "johndoe" not in result
    assert "github.com/redacted" in result


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
    assert r"\textbf{Anonymous Candidate}" in result
    assert r"\end{document}" in result
    # Email redacted
    assert "john@example.com" not in result


def test_redact_name_address_and_all_phone_forms_in_header_only():
    latex = r"""\documentclass{article}
\begin{document}
\begin{center}
  {\LARGE \textbf{Jane Doe}}\\
  123 Main Street\\
  Toronto, Ontario M5V 2T6 \quad 415-555-0192
\end{center}
\section{Experience}
\textit{Example Corp, San Francisco, CA}
\end{document}"""
    result = redact(latex)
    assert "Jane Doe" not in result
    assert "123 Main Street" not in result
    assert "Toronto, Ontario" not in result
    assert "415-555-0192" not in result
    assert "Anonymous Candidate" in result
    assert "Location withheld" in result
    # Body locations are useful non-identity context and must be preserved.
    assert "Example Corp, San Francisco, CA" in result


def test_redact_structured_name_and_address_commands():
    result = redact(
        r"\name{Ada Lovelace}\address{12 St James Square}"
        r"\begin{document}Profile\end{document}"
    )
    assert "Ada Lovelace" not in result
    assert "12 St James Square" not in result
    assert r"\name{Anonymous Candidate}" in result
    assert r"\address{Location withheld}" in result


def test_redaction_output_is_ascii_and_watermark_is_idempotent():
    once = redact(
        r"\documentclass{article}\begin{document}"
        r"jane@example.com +91 98765 43210\end{document}"
    )
    twice = redact(once)
    once.encode("ascii")
    assert "█" not in once
    assert twice.count(r"\SetWatermarkText{ANONYMIZED}") == 1


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

        stored = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert stored.json()["share_anonymous"] is True

    async def test_owner_can_regenerate_failed_or_expired_redacted_pdf(
        self, client, auth_headers: dict
    ):
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={
                "title": "Retry Anonymous Resume",
                "latex_content": r"\documentclass{article}\begin{document}Hi\end{document}",
            },
        )
        resume_id = create_resp.json()["id"]

        with patch(
            "app.workers.latex_worker.submit_latex_compilation"
        ) as submit_compile:
            first = await client.post(
                f"/resumes/{resume_id}/share",
                headers=auth_headers,
                json={"anonymous": True},
            )
            first_stored = await client.get(
                f"/resumes/{resume_id}", headers=auth_headers
            )
            first_job = first_stored.json()["metadata"]["share_anonymous_job_id"]

            second = await client.post(
                f"/resumes/{resume_id}/share",
                headers=auth_headers,
                json={"anonymous": True, "regenerate_anonymous": True},
            )
            second_stored = await client.get(
                f"/resumes/{resume_id}", headers=auth_headers
            )

        second_job = second_stored.json()["metadata"]["share_anonymous_job_id"]
        assert first.status_code == second.status_code == 200
        assert first.json()["share_token"] == second.json()["share_token"]
        assert first_job != second_job
        assert submit_compile.call_count == 2

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

    async def test_editing_content_clears_stale_anonymous_share(
        self, client, auth_headers: dict
    ):
        """Editing latex_content must invalidate the cached anonymous redaction job
        so create_share_link regenerates a fresh redacted PDF."""
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={
                "title": "Stale Anon Resume",
                "latex_content": r"\documentclass{article}\begin{document}old@example.com\end{document}",
            },
        )
        resume_id = create_resp.json()["id"]

        share_resp = await client.post(
            f"/resumes/{resume_id}/share",
            headers=auth_headers,
            json={"anonymous": True},
        )
        assert share_resp.status_code == 200

        before = (
            await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        ).json().get("metadata") or {}
        # Anonymous share stores either a submitted job id or a pending marker.
        assert (
            "share_anonymous_job_id" in before or "share_anonymous_pending" in before
        )

        upd = await client.put(
            f"/resumes/{resume_id}",
            headers=auth_headers,
            json={
                "latex_content": r"\documentclass{article}\begin{document}new@example.com\end{document}",
                "expected_latex_content": r"\documentclass{article}\begin{document}old@example.com\end{document}",
            },
        )
        assert upd.status_code == 200

        after = (
            await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        ).json().get("metadata") or {}
        assert "share_anonymous_job_id" not in after
        assert "share_anonymous_pending" not in after
