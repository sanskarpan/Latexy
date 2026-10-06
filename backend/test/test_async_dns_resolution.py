from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.api.portfolio_routes import verify_domain
from app.services.job_scraper_service import (
    JobScraperResult,
    JobScraperService,
    _SSRFGuardTransport,
)


@pytest.mark.asyncio
async def test_scraper_preflight_dns_runs_off_event_loop():
    service = JobScraperService()
    result = JobScraperResult(url="https://example.com/job", title="Engineer")

    with (
        patch("app.services.job_scraper_service.asyncio.to_thread", AsyncMock()) as to_thread,
        patch("app.services.job_scraper_service.cache_manager.get", AsyncMock(return_value=None)),
        patch.object(service, "_do_scrape", AsyncMock(return_value=result)),
        patch("app.services.job_scraper_service.cache_manager.set", AsyncMock()),
    ):
        scraped = await service.scrape(result.url)

    assert scraped.title == "Engineer"
    to_thread.assert_awaited_once()


@pytest.mark.asyncio
async def test_redirect_transport_dns_guard_runs_off_event_loop():
    transport = _SSRFGuardTransport()
    request = httpx.Request("GET", "https://internal.example/path")
    with patch(
        "app.services.job_scraper_service.asyncio.to_thread",
        AsyncMock(return_value=False),
    ) as to_thread:
        with pytest.raises(httpx.ConnectError):
            await transport.handle_async_request(request)

    to_thread.assert_awaited_once()


@pytest.mark.asyncio
async def test_portfolio_dns_lookups_run_concurrently_off_event_loop():
    user = SimpleNamespace(
        portfolio_custom_domain=None,
        portfolio_domain_verified=False,
    )
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    collision_result = MagicMock()
    collision_result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[user_result, collision_result])
    db.add = MagicMock()

    async def run_in_thread(func, *args):
        return func(*args)

    with (
        patch("app.api.portfolio_routes._resolve_ips", return_value={"203.0.113.10"}),
        patch(
            "app.api.portfolio_routes.asyncio.to_thread",
            AsyncMock(side_effect=run_in_thread),
        ) as to_thread,
    ):
        response = await verify_domain(
            "portfolio.example.com",
            user_id="00000000-0000-0000-0000-000000000001",
            db=db,
        )

    assert response.verified is True
    assert to_thread.await_count == 2

