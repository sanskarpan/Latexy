"""Revenue dashboard: MRR/ARR normalization, ARPU, refunds and chargebacks."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from test.test_admin_control_room_api import _create_user, _headers


def _historical_anchor() -> datetime:
    """Random 1980s timestamp isolated from other control-room fixtures."""
    return datetime(1980, 1, 1, tzinfo=timezone.utc) + timedelta(
        seconds=uuid.uuid4().int % (8 * 365 * 86_400)
    )


def _window(anchor: datetime) -> dict[str, str]:
    return {
        "start": (anchor - timedelta(seconds=1)).isoformat(),
        "end": (anchor + timedelta(seconds=1)).isoformat(),
    }


async def _create_subscription(
    db: AsyncSession,
    *,
    user_id: str,
    plan_id: str,
    amount: int | None,
    provider: str = "dodo",
    status: str = "active",
    period_end: datetime | None = None,
) -> str:
    subscription_id = str(uuid.uuid4())
    provider_subscription_id = f"sub_{uuid.uuid4().hex[:12]}"
    if provider.lower().startswith("test"):
        provider_subscription_id = f"test_{provider_subscription_id}"
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "plan_id, status, current_period_start, current_period_end, quoted_amount) "
            "VALUES (:id, :uid, :provider, :provider_sub, :plan, :status, :start, :end, :amount)"
        ),
        {
            "id": subscription_id,
            "uid": user_id,
            "provider": provider,
            "provider_sub": provider_subscription_id,
            "plan": plan_id,
            "status": status,
            "start": now - timedelta(days=10),
            "end": period_end or (now + timedelta(days=20)),
            "amount": amount,
        },
    )
    await db.commit()
    return subscription_id


async def _insert_payment(
    db: AsyncSession,
    *,
    user_id: str,
    amount: int,
    created_at: datetime,
    currency: str = "INR",
    status: str = "paid",
    subscription_id: str | None = None,
    provider: str = "dodo",
    provider_payment_id: str | None = None,
) -> tuple[str, str]:
    payment_id = str(uuid.uuid4())
    provider_payment_id = provider_payment_id or f"pay_{uuid.uuid4().hex[:12]}"
    await db.execute(
        text(
            "INSERT INTO payments (id, user_id, subscription_id, provider, provider_payment_id, "
            "amount, currency, status, created_at) "
            "VALUES (:id, :uid, :sub, :provider, :provider_payment, :amount, :currency, :status, :created)"
        ),
        {
            "id": payment_id,
            "uid": user_id,
            "sub": subscription_id,
            "provider": provider,
            "provider_payment": provider_payment_id,
            "amount": amount,
            "currency": currency,
            "status": status,
            "created": created_at,
        },
    )
    await db.commit()
    return payment_id, provider_payment_id


async def _insert_refund(
    db: AsyncSession,
    *,
    payment_id: str,
    amount: int,
    created_at: datetime,
    status: str = "succeeded",
    currency: str = "INR",
    provider: str = "dodo",
) -> str:
    refund_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO payment_refunds (id, payment_id, provider, provider_refund_id, "
            "amount, currency, status, reason, created_at) "
            "VALUES (:id, :payment, :provider, :refund, :amount, :currency, :status, 'test', :created)"
        ),
        {
            "id": refund_id,
            "payment": payment_id,
            "provider": provider,
            "refund": f"ref_{uuid.uuid4().hex[:12]}",
            "amount": amount,
            "currency": currency,
            "status": status,
            "created": created_at,
        },
    )
    await db.commit()
    return refund_id


async def _insert_dispute_event(
    db: AsyncSession,
    *,
    event_type: str,
    resource_id: str,
    received_at: datetime,
    provider: str = "dodo",
) -> str:
    event_id = str(uuid.uuid4())
    provider_event = f"evt_{uuid.uuid4().hex[:16]}"
    if provider.lower().startswith("test"):
        provider_event = f"test_{provider_event}"
    await db.execute(
        text(
            "INSERT INTO billing_webhook_events "
            "(id, provider, event_id, event_type, event_resource_id, payload_sha256, status, attempts, received_at) "
            "VALUES (:id, :provider, :event_id, :event_type, :resource, :digest, 'processed', 1, :received)"
        ),
        {
            "id": event_id,
            "provider": provider,
            "event_id": provider_event,
            "event_type": event_type,
            "resource": resource_id,
            "digest": "a" * 64,
            "received": received_at,
        },
    )
    await db.commit()
    return event_id


async def _summary(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    params: dict[str, str] | None = None,
    days: int = 30,
) -> dict:
    response = await client.get(
        "/admin/billing/summary",
        params={"days": days, **(params or {})},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestMrrNormalization:
    async def test_monthly_annual_weekly_and_lifetime_quotes(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        user_id, _ = await _create_user(db_session)
        before = await _summary(client, admin_headers)

        await _create_subscription(
            db_session, user_id=user_id, plan_id="pro", amount=59900
        )
        await _create_subscription(
            db_session, user_id=user_id, plan_id="pro_annual", amount=575000
        )
        await _create_subscription(
            db_session, user_id=user_id, plan_id="weekly", amount=12000
        )
        await _create_subscription(
            db_session, user_id=user_id, plan_id="lifetime", amount=1000000
        )

        after = await _summary(client, admin_headers)
        assert after["mrr_minor"] - before["mrr_minor"] == 59900 + 47917 + 52000
        assert after["arr_minor"] - before["arr_minor"] == (59900 + 47917 + 52000) * 12
        assert after["active_subscriptions"] - before["active_subscriptions"] == 4
        assert after["active_recurring_subscriptions"] - before["active_recurring_subscriptions"] == 3
        assert after["arpu_minor"] == round(
            after["mrr_minor"] / after["active_subscriptions"]
        )
        by_interval = {
            item["interval"]: item
            for item in after["mrr_normalization"]["by_interval"]
        }
        assert by_interval["month"]["mrr_minor"] >= 59900
        assert by_interval["year"]["mrr_minor"] >= 47917
        assert by_interval["week"]["mrr_minor"] >= 52000
        assert by_interval["lifetime"]["mrr_minor"] == 0
        assert after["mrr_normalization"]["lifetime_policy"] == "excluded_from_mrr"


class TestRefundsAndReconciliation:
    async def test_succeeded_refund_subtracts_once_and_failed_refund_does_not(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        user_id, _ = await _create_user(db_session)
        anchor = _historical_anchor()
        window = _window(anchor)
        before = await _summary(client, admin_headers, params=window)

        _, provider_payment_id = await _insert_payment(
            db_session, user_id=user_id, amount=100000, created_at=anchor
        )
        payment_id = (
            await db_session.execute(
                text("SELECT id FROM payments WHERE provider_payment_id = :pid"),
                {"pid": provider_payment_id},
            )
        ).scalar_one()
        await _insert_refund(
            db_session, payment_id=payment_id, amount=30000, created_at=anchor
        )
        await _insert_refund(
            db_session,
            payment_id=payment_id,
            amount=20000,
            created_at=anchor,
            status="failed",
        )

        after = await _summary(client, admin_headers, params=window)
        assert after["gross_revenue_minor"] - before["gross_revenue_minor"] == 100000
        assert after["refunded_minor"] - before["refunded_minor"] == 30000
        assert after["net_revenue_minor"] - before["net_revenue_minor"] == 70000
        assert after["payments_count"] - before["payments_count"] == 1
        assert after["refunds_count"] - before["refunds_count"] == 1
        assert after["refund_view"]["succeeded_minor"] - before["refund_view"]["succeeded_minor"] == 30000
        assert after["refund_view"]["failed_minor"] - before["refund_view"]["failed_minor"] == 20000
        assert after["refund_view"]["failed_count"] - before["refund_view"]["failed_count"] == 1

        reconciliation = after["reconciliation"]
        assert reconciliation["balanced"] is True
        assert reconciliation["difference_minor"] == 0
        assert reconciliation["expected_net_minor"] == reconciliation["net_revenue_minor"]
        assert reconciliation["gross_from_payments_minor"] == after["gross_revenue_minor"]
        assert reconciliation["refunded_from_payment_refunds_minor"] == after["refunded_minor"]
        assert reconciliation["plan_mix_revenue_difference_minor"] == 0


class TestChargebacks:
    async def test_chargeback_events_are_included_once_and_linked_to_payments(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        user_id, _ = await _create_user(db_session)
        anchor = _historical_anchor()
        window = _window(anchor)
        before = await _summary(client, admin_headers, params=window)

        _, provider_payment_id = await _insert_payment(
            db_session, user_id=user_id, amount=50000, created_at=anchor
        )
        await _insert_dispute_event(
            db_session,
            event_type="dispute.opened",
            resource_id=provider_payment_id,
            received_at=anchor,
        )
        await _insert_dispute_event(
            db_session,
            event_type="dispute.lost",
            resource_id=provider_payment_id,
            received_at=anchor + timedelta(milliseconds=1),
        )

        after = await _summary(client, admin_headers, params=window)
        assert after["chargebacks_minor"] - before["chargebacks_minor"] == 50000
        assert after["chargebacks_count"] - before["chargebacks_count"] == 1
        assert (
            after["net_revenue_after_chargebacks_minor"]
            - before["net_revenue_after_chargebacks_minor"]
            == after["net_revenue_minor"]
            - before["net_revenue_minor"]
            - 50000
        )
        assert (
            sum(point["chargebacks_minor"] for point in after["revenue_series"])
            - sum(point["chargebacks_minor"] for point in before["revenue_series"])
            == 50000
        )
        view = after["chargeback_view"]
        assert view["total_minor"] - before["chargeback_view"]["total_minor"] == 50000
        assert view["events_count"] - before["chargeback_view"]["events_count"] == 2
        assert view["count"] - before["chargeback_view"]["count"] == 1
        assert view["lost_count"] - before["chargeback_view"]["lost_count"] == 1
        assert view["items"]
        item = view["items"][0]
        assert "email" not in item
        assert "customer" not in item
        assert "provider_payment_id" not in item
        assert after["reconciliation"]["chargebacks_from_events_minor"] == after["chargebacks_minor"]


class TestTestModeExclusion:
    async def test_test_mode_subscriptions_payments_refunds_and_disputes_are_ignored(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        user_id, _ = await _create_user(db_session)
        anchor = _historical_anchor()
        window = _window(anchor)
        before = await _summary(client, admin_headers, params=window)
        before_mrr = (await _summary(client, admin_headers))["mrr_minor"]

        subscription_id = await _create_subscription(
            db_session,
            user_id=user_id,
            plan_id="pro",
            amount=59900,
            provider="dodo_test",
        )
        payment_id, provider_payment_id = await _insert_payment(
            db_session,
            user_id=user_id,
            amount=90000,
            created_at=anchor,
            provider="dodo_test",
            subscription_id=subscription_id,
        )
        await _insert_refund(
            db_session,
            payment_id=payment_id,
            amount=10000,
            created_at=anchor,
            provider="dodo_test",
        )
        await _insert_dispute_event(
            db_session,
            event_type="dispute.opened",
            resource_id=provider_payment_id,
            received_at=anchor,
            provider="dodo_test",
        )

        # A live provider row whose identifiers/plan are test-prefixed must also
        # be excluded, proving the filter is not only a provider-string check.
        test_plan_subscription = await _create_subscription(
            db_session, user_id=user_id, plan_id="test_pro", amount=59900
        )
        await _insert_payment(
            db_session,
            user_id=user_id,
            amount=70000,
            created_at=anchor,
            subscription_id=test_plan_subscription,
            provider_payment_id=f"test_pay_{uuid.uuid4().hex[:12]}",
        )

        after = await _summary(client, admin_headers, params=window)
        after_mrr = (await _summary(client, admin_headers))["mrr_minor"]
        assert after["gross_revenue_minor"] == before["gross_revenue_minor"]
        assert after["refunded_minor"] == before["refunded_minor"]
        assert after["net_revenue_minor"] == before["net_revenue_minor"]
        assert after["chargebacks_minor"] == before["chargebacks_minor"]
        assert after["payments_count"] == before["payments_count"]
        assert after_mrr == before_mrr
        assert after["active_subscriptions"] == before["active_subscriptions"]
        assert after["reconciliation"]["test_mode_excluded"] is True


class TestPlanMixAndCurrency:
    async def test_plan_mix_attributes_period_revenue_and_refunds(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        user_id, _ = await _create_user(db_session)
        anchor = _historical_anchor()
        window = _window(anchor)
        subscription_id = await _create_subscription(
            db_session, user_id=user_id, plan_id="pro", amount=59900
        )
        payment_id, _ = await _insert_payment(
            db_session,
            user_id=user_id,
            amount=80000,
            created_at=anchor,
            subscription_id=subscription_id,
        )
        await _insert_refund(
            db_session, payment_id=payment_id, amount=5000, created_at=anchor
        )

        body = await _summary(client, admin_headers, params=window)
        plan = next(item for item in body["plan_mix"] if item["plan_id"] == "pro")
        assert plan["revenue_minor"] == 80000
        assert plan["refunded_minor"] == 5000
        assert plan["net_revenue_minor"] == 75000
        assert plan["payments_count"] == 1
        assert plan["refunds_count"] == 1
        assert plan["mrr_minor"] >= 59900
        assert plan["share_percent"] == round(
            plan["revenue_minor"] * 100 / body["gross_revenue_minor"], 2
        )
        assert body["reconciliation"]["plan_mix_attributed_revenue_minor"] == body["gross_revenue_minor"]
        assert body["reconciliation"]["plan_mix_attributed_refunds_minor"] == body["refunded_minor"]

    async def test_explicit_currency_excludes_other_currency_rows(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        user_id, _ = await _create_user(db_session)
        anchor = _historical_anchor()
        window = _window(anchor)
        before_inr = await _summary(client, admin_headers, params={**window, "currency": "INR"})
        before_usd = await _summary(client, admin_headers, params={**window, "currency": "USD"})

        await _insert_payment(
            db_session,
            user_id=user_id,
            amount=4200,
            created_at=anchor,
            currency="USD",
        )

        after_inr = await _summary(client, admin_headers, params={**window, "currency": "INR"})
        after_usd = await _summary(client, admin_headers, params={**window, "currency": "USD"})
        assert after_usd["currency"] == "USD"
        assert after_usd["gross_revenue_minor"] - before_usd["gross_revenue_minor"] == 4200
        assert after_inr["gross_revenue_minor"] == before_inr["gross_revenue_minor"]


class TestRangesAndAccess:
    async def test_daily_and_monthly_series_totals_reconcile(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        user_id, _ = await _create_user(db_session)
        first = datetime(1981, 1, 30, 12, tzinfo=timezone.utc)
        second = datetime(1981, 1, 31, 12, tzinfo=timezone.utc)
        third = datetime(1981, 2, 1, 12, tzinfo=timezone.utc)
        window = {
            "start": (first - timedelta(seconds=1)).isoformat(),
            "end": (third + timedelta(seconds=1)).isoformat(),
        }
        before_daily = await _summary(
            client, admin_headers, params={**window, "granularity": "day"}
        )
        before_monthly = await _summary(
            client, admin_headers, params={**window, "granularity": "month"}
        )
        payment_one, _ = await _insert_payment(
            db_session, user_id=user_id, amount=1000, created_at=first
        )
        await _insert_payment(
            db_session, user_id=user_id, amount=2000, created_at=second
        )
        await _insert_payment(
            db_session, user_id=user_id, amount=3000, created_at=third
        )
        await _insert_refund(
            db_session, payment_id=payment_one, amount=500, created_at=second
        )

        daily = await _summary(
            client, admin_headers, params={**window, "granularity": "day"}
        )
        assert daily["granularity"] == "day"
        assert [point["bucket"] for point in daily["revenue_series"]] == [
            "1981-01-30",
            "1981-01-31",
            "1981-02-01",
        ]
        assert sum(point["gross_revenue_minor"] for point in daily["revenue_series"]) == daily["gross_revenue_minor"]
        assert sum(point["refunds_minor"] for point in daily["revenue_series"]) == daily["refunded_minor"]
        assert sum(point["net_revenue_minor"] for point in daily["revenue_series"]) == daily["net_revenue_minor"]
        assert daily["gross_revenue_minor"] - before_daily["gross_revenue_minor"] == 6000
        assert daily["refunded_minor"] - before_daily["refunded_minor"] == 500
        assert daily["net_revenue_minor"] - before_daily["net_revenue_minor"] == 5500
        daily_by_bucket = {point["bucket"]: point for point in daily["revenue_series"]}
        before_by_bucket = {point["bucket"]: point for point in before_daily["revenue_series"]}
        assert daily_by_bucket["1981-01-30"]["gross_revenue_minor"] - before_by_bucket["1981-01-30"]["gross_revenue_minor"] == 1000
        assert daily_by_bucket["1981-01-31"]["gross_revenue_minor"] - before_by_bucket["1981-01-31"]["gross_revenue_minor"] == 2000
        assert daily_by_bucket["1981-02-01"]["gross_revenue_minor"] - before_by_bucket["1981-02-01"]["gross_revenue_minor"] == 3000

        monthly = await _summary(
            client, admin_headers, params={**window, "granularity": "monthly"}
        )
        assert monthly["granularity"] == "month"
        assert [point["bucket"] for point in monthly["revenue_series"]] == ["1981-01", "1981-02"]
        assert sum(point["gross_revenue_minor"] for point in monthly["revenue_series"]) == monthly["gross_revenue_minor"]
        assert monthly["gross_revenue_minor"] - before_monthly["gross_revenue_minor"] == 6000
        monthly_by_bucket = {point["bucket"]: point for point in monthly["revenue_series"]}
        before_monthly_by_bucket = {point["bucket"]: point for point in before_monthly["revenue_series"]}
        assert monthly_by_bucket["1981-01"]["gross_revenue_minor"] - before_monthly_by_bucket["1981-01"]["gross_revenue_minor"] == 3000
        assert monthly_by_bucket["1981-02"]["gross_revenue_minor"] - before_monthly_by_bucket["1981-02"]["gross_revenue_minor"] == 3000

    async def test_summary_is_admin_only(self, client: AsyncClient, db_session: AsyncSession):
        support_headers = await _headers(db_session, "support")
        response = await client.get("/admin/billing/summary", headers=support_headers)
        assert response.status_code == 403

    async def test_invalid_granularity_and_currency_are_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        bad_granularity = await client.get(
            "/admin/billing/summary", params={"granularity": "week"}, headers=admin_headers
        )
        assert bad_granularity.status_code == 422
        bad_currency = await client.get(
            "/admin/billing/summary", params={"currency": "RUPEE"}, headers=admin_headers
        )
        assert bad_currency.status_code == 422
