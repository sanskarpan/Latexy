"""Explicit provider choice, native bounded streams, and owned admission."""
import json
import threading
import time
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from app.api.resume_engine_routes import engine_providers
from app.core.config import settings
from app.database.models import ResumeOptimizationRun, User, UserAPIKey
from app.services.resume_engine.budgets import BudgetExceeded
from app.services.resume_engine.patches import CompactOptimizationError
from app.services.resume_engine.provider import SemanticProvider, resolve_provider
from app.services.resume_engine.stages import StageCheckpointError
from app.workers.job_lifecycle import set_current_capability

from .test_resume_durable_ledger import admitted as admitted
from .test_resume_durable_ledger import database
from .test_resume_semantic_engine import FakeLedger


def native_events(text='{"patches": [], "missing_evidence": []}', stop="end_turn"):
    return [
        {"type": "message_start", "message": {"type": "message", "role": "assistant", "usage": {"input_tokens": 30, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": stop}, "usage": {"output_tokens": 20}},
        {"type": "message_stop"},
    ]


def framed(events):
    return b"".join(("event: " + event["type"] + "\ndata: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode() for event in events)


@pytest.fixture
def priced(monkeypatch):
    monkeypatch.setattr(settings, "RESUME_ENGINE_MODEL_PRICING", {
        "openai:gpt-4o-mini": {"input_per_million": .15, "output_per_million": .60},
        "anthropic:synthetic-claude": {"input_per_million": .15, "output_per_million": .60},
        "openrouter:synthetic/model": {"input_per_million": .15, "output_per_million": .60},
    })


def provider(priced, content, *, ledger=None, observer=None):
    ledger = ledger or FakeLedger()
    def transport(request):
        if observer is not None:
            observer.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=content)
    result = SemanticProvider(spec=resolve_provider("synthetic-key", "synthetic-claude", selected_provider="anthropic"),
        api_key="synthetic-key", ledger=ledger, deadline=time.monotonic() + 3, cancelled=lambda: False,
        owner_scope="owner", client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(transport), **kwargs))
    return result, ledger


def test_native_anthropic_stream_is_validated_then_replayed_without_another_request(priced):
    observed = []
    adapter, ledger = provider(priced, framed(native_events()), observer=observed)
    try:
        options = dict(system="JSON only", payload={"field": "你好"}, schema={"type": "object"})
        first = adapter.generate("one", **options)
        replay = adapter.generate("one", **options)
        assert first[0] == {"patches": [], "missing_evidence": []} and not first[2] and replay[2]
        assert len(observed) == 1 and len(ledger.intents) == 1
        assert str(observed[0].url) == "https://api.anthropic.com/v1/messages"
        assert observed[0].headers["anthropic-version"] == "2023-06-01"
        body = json.loads(observed[0].content)
        assert body["stream"] is True and body["model"] == "synthetic-claude"
        assert "response_format" not in body and "stream_options" not in body
        assert first[1]["input_tokens"] == 30 and first[1]["output_tokens"] == 20
    finally:
        adapter.close()


@pytest.mark.parametrize("attack", ["truncated", "wrong-event", "wrong-index", "missing-usage", "max-tokens", "refusal", "duplicate", "nonfinite", "framing-overflow", "post-terminal"])
def test_native_anthropic_malformed_or_unfinished_paid_stage_is_not_accepted(priced, attack):
    events = native_events()
    if attack == "truncated":
        events.pop()
    elif attack == "wrong-event":
        events[1]["type"] = "unknown_event"
    elif attack == "wrong-index":
        events[2]["index"] = 1
    elif attack == "missing-usage":
        events[0]["message"].pop("usage")
    elif attack == "max-tokens":
        events[4]["delta"]["stop_reason"] = "max_tokens"
    elif attack == "refusal":
        events[4]["delta"]["stop_reason"] = "refusal"
    elif attack == "post-terminal":
        events.append(events[2])
    data = framed(events)
    if attack == "duplicate":
        data = data.replace(b'"type": "message_start"', b'"type": "message_start", "type": "message_start"', 1)
    elif attack == "nonfinite":
        data = data.replace(b'"input_tokens": 30', b'"input_tokens": NaN', 1)
    elif attack == "framing-overflow":
        data = b":" + b"x" * 128001 + b"\n\n" + data
    adapter, ledger = provider(priced, data)
    try:
        with pytest.raises((CompactOptimizationError, ValueError)):
            adapter.generate("bad", system="JSON", payload={}, schema={})
        assert ledger.intents["bad"].get("failed") and "output" not in ledger.intents["bad"]
        with pytest.raises(RuntimeError, match="ambiguous"):
            adapter.generate("bad", system="JSON", payload={}, schema={})
    finally:
        adapter.close()


def test_anthropic_watchdog_closes_transport_before_blocked_headers(priced):
    closed = threading.Event()
    calls = []
    class Client:
        def stream(self, *args, **kwargs):
            calls.append(kwargs)
            closed.wait(2)
            raise RuntimeError("closed headers")
        def close(self):
            closed.set()
    ledger = FakeLedger()
    adapter = SemanticProvider(spec=resolve_provider("synthetic-key", None, selected_provider="anthropic"),
        api_key="synthetic-key", ledger=ledger, deadline=time.monotonic() + .1,
        cancelled=lambda: False, owner_scope="owner", client_factory=lambda **kwargs: Client())
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="closed headers"):
            adapter.generate("headers", system="JSON", payload={}, schema={})
        assert closed.is_set() and time.monotonic() - started < 1 and len(calls) == 1
        assert ledger.intents["headers"].get("failed")
    finally:
        adapter.close()


def test_native_cumulative_usage_and_ping_events_are_not_double_counted(priced):
    events = native_events()
    events.insert(4, {"type": "message_delta", "delta": {"stop_reason": None}, "usage": {"output_tokens": 10}})
    events.insert(2, {"type": "ping"})
    adapter, _ = provider(priced, framed(events))
    try:
        _, usage, _ = adapter.generate("cumulative", system="JSON", payload={}, schema={})
        assert usage["output_tokens"] == 20
    finally:
        adapter.close()


def test_anthropic_watchdog_closes_a_silent_response_body(priced):
    closed = threading.Event()
    class SilentBody(httpx.SyncByteStream):
        def __iter__(self):
            closed.wait(2)
            raise RuntimeError("closed silent body")
            yield b""  # Mark this as a streaming iterator.
        def close(self):
            closed.set()
    def transport(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=SilentBody())
    ledger = FakeLedger()
    adapter = SemanticProvider(spec=resolve_provider("synthetic-key", None, selected_provider="anthropic"),
        api_key="synthetic-key", ledger=ledger, deadline=time.monotonic() + .1,
        cancelled=lambda: False, owner_scope="owner",
        client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(transport), **kwargs))
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="closed silent body"):
            adapter.generate("body", system="JSON", payload={}, schema={})
        assert closed.is_set() and time.monotonic() - started < 1
        assert ledger.intents["body"].get("failed") and "output" not in ledger.intents["body"]
    finally:
        adapter.close()


