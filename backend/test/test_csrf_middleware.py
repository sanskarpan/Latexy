from unittest.mock import AsyncMock

from fastapi import Request
from starlette.responses import PlainTextResponse

from app.middleware.csrf import SessionCookieCSRFMiddleware


def _request(*, method: str, origin: str | None = None, cookie: str | None = None) -> Request:
    headers = [(b"host", b"api.example")]
    if origin:
        headers.append((b"origin", origin.encode()))
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    return Request(
        {
            "type": "http",
            "method": method,
            "scheme": "https",
            "server": ("api.example", 443),
            "path": "/mutate",
            "raw_path": b"/mutate",
            "query_string": b"",
            "headers": headers,
        }
    )


async def _next(_request: Request):
    return PlainTextResponse("ok")


async def test_cookie_mutation_rejects_cross_origin():
    middleware = SessionCookieCSRFMiddleware(_next)
    response = await middleware.dispatch(
        _request(
            method="POST",
            origin="https://attacker.example",
            cookie="better-auth.session_token=session",
        ),
        _next,
    )
    assert response.status_code == 403


async def test_cookie_mutation_requires_origin_signal():
    middleware = SessionCookieCSRFMiddleware(_next)
    response = await middleware.dispatch(
        _request(
            method="POST",
            cookie="better-auth.session_token=session",
        ),
        _next,
    )
    assert response.status_code == 403


async def test_cookie_mutation_accepts_configured_origin():
    middleware = SessionCookieCSRFMiddleware(_next)
    response = await middleware.dispatch(
        _request(
            method="PATCH",
            origin="http://localhost:5180",
            cookie="__Secure-better-auth.session_token=session",
        ),
        _next,
    )
    assert response.status_code == 200


async def test_cookie_mutation_accepts_same_origin_referer_when_origin_absent():
    middleware = SessionCookieCSRFMiddleware(_next)
    request = _request(
        method="POST",
        cookie="better-auth.session_token=session",
    )
    request.scope["headers"].append((b"referer", b"http://localhost:5180/settings"))
    response = await middleware.dispatch(request, _next)
    assert response.status_code == 200


async def test_bearer_mutation_does_not_require_origin():
    middleware = SessionCookieCSRFMiddleware(_next)
    request = _request(
        method="DELETE",
        cookie="better-auth.session_token=session",
    )
    request.scope["headers"].append((b"authorization", b"Bearer token"))
    response = await middleware.dispatch(request, _next)
    assert response.status_code == 200


async def test_basic_authorization_does_not_bypass_cookie_protection():
    middleware = SessionCookieCSRFMiddleware(_next)
    request = _request(
        method="POST",
        origin="https://attacker.example",
        cookie="better-auth.session_token=session",
    )
    request.scope["headers"].append((b"authorization", b"Basic dXNlcjpwYXNz"))
    response = await middleware.dispatch(request, _next)
    assert response.status_code == 403


async def test_safe_method_does_not_require_origin():
    middleware = SessionCookieCSRFMiddleware(_next)
    response = await middleware.dispatch(
        _request(method="GET", cookie="better-auth.session_token=session"),
        _next,
    )
    assert response.status_code == 200


async def test_options_preflight_is_not_blocked_by_cookie_check():
    middleware = SessionCookieCSRFMiddleware(_next)
    response = await middleware.dispatch(
        _request(
            method="OPTIONS",
            cookie="better-auth.session_token=session",
        ),
        _next,
    )
    assert response.status_code == 200


async def test_cookie_less_public_webhook_is_not_blocked():
    middleware = SessionCookieCSRFMiddleware(_next)
    response = await middleware.dispatch(
        _request(method="POST", origin="https://provider.example"),
        _next,
    )
    assert response.status_code == 200


async def test_verified_custom_origin_is_allowed(monkeypatch):
    from app.middleware import tenant_middleware

    monkeypatch.setattr(
        tenant_middleware,
        "resolve_tenant_origin_hostname",
        AsyncMock(return_value={"slug": "example"}),
    )
    middleware = SessionCookieCSRFMiddleware(_next)
    response = await middleware.dispatch(
        _request(
            method="POST",
            origin="https://cv.example.edu",
            cookie="better-auth.session_token=session",
        ),
        _next,
    )
    assert response.status_code == 200


async def test_malformed_origin_does_not_fall_back_to_trusted_referer():
    middleware = SessionCookieCSRFMiddleware(_next)
    request = _request(
        method="POST",
        origin="https://trusted.example:invalid-port",
        cookie="better-auth.session_token=session",
    )
    request.scope["headers"].append((b"referer", b"https://localhost:5180/settings"))
    response = await middleware.dispatch(request, _next)
    assert response.status_code == 403
