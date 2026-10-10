"""Real Redis stage fences with isolated job keys; never flush shared Redis."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from unittest.mock import MagicMock

import pytest
import redis
from celery.exceptions import Retry

from app.services.resume_engine.stages import OptimizationCheckpoint, StageCheckpointError, stage_fingerprint
from app.workers.job_lifecycle import clear_current_owner, lifecycle_key, set_current_capability

SOURCE = "\\documentclass{article}\n\\begin{document}content\\end{document}"
OUTPUT = (SOURCE, [{"section": "Experience", "change_type": "modified", "reason": "clarity"}], 50, .05)


@pytest.fixture
def owned_stage():
    client = redis.Redis.from_url(os.getenv("TEST_REDIS_URL", "redis://localhost:6380/15"),
                                 socket_connect_timeout=2, socket_timeout=2)
    client.ping()
    job_id = "test_stage_" + uuid.uuid4().hex
    client.hset(lifecycle_key(job_id), mapping={"status": "running", "owner": "owner-a", "epoch": 1,
                                              "lease_until": time.time() + 900})
    set_current_capability(job_id, "owner-a", 1)
    stage = OptimizationCheckpoint(client, job_id, stage_fingerprint({"source": SOURCE, "tenant": "owner-a"}))
    try:
        yield client, job_id, stage
    finally:
        clear_current_owner(job_id)
        keys = list(client.scan_iter(match=f"latexy:job:{job_id}:*"))
        if keys:
            client.delete(*keys)
        client.close()


def test_intent_is_ambiguous_until_completed_output_can_be_replayed(owned_stage):
    client, _, stage = owned_stage
    assert stage.restore() is None
    stage.begin()
    assert 0 < client.ttl(stage.key) <= 86400
    with pytest.raises(StageCheckpointError, match="ambiguous"):
        stage.restore()
    stage.complete(OUTPUT)
    assert stage.restore() == OUTPUT
    assert stage.restore() == OUTPUT


@pytest.mark.parametrize("change", ["source", "job_description", "model", "credential_hash", "provider_url", "compact_enabled", "schema"])
def test_context_fingerprint_changes_for_inputs_model_and_credential_scope(change):
    context = {"source": SOURCE, "job_description": "python", "model": "model-a", "provider_url": "native",
               "credential_hash": hashlib.sha256(b"tenant-a-key").hexdigest(), "compact_enabled": False,
               "schema": "optimization-stage-v1"}
    altered = {**context, change: "changed"}
    assert stage_fingerprint(context) != stage_fingerprint(altered)


def test_context_mismatch_never_returns_prior_paid_output(owned_stage):
    client, job_id, stage = owned_stage
    stage.begin()
    stage.complete(OUTPUT)
    with pytest.raises(StageCheckpointError, match="context changed"):
        OptimizationCheckpoint(client, job_id, "0" * 64).restore()


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(version=2),
    lambda value: value.update(version=True),
    lambda value: value.update(output_hash="0" * 64),
    lambda value: value["output"].__setitem__(0, ""),
    lambda value: value["output"].__setitem__(1, ["invalid change"]),
    lambda value: value["output"].__setitem__(1, [{"section": [], "change_type": "modified", "reason": "invalid"}]),
    lambda value: value["output"].__setitem__(2, True),
    lambda value: value["output"].__setitem__(2, -1),
    lambda value: value["output"].__setitem__(3, float("nan")),
    lambda value: value["output"].__setitem__(3, float("inf")),
])
def test_corrupt_typed_payloads_fail_closed_even_with_plausible_json(owned_stage, mutation):
    client, _, stage = owned_stage
    stage.begin()
    stage.complete(OUTPUT)
    value = json.loads(client.get(stage.key))
    mutation(value)
    client.set(stage.key, json.dumps(value))
    with pytest.raises(StageCheckpointError):
        stage.restore()


@pytest.mark.parametrize("fence", ["takeover", "epoch", "expired", "cancelled", "cancel-requested", "missing"])
def test_stale_cancelled_expired_and_missing_owners_cannot_replace_paid_stage(owned_stage, fence):
    client, job_id, stage = owned_stage
    stage.begin()
    before = client.get(stage.key)
    key = lifecycle_key(job_id)
    if fence == "takeover":
        client.hset(key, mapping={"owner": "owner-b", "epoch": 2})
    elif fence == "epoch":
        client.hset(key, "epoch", 2)
    elif fence == "expired":
        client.hset(key, "lease_until", time.time() - 10)
    elif fence == "cancelled":
        client.hset(key, "status", "cancelled")
    elif fence == "cancel-requested":
        client.hset(key, "cancel_requested", "1")
    else:
        client.delete(key)
    with pytest.raises(StageCheckpointError, match="ownership"):
        stage.complete(OUTPUT)
    assert client.get(stage.key) == before


def test_new_owned_attempt_reuses_previous_complete_stage(owned_stage):
    client, job_id, stage = owned_stage
    stage.begin()
    stage.complete(OUTPUT)
    client.hset(lifecycle_key(job_id), mapping={"owner": "owner-b", "epoch": 2})
    set_current_capability(job_id, "owner-b", 2)
    restored = OptimizationCheckpoint(client, job_id, stage.fingerprint)
    assert restored.restore() == OUTPUT


def test_atomic_stage_transitions_never_overwrite_ambiguous_or_completed_work(owned_stage):
    client, job_id, stage = owned_stage
    with pytest.raises(StageCheckpointError, match="transition"):
        stage.complete(OUTPUT)
    stage.begin()
    requesting = client.get(stage.key)
    with pytest.raises(StageCheckpointError, match="transition"):
        stage.begin()
    assert client.get(stage.key) == requesting
    stage.complete(OUTPUT)
    completed = client.get(stage.key)
    with pytest.raises(StageCheckpointError, match="transition"):
        stage.begin()
    with pytest.raises(StageCheckpointError, match="transition"):
        stage.complete((SOURCE + " changed", [], 80, .08))
    assert client.get(stage.key) == completed
    with pytest.raises(StageCheckpointError, match="transition"):
        OptimizationCheckpoint(client, job_id, "0" * 64).begin()
    assert client.get(stage.key) == completed


def test_expired_or_lost_requesting_marker_cannot_be_recreated_by_completion(owned_stage):
    client, _, stage = owned_stage
    stage.begin()
    client.delete(stage.key)
    with pytest.raises(StageCheckpointError, match="transition"):
        stage.complete(OUTPUT)
    assert not client.exists(stage.key)


def _mock_task(monkeypatch, owned_stage):
    import app.workers.orchestrator as worker
    client, job_id, _ = owned_stage
    # Model a not-yet-admitted first attempt; its admission creates epoch1.
    client.hset(lifecycle_key(job_id), "epoch", 0)
    set_current_capability(job_id, "owner-a", 0)
    def admit(_client, _job, owner, *_):
        epoch = client.hincrby(lifecycle_key(job_id), "epoch", 1)
        client.hset(lifecycle_key(job_id), mapping={"status": "running", "owner": owner,
                                                   "lease_until": time.time() + 900})
        set_current_capability(job_id, owner, epoch)
        return True
    monkeypatch.setattr(worker, "admit_worker", admit)
    monkeypatch.setattr(worker, "get_worker_redis", lambda: client)
    monkeypatch.setattr(worker, "is_cancelled", lambda _: False)
    monkeypatch.setattr(worker, "compute_queue_wait_seconds", lambda _: 0.)
    monkeypatch.setattr(worker, "consume_cold_start_seconds", lambda: 0.)
    monkeypatch.setattr(worker, "publish_event", MagicMock(return_value=True))
    monkeypatch.setattr(worker, "_publish_combined_terminal", MagicMock(return_value=True))
    monkeypatch.setattr(worker, "reconcile_compilation_record", MagicMock())
    monkeypatch.setattr(worker.settings, "RESUME_STAGE_CHECKPOINTS_ENABLED", True)
    monkeypatch.setattr(worker.settings, "RESUME_COMPACT_PATCHES_ENABLED", False)
    llm = MagicMock(return_value=OUTPUT)
    monkeypatch.setattr(worker, "_run_llm_stage", llm)
    return worker, job_id, llm


def test_later_render_retry_reuses_paid_llm_exactly_once(owned_stage, monkeypatch):
    worker, job_id, llm = _mock_task(monkeypatch, owned_stage)
    render = MagicMock(side_effect=[OSError("transient render failure"), (False, .02, "controlled compile failure", 0, b"")])
    monkeypatch.setattr(worker, "_run_latex_stage", render)
    def retry(**kwargs):
        raise Retry(exc=kwargs["exc"], when=0)
    monkeypatch.setattr(worker.optimize_and_compile_task, "retry", retry)
    task = worker.optimize_and_compile_task
    task.push_request(id="first-attempt", retries=0)
    try:
        with pytest.raises(Retry):
            task.run(SOURCE, job_id=job_id, user_api_key="tenant-key")
    finally:
        task.pop_request()
    task.push_request(id="second-attempt", retries=1)
    try:
        result = task.run(SOURCE, job_id=job_id, user_api_key="tenant-key")
    finally:
        task.pop_request()
    assert result["success"] is False
    llm.assert_called_once()
    assert render.call_count == 2
    assert any(call.args[2].get("optimization_checkpoint") is True for call in worker.publish_event.call_args_list)


@pytest.mark.parametrize("marker", ["missing", "requesting", "corrupt", "expired"])
def test_retry_never_repays_a_missing_ambiguous_or_corrupt_stage(owned_stage, monkeypatch, marker):
    client, _, stage = owned_stage
    worker, job_id, llm = _mock_task(monkeypatch, owned_stage)
    if marker in {"requesting", "expired"}:
        stage.begin()
    if marker == "expired":
        client.delete(stage.key)
    elif marker == "corrupt":
        client.set(stage.key, "{invalid JSON")
    task = worker.optimize_and_compile_task
    task.push_request(id="retry-attempt", retries=1)
    try:
        result = task.run(SOURCE, job_id=job_id, user_api_key="tenant-key")
    finally:
        task.pop_request()
    assert result["success"] is False
    llm.assert_not_called()


def test_ambiguous_provider_failure_is_terminal_and_never_repeats_paid_work(owned_stage, monkeypatch):
    client, _, stage = owned_stage
    worker, job_id, llm = _mock_task(monkeypatch, owned_stage)
    llm.side_effect = TimeoutError("provider may have billed request")
    retry = MagicMock(side_effect=AssertionError("ambiguous provider call must not retry"))
    monkeypatch.setattr(worker.optimize_and_compile_task, "retry", retry)
    task = worker.optimize_and_compile_task
    task.push_request(id="first-attempt", retries=0)
    try:
        first = task.run(SOURCE, job_id=job_id, user_api_key="tenant-key")
    finally:
        task.pop_request()
    assert first["success"] is False
    assert json.loads(client.get(stage.key))["status"] == "requesting"
    task.push_request(id="redelivery-attempt", retries=1)
    try:
        second = task.run(SOURCE, job_id=job_id, user_api_key="tenant-key")
    finally:
        task.pop_request()
    assert second["success"] is False
    llm.assert_called_once()
    retry.assert_not_called()


def test_missing_marker_on_duplicate_broker_delivery_cannot_buy_again(owned_stage, monkeypatch):
    client, job_id, _ = owned_stage
    worker, _, llm = _mock_task(monkeypatch, owned_stage)
    client.hset(lifecycle_key(job_id), "epoch", 1)
    task = worker.optimize_and_compile_task
    # Broker redelivery is not a Celery retry: retries still zero, but a new
    # lifecycle ownership claim increments epoch to2.
    task.push_request(id="duplicate-delivery", retries=0)
    try:
        result = task.run(SOURCE, job_id=job_id, user_api_key="tenant-key")
    finally:
        task.pop_request()
    assert result["success"] is False
    llm.assert_not_called()
