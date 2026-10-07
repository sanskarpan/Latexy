"""Real isolated Redis regression coverage for OAuth ticket ownership."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.api.dropbox_routes import DropboxOAuthCompleteRequest, dropbox_complete
from app.api.mendeley_routes import MendeleyOAuthCompleteRequest, mendeley_complete
from app.api.zotero_routes import ZoteroOAuthCompleteRequest, zotero_complete
from app.core.redis import cache_manager, get_redis_cache_client, redis_manager


@pytest.mark.parametrize(
    ("provider", "handler", "request_type", "prefix", "payload"),
    [
        (
            "dropbox",
            dropbox_complete,
            DropboxOAuthCompleteRequest,
            "dbx:complete:",
            {"user_id": "owner", "code": "synthetic-code"},
        ),
        (
            "mendeley",
            mendeley_complete,
            MendeleyOAuthCompleteRequest,
            "mendeley:complete:",
            {"user_id": "owner", "code": "synthetic-code"},
        ),
        (
            "zotero",
            zotero_complete,
            ZoteroOAuthCompleteRequest,
            "zotero:complete:",
            {
                "user_id": "owner",
                "oauth_token": "synthetic-token",
                "oauth_verifier": "synthetic-verifier",
                "request_token_secret": "synthetic-secret",
            },
        ),
    ],
)
async def test_wrong_owner_does_not_consume_completion_ticket(
    provider, handler, request_type, prefix, payload
):
    await redis_manager.init_redis()
    ticket = f"retention-{uuid.uuid4().hex}"
    key = f"{prefix}{ticket}"
    await cache_manager.set(key, payload, ttl=300)

    module = f"app.api.{provider}_routes"
    client_factory, provider_client = _unavailable_provider()
    db = AsyncMock()
    with patch(f"{module}.httpx.AsyncClient", client_factory):
        with pytest.raises(HTTPException) as rejected:
            await handler(request_type(ticket=ticket), db=db, user_id="other-user")

    assert rejected.value.status_code == 403
    provider_client.post.assert_not_awaited()
    assert await cache_manager.get(key) == payload
    redis = await get_redis_cache_client()
    ttl = await redis.ttl(f"cache:{key}")
    assert 0 < ttl <= 300

    # The rightful owner can still claim it; the fake provider failure proves
    # the flow passed ownership and reached exchange without external traffic.
    with patch(f"{module}.httpx.AsyncClient", client_factory):
        with pytest.raises(HTTPException) as owner_attempt:
            await handler(request_type(ticket=ticket), db=db, user_id="owner")
    assert owner_attempt.value.status_code == 502
    provider_client.post.assert_awaited_once()
    assert await cache_manager.get(key) is None
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()

    with patch(f"{module}.httpx.AsyncClient", client_factory):
        with pytest.raises(HTTPException) as replay:
            await handler(request_type(ticket=ticket), db=db, user_id="owner")
    assert replay.value.status_code == 400
    provider_client.post.assert_awaited_once()


@pytest.mark.parametrize(
    ("provider", "handler", "request_type", "prefix", "payload"),
    [
        (
            "dropbox",
            dropbox_complete,
            DropboxOAuthCompleteRequest,
            "dbx:complete:",
            {"user_id": "owner", "code": "synthetic-code"},
        ),
        (
            "mendeley",
            mendeley_complete,
            MendeleyOAuthCompleteRequest,
            "mendeley:complete:",
            {"user_id": "owner", "code": "synthetic-code"},
        ),
        (
            "zotero",
            zotero_complete,
            ZoteroOAuthCompleteRequest,
            "zotero:complete:",
            {
                "user_id": "owner",
                "oauth_token": "synthetic-token",
                "oauth_verifier": "synthetic-verifier",
                "request_token_secret": "synthetic-secret",
            },
        ),
    ],
)
async def test_concurrent_owner_claims_exchange_ticket_once(
    provider, handler, request_type, prefix, payload
):
    await redis_manager.init_redis()
    ticket = f"concurrent-retention-{uuid.uuid4().hex}"
    await cache_manager.set(f"{prefix}{ticket}", payload, ttl=300)

    started = asyncio.Event()
    release = asyncio.Event()
    client_factory, provider_client = _unavailable_provider()

    async def fail_after_gate(*_args, **_kwargs):
        started.set()
        await release.wait()
        raise httpx.ConnectError("synthetic provider unavailable")

    provider_client.post.side_effect = fail_after_gate
    first = None
    try:
        module = f"app.api.{provider}_routes"
        with patch(f"{module}.httpx.AsyncClient", client_factory):
            first = asyncio.create_task(
                handler(request_type(ticket=ticket), db=AsyncMock(), user_id="owner")
            )
            await asyncio.wait_for(started.wait(), timeout=3)
            with pytest.raises(HTTPException) as racing:
                await handler(request_type(ticket=ticket), db=AsyncMock(), user_id="owner")
            assert racing.value.status_code == 400
            release.set()
            with pytest.raises(HTTPException) as winner:
                await first
            assert winner.value.status_code == 502
        provider_client.post.assert_awaited_once()
        assert await cache_manager.get(f"{prefix}{ticket}") is None
    finally:
        release.set()
        if first is not None and not first.done():
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)


def _unavailable_provider():
    provider_client = AsyncMock()
    provider_client.post.side_effect = httpx.ConnectError("synthetic provider unavailable")
    client_factory = MagicMock()
    client_factory.return_value.__aenter__ = AsyncMock(return_value=provider_client)
    client_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return client_factory, provider_client
