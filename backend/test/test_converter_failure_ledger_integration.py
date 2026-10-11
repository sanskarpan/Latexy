"""Credential-free converter failures through real PostgreSQL and Redis ledgers.

Only the provider's HTTP transport and explicitly lost terminal delivery are
replaced. The OpenAI SDK, worker admission, durable finalization, Redis Lua
result/event publication, quota consumption, and refunds all execute normally.
Run against the standard isolated backend test DB and Redis DBs 15/14.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
import redis
from sqlalchemy import delete, select

from app.core.config import settings
from app.database.models import JobFinalization, User
from app.services.entitlement_service import QuotaTicket, entitlement_service
from app.workers import converter_worker, job_lifecycle
from app.workers.cleanup_worker import _reconcile_receipts_without_compilation_rows
from app.workers.finalization_arbiter import bounded_result_payload
from app.workers.quota_refund import refund_quota_once

PROVIDER_ORIGIN = "https://converter.provider.test/v1"
PROVIDER_MODEL = "synthetic-configured-model"
VALID_LATEX = r"\documentclass{article}\begin{document}Synthetic resume\end{document}"


@dataclass
class MeteredConversion:
    user_id: str
    job_id: str
    ticket: QuotaTicket
    queue: redis.Redis
    cache: redis.Redis
    sessions: object

    @property
    def counter_key(self):
        return f"latexy:quota:ai_assists:{self.user_id}:{self.ticket.period}"

    @property
    def receipt_key(self):
        return f"latexy:quota-refund-pending:{self.job_id}"

    @property
    def refund_key(self):
        return f"latexy:quota-refund:ai_assists:{self.job_id}"

    @property
    def terminal_key(self):
        return f"latexy:quota-terminal:{self.job_id}"

    async def run(self):
        # Production ownership/finalization bridges use asyncio.run(), so the
        # synchronous Celery body must run off pytest's already-running loop.
        return await asyncio.to_thread(
            lambda: converter_worker.convert_document_task.apply(
                kwargs={
                    "extracted_data": {"raw_text": "Synthetic resume"},
                    "source_format": "text",
                    "job_id": self.job_id,
                    "user_id": self.user_id,
                    "quota_refund": self.ticket.refund_payload(),
                },
                throw=True,
                # Application results use the real canonical Redis/DB stores;
                # the separate Celery eager-result cache is outside this test.
                ignore_result=True,
            ).get()
        )

    async def durable(self):
        # Read on a fresh session to prove the committed database winner,
        # rather than a previously cached ORM object or a mocked call.
        async with self.sessions() as session:
            return await session.scalar(select(JobFinalization).where(JobFinalization.job_id == self.job_id))

    def result(self):
        return json.loads(self.queue.get(f"latexy:job:{self.job_id}:result"))

    def events(self):
        return [json.loads(fields["payload"]) for _, fields in self.queue.xrange(f"latexy:stream:{self.job_id}")]


@pytest.fixture
async def metered_conversion(db_session_factory):
    user_id, job_id = str(uuid4()), str(uuid4())
    # conftest always forces these runtime URLs to its isolated selections,
    # including when TEST_REDIS_* was omitted and local defaults were chosen.
    queue = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    cache = redis.from_url(os.environ["REDIS_CACHE_URL"], decode_responses=True)
    queue.ping()
    cache.ping()
    try:
        # This is only an application-quota test identity. No payment account,
        # provider credential, subscription, or financial transaction exists.
        async with db_session_factory() as session:
            session.add(User(id=user_id, email=f"test_converter_{user_id}@example.com",
                             name="Synthetic converter test", subscription_plan="free",
                             subscription_status="active"))
            await session.flush()
            session.add(JobFinalization(job_id=job_id, user_id=user_id, job_type="document_conversion",
                                        state="pending", owner_epoch=0,
                                        expires_at=datetime.now(timezone.utc) + timedelta(days=40)))
            await session.commit()

        # Preserve another legitimate unit. Clamping at zero must not conceal
        # a double refund of this conversion's one unit.
        baseline = await entitlement_service.consume_quota("ai_assists", user_id=user_id, plan="free")
        assert baseline.allowed and baseline.used == 1
        ticket = await entitlement_service.consume_quota("ai_assists", user_id=user_id, plan="free", job_id=job_id)
        assert ticket.allowed and ticket.used == 2 and not ticket.unavailable
        case = MeteredConversion(user_id, job_id, ticket, queue, cache, db_session_factory)
        assert cache.get(case.counter_key) == "2"
        receipt = json.loads(cache.get(case.receipt_key))
        assert receipt["receipt_id"] == ticket.receipt_id
        assert receipt["user_id"] == user_id and receipt["dimension"] == "ai_assists"
        assert receipt["cost"] == 1 and receipt["created_at_clock"] == "redis"
        assert job_lifecycle.begin_dispatch(queue, job_id)
        assert job_lifecycle.mark_dispatch_accepted(queue, job_id)
        yield case
    finally:
        job_lifecycle.stop_lease_heartbeat(job_id)
        job_lifecycle.clear_current_owner(job_id)
        # Delete only keys and rows owned by this disposable fixture.
        for client in (queue, cache):
            keys = list(client.scan_iter(match=f"*{job_id}*"))
            keys += list(client.scan_iter(match=f"*{user_id}*"))
            if keys:
                client.delete(*keys)
            client.close()
        async with db_session_factory() as session:
            await session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


def provider_transport(monkeypatch, outcome):
    requests = []

    def handle(request):
        # Never open a socket or let a real provider request escape this seam.
        assert request.method == "POST"
        assert str(request.url) == PROVIDER_ORIGIN + "/chat/completions"
        assert request.headers["authorization"] == "Bearer synthetic-test-key"
        payload = json.loads(request.content)
        assert payload["model"] == PROVIDER_MODEL
        requests.append(payload)
        if outcome == "model_404":
            return httpx.Response(404, json={"error": {"message": "Synthetic model not found",
                                  "type": "invalid_request_error", "code": "model_not_found"}})
        if outcome == "timeout":
            raise httpx.ReadTimeout("Synthetic provider read timeout", request=request)
        return httpx.Response(200, json={
            "id": "synthetic-completion", "object": "chat.completion", "created": 0,
            "model": PROVIDER_MODEL,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": "invalid output" if outcome == "invalid_output" else VALID_LATEX}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        })

    transport = httpx.MockTransport(handle)
    # Intercept below OpenAI rather than replacing its constructor or create().
    # The SDK still serializes requests and maps HTTP 404/timeouts to its real
    # exceptions; max_retries=0 is verified by the observed request count.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", PROVIDER_ORIGIN)
    monkeypatch.setattr(settings, "OPENAI_MODEL", PROVIDER_MODEL)
    return requests


def terminal_delivery_fault(monkeypatch, terminal_type, fault):
    publish = converter_worker.publish_event

    def delivery(job_id, event_type, payload):
        if event_type == terminal_type:
            if fault == "raise":
                raise ConnectionError("Synthetic lost terminal delivery")
            if fault == "drop":
                return ""
        return publish(job_id, event_type, payload)

    monkeypatch.setattr(converter_worker, "publish_event", delivery)


@pytest.mark.parametrize("failure", ["model_404", "timeout", "invalid_output"])
@pytest.mark.parametrize("terminal_delivery", ["normal", "drop", "raise"])
async def test_provider_failure_durably_terminalizes_and_refunds_exactly_once(
    metered_conversion, monkeypatch, failure, terminal_delivery
):
    case = metered_conversion
    requests = provider_transport(monkeypatch, failure)
    terminal_delivery_fault(monkeypatch, "job.failed", terminal_delivery)
    result = await case.run()
    assert result["success"] is False and result["job_id"] == case.job_id
    assert len(requests) == 1

    durable = await case.durable()
    assert durable.state == durable.terminal_result == "failed"
    assert durable.user_id == case.user_id and durable.job_type == "document_conversion"
    assert durable.owner_epoch == 1 and durable.owner_token.startswith("converter-")
    assert durable.decided_at is not None
    assert durable.result_payload["success"] is False
    assert durable.result_payload["job_id"] == case.job_id
    assert durable.result_payload == bounded_result_payload(case.job_id, result)
    # The durable recovery contract deliberately strips arbitrary diagnostics.
    assert "error" not in durable.result_payload and durable.failure_code == "job_failed"
    assert case.result() == result
    assert case.queue.hget(job_lifecycle.lifecycle_key(case.job_id), "status") == "failed"
    assert case.queue.hget(job_lifecycle.lifecycle_key(case.job_id), "terminal_result") == (
        None if terminal_delivery == "normal" else "failed")
    assert case.queue.hget(job_lifecycle.lifecycle_key(case.job_id), "owner") is None
    assert case.cache.get(case.counter_key) == "1"
    assert case.cache.get(case.refund_key) == "1"
    assert case.cache.ttl(case.refund_key) > 39 * 86400
    assert case.cache.get(case.receipt_key) is None
    events = case.events()
    failed_events = [event for event in events if event["type"] == "job.failed"]
    assert len(failed_events) == (1 if terminal_delivery == "normal" else 0)
    if failed_events:
        assert failed_events[0]["error_code"] == ("invalid_latex" if failure == "invalid_output" else "llm_error")
        assert failed_events[0]["retryable"] is False
    assert not any(event["type"] in {"job.completed", "job.retrying"} for event in events)

    # A redelivered Celery/Modal invocation cannot regain the terminal owner,
    # contact the provider, change the committed winner, or refund again.
    assert (await case.run())["error"] == "Job ownership unavailable"
    assert len(requests) == 1
    assert case.result() == result and case.events() == events
    replayed = await case.durable()
    assert (replayed.owner_token, replayed.owner_epoch, replayed.decided_at, replayed.result_payload) == (
        durable.owner_token, durable.owner_epoch, durable.decided_at, durable.result_payload)
    assert not await asyncio.to_thread(refund_quota_once, case.job_id, case.ticket.refund_payload(),
                                       expected_dimension="ai_assists")
    # Also exercise the API enqueue-exception compensation path, which shares
    # the worker's job-scoped marker rather than decrementing independently.
    assert await entitlement_service.refund_quota(case.ticket)
    assert case.cache.get(case.counter_key) == "1"
    assert case.cache.get(case.refund_key) == "1"
    assert case.cache.get(case.receipt_key) is None


@pytest.mark.parametrize("terminal_delivery", ["drop", "raise"])
async def test_lost_success_completion_recovers_without_replay_or_refund(
    metered_conversion, monkeypatch, terminal_delivery
):
    case = metered_conversion
    requests = provider_transport(monkeypatch, "success")
    terminal_delivery_fault(monkeypatch, "job.completed", terminal_delivery)
    await case.run()
    durable = await case.durable()
    assert durable.state == durable.terminal_result == "completed"
    assert durable.owner_epoch == 1 and durable.decided_at is not None
    assert durable.result_payload["success"] is True
    assert durable.result_payload["latex_content"] == VALID_LATEX
    assert case.result()["success"] is True
    assert case.cache.get(case.counter_key) == "2"
    assert case.cache.get(case.refund_key) is None
    assert case.cache.get(case.receipt_key) is not None
    assert not any(event["type"] in {"job.failed", "job.completed", "job.retrying"} for event in case.events())
    assert (await case.run())["error"] == "Job ownership unavailable"
    assert len(requests) == 1

    # Lose the short-lived transport snapshots too. The real cleanup path must
    # restore the canonical durable success and clear its receipt, never turn
    # it into a failed job/refund or repeat the provider call.
    case.queue.delete(f"latexy:job:{case.job_id}:result", f"latexy:job:{case.job_id}:state")
    assert await asyncio.to_thread(_reconcile_receipts_without_compilation_rows, case.queue, case.cache) == 0
    assert case.result()["success"] is True
    assert case.result()["latex_content"] == VALID_LATEX
    assert case.queue.hget(job_lifecycle.lifecycle_key(case.job_id), "status") == "completed"
    assert sum(event["type"] == "job.completed" for event in case.events()) == 1
    assert case.cache.get(case.counter_key) == "2"
    assert case.cache.get(case.refund_key) is None
    assert case.cache.get(case.terminal_key) == "success"
    assert case.cache.get(case.receipt_key) is None
    assert len(requests) == 1
    assert await asyncio.to_thread(_reconcile_receipts_without_compilation_rows, case.queue, case.cache) == 0
    assert sum(event["type"] == "job.completed" for event in case.events()) == 1
    assert case.cache.get(case.counter_key) == "2"
    assert (await case.durable()).result_payload == durable.result_payload
