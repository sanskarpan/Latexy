"""Distributed budget and import quota regression tests."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.api.reference_routes import BibTeXEntry
from app.services.entitlement_service import QuotaTicket
from app.services.external_budget_service import enforce_external_budget
from app.services.job_scraper_service import SSRFError
from app.workers.converter_worker import convert_document_task
from app.workers.github_import_worker import import_github_projects_task


def _ticket(dimension: str = "ai_assists") -> QuotaTicket:
    return QuotaTicket(
        dimension=dimension,
        user_id="user-1",
        period="202608",
        used=1,
        limit=25,
        allowed=True,
    )


async def _consume(scope: str, client_id: str, **overrides) -> int:
    params = {
        "cost": 1,
        "client_limit": 5,
        "global_limit": 10,
        "window_seconds": 60,
        **overrides,
    }
    try:
        await enforce_external_budget(scope, client_id=client_id, **params)
        return 200
    except HTTPException as exc:
        return exc.status_code


class TestDistributedBudget:
    async def test_concurrency_is_atomic_and_rejections_roll_back(self):
        scope = f"test-concurrent-{uuid.uuid4()}"
        first = await asyncio.gather(
            *(_consume(scope, "client-a") for _ in range(20))
        )
        assert first.count(200) == 5
        assert first.count(429) == 15

        # Denied increments were rolled back, leaving five global units for a
        # second client instead of letting rejected traffic exhaust the platform.
        second = await asyncio.gather(
            *(_consume(scope, "client-b") for _ in range(5))
        )
        assert second == [200] * 5

    async def test_weighted_cost_counts_upstream_amplification(self):
        scope = f"test-weighted-{uuid.uuid4()}"
        assert await _consume(scope, "client", cost=3) == 200
        assert await _consume(scope, "client", cost=3) == 429
        assert await _consume(scope, "client", cost=2) == 200

    async def test_store_outage_fails_closed_with_retry_header(self):
        with patch(
            "app.services.external_budget_service.get_redis_cache_client",
            AsyncMock(side_effect=RuntimeError("down")),
        ):
            with pytest.raises(HTTPException) as raised:
                await enforce_external_budget(
                    "outage",
                    client_id="client",
                    cost=1,
                    client_limit=5,
                    global_limit=10,
                    window_seconds=60,
                )
        assert raised.value.status_code == 503
        assert raised.value.headers == {"Retry-After": "30"}


class TestRouteWiring:
    async def test_reference_batch_is_weighted_by_unique_valid_ids(
        self, client: AsyncClient
    ):
        entry = BibTeXEntry(
            identifier="id", bibtex="@misc{x}", cite_key="x", source_type="doi"
        )
        with (
            patch(
                "app.api.reference_routes.enforce_external_budget",
                AsyncMock(),
            ) as budget,
            patch("app.api.reference_routes._fetch_one", AsyncMock(return_value=entry)),
        ):
            response = await client.post(
                "/references/fetch",
                json={
                    "identifiers": [
                        "10.1000/test",
                        "10.1000/test",
                        "1706.03762",
                        "not-an-id",
                    ]
                },
            )
        assert response.status_code == 200
        assert budget.await_args.kwargs["cost"] == 2
        assert budget.await_args.kwargs["client_id"].startswith("ip:")

    async def test_url_import_is_budgeted_and_charged(
        self, client: AsyncClient, auth_headers: dict
    ):
        ticket = _ticket()
        with (
            patch("app.api.sources_routes._enforce_import_budget", AsyncMock()) as budget,
            patch(
                "app.api.sources_routes.entitlement_service.enforce_quota",
                AsyncMock(return_value=ticket),
            ) as quota,
            patch(
                "app.api.sources_routes.url_import.fetch_url_text",
                AsyncMock(return_value="Portfolio"),
            ),
            patch(
                "app.api.sources_routes.url_import.extract_projects",
                return_value=[],
            ),
        ):
            response = await client.post(
                "/sources/import-url",
                json={"url": "https://example.com"},
                headers=auth_headers,
            )
        assert response.status_code == 200
        budget.assert_awaited_once()
        assert quota.await_args.args[0] == "ai_assists"

    async def test_url_import_byok_does_not_consume_platform_quota(
        self, client: AsyncClient, auth_headers: dict
    ):
        with (
            patch("app.api.sources_routes._enforce_import_budget", AsyncMock()),
            patch(
                "app.api.sources_routes.api_key_service.get_user_provider",
                AsyncMock(return_value="user-openai-key"),
            ),
            patch(
                "app.api.sources_routes.entitlement_service.enforce_quota",
                AsyncMock(side_effect=AssertionError("BYOK must not be metered")),
            ) as quota,
            patch(
                "app.api.sources_routes.url_import.fetch_url_text",
                AsyncMock(return_value="Portfolio"),
            ),
            patch(
                "app.api.sources_routes.url_import.extract_projects",
                return_value=[],
            ) as extract,
        ):
            response = await client.post(
                "/sources/import-url",
                json={"url": "https://example.com"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        quota.assert_not_awaited()
        assert extract.call_args.args[2] == "user-openai-key"

    async def test_url_import_byok_fetch_failure_has_no_refund_ticket(
        self, client: AsyncClient, auth_headers: dict
    ):
        with (
            patch("app.api.sources_routes._enforce_import_budget", AsyncMock()),
            patch("app.api.sources_routes.api_key_service.get_user_provider", AsyncMock(return_value="user-openai-key")),
            patch("app.api.sources_routes.entitlement_service.enforce_quota", AsyncMock()) as quota,
            patch("app.api.sources_routes.entitlement_service.refund_quota", AsyncMock()) as refund,
            patch("app.api.sources_routes.url_import.fetch_url_text", AsyncMock(side_effect=SSRFError("blocked"))),
        ):
            response = await client.post(
                "/sources/import-url",
                json={"url": "https://example.com"},
                headers=auth_headers,
            )

        assert response.status_code == 400
        quota.assert_not_awaited()
        refund.assert_not_awaited()

    async def test_url_fetch_failure_refunds_quota(
        self, client: AsyncClient, auth_headers: dict
    ):
        ticket = _ticket()
        with (
            patch("app.api.sources_routes._enforce_import_budget", AsyncMock()),
            patch(
                "app.api.sources_routes.entitlement_service.enforce_quota",
                AsyncMock(return_value=ticket),
            ),
            patch(
                "app.api.sources_routes.entitlement_service.refund_quota",
                AsyncMock(),
            ) as refund,
            patch(
                "app.api.sources_routes.url_import.fetch_url_text",
                AsyncMock(side_effect=SSRFError("blocked")),
            ),
        ):
            response = await client.post(
                "/sources/import-url",
                json={"url": "https://example.com"},
                headers=auth_headers,
            )
        assert response.status_code == 400
        refund.assert_awaited_once_with(ticket)

    async def test_url_budget_rejection_refunds_reserved_quota(
        self, client: AsyncClient, auth_headers: dict
    ):
        ticket = _ticket()
        with (
            patch(
                "app.api.sources_routes.entitlement_service.enforce_quota",
                AsyncMock(return_value=ticket),
            ),
            patch(
                "app.api.sources_routes.entitlement_service.refund_quota",
                AsyncMock(),
            ) as refund,
            patch(
                "app.api.sources_routes._enforce_import_budget",
                AsyncMock(side_effect=HTTPException(status_code=429, detail="limited")),
            ),
        ):
            response = await client.post(
                "/sources/import-url",
                json={"url": "https://example.com"},
                headers=auth_headers,
            )
        assert response.status_code == 429
        refund.assert_awaited_once_with(ticket)

    async def test_linkedin_import_has_dedicated_budget(
        self, client: AsyncClient, auth_headers: dict
    ):
        with patch(
            "app.api.sources_routes._enforce_import_budget", AsyncMock()
        ) as budget:
            response = await client.post(
                "/sources/import-linkedin",
                files={"file": ("resume.txt", b"Experience at Acme", "text/plain")},
                headers=auth_headers,
            )
        assert response.status_code in (200, 422)
        budget.assert_awaited_once()


class TestGitHubWorkerQuota:
    def test_ownerless_failure_without_accepted_terminal_does_not_refund(self):
        payload = _ticket().refund_payload()
        with patch("app.workers.github_import_worker.refund_quota_once") as refund:
            result = import_github_projects_task(
                job_id="job-ownerless", user_id=None, quota_refund=payload
            )
        assert result["success"] is False
        refund.assert_not_called()

    def test_rejected_failure_result_does_not_refund(self):
        payload = _ticket().refund_payload()
        with (
            patch(
                "app.workers.github_import_worker._resolve_import_credentials",
                AsyncMock(return_value=(None, None)),
            ),
            patch("app.workers.github_import_worker._store_result", return_value=False),
            patch("app.workers.github_import_worker.admit_worker", return_value=True),
            patch("app.workers.github_import_worker.publish_event"),
            patch("app.workers.github_import_worker.refund_quota_once") as refund,
        ):
            result = import_github_projects_task(
                job_id="job-rejected-failure", user_id="user-1", quota_refund=payload
            )
        assert result["success"] is False
        refund.assert_not_called()

    def test_accepted_failure_refunds_even_when_event_is_rejected(self):
        payload = _ticket().refund_payload()
        with (
            patch(
                "app.workers.github_import_worker._resolve_import_credentials",
                AsyncMock(return_value=(None, None)),
            ),
            patch("app.workers.github_import_worker._store_result", return_value=True),
            patch("app.workers.github_import_worker.admit_worker", return_value=True),
            patch("app.workers.github_import_worker.publish_event", return_value=""),
            patch("app.workers.github_import_worker.refund_quota_once") as refund,
        ):
            result = import_github_projects_task(
                job_id="job-failed-event-rejected", user_id="user-1", quota_refund=payload
            )
        assert result["success"] is False
        refund.assert_called_once_with(
            "job-failed-event-rejected", payload, expected_dimension="ai_assists"
        )

    def test_success_does_not_refund(self):
        payload = _ticket().refund_payload()
        with (
            patch(
                "app.workers.github_import_worker._resolve_import_credentials",
                AsyncMock(return_value=("github-token", None)),
            ),
            patch("app.workers.github_import_worker.httpx.Client", return_value=MagicMock()),
            patch("app.workers.github_import_worker.gh.fetch_candidate_repos", return_value=[]),
            patch("app.workers.github_import_worker._store_result"),
            patch("app.workers.github_import_worker.admit_worker", return_value=True),
            patch("app.workers.github_import_worker.publish_event"),
            patch("app.workers.github_import_worker.clear_quota_refund_receipt"),
            patch("app.workers.github_import_worker.refund_quota_once") as refund,
        ):
            result = import_github_projects_task(
                job_id="job-success", user_id="user-1", quota_refund=payload
            )
        assert result["success"] is True
        refund.assert_not_called()

    def test_accepted_success_with_rejected_event_does_not_refund(self):
        payload = _ticket().refund_payload()
        with (
            patch(
                "app.workers.github_import_worker._resolve_import_credentials",
                AsyncMock(return_value=("github-token", None)),
            ),
            patch("app.workers.github_import_worker.httpx.Client", return_value=MagicMock()),
            patch("app.workers.github_import_worker.gh.fetch_candidate_repos", return_value=[]),
            patch("app.workers.github_import_worker._store_result", return_value=True),
            patch("app.workers.github_import_worker.admit_worker", return_value=True),
            patch("app.workers.github_import_worker.publish_event", return_value=""),
            patch("app.workers.github_import_worker.clear_quota_refund_receipt"),
            patch("app.workers.github_import_worker.refund_quota_once") as refund,
        ):
            result = import_github_projects_task(
                job_id="job-success-event-rejected", user_id="user-1", quota_refund=payload
            )
        assert result["success"] is False
        refund.assert_not_called()


    def test_duplicate_delivery_does_not_refund_live_owner(self):
        payload = _ticket().refund_payload()
        with (
            patch("app.workers.github_import_worker.admit_worker", return_value=False),
            patch("app.workers.github_import_worker.refund_quota_once") as refund,
        ):
            result = import_github_projects_task(
                job_id="job-duplicate", user_id="user-1", quota_refund=payload
            )

        assert result["error"] == "Job ownership unavailable"
        refund.assert_not_called()


    def test_cancelled_import_refunds(self):
        payload = _ticket().refund_payload()
        repo = {"owner": "owner", "name": "repo"}
        with (
            patch(
                "app.workers.github_import_worker._resolve_import_credentials",
                AsyncMock(return_value=("github-token", None)),
            ),
            patch("app.workers.github_import_worker.httpx.Client", return_value=MagicMock()),
            patch("app.workers.github_import_worker.gh.fetch_candidate_repos", return_value=[repo]),
            patch("app.workers.github_import_worker.gh.rank_repos", return_value=[repo]),
            patch("app.workers.github_import_worker.is_cancelled", return_value=True),
            patch("app.workers.github_import_worker._store_result"),
            patch("app.workers.github_import_worker.admit_worker", return_value=True),
            patch("app.workers.github_import_worker.publish_event"),
            patch("app.workers.github_import_worker.refund_quota_once") as refund,
        ):
            result = import_github_projects_task(
                job_id="job-cancelled", user_id="user-1", quota_refund=payload
            )
        assert result["cancelled"] is True
        refund.assert_called_once()

    def test_retrying_import_does_not_refund(self):
        payload = _ticket().refund_payload()
        with (
            patch(
                "app.workers.github_import_worker._resolve_import_credentials",
                AsyncMock(side_effect=OSError("temporary")),
            ),
            patch("app.workers.github_import_worker.admit_worker", return_value=True),
            patch("app.workers.github_import_worker.publish_event"),
            patch.object(
                import_github_projects_task,
                "retry",
                side_effect=RuntimeError("retry scheduled"),
            ),
            patch("app.workers.github_import_worker.refund_quota_once") as refund,
            pytest.raises(RuntimeError, match="retry scheduled"),
        ):
            import_github_projects_task(
                job_id="job-retrying", user_id="user-1", quota_refund=payload
            )
        refund.assert_not_called()


class TestConverterWorkerQuota:
    def _run_without_provider(self, result_stored, event_id):
        payload = _ticket().refund_payload()
        with (
            patch("app.workers.converter_worker.settings.OPENAI_API_KEY", ""),
            patch("app.workers.converter_worker.admit_worker", return_value=True),
            patch("app.workers.converter_worker.publish_job_result", return_value=result_stored),
            patch("app.workers.converter_worker.publish_event", return_value=event_id),
            patch("app.workers.converter_worker.refund_quota_once") as refund,
        ):
            result = convert_document_task.run(
                extracted_data={},
                source_format="json",
                job_id=f"converter-{result_stored}-{event_id}",
                user_id="user-1",
                quota_refund=payload,
            )
        return result, refund

    def test_rejected_failure_result_does_not_refund(self):
        result, refund = self._run_without_provider(False, "event")
        assert result["success"] is False
        refund.assert_not_called()

    def test_accepted_failure_refunds_when_terminal_event_is_rejected(self):
        result, refund = self._run_without_provider(True, "")
        assert result["success"] is False
        refund.assert_called_once()
