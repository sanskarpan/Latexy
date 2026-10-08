"""Small provider adapter for the documented Dodo Payments REST API.

Business rules live in payment_service. This adapter owns the Dodo host,
Bearer authentication, and wire request/response details.
"""

import asyncio
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
    _RESOURCE_ID = r"[A-Za-z0-9_-]{1,128}"

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None, timeout: float = 15.0):
        self.api_key = api_key if api_key is not None else settings.dodo_api_key
        configured_url = base_url if base_url is not None else settings.dodo_api_base_url
        # Construct the network authority from literals, independently of
        # caller-supplied URL/path strings. Resource values can only affect path.
        self._origin = httpx.URL(
            "https://live.dodopayments.com"
            if settings.normalized_dodo_mode == "live"
            else "https://test.dodopayments.com"
        )
        expected_url = str(self._origin).rstrip("/")
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
        allowed_paths = {
            "GET": (
                rf"/(?:subscriptions|payments|checkouts|refunds)/{self._RESOURCE_ID}",
                rf"/payments/{self._RESOURCE_ID}/line-items",
                r"/discounts/code/(?!\.{1,2}$)(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2}){1,1024}",
            ),
            "POST": (r"/(?:checkouts|refunds)", rf"/customers/{self._RESOURCE_ID}/customer-portal/session"),
            "PATCH": (rf"/subscriptions/{self._RESOURCE_ID}",),
        }
        if not isinstance(path, str) or not any(
            re.fullmatch(pattern, path) for pattern in allowed_paths.get(method, ())
        ):
            raise ValueError("Unsupported Dodo request method or resource path")
        url = self._origin.copy_with(raw_path=path.encode("ascii"))
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            # HTTPX timeouts apply to individual I/O phases; a slow stream can
            # otherwise exceed the reconciliation lock's bounded read budget.
            async with asyncio.timeout(self.timeout):
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout, connect=5.0), follow_redirects=False,
                ) as client:
                    response = await client.request(method, url, headers=headers, json=json_body)
        except (httpx.RequestError, TimeoutError) as exc:
            raise DodoAPIError(503, "provider_unavailable") from exc
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = None
        if response.is_redirect:
            raise DodoAPIError(502, "unexpected_provider_redirect")
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

    async def get_refund(self, refund_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/refunds/{refund_id}")

    async def get_checkout_session(self, session_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/checkouts/{session_id}")

    async def get_payment_line_items(self, payment_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/payments/{payment_id}/line-items")

    async def get_discount_by_code(self, code: str) -> dict[str, Any]:
        return await self.request("GET", f"/discounts/code/{quote(code, safe='')}")

    async def create_customer_portal_session(self, customer_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/customers/{customer_id}/customer-portal/session", json_body={})

    async def create_refund(
        self, payment_id: str, amount: int | None = None, reason: str | None = None,
        *, item_id: str | None = None, tax_inclusive: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(payment_id, str) or not re.fullmatch(self._RESOURCE_ID, payment_id):
            raise ValueError("Invalid Dodo payment identifier")
        payload: dict[str, Any] = {"payment_id": payment_id}
        if amount is not None:
            # Dodo's current API refunds an individual product/addon item.
            # A top-level amount is not a supported field and could turn an
            # intended partial refund into the default full-payment refund.
            if type(amount) is not int or amount <= 0:
                raise ValueError("Partial refund requires a positive integer amount")
            if not isinstance(item_id, str) or not re.fullmatch(self._RESOURCE_ID, item_id):
                raise ValueError("Partial refund requires an explicit payment line-item identifier")
            if type(tax_inclusive) is not bool:
                raise ValueError("Refund tax inclusion must be a boolean")
            payload["items"] = [{"item_id": item_id, "amount": amount, "tax_inclusive": tax_inclusive}]
        elif item_id is not None:
            raise ValueError("Item refund requires an explicit amount")
        if reason:
            if not isinstance(reason, str) or len(reason) > 3000:
                raise ValueError("Refund reason exceeds the provider limit")
            payload["reason"] = reason
        return await self.request("POST", "/refunds", json_body=payload)
