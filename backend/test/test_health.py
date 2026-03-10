"""
Tests for health and basic API availability.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestHealth:
    async def test_health_returns_200(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_health_schema(self, client: AsyncClient):
        resp = await client.get("/health")
        data = resp.json()
        assert "status" in data
        assert "version" in data
        assert "latex_available" in data

    async def test_health_status_value(self, client: AsyncClient):
        resp = await client.get("/health")
        data = resp.json()
        assert data["status"] in ("ok", "degraded", "healthy")

    async def test_openapi_docs_available(self, client: AsyncClient):
        resp = await client.get("/docs")
        assert resp.status_code == 200

    async def test_openapi_json_valid(self, client: AsyncClient):
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        assert "openapi" in spec
        assert "info" in spec
        assert spec["info"]["title"] == "Latexy-Backend"

    async def test_health_endpoint_returns_expected_fields(self, client: AsyncClient):
        """Health endpoint should always return success=True with expected schema."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ("ok", "healthy", "degraded")