@pytest.mark.parametrize("field", ["cache_creation_input_tokens", "cache_read_input_tokens"])
@pytest.mark.parametrize("value", [1, -1, True, "0", None])
def test_native_unpriced_or_invalid_cache_usage_fails_closed(priced, field, value):
    events = native_events()
    events[0]["message"]["usage"][field] = value
    adapter, ledger = provider(priced, framed(events))
    try:
        with pytest.raises(CompactOptimizationError):
            adapter.generate("cache", system="JSON", payload={}, schema={})
        assert ledger.intents["cache"].get("failed") and "output" not in ledger.intents["cache"]
    finally:
        adapter.close()


def test_native_zero_cache_usage_is_supported_without_a_cache_price(priced):
    events = native_events()
    events[0]["message"]["usage"].update(cache_creation_input_tokens=0, cache_read_input_tokens=0,
        cache_creation={"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0})
    adapter, _ = provider(priced, framed(events))
    try:
        assert adapter.generate("cache-zero", system="JSON", payload={}, schema={})[1]["input_tokens"] == 30
    finally:
        adapter.close()


def test_openrouter_reuses_bounded_openai_transport_without_platform_endpoint(priced, monkeypatch):
    from .test_resume_semantic_engine import chunks
    requests, construction = [], []
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://example.invalid/v1")
    client = Obj(chat=Obj(completions=Obj(create=lambda **kwargs: requests.append(kwargs) or chunks({"patches": [], "missing_evidence": []}))), close=lambda: None)
    def factory(**kwargs):
        construction.append(kwargs)
        return client
    ledger = FakeLedger()
    adapter = SemanticProvider(spec=resolve_provider("synthetic-key", None, selected_provider="openrouter"),
        api_key="synthetic-key", ledger=ledger, deadline=time.monotonic() + 3, cancelled=lambda: False,
        owner_scope="owner", client_factory=factory)
    try:
        adapter.generate("openrouter", system="JSON", payload={}, schema={})
        assert construction[0]["base_url"] == "https://openrouter.ai/api/v1"
        assert construction[0]["max_retries"] == 0 and construction[0]["api_key"] == "synthetic-key"
        assert requests[0]["model"] == "synthetic/model" and "response_format" not in requests[0]
        assert requests[0]["stream_options"] == {"include_usage": True}
    finally:
        adapter.close()


@pytest.mark.parametrize("selected,endpoint", [("openai", None), ("anthropic", "https://api.anthropic.com/v1/messages"), ("openrouter", "https://openrouter.ai/api/v1")])
def test_explicit_provider_never_inherits_platform_url_or_price(priced, monkeypatch, selected, endpoint):
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "synthetic-key")
    spec = resolve_provider("synthetic-key", None, selected_provider=selected)
    assert spec.provider == selected and spec.base_url == endpoint
    with pytest.raises(BudgetExceeded):
        resolve_provider("synthetic-key", "unpriced-model", selected_provider=selected)


@pytest.mark.parametrize("attack", ["missing-key", "unpriced", "model-only", "provider-url", "object-provider"])
def test_explicit_provider_admission_refuses_before_quota_or_dispatch(admitted, priced, monkeypatch, attack):
    from app.api import job_routes as routes
    _, args, user_id, resume_id, _, _ = admitted
    quota, dispatch = AsyncMock(), AsyncMock()
    monkeypatch.setattr(routes, "_resolve_user_plan", AsyncMock(return_value="byok"))
    monkeypatch.setattr(routes.api_key_service, "get_user_provider", AsyncMock(return_value=None if attack == "missing-key" else "synthetic-key"))
    monkeypatch.setattr(routes, "_consume_job_quota", quota)
    monkeypatch.setattr(routes, "submit_async", dispatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "platform-must-not-fallback")
    metadata = {"resume_id": resume_id, "optimization_engine": "semantic_v1", "optimization_effort": "quick",
        "expected_content_revision": 1, "expected_source_sha256": args["document"]["source_sha256"],
        "semantic_provider": "anthropic", "semantic_provider_model": "synthetic-claude"}
    if attack == "unpriced":
        metadata["semantic_provider_model"] = "unpriced"
    elif attack == "model-only":
        metadata.pop("semantic_provider")
    elif attack == "provider-url":
        metadata["semantic_provider"] = "https://example.invalid"
    elif attack == "object-provider":
        metadata["semantic_provider"] = {"url": "https://example.invalid"}
    request = routes.JobSubmissionRequest(job_type="combined", latex_content=args["document"]["_source"],
        job_description="Python required", metadata=metadata)
    async def submit(db):
        with pytest.raises(HTTPException) as error:
            await routes.submit_job(request, Obj(client=Obj(host="127.0.0.1")), db, user_id)
        assert error.value.status_code == 422
    database(submit)
    quota.assert_not_awaited()
    dispatch.assert_not_awaited()


def test_provider_options_are_owner_scoped_nonsecret_and_exactly_priced(admitted, priced, monkeypatch):
    _, _, user_id, _, _, _ = admitted
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    async def inspect(db):
        outsider_id = str(uuid4())
        db.add(User(id=outsider_id, email=outsider_id + "@example.test"))
        db.add(UserAPIKey(user_id=user_id, provider="anthropic", encrypted_key="synthetic-unreadable-ciphertext", is_active=True))
        await db.commit()
        response = await engine_providers(db, user_id)
        anthropic = next(item for item in response["providers"] if item["provider"] == "anthropic")
        assert anthropic == {"provider": "anthropic", "key_available": True, "models": ["synthetic-claude"]}
        assert response["default"]["ready"] is False
        assert "synthetic-unreadable-ciphertext" not in json.dumps(response)
        outsider = await engine_providers(db, outsider_id)
        assert not any(item["key_available"] for item in outsider["providers"])
    database(inspect)


def test_unreadable_selected_key_refuses_without_falling_back_to_platform(admitted, priced, monkeypatch):
    from app.api import job_routes as routes
    _, args, user_id, resume_id, _, _ = admitted
    quota, dispatch = AsyncMock(), AsyncMock()
    monkeypatch.setattr(routes, "_resolve_user_plan", AsyncMock(return_value="byok"))
    monkeypatch.setattr(routes, "_consume_job_quota", quota)
    monkeypatch.setattr(routes, "submit_async", dispatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "platform-must-not-fallback")
    metadata = {"resume_id": resume_id, "optimization_engine": "semantic_v1", "optimization_effort": "quick",
        "expected_content_revision": 1, "expected_source_sha256": args["document"]["source_sha256"],
        "semantic_provider": "anthropic", "semantic_provider_model": "synthetic-claude"}
    async def submit(db):
        db.add(UserAPIKey(user_id=user_id, provider="anthropic", encrypted_key="unreadable-selected-key", is_active=True))
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await routes.submit_job(routes.JobSubmissionRequest(job_type="combined", metadata=metadata,
                latex_content=args["document"]["_source"], job_description="Python required"),
                Obj(client=Obj(host="127.0.0.1")), db, user_id)
        assert error.value.status_code == 422
    database(submit)
    quota.assert_not_awaited()
    dispatch.assert_not_awaited()


@pytest.mark.parametrize("selected,model", [("anthropic", "synthetic-claude"), ("openrouter", "synthetic/model")])
def test_real_admission_dispatches_canonical_selected_provider_and_only_its_key(admitted, priced, monkeypatch, selected, model):
    from app.api import job_routes as routes
    _, args, user_id, resume_id, _, _ = admitted
    quota, dispatch = AsyncMock(return_value=None), AsyncMock()
    async def key(_db, _user, provider):
        return "selected-user-key" if provider == selected else "different-openai-key"
    monkeypatch.setattr(routes.api_key_service, "get_user_provider", key)
    monkeypatch.setattr(routes, "_resolve_user_plan", AsyncMock(return_value="byok"))
    monkeypatch.setattr(routes, "_consume_job_quota", quota)
    monkeypatch.setattr(routes, "submit_async", dispatch)
    for name in ("_write_initial_redis_state", "_mark_dispatch_started", "_mark_dispatch_accepted"):
        monkeypatch.setattr(routes, name, AsyncMock(return_value=True))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "platform-must-not-be-used")
    metadata = {"resume_id": resume_id, "optimization_engine": "semantic_v1", "optimization_effort": "quick",
        "expected_content_revision": 1, "expected_source_sha256": args["document"]["source_sha256"],
        "semantic_provider": selected, "semantic_provider_model": model}
    async def submit(db):
        result = await routes.submit_job(routes.JobSubmissionRequest(job_type="combined", metadata=metadata,
            latex_content=args["document"]["_source"], job_description="Python required"), Obj(client=Obj(host="127.0.0.1")), db, user_id)
        assert result.success
    database(submit)
    quota.assert_awaited_once()
    sent = dispatch.call_args.kwargs
    assert sent["user_api_key"] == "selected-user-key"
    assert sent["metadata"]["semantic_provider"] == selected and sent["metadata"]["semantic_provider_model"] == model
    assert "selected-user-key" not in json.dumps(sent["metadata"])


