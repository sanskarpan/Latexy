"""Aggregate error grouping, threshold alerts, feed links, RBAC and privacy (#2166)."""

from __future__ import annotations

import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database import models
from app.services import error_tracking_service as service
from app.services.admin_audit_service import AdminActor

SENSITIVE = "sk-live-secret-do-not-store"


def _release() -> str:
    return f"rel-{uuid.uuid4().hex[:12]}"


async def _clear_groups(db: AsyncSession) -> None:
    await db.execute(text("DELETE FROM admin_error_groups"))
    await db.commit()


async def _seed(
    db: AsyncSession,
    *,
    count: int,
    route: str = "/dashboard",
    release: str,
    error_class: str = "TypeError",
    source: str = "frontend",
    occurred_at: datetime | None = None,
) -> None:
    for _ in range(count):
        await service.record_error_group(
            db,
            source=source,
            route=route,
            release=release,
            error_class=error_class,
            occurred_at=occurred_at,
        )
    await db.commit()


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    token = f"test_sess_error_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Error Feed User', :role, true, 'free', 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"test_error_{user_id.replace('-', '')}@example.com",
            "role": role,
        },
    )
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
    return user_id, {"Authorization": f"Bearer {token}"}


def _actor() -> AdminActor:
    return AdminActor(user_id=str(uuid.uuid4()), email="oncall@example.com", role="admin")


