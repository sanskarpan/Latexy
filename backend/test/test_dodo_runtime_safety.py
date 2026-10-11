"""Dodo-only runtime environment and existing-subscription servicing guards."""

from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.services.payment_service import PaymentService


def test_runtime_blocks_production_dodo_test_checkout_and_servicing(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "DODO_MODE", "test")
    monkeypatch.setattr(settings, "DODO_TEST_API_KEY", "test-key")
    monkeypatch.setattr(settings, "DODO_TEST_WEBHOOK_KEY", "test-webhook-key")
    monkeypatch.setattr(settings, "BILLING_MODE", "auto")
    service = PaymentService()
    assert service.get_status()["reason"] == "production_test_billing_blocked"
    assert not service.is_available()
    assert not service.is_service_available()



def test_existing_dodo_servicing_survives_new_checkout_disable(monkeypatch):
    monkeypatch.setattr(settings, "BILLING_MODE", "disabled")
    monkeypatch.setattr(settings, "DODO_TEST_API_KEY", "test-key")
    service = PaymentService()
    assert not service.is_available()
    assert service.is_service_available()



@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["production", "staging"])
async def test_dodo_test_webhook_cannot_grant_production_access(monkeypatch, environment):
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    monkeypatch.setattr(settings, "DODO_MODE", "test")
    monkeypatch.setattr(settings, "BILLING_MODE", "disabled")
    service = PaymentService()
    verify = MagicMock(return_value=True)
    monkeypatch.setattr(service, "_verify_webhook_signature", verify)
    result = await service.handle_webhook(None, b'{"type":"payment.succeeded"}', {})
    assert result["success"] is False
    assert "live mode" in result["error"]
    verify.assert_not_called()

