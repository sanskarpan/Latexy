"""Dunning status history, recovery reporting and advisory alerts (#2103)."""

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
from app.services import admin_alert_service
from app.services.dunning_history_service import (
    MIN_GROUP_SIZE,
    dunning_recovery_analytics,
)
from app.services.payment_service import PaymentService

PREFIX = "test_dunning_"
EMAIL_PREFIX = "test_dunning_%@example.com"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "free",
    status: str = "active",
    created_at: datetime | None = None,
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    token = f"test_sess_dunning_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, created_at) "
            "VALUES (:id, :email, 'Dunning User', :role, true, :plan, :status, false, :created)"
        ),
        {
            "id": user_id,
            "email": f"{PREFIX}{user_id.replace('-', '')}@example.com",
            "role": role,
            "plan": plan,
            "status": status,
            "created": created_at or _now(),
        },
    )
    await db.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": _now() + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return user_id, {"Authorization": f"Bearer {token}"}


async def _create_subscription(
    db: AsyncSession,
    *,
    user_id: str,
    plan: str = "pro",
    status: str = "past_due",
    provider_event_at: datetime | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> tuple[str, str]:
    subscription_id = str(uuid.uuid4())
    provider_subscription_id = f"sub_dunning_{uuid.uuid4().hex[:16]}"
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "provider_product_id, quoted_amount, quoted_tax_inclusive, plan_id, status, "
            "current_period_start, current_period_end, provider_event_at) "
            "VALUES (:id, :uid, 'dodo', :provider_sub, :product, 59900, true, :plan, "
            ":status, :start, :end, :event_at)"
        ),
        {
            "id": subscription_id,
            "uid": user_id,
            "provider_sub": provider_subscription_id,
            "product": f"p_test_{plan}",
            "plan": plan,
            "status": status,
            "start": period_start or _now() - timedelta(days=10),
            "end": period_end or _now() + timedelta(days=20),
            "event_at": provider_event_at,
        },
    )
    await db.execute(
        text(
            "UPDATE users SET subscription_plan=:plan, subscription_status=:status, subscription_id=:sub WHERE id=:uid"
        ),
        {"plan": plan, "status": status, "sub": subscription_id, "uid": user_id},
    )
    await db.commit()
    return subscription_id, provider_subscription_id


async def _insert_status(
    db: AsyncSession,
    *,
    user_id: str,
    subscription_id: str,
    plan: str,
    status: str,
    event_at: datetime,
    previous_status: str | None,
    event_type: str,
    applied: bool = True,
    reason: str = "provider_status_change",
) -> None:
    await db.execute(
        text(
            "INSERT INTO subscription_status_history "
            "(id, user_id, subscription_id, plan_id, status, previous_status, "
            "event_type, reason, source, provider_event_at, applied) "
            "VALUES (gen_random_uuid(), :uid, :sid, :plan, :status, :previous, "
            ":event_type, :reason, 'billing', :event_at, :applied)"
        ),
        {
            "uid": user_id,
            "sid": subscription_id,
            "plan": plan,
            "status": status,
            "previous": previous_status,
            "event_type": event_type,
            "reason": reason,
            "event_at": event_at,
            "applied": applied,
        },
    )
    await db.commit()


async def _clean(db: AsyncSession) -> None:
    await db.execute(
        text('DELETE FROM session WHERE "userId" IN (SELECT id::text FROM users WHERE email LIKE :email)'),
        {"email": EMAIL_PREFIX},
    )
    await db.execute(text("DELETE FROM admin_alerts WHERE kind = 'billing.dunning_recovery'"))
    await db.execute(text("DELETE FROM users WHERE email LIKE :email"), {"email": EMAIL_PREFIX})
    await db.commit()


@pytest.fixture(autouse=True)
async def _isolate_dunning_users(db_session: AsyncSession):
    await _clean(db_session)
    yield
    await _clean(db_session)


async def _history_rows(db: AsyncSession, subscription_id: str) -> list[tuple]:
    rows = (
        await db.execute(
            text(
                "SELECT status, previous_status, event_type, applied "
                "FROM subscription_status_history WHERE subscription_id=:sid "
                "ORDER BY provider_event_at, recorded_at"
            ),
            {"sid": subscription_id},
        )
    ).all()
    return [tuple(row) for row in rows]


