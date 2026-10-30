"""Tests for Feature 47: Anonymous Resume Mode."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

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
        self, client, auth_headers: dict, db_session
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

        dispatches = []

        async def verify_lineage_before_dispatch(_submission, *args, **kwargs):
            from app.database.models import JobFinalization, Resume

            finalization = await db_session.scalar(select(JobFinalization).where(
                JobFinalization.job_id == kwargs["job_id"]
            ))
            stored_resume = await db_session.get(Resume, resume_id)
            assert finalization is not None
            assert finalization.job_type == "anonymous_share"
            assert finalization.user_id == stored_resume.user_id
            assert finalization.resume_id == resume_id
            assert finalization.compilation_id is None
            assert stored_resume.resume_settings["share_anonymous_job_id"] == kwargs["job_id"]
            from app.core.redis import get_redis_client
            from app.workers.job_lifecycle import lifecycle_key

            redis = await get_redis_client()
            assert await redis.exists(lifecycle_key(kwargs["job_id"]))
            dispatches.append(kwargs)
            return "queued"

        with (
            patch("app.workers.latex_worker.submit_latex_compilation") as submit_compile,
            patch("app.api.resume_routes.submit_async", side_effect=verify_lineage_before_dispatch),
        ):
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
        assert submit_compile.call_count == 0  # submit_async inspects the durable intent instead
        assert len(dispatches) == 2
        for call in dispatches:
            assert call["render_request"] == {
                "document_id": resume_id,
                "content_revision": first_stored.json()["content_revision"],
                "branch": "draft",
            }
            assert call["metadata"]["skip_auto_save"] is True

    @pytest.mark.parametrize("failure_stage", ["before_dispatch", "uncertain_dispatch"])
    async def test_anonymous_dispatch_failure_preserves_only_possible_work(
        self, client, auth_headers, db_session, failure_stage
    ):
        from app.core.redis import get_redis_client
        from app.database.models import JobFinalization
        from app.workers.job_lifecycle import lifecycle_key

        created = await client.post("/resumes/", headers=auth_headers, json={
            "title": "Anonymous dispatch recovery",
            "latex_content": r"\documentclass{article}\begin{document}Hi\end{document}",
        })
        resume_id = created.json()["id"]
        submission = AsyncMock(side_effect=RuntimeError("synthetic uncertain broker result"))
        with patch("app.api.resume_routes.submit_async", new=submission):
            if failure_stage == "before_dispatch":
                with patch("app.api.job_routes._write_initial_redis_state", new=AsyncMock(
                    side_effect=RuntimeError("synthetic queue unavailable"),
                )):
                    response = await client.post(f"/resumes/{resume_id}/share",
                                                 headers=auth_headers, json={"anonymous": True})
            else:
                response = await client.post(f"/resumes/{resume_id}/share",
                                             headers=auth_headers, json={"anonymous": True})
        assert response.status_code == 200, response.text
        stored = (await client.get(f"/resumes/{resume_id}", headers=auth_headers)).json()
        record = (await db_session.execute(select(JobFinalization).where(
            JobFinalization.resume_id == resume_id,
        ))).scalar_one()
        redis = await get_redis_client()
        assert stored["metadata"]["share_anonymous_pending"] is True
        if failure_stage == "before_dispatch":
            submission.assert_not_awaited()
            assert record.state == "failed"
            assert "share_anonymous_job_id" not in stored["metadata"]
            assert not await redis.exists(lifecycle_key(record.job_id))
        else:
            submission.assert_awaited_once()
            assert record.state == "pending"
            assert stored["metadata"]["share_anonymous_job_id"] == record.job_id
            assert await redis.exists(lifecycle_key(record.job_id))

    async def test_regeneration_rechecks_compile_capability_for_existing_share(
        self, client, auth_headers
    ):
        created = await client.post("/resumes/", headers=auth_headers, json={
            "title": "Anonymous compile control",
            "latex_content": r"\documentclass{article}\begin{document}Hi\end{document}",
        })
        resume_id = created.json()["id"]
        with patch("app.workers.latex_worker.submit_latex_compilation") as submit:
            first = await client.post(f"/resumes/{resume_id}/share", headers=auth_headers,
                                      json={"anonymous": True})
            assert first.status_code == 200
            original = (await client.get(f"/resumes/{resume_id}", headers=auth_headers)).json()
            with patch("app.api.resume_routes.enforce_capabilities", new=AsyncMock(
                side_effect=HTTPException(403, "Compilation is disabled"),
            )) as gate:
                denied = await client.post(f"/resumes/{resume_id}/share", headers=auth_headers,
                                           json={"anonymous": True, "regenerate_anonymous": True})
            assert denied.status_code == 403
            gate.assert_awaited_once()
            assert gate.await_args.args == (("c05",), submit.call_args.kwargs["user_id"])
            assert submit.call_count == 1
        stored = (await client.get(f"/resumes/{resume_id}", headers=auth_headers)).json()
        assert stored["metadata"]["share_anonymous_job_id"] == original["metadata"]["share_anonymous_job_id"]

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
