"""User 360 subscription/payment timeline: chronology, pagination and privilege."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import admin_user_service


async def _create_user(db: AsyncSession, *, role: str = "user", email: str | None = None) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = email or f"test_tl_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Timeline User', :role, true, 'pro', 'active', false)"
        ),
        {"id": user_id, "email": email, "role": role},
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_tl_{uuid.uuid4().hex}"
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


async def _headers(db: AsyncSession, role: str) -> dict[str, str]:
    user_id, _ = await _create_user(db, role=role)
    return await _session_headers(db, user_id)


async def _seed_timeline(db: AsyncSession, *, user_id: str, email: str) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    subscription_id = str(uuid.uuid4())
    payment_id = str(uuid.uuid4())
    refund_id = str(uuid.uuid4())
    provider_payment_id = f"pay_tl_{uuid.uuid4().hex[:16]}"
    provider_subscription_id = f"sub_tl_{uuid.uuid4().hex[:16]}"
    provider_refund_id = f"ref_tl_{uuid.uuid4().hex[:16]}"
    plan_audit_id = str(uuid.uuid4())
    entitlement_audit_id = str(uuid.uuid4())

    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "plan_id, status, current_period_start, current_period_end, quoted_amount, created_at) "
            "VALUES (:id, :uid, 'dodo', :provider_sub, 'pro', 'active', :start, :end, 59900, :created)"
        ),
        {
            "id": subscription_id,
            "uid": user_id,
            "provider_sub": provider_subscription_id,
            "start": now - timedelta(days=20),
            "end": now + timedelta(days=10),
            "created": now - timedelta(days=20),
        },
    )
    await db.execute(
        text(
            "INSERT INTO payments (id, user_id, subscription_id, provider, provider_payment_id, "
            "amount, currency, status, created_at) "
            "VALUES (:id, :uid, :sub, 'dodo', :provider_payment, 59900, 'INR', 'paid', :created)"
        ),
        {
            "id": payment_id,
            "uid": user_id,
            "sub": subscription_id,
            "provider_payment": provider_payment_id,
            "created": now - timedelta(days=18),
        },
    )
    await db.execute(
        text(
            "INSERT INTO payment_refunds (id, payment_id, provider, provider_refund_id, "
            "amount, currency, status, reason, created_at) "
            "VALUES (:id, :payment, 'dodo', :provider_refund, 1000, 'INR', 'succeeded', 'goodwill', :created)"
        ),
        {
            "id": refund_id,
            "payment": payment_id,
            "provider_refund": provider_refund_id,
            "created": now - timedelta(days=5),
        },
    )
    for event_type, status, previous_status, effective_at, plan_id, previous_plan_id in (
        ("subscription_created", "active", None, now - timedelta(days=19), "pro", None),
        ("plan_changed", "active", "active", now - timedelta(days=10), "pro", "basic"),
    ):
        await db.execute(
            text(
                "INSERT INTO subscription_history (id, user_id, subscription_id, plan_id, previous_plan_id, "
                "status, previous_status, event_type, reason, source, effective_at) "
                "VALUES (:id, :uid, :sub, :plan, :prev_plan, :status, :prev_status, :event, "
                "'payment_succeeded', 'billing', :effective)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "sub": subscription_id,
                "plan": plan_id,
                "prev_plan": previous_plan_id,
                "status": status,
                "prev_status": previous_status,
                "event": event_type,
                "effective": effective_at,
            },
        )
    await db.execute(
        text(
            "INSERT INTO billing_webhook_events (id, provider, event_id, event_type, event_resource_id, "
            "payload_sha256, status, attempts, last_error, event_at, received_at, processed_at) "
            "VALUES (:id, 'dodo', :event_id, 'payment.succeeded', :resource, :digest, 'processed', 1, "
            ":last_error, :event_at, :received_at, :received_at)"
        ),
        {
            "id": str(uuid.uuid4()),
            "event_id": f"evt_tl_{uuid.uuid4().hex[:16]}",
            "resource": provider_payment_id,
            "digest": "a" * 64,
            "last_error": "secret_webhook_token_should_never_render",
            "event_at": now - timedelta(days=17),
            "received_at": now - timedelta(days=17),
        },
    )
    await db.execute(
        text(
            "INSERT INTO admin_audit_log (id, actor_user_id, actor_email, action, target_type, target_id, "
            "reason, before, after, event_metadata, created_at) "
            "VALUES (:id, :actor, :actor_email, 'user.plan.change', 'user', :target, :reason, "
            "CAST(:before AS jsonb), CAST(:after AS jsonb), '{}'::jsonb, :created)"
        ),
        {
            "id": plan_audit_id,
            "actor": str(uuid.uuid4()),
            "actor_email": "admin@example.com",
            "target": user_id,
            "reason": "Ticket 2102 plan review",
            "before": json.dumps({"subscription_plan": "basic", "subscription_status": "active"}),
            "after": json.dumps({"subscription_plan": "pro", "subscription_status": "active"}),
            "created": now - timedelta(days=3),
        },
    )
    await db.execute(
        text(
            "INSERT INTO admin_audit_log (id, actor_user_id, actor_email, action, target_type, target_id, "
            "reason, before, after, event_metadata, created_at) "
            "VALUES (:id, :actor, :actor_email, 'user.feature.grant', 'user', :target, :reason, "
            "CAST(:before AS jsonb), CAST(:after AS jsonb), CAST(:metadata AS jsonb), :created)"
        ),
        {
            "id": entitlement_audit_id,
            "actor": str(uuid.uuid4()),
            "actor_email": "admin@example.com",
            "target": user_id,
            "reason": "Ticket 2102 entitlement review",
            "before": json.dumps({"override": None}),
            "after": json.dumps({"override": True}),
            "metadata": json.dumps({"feature_key": "pro_export", "token": "secret_audit_token_should_not_render"}),
            "created": now - timedelta(days=1),
        },
    )
    await db.commit()
    return {
        "subscription_id": subscription_id,
        "payment_id": payment_id,
        "refund_id": refund_id,
        "provider_payment_id": provider_payment_id,
        "provider_subscription_id": provider_subscription_id,
        "provider_refund_id": provider_refund_id,
    }


class TestUser360Timeline:
    async def test_admin_timeline_is_chronological_paginated_and_reconciled(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        user_id, email = await _create_user(db_session)
        seeded = await _seed_timeline(db_session, user_id=user_id, email=email)

        # An unrelated account must never bleed into this ledger.
        other_id, _ = await _create_user(db_session)
        await _seed_timeline(db_session, user_id=other_id, email=f"test_tl_other_{other_id}@example.com")

        first = await client.get(
            f"/admin/users/{user_id}/360?timeline_limit=3&timeline_offset=0",
            headers=admin_headers,
        )
        assert first.status_code == 200, first.text
        body = first.json()
        timeline = body["billing"]["timeline"]
        assert body["timeline"] == timeline

        assert timeline["order"] == "desc"
        assert timeline["total"] == 8
        assert timeline["limit"] == 3
        assert timeline["offset"] == 0
        assert timeline["has_more"] is True
        assert timeline["next_offset"] == 3
        assert [row["kind"] for row in timeline["items"]] == [
            "entitlement_change",
            "plan_change",
            "refund",
        ]
        timestamps = [row["occurred_at"] for row in timeline["items"]]
        assert timestamps == sorted(timestamps, reverse=True)
        assert all(row["admin_only"] is True for row in timeline["items"][:2])
        assert timeline["restricted_kinds"] == []

        assert timeline["sources"] == {
            "subscription_history": 2,
            "subscriptions": 1,
            "payments": 1,
            "refunds": 1,
            "webhooks": 1,
            "plan_changes": 1,
            "entitlement_changes": 1,
        }
        assert sum(timeline["counts"].values()) == timeline["total"]

        totals = timeline["totals"]
        assert totals["payments"]["count"] == 1
        assert totals["payments"]["total_minor"] == 59900
        assert totals["payments"]["paid_minor"] == 59900
        assert totals["refunds"]["count"] == 1
        assert totals["refunds"]["total_minor"] == 1000
        assert totals["refunds"]["succeeded_minor"] == 1000
        assert totals["gross_minor"] == 59900
        assert totals["refunded_minor"] == 1000
        assert totals["net_minor"] == 58900
        assert totals["settled_net_minor"] == 58900

        second = await client.get(
            f"/admin/users/{user_id}/360?timeline_limit=3&timeline_offset=3",
            headers=admin_headers,
        )
        assert second.status_code == 200
        second_timeline = second.json()["timeline"]
        assert second_timeline["offset"] == 3
        assert second_timeline["has_more"] is True
        assert second_timeline["next_offset"] == 6
        assert second_timeline["total"] == 8

        third = await client.get(
            f"/admin/users/{user_id}/360?timeline_limit=3&timeline_offset=6",
            headers=admin_headers,
        )
        assert third.status_code == 200
        third_timeline = third.json()["timeline"]
        assert third_timeline["has_more"] is False
        assert third_timeline["next_offset"] is None
        assert len(third_timeline["items"]) == 2

        all_items = [
            row
            for page in (first, second, third)
            for row in page.json()["timeline"]["items"]
        ]
        ids = [row["id"] for row in all_items]
        assert len(ids) == 8
        assert len(set(ids)) == 8
        payment_item = next(row for row in all_items if row["kind"] == "payment")
        assert payment_item["reference"] == seeded["provider_payment_id"]
        webhook_item = next(row for row in all_items if row["kind"] == "webhook")
        assert webhook_item["event_type"] == "payment.succeeded"
        assert "last_error" not in webhook_item

        # The webhook error and audit free text are never part of the timeline.
        dumped = json.dumps(timeline)
        assert "secret_webhook_token_should_never_render" not in dumped
        assert "secret_audit_token_should_not_render" not in dumped
        assert "Ticket 2102" not in dumped
        assert email not in dumped

    async def test_support_sees_only_billing_ledger_and_masked_identity(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        support_headers = await _headers(db_session, "support")
        user_id, email = await _create_user(db_session)
        await _seed_timeline(db_session, user_id=user_id, email=email)

        response = await client.get(f"/admin/users/{user_id}/360", headers=support_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        timeline = body["timeline"]

        assert timeline["viewer_role"] == "support"
        assert timeline["total"] == 5
        assert set(row["kind"] for row in timeline["items"]) == {
            "subscription_history",
            "subscription",
            "payment",
            "refund",
        }
        assert set(timeline["restricted_kinds"]) == {"webhook", "plan_change", "entitlement_change"}
        assert timeline["sources"]["webhooks"] == 0
        assert timeline["sources"]["plan_changes"] == 0
        assert timeline["sources"]["entitlement_changes"] == 0
        assert body["recent_admin_actions"] == []
        assert body["user"]["pii_masked"] is True
        assert body["user"]["email"] != email
        assert email not in response.text
        assert "admin@example.com" not in response.text
        assert "secret_webhook_token_should_never_render" not in response.text
        assert "secret_audit_token_should_not_render" not in response.text

        support_reveal = await client.post(
            f"/admin/users/{user_id}/reveal-pii",
            json={"field": "email", "reason": "Support should not reveal timeline PII"},
            headers=support_headers,
        )
        assert support_reveal.status_code == 403

        user_headers = await _headers(db_session, "user")
        forbidden = await client.get(f"/admin/users/{user_id}/360", headers=user_headers)
        assert forbidden.status_code == 403

    async def test_timeline_is_masked_and_reveal_requires_reason_and_audit(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        user_id, email = await _create_user(db_session)
        await _seed_timeline(db_session, user_id=user_id, email=email)

        missing_reason = await client.post(
            f"/admin/users/{user_id}/reveal-pii",
            json={"field": "email", "reason": "x"},
            headers=admin_headers,
        )
        assert missing_reason.status_code == 422

        reveal = await client.post(
            f"/admin/users/{user_id}/reveal-pii",
            json={"field": "email", "reason": "Ticket 2102 verify billing contact"},
            headers=admin_headers,
        )
        assert reveal.status_code == 200
        assert reveal.json()["value"] == email

        masked_view = await client.get(f"/admin/users/{user_id}/360", headers=admin_headers)
        assert masked_view.status_code == 200
        assert masked_view.json()["user"]["pii_masked"] is True
        assert masked_view.json()["user"]["email"] != email
        assert email not in masked_view.text

        audit = await client.get(
            f"/admin/audit?action=user.pii.reveal&target_id={user_id}",
            headers=admin_headers,
        )
        assert audit.status_code == 200
        assert audit.json()["total"] == 1
        assert audit.json()["items"][0]["reason"] == "Ticket 2102 verify billing contact"
        assert email not in audit.text

    async def test_timeline_page_validation_and_cache_keeps_pii_masked(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        class FakeCache:
            def __init__(self):
                self.values: dict[str, object] = {}
                self.ttls: dict[str, int] = {}

            async def get(self, key: str):
                return self.values.get(key)

            async def set(self, key: str, value, ttl: int = 3600):
                self.values[key] = value
                self.ttls[key] = ttl

            async def delete(self, key: str):
                self.values.pop(key, None)

        fake = FakeCache()
        monkeypatch.setattr(admin_user_service, "cache_manager", fake)
        admin_headers = await _headers(db_session, "admin")
        user_id, email = await _create_user(db_session)

        bad_limit = await client.get(
            f"/admin/users/{user_id}/360?timeline_limit=101",
            headers=admin_headers,
        )
        assert bad_limit.status_code == 422
        bad_offset = await client.get(
            f"/admin/users/{user_id}/360?timeline_offset=-1",
            headers=admin_headers,
        )
        assert bad_offset.status_code == 422

        first = await client.get(
            f"/admin/users/{user_id}/360?timeline_limit=2&timeline_offset=0",
            headers=admin_headers,
        )
        assert first.status_code == 200
        assert first.json()["timeline"]["total"] == 0
        assert fake.values
        cached = next(iter(fake.values.values()))
        assert cached["user"]["pii_masked"] is True
        assert "timeline" not in cached
        assert email not in json.dumps(cached)

        # Billing rows arriving after the 360 snapshot are still visible because
        # the timeline is composed live rather than stored in the base cache.
        await _seed_timeline(db_session, user_id=user_id, email=email)
        refreshed = await client.get(
            f"/admin/users/{user_id}/360?timeline_limit=2&timeline_offset=0",
            headers=admin_headers,
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["timeline"]["total"] == 8
        assert fake.values
