"""Admin path analysis with a Sankey view (#2076).

Covers admin access, first-party route-sequence reconstruction, upgrade/churn
outcome joins, 7/30/90-day windows, plan/cohort filters, node/edge
reconciliation, five-user suppression, edge thresholds, missing-path labelling,
route sanitization and CSV export. No migration or new persistence table is
introduced; route labels reuse the existing ``usage_analytics`` JSONB column.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PREFIX = "test_path_admin_"
EMAIL_PATTERN = f"{PREFIX}%@example.com"
SECRET_TOKEN = "share-secret-token-2076"
SECRET_DOCUMENT = "resume-secret-document-2076"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _email(label: str = "user") -> str:
    return f"{PREFIX}{label}_{uuid.uuid4().hex[:10]}@example.com"


async def _clean_rows(db: AsyncSession, pattern: str = "test_%") -> None:
    """Remove aggregate-report rows owned by test accounts.

    The report intentionally scans the whole table, so a leftover test account
    from another module would change these totals. Production rows never match
    the ``test_`` prefix.
    """

    await db.execute(
        text("DELETE FROM usage_analytics WHERE user_id IN (SELECT id FROM users WHERE email LIKE :pattern)"),
        {"pattern": pattern},
    )
    await db.execute(
        text("DELETE FROM subscription_history WHERE user_id IN (SELECT id FROM users WHERE email LIKE :pattern)"),
        {"pattern": pattern},
    )
    await db.execute(
        text("DELETE FROM subscriptions WHERE user_id IN (SELECT id FROM users WHERE email LIKE :pattern)"),
        {"pattern": pattern},
    )
    await db.commit()


async def _clean_our_rows(db: AsyncSession) -> None:
    await _clean_rows(db, EMAIL_PATTERN)
    await db.execute(
        text('DELETE FROM session WHERE "userId" IN (SELECT id::text FROM users WHERE email LIKE :pattern)'),
        {"pattern": EMAIL_PATTERN},
    )
    await db.execute(text("DELETE FROM users WHERE email LIKE :pattern"), {"pattern": EMAIL_PATTERN})
    await db.commit()


@pytest.fixture(autouse=True)
async def _clean_path_rows(db_session: AsyncSession):
    await _clean_rows(db_session)
    await _clean_our_rows(db_session)
    yield
    await _clean_our_rows(db_session)


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
    created_at: datetime | None = None,
    email: str | None = None,
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    token = f"test_sess_path_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, created_at, updated_at) "
            "VALUES (:id, :email, 'Path Analysis User', :role, true, :plan, 'active', false, :created, :created)"
        ),
        {
            "id": user_id,
            "email": email or _email(role),
            "role": role,
            "plan": plan,
            "created": created_at or (_now() - timedelta(days=400)),
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
    return user_id, {"Authorization": f"Bearer {token}"}


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    _user_id, headers = await _create_user(db, role="admin", plan="team")
    return headers


async def _seed_outcome(
    db: AsyncSession,
    *,
    user_id: str,
    occurred_at: datetime,
    outcome: str = "upgrade",
    plan: str = "pro",
    previous_plan: str | None = None,
) -> str:
    subscription_id = str(uuid.uuid4())
    status = "active" if outcome == "upgrade" else "cancelled"
    await db.execute(
        text(
            "INSERT INTO subscriptions "
            "(id, user_id, provider, plan_id, status, created_at, updated_at) "
            "VALUES (:id, :user_id, 'dodo', :plan, :status, :created_at, :created_at)"
        ),
        {
            "id": subscription_id,
            "user_id": user_id,
            "plan": plan,
            "status": status,
            "created_at": occurred_at - timedelta(days=1),
        },
    )
    if outcome == "upgrade" and previous_plan:
        event_type = "plan_changed"
    elif outcome == "upgrade":
        event_type = "subscription_created"
    else:
        event_type = "cancelled"
    await db.execute(
        text(
            "INSERT INTO subscription_history "
            "(id, user_id, subscription_id, plan_id, previous_plan_id, status, "
            "previous_status, event_type, reason, source, effective_at) "
            "VALUES (:id, :user_id, :subscription_id, :plan, :previous_plan, :status, "
            ":previous_status, :event_type, :reason, 'billing', :effective_at)"
        ),
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "subscription_id": subscription_id,
            "plan": plan,
            "previous_plan": previous_plan,
            "status": status,
            "previous_status": "active" if event_type == "plan_changed" else None,
            "event_type": event_type,
            "reason": "payment_succeeded" if outcome == "upgrade" else "customer_request",
            "effective_at": occurred_at,
        },
    )
    return subscription_id


async def _seed_pageviews(
    db: AsyncSession,
    *,
    user_id: str,
    occurred_at: datetime,
    routes: list[str] | None,
    include_route_metadata: bool = True,
) -> None:
    if routes is None:
        return
    for index, route in enumerate(routes):
        metadata = {"page": "app"}
        if include_route_metadata:
            metadata["route"] = route
        await db.execute(
            text(
                "INSERT INTO usage_analytics "
                "(id, user_id, action, resource_type, event_metadata, created_at) "
                "VALUES (:id, :user_id, 'page_view', 'page', CAST(:metadata AS JSONB), :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "metadata": json.dumps(metadata),
                "created_at": occurred_at - timedelta(minutes=30 - index * 5),
            },
        )


async def _seed_user_with_path(
    db: AsyncSession,
    *,
    outcome: str,
    occurred_at: datetime,
    routes: list[str] | None,
    plan: str = "pro",
    created_at: datetime | None = None,
    include_route_metadata: bool = True,
) -> tuple[str, dict[str, str]]:
    user_id, headers = await _create_user(db, plan=plan, created_at=created_at)
    await _seed_outcome(db, user_id=user_id, occurred_at=occurred_at, outcome=outcome, plan=plan)
    await _seed_pageviews(
        db,
        user_id=user_id,
        occurred_at=occurred_at,
        routes=routes,
        include_route_metadata=include_route_metadata,
    )
    return user_id, headers


def _source_total(section: dict) -> int:
    return sum(node["count"] for node in section["nodes"] if node["kind"] in {"route", "missing"})


def _outcome_total(section: dict) -> int:
    return sum(node["count"] for node in section["nodes"] if node["kind"] == "outcome")


def _edge_total(section: dict) -> int:
    return sum(edge["count"] for edge in section["edges"])


async def _seed_standard_paths(db: AsyncSession, now: datetime) -> None:
    # Six upgrades share path A; six share path B. Path A carries raw query
    # strings and opaque ids that must be canonicalized before they appear.
    for index in range(6):
        await _seed_user_with_path(
            db,
            outcome="upgrade",
            occurred_at=now - timedelta(days=2, minutes=index),
            routes=[
                "/dashboard",
                f"/workspace/{SECRET_DOCUMENT}-{index}?token={SECRET_TOKEN}#frag",
                "/billing",
            ],
        )
    for index in range(6):
        await _seed_user_with_path(
            db,
            outcome="upgrade",
            occurred_at=now - timedelta(days=3, minutes=index),
            routes=["/templates", "/pricing"],
        )
    for index in range(6):
        await _seed_user_with_path(
            db,
            outcome="churn",
            occurred_at=now - timedelta(days=2, minutes=index),
            routes=["/dashboard", "/settings", "/billing"],
        )
    await db.commit()


class TestAdminPathAnalysisAccess:
    async def test_admin_only_and_filter_validation(self, client: AsyncClient, db_session: AsyncSession):
        _user_id, user_headers = await _create_user(db_session, role="user")
        denied = await client.get("/admin/analytics/paths", headers=user_headers)
        assert denied.status_code == 403

        _support_id, support_headers = await _create_user(db_session, role="support")
        support_denied = await client.get("/admin/analytics/paths", headers=support_headers)
        assert support_denied.status_code == 403

        anonymous = await client.get("/admin/analytics/paths")
        assert anonymous.status_code == 401

        admin = await _admin_headers(db_session)
        allowed = await client.get("/admin/analytics/paths", headers=admin)
        assert allowed.status_code == 200, allowed.text
        payload = allowed.json()
        assert payload["suppressed"] is False
        assert payload["summary"]["outcomes"] == 0
        assert payload["upgrade"]["status"] == "empty"
        assert payload["churn"]["status"] == "empty"
        assert payload["minimum_cohort_size"] == 5
        assert payload["data_quality"]["missing_path_imputed"] is False

        bad_plan = await client.get("/admin/analytics/paths", params={"plan": "not-a-plan"}, headers=admin)
        assert bad_plan.status_code == 422
        bad_cohort = await client.get("/admin/analytics/paths", params={"cohort": "vip"}, headers=admin)
        assert bad_cohort.status_code == 422
        bad_threshold = await client.get("/admin/analytics/paths", params={"min_edge_count": 0}, headers=admin)
        assert bad_threshold.status_code == 422
        bad_range = await client.get(
            "/admin/analytics/paths",
            params={"start_date": "2026-03-01", "end_date": "2026-02-01"},
            headers=admin,
        )
        assert bad_range.status_code == 422


class TestAdminPathAnalysisAggregation:
    async def test_reconciliation_top_paths_and_sanitization(self, client: AsyncClient, db_session: AsyncSession):
        now = _now()
        await _seed_standard_paths(db_session, now)
        admin = await _admin_headers(db_session)

        response = await client.get("/admin/analytics/paths", params={"days": 30}, headers=admin)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["suppressed"] is False
        assert body["summary"]["upgrade_outcomes"] == 12
        assert body["summary"]["churn_outcomes"] == 6
        assert body["summary"]["outcomes"] == 18
        assert body["summary"]["paths_with_route_data"] == 18
        assert body["summary"]["paths_without_route_data"] == 0

        upgrade = body["upgrade"]
        assert upgrade["status"] == "visible"
        assert upgrade["total_outcomes"] == 12
        assert upgrade["missing_path_outcomes"] == 0
        assert upgrade["route_coverage_pct"] == 100.0
        assert upgrade["reconciliation"]["reconciled"] is True
        assert _edge_total(upgrade) == _source_total(upgrade)
        assert all(node["count"] == node["outgoing"] for node in upgrade["nodes"] if node["kind"] != "outcome")
        assert all(node["count"] == node["incoming"] for node in upgrade["nodes"] if node["kind"] == "outcome")
        assert _outcome_total(upgrade) == 12

        paths = {path["label"]: path for path in upgrade["top_paths"]}
        workspace_path = "/dashboard → /workspace/:resumeId → /billing → Upgrade"
        pricing_path = "/templates → /pricing → Upgrade"
        assert paths[workspace_path]["count"] == 6
        assert paths[workspace_path]["users"] == 6
        assert paths[pricing_path]["count"] == 6
        assert len(upgrade["top_paths"]) == 2

        # Raw query strings, opaque document ids and share tokens never leave.
        serialized = json.dumps(body)
        assert SECRET_TOKEN not in serialized
        assert SECRET_DOCUMENT not in serialized
        assert "?token=" not in serialized
        assert "user_id" not in upgrade
        assert '"device_fingerprint":' not in serialized
        assert '"user_agent":' not in serialized

        churn = body["churn"]
        assert churn["status"] == "visible"
        assert churn["reconciliation"]["reconciled"] is True
        assert _edge_total(churn) == _source_total(churn)
        assert churn["top_paths"][0]["label"] == "/dashboard → /settings → /billing → Churn"
        assert churn["top_paths"][0]["count"] == 6

        # Explicit CSV export uses the same aggregate rows and no raw identifiers.
        csv_response = await client.get(
            "/admin/analytics/paths",
            params={"days": 30, "format": "csv"},
            headers=admin,
        )
        assert csv_response.status_code == 200, csv_response.text
        assert csv_response.headers["content-type"].startswith("text/csv")
        assert "attachment" in csv_response.headers["content-disposition"]
        rows = list(csv.DictReader(io.StringIO(csv_response.text)))
        assert rows and rows[0].keys() == {
            "section",
            "outcome",
            "source",
            "target",
            "label",
            "count",
            "users",
            "suppressed",
            "note",
        }
        sections = {row["section"] for row in rows}
        assert {"summary", "path", "edge", "node", "suppression", "reconciliation"} <= sections
        assert SECRET_TOKEN not in csv_response.text
        assert SECRET_DOCUMENT not in csv_response.text
        assert "user_id" not in csv_response.text

        alias = await client.get(
            "/admin/analytics/paths/export.csv",
            params={"days": 90},
            headers=admin,
        )
        assert alias.status_code == 200
        assert alias.headers["content-type"].startswith("text/csv")

    async def test_windows_plan_and_cohort_filters(self, client: AsyncClient, db_session: AsyncSession):
        now = _now()
        old_account = now - timedelta(days=120)
        new_account = now - timedelta(days=5)
        for index in range(6):
            await _seed_user_with_path(
                db_session,
                outcome="upgrade",
                occurred_at=now - timedelta(days=2, minutes=index),
                routes=["/dashboard", "/billing"],
                plan="pro",
                created_at=new_account,
            )
        for index in range(6):
            await _seed_user_with_path(
                db_session,
                outcome="upgrade",
                occurred_at=now - timedelta(days=60, minutes=index),
                routes=["/dashboard", "/billing"],
                plan="pro",
                created_at=old_account,
            )
        for index in range(6):
            await _seed_user_with_path(
                db_session,
                outcome="upgrade",
                occurred_at=now - timedelta(days=2, minutes=index),
                routes=["/templates", "/pricing"],
                plan="basic",
                created_at=old_account,
            )
        await db_session.commit()
        admin = await _admin_headers(db_session)

        thirty = await client.get("/admin/analytics/paths", params={"days": 30, "plan": "pro"}, headers=admin)
        assert thirty.status_code == 200, thirty.text
        assert thirty.json()["upgrade"]["total_outcomes"] == 6

        seven = await client.get("/admin/analytics/paths", params={"days": 7, "plan": "pro"}, headers=admin)
        assert seven.status_code == 200, seven.text
        assert seven.json()["upgrade"]["total_outcomes"] == 6

        ninety = await client.get("/admin/analytics/paths", params={"days": 90, "plan": "pro"}, headers=admin)
        assert ninety.status_code == 200, ninety.text
        assert ninety.json()["upgrade"]["total_outcomes"] == 12

        new_cohort = await client.get(
            "/admin/analytics/paths",
            params={"days": 90, "plan": "pro", "cohort": "new"},
            headers=admin,
        )
        assert new_cohort.status_code == 200, new_cohort.text
        assert new_cohort.json()["upgrade"]["total_outcomes"] == 6
        assert new_cohort.json()["filters"]["cohort"] == "new"

        established = await client.get(
            "/admin/analytics/paths",
            params={"days": 90, "plan": "pro", "cohort": "established"},
            headers=admin,
        )
        assert established.status_code == 200, established.text
        assert established.json()["upgrade"]["total_outcomes"] == 6

        basic = await client.get("/admin/analytics/paths", params={"days": 30, "plan": "basic"}, headers=admin)
        assert basic.status_code == 200, basic.text
        assert basic.json()["suppressed"] is False
        assert basic.json()["upgrade"]["total_outcomes"] == 6
        assert basic.json()["churn"]["total_outcomes"] == 0


class TestAdminPathAnalysisSuppressionAndMissingData:
    async def test_missing_path_data_is_labelled_not_invented(self, client: AsyncClient, db_session: AsyncSession):
        now = _now()
        for index in range(6):
            await _seed_user_with_path(
                db_session,
                outcome="upgrade",
                occurred_at=now - timedelta(days=1, minutes=index),
                routes=None,
            )
        # Legacy page_view rows without a route label are still missing data.
        for index in range(6):
            await _seed_user_with_path(
                db_session,
                outcome="churn",
                occurred_at=now - timedelta(days=2, minutes=index),
                routes=["/dashboard", "/settings"],
                include_route_metadata=False,
            )
        await db_session.commit()
        admin = await _admin_headers(db_session)

        response = await client.get("/admin/analytics/paths", params={"days": 30}, headers=admin)
        assert response.status_code == 200, response.text
        body = response.json()
        upgrade = body["upgrade"]
        churn = body["churn"]
        assert upgrade["missing_path_outcomes"] == 6
        assert upgrade["route_path_outcomes"] == 0
        assert upgrade["route_coverage_pct"] == 0.0
        assert upgrade["top_paths"][0]["missing"] is True
        assert upgrade["top_paths"][0]["label"] == "Path data missing → Upgrade"
        assert upgrade["top_paths"][0]["count"] == 6
        assert any(node["kind"] == "missing" for node in upgrade["nodes"])
        assert upgrade["reconciliation"]["reconciled"] is True

        assert churn["missing_path_outcomes"] == 6
        assert churn["route_coverage_pct"] == 0.0
        assert any(node["kind"] == "missing" for node in churn["nodes"])
        assert body["summary"]["paths_without_route_data"] == 12
        assert body["data_quality"]["missing_path_label"] == "Path data missing"
        assert body["data_quality"]["missing_path_imputed"] is False

    async def test_low_volume_edges_paths_and_threshold(self, client: AsyncClient, db_session: AsyncSession):
        now = _now()
        for index in range(5):
            await _seed_user_with_path(
                db_session,
                outcome="upgrade",
                occurred_at=now - timedelta(days=1, minutes=index),
                routes=["/dashboard", "/billing"],
            )
        await _seed_user_with_path(
            db_session,
            outcome="upgrade",
            occurred_at=now - timedelta(hours=2),
            routes=["/templates", "/pricing"],
        )
        for index in range(6):
            await _seed_user_with_path(
                db_session,
                outcome="churn",
                occurred_at=now - timedelta(days=2, minutes=index),
                routes=["/settings", "/billing"],
            )
        await db_session.commit()
        admin = await _admin_headers(db_session)

        response = await client.get("/admin/analytics/paths", params={"days": 30}, headers=admin)
        assert response.status_code == 200, response.text
        body = response.json()
        upgrade = body["upgrade"]
        assert upgrade["status"] == "visible"
        assert upgrade["suppressed_edges"] >= 2
        assert upgrade["suppressed_paths"] == 1
        serialized = json.dumps(upgrade)
        assert "/templates" not in serialized
        assert "/pricing" not in serialized
        assert len(upgrade["top_paths"]) == 1
        assert upgrade["top_paths"][0]["count"] == 5
        assert upgrade["reconciliation"]["reconciled"] is True

        thresholded = await client.get(
            "/admin/analytics/paths",
            params={"days": 30, "min_edge_count": 6},
            headers=admin,
        )
        assert thresholded.status_code == 200, thresholded.text
        upgrade_thresholded = thresholded.json()["upgrade"]
        assert upgrade_thresholded["edges"] == []
        assert upgrade_thresholded["top_paths"] == []
        assert upgrade_thresholded["thresholded_edges"] >= 2
        assert upgrade_thresholded["reconciliation"]["reconciled"] is True

    async def test_global_suppression_below_five_users(self, client: AsyncClient, db_session: AsyncSession):
        now = _now()
        for index in range(4):
            await _seed_user_with_path(
                db_session,
                outcome="upgrade",
                occurred_at=now - timedelta(days=1, minutes=index),
                routes=["/dashboard", "/billing"],
            )
        await db_session.commit()
        admin = await _admin_headers(db_session)

        response = await client.get("/admin/analytics/paths", params={"days": 30}, headers=admin)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["suppressed"] is True
        assert body["suppression"]["applied"] is True
        assert body["summary"]["outcomes"] is None
        assert body["summary"]["upgrade_outcomes"] is None
        assert body["upgrade"]["status"] == "suppressed"
        assert body["churn"]["status"] == "suppressed"
        assert body["upgrade"]["nodes"] == []

        csv_response = await client.get(
            "/admin/analytics/paths",
            params={"days": 30, "format": "csv"},
            headers=admin,
        )
        assert csv_response.status_code == 200
        assert "suppression" in csv_response.text


class TestPathRouteSanitization:
    async def test_ingestion_canonicalizes_route(self, client: AsyncClient, db_session: AsyncSession):
        user_id, headers = await _create_user(db_session, plan="pro")
        response = await client.post(
            "/analytics/track/page-view",
            params={
                "page": "app",
                "route": f"/workspace/{SECRET_DOCUMENT}?token={SECRET_TOKEN}#frag",
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        row = (
            await db_session.execute(
                text("SELECT event_metadata FROM usage_analytics WHERE user_id = :user_id AND action = 'page_view'"),
                {"user_id": user_id},
            )
        ).scalar_one()
        assert row["route"] == "/workspace/:resumeId"
        assert SECRET_TOKEN not in json.dumps(row)
        assert SECRET_DOCUMENT not in json.dumps(row)

        share = await client.post(
            "/analytics/track/page-view",
            params={"page": "app", "route": f"/r/{SECRET_TOKEN}"},
            headers=headers,
        )
        assert share.status_code == 201
        unknown = await client.post(
            "/analytics/track/page-view",
            params={"page": "app", "route": "/internal/secret-user-value"},
            headers=headers,
        )
        assert unknown.status_code == 201

        rows = (
            (
                await db_session.execute(
                    text(
                        "SELECT event_metadata FROM usage_analytics WHERE user_id = :user_id AND action = 'page_view'"
                    ),
                    {"user_id": user_id},
                )
            )
            .scalars()
            .all()
        )
        assert {row["route"] for row in rows} == {
            "/workspace/:resumeId",
            "/r/:token",
            "/other",
        }
        assert all(SECRET_TOKEN not in json.dumps(row) and SECRET_DOCUMENT not in json.dumps(row) for row in rows)
