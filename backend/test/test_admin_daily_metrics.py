"""Daily metrics rollup: refresh, upsert, freshness, fallback and concurrency."""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services import admin_daily_metrics_service as service

MIGRATION_PATH = (
    Path(__file__).parents[1] / "alembic/versions/0100_daily_metrics.py"
)
PII_SENTINELS = (
    "test_daily_secret@example.com",
    "private-prompt-marker",
    "sk_live_secret_token",
    "203.0.113.99",
    "Mozilla/5.0 private-agent",
)


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _at(day, hour: int = 12) -> datetime:
    return datetime.combine(day, time(hour=hour), tzinfo=timezone.utc)


async def _create_user(
    db: AsyncSession,
    *,
    created_at: datetime,
    role: str = "user",
    email: str | None = None,
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    user_email = email or f"test_daily_{uuid.uuid4().hex}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, created_at) "
            "VALUES (:id, :email, :name, :role, true, 'pro', 'active', false, :created)"
        ),
        {
            "id": user_id,
            "email": user_email,
            "name": "Daily Metrics User",
            "role": role,
            "created": created_at,
        },
    )
    await db.commit()
    return user_id, user_email


async def _create_resume(db: AsyncSession, user_id: str) -> str:
    resume_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content, content_revision) "
            "VALUES (:id, :uid, 'Daily metrics resume', '\\\\documentclass{article}', 1)"
        ),
        {"id": resume_id, "uid": user_id},
    )
    await db.commit()
    return resume_id


async def _seed_compilation(
    db: AsyncSession,
    user_id: str,
    *,
    status: str,
    created_at: datetime,
) -> str:
    job_id = _unique("daily_compile")
    await db.execute(
        text(
            "INSERT INTO compilations (id, user_id, job_id, status, created_at) "
            "VALUES (:id, :uid, :job, :status, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "job": job_id,
            "status": status,
            "created": created_at,
        },
    )
    await db.commit()
    return job_id


async def _seed_optimization(
    db: AsyncSession,
    user_id: str,
    resume_id: str,
    *,
    created_at: datetime,
) -> None:
    await db.execute(
        text(
            "INSERT INTO optimizations (id, user_id, resume_id, job_description, "
            "original_latex, optimized_latex, provider, model, created_at) "
            "VALUES (:id, :uid, :rid, :jd, :source, :optimized, 'openai', 'test', :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "rid": resume_id,
            "jd": "private-prompt-marker job description",
            "source": "private-prompt-marker source",
            "optimized": "private-prompt-marker output",
            "created": created_at,
        },
    )
    await db.commit()


async def _seed_usage(
    db: AsyncSession,
    user_id: str | None,
    *,
    created_at: datetime,
    action: str = "test_daily_event",
) -> None:
    await db.execute(
        text(
            "INSERT INTO usage_analytics "
            "(id, user_id, action, event_metadata, ip_address, user_agent, created_at) "
            "VALUES (:id, :uid, :action, '{}'::jsonb, '203.0.113.99', "
            "'Mozilla/5.0 private-agent', :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "action": action,
            "created": created_at,
        },
    )
    await db.commit()


async def _seed_payment(
    db: AsyncSession,
    user_id: str,
    *,
    amount: int,
    currency: str,
    status: str,
    created_at: datetime,
) -> str:
    payment_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO payments (id, user_id, provider, provider_payment_id, "
            "amount, currency, status, created_at) "
            "VALUES (:id, :uid, 'dodo', :provider_id, :amount, :currency, :status, :created)"
        ),
        {
            "id": payment_id,
            "uid": user_id,
            "provider_id": _unique("daily_payment"),
            "amount": amount,
            "currency": currency,
            "status": status,
            "created": created_at,
        },
    )
    await db.commit()
    return payment_id


async def _seed_refund(
    db: AsyncSession,
    payment_id: str,
    *,
    amount: int,
    status: str,
    created_at: datetime,
) -> None:
    await db.execute(
        text(
            "INSERT INTO payment_refunds (id, payment_id, provider, provider_refund_id, "
            "amount, currency, status, created_at) "
            "VALUES (:id, :pid, 'dodo', :provider_refund_id, :amount, 'INR', :status, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "pid": payment_id,
            "provider_refund_id": _unique("daily_refund"),
            "amount": amount,
            "status": status,
            "created": created_at,
        },
    )
    await db.commit()


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    user_id, _email = await _create_user(
        db,
        created_at=datetime.now(timezone.utc),
        role="admin",
    )
    token = f"test_sess_{uuid.uuid4().hex}"
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