async def _configure_alerts(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ERROR_ALERT_THRESHOLD", 3)
    monkeypatch.setattr(settings, "ERROR_ALERT_WINDOW_MINUTES", 15)
    monkeypatch.setattr(settings, "ERROR_ALERT_COOLDOWN_MINUTES", 60)
    monkeypatch.setattr(
        settings,
        "ALERT_SLACK_WEBHOOK_URL",
        "https://hooks.slack.com/services/T000/B000/XYZ",
    )
    monkeypatch.setattr(settings, "ALERT_EMAIL_TO", "oncall@example.com,secondary@example.com")


def test_grouping_route_sanitizers_are_bounded_and_block_documents() -> None:
    assert service.normalize_error_route("/dashboard", source="frontend") == "/dashboard"
    assert service.normalize_error_route("/dashboard?token=abc", source="frontend") == "/dashboard"
    assert service.normalize_error_route("/checkout", source="frontend") == "/other"
    assert service.normalize_error_route("/workspace/abc", source="frontend") is None
    assert service.normalize_error_route("/resumes/123", source="backend") is None
    assert service.normalize_error_route("/api/resumes/abc", source="backend") is None
    assert service.normalize_error_route("/share/abc", source="frontend") is None
    assert service.normalize_error_route("/r/abc", source="frontend") is None

    assert service.normalize_error_route("/billing/1234", source="backend") == "/billing/:id"
    uuid_path = "/admin/alerts/3f0c3a5e-1f0a-4d1b-9a53-5d2a9b1c7e11"
    assert service.normalize_error_route(uuid_path, source="backend") == "/admin/alerts/:id"
    assert service.sanitize_error_class("TypeError") == "TypeError"
    assert service.sanitize_error_class("ValueError: user@example.com") == "UnknownError"
    assert service.sanitize_error_class(f"OOM:{SENSITIVE}") == "UnknownError"
    assert service.sanitize_release("v1.2.3") == "v1.2.3"
    assert service.sanitize_release(f"bad token {SENSITIVE}") == "unknown"
    assert service.sanitize_release("sk-live-secret-token") == "unknown"
    assert service.normalize_error_route("/billing/user@example.com", source="backend") == "/billing/:id"


async def test_feed_groups_by_route_release_and_class(db_session: AsyncSession) -> None:
    await _clear_groups(db_session)
    release_a, release_b = _release(), _release()
    await _seed(db_session, count=6, route="/dashboard", release=release_a, error_class="TypeError")
    await _seed(db_session, count=5, route="/dashboard", release=release_a, error_class="RangeError")
    await _seed(
        db_session,
        count=5,
        route="/billing",
        release=release_b,
        error_class="TypeError",
        source="backend",
    )

    feed = await service.error_feed(db_session, days=7, limit=10)

    groups = {(g["source"], g["route"], g["release"], g["error_class"]): g for g in feed["groups"]}
    assert groups[("frontend", "/dashboard", release_a, "TypeError")]["occurrence_count"] == 6
    assert groups[("frontend", "/dashboard", release_a, "RangeError")]["occurrence_count"] == 5
    assert groups[("backend", "/billing", release_b, "TypeError")]["occurrence_count"] == 5
    assert feed["totals"]["events"] == 16
    assert feed["totals"]["visible_groups"] == 3
    assert feed["suppression"]["minimum_cohort_size"] == 5
    assert feed["suppression"]["user_dimension_included"] is False
    assert feed["runbook_url"] == service.RUNBOOK_URL
    assert set(feed["delivery"]) == {"configured", "channels"}


async def test_feed_suppresses_small_cohorts(db_session: AsyncSession) -> None:
    await _clear_groups(db_session)
    release = _release()
    await _seed(db_session, count=4, route="/dashboard", release=release)

    feed = await service.error_feed(db_session, days=7)

    assert feed["groups"] == []
    assert feed["totals"]["events"] == 4
    assert feed["totals"]["suppressed_groups"] == 1
    assert feed["totals"]["suppressed_events"] == 4


async def test_threshold_dry_run_delivery_and_cooldown(db_session: AsyncSession, monkeypatch) -> None:
    await _clear_groups(db_session)
    await _configure_alerts(monkeypatch)
    release = _release()
    now = datetime.now(timezone.utc)
    await _seed(db_session, count=3, release=release, occurred_at=now)

    slack_calls: list[tuple[str, dict]] = []
    email_calls: list[tuple[str, str, str, str]] = []

    async def slack_sender(url, payload):
        slack_calls.append((url, dict(payload)))

    async def email_sender(to, subject, body, plain):
        email_calls.append((to, subject, body, plain))
        return True

    preview = await service.evaluate_error_alerts(
        db_session,
        actor=_actor(),
        reason="preview threshold state",
        now=now,
        dry_run=True,
        slack_sender=slack_sender,
        email_sender=email_sender,
    )
    assert preview["candidate_count"] == 1
    assert preview["selected_count"] == 1
    assert preview["alerts"][0]["route"] == "/dashboard"
    assert preview["delivery"]["attempted"] is False
    assert slack_calls == [] and email_calls == []

    first = await service.evaluate_error_alerts(
        db_session,
        actor=_actor(),
        reason="dispatch threshold alert",
        now=now,
        slack_sender=slack_sender,
        email_sender=email_sender,
    )
    assert first["alerted"] == 1
    assert first["delivery"]["delivered"] is True
    assert {channel["channel"] for channel in first["delivery"]["channels"]} == {"slack", "email"}
    assert len(slack_calls) == 1 and len(email_calls) == 2
    assert service.RUNBOOK_URL in slack_calls[0][1]["text"]
    assert all(service.RUNBOOK_URL in call[2] for call in email_calls)
    assert all(service.RUNBOOK_URL in call[3] for call in email_calls)

    row = (
        await db_session.execute(
            text("SELECT last_alerted_at, alert_count FROM admin_error_groups WHERE release = :release"),
            {"release": release},
        )
    ).one()
    assert row.alert_count == 1
    assert row.last_alerted_at is not None

    second = await service.evaluate_error_alerts(
        db_session,
        actor=_actor(),
        reason="repeat within cooldown",
        now=now,
        slack_sender=slack_sender,
        email_sender=email_sender,
    )
    assert second["selected_count"] == 0
    assert second["alerted"] == 0
    assert second["skipped_cooldown"] == 1
    assert len(slack_calls) == 1

    await db_session.execute(
        text("UPDATE admin_error_groups SET last_alerted_at = :last WHERE release = :release"),
        {"last": now - timedelta(minutes=61), "release": release},
    )
    await db_session.commit()
    third = await service.evaluate_error_alerts(
        db_session,
        actor=_actor(),
        reason="cooldown elapsed",
        now=now,
        slack_sender=slack_sender,
        email_sender=email_sender,
    )
    assert third["alerted"] == 1
    assert len(slack_calls) == 2


async def test_alert_payload_is_allowlisted_and_redacted(db_session: AsyncSession, monkeypatch) -> None:
    await _clear_groups(db_session)
    await _configure_alerts(monkeypatch)
    release = _release()
    await _seed(db_session, count=3, release=release, error_class="TypeError")

    row = await db_session.scalar(select(models.AdminErrorGroup).where(models.AdminErrorGroup.release == release))
    assert row is not None
    payload = service.build_error_alert_payload(row, now=datetime.now(timezone.utc))

    assert set(payload) == {
        "kind",
        "source",
        "route",
        "release",
        "error_class",
        "window_events",
        "total_events",
        "threshold",
        "window_minutes",
        "first_seen_at",
        "last_seen_at",
        "environment",
        "runbook_url",
    }
    rendered = str(service.render_slack_message([payload])) + str(service.render_error_alert_email([payload]))
    for forbidden in (SENSITIVE, "@example.com", "private document", "secret prompt"):
        assert forbidden not in rendered
    assert payload["runbook_url"] in rendered


async def test_frontend_ingest_accepts_only_metadata_and_drops_documents(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _clear_groups(db_session)
    release = _release()
    ok = await client.post(
        "/telemetry/errors",
        json={"error_class": "TypeError", "route": "/dashboard", "release": release},
    )
    assert ok.status_code == 202
    assert ok.json() == {"accepted": True}

    # No message, stack, email or token field is accepted.
    rejected = await client.post(
        "/telemetry/errors",
        json={
            "error_class": "TypeError",
            "route": "/dashboard",
            "release": release,
            "message": "private document text",
            "email": "user@example.com",
        },
    )
    assert rejected.status_code == 422

    blocked = await client.post(
        "/telemetry/errors",
        json={"error_class": "TypeError", "route": "/workspace/secret", "release": release},
    )
    assert blocked.status_code == 202
    assert blocked.json() == {"accepted": False, "reason": "surface_excluded"}

    rows = (
        await db_session.execute(
            text(
                "SELECT route, release, error_class, occurrence_count FROM admin_error_groups WHERE release = :release"
            ),
            {"release": release},
        )
    ).all()
    assert rows == [("/dashboard", release, "TypeError", 1)]


async def test_frontend_ingest_rate_limit(client: AsyncClient, db_session: AsyncSession, monkeypatch) -> None:
    from app.api import error_telemetry_routes

    async def deny(_key: str) -> bool:
        return False

    monkeypatch.setattr(error_telemetry_routes, "_rate_limit_ok", deny)
    response = await client.post(
        "/telemetry/errors",
        json={"error_class": "TypeError", "route": "/dashboard", "release": _release()},
    )
    assert response.status_code == 429


async def test_backend_exception_capture_uses_class_and_template(
    db_session: AsyncSession,
) -> None:
    await _clear_groups(db_session)

    class BoomTimeout(Exception):
        pass

    recorded = await service.record_backend_exception(
        db_session, route="/billing", exc=BoomTimeout("secret prompt content")
    )
    await db_session.commit()
    assert recorded is not None

    blocked = await service.record_backend_exception(db_session, route="/api/resumes/{resume_id}", exc=BoomTimeout())
    assert blocked is None

    feed = await service.error_feed(db_session, days=7)
    rows = (await db_session.execute(text("SELECT source, route, error_class FROM admin_error_groups"))).all()
    assert rows == [("backend", "/billing", "BoomTimeout")]


async def test_admin_feed_rbac_and_evaluate_audit(client: AsyncClient, db_session: AsyncSession) -> None:
    await _clear_groups(db_session)
    release = _release()
    await _seed(db_session, count=6, release=release)

    _, admin_headers = await _create_user(db_session, role="admin")
    _, user_headers = await _create_user(db_session, role="user")
    _, support_headers = await _create_user(db_session, role="support")

    ok = await client.get("/admin/analytics/errors", headers=admin_headers)
    assert ok.status_code == 200
    assert ok.json()["groups"][0]["route"] == "/dashboard"

    for headers in (user_headers, support_headers):
        denied = await client.get("/admin/analytics/errors", headers=headers)
        assert denied.status_code == 403

    unconfirmed = await client.post(
        "/admin/analytics/errors/evaluate",
        headers=admin_headers,
        json={"reason": "dispatch alerts", "confirm": False},
    )
    assert unconfirmed.status_code == 422

    preview = await client.post(
        "/admin/analytics/errors/evaluate",
        headers=admin_headers,
        json={"reason": "preview alerts", "confirm": False, "dry_run": True},
    )
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True

    reason = f"audited evaluation {uuid.uuid4().hex[:8]}"
    evaluated = await client.post(
        "/admin/analytics/errors/evaluate",
        headers=admin_headers,
        json={"reason": reason, "confirm": True},
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["delivery_configured"] is False
    assert evaluated.json()["alerted"] == 0

    audit_count = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM admin_audit_log WHERE action = 'admin.error_alerts.evaluate' AND reason = :reason"
            ),
            {"reason": reason},
        )
    ).scalar_one()
    assert audit_count == 1

    denied = await client.post(
        "/admin/analytics/errors/evaluate",
        headers=user_headers,
        json={"reason": "not allowed", "confirm": True},
    )
    assert denied.status_code == 403


