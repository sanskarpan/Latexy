"""Dodo is Latexy's only active provider; production cannot use test checkout."""
from pathlib import Path

import pytest

from app.core.config import Settings


def _settings(monkeypatch, **overrides):
    monkeypatch.delenv("SKIP_ENV_VALIDATION", raising=False)
    values = dict(
        _env_file=None, ENVIRONMENT="production", BILLING_MODE="auto",
        DATABASE_URL="postgresql://fixture:fixture@localhost/fixture",
        BETTER_AUTH_SECRET="synthetic-auth-configuration-key-123456789",
        JWT_SECRET_KEY="synthetic-jwt-configuration-key-123456789",
        API_KEY_ENCRYPTION_KEY="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        DODO_MODE="test", DODO_TEST_API_KEY="", DODO_TEST_WEBHOOK_KEY="",
        DODO_LIVE_API_KEY="", DODO_LIVE_WEBHOOK_KEY="",
    )
    values.update(overrides)
    return Settings(**values)


def test_unconfigured_auto_billing_does_not_enable_checkout(monkeypatch):
    assert not _settings(monkeypatch).billing_credentials_configured()


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_production_like_test_credentials_are_rejected(monkeypatch, environment):
    with pytest.raises(ValueError, match="DODO_MODE=live"):
        _settings(monkeypatch, ENVIRONMENT=environment, DODO_TEST_API_KEY="fixture-test",
                  DODO_TEST_WEBHOOK_KEY="fixture-test-webhook")


def test_required_live_dodo_configuration_is_accepted(monkeypatch):
    configured = _settings(monkeypatch, BILLING_MODE="required", DODO_MODE="live",
                           DODO_LIVE_API_KEY="fixture-live", DODO_LIVE_WEBHOOK_KEY="fixture-live-webhook")
    assert configured.billing_credentials_configured()


def test_latexy_has_no_active_razorpay_provider_surface():
    root = Path(__file__).resolve().parents[2]
    for relative in (
        "backend/app/core/config.py", "backend/app/api/routes.py", "backend/app/services/dodo_provider.py",
        "backend/requirements.txt", "backend/requirements.lock", "backend/requirements-dev.lock",
        "frontend/src/app/billing/page.tsx", "frontend/src/lib/api-client.ts", "backend/.env.example",
        ".env.production.example", "docker-compose.prod.yml", "k8s/backend/deployment.yaml", "k8s/deploy.sh",
    ):
        assert "razorpay" not in (root / relative).read_text().lower(), relative
    assert not (root / "backend/app/services/legacy_razorpay_service.py").exists()
    assert not (root / "backend/app/services/billing_service.py").exists()
    assert "BILLING_PROVIDER" not in Settings.model_fields
