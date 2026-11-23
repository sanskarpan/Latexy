"""Durable admin alerts: evaluation, filtering, ack and snooze."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.services import admin_alert_service
from app.services.redis_capacity_service import RedisCapacitySnapshot, redis_capacity_service


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"alert_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Alert User', :role, true, 'free', 'active', false)"
        ),
        {"id": user_id, "email": email, "role": role},
    )
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"alert_sess_{uuid.uuid4().hex}"
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
    return {"Authorization": f"Bearer {token}"}


async def _headers(db: AsyncSession, role: str = "admin") -> dict[str, str]:
    user_id, _ = await _create_user(db, role=role)
    return await _session_headers(db, user_id)


async def _clear_conditions(
    db: AsyncSession, *, now: datetime | None = None
) -> None:
    now = now or datetime.now(timezone.utc)
    await db.execute(
        text("UPDATE billing_webhook_events SET acknowledged_at = now() WHERE status = 'failed'")
    )
    await db.execute(text("UPDATE payments SET status = 'paid' WHERE status = 'failed'"))
    await db.execute(
        text("UPDATE subscriptions SET status = 'active' WHERE status IN ('past_due', 'on_hold')")
    )
    cutoff = now - timedelta(minutes=15)
    await db.execute(
        text(
            "UPDATE compilations SET status = 'completed' "
            "WHERE status IN ('queued', 'pending', 'processing', 'running') AND created_at < :cutoff"
        ),
        {"cutoff": cutoff},
    )
    await db.execute(
        text(
            "UPDATE job_finalizations SET state = 'completed' "
            "WHERE state IN ('pending', 'committing') AND created_at < :cutoff"
        ),
        {"cutoff": cutoff},
    )
    await db.execute(
        text(
            "UPDATE tenants SET domain_verified_at = now() "
            "WHERE custom_domain IS NOT NULL AND domain_verified_at IS NULL"
        )
    )


async def _clear_signals(
    db: AsyncSession, *, now: datetime | None = None
) -> None:
    await db.execute(text("DELETE FROM admin_alerts"))
    await _clear_conditions(db, now=now)


async def _seed_failures(
    db: AsyncSession, *, now: datetime | None = None
) -> None:
    now = now or datetime.now(timezone.utc)
    user_id, _ = await _create_user(db)
    await db.execute(
        text(
            "INSERT INTO billing_webhook_events "
            "(id, provider, event_id, event_type, payload_sha256, status, attempts, received_at) "
            "VALUES (:id, 'dodo', :event_id, 'payment.failed', :sha, 'failed', 1, :received)"
        ),
        {
            "id": str(uuid.uuid4()),
            "event_id": f"evt_{uuid.uuid4().hex}",
            "sha": "b" * 64,
            "received": now - timedelta(minutes=10),
        },
    )
    await db.execute(
        text(
            "INSERT INTO payments (id, user_id, provider, provider_payment_id, "
            "amount, currency, status, created_at) "
            "VALUES (:id, :uid, 'dodo', :provider_payment, 59900, 'INR', 'failed', :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "provider_payment": f"pay_{uuid.uuid4().hex[:12]}",
            "created": now - timedelta(minutes=10),
        },
    )
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "plan_id, status, current_period_start, current_period_end) "
            "VALUES (:id, :uid, 'dodo', :provider_sub, 'pro', 'past_due', :start, :end)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "provider_sub": f"sub_{uuid.uuid4().hex[:12]}",
            "start": now - timedelta(days=2),
            "end": now + timedelta(days=28),
        },
    )
    await db.execute(
        text(
            "INSERT INTO compilations (id, job_id, status, created_at) "
            "VALUES (:id, :job_id, 'processing', :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "job_id": f"job_{uuid.uuid4().hex}",
            "created": now - timedelta(minutes=40),
        },
    )
    await db.execute(
        text(
            "INSERT INTO tenants (id, slug, custom_domain, name, owner_id) "
            "VALUES (:id, :slug, :domain, 'Alert Tenant', :owner)"
        ),
        {
            "id": str(uuid.uuid4()),
            "slug": f"alert-{uuid.uuid4().hex[:10]}",
            "domain": f"{uuid.uuid4().hex[:10]}.example.com",
            "owner": user_id,
        },
    )


async def test_alert_evaluation_deduplicates_and_resolves(db_session: AsyncSession):
    await _clear_signals(db_session)
    await _seed_failures(db_session)

    now = datetime.now(timezone.utc)
    first = await admin_alert_service.evaluate_alerts(db_session, now=now)
    assert first["opened"] >= 4

    rows = (
        await db_session.execute(
            text(
                "SELECT dedupe_key, state, occurrence_count FROM admin_alerts "
                "WHERE dedupe_key IN ('billing.webhook_failures', 'billing.failed_payments', "
                "'billing.past_due', 'jobs.stuck', 'domains.unverified')"
            )
        )
    ).all()
    assert {row.dedupe_key for row in rows} == {
        "billing.webhook_failures",
        "billing.failed_payments",
        "billing.past_due",
        "jobs.stuck",
        "domains.unverified",
    }
    assert all(row.state == "open" for row in rows)

    second = await admin_alert_service.evaluate_alerts(db_session, now=now + timedelta(minutes=1))
    assert second["updated"] >= 4
    rows = (
        await db_session.execute(
            text(
                "SELECT dedupe_key, occurrence_count FROM admin_alerts "
                "WHERE dedupe_key IN ('billing.webhook_failures', 'billing.failed_payments', "
                "'billing.past_due', 'jobs.stuck', 'domains.unverified')"
            )
        )
    ).all()
    assert all(row.occurrence_count == 2 for row in rows)

    await _clear_conditions(db_session)
    resolved = await admin_alert_service.evaluate_alerts(db_session, now=now + timedelta(minutes=2))
    assert resolved["resolved"] >= 4
    states = (
        await db_session.execute(
            text(
                "SELECT dedupe_key, state FROM admin_alerts "
                "WHERE dedupe_key IN ('billing.webhook_failures', 'billing.failed_payments', "
                "'billing.past_due', 'jobs.stuck', 'domains.unverified')"
            )
        )
    ).all()
    assert all(row.state == "resolved" for row in states)


async def test_alert_actions_are_admin_only_and_audited(
    client: AsyncClient, db_session: AsyncSession
):
    await db_session.execute(text("DELETE FROM admin_alerts WHERE dedupe_key LIKE 'test.alert.%'"))
    now = datetime.now(timezone.utc)
    alert = models.AdminAlert(
        kind="test.alert",
        severity="high",
        owner="Platform",
        title="Test alert",
        dedupe_key=f"test.alert.{uuid.uuid4().hex}",
        payload={"count": 1},
        state="open",
        occurrence_count=1,
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(alert)
    await db_session.commit()
    alert_id = alert.id

    unauthenticated = await client.patch(
        f"/admin/alerts/{alert_id}",
        json={"state": "acknowledged", "reason": "reviewed"},
    )
    assert unauthenticated.status_code == 401

    support_headers = await _headers(db_session, "support")
    forbidden = await client.patch(
        f"/admin/alerts/{alert_id}",
        json={"state": "acknowledged", "reason": "reviewed"},
        headers=support_headers,
    )
    assert forbidden.status_code == 403

    admin_headers = await _headers(db_session, "admin")
    acknowledged = await client.patch(
        f"/admin/alerts/{alert_id}",
        json={"state": "acknowledged", "reason": "reviewed provider state"},
        headers=admin_headers,
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["state"] == "acknowledged"

    audit = await client.get(
        f"/admin/audit?action=admin.alert.acknowledge&target_id={alert_id}",
        headers=admin_headers,
    )
    assert audit.status_code == 200
    assert audit.json()["total"] >= 1

    snoozed = await client.patch(
        f"/admin/alerts/{alert_id}",
        json={"state": "snoozed", "reason": "waiting for provider", "snooze_minutes": 60},
        headers=admin_headers,
    )
    assert snoozed.status_code == 200
    body = snoozed.json()
    assert body["state"] == "snoozed"
    assert body["snooze_until"] is not None

    listed = await client.get("/admin/alerts?state=active", headers=admin_headers)
    assert listed.status_code == 200
    assert any(item["id"] == alert_id for item in listed.json()["items"])

    await db_session.execute(text("DELETE FROM admin_alerts WHERE id = :id"), {"id": alert_id})
    await db_session.commit()


FIXED_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


async def _admin_alert_count(db: AsyncSession) -> int:
    return int((await db.execute(text("SELECT count(*) FROM admin_alerts"))).scalar() or 0)


async def _insert_test_alert(
    db: AsyncSession,
    *,
    owner: str,
    kind: str,
    dedupe_key: str,
    severity: str = "high",
) -> models.AdminAlert:
    alert = models.AdminAlert(
        kind=kind,
        severity=severity,
        owner=owner,
        title=f"Test alert {kind}",
        dedupe_key=dedupe_key,
        payload={"count": 1},
        state="open",
        occurrence_count=1,
        first_seen_at=FIXED_NOW,
        last_seen_at=FIXED_NOW,
    )
    db.add(alert)
    await db.flush()
    return alert


async def test_alert_list_filters_by_owner_and_kind(
    client: AsyncClient, db_session: AsyncSession
):
    await db_session.execute(text("DELETE FROM admin_alerts WHERE kind LIKE 'test.alert.filter.%'"))
    suffix = uuid.uuid4().hex[:8]
    billing_key = f"test.alert.filter.billing.{suffix}"
    growth_key = f"test.alert.filter.growth.{suffix}"
    platform_key = f"test.alert.filter.platform.{suffix}"
    billing = await _insert_test_alert(
        db_session, owner="Billing", kind=billing_key, dedupe_key=billing_key
    )
    growth = await _insert_test_alert(
        db_session, owner="Growth", kind=growth_key, dedupe_key=growth_key
    )
    platform = await _insert_test_alert(
        db_session, owner="Platform", kind=platform_key, dedupe_key=platform_key
    )
    await db_session.commit()

    admin_headers = await _headers(db_session, "admin")
    try:
        combined = await client.get(
            "/admin/alerts",
            params={"owner": "Billing", "kind": billing_key},
            headers=admin_headers,
        )
        assert combined.status_code == 200
        body = combined.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == billing.id
        assert body["items"][0]["owner"] == "Billing"
        assert body["items"][0]["kind"] == billing_key

        by_owner = await client.get(
            "/admin/alerts", params={"owner": "Growth"}, headers=admin_headers
        )
        assert by_owner.status_code == 200
        owner_ids = {item["id"] for item in by_owner.json()["items"]}
        assert growth.id in owner_ids
        assert billing.id not in owner_ids
        assert platform.id not in owner_ids
        assert all(item["owner"] == "Growth" for item in by_owner.json()["items"])

        by_kind = await client.get(
            "/admin/alerts", params={"kind": platform_key}, headers=admin_headers
        )
        assert by_kind.status_code == 200
        assert by_kind.json()["total"] == 1
        assert by_kind.json()["items"][0]["id"] == platform.id

        mismatched = await client.get(
            "/admin/alerts",
            params={"owner": "Billing", "kind": growth_key},
            headers=admin_headers,
        )
        assert mismatched.status_code == 200
        assert mismatched.json()["total"] == 0

        too_long_owner = await client.get(
            "/admin/alerts", params={"owner": "x" * 33}, headers=admin_headers
        )
        assert too_long_owner.status_code == 422
        too_long_kind = await client.get(
            "/admin/alerts", params={"kind": "x" * 65}, headers=admin_headers
        )
        assert too_long_kind.status_code == 422
    finally:
        await db_session.execute(
            text("DELETE FROM admin_alerts WHERE kind LIKE 'test.alert.filter.%'")
        )
        await db_session.commit()


async def test_rule_failure_does_not_stop_other_signals(
    monkeypatch, db_session: AsyncSession
):
    await _clear_signals(db_session, now=FIXED_NOW)
    await _seed_failures(db_session, now=FIXED_NOW)

    original_failure_signal = admin_alert_service._failure_signal

    async def failing_failure_signal(db, *, kind, **kwargs):
        if kind == "billing.webhook_failures":
            # Force a real database error inside this rule's savepoint.
            await db.execute(text("SELECT 1 FROM admin_alert_rule_failure_probe"))
        return await original_failure_signal(db, kind=kind, **kwargs)

    monkeypatch.setattr(
        admin_alert_service, "_failure_signal", failing_failure_signal
    )

    signals = await admin_alert_service.collect_signals(db_session, FIXED_NOW)
    keys = {signal["dedupe_key"] for signal in signals}
    assert "billing.webhook_failures" not in keys
    assert {
        "billing.failed_payments",
        "billing.past_due",
        "jobs.stuck",
        "domains.unverified",
    } <= keys

    # The failed savepoint rolled back instead of poisoning the transaction.
    assert (await db_session.execute(text("SELECT 1"))).scalar() == 1

    result = await admin_alert_service.evaluate_alerts(db_session, now=FIXED_NOW)
    assert result["opened"] >= 4
    opened_keys = set(
        (
            await db_session.execute(
                text("SELECT dedupe_key FROM admin_alerts WHERE state = 'open'")
            )
        ).scalars().all()
    )
    assert "billing.failed_payments" in opened_keys
    assert "billing.webhook_failures" not in opened_keys


async def test_redis_capacity_signal_is_durable_and_typed(monkeypatch, db_session: AsyncSession):
    for status, severity in (
        ("warning", "warning"),
        ("critical", "critical"),
        ("exhausted", "critical"),
        ("unavailable", "critical"),
        ("misconfigured", "critical"),
    ):
        async def snapshot_for(value=status):
            return RedisCapacitySnapshot(
                provider="upstash",
                status=value,
                configured=True,
                monthly_requests=950,
                request_limit=1000,
                utilization_ratio=0.95,
            )

        monkeypatch.setattr(redis_capacity_service, "snapshot", snapshot_for)
        signals = await admin_alert_service.collect_signals(db_session, FIXED_NOW)
        capacity = next((row for row in signals if row["dedupe_key"] == "capacity.redis"), None)
        assert capacity is not None
        assert capacity["severity"] == severity
        assert capacity["owner"] == "Platform"
        assert capacity["payload"]["status"] == status
        assert capacity["payload"]["utilization_ratio"] == 0.95


async def test_healthy_redis_capacity_does_not_alert(monkeypatch, db_session: AsyncSession):
    async def fake_snapshot():
        return RedisCapacitySnapshot(
            provider="upstash",
            status="ok",
            configured=True,
            monthly_requests=10,
            request_limit=1000,
            utilization_ratio=0.01,
        )

    monkeypatch.setattr(redis_capacity_service, "snapshot", fake_snapshot)
    signals = await admin_alert_service.collect_signals(db_session, FIXED_NOW)
    assert all(row["dedupe_key"] != "capacity.redis" for row in signals)


async def test_dry_run_previews_without_mutating(db_session: AsyncSession):
    await _clear_signals(db_session, now=FIXED_NOW)
    await _seed_failures(db_session, now=FIXED_NOW)
    assert await _admin_alert_count(db_session) == 0

    preview = await admin_alert_service.evaluate_alerts(
        db_session, now=FIXED_NOW, dry_run=True
    )
    assert preview["dry_run"] is True
    assert {
        "billing.webhook_failures",
        "billing.failed_payments",
        "billing.past_due",
        "jobs.stuck",
        "domains.unverified",
    } <= {signal["dedupe_key"] for signal in preview["signals"]}
    assert preview["would_open"] >= 4
    assert preview["would_update"] == 0
    assert preview["would_resolve"] == 0
    assert await _admin_alert_count(db_session) == 0

    applied = await admin_alert_service.evaluate_alerts(db_session, now=FIXED_NOW)
    assert applied["opened"] >= 4
    assert await _admin_alert_count(db_session) >= 4

    stale_key = f"test.alert.stale.{uuid.uuid4().hex}"
    stale = await _insert_test_alert(
        db_session, owner="Platform", kind=stale_key, dedupe_key=stale_key
    )
    await db_session.commit()

    before = {
        row.dedupe_key: (row.state, row.occurrence_count)
        for row in (
            await db_session.execute(text("SELECT dedupe_key, state, occurrence_count FROM admin_alerts"))
        ).all()
    }
    update_preview = await admin_alert_service.evaluate_alerts(
        db_session, now=FIXED_NOW + timedelta(minutes=1), dry_run=True
    )
    assert update_preview["would_update"] >= 4
    assert update_preview["would_resolve"] >= 1
    after = {
        row.dedupe_key: (row.state, row.occurrence_count)
        for row in (
            await db_session.execute(text("SELECT dedupe_key, state, occurrence_count FROM admin_alerts"))
        ).all()
    }
    assert after == before
    assert after[stale_key] == ("open", 1)
    assert after["billing.webhook_failures"] == ("open", 1)

    followed = await admin_alert_service.evaluate_alerts(
        db_session, now=FIXED_NOW + timedelta(minutes=1)
    )
    assert followed["updated"] >= 4
    assert followed["resolved"] >= 1
    stale_state = (
        await db_session.execute(
            text("SELECT state, resolution FROM admin_alerts WHERE id = :id"),
            {"id": stale.id},
        )
    ).one()
    assert stale_state.state == "resolved"
    assert stale_state.resolution == "auto_clear"


async def test_alert_dry_run_route_is_admin_only(
    client: AsyncClient, db_session: AsyncSession
):
    await _clear_signals(db_session, now=FIXED_NOW)
    await _seed_failures(db_session, now=FIXED_NOW)
    before = await _admin_alert_count(db_session)

    unauthenticated = await client.post("/admin/alerts/dry-run")
    assert unauthenticated.status_code == 401

    support_headers = await _headers(db_session, "support")
    forbidden = await client.post("/admin/alerts/dry-run", headers=support_headers)
    assert forbidden.status_code == 403

    admin_headers = await _headers(db_session, "admin")
    preview = await client.post("/admin/alerts/dry-run", headers=admin_headers)
    assert preview.status_code == 200
    body = preview.json()
    assert body["dry_run"] is True
    assert body["would_open"] >= 4
    assert "billing.webhook_failures" in {
        signal["dedupe_key"] for signal in body["signals"]
    }
    assert await _admin_alert_count(db_session) == before

    # Only the preview route exists: there is no live evaluation trigger.
    live = await client.post("/admin/alerts/evaluate", headers=admin_headers)
    assert live.status_code in (404, 405)


async def test_evaluation_isolates_bad_signal(monkeypatch, db_session: AsyncSession):
    await _clear_signals(db_session, now=FIXED_NOW)
    good_key = f"test.alert.good.{uuid.uuid4().hex}"
    bad_key = f"test.alert.bad.{uuid.uuid4().hex}"
    base = {
        "kind": "test.alert.signal",
        "severity": "medium",
        "owner": "Platform",
        "title": "Test signal",
        "payload": {"count": 1},
        "runbook_url": None,
    }
    good = {**base, "dedupe_key": good_key}
    # Invalid severity trips the check constraint during this signal's flush.
    bad = {**base, "dedupe_key": bad_key, "severity": "bogus"}

    async def fake_collect_signals(_db, _now):
        return [good, bad]

    monkeypatch.setattr(
        admin_alert_service, "collect_signals", fake_collect_signals
    )

    result = await admin_alert_service.evaluate_alerts(db_session, now=FIXED_NOW)
    assert result == {"opened": 1, "updated": 0, "resolved": 0}
    keys = (
        await db_session.execute(
            text(
                "SELECT dedupe_key FROM admin_alerts "
                "WHERE dedupe_key IN (:good, :bad)"
            ),
            {"good": good_key, "bad": bad_key},
        )
    ).scalars().all()
    assert keys == [good_key]
