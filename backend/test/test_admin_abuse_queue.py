"""Admin abuse-signal review queue (#2131).

Covers signal aggregation and weekly dedupe, queue transitions, RBAC, audit
evidence, self-approval refusal, device enforcement, whitelist behaviour and
the DB-level delete/identity guard. All fixtures use the dedicated test DB.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.services import trial_service

REASON = "Reviewed abuse signal 2131"
PREFIX = "abuse_test_"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _headers_for(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_user(
    db: AsyncSession, *, role: str = "admin", email_tag: str | None = None
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    tag = email_tag or user_id.replace("-", "")
    token = f"abuse_sess_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Abuse Queue User', :role, true, 'free', 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"{PREFIX}{tag}@example.com",
            "role": role,
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
            "exp": _now() + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return user_id, _headers_for(token)


async def _seed_device(
    db: AsyncSession,
    *,
    tag: str,
    usage_count: int = 1,
    blocked: bool = False,
    whitelisted: bool = False,
    ip_address: str = "203.0.113.10",
    created_at: datetime | None = None,
    last_used: datetime | None = None,
) -> str:
    fingerprint = f"{PREFIX}device_{tag}_{uuid.uuid4().hex}"
    created = created_at or _now() - timedelta(hours=1)
    used = last_used or created
    await db.execute(
        text(
            "INSERT INTO device_trials "
            "(id, device_fingerprint, ip_address, usage_count, blocked, whitelisted, "
            "last_used, created_at) "
            "VALUES (:id, :fp, CAST(:ip AS inet), :usage, :blocked, :whitelisted, "
            ":last_used, :created_at)"
        ),
        {
            "id": str(uuid.uuid4()),
            "fp": fingerprint,
            "ip": ip_address,
            "usage": usage_count,
            "blocked": blocked,
            "whitelisted": whitelisted,
            "last_used": used,
            "created_at": created,
        },
    )
    await db.commit()
    return fingerprint


async def _seed_payment_failures(db: AsyncSession, user_id: str) -> None:
    for index in range(3):
        await db.execute(
            text(
                "INSERT INTO payments "
                "(id, user_id, provider, provider_payment_id, amount, currency, status, created_at) "
                "VALUES (:id, :uid, 'dodo', :provider_id, 4999, 'INR', 'failed', :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "provider_id": f"{PREFIX}pay_{uuid.uuid4().hex}_{index}",
                "created_at": _now() - timedelta(hours=index + 1),
            },
        )
    await db.commit()


async def _seed_referral_rejections(db: AsyncSession) -> None:
    referrer_id, _ = await _create_user(db, role="user", email_tag=f"referrer_{uuid.uuid4().hex}")
    identity_id = str(uuid.uuid4())
    code = f"ABUSETEST{uuid.uuid4().hex[:12].upper()}"
    await db.execute(
        text(
            "INSERT INTO referral_identities (id, user_id, code, code_digest, created_at) "
            "VALUES (:id, :uid, :code, :digest, :created_at)"
        ),
        {
            "id": identity_id,
            "uid": referrer_id,
            "code": code,
            "digest": hashlib.sha256(code.encode()).hexdigest(),
            "created_at": _now() - timedelta(days=1),
        },
    )
    for _index in range(5):
        referred_id, _ = await _create_user(
            db, role="user", email_tag=f"referred_{uuid.uuid4().hex}"
        )
        await db.execute(
            text(
                "INSERT INTO referral_attributions "
                "(id, referral_identity_id, referrer_user_id, referred_user_id, status, "
                "rejection_reason, captured_at) "
                "VALUES (:id, :identity, :referrer, :referred, 'captured', "
                "'self_referral', :captured_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "identity": identity_id,
                "referrer": referrer_id,
                "referred": referred_id,
                "captured_at": _now() - timedelta(hours=2),
            },
        )
    await db.commit()


async def _seed_coupon_releases(db: AsyncSession, user_id: str) -> None:
    for index in range(3):
        await db.execute(
            text(
                "INSERT INTO coupon_redemptions "
                "(id, coupon_id, user_id, status, redeemed_at) "
                "VALUES (:id, NULL, :uid, 'released', :at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "at": _now() - timedelta(hours=index + 1),
            },
        )
    await db.commit()


async def _seed_usage_pressure(db: AsyncSession) -> None:
    await db.execute(
        text(
            "INSERT INTO usage_analytics (id, action, ip_address, created_at) "
            "SELECT gen_random_uuid(), 'abuse_test_velocity', "
            "CAST('198.51.100.77' AS inet), now() - interval '30 minutes' "
            "FROM generate_series(1, 50)"
        )
    )
    await db.commit()


async def _cleanup(db: AsyncSession) -> None:
    # Queue rows are append-only by trigger; TRUNCATE is the test-only reset.
    await db.execute(text("TRUNCATE TABLE abuse_review_items"))
    await db.execute(
        text("DELETE FROM device_trials WHERE device_fingerprint LIKE :prefix"),
        {"prefix": f"{PREFIX}%"},
    )
    await db.execute(
        text("DELETE FROM usage_analytics WHERE action = 'abuse_test_velocity'")
    )
    await db.execute(
        text(
            "DELETE FROM coupon_redemptions WHERE user_id IN "
            "(SELECT id FROM users WHERE email LIKE :prefix)"
        ),
        {"prefix": f"{PREFIX}%"},
    )
    await db.execute(
        text(
            "DELETE FROM referral_attributions WHERE referrer_user_id IN "
            "(SELECT id FROM users WHERE email LIKE :prefix) OR referred_user_id IN "
            "(SELECT id FROM users WHERE email LIKE :prefix)"
        ),
        {"prefix": f"{PREFIX}%"},
    )
    await db.execute(
        text(
            "DELETE FROM referral_identities WHERE user_id IN "
            "(SELECT id FROM users WHERE email LIKE :prefix)"
        ),
        {"prefix": f"{PREFIX}%"},
    )
    await db.execute(
        text(
            "DELETE FROM payments WHERE user_id IN "
            "(SELECT id FROM users WHERE email LIKE :prefix)"
        ),
        {"prefix": f"{PREFIX}%"},
    )
    await db.commit()


@pytest.fixture(autouse=True)
async def _reset_abuse_rows(db_session: AsyncSession):
    await _cleanup(db_session)
    yield
    await _cleanup(db_session)


async def _scan(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    window_days: int = 30,
    confirm: bool = True,
) -> dict:
    response = await client.post(
        "/admin/abuse/queue/scan",
        json={"window_days": window_days, "reason": REASON, "confirm": confirm},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _find(items: list[dict], signal_type: str) -> dict:
    for item in items:
        if item["signal_type"] == signal_type:
            return item
    raise AssertionError(f"No {signal_type} item in {[item['signal_type'] for item in items]}")


async def _all_items(
    client: AsyncClient, headers: dict[str, str], **params
) -> list[dict]:
    query = {"status": "all", "limit": 200, **params}
    response = await client.get("/admin/abuse/queue", params=query, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


class TestAbuseQueueRbac:
    async def test_admin_only_surface(self, client: AsyncClient, db_session: AsyncSession):
        assert (await client.get("/admin/abuse/queue")).status_code == 401
        for role in ("user", "support"):
            _uid, headers = await _create_user(db_session, role=role)
            assert (
                await client.get("/admin/abuse/queue", headers=headers)
            ).status_code == 403
            assert (
                await client.post(
                    "/admin/abuse/queue/scan",
                    json={"window_days": 30, "reason": REASON, "confirm": True},
                    headers=headers,
                )
            ).status_code == 403

        _admin_id, admin = await _create_user(db_session, role="admin")
        assert (await client.get("/admin/abuse/queue", headers=admin)).status_code == 200


class TestSignalAggregation:
    async def test_aggregates_and_dedupes_all_signal_families(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, admin = await _create_user(db_session, role="admin")
        payment_user, _ = await _create_user(
            db_session, role="user", email_tag=f"payment_{uuid.uuid4().hex}"
        )
        coupon_user, _ = await _create_user(
            db_session, role="user", email_tag=f"coupon_{uuid.uuid4().hex}"
        )

        fingerprints = [
            await _seed_device(db_session, tag=f"cluster_{index}")
            for index in range(5)
        ]
        blocked_fp = await _seed_device(
            db_session,
            tag="blocked",
            usage_count=3,
            blocked=True,
            ip_address="203.0.113.20",
        )
        limit_fp = await _seed_device(
            db_session,
            tag="limit",
            usage_count=3,
            blocked=False,
            ip_address="203.0.113.21",
        )
        await _seed_payment_failures(db_session, payment_user)
        await _seed_referral_rejections(db_session)
        await _seed_coupon_releases(db_session, coupon_user)
        await _seed_usage_pressure(db_session)

        result = await _scan(client, admin)
        assert result["created"] > 0
        assert result["updated"] == 0
        assert result["window_days"] == 30

        items = await _all_items(client, admin)
        by_type = {item["signal_type"] for item in items}
        assert {
            "blocked_device",
            "trial_limit_reached",
            "repeat_ip_cluster",
            "trial_velocity",
            "payment_failure",
            "referral_rejection",
            "coupon_reuse",
            "rate_limit_pressure",
        } <= by_type

        cluster = _find(items, "repeat_ip_cluster")
        assert cluster["evidence"]["devices"] == 5
        assert cluster["evidence"]["cluster_threshold"] == 5
        assert cluster["subject_type"] == "ip"
        assert len(cluster["subject_key"]) == 32
        assert cluster["subject_ref"] == cluster["subject_key"][:12]
        assert cluster["evidence_links"]

        payment = _find(items, "payment_failure")
        assert payment["evidence"]["failed_payments"] == 3
        assert payment["subject_type"] == "account"

        referral = _find(items, "referral_rejection")
        assert referral["evidence"]["reason"] == "self_referral"
        assert referral["evidence"]["rejections"] == 5
        assert referral["subject_type"] == "reason"

        coupon = _find(items, "coupon_reuse")
        assert coupon["evidence"]["released_reservations"] == 3

        pressure = _find(items, "rate_limit_pressure")
        assert pressure["evidence"]["usage_events"] == 50

        # The response never echoes raw identifiers or customer contact data.
        serialized = str(result).lower() + str(items).lower()
        for raw in fingerprints + [blocked_fp, limit_fp]:
            assert raw.lower() not in serialized
        assert "203.0.113." not in serialized
        assert "198.51.100." not in serialized
        assert "@example.com" not in serialized
        assert payment_user not in serialized
        assert coupon_user not in serialized

        # Re-running inside the same ISO week updates evidence and never
        # duplicates a signal for the same subject.
        total_before = len(items)
        second = await _scan(client, admin)
        assert second["created"] == 0
        assert second["updated"] == len(items)
        items_after = await _all_items(client, admin)
        assert len(items_after) == total_before
        assert len({item["dedupe_key"] if "dedupe_key" in item else item["id"] for item in items_after}) == total_before

        audits = (
            await db_session.execute(
                text(
                    "SELECT action, event_metadata FROM admin_audit_log "
                    "WHERE action = 'admin.abuse.scan' ORDER BY created_at DESC LIMIT 5"
                )
            )
        ).all()
        assert len(audits) >= 2
        audit_text = str(audits).lower()
        for raw in fingerprints + [blocked_fp, limit_fp]:
            assert raw.lower() not in audit_text
        assert "203.0.113." not in audit_text

    async def test_payment_failure_subjects_stay_isolated(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, admin = await _create_user(db_session, role="admin")
        first_user, _ = await _create_user(
            db_session, role="user", email_tag=f"payer_a_{uuid.uuid4().hex}"
        )
        second_user, _ = await _create_user(
            db_session, role="user", email_tag=f"payer_b_{uuid.uuid4().hex}"
        )
        await _seed_payment_failures(db_session, first_user)
        await _seed_payment_failures(db_session, second_user)
        await _scan(client, admin)

        items = [
            item
            for item in await _all_items(client, admin, signal_type="payment_failure")
            if item["status"] == "open"
        ]
        assert len(items) == 2
        assert len({item["subject_key"] for item in items}) == 2
        assert {item["evidence"]["failed_payments"] for item in items} == {3}
        serialized = str(items).lower()
        assert first_user not in serialized
        assert second_user not in serialized
        assert "@example.com" not in serialized

    async def test_scan_requires_confirm_and_reason(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, admin = await _create_user(db_session, role="admin")
        missing_confirm = await client.post(
            "/admin/abuse/queue/scan",
            json={"window_days": 30, "reason": REASON, "confirm": False},
            headers=admin,
        )
        assert missing_confirm.status_code == 422
        short_reason = await client.post(
            "/admin/abuse/queue/scan",
            json={"window_days": 30, "reason": "x", "confirm": True},
            headers=admin,
        )
        assert short_reason.status_code == 422
        bad_window = await client.post(
            "/admin/abuse/queue/scan",
            json={"window_days": 14, "reason": REASON, "confirm": True},
            headers=admin,
        )
        assert bad_window.status_code == 422


class TestQueueTransitions:
    async def test_assign_acknowledge_dismiss_and_audit(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_a_id, admin_a = await _create_user(db_session, role="admin")
        admin_b_id, admin_b = await _create_user(db_session, role="admin")
        await _seed_device(db_session, tag="transition", blocked=True)
        await _scan(client, admin_a)
        item = _find(await _all_items(client, admin_a), "blocked_device")

        _regular_id, regular_headers = await _create_user(
            db_session, role="user"
        )
        denied = await client.post(
            f"/admin/abuse/queue/{item['id']}/assign",
            json={"assignee_id": admin_b_id, "reason": REASON, "confirm": True},
            headers=regular_headers,
        )
        assert denied.status_code == 403

        invalid_assignee = await client.post(
            f"/admin/abuse/queue/{item['id']}/assign",
            json={
                "assignee_id": str(uuid.uuid4()),
                "reason": REASON,
                "confirm": True,
            },
            headers=admin_a,
        )
        assert invalid_assignee.status_code == 422

        assigned = await client.post(
            f"/admin/abuse/queue/{item['id']}/assign",
            json={"assignee_id": admin_b_id, "reason": REASON, "confirm": True},
            headers=admin_a,
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["assigned_to"] == admin_b_id

        acknowledged = await client.post(
            f"/admin/abuse/queue/{item['id']}/decision",
            json={
                "decision": "approve",
                "reason": REASON,
                "confirm": True,
            },
            headers=admin_b,
        )
        assert acknowledged.status_code == 200, acknowledged.text
        body = acknowledged.json()
        assert body["item"]["status"] == "approved"
        assert body["item"]["decision"] == "approve"
        assert body["item"]["decided_by"] == admin_b_id

        repeated = await client.post(
            f"/admin/abuse/queue/{item['id']}/decision",
            json={"decision": "approve", "reason": REASON, "confirm": True},
            headers=admin_b,
        )
        assert repeated.status_code == 200
        assert repeated.json()["idempotent"] is True

        dismissed = await client.post(
            f"/admin/abuse/queue/{item['id']}/decision",
            json={"decision": "dismiss", "reason": REASON, "confirm": True},
            headers=admin_a,
        )
        assert dismissed.status_code == 200, dismissed.text
        assert dismissed.json()["item"]["status"] == "dismissed"

        stale = await client.post(
            f"/admin/abuse/queue/{item['id']}/decision",
            json={"decision": "approve", "reason": REASON, "confirm": True},
            headers=admin_a,
        )
        assert stale.status_code == 409

        detail = await client.get(
            f"/admin/abuse/queue/{item['id']}", headers=admin_a
        )
        assert detail.status_code == 200
        assert detail.json()["status"] == "dismissed"
        assert "device_fingerprint" not in detail.text
        assert "ip_address" not in detail.text

        actions = (
            await db_session.execute(
                text(
                    "SELECT action FROM admin_audit_log "
                    "WHERE target_type = 'abuse_review_item' AND target_id = :id"
                ),
                {"id": item["id"]},
            )
        ).scalars().all()
        assert "admin.abuse.assign" in actions
        assert "admin.abuse.decision" in actions

    async def test_non_device_signal_cannot_be_enforced(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, admin = await _create_user(db_session, role="admin")
        payment_user, _ = await _create_user(
            db_session, role="user", email_tag=f"payonly_{uuid.uuid4().hex}"
        )
        await _seed_payment_failures(db_session, payment_user)
        await _scan(client, admin)
        item = _find(await _all_items(client, admin), "payment_failure")

        response = await client.post(
            f"/admin/abuse/queue/{item['id']}/decision",
            json={
                "decision": "action",
                "action": "block",
                "reason": REASON,
                "confirm": True,
            },
            headers=admin,
        )
        assert response.status_code == 422
        assert "device" in response.text.lower()


class TestTwoPersonEnforcement:
    async def test_self_approval_is_refused_and_unblock_applies(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_a_id, admin_a = await _create_user(db_session, role="admin")
        admin_b_id, admin_b = await _create_user(db_session, role="admin")
        fingerprint = await _seed_device(
            db_session, tag="unblock", usage_count=1, blocked=True
        )
        await _scan(client, admin_a)
        subject_key = hashlib.md5(
            fingerprint.encode("utf-8"), usedforsecurity=False
        ).hexdigest()
        item = next(
            candidate
            for candidate in await _all_items(
                client, admin_a, signal_type="blocked_device"
            )
            if candidate["subject_key"] == subject_key
            and candidate["status"] == "open"
        )

        requested = await client.post(
            f"/admin/abuse/queue/{item['id']}/decision",
            json={
                "decision": "action",
                "action": "unblock",
                "reason": "False positive on shared campus network",
                "confirm": True,
            },
            headers=admin_a,
        )
        assert requested.status_code == 202, requested.text
        body = requested.json()
        assert body["approval_required"] is True
        approval_id = body["approval"]["id"]
        assert body["approval"]["request_type"] == "abuse_review_action"
        assert body["approval"]["requested_by"] == admin_a_id
        assert body["approval"]["payload"]["subject_key"] == item["subject_key"]

        self_approve = await client.post(
            f"/admin/approvals/{approval_id}/approve",
            json={"note": "Self approval should fail"},
            headers=admin_a,
        )
        assert self_approve.status_code == 409
        assert "self" in self_approve.text.lower()

        approved = await client.post(
            f"/admin/approvals/{approval_id}/approve",
            json={"note": "Confirmed shared NAT false positive"},
            headers=admin_b,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["approved_by"] == admin_b_id

        executed = await client.post(
            f"/admin/abuse/queue/{item['id']}/decision",
            json={
                "decision": "action",
                "action": "unblock",
                "reason": "False positive on shared campus network",
                "confirm": True,
                "approval_id": approval_id,
            },
            headers=admin_a,
        )
        assert executed.status_code == 200, executed.text
        assert executed.json()["item"]["status"] == "actioned"
        assert executed.json()["item"]["enforcement_action"] == "unblock"
        assert executed.json()["item"]["approval_id"] == approval_id

        trial = await db_session.scalar(
            select(models.DeviceTrial).where(
                models.DeviceTrial.device_fingerprint == fingerprint
            )
        )
        assert trial is not None
        assert trial.blocked is False
        assert trial.whitelisted is False

        status = await trial_service.trial_service.get_trial_status(db_session, fingerprint)
        assert status["blocked"] is False
        assert status["canUse"] is True

        replay = await client.post(
            f"/admin/approvals/{approval_id}/execute",
            json={"note": "replay"},
            headers=admin_a,
        )
        assert replay.status_code == 409
        assert "replayed" in replay.text.lower() or "executed" in replay.text.lower()

        # The queue endpoint is idempotent for the same consumed approval.
        idempotent = await client.post(
            f"/admin/abuse/queue/{item['id']}/decision",
            json={
                "decision": "action",
                "action": "unblock",
                "reason": "False positive on shared campus network",
                "confirm": True,
                "approval_id": approval_id,
            },
            headers=admin_a,
        )
        assert idempotent.status_code == 200
        assert idempotent.json()["idempotent"] is True

    async def test_block_and_whitelist_change_next_trial_check(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_a_id, admin_a = await _create_user(db_session, role="admin")
        _admin_b_id, admin_b = await _create_user(db_session, role="admin")

        block_fp = await _seed_device(
            db_session, tag="block_target", usage_count=3, blocked=False
        )
        await _scan(client, admin_a)
        block_key = hashlib.md5(
            block_fp.encode("utf-8"), usedforsecurity=False
        ).hexdigest()
        block_item = next(
            item
            for item in await _all_items(
                client, admin_a, signal_type="trial_limit_reached"
            )
            if item["subject_key"] == block_key
        )

        request = await client.post(
            f"/admin/abuse/queue/{block_item['id']}/decision",
            json={
                "decision": "action",
                "action": "block",
                "reason": "Repeated trial exhaustion",
                "confirm": True,
            },
            headers=admin_a,
        )
        assert request.status_code == 202, request.text
        approval_id = request.json()["approval"]["id"]
        assert (
            await client.post(
                f"/admin/approvals/{approval_id}/approve",
                json={"note": "Confirmed repeated exhaustion"},
                headers=admin_b,
            )
        ).status_code == 200
        assert (
            await client.post(
                f"/admin/abuse/queue/{block_item['id']}/decision",
                json={
                    "decision": "action",
                    "action": "block",
                    "reason": "Repeated trial exhaustion",
                    "confirm": True,
                    "approval_id": approval_id,
                },
                headers=admin_a,
            )
        ).status_code == 200

        trial = await db_session.scalar(
            select(models.DeviceTrial).where(
                models.DeviceTrial.device_fingerprint == block_fp
            )
        )
        assert trial is not None
        assert trial.blocked is True
        assert trial.whitelisted is False
        status = await trial_service.trial_service.get_trial_status(db_session, block_fp)
        assert status["blocked"] is True
        assert status["canUse"] is False

        # A whitelist action restores use and exempts the device from the
        # automatic ceiling on the next check.
        whitelist_fp = await _seed_device(
            db_session,
            tag="whitelist_target",
            usage_count=3,
            blocked=True,
            last_used=_now() - timedelta(minutes=30),
        )
        await _scan(client, admin_a)
        whitelist_key = hashlib.md5(
            whitelist_fp.encode("utf-8"), usedforsecurity=False
        ).hexdigest()
        whitelist_item = next(
            item
            for item in await _all_items(
                client, admin_a, signal_type="blocked_device"
            )
            if item["subject_key"] == whitelist_key and item["status"] == "open"
        )

        request = await client.post(
            f"/admin/abuse/queue/{whitelist_item['id']}/decision",
            json={
                "decision": "action",
                "action": "whitelist",
                "reason": "Verified partner device",
                "confirm": True,
            },
            headers=admin_a,
        )
        assert request.status_code == 202, request.text
        approval_id = request.json()["approval"]["id"]
        assert (
            await client.post(
                f"/admin/approvals/{approval_id}/approve",
                json={"note": "Verified partner device"},
                headers=admin_b,
            )
        ).status_code == 200
        assert (
            await client.post(
                f"/admin/abuse/queue/{whitelist_item['id']}/decision",
                json={
                    "decision": "action",
                    "action": "whitelist",
                    "reason": "Verified partner device",
                    "confirm": True,
                    "approval_id": approval_id,
                },
                headers=admin_a,
            )
        ).status_code == 200

        trial = await db_session.scalar(
            select(models.DeviceTrial).where(
                models.DeviceTrial.device_fingerprint == whitelist_fp
            )
        )
        assert trial is not None
        assert trial.blocked is False
        assert trial.whitelisted is True
        status = await trial_service.trial_service.get_trial_status(db_session, whitelist_fp)
        assert status["blocked"] is False
        assert status["canUse"] is True

        # A whitelisted exhausted device is not auto-blocked on use.
        tracked = await trial_service.trial_service.track_usage(
            db_session, whitelist_fp, "abuse_test_whitelist_use"
        )
        assert tracked["success"] is True
        trial = await db_session.scalar(
            select(models.DeviceTrial).where(
                models.DeviceTrial.device_fingerprint == whitelist_fp
            )
        )
        await db_session.refresh(trial)
        assert trial is not None
        assert trial.blocked is False

    async def test_approval_for_another_item_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_a_id, admin_a = await _create_user(db_session, role="admin")
        _admin_b_id, admin_b = await _create_user(db_session, role="admin")
        await _seed_device(db_session, tag="cross_a", blocked=True)
        await _seed_device(db_session, tag="cross_b", blocked=True)
        await _scan(client, admin_a)
        items = [
            item
            for item in await _all_items(client, admin_a, signal_type="blocked_device")
            if item["status"] == "open"
        ]
        assert len(items) >= 2
        first, second = items[0], items[1]

        requested = await client.post(
            f"/admin/abuse/queue/{first['id']}/decision",
            json={
                "decision": "action",
                "action": "unblock",
                "reason": "Cross item check",
                "confirm": True,
            },
            headers=admin_a,
        )
        approval_id = requested.json()["approval"]["id"]
        assert (
            await client.post(
                f"/admin/approvals/{approval_id}/approve",
                json={"note": "Approved for the first item"},
                headers=admin_b,
            )
        ).status_code == 200

        cross = await client.post(
            f"/admin/abuse/queue/{second['id']}/decision",
            json={
                "decision": "action",
                "action": "unblock",
                "reason": "Cross item check",
                "confirm": True,
                "approval_id": approval_id,
            },
            headers=admin_a,
        )
        assert cross.status_code == 409
        # The second item must remain open; the approval stays bound to the first.
        refreshed_second = await client.get(
            f"/admin/abuse/queue/{second['id']}", headers=admin_a
        )
        assert refreshed_second.json()["status"] == "open"


class TestDatabaseGuardAndMigration:
    async def test_queue_rows_cannot_be_deleted_or_reidentified(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, admin = await _create_user(db_session, role="admin")
        await _seed_device(db_session, tag="guard", blocked=True)
        await _scan(client, admin)
        item = _find(await _all_items(client, admin), "blocked_device")

        with pytest.raises(Exception):
            await db_session.execute(
                text("DELETE FROM abuse_review_items WHERE id = :id"),
                {"id": item["id"]},
            )
        await db_session.rollback()

        with pytest.raises(Exception):
            await db_session.execute(
                text(
                    "UPDATE abuse_review_items SET subject_key = :new_key WHERE id = :id"
                ),
                {"id": item["id"], "new_key": "0" * 32},
            )
        await db_session.rollback()

        still_there = await client.get(
            f"/admin/abuse/queue/{item['id']}", headers=admin
        )
        assert still_there.status_code == 200
        assert still_there.json()["subject_key"] == item["subject_key"]

    def test_migration_is_rechained_from_daily_metrics(self):
        path = (
            Path(__file__).parents[1]
            / "alembic/versions/0103_abuse_review.py"
        )
        module = __import__("runpy").run_path(str(path))
        assert module["revision"] == "0103_abuse_review"
        assert module["down_revision"] == "0100_daily_metrics"
