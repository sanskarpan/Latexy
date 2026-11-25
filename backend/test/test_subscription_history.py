"""Subscription history: exactly-once writes, backfill and churn analytics."""

from __future__ import annotations

import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database import models
from app.services.payment_service import PaymentService
from app.services.subscription_history_service import (
    record_subscription_transition,
    snapshot,
    subscription_history_service,
)


def _year_month(value: datetime) -> str:
    return f"{value.year:04d}-{value.month:02d}"


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "free",
    status: str = "active",
    created_at: datetime | None = None,
) -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, subscription_plan, "
            "subscription_status, trial_used, created_at) "
            "VALUES (:id, :email, 'History User', :role, true, :plan, :status, false, :created)"
        ),
        {
            "id": user_id,
            "email": f"test_history_{user_id.replace('-', '')}@example.com",
            "role": role,
            "plan": plan,
            "status": status,
            "created": created_at or datetime.now(timezone.utc),
        },
    )
    await db.commit()
    return user_id


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_history_{uuid.uuid4().hex}"
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _create_subscription(
    db: AsyncSession,
    *,
    user_id: str,
    plan: str = "pro",
    status: str = "active",
    amount: int = 59900,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    provider_event_at: datetime | None = None,
) -> tuple[str, str]:
    subscription_id = str(uuid.uuid4())
    provider_subscription_id = f"sub_test_{uuid.uuid4().hex[:16]}"
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "provider_product_id, quoted_amount, quoted_tax_inclusive, plan_id, status, "
            "current_period_start, current_period_end, provider_event_at) "
            "VALUES (:id, :uid, 'dodo', :provider_sub, :product, :amount, true, :plan, "
            ":status, :start, :end, :event_at)"
        ),
        {
            "id": subscription_id,
            "uid": user_id,
            "provider_sub": provider_subscription_id,
            "product": f"p_test_{plan}",
            "amount": amount,
            "plan": plan,
            "status": status,
            "start": period_start or datetime.now(timezone.utc) - timedelta(days=30),
            "end": period_end or datetime.now(timezone.utc) + timedelta(days=30),
            "event_at": provider_event_at,
        },
    )
    await db.execute(
        text(
            "UPDATE users SET subscription_plan=:plan, subscription_status=:status, "
            "subscription_id=:sub WHERE id=:uid"
        ),
        {"plan": plan, "status": status, "sub": subscription_id, "uid": user_id},
    )
    await db.commit()
    return subscription_id, provider_subscription_id


async def _insert_history(
    db: AsyncSession,
    *,
    user_id: str,
    subscription_id: str,
    plan: str,
    status: str,
    effective_at: datetime,
    event_type: str = "status_changed",
    previous_plan: str | None = None,
    previous_status: str | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    reason: str = "provider_status_change",
) -> None:
    await db.execute(
        text(
            "INSERT INTO subscription_history (id, user_id, subscription_id, plan_id, "
            "previous_plan_id, status, previous_status, current_period_start, "
            "current_period_end, event_type, reason, source, effective_at) "
            "VALUES (gen_random_uuid(), :uid, :sid, :plan, :previous_plan, :status, "
            ":previous_status, :period_start, :period_end, :event_type, :reason, 'billing', :effective)"
        ),
        {
            "uid": user_id,
            "sid": subscription_id,
            "plan": plan,
            "previous_plan": previous_plan,
            "status": status,
            "previous_status": previous_status,
            "period_start": period_start,
            "period_end": period_end,
            "event_type": event_type,
            "reason": reason,
            "effective": effective_at,
        },
    )
    await db.commit()


async def _clear_history_users(db: AsyncSession) -> None:
    await db.execute(text("DELETE FROM users WHERE email LIKE 'test_history_%'"))
    await db.commit()


@pytest.fixture(autouse=True)
async def _isolate_history_users(db_session: AsyncSession):
    """Keep committed fixture rows from inflating unrelated cohort suites."""

    await _clear_history_users(db_session)
    yield
    await _clear_history_users(db_session)


