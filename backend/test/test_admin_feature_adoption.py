"""Feature adoption matrix by plan, role, and cohort (C2).

Covers registry completeness, used-at-least-once vs weekly active, penetration
and denominators, reconciliation to raw ``usage_analytics`` rows, plan/role/
cohort filters, subscription-derived plans, small-segment suppression,
admin-only access, and privacy.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.feature_registry import all_feature_keys
from app.database.models import UsageAnalytics


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
            "VALUES (:id, :email, 'Feature Adoption User', :role, true, :plan, 'active', false, :created)"
        ),
        {
            "id": user_id,
            "email": f"test_fa_{user_id.replace('-', '')}@example.com",
            "role": role,
            "plan": plan,
            "created": created_at or datetime.now(timezone.utc),
        },
    )
    await db.commit()
    return user_id


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_fa_{uuid.uuid4().hex}"
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


_CREATED_ADMIN_IDS: list[str] = []


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    admin_plan = f"fa_admin_{uuid.uuid4().hex[:6]}"
    user_id = await _create_user(db, plan=admin_plan, role="admin")
    _CREATED_ADMIN_IDS.append(user_id)
    return await _session_headers(db, user_id)


async def _seed_feature(
    db: AsyncSession,
    user_id: str,
    feature: str,
    count: int = 1,
    *,
    created_at: datetime | None = None,
    metadata_secret: str | None = None,
) -> None:
    created = created_at or datetime.now(timezone.utc) - timedelta(hours=1)
    metadata: dict[str, str] = {"feature": feature}
    if metadata_secret:
        metadata.update(
            {
                "raw_text": metadata_secret,
                "job_description": metadata_secret,
                "document_content": metadata_secret,
            }
        )
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


async def _seed_event(
    db: AsyncSession,
    user_id: str,
    *,
    action: str,
    metadata: dict | None = None,
    created_at: datetime | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO usage_analytics (id, user_id, action, resource_type, event_metadata, created_at) "
            "VALUES (:id, :uid, :action, 'feature', CAST(:metadata AS JSONB), :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "action": action,
            "metadata": json.dumps(metadata) if metadata is not None else None,
            "created": created_at or datetime.now(timezone.utc) - timedelta(hours=1),
        },
    )
    await db.commit()


async def _seed_subscription(
    db: AsyncSession,
    user_id: str,
    *,
    plan_id: str,
    status: str = "active",
) -> str:
    subscription_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, plan_id, status, "
            "current_period_start, current_period_end, created_at, updated_at) "
            "VALUES (:id, :uid, 'test', :plan, :status, :start, :end, :created, :updated)"
        ),
        {
            "id": subscription_id,
            "uid": user_id,
            "plan": plan_id,
            "status": status,
            "start": now - timedelta(days=1),
            "end": now + timedelta(days=30),
            "created": now,
            "updated": now,
        },
    )
    await db.commit()
    return subscription_id


async def _cleanup(
    db: AsyncSession,
    user_ids: list[str],
    *,
    plan_families: list[str] | None = None,
) -> None:
    cleanup_ids = list(dict.fromkeys([*user_ids, *_CREATED_ADMIN_IDS]))
    _CREATED_ADMIN_IDS.clear()
    await db.execute(text("DELETE FROM session WHERE token LIKE 'test_sess_fa_%'"))
    if plan_families:
        await db.execute(
            text("DELETE FROM plan_features WHERE plan_family = ANY(:plans)"),
            {"plans": plan_families},
        )
    if cleanup_ids:
        await db.execute(
            text("DELETE FROM usage_analytics WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": cleanup_ids},
        )
        await db.execute(
            text("DELETE FROM subscriptions WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": cleanup_ids},
        )
        await db.execute(
            text("DELETE FROM users WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": cleanup_ids},
        )
    await db.commit()


def _segment(body: dict, dimension: str, key: str | None = None) -> dict:
    rows = [segment for segment in body["segments"] if segment["dimension"] == dimension]
    if key is None:
        return rows[0]
    return next(segment for segment in rows if segment["key"] == key)


def _feature(segment: dict, feature: str) -> dict:
    return next(row for row in segment["features"] if row["key"] == feature)


def _month_label(value: datetime) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _previous_month_start() -> datetime:
    this_month = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (this_month - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class TestFeatureAdoptionMatrix:
    async def test_every_registry_feature_appears_for_each_segment(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"fa_matrix_{uuid.uuid4().hex[:6]}"
        user_ids: list[str] = []
        try:
            user_ids = [
                await _create_user(db_session, plan=plan, created_at=datetime.now(timezone.utc)) for _ in range(5)
            ]
            for user_id in user_ids:
                await _seed_feature(db_session, user_id, "compile", 1)

            headers = await _admin_headers(db_session)
            response = await client.get(f"/admin/analytics/feature-adoption?days=30&plan={plan}", headers=headers)
            assert response.status_code == 200
            body = response.json()

            registry_keys = set(all_feature_keys())
            assert body["feature_count"] == len(registry_keys)
            assert body["visible_feature_count"] == len(registry_keys)
            assert {segment["dimension"] for segment in body["segments"]} == {
                "plan",
                "role",
                "cohort",
            }
            for segment in body["segments"]:
                assert segment["denominator"] == 5
                assert len(segment["features"]) == len(registry_keys)
                assert {row["key"] for row in segment["features"]} == registry_keys

            plan_segment = _segment(body, "plan", plan)
            compile_row = _feature(plan_segment, "compile")
            assert compile_row["feature"] == "compile"
            assert compile_row["used_at_least_once"] == 5
            assert compile_row["weekly_active"] == 5
            assert compile_row["penetration"] == 100.0
            assert compile_row["weekly_active_penetration"] == 100.0
            # Zero-use registry features stay explicit instead of disappearing.
            unused = _feature(plan_segment, "team_workspaces")
            assert unused["used_at_least_once"] == 0
            assert unused["events"] == 0
        finally:
            await _cleanup(db_session, user_ids)

    async def test_used_at_least_once_wau_and_penetration(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"fa_wau_{uuid.uuid4().hex[:6]}"
        user_ids: list[str] = []
        now = datetime.now(timezone.utc)
        try:
            user_ids = [await _create_user(db_session, plan=plan, created_at=now) for _ in range(5)]
            for user_id in user_ids[:3]:
                await _seed_feature(db_session, user_id, "compile", 1, created_at=now - timedelta(days=1))
            await _seed_feature(db_session, user_ids[3], "compile", 1, created_at=now - timedelta(days=10))
            await _seed_feature(
                db_session, user_ids[0], "cover_letter_generation", 1, created_at=now - timedelta(days=2)
            )
            await _seed_feature(
                db_session, user_ids[1], "cover_letter_generation", 1, created_at=now - timedelta(days=2)
            )
            await _seed_feature(db_session, user_ids[2], "optimize", 1, created_at=now - timedelta(days=2))

            headers = await _admin_headers(db_session)
            response = await client.get(f"/admin/analytics/feature-adoption?days=30&plan={plan}", headers=headers)
            assert response.status_code == 200
            segment = _segment(response.json(), "plan", plan)

            compile_row = _feature(segment, "compile")
            assert compile_row["used_at_least_once"] == 4
            assert compile_row["weekly_active"] == 3
            assert compile_row["penetration"] == 80.0
            assert compile_row["weekly_active_penetration"] == 60.0
            assert compile_row["events"] == 4

            cover_row = _feature(segment, "cover_letters")
            assert cover_row["used_at_least_once"] == 2
            assert cover_row["weekly_active"] == 2
            assert cover_row["penetration"] == 40.0

            # Historical frontend label maps to the registry key.
            optimize_row = _feature(segment, "llm_optimize")
            assert optimize_row["used_at_least_once"] == 1

            today = now.date()
            ranged = await client.get(
                "/admin/analytics/feature-adoption"
                f"?plan={plan}&start_date={(today - timedelta(days=2)).isoformat()}"
                f"&end_date={today.isoformat()}",
                headers=headers,
            )
            assert ranged.status_code == 200
            ranged_body = ranged.json()
            assert ranged_body["days"] == 3
            ranged_compile = _feature(_segment(ranged_body, "plan", plan), "compile")
            assert ranged_compile["used_at_least_once"] == 3
            assert ranged_compile["events"] == 3
        finally:
            await _cleanup(db_session, user_ids)

    async def test_reconciliation_to_usage_analytics(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"fa_recon_{uuid.uuid4().hex[:6]}"
        user_ids: list[str] = []
        try:
            user_ids = [
                await _create_user(db_session, plan=plan, created_at=datetime.now(timezone.utc)) for _ in range(5)
            ]
            for index, user_id in enumerate(user_ids):
                await _seed_feature(db_session, user_id, "compile", index + 1)
            for user_id in user_ids[:3]:
                await _seed_feature(db_session, user_id, "cover_letters", 1)
            await _seed_event(db_session, user_ids[0], action="login")
            await _seed_event(
                db_session, user_ids[1], action="feature_usage", metadata={"feature": "not_a_registry_feature"}
            )

            headers = await _admin_headers(db_session)
            response = await client.get(f"/admin/analytics/feature-adoption?days=30&plan={plan}", headers=headers)
            assert response.status_code == 200
            body = response.json()
            segment = _segment(body, "plan", plan)

            matrix_events = sum(row["events"] for row in segment["features"])
            assert matrix_events == 18
            assert body["reconciliation"]["matrix_events"] == 18
            assert body["reconciliation"]["usage_events"] == 20
            assert body["reconciliation"]["unmatched_events"] == 2
            assert body["reconciliation"]["features_with_usage"] == 2

            raw_count = (
                await db_session.execute(
                    select(func.count(UsageAnalytics.id)).where(UsageAnalytics.user_id.in_(user_ids))
                )
            ).scalar_one()
            assert raw_count == body["reconciliation"]["usage_events"]
            assert "not_a_registry_feature" not in response.text
        finally:
            await _cleanup(db_session, user_ids)

    async def test_plan_role_and_cohort_filters(self, client: AsyncClient, db_session: AsyncSession):
        plan_a = f"fa_plan_a_{uuid.uuid4().hex[:5]}"
        plan_b = f"fa_plan_b_{uuid.uuid4().hex[:5]}"
        now = datetime.now(timezone.utc)
        previous_start = _previous_month_start()
        previous_label = _month_label(previous_start)
        current_label = _month_label(now)
        user_ids: list[str] = []
        try:
            current_ids = [await _create_user(db_session, plan=plan_a, role="user", created_at=now) for _ in range(5)]
            previous_ids = [
                await _create_user(
                    db_session,
                    plan=plan_b,
                    role="user",
                    created_at=previous_start + timedelta(days=2),
                )
                for _ in range(5)
            ]
            user_ids = current_ids + previous_ids
            for user_id in user_ids:
                await _seed_feature(db_session, user_id, "compile", 1)

            headers = await _admin_headers(db_session)
            plan_a_body = (
                await client.get(f"/admin/analytics/feature-adoption?days=90&plan={plan_a}", headers=headers)
            ).json()
            assert {segment["key"] for segment in plan_a_body["segments"] if segment["dimension"] == "plan"} == {plan_a}
            assert {segment["key"] for segment in plan_a_body["segments"] if segment["dimension"] == "cohort"} == {
                current_label
            }

            plan_b_body = (
                await client.get(f"/admin/analytics/feature-adoption?days=90&plan={plan_b}", headers=headers)
            ).json()
            assert {segment["key"] for segment in plan_b_body["segments"] if segment["dimension"] == "plan"} == {plan_b}
            assert {segment["key"] for segment in plan_b_body["segments"] if segment["dimension"] == "cohort"} == {
                previous_label
            }

            role_body = (
                await client.get(
                    f"/admin/analytics/feature-adoption?days=90&plan={plan_a}&role=user",
                    headers=headers,
                )
            ).json()
            assert {segment["key"] for segment in role_body["segments"] if segment["dimension"] == "role"} == {"user"}

            cohort_body = (
                await client.get(
                    f"/admin/analytics/feature-adoption?days=90&cohort={previous_label}",
                    headers=headers,
                )
            ).json()
            assert {segment["key"] for segment in cohort_body["segments"] if segment["dimension"] == "cohort"} == {
                previous_label
            }
            assert {segment["key"] for segment in cohort_body["segments"] if segment["dimension"] == "plan"} == {plan_b}

            # A role filter that matches no one in the selected plan returns no segments.
            excluded_body = (
                await client.get(
                    f"/admin/analytics/feature-adoption?days=90&plan={plan_a}&role=admin",
                    headers=headers,
                )
            ).json()
            assert excluded_body["segments"] == []
        finally:
            await _cleanup(db_session, user_ids)

    async def test_subscription_plan_is_joined_and_preferred(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"fa_sub_{uuid.uuid4().hex[:6]}"
        user_ids: list[str] = []
        try:
            user_ids = [
                await _create_user(db_session, plan="free", created_at=datetime.now(timezone.utc)) for _ in range(5)
            ]
            for user_id in user_ids:
                await _seed_subscription(db_session, user_id, plan_id=plan)
                await _seed_feature(db_session, user_id, "compile", 1)

            headers = await _admin_headers(db_session)
            response = await client.get(f"/admin/analytics/feature-adoption?days=30&plan={plan}", headers=headers)
            assert response.status_code == 200
            body = response.json()
            plan_segment = _segment(body, "plan", plan)
            assert plan_segment["denominator"] == 5
            assert _feature(plan_segment, "compile")["used_at_least_once"] == 5
        finally:
            await _cleanup(db_session, user_ids)


class TestFeatureAdoptionSuppressionAndAccess:
    async def test_segments_below_five_users_are_suppressed(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"fa_small_{uuid.uuid4().hex[:6]}"
        previous_start = _previous_month_start()
        user_ids: list[str] = []
        try:
            user_ids = [
                await _create_user(
                    db_session,
                    plan=plan,
                    created_at=previous_start + timedelta(days=2),
                )
                for _ in range(4)
            ]
            for user_id in user_ids:
                await _seed_feature(db_session, user_id, "compile", 3)

            headers = await _admin_headers(db_session)
            response = await client.get(f"/admin/analytics/feature-adoption?days=365&plan={plan}", headers=headers)
            assert response.status_code == 200
            body = response.json()
            assert body["minimum_segment_size"] == 5
            assert body["suppressed_segments"]["plan"] >= 1
            assert body["suppressed_segments"]["role"] >= 1
            assert body["suppressed_segments"]["cohort"] >= 1
            assert not any(segment["dimension"] == "plan" and segment["key"] == plan for segment in body["segments"])
            assert not any(segment["denominator"] == 4 for segment in body["segments"])
        finally:
            await _cleanup(db_session, user_ids)

    async def test_endpoint_is_admin_only(self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict):
        unauthenticated = await client.get("/admin/analytics/feature-adoption?days=7")
        assert unauthenticated.status_code == 401

        forbidden = await client.get("/admin/analytics/feature-adoption?days=7", headers=auth_headers)
        assert forbidden.status_code == 403

        headers = await _admin_headers(db_session)
        try:
            allowed = await client.get("/admin/analytics/feature-adoption?days=7", headers=headers)
            assert allowed.status_code == 200
            assert {
                "segments",
                "filters",
                "minimum_segment_size",
                "feature_count",
                "reconciliation",
            } <= set(allowed.json())
        finally:
            await _cleanup(db_session, [])

    async def test_entitlement_grants_are_not_usage(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"fa_grant_{uuid.uuid4().hex[:6]}"
        user_ids: list[str] = []
        try:
            user_ids = [
                await _create_user(db_session, plan=plan, created_at=datetime.now(timezone.utc)) for _ in range(5)
            ]
            await db_session.execute(
                text("INSERT INTO plan_features (plan_family, feature_key, enabled) VALUES (:plan, 'compile', true)"),
                {"plan": plan},
            )
            await db_session.commit()

            headers = await _admin_headers(db_session)
            response = await client.get(f"/admin/analytics/feature-adoption?days=30&plan={plan}", headers=headers)
            assert response.status_code == 200
            compile_row = _feature(_segment(response.json(), "plan", plan), "compile")
            assert compile_row["used_at_least_once"] == 0
            assert compile_row["weekly_active"] == 0
            assert compile_row["events"] == 0
            assert compile_row["penetration"] == 0.0
        finally:
            await _cleanup(db_session, user_ids, plan_families=[plan])

    async def test_response_excludes_metadata_text_and_user_ids(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"fa_priv_{uuid.uuid4().hex[:6]}"
        secret = "SECRET_DOCUMENT_BODY_ADOPTION_42"
        user_ids: list[str] = []
        try:
            user_ids = [
                await _create_user(db_session, plan=plan, created_at=datetime.now(timezone.utc)) for _ in range(5)
            ]
            for user_id in user_ids:
                await _seed_feature(
                    db_session,
                    user_id,
                    "compile",
                    2,
                    metadata_secret=secret,
                )
            await _seed_event(
                db_session,
                user_ids[0],
                action="feature_usage",
                metadata={"feature": secret, "raw_text": secret},
            )

            headers = await _admin_headers(db_session)
            response = await client.get(f"/admin/analytics/feature-adoption?days=30&plan={plan}", headers=headers)
            assert response.status_code == 200
            payload = response.text
            assert secret not in payload
            assert "event_metadata" not in payload
            assert "job_description" not in payload
            assert "document_content" not in payload
            for user_id in user_ids:
                assert user_id not in payload
            body = response.json()
            assert all("user_id" not in row for row in body["segments"][0]["features"])

            searched = await client.get(
                f"/admin/analytics/feature-adoption?days=30&plan={plan}&feature=compile",
                headers=headers,
            )
            assert searched.status_code == 200
            searched_body = searched.json()
            assert searched_body["visible_feature_count"] < searched_body["feature_count"]
            for segment in searched_body["segments"]:
                assert segment["features"]
                assert all(
                    "compile"
                    in " ".join(str(row[field] or "") for field in ("key", "label", "category", "description")).lower()
                    for row in segment["features"]
                )
        finally:
            await _cleanup(db_session, user_ids)
