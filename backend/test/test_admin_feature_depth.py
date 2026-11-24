"""Feature depth and frequency analysis (C3).

Covers bucket math, nearest-rank median/p95, plan/cohort filters, small-group
suppression, admin-only access, privacy, and reconciliation with the raw
``usage_analytics`` rows.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, time, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UsageAnalytics
from app.services.admin_growth_service import _percentile, admin_growth_service


async def _create_user(
    db: AsyncSession,
    *,
    plan: str,
    role: str = "user",
    created_at: datetime | None = None,
) -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, created_at) "
            "VALUES (:id, :email, 'Feature Depth User', :role, true, :plan, 'active', false, :created)"
        ),
        {
            "id": user_id,
            "email": f"test_fd_{user_id.replace('-', '')}@example.com",
            "role": role,
            "plan": plan,
            "created": created_at or datetime.now(timezone.utc),
        },
    )
    await db.commit()
    return user_id


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_fd_{uuid.uuid4().hex}"
    await db.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    user_id = await _create_user(db, plan="pro", role="admin")
    return await _session_headers(db, user_id)


async def _seed_feature(
    db: AsyncSession,
    user_id: str,
    feature: str,
    count: int,
    *,
    created_at: datetime | None = None,
    metadata_secret: str | None = None,
) -> None:
    created = created_at or datetime.now(timezone.utc) - timedelta(hours=1)
    metadata = {"feature": feature}
    if metadata_secret:
        metadata.update({"raw_text": metadata_secret, "job_description": metadata_secret})
    for _ in range(count):
        await db.execute(
            text(
                "INSERT INTO usage_analytics (id, user_id, action, resource_type, event_metadata, created_at) "
                "VALUES (:id, :uid, 'feature_usage', 'feature', CAST(:metadata AS JSONB), :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "metadata": json.dumps(metadata),
                "created": created,
            },
        )
    await db.commit()


async def _cleanup(db: AsyncSession, user_ids: list[str]) -> None:
    if not user_ids:
        return
    await db.execute(
        text("DELETE FROM usage_analytics WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": user_ids},
    )
    await db.execute(
        text("DELETE FROM users WHERE id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": user_ids},
    )
    await db.commit()


def _feature(body: dict, feature: str) -> dict:
    return next(item for item in body["features"] if item["feature"] == feature)


def _window_start(days: int) -> datetime:
    today = datetime.now(timezone.utc).date()
    return datetime.combine(today - timedelta(days=days - 1), time.min, tzinfo=timezone.utc)


class TestFeatureDepthMath:
    def test_nearest_rank_percentile_uses_observed_counts(self):
        assert _percentile([], 95) is None
        assert _percentile([1], 95) == 1.0
        assert _percentile([1, 2], 95) == 2.0
        assert _percentile([1, 2, 3, 4, 5], 95) == 5.0
        # Nearest rank at p95 for 20 samples is the 19th value, not an
        # interpolated count between the top two.
        assert _percentile(list(range(1, 21)), 95) == 19.0

    async def test_buckets_median_p95_breadth_and_reconciliation(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"fd_math_{uuid.uuid4().hex[:10]}"
        compile_feature = f"fd_compile_{uuid.uuid4().hex[:8]}"
        export_feature = f"fd_export_{uuid.uuid4().hex[:8]}"
        user_ids: list[str] = []
        try:
            user_ids = [await _create_user(db_session, plan=plan) for _ in range(5)]
            for user_id, compile_events in zip(user_ids, (1, 2, 4, 5, 10)):
                await _seed_feature(db_session, user_id, compile_feature, compile_events)
                await _seed_feature(db_session, user_id, export_feature, 1)

            result = await admin_growth_service.feature_depth(db_session, days=7, plan=plan)

            assert result["suppressed"] is False
            assert result["minimum_group_size"] == 5
            assert result["totals"]["users"] == 5
            assert result["totals"]["events"] == 27
            # Totals are per user across all features: [2, 3, 5, 6, 11].
            assert result["totals"]["median_events_per_user"] == 5.0
            assert result["totals"]["p95_events_per_user"] == 11.0
            assert result["totals"]["repeat_users"] == 5
            assert result["totals"]["repeat_rate"] == 100.0
            assert result["habitual_minimum_events"] == 5
            assert result["totals"]["habitual_users"] == 3
            assert result["totals"]["habitual_rate"] == 60.0
            assert result["totals"]["breadth"]["average_features_per_user"] == 2.0
            assert result["totals"]["breadth"]["median_features_per_user"] == 2.0
            assert {row["key"]: row["users"] for row in result["totals"]["breadth"]["distribution"]} == {
                "1": 0,
                "2": 5,
                "3": 0,
                "4": 0,
                "5+": 0,
            }

            compile_row = _feature(result, compile_feature)
            assert compile_row["users"] == 5
            assert compile_row["events"] == 22
            assert compile_row["events_per_user"] == 4.4
            assert compile_row["median_events_per_user"] == 4.0
            assert compile_row["p95_events_per_user"] == 10.0
            assert compile_row["repeat_users"] == 4
            assert compile_row["repeat_rate"] == 80.0
            assert compile_row["habitual_users"] == 2
            assert compile_row["habitual_rate"] == 40.0
            assert {bucket["key"]: bucket["users"] for bucket in compile_row["buckets"]} == {
                "1": 1,
                "2-4": 2,
                "5-9": 1,
                "10+": 1,
            }
            assert {bucket["key"]: bucket["share"] for bucket in compile_row["buckets"]} == {
                "1": 20.0,
                "2-4": 40.0,
                "5-9": 20.0,
                "10+": 20.0,
            }
            assert compile_row["breadth"]["average_features_per_user"] == 2.0
            assert compile_row["breadth"]["sole_feature_users"] == 0
            assert compile_row["breadth"]["multi_feature_users"] == 5

            export_row = _feature(result, export_feature)
            assert export_row["users"] == 5
            assert export_row["events"] == 5
            assert export_row["median_events_per_user"] == 1.0
            assert export_row["p95_events_per_user"] == 1.0
            assert export_row["repeat_users"] == 0

            raw_count = (
                await db_session.execute(
                    select(func.count(UsageAnalytics.id)).where(
                        UsageAnalytics.user_id.in_(user_ids),
                        UsageAnalytics.created_at >= _window_start(7),
                    )
                )
            ).scalar_one()
            assert raw_count == result["totals"]["events"]
            assert sum(row["events"] for row in result["features"]) == raw_count

            # The HTTP surface must reconcile to the same raw rows.
            headers = await _admin_headers(db_session)
            response = await client.get(f"/admin/analytics/feature-depth?days=7&plan={plan}", headers=headers)
            assert response.status_code == 200
            body = response.json()
            assert body["totals"]["events"] == raw_count
            assert body["totals"]["users"] == 5
            assert sum(row["events"] for row in body["features"]) == raw_count
        finally:
            await _cleanup(db_session, user_ids)

    async def test_plan_and_cohort_filters(self, db_session: AsyncSession):
        plan = f"fd_filter_{uuid.uuid4().hex[:10]}"
        feature = f"fd_cohort_{uuid.uuid4().hex[:8]}"
        this_month = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_month = (this_month - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_label = previous_month.strftime("%Y-%m")
        user_ids: list[str] = []
        try:
            previous_ids = [
                await _create_user(db_session, plan=plan, created_at=previous_month + timedelta(days=2))
                for _ in range(5)
            ]
            current_ids = [
                await _create_user(db_session, plan=plan, created_at=this_month + timedelta(days=2)) for _ in range(5)
            ]
            user_ids = previous_ids + current_ids
            for user_id in user_ids:
                await _seed_feature(db_session, user_id, feature, 1)

            filtered = await admin_growth_service.feature_depth(db_session, days=365, plan=plan, cohort=previous_label)
            assert filtered["filters"]["plan"] == plan
            assert filtered["filters"]["cohort"] == previous_label
            assert filtered["totals"]["users"] == 5
            assert _feature(filtered, feature)["users"] == 5

            plan_only = await admin_growth_service.feature_depth(db_session, days=365, plan=plan)
            assert plan_only["totals"]["users"] == 10
            assert _feature(plan_only, feature)["users"] == 10
            assert plan_only["totals"]["events"] == 10

            missing_cohort = await admin_growth_service.feature_depth(db_session, days=365, plan=plan, cohort="2020-01")
            assert missing_cohort["suppressed"] is False
            assert missing_cohort["totals"]["users"] == 0
            assert missing_cohort["features"] == []
        finally:
            await _cleanup(db_session, user_ids)


class TestFeatureDepthSuppression:
    async def test_small_features_and_cohorts_are_suppressed(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"fd_small_{uuid.uuid4().hex[:10]}"
        common_feature = f"fd_common_{uuid.uuid4().hex[:8]}"
        rare_feature = f"fd_rare_{uuid.uuid4().hex[:8]}"
        user_ids: list[str] = []
        try:
            user_ids = [await _create_user(db_session, plan=plan) for _ in range(5)]
            for user_id in user_ids:
                await _seed_feature(db_session, user_id, common_feature, 2)
            for user_id in user_ids[:4]:
                await _seed_feature(db_session, user_id, rare_feature, 1)

            result = await admin_growth_service.feature_depth(db_session, days=7, plan=plan)
            assert result["suppressed"] is False
            assert result["suppressed_features"] == 1
            assert [row["feature"] for row in result["features"]] == [common_feature]
            # Totals still reconcile with usage_analytics for the cohort.
            assert result["totals"]["events"] == 14

            headers = await _admin_headers(db_session)
            response = await client.get(f"/admin/analytics/feature-depth?days=7&plan={plan}", headers=headers)
            assert response.status_code == 200
            body = response.json()
            assert rare_feature not in json.dumps(body)
            assert body["suppressed_features"] == 1
        finally:
            await _cleanup(db_session, user_ids)

    async def test_filtered_cohort_below_five_leaks_no_counts(self, db_session: AsyncSession):
        plan = f"fd_tiny_{uuid.uuid4().hex[:10]}"
        feature = f"fd_tiny_{uuid.uuid4().hex[:8]}"
        user_ids: list[str] = []
        try:
            user_ids = [await _create_user(db_session, plan=plan) for _ in range(4)]
            for user_id in user_ids:
                await _seed_feature(db_session, user_id, feature, 3)

            result = await admin_growth_service.feature_depth(db_session, days=7, plan=plan)
            assert result["suppressed"] is True
            assert result["suppressed_features"] == 1
            assert result["features"] == []
            assert result["totals"]["users"] == 0
            assert result["totals"]["events"] == 0
            assert result["totals"]["median_events_per_user"] is None
            assert result["totals"]["p95_events_per_user"] is None
            assert feature not in json.dumps(result)
        finally:
            await _cleanup(db_session, user_ids)


class TestFeatureDepthAccessAndPrivacy:
    async def test_endpoint_is_admin_only(self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict):
        unauthenticated = await client.get("/admin/analytics/feature-depth?days=7")
        assert unauthenticated.status_code == 401

        forbidden = await client.get("/admin/analytics/feature-depth?days=7", headers=auth_headers)
        assert forbidden.status_code == 403

        plan = f"fd_access_{uuid.uuid4().hex[:10]}"
        feature = f"fd_access_{uuid.uuid4().hex[:8]}"
        headers = await _admin_headers(db_session)
        user_ids = [await _create_user(db_session, plan=plan) for _ in range(5)]
        try:
            for user_id in user_ids:
                await _seed_feature(db_session, user_id, feature, 1)
            allowed = await client.get(f"/admin/analytics/feature-depth?days=7&plan={plan}", headers=headers)
            assert allowed.status_code == 200
            body = allowed.json()
            assert {
                "totals",
                "features",
                "filters",
                "minimum_group_size",
                "habitual_definition",
            } <= set(body)
            assert body["totals"]["users"] == 5
        finally:
            await _cleanup(db_session, user_ids)

    async def test_response_excludes_metadata_text_and_user_ids(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"fd_privacy_{uuid.uuid4().hex[:10]}"
        feature = f"fd_privacy_{uuid.uuid4().hex[:8]}"
        secret = "SECRET_DOCUMENT_BODY_42"
        user_ids: list[str] = []
        try:
            user_ids = [await _create_user(db_session, plan=plan) for _ in range(5)]
            for user_id in user_ids:
                await _seed_feature(db_session, user_id, feature, 2, metadata_secret=secret)

            headers = await _admin_headers(db_session)
            response = await client.get(f"/admin/analytics/feature-depth?days=7&plan={plan}", headers=headers)
            assert response.status_code == 200
            payload = response.text
            assert secret not in payload
            assert "job_description" not in payload
            assert "event_metadata" not in payload
            for user_id in user_ids:
                assert user_id not in payload
            body = response.json()
            assert all("user_id" not in row for row in body["features"])
        finally:
            await _cleanup(db_session, user_ids)
