"""Regression tests for bounded jobs-WebSocket message decoding."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.ws_routes import (
    _MAX_JOB_WS_MESSAGE_BYTES,
    _decode_job_ws_message,
    _WebSocketMessageTooLarge,
    jobs_websocket,
)


def test_jobs_websocket_rejects_oversized_frame_before_json_parse():
    payload = {"type": "ping", "padding": "x" * _MAX_JOB_WS_MESSAGE_BYTES}

    with pytest.raises(_WebSocketMessageTooLarge):
        _decode_job_ws_message({"type": "websocket.receive", "text": str(payload)})


def test_jobs_websocket_accepts_bounded_json_object():
    assert _decode_job_ws_message({"type": "websocket.receive", "text": '{"type":"ping"}'}) == {
        "type": "ping"
    }


def test_jobs_websocket_rejects_non_object_json():
    with pytest.raises(ValueError, match="object"):
        _decode_job_ws_message({"type": "websocket.receive", "text": "[]"})


@pytest.mark.asyncio
async def test_jobs_websocket_rejects_invalid_ticket_before_upgrade():
    websocket = MagicMock()
    websocket.query_params = {"ticket": "invalid"}
    websocket.accept = AsyncMock()
    websocket.close = AsyncMock()

    with patch("app.api.ws_routes._consume_ws_ticket", new=AsyncMock(return_value=None)):
        await jobs_websocket(websocket)

    websocket.accept.assert_not_awaited()
    websocket.close.assert_awaited_once_with(code=4001, reason="Invalid or expired WebSocket ticket")