async def _history_rows(
    db: AsyncSession, subscription_id: str
) -> list[tuple[str, str, str | None, str | None]]:
    rows = (
        await db.execute(
            text(
                "SELECT event_type, status, previous_plan_id, previous_status "
                "FROM subscription_history WHERE subscription_id=:sid "
                "ORDER BY effective_at, recorded_at"
            ),
            {"sid": subscription_id},
        )
    ).all()
    return [tuple(row) for row in rows]


class TestExactlyOnceRecording:
    async def test_duplicate_lifecycle_events_record_one_transition_each(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
        monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_BASIC_MONTHLY", "p_test_basic")
        user_id = await _create_user(db_session)
        subscription_id, provider_sub_id = await _create_subscription(
            db_session, user_id=user_id, status="checkout_pending"
        )
        service = PaymentService()
        paused_at = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
        changed_at = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
        cancelled_at = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)

        paused = {
            "payload_type": "Subscription",
            "subscription_id": provider_sub_id,
            "product_id": "p_test_pro",
            "status": "paused",
        }
        for _ in range(2):
            assert await service._handle_subscription_event(
                db_session,
                "subscription.paused",
                paused,
                {"timestamp": paused_at.isoformat()},
            ) == {"success": True}

        plan_change = {
            "payload_type": "Subscription",
            "subscription_id": provider_sub_id,
            "product_id": "p_test_basic",
            "status": "active",
            "currency": "INR",
            "tax_inclusive": True,
            "recurring_pre_tax_amount": 29900,
        }
        for _ in range(2):
            assert await service._handle_subscription_event(
                db_session,
                "subscription.plan_changed",
                plan_change,
                {"timestamp": changed_at.isoformat()},
            ) == {"success": True}

        cancelled = {
            "payload_type": "Subscription",
            "subscription_id": provider_sub_id,
            "product_id": "p_test_basic",
            "status": "cancelled",
            "metadata": {
                "latexy_intent_id": subscription_id,
                "latexy_user_id": user_id,
            },
        }
        for _ in range(2):
            assert await service._handle_subscription_event(
                db_session,
                "subscription.cancelled",
                cancelled,
                {"timestamp": cancelled_at.isoformat()},
            ) == {"success": True}

        rows = await _history_rows(db_session, subscription_id)
        assert rows == [
            ("status_changed", "paused", "pro", "checkout_pending"),
            ("plan_changed", "active", "pro", "paused"),
            ("cancelled", "cancelled", "basic", "active"),
        ]

    async def test_duplicate_payment_event_records_activation_once(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
        user_id = await _create_user(db_session)
        subscription_id, provider_sub_id = await _create_subscription(
            db_session, user_id=user_id, status="checkout_pending"
        )
        checkout_id = f"chk_test_{uuid.uuid4().hex[:16]}"
        await db_session.execute(
            text("UPDATE subscriptions SET provider_checkout_session_id=:checkout WHERE id=:sid"),
            {"checkout": checkout_id, "sid": subscription_id},
        )
        await db_session.commit()
        service = PaymentService()
        payment_payload = {
            "payload_type": "Payment",
            "payment_id": f"pay_test_{uuid.uuid4().hex[:16]}",
            "status": "succeeded",
            "currency": "INR",
            "total_amount": 59900,
            "tax": 5490,
            "customer": {"customer_id": "cust_history"},
            "checkout_session_id": checkout_id,
            "subscription_id": provider_sub_id,
            "product_cart": [{"product_id": "p_test_pro", "quantity": 1}],
            "metadata": {
                "latexy_intent_id": subscription_id,
                "latexy_user_id": user_id,
                "latexy_plan_id": "pro",
                "latexy_tax_inclusive": "true",
            },
        }
        event_at = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
        for _ in range(2):
            assert await service._handle_payment_succeeded(
                db_session, dict(payment_payload), {"timestamp": event_at.isoformat()}
            ) == {"success": True}

        rows = await _history_rows(db_session, subscription_id)
        assert rows == [("activated", "active", "pro", "checkout_pending")]


    async def test_history_row_rolls_back_with_the_billing_transaction(
        self, db_session: AsyncSession
    ) -> None:
        user_id = await _create_user(db_session)
        subscription_id, _ = await _create_subscription(
            db_session, user_id=user_id, status="active"
        )
        subscription = await db_session.get(models.Subscription, subscription_id)
        assert subscription is not None
        before = snapshot(subscription)
        subscription.status = "paused"
        assert await record_subscription_transition(
            db_session,
            subscription,
            before,
            reason="provider_status_change",
            effective_at=datetime(2026, 10, 5, 12, tzinfo=timezone.utc),
        ) is True
        assert await db_session.scalar(
            text("SELECT COUNT(*) FROM subscription_history WHERE subscription_id=:sid"),
            {"sid": subscription_id},
        ) == 1
        await db_session.rollback()
        assert await db_session.scalar(
            text("SELECT COUNT(*) FROM subscription_history WHERE subscription_id=:sid"),
            {"sid": subscription_id},
        ) == 0


class TestSubscriptionAnalytics:
    @pytest.fixture
    async def seeded(self, db_session: AsyncSession) -> dict[str, object]:
        await db_session.execute(
            text("DELETE FROM users WHERE email LIKE 'test_history_%'")
        )
        await db_session.commit()
        now = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
        period_start = now - timedelta(days=30)
        baseline = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)
        cohort_a = datetime(2026, 1, 15, 9, tzinfo=timezone.utc)
        cohort_b = datetime(2026, 2, 15, 9, tzinfo=timezone.utc)
        user_ids: list[str] = []
        subscription_ids: dict[str, str] = {}

        for index in range(6):
            user_id = await _create_user(
                db_session,
                plan="pro",
                created_at=cohort_a,
            )
            user_ids.append(user_id)
        for _ in range(4):
            user_ids.append(
                await _create_user(db_session, plan="pro", created_at=cohort_b)
            )

        # 1: stay on pro.
        sid, _ = await _create_subscription(
            db_session, user_id=user_ids[0], plan="pro", amount=59900,
            period_start=baseline, period_end=now + timedelta(days=30),
        )
        subscription_ids["steady"] = sid
        await _insert_history(
            db_session, user_id=user_ids[0], subscription_id=sid, plan="pro",
            status="active", effective_at=baseline,
            event_type="activated", reason="payment_succeeded",
            period_start=baseline, period_end=now + timedelta(days=30),
        )

        # 2: upgrade basic -> pro.
        sid, _ = await _create_subscription(
            db_session, user_id=user_ids[1], plan="basic", amount=29900,
            period_start=baseline, period_end=now + timedelta(days=30),
        )
        subscription_ids["upgrade"] = sid
        await _insert_history(
            db_session, user_id=user_ids[1], subscription_id=sid, plan="basic",
            status="active", effective_at=baseline,
            event_type="activated", reason="payment_succeeded",
            period_start=baseline, period_end=now + timedelta(days=30),
        )
        await _insert_history(
            db_session, user_id=user_ids[1], subscription_id=sid, plan="pro",
            status="active", previous_plan="basic", previous_status="active",
            effective_at=datetime(2026, 11, 5, 9, tzinfo=timezone.utc),
            event_type="plan_changed", reason="plan_change",
            period_start=baseline, period_end=now + timedelta(days=30),
        )
        await db_session.execute(
            text("UPDATE subscriptions SET plan_id='pro', quoted_amount=59900 WHERE id=:sid"),
            {"sid": sid},
        )
        await db_session.execute(
            text("UPDATE users SET subscription_plan='pro' WHERE id=:uid"),
            {"uid": user_ids[1]},
        )
        await db_session.commit()

        # 3: downgrade pro -> basic.
        sid, _ = await _create_subscription(
            db_session, user_id=user_ids[2], plan="basic", amount=29900,
            period_start=baseline, period_end=now + timedelta(days=30),
        )
        subscription_ids["downgrade"] = sid
        await _insert_history(
            db_session, user_id=user_ids[2], subscription_id=sid, plan="pro",
            status="active", effective_at=baseline,
            event_type="activated", reason="payment_succeeded",
            period_start=baseline, period_end=now + timedelta(days=30),
        )
        await _insert_history(
            db_session, user_id=user_ids[2], subscription_id=sid, plan="basic",
            status="active", previous_plan="pro", previous_status="active",
            effective_at=datetime(2026, 11, 6, 9, tzinfo=timezone.utc),
            event_type="plan_changed", reason="plan_change",
            period_start=baseline, period_end=now + timedelta(days=30),
        )
        # 4: churn.
        sid, _ = await _create_subscription(
            db_session, user_id=user_ids[3], plan="pro", status="cancelled", amount=59900,
            period_start=baseline, period_end=datetime(2026, 11, 7, 9, tzinfo=timezone.utc),
        )
        subscription_ids["churn"] = sid
        await _insert_history(
            db_session, user_id=user_ids[3], subscription_id=sid, plan="pro",
            status="active", effective_at=baseline,
            event_type="activated", reason="payment_succeeded",
            period_start=baseline, period_end=now + timedelta(days=30),
        )
        await _insert_history(
            db_session, user_id=user_ids[3], subscription_id=sid, plan="pro",
            status="cancelled", previous_plan="pro", previous_status="active",
            effective_at=datetime(2026, 11, 7, 9, tzinfo=timezone.utc),
            event_type="cancelled", reason="provider_status_change",
            period_start=baseline, period_end=datetime(2026, 11, 7, 9, tzinfo=timezone.utc),
        )

        # 5: cancellation scheduled, still paid.
        sid, _ = await _create_subscription(
            db_session, user_id=user_ids[4], plan="pro", status="cancel_scheduled", amount=59900,
            period_start=baseline, period_end=now + timedelta(days=30),
        )
        subscription_ids["scheduled"] = sid
        await _insert_history(
            db_session, user_id=user_ids[4], subscription_id=sid, plan="pro",
            status="active", effective_at=baseline,
            event_type="activated", reason="payment_succeeded",
            period_start=baseline, period_end=now + timedelta(days=30),
        )
        await _insert_history(
            db_session, user_id=user_ids[4], subscription_id=sid, plan="pro",
            status="cancel_scheduled", previous_plan="pro", previous_status="active",
            effective_at=datetime(2026, 11, 8, 9, tzinfo=timezone.utc),
            event_type="cancellation_scheduled", reason="cancellation_scheduled",
            period_start=baseline, period_end=now + timedelta(days=30),
        )

        # 6: new paid in the window.
        sid, _ = await _create_subscription(
            db_session, user_id=user_ids[5], plan="basic", amount=29900,
            period_start=datetime(2026, 11, 10, 9, tzinfo=timezone.utc),
            period_end=now + timedelta(days=30),
        )
        subscription_ids["new"] = sid
        await _insert_history(
            db_session, user_id=user_ids[5], subscription_id=sid, plan="basic",
            status="active", effective_at=datetime(2026, 11, 10, 9, tzinfo=timezone.utc),
            event_type="activated", reason="payment_succeeded",
            period_start=datetime(2026, 11, 10, 9, tzinfo=timezone.utc),
            period_end=now + timedelta(days=30),
        )

        # Four subscribers in a separate signup month must stay suppressed.
        for user_id in user_ids[6:]:
            sid, _ = await _create_subscription(
                db_session, user_id=user_id, plan="pro", amount=59900,
                period_start=baseline, period_end=now + timedelta(days=30),
            )
            await _insert_history(
                db_session, user_id=user_id, subscription_id=sid, plan="pro",
                status="active", effective_at=baseline,
                event_type="activated", reason="payment_succeeded",
                period_start=baseline, period_end=now + timedelta(days=30),
            )

        yield {
            "now": now,
            "cohort_a": _year_month(cohort_a),
            "cohort_b": _year_month(cohort_b),
            "user_ids": user_ids,
        }
        # Teardown runs even when a test fails, so this fixture never leaves a
        # synthetic 2026-01 cohort behind for unrelated retention suites.
        await db_session.execute(
            text("DELETE FROM users WHERE email LIKE 'test_history_%'")
        )
        await db_session.commit()

    async def test_movement_churn_and_reconciliation(
        self, db_session: AsyncSession, seeded: dict[str, object]
    ) -> None:
        now = seeded["now"]
        result = await subscription_history_service.subscription_analytics(
            db_session,
            days=30,
            now=now,
            signup_from=datetime(2026, 1, 1).date(),
            signup_to=datetime(2026, 2, 28).date(),
        )
        summary = result["summary"]
        assert result["suppressed"] is False
        assert summary["active_at_start"] == 9
        assert summary["active_at_end"] == 9
        assert summary["upgrades"] == 1
        assert summary["downgrades"] == 1
        assert summary["lateral_moves"] == 0
        assert summary["movement_total"] == 2
        assert summary["cancellations"] == 1
        assert summary["cancellation_scheduled"] == 1
        assert summary["churn_count"] == 1
        assert summary["churn_rate"] == 11.11
        assert summary["new_paid"] == 1

        movement = {(row["direction"], row["from_plan"], row["to_plan"]): row["count"] for row in result["movements"]}
        assert movement == {("upgrade", "basic", "pro"): 1, ("downgrade", "pro", "basic"): 1}

        plan_mix = {row["plan_id"]: row["subscriptions"] for row in result["plan_mix"]}
        assert plan_mix == {"pro": 7, "basic": 2}
        assert result["summary"]["mrr_minor"] == sum(row["mrr_minor"] for row in result["plan_mix"])
        assert result["reconciliation"]["plan_mix_total_matches_active_at_end"] is True
        assert result["reconciliation"]["movement_total_reconciles"] is True
        assert result["reconciliation"]["churn_reconciles"] is True
        assert all(check["ok"] for check in result["reconciliation"]["checks"])

        cohorts = {row["cohort"]: row for row in result["cohorts"]}
        assert seeded["cohort_a"] in cohorts
        assert seeded["cohort_b"] not in cohorts
        assert result["suppressed_cohorts"] >= 1
        assert cohorts[seeded["cohort_a"]]["churn_count"] == 1
        assert cohorts[seeded["cohort_a"]]["upgrades"] == 1

    async def test_cohort_filters_and_suppression(
        self, db_session: AsyncSession, seeded: dict[str, object]
    ) -> None:
        now = seeded["now"]
        cohort_a = str(seeded["cohort_a"])
        cohort_b = str(seeded["cohort_b"])

        selected = await subscription_history_service.subscription_analytics(
            db_session, days=30, now=now, signup_month=cohort_a
        )
        assert selected["suppressed"] is False
        assert selected["filters"]["signup_month"] == cohort_a
        assert selected["summary"]["active_at_end"] == 5
        assert [row["cohort"] for row in selected["cohorts"]] == [cohort_a]

        suppressed = await subscription_history_service.subscription_analytics(
            db_session, days=30, now=now, signup_month=cohort_b
        )
        assert suppressed["suppressed"] is True
        assert suppressed["summary"]["active_at_end"] == 0
        assert suppressed["cohorts"] == []

        ranged = await subscription_history_service.subscription_analytics(
            db_session,
            days=30,
            now=now,
            signup_from=datetime(2026, 1, 1).date(),
            signup_to=datetime(2026, 1, 31).date(),
        )
        assert ranged["suppressed"] is False
        assert ranged["filters"]["signup_from"] == "2026-01-01"
        assert ranged["filters"]["signup_to"] == "2026-01-31"

        plan_filtered = await subscription_history_service.subscription_analytics(
            db_session,
            days=30,
            now=now,
            signup_from=datetime(2026, 1, 1).date(),
            signup_to=datetime(2026, 2, 28).date(),
            plan="basic",
        )
        assert plan_filtered["filters"]["plan"] == "basic"
        assert plan_filtered["suppressed"] is True

        with pytest.raises(ValueError):
            await subscription_history_service.subscription_analytics(
                db_session,
                days=30,
                now=now,
                signup_month=cohort_a,
                signup_from=datetime(2026, 1, 1).date(),
            )

    async def test_endpoint_is_admin_only_and_aggregate_only(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        non_admin = await _create_user(db_session, role="user")
        non_admin_headers = await _session_headers(db_session, non_admin)
        forbidden = await client.get(
            "/admin/subscriptions/analytics?days=30", headers=non_admin_headers
        )
        assert forbidden.status_code == 403

        admin = await _create_user(db_session, role="admin")
        admin_headers = await _session_headers(db_session, admin)
        response = await client.get(
            "/admin/subscriptions/analytics?days=30", headers=admin_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["currency"] in {"INR", "USD", "EUR", "GBP"}
        assert body["minor_unit"] in {"paise", "minor_units"}
        assert body["minimum_cohort_size"] == 5
        assert "reconciliation" in body
        assert "email" not in response.text.lower()
        assert "example.com" not in response.text


class TestMigrationAndBackfill:
    def test_migration_revision_chain_and_documented_backfill(self) -> None:
        path = (
            Path(__file__).parents[1]
            / "alembic/versions/0084_subscription_history.py"
        )
        spec = importlib.util.spec_from_file_location("subscription_history_migration", path)
        migration = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(migration)

        assert migration.revision == "0084_subscription_history"
        assert migration.down_revision == "0083_compile_error_taxonomy"
        assert "ON CONFLICT" in migration.BACKFILL_SQL
        assert "previous_plan_id" in migration.BACKFILL_SQL
        assert "backfill" in migration.BACKFILL_SQL
        assert "drop_table" in Path(path).read_text()

    async def test_backfill_is_idempotent_and_preserves_current_state(
        self, db_session: AsyncSession
    ) -> None:
        path = (
            Path(__file__).parents[1]
            / "alembic/versions/0084_subscription_history.py"
        )
        spec = importlib.util.spec_from_file_location("subscription_history_migration", path)
        migration = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(migration)

        user_id = await _create_user(db_session)
        event_at = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
        subscription_id, _ = await _create_subscription(
            db_session,
            user_id=user_id,
            plan="pro",
            status="active",
            period_start=event_at - timedelta(days=1),
            period_end=event_at + timedelta(days=30),
            provider_event_at=event_at,
        )
        await db_session.execute(
            text("DELETE FROM subscription_history WHERE subscription_id=:sid"),
            {"sid": subscription_id},
        )
        await db_session.commit()

        await db_session.execute(text(migration.BACKFILL_SQL))
        await db_session.commit()
        await db_session.execute(text(migration.BACKFILL_SQL))
        await db_session.commit()

        rows = (
            await db_session.execute(
                text(
                    "SELECT plan_id, status, previous_plan_id, previous_status, "
                    "event_type, reason, source, effective_at "
                    "FROM subscription_history WHERE subscription_id=:sid"
                ),
                {"sid": subscription_id},
            )
        ).all()
        assert len(rows) == 1
        row = rows[0]
        assert (row.plan_id, row.status) == ("pro", "active")
        assert row.previous_plan_id is None
        assert row.previous_status is None
        assert (row.event_type, row.reason, row.source) == (
            "backfill",
            "backfill",
            "backfill",
        )
        assert row.effective_at == event_at

    async def test_live_schema_has_allowlists_and_natural_key(
        self, db_session: AsyncSession
    ) -> None:
        columns = {
            row.column_name
            for row in (
                await db_session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name='subscription_history'"
                    )
                )
            ).all()
        }
        assert {
            "id",
            "user_id",
            "subscription_id",
            "plan_id",
            "previous_plan_id",
            "status",
            "previous_status",
            "current_period_start",
            "current_period_end",
            "event_type",
            "reason",
            "source",
            "effective_at",
            "recorded_at",
        } == columns
        assert not {"email", "name", "document", "payload", "token"} & columns
        constraint = (
            await db_session.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname='uq_subscription_history_transition'"
                )
            )
        ).scalar_one()
        assert "UNIQUE" in constraint