async def test_out_of_order_and_duplicate_webhooks_are_idempotent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, _ = await _create_user(db_session)
    subscription_id, provider_sub_id = await _create_subscription(
        db_session,
        user_id=user_id,
        status="past_due",
        provider_event_at=datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
    )
    await _insert_status(
        db_session,
        user_id=user_id,
        subscription_id=subscription_id,
        plan="pro",
        status="past_due",
        previous_status="active",
        event_at=datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
        event_type="dunning_started",
        reason="payment_failed",
    )
    service = PaymentService()
    active = {
        "payload_type": "Subscription",
        "subscription_id": provider_sub_id,
        "product_id": "p_test_pro",
        "status": "active",
        "customer": {"customer_id": "cus_dunning"},
        "metadata": {
            "latexy_intent_id": subscription_id,
            "latexy_user_id": user_id,
        },
    }
    recovered_at = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    assert await service._handle_subscription_event(
        db_session,
        "subscription.updated",
        active,
        {"timestamp": recovered_at.isoformat()},
    ) == {"success": True}

    # A duplicate delivery cannot add a second recovery row.
    assert await service._handle_subscription_event(
        db_session,
        "subscription.updated",
        dict(active),
        {"timestamp": recovered_at.isoformat()},
    ) == {"success": True}

    # A delayed older past-due snapshot is retained for chronology but must not
    # regress the live subscription or provider_event_at watermark.
    stale_at = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
    stale = dict(active)
    stale["status"] = "past_due"
    for _ in range(2):
        assert await service._handle_subscription_event(
            db_session,
            "subscription.past_due",
            stale,
            {"timestamp": stale_at.isoformat()},
        ) == {"success": True}

    subscription = (
        await db_session.execute(
            text("SELECT status, provider_event_at FROM subscriptions WHERE id=:sid"),
            {"sid": subscription_id},
        )
    ).one()
    assert subscription.status == "active"
    assert subscription.provider_event_at == recovered_at

    rows = await _history_rows(db_session, subscription_id)
    assert rows == [
        ("past_due", "active", "dunning_started", True),
        ("past_due", "past_due", "status_observed", False),
        ("active", "past_due", "recovered", True),
    ]

    report = await dunning_recovery_analytics(
        db_session,
        start=datetime(2026, 10, 1, tzinfo=timezone.utc),
        end=datetime(2026, 10, 5, tzinfo=timezone.utc),
        now=datetime(2026, 10, 5, tzinfo=timezone.utc),
    )
    assert report["summary"]["dunning_cases"] == 1
    assert report["summary"]["recovered"] == 1
    assert report["summary"]["recovery_rate"] == 100.0
    assert report["summary"]["median_time_to_active_seconds"] == 172800
    assert all(check["ok"] for check in report["reconciliation"]["checks"])


