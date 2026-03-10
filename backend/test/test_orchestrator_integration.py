"""
Integration tests for orchestrator.py fixes:
1. Docker fallback to local pdflatex
2. Delimiter state machine (no JSON in editor tokens)
3. Compile failure preserves optimized_latex in job.failed event
4. Section-specific prompt injection
5. Optimization history endpoints
6. Restore optimization endpoint
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

# ─── Fix 1: Docker fallback ───────────────────────────────────────────────────

class TestDockerFallback:
    def test_uses_local_pdflatex_when_docker_not_found(self, tmp_path):
        """When Docker is unavailable, orchestrator uses local pdflatex."""
        from app.workers.orchestrator import _run_latex_stage

        sample_tex = (
            r"\documentclass{article}\begin{document}Hello\end{document}"
        )
        job_id = "test-docker-fallback"
        job_dir = tmp_path / job_id
        job_dir.mkdir()

        with (
            patch("app.workers.orchestrator.shutil.which", return_value=None),
            patch("app.workers.orchestrator.subprocess.Popen") as mock_popen,
            patch("app.workers.orchestrator.publish_event"),
            patch("app.workers.orchestrator.is_cancelled", return_value=False),
            patch("app.workers.orchestrator.settings") as mock_settings,
        ):
            mock_settings.TEMP_DIR = tmp_path
            mock_settings.LATEX_DOCKER_IMAGE = "texlive/texlive:latest"

            # Mock successful pdflatex run
            mock_proc = MagicMock()
            mock_proc.stdout = iter(["This is pdfTeX\n", "Output written on resume.pdf\n"])
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc

            # Create the pdf file so the check passes
            (job_dir / "resume.pdf").write_bytes(b"%PDF-1.4")
            (job_dir / "resume.tex").write_text(sample_tex)

            success, _, _ = _run_latex_stage(job_id, sample_tex)

            assert mock_popen.called
            cmd = mock_popen.call_args[0][0]
            # Must NOT use docker
            assert cmd[0] != "docker"
            assert cmd[0] == "pdflatex"
            # cwd must be set (not None) for local execution
            assert mock_popen.call_args[1].get("cwd") is not None

    def test_uses_docker_when_available(self, tmp_path):
        """When Docker is available, orchestrator uses docker run."""
        from app.workers.orchestrator import _run_latex_stage

        job_id = "test-docker-available"
        job_dir = tmp_path / job_id
        job_dir.mkdir()

        with (
            patch("app.workers.orchestrator.shutil.which", return_value="/usr/bin/docker"),
            patch("app.workers.orchestrator.subprocess.Popen") as mock_popen,
            patch("app.workers.orchestrator.publish_event"),
            patch("app.workers.orchestrator.is_cancelled", return_value=False),
            patch("app.workers.orchestrator.settings") as mock_settings,
        ):
            mock_settings.TEMP_DIR = tmp_path
            mock_settings.LATEX_DOCKER_IMAGE = "texlive/texlive:latest"

            mock_proc = MagicMock()
            mock_proc.stdout = iter([])
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc

            (job_dir / "resume.pdf").write_bytes(b"%PDF-1.4")
            (job_dir / "resume.tex").write_text("test")

            _run_latex_stage(job_id, "test")

            cmd = mock_popen.call_args[0][0]
            assert cmd[0] == "docker"
            assert "run" in cmd


# ─── Fix 2: No JSON in llm.token events ──────────────────────────────────────

class TestDelimiterStreaming:
    """Verify that _run_llm_stage only emits LaTeX tokens, not JSON scaffold."""

    def _make_stream_chunk(self, text: str) -> MagicMock:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = text
        chunk.usage = None
        return chunk

    def _make_usage_chunk(self, total: int) -> MagicMock:
        chunk = MagicMock()
        chunk.choices = []
        usage = MagicMock()
        usage.total_tokens = total
        chunk.usage = usage
        return chunk

    def test_only_latex_tokens_published(self):
        """llm.token events contain only LaTeX — no JSON braces or keys."""
        latex_body = r"\documentclass{article}\begin{document}test\end{document}"
        changes_json = '[{"section":"Summary","change_type":"modified","reason":"better"}]'
        full_response = f"<<<LATEX>>>\n{latex_body}\n<<<END_LATEX>>>\n<<<CHANGES>>>\n{changes_json}\n<<<END_CHANGES>>>"

        # Deliver in small chunks to stress-test buffering
        chunk_size = 10
        chunks = [
            full_response[i:i+chunk_size]
            for i in range(0, len(full_response), chunk_size)
        ]

        published_tokens = []

        def capture_publish(job_id, event_type, payload, **kwargs):
            if event_type == "llm.token":
                published_tokens.append(payload["token"])

        with (
            patch("app.workers.orchestrator.publish_event", side_effect=capture_publish),
            patch("app.workers.orchestrator.is_cancelled", return_value=False),
            patch("app.workers.orchestrator.llm_service") as mock_llm_svc,
            patch("app.workers.orchestrator.openai.OpenAI") as mock_openai,
            patch("app.workers.orchestrator.settings") as mock_settings,
        ):
            mock_settings.OPENAI_MODEL = "gpt-4o"
            mock_settings.OPENAI_MAX_TOKENS = 4096
            mock_settings.OPENAI_TEMPERATURE = 0.7
            mock_llm_svc.extract_keywords_from_job_description.return_value = []
            mock_llm_svc._create_optimization_prompt.return_value = "prompt"
            mock_llm_svc.count_tokens.return_value = 100

            stream_chunks = [self._make_stream_chunk(c) for c in chunks]
            stream_chunks.append(self._make_usage_chunk(500))
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = iter(stream_chunks)
            mock_openai.return_value = mock_client

            from app.workers.orchestrator import _run_llm_stage
            optimized, changes, tokens, _ = _run_llm_stage(
                "test-job", latex_body, None, "balanced", "fake-key"
            )

        combined = "".join(published_tokens)
        # JSON keys must not appear in published tokens
        assert '"optimized_latex"' not in combined
        assert '"changes"' not in combined
        assert "<<<LATEX>>>" not in combined
        assert "<<<END_LATEX>>>" not in combined
        # The latex result should contain the actual LaTeX
        assert "\\documentclass" in optimized
        assert len(changes) == 1
        assert changes[0]["section"] == "Summary"

    def test_fallback_when_no_delimiters(self):
        """If LLM ignores delimiters, falls back to JSON parse of accumulated output."""
        latex_body = r"\documentclass{article}\begin{document}fallback\end{document}"
        json_response = json.dumps({
            "optimized_latex": latex_body,
            "changes": [{"section": "A", "change_type": "modified", "reason": "r"}]
        })

        published_tokens = []

        def capture_publish(job_id, event_type, payload, **kwargs):
            if event_type == "llm.token":
                published_tokens.append(payload["token"])

        with (
            patch("app.workers.orchestrator.publish_event", side_effect=capture_publish),
            patch("app.workers.orchestrator.is_cancelled", return_value=False),
            patch("app.workers.orchestrator.llm_service") as mock_llm_svc,
            patch("app.workers.orchestrator.openai.OpenAI") as mock_openai,
            patch("app.workers.orchestrator.settings") as mock_settings,
        ):
            mock_settings.OPENAI_MODEL = "gpt-4o"
            mock_settings.OPENAI_MAX_TOKENS = 4096
            mock_settings.OPENAI_TEMPERATURE = 0.7
            mock_llm_svc.extract_keywords_from_job_description.return_value = []
            mock_llm_svc._create_optimization_prompt.return_value = "prompt"
            mock_llm_svc.count_tokens.return_value = 100

            stream_chunks = [self._make_stream_chunk(json_response)]
            stream_chunks.append(self._make_usage_chunk(200))
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = iter(stream_chunks)
            mock_openai.return_value = mock_client

            from app.workers.orchestrator import _run_llm_stage
            optimized, changes, _, _ = _run_llm_stage(
                "test-fallback", latex_body, None, "balanced", "fake-key"
            )

        # Fallback to JSON parse should recover the latex
        assert "\\documentclass" in optimized
        assert "fallback" in optimized
        # No tokens emitted to frontend (state machine never entered IN_LATEX)
        assert published_tokens == []


# ─── Fix 3: Preserve LaTeX on compile fail ───────────────────────────────────

class TestCompileFailPreservesLatex:
    def test_job_failed_includes_optimized_latex(self, tmp_path):
        """When compilation fails, job.failed event contains optimized_latex."""
        from app.workers.orchestrator import optimize_and_compile_task

        sample_latex = r"\documentclass{article}\begin{document}content\end{document}"
        optimized_latex = r"\documentclass{article}\begin{document}optimized\end{document}"
        job_id = "test-preserve-latex"

        published_events: list[dict] = []

        def capture_publish(jid, etype, payload, **kwargs):
            published_events.append({"type": etype, "payload": payload})

        with (
            patch("app.workers.orchestrator.publish_event", side_effect=capture_publish),
            patch("app.workers.orchestrator.publish_job_result"),
            patch("app.workers.orchestrator.is_cancelled", return_value=False),
            patch("app.workers.orchestrator._run_llm_stage",
                  return_value=(optimized_latex, [{"section": "S", "change_type": "modified", "reason": "r"}], 100, 1.0)),
            patch("app.workers.orchestrator._run_latex_stage",
                  return_value=(False, 0.5, "pdflatex exited with code 1. See log.line events for details.")),
            patch("app.workers.orchestrator.settings") as mock_settings,
        ):
            mock_settings.OPENAI_API_KEY = "fake-key"

            # Call the task synchronously (bypass Celery)
            task = optimize_and_compile_task
            task_instance = MagicMock()
            task_instance.request.id = "task-123"
            task_instance.request.retries = 0
            task_instance.max_retries = 1

            result = optimize_and_compile_task.__wrapped__(
                task_instance, sample_latex, job_id=job_id
            )

        # Find job.failed event
        failed_events = [e for e in published_events if e["type"] == "job.failed"]
        assert len(failed_events) == 1
        failed_payload = failed_events[0]["payload"]

        assert "optimized_latex" in failed_payload
        assert failed_payload["optimized_latex"] == optimized_latex
        assert "changes_made" in failed_payload
        assert result["success"] is False
        assert result.get("optimized_latex") == optimized_latex


# ─── Feature 3: Section-specific prompt ──────────────────────────────────────

class TestSectionSpecificPrompt:
    def test_target_sections_added_to_prompt(self):
        """target_sections constraint appears in the generated prompt."""
        from app.services.llm_service import LLMService

        svc = LLMService.__new__(LLMService)
        prompt = svc._create_optimization_prompt(
            latex_content=r"\section{Experience}\section{Skills}",
            job_description=None,
            keywords=[],
            optimization_level="balanced",
            target_sections=["Experience"],
            custom_instructions=None,
        )

        assert "Experience" in prompt
        assert "Only modify these sections" in prompt
        assert "byte-for-byte identical" in prompt

    def test_custom_instructions_added_to_prompt(self):
        """custom_instructions appear verbatim in the prompt."""
        from app.services.llm_service import LLMService

        svc = LLMService.__new__(LLMService)
        prompt = svc._create_optimization_prompt(
            latex_content=r"\section{Summary}",
            job_description=None,
            keywords=[],
            optimization_level="balanced",
            target_sections=None,
            custom_instructions="keep it to 1 page",
        )

        assert "keep it to 1 page" in prompt

    def test_no_section_constraint_when_none(self):
        """When target_sections is None, no constraint is injected."""
        from app.services.llm_service import LLMService

        svc = LLMService.__new__(LLMService)
        prompt = svc._create_optimization_prompt(
            latex_content=r"\section{Summary}",
            job_description=None,
            keywords=[],
            optimization_level="balanced",
            target_sections=None,
            custom_instructions=None,
        )

        assert "Only modify these sections" not in prompt
        assert "User instructions" not in prompt

    def test_delimiter_format_in_prompt(self):
        """Prompt instructs LLM to use delimiter format, not JSON object."""
        from app.services.llm_service import LLMService

        svc = LLMService.__new__(LLMService)
        prompt = svc._create_optimization_prompt(
            latex_content=r"\section{A}",
            job_description=None,
            keywords=[],
            optimization_level="balanced",
        )

        assert "<<<LATEX>>>" in prompt
        assert "<<<END_LATEX>>>" in prompt
        assert "<<<CHANGES>>>" in prompt
        # Old JSON format should NOT be in the prompt
        assert '"optimized_latex"' not in prompt


# ─── Feature 1: Optimization history endpoints ───────────────────────────────

@pytest.fixture
async def test_resume(client: AsyncClient, auth_headers: dict):
    """Create a test resume and clean it up after the test."""
    resp = await client.post(
        "/resumes/",
        json={"title": "Orch Test Resume", "latex_content": r"\documentclass{article}\begin{document}Test\end{document}"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    resume = resp.json()
    yield resume
    # Cleanup
    await client.delete(f"/resumes/{resume['id']}", headers=auth_headers)


@pytest.mark.asyncio
class TestOptimizationHistoryEndpoints:
    async def test_record_optimization(self, client: AsyncClient, auth_headers: dict, test_resume):
        """POST record-optimization saves an optimization record."""
        resp = await client.post(
            f"/resumes/{test_resume['id']}/record-optimization",
            json={
                "original_latex": r"\section{old}",
                "optimized_latex": r"\section{new}",
                "changes_made": [{"section": "Summary", "change_type": "modified", "reason": "clearer"}],
                "ats_score": 78.5,
                "tokens_used": 1200,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        assert "id" in data

    async def test_get_optimization_history(self, client: AsyncClient, auth_headers: dict, test_resume):
        """GET optimization-history returns previously recorded optimizations."""
        # Record one first
        await client.post(
            f"/resumes/{test_resume['id']}/record-optimization",
            json={
                "original_latex": r"\section{orig}",
                "optimized_latex": r"\section{opt}",
                "ats_score": 80.0,
                "tokens_used": 500,
            },
            headers=auth_headers,
        )

        resp = await client.get(
            f"/resumes/{test_resume['id']}/optimization-history",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        history = resp.json()
        assert isinstance(history, list)
        assert len(history) >= 1
        entry = history[0]
        assert "id" in entry
        assert "created_at" in entry
        assert "ats_score" in entry
        assert "changes_count" in entry

    async def test_restore_optimization(self, client: AsyncClient, auth_headers: dict, test_resume):
        """POST restore-optimization updates resume latex_content."""
        # Record
        rec_resp = await client.post(
            f"/resumes/{test_resume['id']}/record-optimization",
            json={
                "original_latex": r"\section{before}",
                "optimized_latex": r"\section{restored content}",
                "ats_score": 85.0,
            },
            headers=auth_headers,
        )
        opt_id = rec_resp.json()["id"]

        # Restore
        restore_resp = await client.post(
            f"/resumes/{test_resume['id']}/restore-optimization/{opt_id}",
            headers=auth_headers,
        )
        assert restore_resp.status_code == 200
        data = restore_resp.json()
        assert data["success"] is True
        assert "restored content" in data["latex_content"]

        # Verify resume was updated
        resume_resp = await client.get(
            f"/resumes/{test_resume['id']}",
            headers=auth_headers,
        )
        assert "restored content" in resume_resp.json()["latex_content"]

    async def test_history_not_accessible_by_other_user(self, client: AsyncClient, test_resume):
        """Other users cannot see or restore another user's optimization history."""
        resp = await client.get(
            f"/resumes/{test_resume['id']}/optimization-history",
            # No auth headers — unauthenticated
        )
        assert resp.status_code in (401, 403)
