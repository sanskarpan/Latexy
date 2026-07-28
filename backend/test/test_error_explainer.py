"""
Tests for the AI LaTeX error explainer (pattern matching + endpoint).
"""

import pytest
from httpx import AsyncClient

# ── Pattern matching tests ────────────────────────────────────────────────────


class TestPatternMatching:
    """Test the regex-based pattern fallback dictionary."""

    def _service(self):
        from app.services.error_explainer_service import error_explainer_service
        return error_explainer_service

    def test_pattern_undefined_control_sequence(self):
        result = self._service().explain_from_patterns("! Undefined control sequence.")
        assert "exist" in result.explanation.lower() or "command" in result.explanation.lower()
        assert result.suggested_fix

    def test_pattern_missing_dollar(self):
        result = self._service().explain_from_patterns("! Missing $ inserted.")
        assert "math" in result.explanation.lower()
        assert result.suggested_fix

    def test_pattern_extra_brace(self):
        result = self._service().explain_from_patterns("! Extra }.")
        assert "brace" in result.explanation.lower() or "}" in result.explanation
        assert result.suggested_fix

    def test_pattern_overfull_hbox(self):
        result = self._service().explain_from_patterns(
            "Overfull \\hbox (12.0pt too wide) in paragraph at lines 42--45"
        )
        assert "wide" in result.explanation.lower() or "overflow" in result.explanation.lower()
        assert result.suggested_fix

    def test_pattern_unknown_error_returns_generic(self):
        result = self._service().explain_from_patterns(
            "xyzzy blarf totally unknown error 999"
        )
        assert result.explanation  # should still return something
        assert result.suggested_fix

    def test_pattern_environment_mismatch(self):
        result = self._service().explain_from_patterns(
            "! LaTeX Error: \\begin{itemize} on input line 5 ended by \\end{enumerate}."
        )
        assert "different name" in result.explanation.lower() or "match" in result.explanation.lower()

    def test_pattern_missing_begin_document(self):
        result = self._service().explain_from_patterns(
            "! LaTeX Error: Missing \\begin{document}."
        )
        assert "document" in result.explanation.lower()

    def test_pattern_emergency_stop(self):
        result = self._service().explain_from_patterns("!  ==> Fatal error occurred, no output PDF file produced!")
        # Emergency stop won't match but let's test something that does
        result2 = self._service().explain_from_patterns("! Emergency stop.")
        assert "critical" in result2.explanation.lower() or "halt" in result2.explanation.lower()