async def _user_headers(db: AsyncSession) -> dict[str, str]:
    user_id, _email = await _create_user(
        db,
        created_at=datetime.now(timezone.utc),
        role="user",
    )
    token = f"test_sess_{uuid.uuid4().hex}"
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


async def _cleanup(db: AsyncSession) -> None:
    await db.rollback()
    await db.execute(text("DELETE FROM admin_daily_metrics"))
    test_users = "SELECT id FROM users WHERE email LIKE 'test_daily_%'"
    await db.execute(
        text(
            "DELETE FROM payment_refunds WHERE payment_id IN ("
            f"SELECT p.id FROM payments p WHERE p.user_id IN ({test_users}))"
        )
    )
    await db.execute(
        text(f"DELETE FROM payments WHERE user_id IN ({test_users})")
    )
    await db.execute(
        text(f"DELETE FROM optimizations WHERE user_id IN ({test_users})")
    )
    await db.execute(
        text(f"DELETE FROM compilations WHERE user_id IN ({test_users})")
    )
    await db.execute(
        text(f"DELETE FROM usage_analytics WHERE user_id IN ({test_users})")
    )
    await db.execute(
        text(f"DELETE FROM resumes WHERE user_id IN ({test_users})")
    )
    await db.execute(
        text('DELETE FROM session WHERE "userId" IN (SELECT id::text FROM users WHERE email LIKE \'test_daily_%\')')
    )
    await db.execute(
        text("DELETE FROM users WHERE email LIKE 'test_daily_%'")
    )
    await db.commit()


@pytest.fixture(autouse=True)
async def _clean_daily_metrics(db_session: AsyncSession):
    await _cleanup(db_session)
    yield
    await _cleanup(db_session)


class TestMigrationContract:
    def test_migration_is_additive_reversible_and_has_unique_date_key(self):
        spec = importlib.util.spec_from_file_location(
            "daily_metrics_migration", MIGRATION_PATH
        )
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        calls: list[tuple] = []

        class FakeOp:
            def create_table(self, name: str, *columns, **kwargs) -> None:
                calls.append(("create_table", name, columns, kwargs))

            def create_index(self, name: str, table: str, columns, **kwargs) -> None:
                calls.append(("create_index", name, table, columns, kwargs))

            def drop_index(self, name: str, table_name: str) -> None:
                calls.append(("drop_index", name, table_name))

            def drop_table(self, name: str) -> None:
                calls.append(("drop_table", name))

        assert migration.revision == "0100_daily_metrics"
        assert migration.down_revision == "0092_document_complexity"
        migration.op = FakeOp()
        migration.upgrade()

        table_call = next(call for call in calls if call[0] == "create_table")
        assert table_call[1] == "admin_daily_metrics"
        columns = {
            column.name: column
            for column in table_call[2]
            if column.__class__.__name__ == "Column"
        }
        assert set(columns) == {
            "metric_date",
            "new_users",
            "active_users",
            "usage_events",
            "compilations",
            "completed_compilations",
            "failed_compilations",
            "optimizations",
            "payments_count",
            "gross_revenue_minor",
            "refunds_count",
            "refund_amount_minor",
            "refreshed_at",
        }
        assert columns["metric_date"].primary_key is True
        assert any(
            getattr(item, "name", None) == "ck_admin_daily_metrics_nonnegative"
            for item in table_call[2]
        )
        assert any(
            call[0] == "create_index"
            and call[1] == "idx_admin_daily_metrics_refreshed_at"
            for call in calls
        )

        calls.clear()
        migration.downgrade()
        assert [call[0] for call in calls] == ["drop_index", "drop_table"]
        assert calls[-1][1] == "admin_daily_metrics"

    def test_beat_schedule_refreshes_inside_the_five_to_fifteen_minute_window(self):
        from app.core.celery_app import celery_app

        entry = celery_app.conf.beat_schedule["refresh-daily-metrics"]
        assert entry["task"] == (
            "app.workers.cleanup_worker.refresh_daily_metrics_task"
        )
        assert 300 <= float(entry["schedule"]) <= 900


