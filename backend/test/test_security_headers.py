"""
Tests for HTTP security headers, docs gating, and CORS origin filtering.
"""

import pytest
from httpx import AsyncClient

from app.core.config import settings


@pytest.mark.asyncio
class TestSecurityHeaders:
    async def test_security_headers_present_on_response(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    async def test_security_headers_do_not_break_json(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        # JSON body still parses fine with the extra headers.
        assert isinstance(resp.json(), dict)


class TestFramableAssetExemption:
    """Template/resume PDF + thumbnail endpoints must be embeddable in the app
    iframe, so they are exempt from X-Frame-Options: DENY (see #preview-fix)."""

    def test_framable_paths(self):
        from app.middleware.security_headers import _is_framable_asset

        assert _is_framable_asset("/templates/abc-123/pdf") is True
        assert _is_framable_asset("/templates/abc-123/thumbnail") is True
        assert _is_framable_asset("/download/job-1") is True

    def test_non_framable_paths_stay_denied(self):
        from app.middleware.security_headers import _is_framable_asset

        assert _is_framable_asset("/health") is False
        assert _is_framable_asset("/templates/") is False
        assert _is_framable_asset("/resumes/abc/pdf") is False  # not a template/download path
        assert _is_framable_asset("/admin/users") is False


class TestEffectiveCorsOrigins:
    def test_localhost_stripped_in_production(self, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(
            settings,
            "CORS_ORIGINS",
            ["http://localhost:5180", "http://127.0.0.1:3000", "https://latexy.com"],
        )
        origins = settings.effective_cors_origins()
        assert origins == ["https://latexy.com"]

    def test_localhost_kept_in_development(self, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        monkeypatch.setattr(
            settings,
            "CORS_ORIGINS",
            ["http://localhost:5180", "https://latexy.com"],
        )
        origins = settings.effective_cors_origins()
        assert "http://localhost:5180" in origins
        assert "https://latexy.com" in origins


class TestDocsGating:
    def test_docs_disabled_flag_when_production_like(self, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        assert settings.is_production_like() is True

    def test_docs_enabled_in_development(self, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        assert settings.is_production_like() is False
