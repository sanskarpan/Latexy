"""
Unit tests for app.workers.event_publisher.

All tests inject a MagicMock in place of the module-level _worker_redis so
no live Redis is required.  The autouse fixture resets _worker_redis to None
before each test and restores it afterward, ensuring full isolation.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

import app.workers.event_publisher as ep
from app.workers.event_publisher import (
    get_worker_redis,
    initialize_worker_redis,
    is_cancelled,
    publish_event,
    publish_job_result,
    store_job_meta,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_worker_redis():
    """Isolate _worker_redis between tests."""
    original = ep._worker_redis
    ep._worker_redis = None
    yield
    ep._worker_redis = original


@pytest.fixture
def mock_r():
    """Inject a pre-configured MagicMock as the worker Redis client."""
    m = MagicMock()
    m.incr.return_value = 1
    m.xadd.return_value = "1700000000000-0"
    m.exists.return_value = 0
    ep._worker_redis = m
    return m


@pytest.fixture
def job_id():
    return str(uuid.uuid4())


# ── get_worker_redis ───────────────────────────────────────────────────────────

class TestGetWorkerRedis:

    def test_raises_before_init(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            get_worker_redis()

    def test_raises_mentions_signal(self):
        with pytest.raises(RuntimeError, match="worker_process_init"):
            get_worker_redis()

    def test_returns_client_after_inject(self, mock_r):
        assert get_worker_redis() is mock_r

    def test_returns_same_instance_on_repeated_calls(self, mock_r):
        assert get_worker_redis() is get_worker_redis()


# ── initialize_worker_redis ────────────────────────────────────────────────────

class TestInitializeWorkerRedis:

    def test_creates_redis_client(self):
        with patch("redis.from_url") as mock_from_url:
            mock_client = MagicMock()
            mock_from_url.return_value = mock_client
            initialize_worker_redis("redis://localhost:6379/0")
            assert ep._worker_redis is mock_client

    def test_calls_ping_on_init(self):
        with patch("redis.from_url") as mock_from_url:
            mock_client = MagicMock()
            mock_from_url.return_value = mock_client
            initialize_worker_redis("redis://localhost:6379/0")
            mock_client.ping.assert_called_once()

    def test_ping_failure_propagates(self):
        with patch("redis.from_url") as mock_from_url:
            mock_client = MagicMock()
            mock_client.ping.side_effect = ConnectionError("refused")
            mock_from_url.return_value = mock_client
            with pytest.raises(ConnectionError):
                initialize_worker_redis("redis://localhost:6379/0")

    def test_passes_decode_responses_true(self):
        with patch("redis.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()
            initialize_worker_redis("redis://localhost:6379/0")
            _, kwargs = mock_from_url.call_args
            assert kwargs.get("decode_responses") is True

    def test_max_connections_is_small(self):
        with patch("redis.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()
            initialize_worker_redis("redis://localhost:6379/0")
            _, kwargs = mock_from_url.call_args
            assert kwargs.get("max_connections", 999) <= 10

    def test_retry_on_timeout_enabled(self):
        with patch("redis.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()
            initialize_worker_redis("redis://localhost:6379/0")
            _, kwargs = mock_from_url.call_args
            assert kwargs.get("retry_on_timeout") is True

    def test_url_passed_through(self):
        url = "redis://myhost:6380/3"
        with patch("redis.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()
            initialize_worker_redis(url)
            pos_args, _ = mock_from_url.call_args
            assert pos_args[0] == url

    def test_replaces_existing_client(self):
        first = MagicMock()
        second = MagicMock()
        with patch("redis.from_url", side_effect=[first, second]):
            initialize_worker_redis("redis://localhost:6379/0")
            initialize_worker_redis("redis://localhost:6379/0")
        assert ep._worker_redis is second


# ── publish_event ──────────────────────────────────────────────────────────────

class TestPublishEvent:

    def test_returns_stream_entry_id(self, mock_r, job_id):
        entry_id = publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        assert entry_id == "1700000000000-0"

    def test_calls_xadd_once(self, mock_r, job_id):
        publish_event(job_id, "job.progress", {"percent": 50, "stage": "llm", "message": "hi"})
        mock_r.xadd.assert_called_once()

    def test_xadd_stream_key_format(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        stream_key = mock_r.xadd.call_args[0][0]
        assert stream_key == f"latexy:stream:{job_id}"

    def test_xadd_fields_contain_type(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        fields = mock_r.xadd.call_args[0][1]
        assert fields["type"] == "job.started"

    def test_xadd_payload_is_valid_json(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        fields = mock_r.xadd.call_args[0][1]
        payload = json.loads(fields["payload"])
        assert isinstance(payload, dict)

    def test_xadd_payload_contains_job_id(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        fields = mock_r.xadd.call_args[0][1]
        payload = json.loads(fields["payload"])
        assert payload["job_id"] == job_id

    def test_xadd_payload_contains_event_type(self, mock_r, job_id):
        publish_event(job_id, "log.line", {"source": "pdflatex", "line": "ok", "is_error": False})
        fields = mock_r.xadd.call_args[0][1]
        payload = json.loads(fields["payload"])
        assert payload["type"] == "log.line"

    def test_xadd_payload_extra_fields_merged(self, mock_r, job_id):
        publish_event(job_id, "log.line", {"source": "pdflatex", "line": "ERROR line", "is_error": True})
        fields = mock_r.xadd.call_args[0][1]
        payload = json.loads(fields["payload"])
        assert payload["source"] == "pdflatex"
        assert payload["is_error"] is True

    def test_pubsub_publish_called_once(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        mock_r.publish.assert_called_once()

    def test_pubsub_channel_format(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        channel = mock_r.publish.call_args[0][0]
        assert channel == f"latexy:events:{job_id}"

    def test_pubsub_message_is_valid_json(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        raw_msg = mock_r.publish.call_args[0][1]
        msg = json.loads(raw_msg)
        assert msg["type"] == "event"
        assert "event" in msg

    def test_pubsub_message_includes_stream_id(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        raw_msg = mock_r.publish.call_args[0][1]
        msg = json.loads(raw_msg)
        assert "stream_id" in msg
        assert msg["stream_id"] == "1700000000000-0"

    def test_state_setex_called(self, mock_r, job_id):
        publish_event(job_id, "job.progress", {"percent": 30, "stage": "llm", "message": "x"})
        assert mock_r.setex.called

    def test_state_key_format(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        state_key = mock_r.setex.call_args[0][0]
        assert state_key == f"latexy:job:{job_id}:state"

    def test_state_status_processing_for_job_started(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        state = json.loads(mock_r.setex.call_args[0][2])
        assert state["status"] == "processing"

    def test_state_status_completed_for_job_completed(self, mock_r, job_id):
        publish_event(job_id, "job.completed", {
            "pdf_job_id": job_id, "ats_score": 80.0, "ats_details": {},
            "changes_made": [], "compilation_time": 1.0,
            "optimization_time": 2.0, "tokens_used": 100,
        })
        state = json.loads(mock_r.setex.call_args[0][2])
        assert state["status"] == "completed"

    def test_state_status_failed_for_job_failed(self, mock_r, job_id):
        publish_event(job_id, "job.failed", {
            "stage": "llm", "error_code": "internal",
            "error_message": "err", "retryable": False,
        })
        state = json.loads(mock_r.setex.call_args[0][2])
        assert state["status"] == "failed"

    def test_state_status_cancelled_for_job_cancelled(self, mock_r, job_id):
        publish_event(job_id, "job.cancelled", {})
        state = json.loads(mock_r.setex.call_args[0][2])
        assert state["status"] == "cancelled"

    def test_state_percent_from_payload(self, mock_r, job_id):
        publish_event(job_id, "job.progress", {"percent": 45, "stage": "llm", "message": "hi"})
        state = json.loads(mock_r.setex.call_args[0][2])
        assert state["percent"] == 45

    def test_state_stage_from_payload(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "latex_compilation"})
        state = json.loads(mock_r.setex.call_args[0][2])
        assert state["stage"] == "latex_compilation"

    def test_sequence_uses_incr(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        mock_r.incr.assert_called_with(f"latexy:job:{job_id}:seq")

    def test_event_has_valid_uuid_event_id(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        fields = mock_r.xadd.call_args[0][1]
        uuid.UUID(fields["event_id"])  # raises if invalid UUID

    def test_event_ids_are_unique_across_calls(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        publish_event(job_id, "job.progress", {"percent": 50, "stage": "llm", "message": "x"})
        calls = mock_r.xadd.call_args_list
        ids = [c[0][1]["event_id"] for c in calls]
        assert ids[0] != ids[1]

    def test_stream_ttl_set(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        expire_keys = [c[0][0] for c in mock_r.expire.call_args_list]
        assert f"latexy:stream:{job_id}" in expire_keys

    def test_sequence_key_ttl_set(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        expire_keys = [c[0][0] for c in mock_r.expire.call_args_list]
        assert f"latexy:job:{job_id}:seq" in expire_keys

    def test_multiple_events_monotonic_sequence(self, mock_r, job_id):
        mock_r.incr.side_effect = [1, 2, 3]
        for i in range(3):
            publish_event(job_id, "job.progress", {"percent": i * 10, "stage": "llm", "message": "x"})
        seqs = [
            json.loads(c[0][1]["payload"])["sequence"]
            for c in mock_r.xadd.call_args_list
        ]
        assert seqs == [1, 2, 3]

    def test_sequence_included_in_stream_fields(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        fields = mock_r.xadd.call_args[0][1]
        assert "sequence" in fields

    def test_maxlen_limit_set_on_xadd(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        kwargs = mock_r.xadd.call_args[1]
        assert "maxlen" in kwargs
        assert kwargs["maxlen"] == 10000

    def test_state_ttl_is_24h(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"})
        ttl = mock_r.setex.call_args[0][1]
        assert ttl == 86400

    def test_custom_ttl_propagates_to_state(self, mock_r, job_id):
        publish_event(job_id, "job.started", {"worker_id": "w1", "stage": "llm"}, ttl=3600)
        ttl = mock_r.setex.call_args[0][1]
        assert ttl == 3600


# ── publish_job_result ─────────────────────────────────────────────────────────

class TestPublishJobResult:

    def test_calls_setex(self, mock_r, job_id):
        publish_job_result(job_id, {"success": True, "ats_score": 80.0})
        mock_r.setex.assert_called_once()

    def test_key_format(self, mock_r, job_id):
        publish_job_result(job_id, {"success": True})
        key = mock_r.setex.call_args[0][0]
        assert key == f"latexy:job:{job_id}:result"

    def test_stores_valid_json(self, mock_r, job_id):
        result = {"success": True, "ats_score": 85.5, "tokens_used": 300}
        publish_job_result(job_id, result)
        stored = mock_r.setex.call_args[0][2]
        parsed = json.loads(stored)
        assert parsed["success"] is True
        assert parsed["ats_score"] == 85.5

    def test_default_ttl_is_24h(self, mock_r, job_id):
        publish_job_result(job_id, {"success": True})
        ttl = mock_r.setex.call_args[0][1]
        assert ttl == 86400

    def test_custom_ttl_accepted(self, mock_r, job_id):
        publish_job_result(job_id, {"success": True}, ttl=3600)
        ttl = mock_r.setex.call_args[0][1]
        assert ttl == 3600

    def test_nested_result_serialized_correctly(self, mock_r, job_id):
        result = {
            "success": True,
            "ats_details": {"category_scores": {"formatting": 80}},
        }
        publish_job_result(job_id, result)
        stored = mock_r.setex.call_args[0][2]
        parsed = json.loads(stored)
        assert parsed["ats_details"]["category_scores"]["formatting"] == 80


# ── store_job_meta ─────────────────────────────────────────────────────────────

class TestStoreJobMeta:

    def test_setex_called(self, mock_r, job_id):
        store_job_meta(job_id, user_id=None, job_type="ats_scoring")
        mock_r.setex.assert_called_once()

    def test_key_format(self, mock_r, job_id):
        store_job_meta(job_id, user_id=None, job_type="ats_scoring")
        key = mock_r.setex.call_args[0][0]
        assert key == f"latexy:job:{job_id}:meta"

    def test_meta_contains_job_id(self, mock_r, job_id):
        store_job_meta(job_id, user_id=None, job_type="combined")
        meta = json.loads(mock_r.setex.call_args[0][2])
        assert meta["job_id"] == job_id

    def test_meta_contains_job_type(self, mock_r, job_id):
        store_job_meta(job_id, user_id=None, job_type="latex_compilation")
        meta = json.loads(mock_r.setex.call_args[0][2])
        assert meta["job_type"] == "latex_compilation"

    def test_meta_contains_submitted_at_float(self, mock_r, job_id):
        store_job_meta(job_id, user_id=None, job_type="combined")
        meta = json.loads(mock_r.setex.call_args[0][2])
        assert isinstance(meta["submitted_at"], float)
        assert meta["submitted_at"] > 0

    def test_with_user_id_adds_to_zset(self, mock_r, job_id):
        user_id = str(uuid.uuid4())
        store_job_meta(job_id, user_id=user_id, job_type="combined")
        mock_r.zadd.assert_called_once()

    def test_zset_key_format(self, mock_r, job_id):
        user_id = str(uuid.uuid4())
        store_job_meta(job_id, user_id=user_id, job_type="combined")
        zset_key = mock_r.zadd.call_args[0][0]
        assert zset_key == f"latexy:user:{user_id}:jobs"

    def test_zset_mapping_contains_job_id(self, mock_r, job_id):
        user_id = str(uuid.uuid4())
        store_job_meta(job_id, user_id=user_id, job_type="combined")
        mapping = mock_r.zadd.call_args[0][1]
        assert job_id in mapping

    def test_without_user_id_no_zset(self, mock_r, job_id):
        store_job_meta(job_id, user_id=None, job_type="latex_compilation")
        mock_r.zadd.assert_not_called()

    def test_user_zset_ttl_set(self, mock_r, job_id):
        user_id = str(uuid.uuid4())
        store_job_meta(job_id, user_id=user_id, job_type="combined")
        expire_keys = [c[0][0] for c in mock_r.expire.call_args_list]
        assert f"latexy:user:{user_id}:jobs" in expire_keys

    def test_user_zset_ttl_is_30_days(self, mock_r, job_id):
        user_id = str(uuid.uuid4())
        store_job_meta(job_id, user_id=user_id, job_type="combined")
        # Find the expire call for the ZSET key
        for c in mock_r.expire.call_args_list:
            if c[0][0] == f"latexy:user:{user_id}:jobs":
                assert c[0][1] == 30 * 86400
                return
        pytest.fail("No expire call found for user ZSET key")

    def test_meta_user_id_stored(self, mock_r, job_id):
        user_id = str(uuid.uuid4())
        store_job_meta(job_id, user_id=user_id, job_type="combined")
        meta = json.loads(mock_r.setex.call_args[0][2])
        assert meta["user_id"] == user_id

    def test_meta_user_id_none_when_no_user(self, mock_r, job_id):
        store_job_meta(job_id, user_id=None, job_type="latex_compilation")
        meta = json.loads(mock_r.setex.call_args[0][2])
        assert meta["user_id"] is None


# ── is_cancelled ───────────────────────────────────────────────────────────────

class TestIsCancelled:

    def test_returns_false_if_no_key(self, mock_r, job_id):
        mock_r.exists.return_value = 0
        assert is_cancelled(job_id) is False

    def test_returns_true_if_key_exists(self, mock_r, job_id):
        mock_r.exists.return_value = 1
        assert is_cancelled(job_id) is True

    def test_checks_correct_key(self, mock_r, job_id):
        mock_r.exists.return_value = 0
        is_cancelled(job_id)
        mock_r.exists.assert_called_once_with(f"latexy:job:{job_id}:cancel")

    def test_nonzero_value_is_truthy(self, mock_r, job_id):
        mock_r.exists.return_value = 5
        assert is_cancelled(job_id) is True

    def test_different_jobs_independent(self, mock_r):
        job_a = str(uuid.uuid4())
        job_b = str(uuid.uuid4())
        mock_r.exists.side_effect = lambda key: 1 if job_a in key else 0
        assert is_cancelled(job_a) is True
        assert is_cancelled(job_b) is False
