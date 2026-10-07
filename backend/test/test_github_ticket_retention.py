"""Real isolated Redis controls; provider traffic and database writes are fake."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.api.github_routes import GitHubOAuthCompleteRequest, github_complete
from app.core.redis import cache_manager, get_redis_cache_client, redis_manager


async def seed_ticket():
    await redis_manager.init_redis()
    ticket = f"test-owner-retention-{uuid.uuid4().hex}"
    owner = str(uuid.uuid4())
    payload = {"user_id": owner, "code": "synthetic-provider-code", "purpose": "import"}
    await cache_manager.set(f"gh:complete:{ticket}", payload, ttl=300)
    return ticket, owner, payload


def unavailable_provider():
    provider = AsyncMock()
    provider.post.side_effect = httpx.ConnectError("synthetic provider unavailable")
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=provider)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory, provider


async def test_wrong_owner_preserves_ticket_for_its_original_owner():
    ticket, owner, payload = await seed_ticket()
    body = GitHubOAuthCompleteRequest(ticket=ticket)
    db = AsyncMock()
    factory, provider = unavailable_provider()
    with patch("app.api.github_routes.httpx.AsyncClient", factory):
        with pytest.raises(HTTPException) as rejected:
            await github_complete(body, db=db, user_id=str(uuid.uuid4()))
        assert rejected.value.status_code == 403
        factory.assert_not_called()
        assert await cache_manager.get(f"gh:complete:{ticket}") == payload
        redis = await get_redis_cache_client()
        assert 0 < await redis.ttl(f"cache:gh:complete:{ticket}") <= 300

        # The rightful owner reaches the fake exchange, rather than an expired
        # ticket error. No external request or durable account mutation occurs.
        with pytest.raises(HTTPException) as owner_attempt:
            await github_complete(body, db=db, user_id=owner)
        assert owner_attempt.value.status_code == 502
        provider.post.assert_awaited_once()
        assert await cache_manager.get(f"gh:complete:{ticket}") is None
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_matching_owner_consumes_ticket_once_even_if_exchange_fails():
    ticket, owner, _payload = await seed_ticket()
    body = GitHubOAuthCompleteRequest(ticket=ticket)
    factory, provider = unavailable_provider()
    with patch("app.api.github_routes.httpx.AsyncClient", factory):
        with pytest.raises(HTTPException) as first:
            await github_complete(body, db=AsyncMock(), user_id=owner)
        assert first.value.status_code == 502
        with pytest.raises(HTTPException) as replay:
            await github_complete(body, db=AsyncMock(), user_id=owner)
        assert replay.value.status_code == 400
        provider.post.assert_awaited_once()


async def test_concurrent_matching_owners_cannot_exchange_one_ticket_twice():
    ticket, owner, _payload = await seed_ticket()
    body = GitHubOAuthCompleteRequest(ticket=ticket)
    started = asyncio.Event()
    release = asyncio.Event()
    factory, provider = unavailable_provider()

    async def exchange(*_args, **_kwargs):
        started.set()
        await release.wait()
        raise httpx.ConnectError("synthetic provider unavailable")

    provider.post.side_effect = exchange
    first = None
    try:
        with patch("app.api.github_routes.httpx.AsyncClient", factory):
            first = asyncio.create_task(github_complete(body, db=AsyncMock(), user_id=owner))
            await asyncio.wait_for(started.wait(), timeout=3)
            with pytest.raises(HTTPException) as racing:
                await github_complete(body, db=AsyncMock(), user_id=owner)
            assert racing.value.status_code == 400
            release.set()
            with pytest.raises(HTTPException) as winner:
                await first
            assert winner.value.status_code == 502
            provider.post.assert_awaited_once()
    finally:
        release.set()
        if first is not None and not first.done():
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)


@pytest.mark.parametrize("payload", [None, "invalid", {}, {"user_id": "owner"}, {"code": "code"}])
async def test_missing_or_malformed_ticket_never_reaches_provider(payload):
    await redis_manager.init_redis()
    ticket = f"test-invalid-retention-{uuid.uuid4().hex}"
    if payload is not None:
        await cache_manager.set(f"gh:complete:{ticket}", payload, ttl=300)
    db = AsyncMock()
    factory, _provider = unavailable_provider()
    with patch("app.api.github_routes.httpx.AsyncClient", factory):
        with pytest.raises(HTTPException) as rejected:
            await github_complete(GitHubOAuthCompleteRequest(ticket=ticket), db=db, user_id="owner")
        assert rejected.value.status_code == 400
        factory.assert_not_called()
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_expiry_between_peek_and_claim_is_rejected():
    ticket, owner, _payload = await seed_ticket()
    db = AsyncMock()
    factory, _provider = unavailable_provider()
    original_get = cache_manager.get

    async def expire_after_read(key):
        observed = await original_get(key)
        await cache_manager.delete(key)
        return observed

    with patch.object(cache_manager, "get", side_effect=expire_after_read), patch(
        "app.api.github_routes.httpx.AsyncClient", factory
    ):
        with pytest.raises(HTTPException) as rejected:
            await github_complete(GitHubOAuthCompleteRequest(ticket=ticket), db=db, user_id=owner)
        assert rejected.value.status_code == 400
        factory.assert_not_called()
    assert await cache_manager.get(f"gh:complete:{ticket}") is None
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()