async def test_recovery_metrics_reconcile_and_filters_work(
    db_session: AsyncSession,
) -> None:
    started = datetime(2026, 11, 1, 9, tzinfo=timezone.utc)
    cohort_a = datetime(2026, 1, 15, 9, tzinfo=timezone.utc)
    cohort_b = datetime(2026, 2, 15, 9, tzinfo=timezone.utc)
    now = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)

    async def seed_episode(
        *,
        created_at: datetime,
        plan: str,
        start_day: int,
        outcome: str,
        outcome_day: int | None,
    ) -> None:
        user_id, _ = await _create_user(
            db_session,
            plan=plan,
            status="active",
            created_at=created_at,
        )
        current_status = {
            "recovered": "active",
            "cancelled": "cancelled",
            "open": "past_due",
        }[outcome]
        subscription_id, _ = await _create_subscription(
            db_session,
            user_id=user_id,
            plan=plan,
            status=current_status,
            period_end=now + timedelta(days=30),
        )
        await _insert_status(
            db_session,
            user_id=user_id,
            subscription_id=subscription_id,
            plan=plan,
            status="past_due",
            previous_status="active",
            event_at=started + timedelta(days=start_day - 1),
            event_type="dunning_started",
            reason="payment_failed",
        )
        if outcome_day is not None:
            event_type = "recovered" if outcome == "recovered" else "cancelled"
            final_status = "active" if outcome == "recovered" else "cancelled"
            await _insert_status(
                db_session,
                user_id=user_id,
                subscription_id=subscription_id,
                plan=plan,
                status=final_status,
                previous_status="past_due",
                event_at=started + timedelta(days=outcome_day - 1),
                event_type=event_type,
                reason=("payment_succeeded" if outcome == "recovered" else "provider_status_change"),
            )

    # Five pro cases: recoveries at 2/4/6 days, one cancellation at 2 days and
    # one still open.
    for start_day, outcome, outcome_day in (
        (1, "recovered", 3),
        (1, "recovered", 5),
        (1, "recovered", 7),
        (2, "cancelled", 4),
        (3, "open", None),
    ):
        await seed_episode(
            created_at=cohort_a,
            plan="pro",
            start_day=start_day,
            outcome=outcome,
            outcome_day=outcome_day,
        )
    # Five basic cases: recoveries at 1/3/5/7 days and one cancellation at 4.
    for start_day, outcome_day in ((4, 5), (5, 8), (6, 11), (7, 14), (8, 12)):
        await seed_episode(
            created_at=cohort_b,
            plan="basic",
            start_day=start_day,
            outcome="recovered" if start_day != 8 else "cancelled",
            outcome_day=outcome_day,
        )

    signup_filter = {
        "signup_from": datetime(2026, 1, 1).date(),
        "signup_to": datetime(2026, 2, 28).date(),
    }
    report = await dunning_recovery_analytics(
        db_session,
        start=datetime(2026, 11, 1, tzinfo=timezone.utc),
        end=now,
        now=now,
        **signup_filter,
    )
    summary = report["summary"]
    assert summary["dunning_cases"] == 10
    assert summary["recovered"] == 7
    assert summary["cancelled"] == 2
    assert summary["open_cases"] == 1
    assert summary["recovery_rate"] == 70.0
    assert summary["past_due"] == 1
    assert summary["on_hold"] == 0
    # Active-to-recovery durations are 1/2/3/4/5/6/7 days, so the median is
    # 4 days.
    assert summary["median_time_to_active_seconds"] == 345600
    # Cancellation durations are 2 days (pro) and 4 days (basic).
    assert summary["median_time_to_cancel_seconds"] == 259200
    assert report["suppressed"] is False
    assert report["advisory"]["active"] is True

    plans = {row["plan_id"]: row for row in report["by_plan"]}
    assert plans["pro"]["dunning_cases"] == 5
    assert plans["pro"]["recovered"] == 3
    assert plans["pro"]["open_cases"] == 1
    assert plans["pro"]["recovery_rate"] == 60.0
    assert plans["basic"]["dunning_cases"] == 5
    assert plans["basic"]["recovered"] == 4
    assert plans["basic"]["recovery_rate"] == 80.0

    cohorts = {row["cohort"]: row for row in report["cohorts"]}
    assert cohorts["2026-01"]["dunning_cases"] == 5
    assert cohorts["2026-02"]["dunning_cases"] == 5

    plan_filtered = await dunning_recovery_analytics(
        db_session,
        start=datetime(2026, 11, 1, tzinfo=timezone.utc),
        end=now,
        now=now,
        plan="basic",
        **signup_filter,
    )
    assert plan_filtered["summary"]["dunning_cases"] == 5
    assert plan_filtered["summary"]["recovered"] == 4
    assert plan_filtered["summary"]["recovery_rate"] == 80.0
    assert plan_filtered["summary"]["past_due"] == 0
    assert [row["plan_id"] for row in plan_filtered["by_plan"]] == ["basic"]

    cohort_filtered = await dunning_recovery_analytics(
        db_session,
        start=datetime(2026, 11, 1, tzinfo=timezone.utc),
        end=now,
        now=now,
        signup_month="2026-01",
    )
    assert cohort_filtered["summary"]["dunning_cases"] == 5
    assert cohort_filtered["summary"]["recovered"] == 3
    assert [row["plan_id"] for row in cohort_filtered["by_plan"]] == ["pro"]

    date_filtered = await dunning_recovery_analytics(
        db_session,
        start=datetime(2026, 11, 6, tzinfo=timezone.utc),
        end=now,
        now=now,
        **signup_filter,
    )
    # Basic starts on 11-06, 11-07 and 11-08 remain in range.
    assert date_filtered["summary"]["dunning_cases"] == 3
    assert date_filtered["filters"]["start"] == "2026-11-06T00:00:00+00:00"

    with pytest.raises(ValueError):
        await dunning_recovery_analytics(
            db_session,
            start=datetime(2026, 11, 1, tzinfo=timezone.utc),
            end=now,
            signup_month="2026-01",
            signup_from=datetime(2026, 1, 1).date(),
        )

    assert all(check["ok"] for check in report["reconciliation"]["checks"])
    assert report["reconciliation"]["by_plan_cases"] == 10
    assert report["reconciliation"]["cohort_cases"] == 10


