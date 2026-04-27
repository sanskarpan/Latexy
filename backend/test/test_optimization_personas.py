"""
Tests for Feature 56 — AI Custom Optimization Persona.

Covers:
  56A — PERSONAS dict has all five keys with required fields
  56B — POST /jobs/submit with combined job_type + valid persona accepted (HTTP 200)
  56B — POST /jobs/submit with combined job_type + invalid persona returns 422
  56B — persona prompt_addon text is injected into the LLM system prompt
  56C — GET /ai/personas returns all 5 personas
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from app.services.optimization_personas import PERSONAS, VALID_PERSONA_KEYS

# ---------------------------------------------------------------------------
# A – Unit tests for the personas service
# ---------------------------------------------------------------------------


class TestPersonasService:
    def test_five_personas_present(self):
        assert len(PERSONAS) == 5

    def test_all_required_keys_present(self):
        for key, cfg in PERSONAS.items():
            assert "label" in cfg, f"{key} missing 'label'"
            assert "description" in cfg, f"{key} missing 'description'"
            assert "prompt_addon" in cfg, f"{key} missing 'prompt_addon'"

    def test_valid_persona_keys_frozenset(self):
        assert VALID_PERSONA_KEYS == frozenset(
            {"startup", "enterprise", "academic", "career_change", "executive"}
        )

    def test_prompt_addons_are_non_empty(self):
        for key, cfg in PERSONAS.items():
            assert cfg["prompt_addon"].strip(), f"{key} has empty prompt_addon"

    def test_startup_persona_content(self):
        addon = PERSONAS["startup"]["prompt_addon"]
        assert "startup" in addon.lower() or "scale-up" in addon.lower()

    def test_executive_persona_content(self):
        addon = PERSONAS["executive"]["prompt_addon"]
        assert "executive" in addon.lower() or "c-suite" in addon.lower() or "p&l" in addon.lower()


# ---------------------------------------------------------------------------
# B – POST /jobs/submit endpoint
# ---------------------------------------------------------------------------


def _make_mock_celery():
    """Return a mock that prevents Celery from actually enqueueing tasks."""
    mock_task = MagicMock()
    mock_task.apply_async = MagicMock(return_value=MagicMock(id="mock-task-id"))
    return mock_task


@pytest.mark.asyncio
class TestPersonaJobSubmission:
    async def test_valid_persona_accepted(self, client: AsyncClient):
        """A combined job with a valid persona returns 200."""
        with patch("app.workers.orchestrator.submit_optimize_and_compile", return_value=None):
            resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "combined",
                    "latex_content": r"\documentclass{article}\begin{document}Hello\end{document}",
                    "persona": "startup",
                },
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["job_id"]

    async def test_invalid_persona_returns_422(self, client: AsyncClient):
        """An unknown persona value should return 422."""
        with patch("app.workers.orchestrator.submit_optimize_and_compile", return_value=None):
            resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "combined",
                    "latex_content": r"\documentclass{article}\begin{document}Hello\end{document}",
                    "persona": "not_a_real_persona",
                },
            )
        assert resp.status_code == 422, resp.text

    async def test_no_persona_still_works(self, client: AsyncClient):
        """Omitting persona entirely should still work (backward compat)."""
        with patch("app.workers.orchestrator.submit_optimize_and_compile", return_value=None):
            resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "combined",
                    "latex_content": r"\documentclass{article}\begin{document}Hello\end{document}",
                },
            )

        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# C – GET /ai/personas endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPersonasEndpoint:
    async def test_returns_all_five_personas(self, client: AsyncClient):
        resp = await client.get("/ai/personas")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 5

    async def test_persona_items_have_required_fields(self, client: AsyncClient):
        resp = await client.get("/ai/personas")
        assert resp.status_code == 200
        for item in resp.json():
            assert "key" in item
            assert "label" in item
            assert "description" in item

    async def test_persona_keys_match_service(self, client: AsyncClient):
        resp = await client.get("/ai/personas")
        assert resp.status_code == 200
        returned_keys = {item["key"] for item in resp.json()}
        assert returned_keys == VALID_PERSONA_KEYS


# ---------------------------------------------------------------------------
# D – LLM prompt injection unit test
# ---------------------------------------------------------------------------


class TestPersonaPromptInjection:
    """Test that the persona addon is injected into _run_llm_stage system prompt."""

    def test_persona_addon_in_system_prompt(self):
        """The startup persona's prompt_addon should appear in the system content."""
        from unittest.mock import MagicMock, patch

        captured_messages: list = []

        def fake_create(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            # Return a minimal stream-like iterable
            return iter([])

        with (
            patch("app.workers.orchestrator.openai.OpenAI") as mock_client_cls,
            patch(
                "app.workers.orchestrator.llm_service._create_optimization_prompt",
                return_value="PROMPT",
            ),
            patch(
                "app.workers.orchestrator.llm_service.extract_keywords_from_job_description",
                return_value=[],
            ),
            patch("app.workers.orchestrator.publish_event"),
            patch("app.workers.orchestrator.is_cancelled", return_value=False),
        ):
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = fake_create
            mock_client_cls.return_value = mock_client

            from app.workers.orchestrator import _run_llm_stage

            try:
                _run_llm_stage(
                    job_id="test-job",
                    latex_content=r"\documentclass{article}\begin{document}Hi\end{document}",
                    job_description=None,
                    optimization_level="balanced",
                    api_key="sk-test",
                    persona="startup",
                )
            except Exception:
                pass  # Stream will be empty — we only care that it was called

        # Verify the system message contains the startup addon text
        assert captured_messages, "No messages were captured"
        system_msgs = [m for m in captured_messages if m.get("role") == "system"]
        assert system_msgs, "No system message captured"
        system_content = system_msgs[0]["content"]
        startup_addon = PERSONAS["startup"]["prompt_addon"]
        assert startup_addon in system_content

    def test_no_persona_uses_base_system_prompt(self):
        """When persona is None, only the base system prompt is used."""
        captured_messages: list = []

        def fake_create(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            return iter([])

        with (
            patch("app.workers.orchestrator.openai.OpenAI") as mock_client_cls,
            patch(
                "app.workers.orchestrator.llm_service._create_optimization_prompt",
                return_value="PROMPT",
            ),
            patch(
                "app.workers.orchestrator.llm_service.extract_keywords_from_job_description",
                return_value=[],
            ),
            patch("app.workers.orchestrator.publish_event"),
            patch("app.workers.orchestrator.is_cancelled", return_value=False),
        ):
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = fake_create
            mock_client_cls.return_value = mock_client

            from app.workers.orchestrator import _run_llm_stage

            try:
                _run_llm_stage(
                    job_id="test-job-2",
                    latex_content=r"\documentclass{article}\begin{document}Hi\end{document}",
                    job_description=None,
                    optimization_level="balanced",
                    api_key="sk-test",
                    persona=None,
                )
            except Exception:
                pass

        assert captured_messages
        system_msgs = [m for m in captured_messages if m.get("role") == "system"]
        assert system_msgs
        system_content = system_msgs[0]["content"]
        # No persona addon should be present
        for _, cfg in PERSONAS.items():
            assert cfg["prompt_addon"] not in system_content
