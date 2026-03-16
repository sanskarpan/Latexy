"""
Tests for Feature 9: Multiple LaTeX Compilers.

Covers:
  - PATCH /resumes/{id}/settings  — valid + invalid compiler
  - compile_latex_task             — uses correct binary, validates unknown → fallback
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LATEX = r"\documentclass{article}\begin{document}Hello\end{document}"


async def _create_resume(client: AsyncClient, auth_headers: dict, title: str = "Compiler Test") -> dict:
    resp = await client.post(
        "/resumes/",
        headers=auth_headers,
        json={"title": title, "latex_content": _LATEX},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# PATCH /resumes/{id}/settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResumeSettingsEndpoint:
    async def test_valid_pdflatex(self, client: AsyncClient, auth_headers: dict):
        """PATCH with pdflatex → 200, metadata.compiler=pdflatex."""
        resume = await _create_resume(client, auth_headers)
        resp = await client.patch(
            f"/resumes/{resume['id']}/settings",
            headers=auth_headers,
            json={"compiler": "pdflatex"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["metadata"]["compiler"] == "pdflatex"

    async def test_valid_xelatex(self, client: AsyncClient, auth_headers: dict):
        """PATCH with xelatex → 200, metadata updated."""
        resume = await _create_resume(client, auth_headers)
        resp = await client.patch(
            f"/resumes/{resume['id']}/settings",
            headers=auth_headers,
            json={"compiler": "xelatex"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["metadata"]["compiler"] == "xelatex"

    async def test_valid_lualatex(self, client: AsyncClient, auth_headers: dict):
        """PATCH with lualatex → 200, metadata updated."""
        resume = await _create_resume(client, auth_headers)
        resp = await client.patch(
            f"/resumes/{resume['id']}/settings",
            headers=auth_headers,
            json={"compiler": "lualatex"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["metadata"]["compiler"] == "lualatex"

    async def test_invalid_compiler_rejected(self, client: AsyncClient, auth_headers: dict):
        """PATCH with unknown compiler → 400."""
        resume = await _create_resume(client, auth_headers)
        resp = await client.patch(
            f"/resumes/{resume['id']}/settings",
            headers=auth_headers,
            json={"compiler": "ghostscript"},
        )
        assert resp.status_code == 400
        assert "Invalid compiler" in resp.json()["detail"]

    async def test_settings_persisted_on_get(self, client: AsyncClient, auth_headers: dict):
        """After PATCH, GET returns the updated metadata."""
        resume = await _create_resume(client, auth_headers)
        await client.patch(
            f"/resumes/{resume['id']}/settings",
            headers=auth_headers,
            json={"compiler": "xelatex"},
        )
        get_resp = await client.get(f"/resumes/{resume['id']}", headers=auth_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["metadata"]["compiler"] == "xelatex"

    async def test_settings_switch_compiler(self, client: AsyncClient, auth_headers: dict):
        """Compiler can be switched from one value to another."""
        resume = await _create_resume(client, auth_headers)
        # Set to xelatex first
        await client.patch(
            f"/resumes/{resume['id']}/settings",
            headers=auth_headers,
            json={"compiler": "xelatex"},
        )
        # Switch to lualatex
        resp = await client.patch(
            f"/resumes/{resume['id']}/settings",
            headers=auth_headers,
            json={"compiler": "lualatex"},
        )
        assert resp.status_code == 200
        assert resp.json()["metadata"]["compiler"] == "lualatex"

    async def test_cannot_update_others_resume(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """PATCH on another user's resume → 404."""
        resume = await _create_resume(client, auth_headers)

        # Create a second user and get their auth headers
        user2_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'User2', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
            ),
            {"id": user2_id, "email": f"test_{user2_id[:8]}@example.com"},
        )
        await db_session.commit()

        from datetime import datetime, timedelta, timezone
        token2 = f"test_sess_{uuid.uuid4().hex}"
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        await db_session.execute(
            text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
            {"id": str(uuid.uuid4()), "uid": user2_id, "exp": expires_at, "tok": token2},
        )
        await db_session.commit()

        headers2 = {"Authorization": f"Bearer {token2}"}
        resp = await client.patch(
            f"/resumes/{resume['id']}/settings",
            headers=headers2,
            json={"compiler": "xelatex"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# compile_latex_task — unit tests (no real subprocess)
# ---------------------------------------------------------------------------


class TestCompileLatexTaskCompilerParam:
    """Unit tests for compile_latex_task compiler selection logic.

    We mock subprocess.Popen so no real LaTeX binary is needed.
    The worker writes the .tex file directly (no latex_service call), then
    runs [compiler, -interaction=nonstopmode, ...] via Popen.
    """

    def _make_mock_popen(self, returncode: int = 0):
        """Return a mock subprocess.Popen result."""
        mock_proc = MagicMock()
        mock_proc.returncode = returncode
        mock_proc.stdout = iter(["Output written on stdout"])
        mock_proc.wait = MagicMock(return_value=returncode)
        return mock_proc

    def _run_task_with_mock(self, compiler: str) -> list:
        """Run compile_latex_task with a mocked Popen; return the captured cmd list.

        Note: Celery bound tasks must be called without a mock `self` arg —
        passing one as a positional arg would map to `latex_content` since `self`
        is injected by the bind mechanism.  Call the task directly with kwargs only.
        """
        from app.workers.latex_worker import compile_latex_task

        captured_cmd: list = []

        def fake_popen(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return self._make_mock_popen()

        job_id = str(uuid.uuid4())

        with (
            patch("app.workers.latex_worker.subprocess.Popen", side_effect=fake_popen),
            patch("app.workers.latex_worker.publish_event"),
            patch("app.workers.latex_worker.publish_job_result"),
            patch("app.workers.latex_worker.is_cancelled", return_value=False),
            patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=True),
            # Prevent real filesystem operations
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            # pdf_file.exists() → False so task goes to failure path (fine, Popen already called)
            patch("pathlib.Path.exists", return_value=False),
        ):
            try:
                # Call the task directly — Celery's bind mechanism provides `self`
                compile_latex_task(
                    latex_content=_LATEX,
                    job_id=job_id,
                    compiler=compiler,
                )
            except Exception:
                pass  # Any error after Popen is fine — we only care about the cmd

        return captured_cmd

    def test_xelatex_used_in_cmd(self):
        """compile_latex_task with compiler='xelatex' invokes xelatex binary."""
        cmd = self._run_task_with_mock("xelatex")
        assert any("xelatex" in str(c) for c in cmd), f"Expected xelatex in cmd, got: {cmd}"

    def test_lualatex_used_in_cmd(self):
        """compile_latex_task with compiler='lualatex' invokes lualatex binary."""
        cmd = self._run_task_with_mock("lualatex")
        assert any("lualatex" in str(c) for c in cmd), f"Expected lualatex in cmd, got: {cmd}"

    def test_invalid_compiler_falls_back_to_pdflatex(self):
        """compile_latex_task with unknown compiler falls back to pdflatex."""
        cmd = self._run_task_with_mock("ghostscript")
        assert any("pdflatex" in str(c) for c in cmd), f"Expected pdflatex fallback in cmd, got: {cmd}"
        assert not any("ghostscript" in str(c) for c in cmd)
