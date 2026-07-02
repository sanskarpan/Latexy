"""
Tests for the byok-llm bug-fix pass.

Covers:
  - Per-model cost accounting (not a fixed per-provider constant)
  - MultiProviderLLMService.generate fallback is OFF by default and, when on,
    scoped to the SAME user's providers (no cross-tenant key/billing leakage)
  - remove_provider drops the stale usage_stats entry
  - ai_routes platform-key fallback resolution + rate-limit gating
  - byok endpoint auth gating (/validate auth, /system/health admin) and the
    /generate stream=true rejection
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

import app.api.ai_routes as air
from app.services.llm_provider_service import (
    AnthropicProvider,
    BaseLLMProvider,
    LLMRequest,
    LLMResponse,
    MultiProviderLLMService,
    OpenAIProvider,
    ProviderCapabilities,
)

_USAGE = {"prompt_tokens": 1000, "completion_tokens": 1000, "total_tokens": 2000}


# ── Fake provider for service-level tests ────────────────────────────────────


class _FakeProvider(BaseLLMProvider):
    def __init__(self, api_key: str, *, fail: bool = False, tag: str = "x"):
        super().__init__(api_key)
        self._fail = fail
        self._tag = tag

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if self._fail:
            raise RuntimeError("boom")
        return LLMResponse(
            content=self._tag,
            model=request.model,
            provider=self._tag,
            usage=dict(_USAGE),
            cost=0.0,
            latency=0.0,
            finish_reason="stop",
        )

    async def validate_api_key(self) -> bool:
        return True

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(1000, True, False, False, 0.5, 0.5, 1, 1)

    def get_available_models(self):
        return ["m"]


# ── Per-model cost accounting (#8) ───────────────────────────────────────────


class TestPerModelPricing:
    def test_openai_cost_varies_by_model(self):
        p = OpenAIProvider("sk-test")
        mini = p.calculate_cost(_USAGE, "gpt-4o-mini")
        turbo = p.calculate_cost(_USAGE, "gpt-4-turbo")
        assert mini < turbo, "cheap model must not be billed at gpt-4-turbo rates"
        assert mini == pytest.approx(0.00015 + 0.0006)
        assert turbo == pytest.approx(0.01 + 0.03)

    def test_anthropic_opus_costs_more_than_haiku(self):
        a = AnthropicProvider("sk-test")
        opus = a.calculate_cost(_USAGE, "claude-3-opus-20240229")
        haiku = a.calculate_cost(_USAGE, "claude-3-haiku-20240307")
        assert opus > haiku

    def test_unknown_model_falls_back_to_capabilities(self):
        p = OpenAIProvider("sk-test")
        caps = p.get_capabilities()
        cost = p.calculate_cost(_USAGE, "some-future-model-2030")
        assert cost == pytest.approx(
            caps.cost_per_1k_input_tokens + caps.cost_per_1k_output_tokens
        )


# ── Fallback scoping (#5) + usage_stats cleanup (#18) ────────────────────────


@pytest.mark.asyncio
class TestGenerateFallbackScoping:
    async def test_fallback_off_by_default(self):
        svc = MultiProviderLLMService()
        svc.add_provider("openai_userA", _FakeProvider("k", fail=True, tag="A"))
        svc.add_provider("anthropic_userA", _FakeProvider("k", fail=False, tag="A2"))
        req = LLMRequest(messages=[], model="m", user_id="userA")
        with pytest.raises(RuntimeError):
            await svc.generate(req, provider_name="openai_userA")

    async def test_fallback_scoped_to_same_user(self):
        svc = MultiProviderLLMService()
        svc.add_provider("openai_userA", _FakeProvider("k", fail=True, tag="A"))
        svc.add_provider("anthropic_userA", _FakeProvider("k", fail=False, tag="A2"))
        svc.add_provider("openai_userB", _FakeProvider("k", fail=False, tag="B"))
        req = LLMRequest(messages=[], model="m", user_id="userA")
        resp = await svc.generate(req, provider_name="openai_userA", fallback=True)
        assert resp.provider == "A2", "must fall back only to the SAME user's provider"

    async def test_no_cross_user_fallback(self):
        svc = MultiProviderLLMService()
        svc.add_provider("openai_userA", _FakeProvider("k", fail=True, tag="A"))
        svc.add_provider("openai_userB", _FakeProvider("k", fail=False, tag="B"))
        req = LLMRequest(messages=[], model="m", user_id="userA")
        with pytest.raises(RuntimeError):
            # userB's key must never be used to serve userA's request
            await svc.generate(req, provider_name="openai_userA", fallback=True)

    def test_remove_provider_drops_usage_stats(self):
        svc = MultiProviderLLMService()
        svc.add_provider("openai_x", _FakeProvider("k"))
        assert "openai_x" in svc.usage_stats
        svc.remove_provider("openai_x")
        assert "openai_x" not in svc.usage_stats


# ── ai_routes platform-key resolution + rate limiting (#3) ───────────────────


@pytest.mark.asyncio
class TestAIKeyResolution:
    async def test_rate_limit_disabled_in_tests(self):
        # RATE_LIMIT_ENABLED is false in the test env -> never limited.
        assert await air._system_key_rate_limited("anyone") is False

    async def test_prefers_system_key_for_anonymous(self, monkeypatch):
        monkeypatch.setattr(air.settings, "OPENAI_API_KEY", "sk-sys")
        key = await air._resolve_ai_api_key(None, None, "1.2.3.4")
        assert key == "sk-sys"

    async def test_returns_none_when_no_key_configured(self, monkeypatch):
        monkeypatch.setattr(air.settings, "OPENAI_API_KEY", "")
        key = await air._resolve_ai_api_key(None, None, "1.2.3.4")
        assert key is None


# ── byok endpoint auth + stream gating (#6, #7) ──────────────────────────────


@pytest.mark.asyncio
class TestByokEndpointGuards:
    async def test_validate_requires_auth(self, client: AsyncClient):
        r = await client.post(
            "/byok/validate", json={"provider": "openai", "api_key": "sk-x"}
        )
        assert r.status_code in (401, 403)

    async def test_system_health_requires_admin(self, client: AsyncClient):
        r = await client.get("/byok/system/health")
        assert r.status_code in (401, 403)

    async def test_generate_rejects_stream(self, client: AsyncClient, auth_headers: dict):
        r = await client.post(
            "/byok/generate",
            headers=auth_headers,
            json={
                "provider": "openai",
                "messages": [{"role": "user", "content": "hi"}],
                "model": "gpt-4o-mini",
                "stream": True,
            },
        )
        assert r.status_code == 400
