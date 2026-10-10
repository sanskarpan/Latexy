"""Dodo-only checkout and existing-subscription servicing route contracts."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import routes


@pytest.mark.parametrize("available", [True, False])
async def test_plans_identify_dodo_even_when_new_sales_are_unavailable(monkeypatch, available):
    monkeypatch.setattr(routes.feature_flag_service, "get_flag", AsyncMock(return_value=available))
    monkeypatch.setattr(routes.payment_service, "get_subscription_plans", AsyncMock(return_value={}))
    monkeypatch.setattr(routes.payment_service, "get_status", Mock(return_value={
        "feature_enabled": available, "available": available,
        "mode": "enabled" if available else "disabled", "message": "Billing status",
    }))
    result = await routes.get_subscription_plans(db=object())
    assert result.model_dump()["billing"]["provider"] == "dodo"
    assert result.billing.available is available


@pytest.mark.parametrize(("legacy", "explicit"), [
    ("/subscription/create", "/billing/dodo/subscription/create"),
    ("/subscription/cancel", "/billing/dodo/subscription/cancel"),
    ("/subscription/reconcile", "/billing/dodo/subscription/reconcile"),
    ("/subscription/student/verify/{token}", "/billing/dodo/subscription/student/verify/{token}"),
])
def test_dodo_only_rollout_routes_preserve_the_same_handler_and_auth_dependencies(legacy, explicit):
    endpoints = {route.path: route for route in routes.router.routes if hasattr(route, "path")}
    original, dodo = endpoints[legacy], endpoints[explicit]
    assert dodo.endpoint is original.endpoint
    assert dodo.methods == original.methods
    assert [dependency.call for dependency in dodo.dependant.dependencies] == [
        dependency.call for dependency in original.dependant.dependencies
    ]


def _request(payload: bytes, headers: dict[str, str]) -> Request:
    request = Request({
        "type": "http", "method": "POST", "path": "/billing/webhook",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
    })
    request._body = payload
    return request


async def test_create_response_remains_hosted_checkout_with_server_identity(monkeypatch):
    create = AsyncMock(return_value={
        "success": True, "checkout_type": "hosted", "subscription_id": "sub_test",
        "checkout_session_id": "checkout_test", "short_url": "https://checkout.example.test/owned",
    })
    monkeypatch.setattr(routes.payment_service, "create_subscription", create)
    monkeypatch.setattr(routes.feature_flag_service, "get_flag", AsyncMock(return_value=True))
    row = SimpleNamespace(email="owner@example.com", name="Owner")
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(one_or_none=Mock(return_value=row))))
    response = await routes.create_subscription(routes.CreateSubscriptionRequest(
        planId="basic", customerEmail="untrusted@example.com", customerName="Untrusted",
    ), db=db, user_id="owner-id")
    assert response.model_dump() == {
        "success": True, "subscriptionId": "sub_test", "checkoutSessionId": "checkout_test",
        "shortUrl": "https://checkout.example.test/owned", "checkoutType": "hosted",
        "verificationRequired": False, "verificationPreviewUrl": None,
        "coupon": None, "error": None, "message": None,
    }
    assert create.await_args.kwargs["customer_email"] == "owner@example.com"
    assert create.await_args.kwargs["customer_name"] == "Owner"


async def test_existing_dodo_cancellation_ignores_new_sales_feature_flag(monkeypatch):
    flag = AsyncMock(return_value=False)
    cancel = AsyncMock(return_value={"success": True, "message": "Cancellation scheduled"})
    monkeypatch.setattr(routes.feature_flag_service, "get_flag", flag)
    monkeypatch.setattr(routes.payment_service, "cancel_subscription", cancel)
    db = object()
    result = await routes.cancel_subscription(db=db, user_id="dodo-owner")
    assert result.success
    cancel.assert_awaited_once_with(db, "dodo-owner")
    flag.assert_not_awaited()


async def test_existing_dodo_recovery_ignores_new_sales_feature_flag(monkeypatch):
    flag = AsyncMock(return_value=False)
    recover = AsyncMock(return_value={"success": False, "status": "pending", "message": "Not confirmed yet"})
    monkeypatch.setattr(routes.feature_flag_service, "get_flag", flag)
    monkeypatch.setattr(routes.payment_service, "reconcile_checkout", recover)
    db = object()
    result = await routes.reconcile_subscription(db=db, user_id="dodo-owner")
    assert result.status == "pending"
    recover.assert_awaited_once_with(db, "dodo-owner")
    flag.assert_not_awaited()


async def test_webhook_forwards_raw_body_and_standard_signature_headers_to_dodo(monkeypatch):
    handle = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(routes.payment_service, "handle_webhook", handle)
    body = b'{ "data": {"amount": 123} }\n'
    headers = {"webhook-id": "evt_test", "webhook-timestamp": "123", "webhook-signature": "v1,test"}
    db = object()
    assert await routes.dodo_webhook(_request(body, headers), db=db) == {"status": "ok"}
    handle.assert_awaited_once_with(db, body, headers)


@pytest.mark.parametrize(("result", "status"), [
    ({"success": False, "error": "Invalid webhook signature"}, 400),
    ({"success": False, "retryable": True, "error": "Transient database failure"}, 500),
])
async def test_webhook_rejection_and_retryability_are_preserved(monkeypatch, result, status):
    monkeypatch.setattr(routes.payment_service, "handle_webhook", AsyncMock(return_value=result))
    with pytest.raises(HTTPException) as error:
        await routes.dodo_webhook(_request(b"{}", {}), db=object())
    assert error.value.status_code == status
    assert error.value.detail == "Webhook processing failed"


def test_both_webhook_urls_use_the_same_dodo_handler():
    handlers = {route.path: route.endpoint for route in routes.router.routes if hasattr(route, "path")}
    assert handlers["/billing/webhook"] is routes.dodo_webhook
    assert handlers["/billing/dodo/webhook"] is routes.dodo_webhook
