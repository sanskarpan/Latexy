"""Weekly/lifetime plan health: reconciliation, refund access, alerts and privacy."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import admin_alert_service
from app.services.admin_plan_health_service import (
    PaymentRow,
    RefundRow,
    RenewalEventRow,
    SubscriptionRow,
    build_plan_health,
)
from app.services.payment_service import PaymentService
from test.test_admin_control_room_api import _create_user, _headers, _session_headers
from test.test_admin_revenue_dashboard_api import (
    _insert_dispute_event,
    _insert_payment,
    _insert_refund,
)

PLANS = ("weekly", "lifetime")
ACTIVE = ("active", "cancel_scheduled", "past_due", "on_hold", "paused")
SETTLED = ("paid", "partially_refunded", "captured", "refunded", "succeeded")
NON_ACQUISITION = ("checkout_pending", "checkout_unknown", "created", "pending", "failed")


async def _create_plan_subscription(
    db: AsyncSession,
    *,
    user_id: str,
    plan_id: str,
    status: str = "active",
    created_at: datetime | None = None,
    cancelled_at: datetime | None = None,
    period_end: datetime | None = None,
    amount: int | None = None,
) -> str:
    subscription_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "plan_id, status, current_period_start, current_period_end, cancelled_at, "
            "quoted_amount, created_at) "
            "VALUES (:id, :uid, 'dodo', :provider_sub, :plan, :status, :start, :end, "
            ":cancelled, :amount, :created)"
        ),
        {
            "id": subscription_id,
            "uid": user_id,
            "provider_sub": f"sub_{uuid.uuid4().hex[:12]}",
            "plan": plan_id,
            "status": status,
            "start": (created_at or now) - timedelta(days=7),
            "end": period_end,
            "cancelled": cancelled_at,
            "amount": amount,
            "created": created_at or now,
        },
    )
    await db.commit()
    return subscription_id


async def _set_user_entitlement(db: AsyncSession, *, user_id: str, plan_id: str, subscription_id: str) -> None:
    await db.execute(
        text(
            "UPDATE users SET subscription_plan = :plan, subscription_status = 'active', "
            "subscription_id = :sub WHERE id = :uid"
        ),
        {"plan": plan_id, "sub": subscription_id, "uid": user_id},
    )
    await db.commit()


async def _lifetime_purchase(
    db: AsyncSession,
    *,
    status: str = "active",
    amount: int = 199900,
    created_at: datetime | None = None,
) -> tuple[str, str, str, str]:
    user_id, email = await _create_user(db)
    subscription_id = await _create_plan_subscription(
        db, user_id=user_id, plan_id="lifetime", status=status, amount=amount
    )
    await _set_user_entitlement(db, user_id=user_id, plan_id="lifetime", subscription_id=subscription_id)
    payment_id, provider_payment_id = await _insert_payment(
        db,
        user_id=user_id,
        subscription_id=subscription_id,
        amount=amount,
        created_at=created_at or datetime.now(timezone.utc),
    )
    return user_id, email, subscription_id, payment_id


async def _plan_health(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    days: int = 30,
) -> dict:
    response = await client.get("/admin/analytics/plan-health", params={"days": days}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _expected_counts(db: AsyncSession, *, plan_id: str, start: datetime, now: datetime) -> dict:
    end = datetime.now(timezone.utc) + timedelta(seconds=5)
    active = int(
        (
            await db.execute(
                text(
                    "SELECT count(*) FROM subscriptions WHERE plan_id = :plan "
                    "AND status = ANY(:statuses) "
                    "AND (current_period_end IS NULL OR current_period_end >= :now)"
                ),
                {"plan": plan_id, "statuses": list(ACTIVE), "now": end},
            )
        ).scalar()
        or 0
    )
    new = int(
        (
            await db.execute(
                text(
                    "SELECT count(*) FROM subscriptions WHERE plan_id = :plan "
                    "AND created_at >= :start AND created_at < :now "
                    "AND NOT (status = ANY(:excluded))"
                ),
                {
                    "plan": plan_id,
                    "start": start,
                    "now": end,
                    "excluded": list(NON_ACQUISITION),
                },
            )
        ).scalar()
        or 0
    )
    cancelled = int(
        (
            await db.execute(
                text(
                    "SELECT count(*) FROM subscriptions WHERE plan_id = :plan "
                    "AND cancelled_at >= :start AND cancelled_at < :now"
                ),
                {"plan": plan_id, "start": start, "now": end},
            )
        ).scalar()
        or 0
    )
    gross = int(
        (
            await db.execute(
                text(
                    "SELECT coalesce(sum(p.amount), 0) FROM payments p "
                    "JOIN subscriptions s ON s.id = p.subscription_id "
                    "WHERE s.plan_id = :plan AND p.status = ANY(:statuses) "
                    "AND p.created_at >= :start AND p.created_at < :now"
                ),
                {
                    "plan": plan_id,
                    "statuses": list(SETTLED),
                    "start": start,
                    "now": end,
                },
            )
        ).scalar()
        or 0
    )
    refunded = int(
        (
            await db.execute(
                text(
                    "SELECT coalesce(sum(r.amount), 0) FROM payment_refunds r "
                    "JOIN payments p ON p.id = r.payment_id "
                    "JOIN subscriptions s ON s.id = p.subscription_id "
                    "WHERE s.plan_id = :plan AND r.status = 'succeeded' "
                    "AND r.created_at >= :start AND r.created_at < :now"
                ),
                {"plan": plan_id, "start": start, "now": end},
            )
        ).scalar()
        or 0
    )
    return {
        "active": active,
        "new": new,
        "cancelled": cancelled,
        "gross": gross,
        "refunded": refunded,
    }


def _all_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys |= _all_keys(child)
    elif isinstance(value, list):
        for child in value:
            keys |= _all_keys(child)
    return keys


def test_rate_math_for_lifetime_refund_and_weekly_renewal_churn() -> None:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)
    subscriptions = [
        SubscriptionRow(
            id=f"sub-{index}",
            user_id=f"user-{index}",
            plan_id="lifetime",
            status="active",
            created_at=start + timedelta(days=1),
            cancelled_at=None,
            current_period_end=None,
        )
        for index in range(2)
    ]
    subscriptions += [
        SubscriptionRow(
            id=f"weekly-{index}",
            user_id=f"weekly-user-{index}",
            plan_id="weekly",
            status="active",
            created_at=start + timedelta(days=1),
            cancelled_at=None,
            current_period_end=now + timedelta(days=3),
        )
        for index in range(2)
    ]
    payments = [
        PaymentRow(
            plan_id="lifetime",
            subscription_id=f"sub-{index}",
            amount=199900,
            status="paid",
            created_at=start + timedelta(days=1),
        )
        for index in range(2)
    ]
    refunds = [
        RefundRow(
            plan_id="lifetime",
            subscription_id="sub-0",
            amount=199900,
            status="succeeded",
            created_at=start + timedelta(days=2),
        )
    ]
    renewals = [
        RenewalEventRow(
            plan_id="weekly",
            subscription_id=f"weekly-{index}",
            effective_at=start + timedelta(days=2),
        )
        for index in range(2)
    ]
    body = build_plan_health(
        subscriptions=subscriptions,
        payments=payments,
        refunds=refunds,
        renewal_events=renewals,
        chargebacks=[],
        lifetime_sales=2,
        lifetime_refunds=1,
        now=now,
        window_days=30,
        currency="INR",
    )

    lifetime = body["plans"]["lifetime"]
    assert lifetime["lifetime_refund_rate_pct"] == 50.0
    assert lifetime["refunds"]["amount_rate_pct"] == 50.0
    assert lifetime["revenue"]["net_minor"] == 199900

    weekly = body["plans"]["weekly"]
    assert weekly["renewal"]["renewals"] == 2
    assert weekly["renewal"]["cancellations"] == 0
    assert weekly["renewal"]["renewal_rate_pct"] == 100.0
    assert weekly["renewal"]["churn_rate_pct"] == 0.0
    assert body["reconciliation"]["balanced"] is True
    assert body["minimum_cohort_size"] == 5


async def test_plan_health_counts_reconcile_to_subscriptions_and_payments(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _headers(db_session)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)

    for _ in range(3):
        user_id, _email = await _create_user(db_session)
        subscription_id = await _create_plan_subscription(
            db_session,
            user_id=user_id,
            plan_id="weekly",
            period_end=now + timedelta(days=5),
            amount=49900,
        )
        await _insert_payment(
            db_session,
            user_id=user_id,
            subscription_id=subscription_id,
            amount=49900,
            created_at=now - timedelta(days=1),
        )

    cancelled_user, _ = await _create_user(db_session)
    await _create_plan_subscription(
        db_session,
        user_id=cancelled_user,
        plan_id="weekly",
        status="cancelled",
        created_at=now - timedelta(days=10),
        cancelled_at=now - timedelta(days=2),
        period_end=now - timedelta(days=2),
        amount=49900,
    )

    lifetime_payment_ids: list[tuple[str, str, str]] = []
    for _ in range(2):
        user_id, _email, subscription_id, payment_id = await _lifetime_purchase(db_session)
        lifetime_payment_ids.append((user_id, subscription_id, payment_id))

    refunded_user, _email, refunded_subscription_id, refunded_payment_id = await _lifetime_purchase(db_session)
    await db_session.execute(
        text("UPDATE subscriptions SET status = 'refunded', cancelled_at = :now WHERE id = :id"),
        {"now": now - timedelta(days=3), "id": refunded_subscription_id},
    )
    await db_session.execute(
        text("UPDATE payments SET status = 'refunded' WHERE id = :id"),
        {"id": refunded_payment_id},
    )
    await _insert_refund(
        db_session,
        payment_id=refunded_payment_id,
        amount=199900,
        created_at=now - timedelta(days=3),
    )
    await db_session.commit()

    body = await _plan_health(client, admin)
    for plan_id in PLANS:
        expected = await _expected_counts(db_session, plan_id=plan_id, start=start, now=now)
        plan = body["plans"][plan_id]
        assert plan["active_subscriptions"] == expected["active"], plan_id
        assert plan["new_subscriptions"] == expected["new"], plan_id
        assert plan["cancelled_subscriptions"] == expected["cancelled"], plan_id
        assert plan["revenue"]["gross_minor"] == expected["gross"], plan_id
        assert plan["refunds"]["amount_minor"] == expected["refunded"], plan_id
        assert plan["revenue"]["net_minor"] == plan["revenue"]["gross_minor"] - plan["refunds"]["amount_minor"]
    assert body["plans"]["lifetime"]["lifetime_refunds"] >= 1
    assert body["reconciliation"]["balanced"] is True


async def test_full_lifetime_refund_revokes_access_and_updates_plan_health(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _headers(db_session)
    user_id, email, subscription_id, payment_id = await _lifetime_purchase(db_session)
    provider_payment_id = (
        await db_session.execute(text("SELECT provider_payment_id FROM payments WHERE id = :id"), {"id": payment_id})
    ).scalar_one()
    for _ in range(5):
        await _lifetime_purchase(db_session)

    result = await PaymentService()._handle_refund_event(
        db_session,
        "refund.succeeded",
        {
            "refund_id": f"ref_{uuid.uuid4().hex[:12]}",
            "payment_id": provider_payment_id,
            "amount": 199900,
            "currency": "INR",
            "status": "succeeded",
        },
    )
    assert result == {"success": True}

    access = (
        await db_session.execute(
            text(
                "SELECT u.subscription_plan, u.subscription_status, s.status "
                "FROM users u JOIN subscriptions s ON s.id = :sub WHERE u.id = :uid"
            ),
            {"sub": subscription_id, "uid": user_id},
        )
    ).one()
    assert access[0] == "free"
    assert access[1] == "refunded"
    assert access[2] == "refunded"

    body = await _plan_health(client, admin)
    lifetime = body["plans"]["lifetime"]
    assert lifetime["lifetime_sales"] >= 6
    assert lifetime["lifetime_refunds"] >= 1
    assert lifetime["lifetime_refund_rate_pct"] >= 10.0
    assert lifetime["lifetime_refunds"] < lifetime["lifetime_sales"]
    assert lifetime["refunded_subscriptions"] >= 1
    current = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM subscriptions WHERE plan_id = 'lifetime' "
                "AND status = ANY(:statuses) "
                "AND (current_period_end IS NULL OR current_period_end >= :now)"
            ),
            {"statuses": list(ACTIVE), "now": datetime.now(timezone.utc)},
        )
    ).scalar_one()
    assert lifetime["active_subscriptions"] == int(current)
    assert email not in json.dumps(body)
    assert "user_id" not in json.dumps(body)


async def test_risk_flags_and_alert_outlier_are_advisory_and_aggregate_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _headers(db_session)
    now = datetime.now(timezone.utc)

    lifetime_payment_ids: list[str] = []
    for _ in range(6):
        _user_id, _email, _subscription_id, payment_id = await _lifetime_purchase(db_session)
        lifetime_payment_ids.append(payment_id)
    await _insert_refund(
        db_session,
        payment_id=lifetime_payment_ids[0],
        amount=199900,
        created_at=now - timedelta(days=1),
    )
    await db_session.execute(
        text("UPDATE payments SET status = 'refunded' WHERE id = :id"),
        {"id": lifetime_payment_ids[0]},
    )
    await db_session.commit()

    cancellations = 0
    for _ in range(5):
        user_id, _email = await _create_user(db_session)
        await _create_plan_subscription(
            db_session,
            user_id=user_id,
            plan_id="weekly",
            status="cancelled",
            created_at=now - timedelta(days=12),
            cancelled_at=now - timedelta(days=2),
            period_end=now - timedelta(days=2),
        )
        cancellations += 1
    for _ in range(3):
        user_id, _email = await _create_user(db_session)
        await _create_plan_subscription(
            db_session,
            user_id=user_id,
            plan_id="weekly",
            period_end=now + timedelta(days=4),
        )
        await _create_plan_subscription(
            db_session,
            user_id=user_id,
            plan_id="lifetime",
            status="refunded",
            cancelled_at=now - timedelta(days=4),
        )

    provider_payment_id = (
        await db_session.execute(
            text("SELECT provider_payment_id FROM payments WHERE id = :id"),
            {"id": lifetime_payment_ids[0]},
        )
    ).scalar_one()
    await _insert_dispute_event(
        db_session,
        event_type="dispute.opened",
        resource_id=provider_payment_id,
        received_at=now - timedelta(hours=2),
    )

    body = await _plan_health(client, admin)
    flags = {(flag["plan_id"], flag["code"]) for flag in body["risk_flags"]}
    assert ("lifetime", "lifetime_refund_rate_high") in flags
    assert ("lifetime", "chargebacks_open") in flags
    assert ("weekly", "weekly_churn_rate_high") in flags
    for flag in body["risk_flags"]:
        assert flag["advisory"] is True
        assert flag["requires_human_review"] is True
        assert flag["auto_action"] == "none"
    assert body["advisory"]["automatic_refund"] is False
    assert body["advisory"]["automatic_downgrade"] is False
    assert body["advisory"]["automatic_cancellation"] is False
    assert body["advisory"]["automatic_grant"] is False
    assert body["plans"]["lifetime"]["chargebacks"]["open_count"] >= 1
    assert cancellations == body["plans"]["weekly"]["cancelled_subscriptions"] or (
        body["plans"]["weekly"]["cancelled_subscriptions"] >= cancellations
    )

    signals = await admin_alert_service.collect_signals(db_session, now)
    plan_signals = [signal for signal in signals if signal["kind"] == "billing.plan_health"]
    assert plan_signals
    assert any("lifetime_refund_rate_high" in signal["dedupe_key"] for signal in plan_signals)
    for signal in plan_signals:
        assert signal["payload"]["advisory"] is True
        assert signal["payload"]["requires_human_review"] is True
        assert signal["payload"]["auto_action"] == "none"
        assert "@" not in json.dumps(signal["payload"])

    await admin_alert_service.evaluate_alerts(db_session, now=now)
    row = (
        await db_session.execute(
            text(
                "SELECT kind, severity, payload FROM admin_alerts WHERE dedupe_key LIKE 'billing.plan_health.%' LIMIT 1"
            )
        )
    ).one_or_none()
    assert row is not None
    assert row[0] == "billing.plan_health"
    assert row[1] in {"critical", "high"}


async def test_small_cohorts_are_suppressed_and_no_pii_is_returned(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _headers(db_session)
    emails: list[str] = []
    for _ in range(4):
        _user_id, email = await _create_user(db_session)
        emails.append(email)
        await _create_plan_subscription(
            db_session,
            user_id=_user_id,
            plan_id="lifetime",
            period_end=None,
        )

    body = await _plan_health(client, admin)
    serialized = json.dumps(body)
    assert all(
        monthly["users"] >= body["minimum_cohort_size"] for monthly in body["plans"]["lifetime"]["retention"]["cohorts"]
    )
    assert all(
        monthly["users"] >= body["minimum_cohort_size"] for monthly in body["plans"]["weekly"]["retention"]["cohorts"]
    )
    assert body["minimum_cohort_size"] == 5
    keys = _all_keys(body)
    for forbidden in (
        "user_id",
        "email",
        "provider_payment_id",
        "provider_subscription_id",
        "customer_id",
        "payment_method",
    ):
        assert forbidden not in keys
    for email in emails:
        assert email not in serialized


async def test_plan_health_is_admin_only(client: AsyncClient, db_session: AsyncSession) -> None:
    admin = await _headers(db_session)
    user = await _headers(db_session, role="user")
    support = await _headers(db_session, role="support")

    allowed = await client.get("/admin/analytics/plan-health", headers=admin)
    assert allowed.status_code == 200, allowed.text

    denied = await client.get("/admin/analytics/plan-health", headers=user)
    assert denied.status_code == 403
    support_denied = await client.get("/admin/analytics/plan-health", headers=support)
    assert support_denied.status_code == 403
    anonymous = await client.get("/admin/analytics/plan-health")
    assert anonymous.status_code == 401


async def test_missing_session_cannot_read_plan_health(client: AsyncClient, db_session: AsyncSession) -> None:
    # An expired/forged bearer is denied before any aggregate is computed.
    headers = await _session_headers(db_session, str(uuid.uuid4()))
    response = await client.get("/admin/analytics/plan-health", headers=headers)
    assert response.status_code in {401, 403}