def test_real_native_candidate_recovery_is_fenced_to_provider_model_and_endpoint(admitted, priced):
    from app.services.resume_engine.service import run_semantic_optimization
    ledger, args, user_id, resume_id, job_id, redis = admitted
    async def remove_unpaid_fixture_seed(db):
        await db.delete(await db.get(ResumeOptimizationRun, job_id))
    database(remove_unpaid_fixture_seed)
    set_current_capability(job_id, ledger.owner, ledger.epoch)
    calls = []
    def transport(request):
        data = json.loads(json.loads(request.content)["messages"][0]["content"])["input"]
        calls.append(data)
        if "nodes" in data:
            node = data["nodes"][0]
            fact = next(fact for fact in data["facts"] if fact["node_id"] == node["node_id"])
            value = {"patches": [{"node_id": node["node_id"], "expected_node_revision": node["node_revision"],
                "text": "Developed Python services", "evidence_ids": [fact["fact_id"]], "requirement_ids": [],
                "reason": "Clearer action wording"}], "missing_evidence": []}
        else:
            value = {"verdicts": [{"patch_id": patch["patch_id"], "supported": True, "reason": "Same action and tool"} for patch in data["candidates"]]}
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=framed(native_events(json.dumps(value))))
    options = dict(job_id=job_id, source=args["document"]["_source"], job_description="Python required", user_id=user_id,
        metadata={"resume_id": resume_id, "optimization_effort": "quick", "expected_content_revision": 1,
            "expected_source_sha256": args["document"]["source_sha256"], "semantic_provider": "anthropic", "semantic_provider_model": "synthetic-claude"},
        api_key="synthetic-key", model=None, redis=redis, cancelled=lambda: False, publish=lambda *args: None,
        client_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(transport), **kwargs))
    first = run_semantic_optimization(**options)
    assert "Developed Python services" in first[0][0]
    assert run_semantic_optimization(**options)[0][0] == first[0][0] and len(calls) == 2
    async def inspect(db):
        row = await db.get(ResumeOptimizationRun, job_id)
        assert row.provider == "anthropic" and row.model == "synthetic-claude"
        assert row.context_payload["provider_endpoint_identity"] == "anthropic_messages_v1:https://api.anthropic.com/v1/messages"
    database(inspect)
    with pytest.raises(StageCheckpointError, match="context changed"):
        run_semantic_optimization(**{**options, "metadata": {**options["metadata"], "semantic_provider": "openrouter", "semantic_provider_model": "synthetic/model"}})
    assert len(calls) == 2
