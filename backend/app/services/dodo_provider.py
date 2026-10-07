"""Small provider adapter for the documented Dodo Payments REST API.

Business rules live in payment_service. This adapter owns the Dodo host,
Bearer authentication, and wire request/response details.
"""

import re
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from ..core.config import settings


class DodoAPIError(RuntimeError):
    def __init__(self, status_code: int, code: str = "provider_error"):
        self.status_code = status_code
        self.code = code
        super().__init__(f"Dodo request failed ({status_code}, {code})")


class DodoProvider:
    provider_name = "dodo"

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None, timeout: float = 15.0):
        self.api_key = api_key if api_key is not None else settings.dodo_api_key
        configured_url = base_url if base_url is not None else settings.dodo_api_base_url
        expected_url = settings.dodo_api_base_url
        parsed_url = urlsplit(configured_url)
        parsed_expected = urlsplit(expected_url)
        if (
            parsed_url.scheme != "https"
            or parsed_url.netloc != parsed_expected.netloc
            or parsed_url.path not in {"", "/"}
            or parsed_url.query
            or parsed_url.fragment
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.port is not None
        ):
            # Never send the provider credential to a caller-selected host.
            # The active DODO_MODE also remains the authority for test/live.
            raise ValueError("Dodo API base URL must match the active mode's official HTTPS origin")
        self.base_url = expected_url
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise DodoAPIError(503, "billing_unconfigured")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=5.0)) as client:
                response = await client.request(method, f"{self.base_url}{path}", headers=headers, json=json_body)
        except httpx.RequestError as exc:
            raise DodoAPIError(503, "provider_unavailable") from exc
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = None
        if response.is_error:
            error = body.get("error") if isinstance(body, dict) else None
            code = error.get("code") if isinstance(error, dict) else body.get("code") if isinstance(body, dict) else None
            # Keep provider descriptions, customer data and arbitrary response
            # content out of application logs and client-visible exceptions.
            safe_code = code if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_]{1,64}", code) else "provider_error"
            raise DodoAPIError(response.status_code, safe_code)
        if not isinstance(body, dict):
            raise DodoAPIError(502, "invalid_provider_response")
        return body

    async def create_checkout_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Checkout-session creation is intentionally not automatically retried:
        # Dodo documents no idempotency key for this endpoint, and a timeout can
        # leave an unknown session at the provider. Local intent metadata lets
        # the signed webhook safely reconcile a session if it completed.
        return await self.request("POST", "/checkouts", json_body=payload)

    async def update_subscription(self, subscription_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PATCH", f"/subscriptions/{subscription_id}", json_body=payload)

    async def get_subscription(self, subscription_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/subscriptions/{subscription_id}")

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/payments/{payment_id}")

    async def get_discount_by_code(self, code: str) -> dict[str, Any]:
        return await self.request("GET", f"/discounts/code/{quote(code, safe='')}")

    async def create_customer_portal_session(self, customer_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/customers/{customer_id}/customer-portal/session", json_body={})

    async def create_refund(self, payment_id: str, amount: int | None = None, reason: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"payment_id": payment_id}
        if amount is not None:
            payload["amount"] = amount
        if reason:
            payload["reason"] = reason
        return await self.request("POST", "/refunds", json_body=payload)