async def test_error_table_has_no_content_columns() -> None:
    table = models.AdminErrorGroup.__table__
    assert set(table.columns.keys()) == {
        "id",
        "source",
        "route",
        "release",
        "error_class",
        "occurrence_count",
        "window_events",
        "window_started_at",
        "first_seen_at",
        "last_seen_at",
        "last_alerted_at",
        "alert_count",
        "created_at",
        "updated_at",
    }


def test_error_alerts_migration_shape() -> None:
    path = Path(__file__).parents[1] / "alembic/versions/0109_error_alerts.py"
    spec = importlib.util.spec_from_file_location("test_0109_error_alerts", path)
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

    assert migration.revision == "0109_error_alerts"
    assert migration.down_revision == "0100_daily_metrics"
    migration.op = FakeOp()
    migration.upgrade()

    table_call = next(call for call in calls if call[0] == "create_table")
    assert table_call[1] == "admin_error_groups"
    columns = {column.name: column for column in table_call[2] if column.__class__.__name__ == "Column"}
    assert set(columns) == {
        "id",
        "source",
        "route",
        "release",
        "error_class",
        "occurrence_count",
        "window_events",
        "window_started_at",
        "first_seen_at",
        "last_seen_at",
        "last_alerted_at",
        "alert_count",
        "created_at",
        "updated_at",
    }