class TestRefresh:
    async def test_refresh_aggregates_all_sources_into_unique_daily_rows(
        self, db_session: AsyncSession
    ):
        now = datetime.now(timezone.utc)
        today = now.date()
        yesterday = today - timedelta(days=1)
        baseline_series, _baseline_descriptor = await service.daily_series(
            db_session, days=7, now=now
        )
        baseline = {point["date"]: point for point in baseline_series}
        user_today_a, _ = await _create_user(db_session, created_at=_at(today, 8))
        user_today_b, _ = await _create_user(db_session, created_at=_at(today, 9))
        user_yesterday, _ = await _create_user(
            db_session, created_at=_at(yesterday, 9)
        )
        resume_a = await _create_resume(db_session, user_today_a)
        resume_b = await _create_resume(db_session, user_today_b)

        await _seed_compilation(
            db_session, user_today_a, status="completed", created_at=_at(today, 10)
        )
        await _seed_compilation(
            db_session, user_today_b, status="completed", created_at=_at(today, 11)
        )
        await _seed_compilation(
            db_session, user_today_a, status="failed", created_at=_at(today, 12)
        )
        await _seed_compilation(
            db_session, user_yesterday, status="completed", created_at=_at(yesterday)
        )
        await _seed_optimization(
            db_session, user_today_a, resume_a, created_at=_at(today, 10)
        )
        await _seed_optimization(
            db_session, user_today_b, resume_b, created_at=_at(today, 11)
        )
        await _seed_optimization(
            db_session, user_yesterday, resume_a, created_at=_at(yesterday)
        )
        for _ in range(5):
            await _seed_usage(db_session, user_today_a, created_at=_at(today, 10))
        for _ in range(5):
            await _seed_usage(db_session, user_today_b, created_at=_at(today, 11))
        await _seed_usage(db_session, user_yesterday, created_at=_at(yesterday))
        payment_today = await _seed_payment(
            db_session,
            user_today_a,
            amount=50_000,
            currency="INR",
            status="paid",
            created_at=_at(today, 13),
        )
        await _seed_payment(
            db_session,
            user_yesterday,
            amount=20_000,
            currency="INR",
            status="captured",
            created_at=_at(yesterday, 13),
        )
        await _seed_payment(
            db_session,
            user_today_b,
            amount=9_900,
            currency="USD",
            status="paid",
            created_at=_at(today, 14),
        )
        await _seed_refund(
            db_session,
            payment_today,
            amount=10_000,
            status="succeeded",
            created_at=_at(today, 15),
        )
        await _seed_refund(
            db_session,
            payment_today,
            amount=5_000,
            status="failed",
            created_at=_at(today, 16),
        )

        result = await service.refresh_daily_metrics(db_session, days=7, now=now)
        assert result["status"] == "refreshed"
        assert result["rows"] == 7
        assert result["days"] == 7

        rows = (
            await db_session.execute(
                service.AdminDailyMetric.__table__.select().order_by(
                    service.AdminDailyMetric.metric_date
                )
            )
        ).all()
        by_date = {row.metric_date: row for row in rows}
        assert len(by_date) == 7
        assert len(set(by_date)) == 7

        today_row = by_date[today]
        today_base = baseline[today.isoformat()]
        assert today_row.new_users == today_base["new_users"] + 2
        assert today_row.active_users == today_base["active_users"] + 2
        assert today_row.usage_events == today_base["events"] + 10
        assert today_row.compilations == today_base["compilations"] + 3
        assert today_row.completed_compilations == today_base["completed_compilations"] + 2
        assert today_row.failed_compilations == today_base["failed_compilations"] + 1
        assert today_row.optimizations == today_base["optimizations"] + 2
        assert today_row.payments_count == today_base["payments_count"] + 1
        assert today_row.gross_revenue_minor == round(today_base["gross_revenue_inr"] * 100) + 50_000
        assert today_row.refunds_count == today_base["refunds_count"] + 1
        assert today_row.refund_amount_minor == round(today_base["refunds_inr"] * 100) + 10_000

        yesterday_row = by_date[yesterday]
        yesterday_base = baseline[yesterday.isoformat()]
        assert yesterday_row.new_users == yesterday_base["new_users"] + 1
        assert yesterday_row.active_users == yesterday_base["active_users"] + 1
        assert yesterday_row.usage_events == yesterday_base["events"] + 1
        assert yesterday_row.compilations == yesterday_base["compilations"] + 1
        assert yesterday_row.completed_compilations == yesterday_base["completed_compilations"] + 1
        assert yesterday_row.failed_compilations == yesterday_base["failed_compilations"]
        assert yesterday_row.optimizations == yesterday_base["optimizations"] + 1
        assert yesterday_row.payments_count == yesterday_base["payments_count"] + 1
        assert yesterday_row.gross_revenue_minor == round(yesterday_base["gross_revenue_inr"] * 100) + 20_000
        assert yesterday_row.refunds_count == yesterday_base["refunds_count"]

        empty_day = today - timedelta(days=3)
        empty = by_date[empty_day]
        empty_base = baseline[empty_day.isoformat()]
        assert empty.compilations == empty_base["compilations"]
        assert empty.gross_revenue_minor == round(empty_base["gross_revenue_inr"] * 100)

    async def test_duplicate_day_refresh_upserts_without_extra_rows(
        self, db_session: AsyncSession
    ):
        now = datetime.now(timezone.utc)
        today = now.date()
        baseline_series, _ = await service.daily_series(db_session, days=3, now=now)
        baseline = {point["date"]: point for point in baseline_series}[today.isoformat()]
        user_id, _ = await _create_user(db_session, created_at=_at(today, 8))
        await _seed_compilation(
            db_session, user_id, status="completed", created_at=_at(today, 9)
        )

        first = await service.refresh_daily_metrics(db_session, days=3, now=now)
        assert first["status"] == "refreshed"
        first_row = (
            await db_session.execute(
                service.AdminDailyMetric.__table__.select().where(
                    service.AdminDailyMetric.metric_date == today
                )
            )
        ).one()
        assert first_row.compilations == baseline["compilations"] + 1

        await _seed_compilation(
            db_session, user_id, status="failed", created_at=_at(today, 10)
        )
        later = now + timedelta(minutes=10)
        second = await service.refresh_daily_metrics(db_session, days=3, now=later)
        assert second["status"] == "refreshed"

        rows = (
            await db_session.execute(
                service.AdminDailyMetric.__table__.select().where(
                    service.AdminDailyMetric.metric_date == today
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].compilations == baseline["compilations"] + 2
        assert rows[0].failed_compilations == baseline["failed_compilations"] + 1
        assert rows[0].refreshed_at == later

    async def test_failed_refresh_keeps_the_prior_snapshot(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        now = datetime.now(timezone.utc)
        today = now.date()
        user_id, _ = await _create_user(db_session, created_at=_at(today, 8))
        await _seed_compilation(
            db_session, user_id, status="completed", created_at=_at(today, 9)
        )
        first = await service.refresh_daily_metrics(db_session, days=3, now=now)
        assert first["status"] == "refreshed"
        before = (
            await db_session.execute(
                service.AdminDailyMetric.__table__.select().order_by(
                    service.AdminDailyMetric.metric_date
                )
            )
        ).all()
        before_snapshot = [tuple(row) for row in before]

        async def _boom(*args, **kwargs):
            raise RuntimeError("synthetic refresh failure")

        monkeypatch.setattr(service, "_perform_upsert", _boom)
        failed = await service.refresh_daily_metrics(
            db_session, days=3, now=now + timedelta(minutes=5)
        )
        assert failed["status"] == "failed"
        assert failed["reason"] == "refresh_failed"
        assert failed["error_type"] == "RuntimeError"

        after = (
            await db_session.execute(
                service.AdminDailyMetric.__table__.select().order_by(
                    service.AdminDailyMetric.metric_date
                )
            )
        ).all()
        assert [tuple(row) for row in after] == before_snapshot


class TestFreshnessAndFallback:
    async def test_fresh_rollup_is_preferred_and_stale_rollup_falls_back(
        self, db_session: AsyncSession
    ):
        now = datetime.now(timezone.utc)
        today = now.date()
        baseline_series, _ = await service.daily_series(db_session, days=7, now=now)
        baseline = {point["date"]: point for point in baseline_series}[today.isoformat()]
        user_id, _ = await _create_user(db_session, created_at=_at(today, 8))
        await _seed_compilation(
            db_session, user_id, status="completed", created_at=_at(today, 9)
        )
        await service.refresh_daily_metrics(db_session, days=7, now=now)

        freshness = await service.daily_metrics_freshness(db_session, now=now)
        assert freshness["fresh"] is True
        assert freshness["reason"] == "fresh"
        assert freshness["rollup_rows"] == 7

        # Overwrite the rollup with a sentinel to prove the read path uses it.
        await db_session.execute(
            text(
                "UPDATE admin_daily_metrics SET compilations = 999, active_users = 8 "
                "WHERE metric_date = :day"
            ),
            {"day": today},
        )
        await db_session.commit()

        series, descriptor = await service.daily_series(
            db_session, days=7, now=now
        )
        assert descriptor["source"] == "rollup"
        assert descriptor["fresh"] is True
        point = next(item for item in series if item["date"] == today.isoformat())
        assert point["compilations"] == 999
        assert point["sparse"] is False

        # Age the snapshot beyond the stale threshold; the same request must
        # now be computed from base tables and labelled as a fallback.
        stale_at = now - timedelta(seconds=service.STALE_AFTER_SECONDS + 60)
        await db_session.execute(
            text("UPDATE admin_daily_metrics SET refreshed_at = :stale"),
            {"stale": stale_at},
        )
        await db_session.commit()

        stale_series, stale_descriptor = await service.daily_series(
            db_session, days=7, now=now
        )
        assert stale_descriptor["source"] == "base_tables"
        assert stale_descriptor["fresh"] is False
        assert stale_descriptor["reason"] == "stale"
        assert stale_descriptor["fallback_reason"] == "stale"
        stale_point = next(
            item for item in stale_series if item["date"] == today.isoformat()
        )
        assert stale_point["compilations"] == baseline["compilations"] + 1

    async def test_missing_rollup_falls_back_to_base_tables(
        self, db_session: AsyncSession
    ):
        now = datetime.now(timezone.utc)
        baseline_series, _ = await service.daily_series(db_session, days=3, now=now)
        baseline_total = sum(point["compilations"] for point in baseline_series)
        user_id, _ = await _create_user(db_session, created_at=_at(now.date(), 8))
        await _seed_compilation(
            db_session, user_id, status="failed", created_at=_at(now.date(), 9)
        )

        series, descriptor = await service.daily_series(
            db_session, days=3, now=now
        )
        assert descriptor["source"] == "base_tables"
        assert descriptor["reason"] == "no_rollup"
        assert descriptor["fallback_reason"] == "no_rollup"
        assert sum(point["compilations"] for point in series) == baseline_total + 1

    async def test_insufficient_coverage_falls_back_to_base_tables(
        self, db_session: AsyncSession
    ):
        now = datetime.now(timezone.utc)
        user_id, _ = await _create_user(db_session, created_at=_at(now.date(), 8))
        await _seed_compilation(
            db_session, user_id, status="completed", created_at=_at(now.date(), 9)
        )
        await service.refresh_daily_metrics(db_session, days=2, now=now)

        _series, descriptor = await service.daily_series(
            db_session, days=7, now=now
        )
        assert descriptor["source"] == "base_tables"
        assert descriptor["fallback_reason"] == "insufficient_coverage"

    async def test_report_totals_revenue_and_privacy_boundary(
        self, db_session: AsyncSession
    ):
        now = datetime.now(timezone.utc)
        today = now.date()
        baseline_series, _ = await service.daily_series(db_session, days=7, now=now)
        baseline_totals = service._totals(baseline_series)
        baseline_today = {
            point["date"]: point for point in baseline_series
        }[today.isoformat()]
        user_id, email = await _create_user(db_session, created_at=_at(today, 8))
        await _seed_compilation(
            db_session, user_id, status="completed", created_at=_at(today, 9)
        )
        payment_id = await _seed_payment(
            db_session,
            user_id,
            amount=25_000,
            currency="INR",
            status="paid",
            created_at=_at(today, 10),
        )
        await _seed_refund(
            db_session,
            payment_id,
            amount=5_000,
            status="succeeded",
            created_at=_at(today, 11),
        )
        await _seed_usage(db_session, user_id, created_at=_at(today, 12))
        await service.refresh_daily_metrics(db_session, days=7, now=now)

        report = await service.daily_metrics_report(db_session, days=7, now=now)
        assert report["source"] == "rollup"
        assert report["freshness"]["fresh"] is True
        assert report["freshness"]["refresh_interval_seconds"] == 600
        assert report["totals"]["compilations"] == baseline_totals["compilations"] + 1
        assert report["totals"]["gross_revenue_inr"] == pytest.approx(
            baseline_totals["gross_revenue_inr"] + 250.0, abs=0.01
        )
        assert report["totals"]["refunds_inr"] == pytest.approx(
            baseline_totals["refunds_inr"] + 50.0, abs=0.01
        )
        assert report["totals"]["revenue_inr"] == pytest.approx(
            baseline_totals["revenue_inr"] + 200.0, abs=0.01
        )
        assert report["minimum_cohort_users"] == 5
        assert report["suppression"]["cohort_rows_returned"] == 0
        today_point = next(
            point for point in report["series"] if point["date"] == today.isoformat()
        )
        assert today_point["active_users"] == baseline_today["active_users"] + 1
        assert today_point["sparse"] is (today_point["active_users"] < 5)
        encoded = json.dumps(report)
        assert email not in encoded
        for sentinel in PII_SENTINELS:
            assert sentinel not in encoded
        assert '"user_agent"' not in encoded
        assert '"ip_address"' not in encoded
        assert '"email"' not in encoded


class TestSuppression:
    @pytest.mark.parametrize(
        ("active_users", "expected_sparse"),
        [(0, False), (1, True), (4, True), (5, False), (12, False)],
    )
    def test_sparse_flag_uses_the_five_user_minimum(
        self, active_users: int, expected_sparse: bool
    ):
        row = SimpleNamespace(
            new_users=0,
            active_users=active_users,
            usage_events=0,
            compilations=0,
            completed_compilations=0,
            failed_compilations=0,
            optimizations=0,
            payments_count=0,
            gross_revenue_minor=0,
            refunds_count=0,
            refund_amount_minor=0,
        )
        point = service._point(date(2026, 1, 15), row)
        assert point["active_users"] == active_users
        assert point["sparse"] is expected_sparse


class TestConcurrency:
    async def test_overlapping_refresh_skips_instead_of_racing(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
    ):
        now = datetime.now(timezone.utc)
        async with db_session_factory() as holder:
            held = (
                await holder.execute(
                    text("SELECT pg_try_advisory_xact_lock(:key)"),
                    {"key": service.REFRESH_LOCK_KEY},
                )
            ).scalar()
            assert held is True

            async with db_session_factory() as contender:
                skipped = await service.refresh_daily_metrics(
                    contender, days=3, now=now
                )
                assert skipped["status"] == "skipped"
                assert skipped["reason"] == "lock_not_acquired"
                assert skipped["rows"] == 0

            await holder.rollback()

        async with db_session_factory() as refreshed_session:
            refreshed = await service.refresh_daily_metrics(
                refreshed_session, days=3, now=now
            )
            assert refreshed["status"] == "refreshed"
            rows = (
                await refreshed_session.execute(
                    service.AdminDailyMetric.__table__.select()
                )
            ).all()
            assert len(rows) == 3
            assert len({row.metric_date for row in rows}) == 3


class TestApi:
    async def test_endpoint_requires_admin_and_returns_aggregate_payload(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        unauthenticated = await client.get("/admin/analytics/daily-metrics?days=7")
        assert unauthenticated.status_code == 401

        user_headers = await _user_headers(db_session)
        forbidden = await client.get(
            "/admin/analytics/daily-metrics?days=7", headers=user_headers
        )
        assert forbidden.status_code == 403

        admin_headers = await _admin_headers(db_session)
        now = datetime.now(timezone.utc)
        user_id, email = await _create_user(
            db_session, created_at=_at(now.date(), 8)
        )
        await _seed_compilation(
            db_session, user_id, status="completed", created_at=_at(now.date(), 9)
        )
        await service.refresh_daily_metrics(db_session, days=7, now=now)

        response = await client.get(
            "/admin/analytics/daily-metrics?days=7", headers=admin_headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source"] == "rollup"
        assert body["freshness"]["fresh"] is True
        assert body["freshness"]["source"] == "rollup"
        assert body["days"] == 7
        assert len(body["series"]) == 7
        assert body["totals"]["compilations"] >= 1
        assert body["privacy"]["aggregate_only"] is True
        assert body["privacy"]["per_user_rows"] is False
        assert email not in response.text
        for sentinel in PII_SENTINELS:
            assert sentinel not in response.text
        assert '"user_agent"' not in response.text
        assert '"ip_address"' not in response.text
        assert '"email"' not in response.text

    async def test_overview_exposes_metrics_freshness(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.api.analytics_routes import reset_admin_overview_cache
        from app.core.redis import cache_manager

        admin_headers = await _admin_headers(db_session)
        now = datetime.now(timezone.utc)
        await service.refresh_daily_metrics(db_session, days=7, now=now)
        reset_admin_overview_cache()
        try:
            await cache_manager.delete("analytics:admin_overview:7")
        except Exception:
            pass

        response = await client.get(
            "/analytics/admin/overview?days=7", headers=admin_headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["metrics_freshness"]["source"] == "rollup"
        assert body["metrics_freshness"]["fresh"] is True
        assert len(body["timeseries"]) == 7