# ── Endpoint tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestExplainErrorEndpoint:
    """Test the POST /ai/explain-error endpoint."""

    async def test_endpoint_returns_required_fields(self, client: AsyncClient):
        resp = await client.post(
            "/ai/explain-error",
            json={"error_message": "! Undefined control sequence."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "explanation" in data
        assert "suggested_fix" in data
        assert "source" in data
        assert "cached" in data
        assert "processing_time" in data
        assert data["success"] is True

    async def test_endpoint_empty_message_rejected(self, client: AsyncClient):
        resp = await client.post(
            "/ai/explain-error",
            json={"error_message": ""},
        )
        assert resp.status_code == 422

    async def test_endpoint_too_long_rejected(self, client: AsyncClient):
        resp = await client.post(
            "/ai/explain-error",
            json={"error_message": "x" * 2001},
        )
        assert resp.status_code == 422

    async def test_endpoint_pattern_source(self, client: AsyncClient):
        """Endpoint should return a valid source type."""
        resp = await client.post(
            "/ai/explain-error",
            json={
                "error_message": "! Missing $ inserted.",
                "surrounding_latex": "\\badcommand",
                "error_line": 5,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] in ("pattern", "llm", "error")

    async def test_endpoint_with_surrounding_latex(self, client: AsyncClient):
        resp = await client.post(
            "/ai/explain-error",
            json={
                "error_message": "! Undefined control sequence.",
                "surrounding_latex": "\\documentclass{article}\n\\begin{document}\n\\badcommand\n\\end{document}",
                "error_line": 3,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["explanation"]

    async def test_endpoint_auth_optional(self, client: AsyncClient, auth_headers: dict):
        """Endpoint should work for both anonymous and authenticated users."""
        # Anonymous
        resp1 = await client.post(
            "/ai/explain-error",
            json={"error_message": "! Extra }."},
        )
        assert resp1.status_code == 200

        # Authenticated
        resp2 = await client.post(
            "/ai/explain-error",
            json={"error_message": "! Extra }."},
            headers=auth_headers,
        )
        assert resp2.status_code == 200


# ── Quota metering ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestExplainErrorQuotaMetering:
    """Only real LLM work may spend an ``ai_assists`` unit.

    The pattern table and the 24h cache cost nothing, so a signed-in caller with
    an exhausted allowance must still get them — anonymous callers do.
    """

    @staticmethod
    def _deny_quota(monkeypatch) -> list:
        """Make every quota charge raise 402 and record that it happened."""
        from fastapi import HTTPException

        import app.api.ai_routes as ai_routes
        from app.core.errors import error_body

        charges: list = []

        async def _enforce(dimension, **kwargs):
            charges.append(dimension)
            raise HTTPException(
                status_code=402,
                detail=error_body("quota_exceeded", "spent", None),
            )

        monkeypatch.setattr(
            ai_routes.entitlement_service, "enforce_quota", _enforce
        )
        return charges

    async def test_pattern_answer_is_free_for_authenticated_user(
        self, client: AsyncClient, auth_headers: dict, monkeypatch
    ):
        import app.api.ai_routes as ai_routes

        charges = self._deny_quota(monkeypatch)

        async def _no_key(*args, **kwargs):
            return ai_routes.ResolvedAIKey(None)

        monkeypatch.setattr(ai_routes, "_resolve_ai_api_key", _no_key)

        resp = await client.post(
            "/ai/explain-error",
            json={"error_message": "! Undefined control sequence."},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["source"] == "pattern"
        assert charges == []

    async def test_cache_hit_is_free_for_authenticated_user(
        self, client: AsyncClient, auth_headers: dict, monkeypatch
    ):
        import app.api.ai_routes as ai_routes
        import app.services.error_explainer_service as explainer

        charges = self._deny_quota(monkeypatch)

        async def _key(*args, **kwargs):
            return ai_routes.ResolvedAIKey("sk-test")

        async def _cached(_key_name):
            return {
                "explanation": "cached explanation",
                "suggested_fix": "cached fix",
                "corrected_code": None,
                "source": "llm",
            }

        monkeypatch.setattr(ai_routes, "_resolve_ai_api_key", _key)
        monkeypatch.setattr(explainer.cache_manager, "get", _cached)

        resp = await client.post(
            "/ai/explain-error",
            json={"error_message": "! Undefined control sequence."},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"] is True
        assert body["explanation"] == "cached explanation"
        assert charges == []

    async def test_llm_call_is_charged_and_denial_surfaces(
        self, client: AsyncClient, auth_headers: dict, monkeypatch
    ):
        import app.api.ai_routes as ai_routes
        import app.services.error_explainer_service as explainer

        charges = self._deny_quota(monkeypatch)

        async def _key(*args, **kwargs):
            return ai_routes.ResolvedAIKey("sk-test")

        async def _miss(_key_name):
            return None

        async def _llm(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("LLM called despite exhausted quota")

        monkeypatch.setattr(ai_routes, "_resolve_ai_api_key", _key)
        monkeypatch.setattr(explainer.cache_manager, "get", _miss)
        monkeypatch.setattr(
            explainer.error_explainer_service, "explain_with_llm", _llm
        )

        resp = await client.post(
            "/ai/explain-error",
            json={"error_message": "! Undefined control sequence."},
            headers=auth_headers,
        )
        assert resp.status_code == 402
        assert resp.json()["error"]["code"] == "quota_exceeded"
        assert charges == ["ai_assists"]