async def test_status_history_rows_are_append_only(db_session_factory, db_session: AsyncSession) -> None:
    user_id, _ = await _create_user(db_session)
    subscription_id, _ = await _create_subscription(db_session, user_id=user_id, plan="pro", status="past_due")
    await _insert_status(
        db_session,
        user_id=user_id,
        subscription_id=subscription_id,
        plan="pro",
        status="past_due",
        previous_status="active",
        event_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        event_type="dunning_started",
    )

    async with db_session_factory() as other:
        with pytest.raises(Exception) as excinfo:
            await other.execute(
                text("UPDATE subscription_status_history SET reason='tampered' WHERE subscription_id=:sid"),
                {"sid": subscription_id},
            )
            await other.commit()
        await other.rollback()
    assert "append-only" in str(excinfo.value).lower()
    assert (
        await db_session.scalar(
            text("SELECT reason FROM subscription_status_history WHERE subscription_id=:sid"),
            {"sid": subscription_id},
        )
        == "provider_status_change"
    )


async def test_small_plan_and_cohort_cells_are_suppressed(
    db_session: AsyncSession,
) -> None:
    started = datetime(2026, 11, 1, 9, tzinfo=timezone.utc)
    now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
    for index in range(5):
        user_id, _ = await _create_user(
            db_session,
            plan="pro",
            created_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        )
        subscription_id, _ = await _create_subscription(db_session, user_id=user_id, plan="pro", status="active")
        await _insert_status(
            db_session,
            user_id=user_id,
            subscription_id=subscription_id,
            plan="pro",
            status="past_due",
            previous_status="active",
            event_at=started + timedelta(hours=index),
            event_type="dunning_started",
        )
        await _insert_status(
            db_session,
            user_id=user_id,
            subscription_id=subscription_id,
            plan="pro",
            status="active",
            previous_status="past_due",
            event_at=started + timedelta(days=2, hours=index),
            event_type="recovered",
        )
    for index in range(2):
        user_id, _ = await _create_user(
            db_session,
            plan="team",
            created_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
        )
        subscription_id, _ = await _create_subscription(db_session, user_id=user_id, plan="team", status="active")
        await _insert_status(
            db_session,
            user_id=user_id,
            subscription_id=subscription_id,
            plan="team",
            status="past_due",
            previous_status="active",
            event_at=started + timedelta(hours=index),
            event_type="dunning_started",
        )
        await _insert_status(
            db_session,
            user_id=user_id,
            subscription_id=subscription_id,
            plan="team",
            status="active",
            previous_status="past_due",
            event_at=started + timedelta(days=1, hours=index),
            event_type="recovered",
        )

    report = await dunning_recovery_analytics(
        db_session,
        start=datetime(2026, 11, 1, tzinfo=timezone.utc),
        end=now,
        now=now,
        signup_from=datetime(2026, 1, 1).date(),
        signup_to=datetime(2026, 2, 28).date(),
    )
    plans = {row["plan_id"]: row for row in report["by_plan"]}
    assert plans["pro"]["suppressed"] is False
    assert plans["pro"]["dunning_cases"] == 5
    assert plans["team"]["suppressed"] is True
    assert plans["team"]["dunning_cases"] is None
    assert plans["team"]["recovery_rate"] is None
    cohorts = {row["cohort"]: row for row in report["cohorts"]}
    assert cohorts["2026-02"]["suppressed"] is True
    assert report["suppressed"] is True
    assert report["suppressed_groups"] >= 2
    assert report["minimum_cohort_size"] == MIN_GROUP_SIZE


