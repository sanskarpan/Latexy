"""Focused HTTP contract tests for the Dodo provider adapter."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.dodo_provider import DodoAPIError, DodoProvider


@pytest.mark.parametrize(
    ("mode", "host"),
    [
        ("test", "https://test.dodopayments.com"),
        ("live", "https://live.dodopayments.com"),
    ],
)
@pytest.mark.asyncio
async def test_provider_uses_mode_host_bearer_auth_and_documented_wire_payloads(
    mode: str,
    host: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DODO_MODE", mode)
    monkeypatch.setattr(settings, "DODO_TEST_API_KEY", "test-adapter-key")
    monkeypatch.setattr(settings, "DODO_LIVE_API_KEY", "live-adapter-key")

    checkout_payload = {
        "product_cart": [{"product_id": "pdt_plan", "quantity": 1}],
        "discount_codes": ["WELCOME"],
        "metadata": {"latexy_intent_id": "intent-123"},
    }
    cancel_payload = {"cancel_at_next_billing_date": True}
    with respx.mock(assert_all_called=True) as router:
        checkout = router.post(f"{host}/checkouts").mock(
            return_value=httpx.Response(200, json={"session_id": "sess_123", "checkout_url": "https://checkout.test"})
        )
        cancel = router.patch(f"{host}/subscriptions/sub_123").mock(
            return_value=httpx.Response(200, json={"subscription_id": "sub_123"})
        )
        refund = router.post(f"{host}/refunds").mock(
            return_value=httpx.Response(200, json={"refund_id": "ref_123"})
        )
        portal = router.post(f"{host}/customers/cus_123/customer-portal/session").mock(
            return_value=httpx.Response(200, json={"link": "https://portal.test"})
        )
        provider = DodoProvider()

        await provider.create_checkout_session(checkout_payload)
        await provider.update_subscription("sub_123", cancel_payload)
        await provider.create_refund("pay_123", amount=1200, reason="customer_request")
        await provider.create_customer_portal_session("cus_123")

    expected_key = "live-adapter-key" if mode == "live" else "test-adapter-key"
    for route in (checkout, cancel, refund, portal):
        request = route.calls.last.request
        assert request.headers["Authorization"] == f"Bearer {expected_key}"
        assert request.headers["Content-Type"] == "application/json"

    assert [(route.calls.last.request.method, str(route.calls.last.request.url)) for route in (checkout, cancel, refund, portal)] == [
        ("POST", f"{host}/checkouts"),
        ("PATCH", f"{host}/subscriptions/sub_123"),
        ("POST", f"{host}/refunds"),
        ("POST", f"{host}/customers/cus_123/customer-portal/session"),
    ]
    assert checkout.calls.last.request.content == httpx.Request(
        "POST", f"{host}/checkouts", json=checkout_payload
    ).content
    assert cancel.calls.last.request.content == httpx.Request(
        "PATCH", f"{host}/subscriptions/sub_123", json=cancel_payload
    ).content
    assert refund.calls.last.request.content == httpx.Request(
        "POST",
        f"{host}/refunds",
        json={"payment_id": "pay_123", "amount": 1200, "reason": "customer_request"},
    ).content
    assert portal.calls.last.request.content == b"{}"


@pytest.mark.asyncio
async def test_refund_omits_optional_fields_when_not_provided() -> None:
    host = "https://test.dodopayments.com"
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{host}/refunds").mock(
            return_value=httpx.Response(200, json={"refund_id": "ref_123"})
        )
        provider = DodoProvider(api_key="test-adapter-key", base_url=host)

        await provider.create_refund("pay_123")

    assert route.calls.last.request.content == b'{"payment_id":"pay_123"}'


@pytest.mark.asyncio
async def test_discount_code_is_escaped_as_a_single_path_segment() -> None:
    host = "https://test.dodopayments.com"
    code = "SAVE/50?x=%"
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{host}/discounts/code/SAVE%2F50%3Fx%3D%25").mock(
            return_value=httpx.Response(200, json={"discount_id": "dsc_123", "code": code})
        )
        provider = DodoProvider(api_key="test-adapter-key", base_url=host)

        result = await provider.get_discount_by_code(code)

    assert result["discount_id"] == "dsc_123"
    assert str(route.calls.last.request.url) == f"{host}/discounts/code/SAVE%2F50%3Fx%3D%25"
    assert route.calls.last.request.url.raw_path == b"/discounts/code/SAVE%2F50%3Fx%3D%25"


@pytest.mark.parametrize(
    "transport_error",
    [
        httpx.ConnectError("unreachable"),
        httpx.ConnectTimeout("connect timed out"),
        httpx.ReadTimeout("timed out"),
        httpx.RemoteProtocolError("connection closed"),
    ],
)
@pytest.mark.asyncio
async def test_checkout_transport_error_is_not_retried(transport_error: httpx.RequestError) -> None:
    host = "https://test.dodopayments.com"
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{host}/checkouts").mock(side_effect=transport_error)
        provider = DodoProvider(api_key="test-adapter-key", base_url=host)

        with pytest.raises(DodoAPIError) as error:
            await provider.create_checkout_session({"product_cart": []})

    assert error.value.status_code == 503
    assert error.value.code == "provider_unavailable"
    assert route.call_count == 1
    assert "timed out" not in str(error.value)
    assert "connection closed" not in str(error.value)


@pytest.mark.asyncio
async def test_non_object_success_response_is_rejected_without_echoing_body() -> None:
    host = "https://test.dodopayments.com"
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{host}/checkouts").mock(return_value=httpx.Response(200, json=["provider", "secret"]))
        provider = DodoProvider(api_key="test-adapter-key", base_url=host)

        with pytest.raises(DodoAPIError) as error:
            await provider.create_checkout_session({"product_cart": []})

    assert error.value.status_code == 502
    assert error.value.code == "invalid_provider_response"
    assert "secret" not in str(error.value)


@pytest.mark.asyncio
async def test_malformed_success_json_is_rejected() -> None:
    host = "https://test.dodopayments.com"
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{host}/checkouts").mock(return_value=httpx.Response(200, content=b"not-json"))
        provider = DodoProvider(api_key="test-adapter-key", base_url=host)

        with pytest.raises(DodoAPIError) as error:
            await provider.create_checkout_session({"product_cart": []})

    assert error.value.status_code == 502
    assert error.value.code == "invalid_provider_response"
    assert "not-json" not in str(error.value)


@pytest.mark.asyncio
async def test_provider_error_body_is_not_echoed() -> None:
    host = "https://test.dodopayments.com"
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{host}/checkouts").mock(
            return_value=httpx.Response(
                401,
                json={
                    "error": {
                        "code": "invalid_api_key",
                        "message": "Authorization failed for Bearer do-not-leak-this",
                    }
                },
            )
        )
        provider = DodoProvider(api_key="test-adapter-key", base_url=host)

        with pytest.raises(DodoAPIError) as error:
            await provider.create_checkout_session({"product_cart": []})

    assert error.value.status_code == 401
    assert error.value.code == "invalid_api_key"
    assert "do-not-leak-this" not in str(error.value)
    assert "Authorization failed" not in str(error.value)


@pytest.mark.asyncio
async def test_untrusted_provider_error_code_is_sanitized() -> None:
    host = "https://test.dodopayments.com"
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{host}/checkouts").mock(
            return_value=httpx.Response(
                500,
                json={"error": {"code": "Bearer key=do-not-leak-this; body=private", "message": "failure"}},
            )
        )
        provider = DodoProvider(api_key="test-adapter-key", base_url=host)

        with pytest.raises(DodoAPIError) as error:
            await provider.create_checkout_session({"product_cart": []})

    assert error.value.status_code == 500
    assert error.value.code == "provider_error"
    assert "do-not-leak-this" not in str(error.value)
    assert "private" not in str(error.value)


@pytest.mark.asyncio
async def test_top_level_provider_error_code_is_preserved_without_message() -> None:
    host = "https://test.dodopayments.com"
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{host}/refunds").mock(
            return_value=httpx.Response(
                409,
                json={
                    "code": "INSUFFICIENT_WALLET_FUNDS",
                    "message": "Insufficient funds in wallet",
                },
            )
        )
        provider = DodoProvider(api_key="test-adapter-key", base_url=host)

        with pytest.raises(DodoAPIError) as error:
            await provider.create_refund("pay_123", amount=1200)

    assert error.value.status_code == 409
    assert error.value.code == "INSUFFICIENT_WALLET_FUNDS"
    assert "Insufficient funds in wallet" not in str(error.value)
    assert "wallet" not in str(error.value)
