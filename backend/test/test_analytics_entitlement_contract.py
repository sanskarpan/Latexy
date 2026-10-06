"""Regression coverage for analytics feature gates."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.entitlement_service import entitlement_service


@pytest.mark.asyncio
async def test_timeseries_respects_analytics_feature_gate(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
):
    """The richer analytics endpoint must not bypass the dashboard entitlement."""

    await entitlement_service.set_matrix_cell("free", "analytics", False, db_session)
    try:
        response = await client.get("/analytics/me/timeseries?days=7", headers=auth_headers)
    finally:
        # Keep the shared entitlement blob at the all-enabled baseline for the
        # rest of the test suite.
        await entitlement_service.set_matrix_cell("free", "analytics", True, db_session)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "feature_disabled"
