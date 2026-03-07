"""
WebSocket endpoint protocol tests.

Uses Starlette's synchronous TestClient (websocket_connect support).
event_bus and Redis are mocked so no running Redis is required for
the protocol tests; the auth/Redis integration is covered by test_auth.py
and test_jobs.py which use the async ASGI transport.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.main import app


# ---------------------------------------------------------------------------
# Shared mock: patch event_bus and redis for all WebSocket tests
# ---------------------------------------------------------------------------

def _make_mock_redis() -> MagicMock:
    r = MagicMock()
    r.setex = AsyncMock(return_value=True)
    r.publish = AsyncMock(return_value=1)
    return r


@pytest.fixture(scope="class")
def ws_client():
    """
    Sync TestClient with event_bus and Redis mocked.

    We patch at the ws_routes module level so the WebSocket handler sees
    the mocks regardless of what the rest of the app has initialised.
    """
    mock_redis = _make_mock_redis()
    with (
        patch("app.api.ws_routes.event_bus") as mock_bus,
        patch("app.api.ws_routes.get_redis_client", new_callable=AsyncMock, return_value=mock_redis),
    ):
        mock_bus.subscribe = AsyncMock(return_value=0)
        mock_bus.disconnect = AsyncMock()
        mock_bus.disconnect_all = AsyncMock()

        # TestClient without context-manager avoids running the full lifespan
        # (which would reinitialise globals in a background thread loop).
        client = TestClient(app, raise_server_exceptions=True)
        yield client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebSocketProtocol:
    """WebSocket message protocol — no actual Redis / event delivery needed."""

    def test_connect_and_ping(self, ws_client: TestClient):
        """Server responds to ping with pong + server_time."""
        with ws_client.websocket_connect("/ws/jobs") as ws:
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()

        assert msg["type"] == "pong"
        assert "server_time" in msg
        assert isinstance(msg["server_time"], float)

    def test_subscribe_returns_subscribed(self, ws_client: TestClient):
        """Subscribe to a job_id returns subscribed confirmation."""
        job_id = str(uuid.uuid4())
        with ws_client.websocket_connect("/ws/jobs") as ws:
            ws.send_json({"type": "subscribe", "job_id": job_id})
            msg = ws.receive_json()

        assert msg["type"] == "subscribed"
        assert msg["job_id"] == job_id
        assert "replayed_count" in msg
        assert isinstance(msg["replayed_count"], int)

    def test_subscribe_missing_job_id_returns_error(self, ws_client: TestClient):
        """subscribe without job_id returns error code invalid_request."""
        with ws_client.websocket_connect("/ws/jobs") as ws:
            ws.send_json({"type": "subscribe"})
            msg = ws.receive_json()

        assert msg["type"] == "error"
        assert msg["code"] == "invalid_request"
        assert "job_id" in msg["message"].lower()

    def test_unknown_message_type_returns_error(self, ws_client: TestClient):
        """Unrecognised message type returns error code unknown_message_type."""
        with ws_client.websocket_connect("/ws/jobs") as ws:
            ws.send_json({"type": "totally_unknown"})
            msg = ws.receive_json()

        assert msg["type"] == "error"
        assert msg["code"] == "unknown_message_type"

    def test_cancel_missing_job_id_returns_error(self, ws_client: TestClient):
        """cancel without job_id returns error code invalid_request."""
        with ws_client.websocket_connect("/ws/jobs") as ws:
            ws.send_json({"type": "cancel"})
            msg = ws.receive_json()

        assert msg["type"] == "error"
        assert msg["code"] == "invalid_request"

    def test_cancel_with_job_id_succeeds(self, ws_client: TestClient):
        """cancel with a valid job_id sets the Redis flag; ping still works after."""
        job_id = str(uuid.uuid4())
        with ws_client.websocket_connect("/ws/jobs") as ws:
            ws.send_json({"type": "cancel", "job_id": job_id})
            # cancel has no response, ping to verify connection is still alive
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()

        assert msg["type"] == "pong"

    def test_unsubscribe_then_ping(self, ws_client: TestClient):
        """Unsubscribe from a job; connection remains open for further messages."""
        job_id = str(uuid.uuid4())
        with ws_client.websocket_connect("/ws/jobs") as ws:
            ws.send_json({"type": "subscribe", "job_id": job_id})
            ws.receive_json()  # subscribed ack

            ws.send_json({"type": "unsubscribe", "job_id": job_id})
            # unsubscribe has no response; verify connection still alive
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()

        assert msg["type"] == "pong"

    def test_multiple_subscriptions(self, ws_client: TestClient):
        """A single connection can subscribe to multiple job_ids."""
        job_ids = [str(uuid.uuid4()) for _ in range(3)]
        with ws_client.websocket_connect("/ws/jobs") as ws:
            for jid in job_ids:
                ws.send_json({"type": "subscribe", "job_id": jid})
                msg = ws.receive_json()
                assert msg["type"] == "subscribed"
                assert msg["job_id"] == jid

    def test_ping_pong_multiple_times(self, ws_client: TestClient):
        """Multiple sequential ping/pong within a single connection."""
        with ws_client.websocket_connect("/ws/jobs") as ws:
            for _ in range(3):
                ws.send_json({"type": "ping"})
                msg = ws.receive_json()
                assert msg["type"] == "pong"

    def test_subscribe_with_last_event_id(self, ws_client: TestClient):
        """subscribe with last_event_id triggers replay (replayed_count >= 0)."""
        job_id = str(uuid.uuid4())
        with ws_client.websocket_connect("/ws/jobs") as ws:
            ws.send_json({
                "type": "subscribe",
                "job_id": job_id,
                "last_event_id": "0-0",
            })
            msg = ws.receive_json()

        assert msg["type"] == "subscribed"
        assert msg["job_id"] == job_id
        assert msg["replayed_count"] >= 0

    def test_missing_type_field_returns_error(self, ws_client: TestClient):
        """Message without 'type' field should return unknown_message_type error."""
        with ws_client.websocket_connect("/ws/jobs") as ws:
            ws.send_json({"job_id": "some-id"})
            msg = ws.receive_json()

        assert msg["type"] == "error"
        assert msg["code"] == "unknown_message_type"

    def test_subscribe_with_extra_fields_succeeds(self, ws_client: TestClient):
        """Extra fields in a subscribe message are silently ignored."""
        job_id = str(uuid.uuid4())
        with ws_client.websocket_connect("/ws/jobs") as ws:
            ws.send_json({
                "type": "subscribe",
                "job_id": job_id,
                "unknown_field": "ignored_value",
            })
            msg = ws.receive_json()

        assert msg["type"] == "subscribed"
        assert msg["job_id"] == job_id

    def test_ping_with_extra_fields_still_responds_pong(self, ws_client: TestClient):
        """Extra fields on a ping are ignored; pong is still returned."""
        with ws_client.websocket_connect("/ws/jobs") as ws:
            ws.send_json({"type": "ping", "client_time": 1234567890.0})
            msg = ws.receive_json()

        assert msg["type"] == "pong"
        assert "server_time" in msg

    def test_subscribe_then_cancel_then_ping(self, ws_client: TestClient):
        """Sequence: subscribe → cancel same job → ping; connection stays live."""
        job_id = str(uuid.uuid4())
        with ws_client.websocket_connect("/ws/jobs") as ws:
            ws.send_json({"type": "subscribe", "job_id": job_id})
            ws.receive_json()  # subscribed ack

            ws.send_json({"type": "cancel", "job_id": job_id})
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()

        assert msg["type"] == "pong"