async def test_admin_endpoint_is_admin_only_aggregate_and_read_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id, user_headers = await _create_user(db_session, role="user")
    subscription_id, _ = await _create_subscription(db_session, user_id=user_id, plan="pro", status="past_due")
    await _insert_status(
        db_session,
        user_id=user_id,
        subscription_id=subscription_id,
        plan="pro",
        status="past_due",
        previous_status="active",
        event_at=_now() - timedelta(days=2),
        event_type="dunning_started",
        reason="payment_failed",
    )

    forbidden = await client.get("/admin/billing/dunning-recovery?days=30", headers=user_headers)
    assert forbidden.status_code == 403

    support_id, support_headers = await _create_user(db_session, role="support")
    assert support_id
    support = await client.get("/admin/billing/dunning-recovery?days=30", headers=support_headers)
    assert support.status_code == 403

    admin_id, admin_headers = await _create_user(db_session, role="admin")
    assert admin_id
    before_status = await db_session.scalar(
        text("SELECT status FROM subscriptions WHERE id=:sid"), {"sid": subscription_id}
    )
    before_rows = await db_session.scalar(
        text("SELECT COUNT(*) FROM subscription_status_history WHERE subscription_id=:sid"),
        {"sid": subscription_id},
    )
    response = await client.get("/admin/billing/dunning-recovery?days=30", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["minimum_cohort_size"] == 5
    assert body["guardrails"]["read_only"] is True
    assert body["guardrails"]["automatic_downgrade"] is False
    assert body["guardrails"]["automatic_refund"] is False
    assert "email" not in response.text.lower()
    assert "example.com" not in response.text
    assert PREFIX not in response.text
    assert "provider_event_id" not in response.text
    assert "payload" not in response.text
    after_status = await db_session.scalar(
        text("SELECT status FROM subscriptions WHERE id=:sid"), {"sid": subscription_id}
    )
    after_rows = await db_session.scalar(
        text("SELECT COUNT(*) FROM subscription_status_history WHERE subscription_id=:sid"),
        {"sid": subscription_id},
    )
    assert after_status == before_status == "past_due"
    assert after_rows == before_rows

    alias = await client.get("/admin/subscriptions/dunning?days=30", headers=admin_headers)
    assert alias.status_code == 200
    assert alias.json()["summary"]["open_now"] >= 1


async def test_dunning_advisory_alert_and_manual_ack_are_audited(client: AsyncClient, db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await db_session.execute(text("DELETE FROM admin_alerts WHERE dedupe_key = 'billing.dunning_recovery'"))
    for index in range(5):
        user_id, _ = await _create_user(db_session)
        await _create_subscription(
            db_session,
            user_id=user_id,
            plan="pro",
            status="past_due",
            provider_event_at=now - timedelta(days=index + 1),
        )

    await admin_alert_service.evaluate_alerts(db_session, now=now)
    alert = (
        await db_session.execute(
            text(
                "SELECT id, kind, payload FROM admin_alerts "
                "WHERE dedupe_key = 'billing.dunning_recovery' AND state = 'open'"
            )
        )
    ).one_or_none()
    assert alert is not None
    assert alert.kind == "billing.dunning_recovery"
    assert alert.payload["advisory"] is True
    assert alert.payload["automatic_downgrade"] is False
    assert alert.payload["automatic_refund"] is False

    admin_id, admin_headers = await _create_user(db_session, role="admin")
    response = await client.patch(
        f"/admin/alerts/{alert.id}",
        json={"state": "acknowledged", "reason": "reviewed dunning backlog"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["state"] == "acknowledged"

    audit = (
        await db_session.execute(
            text(
                "SELECT actor_user_id, action, target_id FROM admin_audit_log "
                "WHERE action = 'admin.alert.acknowledge' AND target_id = :target "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"target": str(alert.id)},
        )
    ).one_or_none()
    assert audit is not None
    assert str(audit.actor_user_id) == admin_id
    assert audit.target_id == str(alert.id)


def test_migration_revision_chain_and_backfill() -> None:
    path = Path(__file__).parents[1] / "alembic/versions/0091_dunning_history.py"
    spec = importlib.util.spec_from_file_location("dunning_history_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

    assert migration.revision == "0091_dunning_history"
    assert migration.down_revision == "0090_ats_score_baseline"
    assert "subscription_status_history" in migration.BACKFILL_SQL
    assert "ON CONFLICT" in migration.BACKFILL_SQL
    assert "'past_due'" in migration.BACKFILL_SQL
    assert "'on_hold'" in migration.BACKFILL_SQL
    source = Path(path).read_text()
    assert "drop_table" in source
    assert "subscription_status_history_append_only" in source
    assert "BEFORE UPDATE" in source
