from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from app.api.byok_routes import get_system_health


@pytest.mark.asyncio
async def test_system_health_uses_live_timestamp():
    with patch('app.api.byok_routes.multi_provider_service.get_provider_health', return_value={"openai": {"healthy": True}}):
        with patch('app.api.byok_routes.multi_provider_service.get_usage_stats', return_value={"openai": {"requests": 2, "cost": 1.5}}):
            payload = await get_system_health()

    assert payload["success"] is True
    assert payload["timestamp"] != "2024-01-01T00:00:00Z"
    parsed = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
