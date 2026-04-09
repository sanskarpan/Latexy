"""
Tests for Feature 45: Salary Estimator.

Covers:
  - Response contains all required fields
  - low <= median <= high invariant
  - Cache: second identical request returns cached=True
  - Unsorted LLM values are re-sorted by the endpoint
  - Validation: resume_latex too long (>50000) → 422
  - Validation: target_role too long (>200) → 422
  - Validation: location too long (>200) → 422
  - Endpoint accessible without auth (anonymous)
  - Currency inferred from location
  - No API key configured → returns graceful response (not 500)
  - Percentile clamped to 0-100
  - LLM error → graceful fallback (not 500)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SETTINGS_PATCH = "app.api.ai_routes.settings"

SIMPLE_LATEX = r"""
\documentclass{article}
\begin{document}
Senior Software Engineer with 8 years experience in Python, AWS, and Kubernetes.
\end{document}
"""

_VALID_PAYLOAD = {
    "resume_latex": SIMPLE_LATEX,
    "target_role": "Senior Software Engineer",
    "location": "San Francisco, CA",
}


def _make_openai_response(data: dict) -> MagicMock:
    """Build a minimal fake OpenAI response."""
    choice = MagicMock()
    choice.message.content = json.dumps(data)
    resp = MagicMock()
    resp.choices = [choice]
    return resp


_VALID_LLM_RESP = {
    "currency": "USD",
    "low": 140000,
    "median": 165000,
    "high": 200000,
    "percentile": 78,
    "key_skills": ["Python", "AWS", "Kubernetes"],
    "disclaimer": "Estimates are based on publicly available market data and may vary.",
}


def _mock_settings(mock):
    mock.OPENAI_API_KEY = "sk-test-dummy"
    mock.OPENAI_MODEL = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# 45A — Cache key helper unit tests
# ---------------------------------------------------------------------------


class TestSalaryCacheKey:
    def test_returns_ai_salary_prefix(self):
        from app.api.ai_routes import _salary_cache_key

        key = _salary_cache_key(SIMPLE_LATEX, "Software Engineer", "New York")
        assert key.startswith("ai:salary:")

    def test_returns_16_hex_chars(self):
        from app.api.ai_routes import _salary_cache_key

        key = _salary_cache_key(SIMPLE_LATEX, "Software Engineer", "New York")
        suffix = key.removeprefix("ai:salary:")
        assert len(suffix) == 16
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_same_inputs_same_key(self):
        from app.api.ai_routes import _salary_cache_key

        k1 = _salary_cache_key(SIMPLE_LATEX, "SWE", "NYC")
        k2 = _salary_cache_key(SIMPLE_LATEX, "SWE", "NYC")
        assert k1 == k2

    def test_different_role_different_key(self):
        from app.api.ai_routes import _salary_cache_key

        k1 = _salary_cache_key(SIMPLE_LATEX, "SWE", "NYC")
        k2 = _salary_cache_key(SIMPLE_LATEX, "Data Scientist", "NYC")
        assert k1 != k2

    def test_different_location_different_key(self):
        from app.api.ai_routes import _salary_cache_key

        k1 = _salary_cache_key(SIMPLE_LATEX, "SWE", "NYC")
        k2 = _salary_cache_key(SIMPLE_LATEX, "SWE", "London")
        assert k1 != k2

    def test_location_case_insensitive(self):
        """Cache key uses lowercased location → same key for different cases."""
        from app.api.ai_routes import _salary_cache_key

        k1 = _salary_cache_key(SIMPLE_LATEX, "SWE", "New York")
        k2 = _salary_cache_key(SIMPLE_LATEX, "SWE", "new york")
        assert k1 == k2

    def test_role_case_insensitive(self):
        from app.api.ai_routes import _salary_cache_key

        k1 = _salary_cache_key(SIMPLE_LATEX, "Software Engineer", "NYC")
        k2 = _salary_cache_key(SIMPLE_LATEX, "software engineer", "NYC")
        assert k1 == k2


# ---------------------------------------------------------------------------
# 45B — Validation tests (no LLM needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSalaryEstimateValidation:
    async def test_resume_latex_too_long_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/salary-estimate",
            json={
                "resume_latex": "x" * 50_001,
                "target_role": "Engineer",
                "location": "NYC",
            },
        )
        assert resp.status_code == 422

    async def test_target_role_too_long_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/salary-estimate",
            json={
                "resume_latex": SIMPLE_LATEX,
                "target_role": "R" * 201,
                "location": "NYC",
            },
        )
        assert resp.status_code == 422

    async def test_location_too_long_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/salary-estimate",
            json={
                "resume_latex": SIMPLE_LATEX,
                "target_role": "Engineer",
                "location": "L" * 201,
            },
        )
        assert resp.status_code == 422

    async def test_missing_resume_latex_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/salary-estimate",
            json={"target_role": "Engineer", "location": "NYC"},
        )
        assert resp.status_code == 422

    async def test_missing_target_role_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/salary-estimate",
            json={"resume_latex": SIMPLE_LATEX, "location": "NYC"},
        )
        assert resp.status_code == 422

    async def test_missing_location_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/salary-estimate",
            json={"resume_latex": SIMPLE_LATEX, "target_role": "Engineer"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 45C — LLM-backed response tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSalaryEstimateLLM:
    async def test_response_contains_all_required_fields(self, client: AsyncClient):
        """Response includes all required fields with correct types."""
        with (
            patch(_SETTINGS_PATCH) as mock_settings,
            patch("app.api.ai_routes.openai.AsyncOpenAI") as mock_cls,
            patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock),
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_VALID_LLM_RESP)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post("/ai/salary-estimate", json=_VALID_PAYLOAD)
            assert resp.status_code == 200
            data = resp.json()

        for key in ("currency", "low", "median", "high", "percentile", "key_skills", "disclaimer", "cached"):
            assert key in data, f"Missing key: {key}"

        assert isinstance(data["currency"], str)
        assert isinstance(data["low"], int)
        assert isinstance(data["median"], int)
        assert isinstance(data["high"], int)
        assert isinstance(data["percentile"], int)
        assert isinstance(data["key_skills"], list)
        assert isinstance(data["disclaimer"], str)
        assert isinstance(data["cached"], bool)

    async def test_low_lte_median_lte_high_invariant(self, client: AsyncClient):
        """low <= median <= high must always hold."""
        with (
            patch(_SETTINGS_PATCH) as mock_settings,
            patch("app.api.ai_routes.openai.AsyncOpenAI") as mock_cls,
            patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock),
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_VALID_LLM_RESP)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post("/ai/salary-estimate", json=_VALID_PAYLOAD)
            assert resp.status_code == 200
            data = resp.json()

        assert data["low"] <= data["median"] <= data["high"], (
            f"Invariant violated: low={data['low']} median={data['median']} high={data['high']}"
        )

    async def test_unsorted_llm_values_are_corrected(self, client: AsyncClient):
        """If LLM returns low > median > high, endpoint reorders them."""
        bad_resp = {**_VALID_LLM_RESP, "low": 200000, "median": 165000, "high": 140000}
        with (
            patch(_SETTINGS_PATCH) as mock_settings,
            patch("app.api.ai_routes.openai.AsyncOpenAI") as mock_cls,
            patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock),
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(bad_resp)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post("/ai/salary-estimate", json=_VALID_PAYLOAD)
            assert resp.status_code == 200
            data = resp.json()

        assert data["low"] <= data["median"] <= data["high"]
        assert data["low"] == 140000
        assert data["median"] == 165000
        assert data["high"] == 200000

    async def test_cached_false_on_first_request(self, client: AsyncClient):
        """First request returns cached=False."""
        with (
            patch(_SETTINGS_PATCH) as mock_settings,
            patch("app.api.ai_routes.openai.AsyncOpenAI") as mock_cls,
            patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock),
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_VALID_LLM_RESP)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post("/ai/salary-estimate", json=_VALID_PAYLOAD)
            assert resp.status_code == 200
            assert resp.json()["cached"] is False

    async def test_cache_hit_returns_cached_true(self, client: AsyncClient):
        """Second identical request returns cached=True (served from cache)."""
        cached_data = {
            "currency": "USD",
            "low": 140000,
            "median": 165000,
            "high": 200000,
            "percentile": 78,
            "key_skills": ["Python", "AWS"],
            "disclaimer": "Estimates may vary.",
        }
        with (
            patch(_SETTINGS_PATCH) as mock_settings,
            patch("app.api.ai_routes.openai.AsyncOpenAI") as mock_cls,
            patch(
                "app.api.ai_routes.cache_manager.get",
                new_callable=AsyncMock,
                return_value=cached_data,
            ),
            patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock),
        ):
            _mock_settings(mock_settings)
            mock_cls.return_value = AsyncMock()  # should NOT be called

            resp = await client.post("/ai/salary-estimate", json=_VALID_PAYLOAD)
            assert resp.status_code == 200
            data = resp.json()

        assert data["cached"] is True
        # LLM was never called
        mock_cls.return_value.chat.completions.create.assert_not_called()

    async def test_percentile_clamped_to_0_100(self, client: AsyncClient):
        """Percentile values outside [0,100] are clamped."""
        bad_resp = {**_VALID_LLM_RESP, "percentile": 150}
        with (
            patch(_SETTINGS_PATCH) as mock_settings,
            patch("app.api.ai_routes.openai.AsyncOpenAI") as mock_cls,
            patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock),
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(bad_resp)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post("/ai/salary-estimate", json=_VALID_PAYLOAD)
            assert resp.status_code == 200
            data = resp.json()

        assert 0 <= data["percentile"] <= 100

    async def test_no_api_key_returns_graceful_response(self, client: AsyncClient):
        """Missing API key → 200 with empty/zero values (not 500)."""
        with patch(_SETTINGS_PATCH) as mock_settings:
            mock_settings.OPENAI_API_KEY = ""

            resp = await client.post("/ai/salary-estimate", json=_VALID_PAYLOAD)

        assert resp.status_code == 200
        data = resp.json()
        # Should return zeros gracefully
        assert data["low"] == 0
        assert data["median"] == 0
        assert data["high"] == 0

    async def test_anon_accessible(self, client: AsyncClient):
        """Endpoint accessible without Authorization header."""
        with (
            patch(_SETTINGS_PATCH) as mock_settings,
            patch("app.api.ai_routes.openai.AsyncOpenAI") as mock_cls,
            patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock),
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_VALID_LLM_RESP)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/salary-estimate",
                json=_VALID_PAYLOAD,
                # No auth headers
            )
        assert resp.status_code == 200

    async def test_key_skills_is_list_of_strings(self, client: AsyncClient):
        """key_skills must be a list of strings."""
        with (
            patch(_SETTINGS_PATCH) as mock_settings,
            patch("app.api.ai_routes.openai.AsyncOpenAI") as mock_cls,
            patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock),
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_VALID_LLM_RESP)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post("/ai/salary-estimate", json=_VALID_PAYLOAD)
            assert resp.status_code == 200
            data = resp.json()

        assert isinstance(data["key_skills"], list)
        for skill in data["key_skills"]:
            assert isinstance(skill, str)

    async def test_llm_error_returns_graceful_response(self, client: AsyncClient):
        """If LLM call raises, endpoint returns 200 with fallback values (not 500)."""
        with (
            patch(_SETTINGS_PATCH) as mock_settings,
            patch("app.api.ai_routes.openai.AsyncOpenAI") as mock_cls,
            patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock),
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                side_effect=Exception("OpenAI rate limit")
            )
            mock_cls.return_value = mock_openai

            resp = await client.post("/ai/salary-estimate", json=_VALID_PAYLOAD)

        assert resp.status_code == 200
        data = resp.json()
        # Should be non-500, all required fields present
        for key in ("currency", "low", "median", "high", "percentile", "key_skills", "disclaimer", "cached"):
            assert key in data

    async def test_currency_from_location_us(self, client: AsyncClient):
        """For US location, currency should be USD."""
        with (
            patch(_SETTINGS_PATCH) as mock_settings,
            patch("app.api.ai_routes.openai.AsyncOpenAI") as mock_cls,
            patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock),
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_VALID_LLM_RESP)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/salary-estimate",
                json={**_VALID_PAYLOAD, "location": "New York, USA"},
            )
            assert resp.status_code == 200
            data = resp.json()

        assert data["currency"] == "USD"

    async def test_currency_for_uk_location(self, client: AsyncClient):
        """For UK location, currency should be GBP."""
        uk_resp = {**_VALID_LLM_RESP, "currency": "GBP", "low": 70000, "median": 85000, "high": 110000}
        with (
            patch(_SETTINGS_PATCH) as mock_settings,
            patch("app.api.ai_routes.openai.AsyncOpenAI") as mock_cls,
            patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock),
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(uk_resp)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post(
                "/ai/salary-estimate",
                json={**_VALID_PAYLOAD, "location": "London, UK"},
            )
            assert resp.status_code == 200
            data = resp.json()

        assert data["currency"] == "GBP"

    async def test_cache_set_called_on_first_request(self, client: AsyncClient):
        """Cache.set is called with TTL=86400 on a fresh request."""
        with (
            patch(_SETTINGS_PATCH) as mock_settings,
            patch("app.api.ai_routes.openai.AsyncOpenAI") as mock_cls,
            patch("app.api.ai_routes.cache_manager.get", new_callable=AsyncMock, return_value=None),
            patch("app.api.ai_routes.cache_manager.set", new_callable=AsyncMock) as mock_set,
        ):
            _mock_settings(mock_settings)
            mock_openai = AsyncMock()
            mock_openai.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_VALID_LLM_RESP)
            )
            mock_cls.return_value = mock_openai

            resp = await client.post("/ai/salary-estimate", json=_VALID_PAYLOAD)
            assert resp.status_code == 200

        mock_set.assert_called_once()
        call_kwargs = mock_set.call_args
        # TTL should be 86400 (24h)
        assert call_kwargs.kwargs.get("ttl") == 86400 or (len(call_kwargs.args) >= 3 and call_kwargs.args[2] == 86400)
