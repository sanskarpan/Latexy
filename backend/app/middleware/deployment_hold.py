"""Process-local HTTP and WebSocket deployment traffic hold."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_PROBE_PATHS = frozenset({"/health", "/readyz", "/livez", "/jobs/health"})
_TEMPLATE_CATALOG_PATHS = frozenset({"/templates", "/templates/", "/templates/categories"})
_TEMPLATE_ASSET_PATH = re.compile(
    r"^/templates/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/(?:thumbnail|pdf)$"
)
_HOLD_HEADER = (b"x-latexy-deployment-hold",)
_HOLD_BODY = json.dumps({"code": "deployment_traffic_held"}, separators=(",", ":")).encode()


def _is_allowlisted(scope: Scope) -> bool:
    method = scope.get("method", "GET").upper()
    path = scope.get("path", "")
    if path in _PROBE_PATHS:
        return method in {"GET", "HEAD"}
    if method == "GET" and path in _TEMPLATE_CATALOG_PATHS:
        return True
    if method == "GET" and _TEMPLATE_ASSET_PATH.fullmatch(path) is not None:
        return True
    if method == "GET" and path == "/config/entitlements":
        has_auth_material = any(
            name.lower() in {b"authorization", b"cookie", b"x-api-key"}
            for name, _value in scope.get("headers", [])
        )
        return (
            scope.get("query_string", b"") == b"include_quotas=false"
            and not has_auth_material
        )
    return False


class DeploymentTrafficHoldMiddleware:
    """Reject ordinary traffic while allowing health probes and template assets."""

    def __init__(self, app: ASGIApp, enabled: bool | None = None) -> None:
        self.app = app
        self.enabled = enabled

    def _enabled_for_scope(self, scope: Scope) -> bool:
        if self.enabled is not None:
            return self.enabled
        asgi_app = scope.get("app")
        state = getattr(asgi_app, "state", None)
        enabled = getattr(state, "deployment_traffic_held", None)
        if type(enabled) is not bool:
            raise RuntimeError("deployment traffic hold was not validated during startup")
        return enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]
        if scope_type == "lifespan":
            await self.app(scope, receive, send)
            return

        enabled = self._enabled_for_scope(scope)
        if scope_type == "websocket":
            if enabled:
                # A close before accept is an HTTP handshake denial (typically
                # 403), not a WebSocket close frame. Complete the handshake and
                # then send 1013 so clients receive the intended retry signal.
                await send({"type": "websocket.accept"})
                await send({"type": "websocket.close", "code": 1013})
                return
            await self.app(scope, receive, send)
            return

        if scope_type != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_hold_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers = [(key, value) for key, value in headers if key.lower() != _HOLD_HEADER[0]]
                headers.append((_HOLD_HEADER[0], b"true" if enabled else b"false"))
                if scope.get("path", "") in _PROBE_PATHS:
                    headers = [(key, value) for key, value in headers if key.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        if enabled and not _is_allowlisted(scope):
            await send_with_hold_header({
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_HOLD_BODY)).encode("ascii")),
                    (b"retry-after", b"30"),
                    (b"cache-control", b"no-store"),
                ],
            })
            await send_with_hold_header({"type": "http.response.body", "body": _HOLD_BODY})
            return

        await self.app(scope, receive, send_with_hold_header)
