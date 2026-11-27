"""Cohort-to-feature-flag sync and fail-closed evaluation (issue #2165).

Covers cohort creation and flag mapping, aggregate admin visibility, tenant
isolation, the five-user minimum, consent-gated evaluation, exposure
deduplication, stale/error fail-closed behaviour, audit evidence, the migration
contract and admin RBAC. All accounts, tenants and flags are synthetic.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AdminAuditLog

ADMIN = "/admin/cohorts"
EVALUATE = "/analytics/cohorts/evaluate"
REASON = "Cohort sync test reason"
NOW = datetime.now(timezone.utc)


def _suffix() -> str:
    return uuid.uuid4().hex[:12]


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    tenant_id: str | None = None,
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    token = f"test_sess_cohort_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, created_at, default_tenant_id) "
            "VALUES (:id, :email, 'Cohort Test User', :role, true, 'free', "
            "'active', false, :created, :tenant_id)"
        ),
        {
            "id": user_id,
            "email": f"test_cohort_{user_id.replace('-', '')}@example.com",
            "role": role,
            "created": NOW,
            "tenant_id": tenant_id,
        },
    )
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": NOW + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return user_id, {"Authorization": f"Bearer {token}"}


async def _create_tenant(db: AsyncSession, owner_id: str) -> str:
    tenant_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO tenants (id, slug, name, owner_id, plan_id, max_members, active) "
            "VALUES (:id, :slug, 'Cohort Test Tenant', :owner, 'agency', 50, true)"
        ),
        {"id": tenant_id, "slug": f"test-cohort-{_suffix()}", "owner": owner_id},
    )
    await db.commit()
    return tenant_id


async def _create_flag(db: AsyncSession, *, enabled: bool = True) -> str:
    key = f"test_cohort_flag_{_suffix()}"
    await db.execute(
        text(
            "INSERT INTO feature_flags (key, enabled, label) "
            "VALUES (:key, :enabled, 'Test cohort flag')"
        ),
        {"key": key, "enabled": enabled},
    )
    await db.commit()
    return key


async def _consent(
    db: AsyncSession,
    anonymous_id: str,
    *,
    decision: str = "granted",
    created_at: datetime | None = None,
) -> None:
    action = {
        "granted": "consent_granted",
        "denied": "consent_denied",
        "withdrawn": "consent_withdrawn",
    }[decision]
    await db.execute(
        text(
            "INSERT INTO usage_analytics (id, user_id, action, resource_type, "
            "event_metadata, created_at) "
            "VALUES (:id, NULL, :action, 'consent', CAST(:metadata AS JSONB), :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "action": action,
            "metadata": json.dumps(
                {
                    "decision": decision,
                    "surface": "banner",
                    "source": "first_party_consent",
                    "anonymous_id": anonymous_id,
                }
            ),
            "created": created_at or NOW - timedelta(minutes=5),
        },
    )
    await db.commit()


async def _create_cohort(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    key: str | None = None,
    tenant_id: str | None = None,
    stale_after_seconds: int = 86_400,
    minimum_size: int = 5,
) -> dict:
    response = await client.post(
        ADMIN,
        headers=headers,
        json={
            "key": key or f"testcohort_{_suffix()}",
            "name": "Test PostHog cohort",
            "description": "Synthetic cohort for tests",
            "tenant_id": tenant_id,
            "posthog_cohort_id": f"ph-{_suffix()}",
            "minimum_size": minimum_size,
            "stale_after_seconds": stale_after_seconds,
            "reason": REASON,
            "confirm": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _map(client: AsyncClient, headers: dict[str, str], cohort_id: str, flag_key: str):
    return await client.post(
        f"{ADMIN}/{cohort_id}/mappings",
        headers=headers,
        json={"flag_key": flag_key, "reason": REASON, "confirm": True},
    )


async def _sync(
    client: AsyncClient,
    headers: dict[str, str],
    cohort_id: str,
    *,
    members: list[str] | None = None,
    error_code: str | None = None,
):
    payload: dict = {"reason": REASON, "confirm": True}
    if members is not None:
        payload["members"] = members
    if error_code is not None:
        payload["error_code"] = error_code
    return await client.post(f"{ADMIN}/{cohort_id}/sync", headers=headers, json=payload)


async def _evaluate(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    anonymous_id: str,
    flag_keys: list[str],
):
    return await client.post(
        EVALUATE,
        headers=headers,
        json={"anonymous_id": anonymous_id, "flag_keys": flag_keys},
    )


async def _list(client: AsyncClient, headers: dict[str, str], cohort_id: str) -> dict:
    response = await client.get(ADMIN, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    return next(item for item in body["cohorts"] if item["id"] == cohort_id)


async def _exposure_count(db: AsyncSession, user_id: str, flag_key: str) -> int:
    return int(
        await db.scalar(
            text(
                "SELECT count(*) FROM usage_analytics "
                "WHERE user_id = :uid AND action = 'cohort_flag_exposed' "
                "AND event_metadata->>'flag_key' = :flag"
            ),
            {"uid": user_id, "flag": flag_key},
        )
        or 0
    )


async def test_admin_creates_maps_lists_and_audits_without_member_identifiers(
    client: AsyncClient, db_session: AsyncSession
):
    _admin_id, admin_headers = await _create_user(db_session, role="admin")
    flag_key = await _create_flag(db_session)
    cohort = await _create_cohort(client, admin_headers)

    assert cohort["status"] == "never_synced"
    assert cohort["size"] == 0
    assert cohort["flags"] == []
    assert cohort["evaluation_allowed"] is False

    mapped = await _map(client, admin_headers, cohort["id"], flag_key)
    assert mapped.status_code == 201, mapped.text
    assert [item["key"] for item in mapped.json()["flags"]] == [flag_key]

    listed = await _list(client, admin_headers, cohort["id"])
    assert listed["status"] == "never_synced"
    assert listed["last_sync_error"] is None
    assert listed["flags"][0]["key"] == flag_key
    assert listed["tenant_slug"] is None

    summaries = await client.get(ADMIN, headers=admin_headers)
    body = summaries.json()
    assert body["aggregate_only"] is True
    assert body["member_identifiers_returned"] is False
    assert body["summary"]["with_flag_mappings"] >= 1

    actions = (
        await db_session.execute(
            select(AdminAuditLog.action).where(
                AdminAuditLog.action.in_(["cohort.create", "cohort.flag_map"])
            )
        )
    ).scalars().all()
    assert "cohort.create" in actions
    assert "cohort.flag_map" in actions

    duplicate = await _map(client, admin_headers, cohort["id"], flag_key)
    assert duplicate.status_code == 409

    unknown = await _map(client, admin_headers, cohort["id"], f"missing_{_suffix()}")
    assert unknown.status_code == 422

    unmapped = await client.delete(
        f"{ADMIN}/{cohort['id']}/mappings/{flag_key}",
        params={"reason": REASON, "confirm": "true"},
        headers=admin_headers,
    )
    assert unmapped.status_code == 200, unmapped.text
    assert unmapped.json()["flags"] == []


async def test_sync_replaces_membership_and_evaluation_records_exposure(
    client: AsyncClient, db_session: AsyncSession
):
    _admin_id, admin_headers = await _create_user(db_session, role="admin")
    flag_key = await _create_flag(db_session)
    cohort = await _create_cohort(client, admin_headers)
    assert (await _map(client, admin_headers, cohort["id"], flag_key)).status_code == 201

    members = [(await _create_user(db_session)) for _ in range(6)]
    sync = await _sync(
        client, admin_headers, cohort["id"], members=[user_id for user_id, _ in members]
    )
    assert sync.status_code == 200, sync.text
    assert sync.json()["status"] == "synced"
    assert sync.json()["size"] == 6
    assert sync.json()["sync_counts"] == {
        "requested": 6,
        "accepted": 6,
        "rejected_malformed": 0,
        "rejected_unknown": 0,
        "rejected_tenant": 0,
    }

    member_id, member_headers = members[0]
    anonymous_id = f"cohort-anon-{_suffix()}"
    await _consent(db_session, anonymous_id)

    first = await _evaluate(
        client, member_headers, anonymous_id=anonymous_id, flag_keys=[flag_key]
    )
    assert first.status_code == 200, first.text
    result = first.json()["results"][0]
    assert result == {
        "key": flag_key,
        "enabled": True,
        "reason": "cohort_match",
        "exposure_recorded": True,
    }
    assert await _exposure_count(db_session, member_id, flag_key) == 1

    second = await _evaluate(
        client, member_headers, anonymous_id=anonymous_id, flag_keys=[flag_key]
    )
    assert second.json()["results"][0]["exposure_recorded"] is False
    assert await _exposure_count(db_session, member_id, flag_key) == 1

    outsider_id, outsider_headers = await _create_user(db_session)
    outsider_anon = f"cohort-anon-{_suffix()}"
    await _consent(db_session, outsider_anon)
    outsider = await _evaluate(
        client, outsider_headers, anonymous_id=outsider_anon, flag_keys=[flag_key]
    )
    assert outsider.json()["results"][0]["enabled"] is False
    assert outsider.json()["results"][0]["reason"] == "not_in_cohort"
    assert await _exposure_count(db_session, outsider_id, flag_key) == 1

    # A later successful sync replaces the prior snapshot atomically.
    replacement = await _sync(
        client,
        admin_headers,
        cohort["id"],
        members=[user_id for user_id, _ in members[1:]],
    )
    assert replacement.status_code == 200
    assert replacement.json()["size"] == 5
    after_removal = await _evaluate(
        client, member_headers, anonymous_id=anonymous_id, flag_keys=[flag_key]
    )
    assert after_removal.json()["results"][0]["enabled"] is False


async def test_stale_and_error_syncs_fail_closed_and_are_visible(
    client: AsyncClient, db_session: AsyncSession
):
    _admin_id, admin_headers = await _create_user(db_session, role="admin")
    flag_key = await _create_flag(db_session)
    cohort = await _create_cohort(client, admin_headers, stale_after_seconds=300)
    assert (await _map(client, admin_headers, cohort["id"], flag_key)).status_code == 201

    members = [(await _create_user(db_session)) for _ in range(5)]
    member_id, member_headers = members[0]
    anonymous_id = f"cohort-anon-{_suffix()}"
    await _consent(db_session, anonymous_id)
    assert (
        await _sync(
            client,
            admin_headers,
            cohort["id"],
            members=[user_id for user_id, _ in members],
        )
    ).status_code == 200

    fresh = await _evaluate(
        client, member_headers, anonymous_id=anonymous_id, flag_keys=[flag_key]
    )
    assert fresh.json()["results"][0]["enabled"] is True

    await db_session.execute(
        text(
            "UPDATE feature_cohorts SET last_synced_at = :old WHERE id = :id"
        ),
        {"old": NOW - timedelta(hours=1), "id": cohort["id"]},
    )
    await db_session.commit()

    stale_listed = await _list(client, admin_headers, cohort["id"])
    assert stale_listed["status"] == "stale"
    assert stale_listed["is_stale"] is True
    assert stale_listed["evaluation_allowed"] is False
    stale_eval = await _evaluate(
        client, member_headers, anonymous_id=anonymous_id, flag_keys=[flag_key]
    )
    assert stale_eval.json()["results"][0]["enabled"] is False
    assert stale_eval.json()["results"][0]["reason"] == "sync_not_current"
    # Exposure is still recorded for the failed-closed evaluation.
    assert await _exposure_count(db_session, member_id, flag_key) == 1
    stale_eval_again = await _evaluate(
        client, member_headers, anonymous_id=anonymous_id, flag_keys=[flag_key]
    )
    assert stale_eval_again.json()["results"][0]["exposure_recorded"] is False

    failed = await _sync(
        client, admin_headers, cohort["id"], error_code="posthog_timeout"
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "error"
    assert failed.json()["last_sync_error"] == "posthog_timeout"

    error_listed = await _list(client, admin_headers, cohort["id"])
    assert error_listed["status"] == "error"
    assert error_listed["last_sync_error"] == "posthog_timeout"

    error_eval = await _evaluate(
        client, member_headers, anonymous_id=anonymous_id, flag_keys=[flag_key]
    )
    assert error_eval.json()["results"][0]["enabled"] is False
    assert error_eval.json()["results"][0]["reason"] == "sync_not_current"

    invalid_error = await _sync(
        client,
        admin_headers,
        cohort["id"],
        error_code="Provider said: timeout with secret detail",
    )
    assert invalid_error.status_code == 422

    recovered = await _sync(
        client,
        admin_headers,
        cohort["id"],
        members=[user_id for user_id, _ in members],
    )
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "synced"
    assert recovered.json()["last_sync_error"] is None
    recovered_eval = await _evaluate(
        client, member_headers, anonymous_id=anonymous_id, flag_keys=[flag_key]
    )
    assert recovered_eval.json()["results"][0]["enabled"] is True


async def test_public_operational_flag_fails_closed_while_cohort_mapped(
    client: AsyncClient, db_session: AsyncSession
):
    _admin_id, admin_headers = await _create_user(db_session, role="admin")
    existing = await db_session.scalar(
        text("SELECT enabled FROM feature_flags WHERE key = 'upgrade_ctas'")
    )
    await db_session.execute(
        text(
            "INSERT INTO feature_flags (key, enabled, label) "
            "VALUES ('upgrade_ctas', true, 'Upgrade CTAs') "
            "ON CONFLICT (key) DO UPDATE SET enabled = true"
        )
    )
    await db_session.commit()
    try:
        before = await client.get("/config/feature-flags")
        assert before.status_code == 200
        assert before.json()["upgrade_ctas"] is True

        cohort = await _create_cohort(client, admin_headers)
        mapped = await _map(client, admin_headers, cohort["id"], "upgrade_ctas")
        assert mapped.status_code == 201

        gated = await client.get("/config/feature-flags")
        assert gated.json()["upgrade_ctas"] is False

        unmapped = await client.delete(
            f"{ADMIN}/{cohort['id']}/mappings/upgrade_ctas",
            params={"reason": REASON, "confirm": "true"},
            headers=admin_headers,
        )
        assert unmapped.status_code == 200

        after = await client.get("/config/feature-flags")
        assert after.json()["upgrade_ctas"] is True
    finally:
        await db_session.execute(
            text("UPDATE feature_flags SET enabled = :enabled WHERE key = 'upgrade_ctas'"),
            {"enabled": bool(existing) if existing is not None else True},
        )
        await db_session.commit()


async def test_below_minimum_cohort_is_suppressed_and_never_enables(
    client: AsyncClient, db_session: AsyncSession
):
    _admin_id, admin_headers = await _create_user(db_session, role="admin")
    flag_key = await _create_flag(db_session)
    cohort = await _create_cohort(client, admin_headers)
    assert (await _map(client, admin_headers, cohort["id"], flag_key)).status_code == 201

    members = [(await _create_user(db_session)) for _ in range(3)]
    member_id, member_headers = members[0]
    anonymous_id = f"cohort-anon-{_suffix()}"
    await _consent(db_session, anonymous_id)
    synced = await _sync(
        client, admin_headers, cohort["id"], members=[uid for uid, _ in members]
    )
    assert synced.status_code == 200
    assert synced.json()["status"] == "below_minimum"
    assert synced.json()["size"] is None
    assert synced.json()["size_suppressed"] is True
    assert synced.json()["evaluation_allowed"] is False

    evaluated = await _evaluate(
        client, member_headers, anonymous_id=anonymous_id, flag_keys=[flag_key]
    )
    assert evaluated.json()["results"][0]["enabled"] is False
    assert evaluated.json()["results"][0]["reason"] == "sync_not_current"

    too_small = await client.post(
        ADMIN,
        headers=admin_headers,
        json={
            "key": f"testcohort_{_suffix()}",
            "name": "Too small",
            "minimum_size": 4,
            "reason": REASON,
            "confirm": True,
        },
    )
    assert too_small.status_code == 422


async def test_tenant_scoped_membership_does_not_cross_tenants(
    client: AsyncClient, db_session: AsyncSession
):
    admin_id, admin_headers = await _create_user(db_session, role="admin")
    tenant_a = await _create_tenant(db_session, admin_id)
    tenant_b = await _create_tenant(db_session, admin_id)
    flag_key = await _create_flag(db_session)
    cohort = await _create_cohort(client, admin_headers, tenant_id=tenant_a)
    assert (await _map(client, admin_headers, cohort["id"], flag_key)).status_code == 201

    tenant_a_members = [
        (await _create_user(db_session, tenant_id=tenant_a)) for _ in range(5)
    ]
    tenant_b_members = [
        (await _create_user(db_session, tenant_id=tenant_b)) for _ in range(3)
    ]
    synced = await _sync(
        client,
        admin_headers,
        cohort["id"],
        members=[uid for uid, _ in tenant_a_members]
        + [uid for uid, _ in tenant_b_members],
    )
    assert synced.status_code == 200
    assert synced.json()["size"] == 5
    assert synced.json()["sync_counts"]["rejected_tenant"] == 3

    anonymous_a = f"cohort-anon-{_suffix()}"
    anonymous_b = f"cohort-anon-{_suffix()}"
    await _consent(db_session, anonymous_a)
    await _consent(db_session, anonymous_b)

    allowed = await _evaluate(
        client,
        tenant_a_members[0][1],
        anonymous_id=anonymous_a,
        flag_keys=[flag_key],
    )
    assert allowed.json()["results"][0]["enabled"] is True

    denied = await _evaluate(
        client,
        tenant_b_members[0][1],
        anonymous_id=anonymous_b,
        flag_keys=[flag_key],
    )
    assert denied.json()["results"][0]["enabled"] is False
    assert denied.json()["results"][0]["reason"] == "not_in_cohort"

    listed = await _list(client, admin_headers, cohort["id"])
    assert listed["tenant_slug"].startswith("test-cohort-")
    serialized = json.dumps(listed)
    for user_id, _ in tenant_a_members + tenant_b_members:
        assert user_id not in serialized


async def test_consent_is_required_for_treatment_and_exposure(
    client: AsyncClient, db_session: AsyncSession
):
    _admin_id, admin_headers = await _create_user(db_session, role="admin")
    flag_key = await _create_flag(db_session)
    cohort = await _create_cohort(client, admin_headers)
    assert (await _map(client, admin_headers, cohort["id"], flag_key)).status_code == 201

    members = [(await _create_user(db_session)) for _ in range(5)]
    member_id, member_headers = members[0]
    assert (
        await _sync(
            client,
            admin_headers,
            cohort["id"],
            members=[uid for uid, _ in members],
        )
    ).status_code == 200

    anonymous_id = f"cohort-anon-{_suffix()}"
    await _consent(db_session, anonymous_id, decision="denied")
    denied = await _evaluate(
        client, member_headers, anonymous_id=anonymous_id, flag_keys=[flag_key]
    )
    assert denied.status_code == 200
    assert denied.json()["consent_required"] is True
    assert denied.json()["results"][0]["enabled"] is False
    assert denied.json()["results"][0]["reason"] == "consent_required"
    assert await _exposure_count(db_session, member_id, flag_key) == 0

    await _consent(
        db_session, anonymous_id, decision="granted", created_at=NOW - timedelta(minutes=1)
    )
    granted = await _evaluate(
        client, member_headers, anonymous_id=anonymous_id, flag_keys=[flag_key]
    )
    assert granted.json()["results"][0]["enabled"] is True
    assert await _exposure_count(db_session, member_id, flag_key) == 1

    await _consent(
        db_session, anonymous_id, decision="withdrawn", created_at=NOW + timedelta(minutes=1)
    )
    withdrawn = await _evaluate(
        client, member_headers, anonymous_id=anonymous_id, flag_keys=[flag_key]
    )
    assert withdrawn.json()["results"][0]["enabled"] is False
    assert withdrawn.json()["results"][0]["reason"] == "consent_required"
    assert await _exposure_count(db_session, member_id, flag_key) == 1

    invalid = await client.post(
        EVALUATE,
        headers=member_headers,
        json={"anonymous_id": "person@example.com", "flag_keys": [flag_key]},
    )
    assert invalid.status_code == 422


async def test_cohort_admin_routes_are_admin_only(
    client: AsyncClient, db_session: AsyncSession
):
    _admin_id, admin_headers = await _create_user(db_session, role="admin")
    _user_id, user_headers = await _create_user(db_session, role="user")
    cohort = await _create_cohort(client, admin_headers)

    for headers in ({}, user_headers):
        assert (await client.get(ADMIN, headers=headers)).status_code in {401, 403}
        assert (
            await client.post(
                ADMIN,
                headers=headers,
                json={
                    "key": f"testcohort_{_suffix()}",
                    "name": "Denied",
                    "reason": REASON,
                    "confirm": True,
                },
            )
        ).status_code in {401, 403}
        assert (
            await client.post(
                f"{ADMIN}/{cohort['id']}/sync",
                headers=headers,
                json={"members": [], "reason": REASON, "confirm": True},
            )
        ).status_code in {401, 403}

    missing_confirm = await client.post(
        ADMIN,
        headers=admin_headers,
        json={
            "key": f"testcohort_{_suffix()}",
            "name": "No confirm",
            "reason": REASON,
        },
    )
    assert missing_confirm.status_code == 422


def test_migration_declares_reserved_revision_tables_and_constraints():
    path = Path(__file__).parents[1] / "alembic/versions/0108_cohort_sync.py"
    spec = importlib.util.spec_from_file_location("cohort_sync_migration", path)
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

    assert migration.revision == "0108_cohort_sync"
    assert migration.down_revision == "0106_admin_experiments"
    migration.op = FakeOp()
    migration.upgrade()

    tables = [call[1] for call in calls if call[0] == "create_table"]
    assert tables == [
        "feature_cohorts",
        "feature_cohort_members",
        "feature_cohort_flag_mappings",
    ]
    cohort_columns = {
        column.name: column
        for column in next(call for call in calls if call[0] == "create_table")[2]
        if column.__class__.__name__ == "Column"
    }
    assert set(cohort_columns) == {
        "id",
        "key",
        "name",
        "description",
        "tenant_id",
        "posthog_cohort_id",
        "minimum_size",
        "stale_after_seconds",
        "sync_state",
        "synced_size",
        "last_sync_attempt_at",
        "last_synced_at",
        "last_sync_error",
        "created_at",
        "updated_at",
    }
    member_columns = {
        column.name
        for column in calls[2][2]
        if column.__class__.__name__ == "Column"
    }
    assert member_columns == {"cohort_id", "user_id", "synced_at"}
    mapping_columns = {
        column.name
        for column in calls[4][2]
        if column.__class__.__name__ == "Column"
    }
    assert mapping_columns == {"cohort_id", "flag_key", "created_at"}

    migration.downgrade()
    dropped = [call[1] for call in calls if call[0] == "drop_table"]
    assert dropped == [
        "feature_cohort_flag_mappings",
        "feature_cohort_members",
        "feature_cohorts",
    ]
