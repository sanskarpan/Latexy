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
    redis = await get_redis_cache_client()
    key = f"cache:gh:complete:{ticket}"
    # A much shorter remaining lifetime detects accidental TTL renewal too.
    await redis.pexpire(key, 120_000)
    deadline = await redis.execute_command("PEXPIRETIME", key)
    with patch("app.api.github_routes.httpx.AsyncClient", factory):
        for _ in range(3):
            with pytest.raises(HTTPException) as rejected:
                await github_complete(body, db=db, user_id=str(uuid.uuid4()))
            assert rejected.value.status_code == 403
            assert await cache_manager.get(f"gh:complete:{ticket}") == payload
            assert await redis.execute_command("PEXPIRETIME", key) == deadline
        factory.assert_not_called()

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


async def test_both_requests_read_before_atomic_claim_only_one_exchanges():
    ticket, owner, payload = await seed_ticket()
    body = GitHubOAuthCompleteRequest(ticket=ticket)
    both_read = asyncio.Event()
    original_get = cache_manager.get
    read_count = 0
    factory, provider = unavailable_provider()
    db = AsyncMock()

    async def read_before_either_claim(key):
        nonlocal read_count
        observed = await original_get(key)
        assert observed == payload
        read_count += 1
        if read_count == 2:
            both_read.set()
        await asyncio.wait_for(both_read.wait(), timeout=3)
        return observed

    with patch.object(cache_manager, "get", side_effect=read_before_either_claim), patch(
        "app.api.github_routes.httpx.AsyncClient", factory
    ):
        results = await asyncio.gather(
            github_complete(body, db=db, user_id=owner),
            github_complete(body, db=db, user_id=owner),
            return_exceptions=True,
        )
    assert read_count == 2
    assert all(isinstance(result, HTTPException) for result in results)
    assert sorted(result.status_code for result in results) == [400, 502]
    provider.post.assert_awaited_once()
    assert await cache_manager.get(f"gh:complete:{ticket}") is None
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_owner_can_successfully_finish_after_wrong_account_rejection():
    ticket, owner, _payload = await seed_ticket()
    body = GitHubOAuthCompleteRequest(ticket=ticket)
    user = MagicMock(user_metadata={"other_integration": "preserved"})
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db = AsyncMock()
    db.execute.return_value = result
    factory, provider = unavailable_provider()
    provider.post.side_effect = None
    provider.post.return_value = httpx.Response(
        200,
        request=httpx.Request("POST", "https://github.com/login/oauth/access_token"),
        json={"access_token": "synthetic-token", "scope": ""},
    )
    with (
        patch("app.api.github_routes.httpx.AsyncClient", factory),
        patch(
            "app.api.github_routes.github_sync_service.get_github_user",
            new=AsyncMock(return_value={"login": "synthetic-owner"}),
        ) as profile,
        patch("app.api.github_routes.encryption_service.encrypt", return_value="encrypted-test-token"),
    ):
        with pytest.raises(HTTPException) as rejected:
            await github_complete(body, db=db, user_id=str(uuid.uuid4()))
        assert rejected.value.status_code == 403
        factory.assert_not_called()
        db.execute.assert_not_awaited()
        db.commit.assert_not_awaited()
        assert await github_complete(body, db=db, user_id=owner) == {
            "success": True, "message": "GitHub account connected",
        }
        with pytest.raises(HTTPException) as replay:
            await github_complete(body, db=db, user_id=owner)
        assert replay.value.status_code == 400
        provider.post.assert_awaited_once()
        profile.assert_awaited_once_with("synthetic-token")
    db.execute.assert_awaited_once()
    statement = db.execute.await_args.args[0]
    assert list(statement.compile().params.values()) == [owner]
    db.commit.assert_awaited_once()
    assert user.github_access_token == "encrypted-test-token"
    assert user.github_username == "synthetic-owner"
    assert user.user_metadata == {
        "other_integration": "preserved",
        "github_oauth": {"scopes": [], "purpose": "import"},
    }


async def test_unauthenticated_request_cannot_consume_ticket():
    from app.main import app

    ticket, _owner, payload = await seed_ticket()
    factory, _provider = unavailable_provider()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    async with client:
        with patch("app.api.github_routes.httpx.AsyncClient", factory):
            response = await client.post("/github/complete", json={"ticket": ticket})
            assert response.status_code == 401
            factory.assert_not_called()
    assert await cache_manager.get(f"gh:complete:{ticket}") == payload


async def test_owner_is_rechecked_after_atomic_claim():
    ticket, owner, payload = await seed_ticket()
    db = AsyncMock()
    factory, _provider = unavailable_provider()
    original_get = cache_manager.get

    async def change_owner_after_read(key):
        observed = await original_get(key)
        await cache_manager.set(key, {**payload, "user_id": str(uuid.uuid4())}, ttl=300)
        return observed

    with patch.object(cache_manager, "get", side_effect=change_owner_after_read), patch(
        "app.api.github_routes.httpx.AsyncClient", factory
    ):
        with pytest.raises(HTTPException) as rejected:
            await github_complete(GitHubOAuthCompleteRequest(ticket=ticket), db=db, user_id=owner)
        assert rejected.value.status_code == 403
        factory.assert_not_called()
    assert await cache_manager.get(f"gh:complete:{ticket}") is None
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


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
