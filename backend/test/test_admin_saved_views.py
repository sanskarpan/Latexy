"""Saved admin views and aggregate cohort segments.

Covers RBAC, private/shared visibility, optimistic concurrency, soft delete,
audit, allowlisted view filters, the typed segment DSL, five-user suppression
and SQL-injection attempts. All identifiers used here are synthetic.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _token(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "admin",
    plan: str = "free",
    verified: bool = True,
    created_at: datetime | None = None,
    tenant_id: str | None = None,
    email: str | None = None,
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    token = f"test_sess_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, created_at, default_tenant_id) "
            "VALUES (:id, :email, :name, :role, :verified, :plan, 'active', false, "
            "COALESCE(:created_at, now()), :tenant_id)"
        ),
        {
            "id": user_id,
            "email": email or f"test_saved_views_{user_id.replace('-', '')}@example.com",
            "name": "Saved Views User",
            "role": role,
            "verified": verified,
            "plan": plan,
            "created_at": created_at,
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
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return user_id, {"Authorization": f"Bearer {token}"}


async def _admin_headers(
    db: AsyncSession, *, role: str = "admin", **kwargs
) -> dict[str, str]:
    _user_id, headers = await _create_user(db, role=role, **kwargs)
    return headers


async def _create_tenant(db: AsyncSession, owner_id: str, *, slug: str | None = None) -> str:
    tenant_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO tenants (id, slug, name, owner_id, plan_id, max_members, active) "
            "VALUES (:id, :slug, 'Saved View Tenant', :owner, 'agency', 10, true)"
        ),
        {
            "id": tenant_id,
            "slug": slug or f"test-tenant-{tenant_id[:8]}",
            "owner": owner_id,
        },
    )
    await db.commit()
    return tenant_id


async def _event(db: AsyncSession, user_id: str, action: str, metadata: dict | None = None) -> None:
    await db.execute(
        text(
            "INSERT INTO usage_analytics (id, user_id, action, event_metadata, created_at) "
            "VALUES (:id, :uid, :action, CAST(:metadata AS jsonb), now())"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "action": action,
            "metadata": json.dumps(metadata or {}),
        },
    )
    await db.commit()


def _view(**overrides):
    body = {
        "name": "Growth review",
        "scope": "analytics",
        "filters": {"plan": "pro", "compiler": "pdflatex"},
        "columns": ["kpis", "funnel"],
        "sort": {"field": "plan", "direction": "asc"},
        "range_days": 30,
        "shared": False,
        "is_default": False,
    }
    body.update(overrides)
    return body


def _segment_definition(**overrides):
    body = {
        "match": "all",
        "conditions": [
            {"field": "plan", "operator": "eq", "value": "pro"},
        ],
    }
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
async def _clean_saved_views(db_session: AsyncSession):
    await db_session.execute(text("DELETE FROM admin_saved_views"))
    await db_session.execute(text("DELETE FROM admin_segments"))
    await db_session.commit()
    yield
    await db_session.execute(text("DELETE FROM admin_saved_views"))
    await db_session.execute(text("DELETE FROM admin_segments"))
    await db_session.commit()


async def _create_view(client: AsyncClient, headers: dict[str, str], **overrides) -> dict:
    response = await client.post("/admin/saved-views", json=_view(**overrides), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _create_segment(client: AsyncClient, headers: dict[str, str], **overrides) -> dict:
    body = {
        "name": "Plan cohort",
        "description": "Aggregate plan cohort",
        "definition": _segment_definition(),
        "shared": False,
    }
    body.update(overrides)
    response = await client.post("/admin/segments", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _audit_actions(db: AsyncSession, target_type: str, target_id: str) -> list[str]:
    rows = (
        await db.execute(
            text(
                "SELECT action FROM admin_audit_log "
                "WHERE target_type = :target_type AND target_id = :target_id "
                "ORDER BY created_at ASC"
            ),
            {"target_type": target_type, "target_id": target_id},
        )
    ).scalars().all()
    return list(rows)


# --------------------------------------------------------------------------- #
#  RBAC and boundaries                                                        #
# --------------------------------------------------------------------------- #


async def test_saved_views_and_segments_are_admin_only(
    client: AsyncClient, db_session: AsyncSession
):
    assert (await client.get("/admin/saved-views")).status_code == 401
    assert (await client.get("/admin/segments")).status_code == 401
    assert (
        await client.post("/admin/segments/preview", json={"definition": _segment_definition()})
    ).status_code == 401

    support = await _admin_headers(db_session, role="support")
    for method, path, body in [
        ("get", "/admin/saved-views", None),
        ("post", "/admin/saved-views", _view()),
        ("get", "/admin/saved-views/catalog", None),
        ("get", "/admin/segments", None),
        ("post", "/admin/segments", {"name": "Nope", "definition": _segment_definition()}),
        ("post", "/admin/segments/preview", {"definition": _segment_definition()}),
        ("get", "/admin/segments/fields", None),
    ]:
        response = await getattr(client, method)(path, headers=support, **({"json": body} if body else {}))
        assert response.status_code == 403, (method, path, response.text)

    admin = await _admin_headers(db_session)
    for path in ["/admin/saved-views", "/admin/saved-views/catalog", "/admin/segments", "/admin/segments/fields"]:
        response = await client.get(path, headers=admin)
        assert response.status_code == 200, (path, response.text)


async def test_private_views_are_owner_only_and_shared_views_are_read_only_to_others(
    client: AsyncClient, db_session: AsyncSession
):
    owner = await _admin_headers(db_session)
    other = await _admin_headers(db_session)

    private = await _create_view(client, owner, name="Private review")
    private_id = private["id"]
    assert private["is_owner"] is True

    assert (await client.get(f"/admin/saved-views/{private_id}", headers=other)).status_code == 404
    other_list = await client.get("/admin/saved-views", headers=other)
    assert other_list.status_code == 200
    assert other_list.json()["items"] == []

    shared = await _create_view(client, owner, name="Shared review", shared=True)
    shared_id = shared["id"]
    visible = await client.get(f"/admin/saved-views/{shared_id}", headers=other)
    assert visible.status_code == 200, visible.text
    assert visible.json()["is_owner"] is False
    assert visible.json()["shared"] is True

    forbidden = await client.patch(
        f"/admin/saved-views/{shared_id}",
        json={"expected_version": 1, "name": "Hijacked"},
        headers=other,
    )
    assert forbidden.status_code == 403
    forbidden_delete = await client.delete(
        f"/admin/saved-views/{shared_id}",
        params={"version": 1, "confirm": "true", "reason": "cross-admin attempt"},
        headers=other,
    )
    assert forbidden_delete.status_code == 403

    assert (await client.get(f"/admin/saved-views/{private_id}", headers=owner)).status_code == 200


# --------------------------------------------------------------------------- #
#  View CRUD, validation, concurrency and audit                               #
# --------------------------------------------------------------------------- #


async def test_saved_view_crud_defaults_share_rename_and_soft_delete(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(db_session)
    first = await _create_view(client, headers, name="Default analytics", is_default=True)
    assert first["filters"] == {"plan": "pro", "compiler": "pdflatex"}
    assert first["columns"] == ["kpis", "funnel"]
    assert first["sort"] == {"field": "plan", "direction": "asc"}
    assert first["range_days"] == 30
    assert first["version"] == 1

    second = await _create_view(client, headers, name="Secondary analytics", is_default=True)
    # Setting a new default clears the previous one in the same scope.
    refreshed = await client.get(f"/admin/saved-views/{first['id']}", headers=headers)
    assert refreshed.json()["is_default"] is False
    assert second["is_default"] is True

    renamed = await client.patch(
        f"/admin/saved-views/{second['id']}",
        json={
            "expected_version": 1,
            "name": "Renamed analytics",
            "shared": True,
            "filters": {"plan": ["pro", "team"], "feature": "compile"},
            "range_days": 90,
        },
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    body = renamed.json()
    assert body["name"] == "Renamed analytics"
    assert body["shared"] is True
    assert body["version"] == 2
    assert body["filters"]["plan"] == ["pro", "team"]
    assert body["range_days"] == 90

    stale = await client.patch(
        f"/admin/saved-views/{second['id']}",
        json={"expected_version": 1, "name": "Stale write"},
        headers=headers,
    )
    assert stale.status_code == 409

    missing_reason = await client.delete(
        f"/admin/saved-views/{second['id']}",
        params={"version": 2, "confirm": "true"},
        headers=headers,
    )
    assert missing_reason.status_code == 422
    unconfirmed = await client.delete(
        f"/admin/saved-views/{second['id']}",
        params={"version": 2, "reason": "duplicate view"},
        headers=headers,
    )
    assert unconfirmed.status_code == 422

    deleted = await client.delete(
        f"/admin/saved-views/{second['id']}",
        params={"version": 2, "confirm": "true", "reason": "duplicate view"},
        headers=headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    assert (await client.get(f"/admin/saved-views/{second['id']}", headers=headers)).status_code == 404
    listed = await client.get("/admin/saved-views", headers=headers)
    assert [item["id"] for item in listed.json()["items"]] == [first["id"]]

    # Soft delete retains the row and its audit trail.
    row = (
        await db_session.execute(
            text(
                "SELECT deleted_at, version FROM admin_saved_views WHERE id = :id"
            ),
            {"id": second["id"]},
        )
    ).mappings().one()
    assert row["deleted_at"] is not None
    assert row["version"] == 3

    actions = await _audit_actions(db_session, "admin_saved_view", second["id"])
    assert actions == [
        "admin.saved_view.create",
        "admin.saved_view.share",
        "admin.saved_view.delete",
    ]
    # Audit snapshots never carry the view name or filter values.
    audit_payload = (
        await db_session.execute(
            text(
                "SELECT before, after FROM admin_audit_log "
                "WHERE target_type = 'admin_saved_view' AND target_id = :id "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"id": second["id"]},
        )
    ).mappings().one()
    assert "Renamed analytics" not in str(audit_payload)


async def test_view_validation_rejects_unknown_filters_pii_and_bad_ranges(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(db_session)
    cases = [
        {**_view(), "filters": {"unknown_field": "x"}},
        {**_view(), "filters": {"plan": "enterprise"}},
        {**_view(), "filters": {"compiler": "pdflatex; DROP TABLE users"}},
        {**_view(), "filters": {"template": "not-a-uuid"}},
        {**_view(), "filters": {"plan": ["pro"] * 21}},
        {**_view(), "columns": ["secret_prompt"]},
        {**_view(), "sort": {"field": "name", "direction": "asc"}},
        {**_view(), "range_days": 500},
        {**_view(), "name": "alice@example.com"},
        {**_view(), "name": "Call 555 123 4567"},
        {**_view(), "name": "\\documentclass{article}"},
        {**_view(), "scope": "flags"},
        {**_view(), "filters": {"plan": {"sql": "SELECT 1"}}},
    ]
    for body in cases:
        response = await client.post("/admin/saved-views", json=body, headers=headers)
        assert response.status_code == 422, (body, response.text)

    operations = await client.post(
        "/admin/saved-views",
        json=_view(
            name="Operations review",
            scope="operations",
            filters={"status": "open", "severity": "high", "service": "worker"},
            columns=["incidents"],
            sort={"field": "severity", "direction": "desc"},
        ),
        headers=headers,
    )
    assert operations.status_code == 201, operations.text
    # Analytics-only filter keys are not accepted for the operations scope.
    mixed = await client.post(
        "/admin/saved-views",
        json=_view(
            name="Mixed operations",
            scope="operations",
            filters={"compiler": "pdflatex"},
        ),
        headers=headers,
    )
    assert mixed.status_code == 422


async def test_view_names_are_deduped_per_owner_and_scope(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(db_session)
    first = await _create_view(client, headers, name="Duplicated")
    duplicate = await client.post(
        "/admin/saved-views",
        json=_view(name="duplicated"),
        headers=headers,
    )
    assert duplicate.status_code == 409
    other_scope = await client.post(
        "/admin/saved-views",
        json=_view(
            name="Duplicated",
            scope="quality",
            filters={"plan": "pro"},
            columns=["templates"],
            sort={"field": "plan", "direction": "asc"},
        ),
        headers=headers,
    )
    assert other_scope.status_code == 201, other_scope.text

    other_admin = await _admin_headers(db_session)
    allowed = await client.post(
        "/admin/saved-views",
        json=_view(name="Duplicated"),
        headers=other_admin,
    )
    assert allowed.status_code == 201

    rename = await client.patch(
        f"/admin/saved-views/{first['id']}",
        json={"expected_version": 1, "name": "Duplicated too"},
        headers=headers,
    )
    assert rename.status_code == 200


async def test_view_pagination_is_stable_and_bounded(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(db_session)
    created = []
    for index in range(5):
        created.append(await _create_view(client, headers, name=f"View {index}"))
    page_one = await client.get(
        "/admin/saved-views", params={"limit": 2, "offset": 0}, headers=headers
    )
    page_two = await client.get(
        "/admin/saved-views", params={"limit": 2, "offset": 2}, headers=headers
    )
    assert page_one.status_code == page_two.status_code == 200
    assert page_one.json()["total"] == 5
    ids_one = [item["id"] for item in page_one.json()["items"]]
    ids_two = [item["id"] for item in page_two.json()["items"]]
    assert len(ids_one) == len(ids_two) == 2
    assert not set(ids_one) & set(ids_two)
    too_large = await client.get(
        "/admin/saved-views", params={"limit": 500}, headers=headers
    )
    assert too_large.status_code == 422


# --------------------------------------------------------------------------- #
#  Segment DSL, preview suppression and injection handling                    #
# --------------------------------------------------------------------------- #


async def test_segment_crud_catalog_and_ownership(
    client: AsyncClient, db_session: AsyncSession
):
    owner = await _admin_headers(db_session)
    other = await _admin_headers(db_session)

    catalog = await client.get("/admin/segments/fields", headers=owner)
    assert catalog.status_code == 200
    payload = catalog.json()
    assert payload["minimum_cohort"] == 5
    assert {field["field"] for field in payload["fields"]} == {
        "plan",
        "role",
        "signup_month",
        "verified",
        "tenant",
        "feature_used",
        "country_bucket",
    }

    private = await _create_segment(client, owner, name="Private cohort")
    assert private["version"] == 1
    assert (await client.get(f"/admin/segments/{private['id']}", headers=other)).status_code == 404

    shared = await _create_segment(client, owner, name="Shared cohort", shared=True)
    visible = await client.get(f"/admin/segments/{shared['id']}", headers=other)
    assert visible.status_code == 200
    assert visible.json()["is_owner"] is False

    forbidden = await client.patch(
        f"/admin/segments/{shared['id']}",
        json={"expected_version": 1, "name": "Hijacked"},
        headers=other,
    )
    assert forbidden.status_code == 403

    renamed = await client.patch(
        f"/admin/segments/{private['id']}",
        json={
            "expected_version": 1,
            "name": "Renamed cohort",
            "definition": _segment_definition(
                conditions=[
                    {"field": "role", "operator": "in", "value": ["user", "support"]},
                    {"field": "verified", "operator": "eq", "value": True},
                ]
            ),
        },
        headers=owner,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["version"] == 2
    assert renamed.json()["condition_count"] == 2

    stale = await client.patch(
        f"/admin/segments/{private['id']}",
        json={"expected_version": 1, "name": "Stale"},
        headers=owner,
    )
    assert stale.status_code == 409

    deleted = await client.delete(
        f"/admin/segments/{private['id']}",
        params={"version": 2, "confirm": "true", "reason": "cohort no longer needed"},
        headers=owner,
    )
    assert deleted.status_code == 200
    assert (await client.get(f"/admin/segments/{private['id']}", headers=owner)).status_code == 404
    actions = await _audit_actions(db_session, "admin_segment", private["id"])
    assert actions == ["admin.segment.create", "admin.segment.update", "admin.segment.delete"]


async def test_segment_validation_rejects_sql_injection_and_unknown_fields(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(db_session)
    attempts = [
        {"match": "all", "conditions": [{"field": "plan; DROP TABLE users", "operator": "eq", "value": "pro"}]},
        {"match": "all", "conditions": [{"field": "plan", "operator": "in); --", "value": ["pro"]}]},
        {"match": "all", "conditions": [{"field": "plan", "operator": "eq", "value": "pro' OR 1=1 --"}]},
        {"match": "all", "conditions": [{"field": "users.password", "operator": "eq", "value": "x"}]},
        {"match": "all", "conditions": [{"field": "plan", "operator": "eq", "value": "pro", "sql": "1=1"}]},
        {"match": "all; DELETE FROM users", "conditions": []},
        {"match": "all", "conditions": [{"field": "plan", "operator": "like", "value": "pro%"}]},
        {"match": "all", "conditions": [{"field": "verified", "operator": "eq", "value": "true"}]},
        {"match": "all", "conditions": [{"field": "tenant", "operator": "eq", "value": "../../etc/passwd"}]},
        {"match": "all", "conditions": [{"field": "country_bucket", "operator": "eq", "value": "1; DROP TABLE users"}]},
        {"match": "all", "conditions": [], "extra": True},
    ]
    for definition in attempts:
        response = await client.post(
            "/admin/segments/preview", json={"definition": definition}, headers=headers
        )
        assert response.status_code == 422, (definition, response.text)

    stored_attempt = await client.post(
        "/admin/segments",
        json={"name": "Bad cohort", "definition": attempts[0]},
        headers=headers,
    )
    assert stored_attempt.status_code == 422

    # A tampered JSONB row is revalidated before compilation and never executed.
    segment = await _create_segment(client, headers, name="Tamper target")
    await db_session.execute(
        text(
            "UPDATE admin_segments SET definition = CAST(:definition AS jsonb) WHERE id = :id"
        ),
        {
            "id": segment["id"],
            "definition": '{"match":"all","conditions":[{"field":"plan; DROP TABLE users","operator":"eq","value":"pro"}]}',
        },
    )
    await db_session.commit()
    preview = await client.get(
        f"/admin/segments/{segment['id']}/preview", headers=headers
    )
    assert preview.status_code == 422
    # The accounts table is still present.
    assert await db_session.scalar(text("SELECT count(*) FROM users")) > 0


async def test_segment_preview_is_aggregate_and_suppresses_small_cohorts(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(db_session)
    action = _token("saved_view_feature")

    # Six pro users with the unique event, plus four team users with the same
    # event so one breakdown bucket is suppressed.
    for _ in range(6):
        user_id, _headers = await _create_user(db_session, role="user", plan="pro")
        await _event(db_session, user_id, action)
    for _ in range(4):
        user_id, _headers = await _create_user(db_session, role="user", plan="team")
        await _event(db_session, user_id, action)

    definition = _segment_definition(
        conditions=[{"field": "feature_used", "operator": "eq", "value": action}]
    )
    preview = await client.post(
        "/admin/segments/preview",
        json={"definition": definition, "group_by": "plan"},
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["count"] == 10
    assert body["suppressed"] is False
    assert body["minimum_cohort"] == 5
    assert body["groups"] == [{"value": "pro", "count": 6}]
    assert body["suppressed_groups"] == 1
    assert "user_id" not in str(body)

    # Only four matching users: never reveal the raw count.
    small_action = _token("small_feature")
    for _ in range(4):
        user_id, _headers = await _create_user(db_session, role="user", plan="pro")
        await _event(db_session, user_id, small_action)
    small = await client.post(
        "/admin/segments/preview",
        json={
            "definition": _segment_definition(
                conditions=[{"field": "feature_used", "operator": "eq", "value": small_action}]
            ),
            "group_by": "plan",
        },
        headers=headers,
    )
    assert small.status_code == 200, small.text
    small_body = small.json()
    assert small_body["count"] is None
    assert small_body["suppressed"] is True
    assert small_body["groups"] == []


async def test_segment_fields_compile_to_allowlisted_aggregates(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(db_session)
    admin_id, _ = await _create_user(db_session, role="admin", plan="pro")
    tenant_id = await _create_tenant(db_session, admin_id)

    action = _token("country_feature")
    for _ in range(5):
        user_id, _headers = await _create_user(
            db_session, role="user", plan="pro", tenant_id=tenant_id
        )
        await _event(db_session, user_id, action, {"country": "IN"})
    for _ in range(3):
        user_id, _headers = await _create_user(db_session, role="user", plan="free")
        await _event(db_session, user_id, action, {"country": "US"})

    async def preview(conditions):
        response = await client.post(
            "/admin/segments/preview",
            json={"definition": {"match": "all", "conditions": conditions}},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        return response.json()

    by_tenant = await preview(
        [{"field": "tenant", "operator": "eq", "value": f"test-tenant-{tenant_id[:8]}"}]
    )
    assert by_tenant["count"] == 5

    by_country = await preview(
        [
            {"field": "country_bucket", "operator": "eq", "value": "IN"},
            {"field": "feature_used", "operator": "eq", "value": action},
        ]
    )
    assert by_country["count"] == 5

    by_month = await preview(
        [
            {
                "field": "signup_month",
                "operator": "gte",
                "value": datetime.now(timezone.utc).strftime("%Y-%m"),
            }
        ]
    )
    assert by_month["count"] >= 5

    # Unknown tenant emits a normal (empty) aggregate, never raw SQL.
    unknown = await preview(
        [{"field": "tenant", "operator": "eq", "value": "no-such-tenant"}]
    )
    assert unknown["count"] is None
    assert unknown["suppressed"] is True
