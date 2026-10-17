from __future__ import annotations

import ast
import asyncio
import json
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.deployment_hold import DEPLOYMENT_TRAFFIC_HOLD_ENV, deployment_traffic_held
from app.middleware.deployment_hold import DeploymentTrafficHoldMiddleware


class FakeASGIApp:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, scope, receive, send) -> None:
        self.calls.append(scope)
        if scope["type"] == "http":
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({"type": "http.response.body", "body": b"ok"})
        elif scope["type"] == "websocket":
            await send({"type": "websocket.accept"})
        elif scope["type"] == "lifespan":
            await send({"type": "lifespan.startup.complete"})


def invoke_http(
    middleware,
    method: str,
    path: str,
    app_state=None,
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> list[dict]:
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query_string,
        "headers": headers or [],
    }
    if app_state is not None:
        scope["app"] = SimpleNamespace(state=app_state)
    asyncio.run(middleware(scope, receive, send))
    return messages


def invoke_websocket(middleware) -> list[dict]:
    messages: list[dict] = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        messages.append(message)

    asyncio.run(middleware({"type": "websocket", "path": "/ws/jobs"}, receive, send))
    return messages


class DeploymentTrafficHoldTests(unittest.TestCase):
    def test_flag_parser_accepts_only_true_false_and_empty(self) -> None:
        self.assertFalse(deployment_traffic_held({}))
        self.assertTrue(deployment_traffic_held({"DEPLOY_TARGET": "modal"}))
        self.assertTrue(deployment_traffic_held({"MODAL_ENVIRONMENT": "main"}))
        self.assertTrue(deployment_traffic_held({}, source_deployment=True))
        for value in ("", "  ", "false", " FALSE "):
            with self.subTest(value=value):
                self.assertFalse(deployment_traffic_held({DEPLOYMENT_TRAFFIC_HOLD_ENV: value}))
        for value in ("true", " TRUE "):
            with self.subTest(value=value):
                self.assertTrue(deployment_traffic_held({DEPLOYMENT_TRAFFIC_HOLD_ENV: value}))
        for value in ("yes", "0", "enabled", "true-ish"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                deployment_traffic_held({DEPLOYMENT_TRAFFIC_HOLD_ENV: value})

    def test_source_deployments_distinguish_local_development_from_approved_production_release(self) -> None:
        self.assertFalse(deployment_traffic_held({
            DEPLOYMENT_TRAFFIC_HOLD_ENV: "false",
            "MODAL_ENVIRONMENT": "dev",
        }, source_deployment=True))
        with self.assertRaisesRegex(ValueError, "MODAL_ENVIRONMENT=dev"):
            deployment_traffic_held({DEPLOYMENT_TRAFFIC_HOLD_ENV: "false"}, source_deployment=True)
        with self.assertRaisesRegex(ValueError, "exact approved DEPLOY_SHA"):
            deployment_traffic_held({
                DEPLOYMENT_TRAFFIC_HOLD_ENV: "false",
                "MODAL_ENVIRONMENT": "main",
                "DEPLOY_SHA": "a" * 40,
                "MODAL_TRAFFIC_RELEASE_APPROVED_SHA": "b" * 40,
            }, source_deployment=True)
        with self.assertRaisesRegex(ValueError, "exact approved DEPLOY_SHA"):
            deployment_traffic_held({
                DEPLOYMENT_TRAFFIC_HOLD_ENV: "false",
                "MODAL_ENVIRONMENT": "main",
                "DEPLOY_SHA": "not-a-sha",
                "MODAL_TRAFFIC_RELEASE_APPROVED_SHA": "not-a-sha",
            }, source_deployment=True)
        self.assertFalse(deployment_traffic_held({
            DEPLOYMENT_TRAFFIC_HOLD_ENV: "false",
            "MODAL_ENVIRONMENT": "main",
            "DEPLOY_SHA": "a" * 40,
            "MODAL_TRAFFIC_RELEASE_APPROVED_SHA": "a" * 40,
        }, source_deployment=True))

    def test_held_requests_return_503_for_every_method_with_retry_and_no_store(self) -> None:
        for method in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
            with self.subTest(method=method):
                downstream = FakeASGIApp()
                messages = invoke_http(DeploymentTrafficHoldMiddleware(downstream, enabled=True), method, "/api/private")
                start = messages[0]
                headers = dict(start["headers"])
                self.assertEqual(start["status"], 503)
                self.assertEqual(headers[b"retry-after"], b"30")
                self.assertEqual(headers[b"cache-control"], b"no-store")
                self.assertEqual(headers[b"x-latexy-deployment-hold"], b"true")
                body = json.loads(messages[1]["body"])
                self.assertEqual(body["code"], "deployment_traffic_held")
                self.assertEqual(downstream.calls, [])

    def test_only_exact_health_probes_allow_get_and_head(self) -> None:
        for path in ("/health", "/readyz", "/livez", "/jobs/health"):
            for method in ("GET", "HEAD"):
                with self.subTest(path=path, method=method):
                    downstream = FakeASGIApp()
                    messages = invoke_http(DeploymentTrafficHoldMiddleware(downstream, enabled=True), method, path)
                    self.assertEqual(messages[0]["status"], 200)
                    headers = dict(messages[0]["headers"])
                    self.assertEqual(headers[b"x-latexy-deployment-hold"], b"true")
                    self.assertEqual(headers[b"cache-control"], b"no-store")
                    self.assertEqual(len(downstream.calls), 1)

    def test_probe_variants_and_private_routes_remain_held(self) -> None:
        denied = (
            ("POST", "/health"),
            ("GET", "/health/"),
            ("GET", "/jobs/health/"),
            ("GET", "/docs"),
            ("GET", "/openapi.json"),
            ("GET", "/api/public/payments"),
            ("GET", "/admin"),
            ("GET", "/downloads/private"),
        )
        for method, path in denied:
            with self.subTest(method=method, path=path):
                downstream = FakeASGIApp()
                messages = invoke_http(DeploymentTrafficHoldMiddleware(downstream, enabled=True), method, path)
                self.assertEqual(messages[0]["status"], 503)
                self.assertEqual(downstream.calls, [])

    def test_template_catalog_and_uuid_assets_allow_get_only(self) -> None:
        template_id = "123e4567-e89b-12d3-a456-426614174000"
        allowed = ("/templates", "/templates/", "/templates/categories",
                   f"/templates/{template_id}/thumbnail", f"/templates/{template_id}/pdf")
        for path in allowed:
            with self.subTest(path=path):
                downstream = FakeASGIApp()
                messages = invoke_http(DeploymentTrafficHoldMiddleware(downstream, enabled=True), "GET", path)
                self.assertEqual(messages[0]["status"], 200)
                self.assertEqual(dict(messages[0]["headers"])[b"x-latexy-deployment-hold"], b"true")
                self.assertEqual(len(downstream.calls), 1)
        denied = (
            ("HEAD", "/templates/"),
            ("POST", "/templates/"),
            ("GET", f"/templates/{template_id}"),
            ("GET", "/templates/not-a-uuid/pdf"),
            ("HEAD", f"/templates/{template_id}/pdf"),
        )
        for method, path in denied:
            with self.subTest(method=method, path=path):
                downstream = FakeASGIApp()
                messages = invoke_http(DeploymentTrafficHoldMiddleware(downstream, enabled=True), method, path)
                self.assertEqual(messages[0]["status"], 503)
                self.assertEqual(downstream.calls, [])

    def test_anonymous_entitlements_probe_requires_exact_query_and_no_auth_material(self) -> None:
        downstream = FakeASGIApp()
        messages = invoke_http(
            DeploymentTrafficHoldMiddleware(downstream, enabled=True),
            "GET",
            "/config/entitlements",
            query_string=b"include_quotas=false",
        )
        self.assertEqual(messages[0]["status"], 200)
        self.assertEqual(dict(messages[0]["headers"])[b"x-latexy-deployment-hold"], b"true")
        self.assertEqual(len(downstream.calls), 1)

        denied_cases = [
            ("GET", b"", []),
            ("GET", b"include_quotas=true", []),
            ("GET", b"include_quotas=false&extra=1", []),
            ("GET", b"extra=1&include_quotas=false", []),
            ("GET", b"include_quotas=false&include_quotas=false", []),
            ("HEAD", b"include_quotas=false", []),
            ("POST", b"include_quotas=false", []),
            ("GET", b"include_quotas=false", [(b"Authorization", b"Bearer synthetic")]),
            ("GET", b"include_quotas=false", [(b"cOoKiE", b"session=synthetic")]),
            ("GET", b"include_quotas=false", [(b"X-API-Key", b"synthetic")]),
        ]
        for method, query, request_headers in denied_cases:
            with self.subTest(method=method, query=query, headers=request_headers):
                downstream = FakeASGIApp()
                messages = invoke_http(
                    DeploymentTrafficHoldMiddleware(downstream, enabled=True),
                    method,
                    "/config/entitlements",
                    query_string=query,
                    headers=request_headers,
                )
                self.assertEqual(messages[0]["status"], 503)
                self.assertEqual(dict(messages[0]["headers"])[b"x-latexy-deployment-hold"], b"true")
                self.assertEqual(downstream.calls, [])

    def test_disabled_http_flow_is_unchanged_and_carries_false_header(self) -> None:
        downstream = FakeASGIApp()
        messages = invoke_http(DeploymentTrafficHoldMiddleware(downstream, enabled=False), "POST", "/api/private")
        self.assertEqual(messages[0]["status"], 200)
        self.assertEqual(dict(messages[0]["headers"])[b"x-latexy-deployment-hold"], b"false")
        self.assertEqual(len(downstream.calls), 1)

    def test_default_middleware_reads_preinitialized_app_state_without_lifespan(self) -> None:
        for enabled, expected_status, expected_header in (
            (True, 503, b"true"),
            (False, 200, b"false"),
        ):
            with self.subTest(enabled=enabled):
                downstream = FakeASGIApp()
                messages = invoke_http(
                    DeploymentTrafficHoldMiddleware(downstream),
                    "GET",
                    "/api/private",
                    SimpleNamespace(deployment_traffic_held=enabled),
                )
                self.assertEqual(messages[0]["status"], expected_status)
                self.assertEqual(dict(messages[0]["headers"])[b"x-latexy-deployment-hold"], expected_header)
                self.assertEqual(len(downstream.calls), int(not enabled))

    def test_minimal_fastapi_route_works_without_lifespan_when_state_is_initialized(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        app = FastAPI()
        app.state.deployment_traffic_held = False
        app.add_middleware(DeploymentTrafficHoldMiddleware)

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        async def request_without_lifespan():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                return await client.get("/health")

        response = asyncio.run(request_without_lifespan())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-latexy-deployment-hold"], "false")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_hold_with_cors_and_verified_tenant_cors_never_reaches_business_handler(self) -> None:
        from fastapi import FastAPI, Request
        from fastapi.middleware.cors import CORSMiddleware
        from httpx import ASGITransport, AsyncClient
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import Response

        # Execute the unchanged production middleware class definition without
        # importing its module (which loads app settings and service clients).
        source_path = Path(__file__).resolve().parents[1] / "app" / "middleware" / "tenant_middleware.py"
        source_tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        class_node = next(
            node for node in source_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "VerifiedTenantCORSMiddleware"
        )
        isolated_middleware = types.ModuleType("isolated_verified_tenant_cors")
        isolated_middleware.__dict__.update({
            "BaseHTTPMiddleware": BaseHTTPMiddleware,
            "Request": Request,
            "Response": Response,
        })

        async def no_tenant(_hostname: str):
            return None

        isolated_middleware.resolve_tenant_origin_hostname = no_tenant
        isolated_tree = ast.Module(body=[class_node], type_ignores=[])
        exec(compile(isolated_tree, str(source_path), "exec"), isolated_middleware.__dict__)
        VerifiedTenantCORSMiddleware = isolated_middleware.VerifiedTenantCORSMiddleware

        business_calls = {"held": 0, "released": 0}
        resolver_calls: list[str] = []

        def make_app(held: bool, key: str):
            app = FastAPI()
            app.state.deployment_traffic_held = held

            @app.get("/health")
            async def health():
                return {"status": "ok"}

            @app.post("/private")
            async def private_action():
                business_calls[key] += 1
                return {"changed": True}

            app.add_middleware(DeploymentTrafficHoldMiddleware)
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["http://allowed.example"],
                allow_credentials=True,
                allow_methods=["GET", "HEAD", "POST", "OPTIONS"],
                allow_headers=["Content-Type"],
                expose_headers=["Retry-After", "X-Latexy-Deployment-Hold"],
            )
            app.add_middleware(VerifiedTenantCORSMiddleware)
            return app

        async def verified_tenant(_hostname: str):
            resolver_calls.append(_hostname)
            if _hostname == "verified.example":
                return {"id": "synthetic-tenant", "slug": "synthetic"}
            return None

        async def send_requests(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                static_held = await client.post("/private", headers={"Origin": "http://allowed.example"})
                tenant_held = await client.post("/private", headers={"Origin": "https://verified.example"})
                unknown_held = await client.post("/private", headers={"Origin": "https://unknown.example"})
                preflight = await client.options(
                    "/private",
                    headers={
                        "Origin": "http://allowed.example",
                        "Access-Control-Request-Method": "POST",
                    },
                )
                after_preflight = await client.post("/private", headers={"Origin": "http://allowed.example"})
                health = await client.get("/health", headers={"Origin": "https://verified.example"})
            return static_held, tenant_held, unknown_held, preflight, after_preflight, health

        held_app = make_app(True, "held")
        with patch.object(isolated_middleware, "resolve_tenant_origin_hostname", new=verified_tenant):
            static_held, tenant_held, unknown_held, preflight, after_preflight, health = asyncio.run(
                send_requests(held_app)
            )
        self.assertEqual(static_held.status_code, 503)
        self.assertEqual(static_held.headers["access-control-allow-origin"], "http://allowed.example")
        self.assertEqual(static_held.headers["x-latexy-deployment-hold"], "true")
        self.assertEqual(tenant_held.status_code, 503)
        self.assertEqual(tenant_held.headers["access-control-allow-origin"], "https://verified.example")
        self.assertEqual(tenant_held.headers["x-latexy-deployment-hold"], "true")
        self.assertEqual(unknown_held.status_code, 503)
        self.assertNotIn("access-control-allow-origin", unknown_held.headers)
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(after_preflight.status_code, 503)
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.headers["x-latexy-deployment-hold"], "true")
        self.assertEqual(health.headers["cache-control"], "no-store")
        self.assertEqual(business_calls["held"], 0)
        self.assertEqual(resolver_calls, ["verified.example", "unknown.example", "verified.example"])

        released_app = make_app(False, "released")
        with patch.object(isolated_middleware, "resolve_tenant_origin_hostname", new=verified_tenant):
            async def send_released():
                async with AsyncClient(transport=ASGITransport(app=released_app), base_url="http://test") as client:
                    return await client.post("/private", headers={"Origin": "http://allowed.example"})

            released = asyncio.run(send_released())
        self.assertEqual(released.status_code, 200)
        self.assertEqual(released.headers["access-control-allow-origin"], "http://allowed.example")
        self.assertEqual(released.headers["x-latexy-deployment-hold"], "false")
        self.assertEqual(business_calls["released"], 1)

    def test_missing_startup_state_fails_closed(self) -> None:
        downstream = FakeASGIApp()
        middleware = DeploymentTrafficHoldMiddleware(downstream)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(_message):
            return None

        with self.assertRaisesRegex(RuntimeError, "not validated during startup"):
            asyncio.run(middleware(
                {"type": "http", "method": "GET", "path": "/health", "app": SimpleNamespace(state=SimpleNamespace())},
                receive,
                send,
            ))
        self.assertEqual(downstream.calls, [])

    def test_middleware_overwrites_downstream_hold_header(self) -> None:
        class ForgingASGIApp:
            async def __call__(self, _scope, _receive, send):
                await send({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"x-latexy-deployment-hold", b"false")],
                })
                await send({"type": "http.response.body", "body": b"ok"})

        messages = invoke_http(
            DeploymentTrafficHoldMiddleware(ForgingASGIApp()),
            "GET",
            "/health",
            SimpleNamespace(deployment_traffic_held=True),
        )
        headers = dict(messages[0]["headers"])
        self.assertEqual(headers[b"x-latexy-deployment-hold"], b"true")
        self.assertEqual(headers[b"cache-control"], b"no-store")

    def test_held_websocket_accepts_then_closes_without_calling_application(self) -> None:
        downstream = FakeASGIApp()
        messages = invoke_websocket(DeploymentTrafficHoldMiddleware(downstream, enabled=True))
        self.assertEqual(messages, [
            {"type": "websocket.accept"},
            {"type": "websocket.close", "code": 1013},
        ])
        self.assertEqual(downstream.calls, [])

    def test_held_websocket_client_completes_handshake_then_observes_1013_close(self) -> None:
        from fastapi import FastAPI, WebSocket
        from starlette.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        app = FastAPI()
        app.state.deployment_traffic_held = True
        business_calls: list[str] = []

        @app.websocket("/ws/jobs")
        async def websocket_route(websocket: WebSocket) -> None:
            business_calls.append("entered")
            await websocket.accept()

        app.add_middleware(DeploymentTrafficHoldMiddleware)
        with TestClient(app) as client:
            with self.assertRaises(WebSocketDisconnect) as disconnect:
                with client.websocket_connect("/ws/jobs") as websocket:
                    websocket.receive_text()

        self.assertEqual(disconnect.exception.code, 1013)
        self.assertEqual(business_calls, [])

    def test_released_websocket_is_forwarded_to_the_application(self) -> None:
        downstream = FakeASGIApp()
        messages = invoke_websocket(DeploymentTrafficHoldMiddleware(downstream, enabled=False))
        self.assertEqual(messages, [{"type": "websocket.accept"}])
        self.assertEqual(len(downstream.calls), 1)

    def test_lifespan_is_always_passed_through(self) -> None:
        downstream = FakeASGIApp()
        messages: list[dict] = []

        async def receive():
            return {"type": "lifespan.startup"}

        async def send(message):
            messages.append(message)

        asyncio.run(DeploymentTrafficHoldMiddleware(downstream, enabled=True)(
            {"type": "lifespan"}, receive, send
        ))
        self.assertEqual(messages, [{"type": "lifespan.startup.complete"}])
        self.assertEqual(len(downstream.calls), 1)


if __name__ == "__main__":
    unittest.main()
