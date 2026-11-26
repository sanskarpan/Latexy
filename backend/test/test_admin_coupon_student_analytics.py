"""Coupon and student-verification performance analytics.

Covers redemption/subscription reconciliation, expired and reused lifecycle
events, the request -> verify -> paid funnel, five-user suppression, privacy,
admin-only access, and the no-migration constraint.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Base, UsageAnalytics
from app.services.coupon_student_analytics_service import (
    record_coupon_reserved,
    record_student_failure,
    record_student_requested,
)

NOW = datetime.now(timezone.utc)
# A future, isolated anchor so other shared-database activity cannot overlap.
ANCHOR = datetime(2033, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=uuid.uuid4().int % (300 * 86_400))
ENDPOINT = "/admin/revenue/coupon-student-performance"

COUPON_RESERVED = "coupon_reserved"
COUPON_REDEEMED = "coupon_redeemed"
STUDENT_REQUESTED = "student_verification_requested"
STUDENT_VERIFIED = "student_verification_verified"
STUDENT_PAID = "student_verification_paid"
STUDENT_FAILED = "student_verification_failed"


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
    created_at: datetime | None = None,
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"test_coupon_student_{role}_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, created_at) "
            "VALUES (:id, :email, 'Coupon Student Test', :role, true, :plan, 'active', false, :created)"
        ),
        {
            "id": user_id,
            "email": email,
            "role": role,
            "plan": plan,
            "created": created_at or NOW,
        },
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_coupon_student_{uuid.uuid4().hex}"
    await db.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": NOW + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _headers(db: AsyncSession, role: str = "admin") -> dict[str, str]:
    user_id, _email = await _create_user(db, role=role)
    return await _session_headers(db, user_id)


async def _insert_coupon(
    db: AsyncSession,
    *,
    code: str | None = None,
    discount_percent: int = 25,
    applicable_plans: list[str] | None = None,
    max_uses: int | None = 50,
    used_count: int = 0,
    expires_at: datetime | None = None,
) -> tuple[str, str]:
    coupon_id = str(uuid.uuid4())
    code = code or f"TEST{uuid.uuid4().hex[:12].upper()}"
    await db.execute(
        text(
            "INSERT INTO coupon_codes (id, code, discount_percent, applicable_plans, "
            "max_uses, used_count, expires_at, created_at) "
            "VALUES (:id, :code, :discount, :plans, :max_uses, :used_count, :expires, :created)"
        ),
        {
            "id": coupon_id,
            "code": code,
            "discount": discount_percent,
            "plans": applicable_plans or ["pro"],
            "max_uses": max_uses,
            "used_count": used_count,
            "expires": expires_at,
            "created": ANCHOR - timedelta(days=1),
        },
    )
    await db.commit()
    return coupon_id, code


async def _insert_subscription(
    db: AsyncSession,
    *,
    user_id: str,
    status: str = "active",
    plan_id: str = "pro",
    created_at: datetime | None = None,
) -> str:
    subscription_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, plan_id, status, "
            "created_at, current_period_start) "
            "VALUES (:id, :uid, 'dodo', :plan, :status, :created, :created)"
        ),
        {
            "id": subscription_id,
            "uid": user_id,
            "plan": plan_id,
            "status": status,
            "created": created_at or ANCHOR,
        },
    )
    await db.commit()
    return subscription_id


async def _insert_payment(
    db: AsyncSession,
    *,
    user_id: str,
    subscription_id: str,
    status: str = "paid",
    created_at: datetime | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO payments (id, user_id, subscription_id, provider, "
            "provider_payment_id, amount, currency, status, created_at) "
            "VALUES (:id, :uid, :sub, 'dodo', :provider_payment, 59900, 'INR', :status, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "sub": subscription_id,
            "provider_payment": f"pay_{uuid.uuid4().hex[:16]}",
            "status": status,
            "created": created_at or ANCHOR,
        },
    )
    await db.commit()


async def _insert_redemption(
    db: AsyncSession,
    *,
    coupon_id: str,
    user_id: str,
    subscription_id: str | None,
    status: str = "redeemed",
    redeemed_at: datetime | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO coupon_redemptions (id, coupon_id, user_id, subscription_id, "
            "status, redeemed_at) VALUES (:id, :coupon, :uid, :sub, :status, :redeemed)"
        ),
        {
            "id": str(uuid.uuid4()),
            "coupon": coupon_id,
            "uid": user_id,
            "sub": subscription_id,
            "status": status,
            "redeemed": redeemed_at if status == "redeemed" else None,
        },
    )
    await db.commit()


async def _insert_event(
    db: AsyncSession,
    *,
    user_id: str | None,
    action: str,
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO usage_analytics (id, user_id, action, resource_type, "
            "event_metadata, created_at) "
            "VALUES (:id, :uid, :action, 'revenue_lifecycle', CAST(:metadata AS JSONB), :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "action": action,
            "metadata": json.dumps(metadata or {}),
            "created": created_at or ANCHOR,
        },
    )
    await db.commit()


async def _cleanup_temp_rows(db: AsyncSession) -> None:
    """Keep repeated local runs deterministic without dropping shared tables."""
    lifecycle_actions = (
        COUPON_RESERVED,
        COUPON_REDEEMED,
        "coupon_released",
        STUDENT_REQUESTED,
        STUDENT_VERIFIED,
        STUDENT_PAID,
        STUDENT_FAILED,
    )
    await db.execute(
        text(
            "DELETE FROM coupon_redemptions WHERE coupon_id IN "
            "(SELECT id FROM coupon_codes WHERE code LIKE 'TEST%') "
            "OR user_id IN (SELECT id FROM users WHERE email LIKE 'test_coupon_student_%')"
        )
    )
    await db.execute(
        text(
            "DELETE FROM usage_analytics WHERE action = ANY(:actions) "
            "OR user_id IN (SELECT id FROM users WHERE email LIKE 'test_coupon_student_%')"
        ),
        {"actions": list(lifecycle_actions)},
    )
    await db.execute(
        text("DELETE FROM payments WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_coupon_student_%')")
    )
    await db.execute(
        text(
            "DELETE FROM subscriptions WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test_coupon_student_%')"
        )
    )
    await db.execute(text("DELETE FROM coupon_codes WHERE code LIKE 'TEST%'"))
    await db.execute(text("DELETE FROM session WHERE token LIKE 'test_sess_coupon_student_%'"))
    await db.execute(text("DELETE FROM users WHERE email LIKE 'test_coupon_student_%'"))
    await db.commit()


@pytest.fixture(autouse=True)
async def isolated_rows(db_session: AsyncSession):
    await _cleanup_temp_rows(db_session)
    yield
    await _cleanup_temp_rows(db_session)


def _params(**overrides: Any) -> dict[str, Any]:
    values = {
        "start": (ANCHOR - timedelta(days=1)).isoformat(),
        "end": (ANCHOR + timedelta(days=2)).isoformat(),
    }
    values.update(overrides)
    return values


def _assert_no_sensitive_keys(value: Any) -> None:
    forbidden = {
        "user_id",
        "email",
        "student_email",
        "ip_address",
        "user_agent",
        "event_metadata",
        "verification_token",
    }
    if isinstance(value, dict):
        assert not (set(value) & forbidden), set(value) & forbidden
        for child in value.values():
            _assert_no_sensitive_keys(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_sensitive_keys(child)


@pytest.mark.asyncio
async def test_coupon_redemptions_reconcile_to_subscriptions_and_plan_filter(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin_headers = await _headers(db_session)
    coupon_id, code = await _insert_coupon(
        db_session,
        applicable_plans=["pro"],
        max_uses=10,
        used_count=5,
        expires_at=ANCHOR + timedelta(days=30),
    )
    for index in range(5):
        user_id, _ = await _create_user(db_session, created_at=ANCHOR - timedelta(days=5))
        subscription_id = await _insert_subscription(
            db_session,
            user_id=user_id,
            status="active",
            plan_id="pro",
        )
        await _insert_payment(db_session, user_id=user_id, subscription_id=subscription_id)
        await _insert_redemption(
            db_session,
            coupon_id=coupon_id,
            user_id=user_id,
            subscription_id=subscription_id,
            redeemed_at=ANCHOR + timedelta(hours=index),
        )
        await _insert_event(
            db_session,
            user_id=user_id,
            action=COUPON_RESERVED,
            metadata={"coupon_id": coupon_id, "plan_id": "pro"},
            created_at=ANCHOR + timedelta(minutes=index),
        )

    response = await client.get(ENDPOINT, params=_params(plan="pro"), headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    coupon = body["coupon"]
    assert coupon["totals"]["redemptions"] >= 5
    assert coupon["totals"]["paid_redemptions"] >= 5
    assert coupon["totals"]["conversion_pct"] == 100.0
    assert coupon["reconciliation"]["checks"][0]["key"] == "redemptions_linked_to_subscriptions"
    assert coupon["reconciliation"]["checks"][1]["key"] == "used_count_matches_active_redemptions"
    row = next(item for item in coupon["by_coupon"] if item["coupon_id"] == coupon_id)
    assert row["code"] == code
    assert row["redemptions"] == 5
    assert row["paid_redemptions"] == 5
    assert row["conversion_pct"] == 100.0
    assert body["filters"]["plan"] == "pro"
    assert body["privacy"]["aggregate_only"] is True
    assert body["minimum_segment_size"] == 5
    _assert_no_sensitive_keys(body)

    filtered = await client.get(ENDPOINT, params=_params(plan="basic"), headers=admin_headers)
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert all(item["coupon_id"] != coupon_id for item in filtered_body["coupon"]["by_coupon"])
    assert filtered_body["student"]["applicable"] is False


@pytest.mark.asyncio
async def test_expired_and_reused_coupon_tokens_are_review_flags_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin_headers = await _headers(db_session)
    coupon_id, code = await _insert_coupon(
        db_session,
        applicable_plans=["pro"],
        max_uses=25,
        used_count=5,
        expires_at=ANCHOR - timedelta(days=1),
    )
    for index in range(5):
        user_id, _ = await _create_user(db_session, created_at=ANCHOR - timedelta(days=5))
        subscription_id = await _insert_subscription(
            db_session,
            user_id=user_id,
            status="active",
            plan_id="pro",
        )
        await _insert_redemption(
            db_session,
            coupon_id=coupon_id,
            user_id=user_id,
            subscription_id=subscription_id,
            redeemed_at=ANCHOR + timedelta(hours=index),
        )
        for attempt in range(2):
            await _insert_event(
                db_session,
                user_id=user_id,
                action=COUPON_RESERVED,
                metadata={"coupon_id": coupon_id, "plan_id": "pro"},
                created_at=ANCHOR + timedelta(minutes=index * 10 + attempt),
            )

    response = await client.get(ENDPOINT, params=_params(plan="pro"), headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    coupon = body["coupon"]
    assert coupon["totals"]["expired_redemptions"] >= 5
    assert coupon["totals"]["repeated_reservation_users"] >= 5
    row = next(item for item in coupon["by_coupon"] if item["coupon_id"] == coupon_id)
    assert row["code"] == code
    assert row["expired_redemptions"] >= 5
    assert row["repeated_reservation_users"] >= 5
    kinds = {flag["kind"] for flag in body["review_flags"]}
    assert {"expired_coupon_redemption", "suspicious_reuse"} & kinds
    assert all(flag["requires_human_review"] is True for flag in body["review_flags"])
    assert all(flag["automated_action"] == "none" for flag in body["review_flags"])
    _assert_no_sensitive_keys(body)


@pytest.mark.asyncio
async def test_student_request_verify_paid_funnel_and_repeated_failures(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin_headers = await _headers(db_session)
    users: list[str] = []
    for index in range(6):
        user_id, _ = await _create_user(db_session, plan="student", created_at=ANCHOR - timedelta(days=2))
        users.append(user_id)
        base = ANCHOR + timedelta(minutes=index * 20)
        await _insert_event(
            db_session,
            user_id=user_id,
            action=STUDENT_REQUESTED,
            metadata={"plan_id": "student"},
            created_at=base,
        )
        await _insert_event(
            db_session,
            user_id=user_id,
            action=STUDENT_VERIFIED,
            metadata={"plan_id": "student"},
            created_at=base + timedelta(minutes=5),
        )
        await _insert_event(
            db_session,
            user_id=user_id,
            action=STUDENT_PAID,
            metadata={"plan_id": "student"},
            created_at=base + timedelta(minutes=10),
        )
    for user_id in users[:5]:
        for attempt in range(2):
            await _insert_event(
                db_session,
                user_id=user_id,
                action=STUDENT_FAILED,
                metadata={"plan_id": "student", "reason": "expired_or_invalid"},
                created_at=ANCHOR + timedelta(minutes=attempt),
            )
    await _insert_event(
        db_session,
        user_id=None,
        action=STUDENT_FAILED,
        metadata={"plan_id": "student", "reason": "already_used"},
        created_at=ANCHOR + timedelta(minutes=1),
    )

    response = await client.get(ENDPOINT, params=_params(plan="student"), headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    student = body["student"]
    assert student["applicable"] is True
    assert student["requested_users"] == 6
    assert student["verified_users"] == 6
    assert student["paid_users"] == 6
    assert student["conversion"]["requested_to_verified"] == 100.0
    assert student["conversion"]["verified_to_paid"] == 100.0
    assert student["failures"]["total_events"] >= 11
    assert student["failures"]["distinct_users"] >= 5
    assert student["failures"]["repeated_failure_users"] >= 5
    reasons = {item["reason"] for item in student["failures"]["by_reason"]}
    assert "expired_or_invalid" in reasons
    assert "already_used" in reasons
    assert student["reconciliation"]["requested_at_least_verified"] is True
    assert student["reconciliation"]["verified_at_least_paid"] is True
    assert student["reconciliation"]["paid_without_verification"] == 0
    kinds = {flag["kind"] for flag in body["review_flags"]}
    assert {"expired_or_invalid_token", "reused_token", "repeated_student_failures"} <= kinds
    assert all(flag["automated_action"] == "none" for flag in body["review_flags"])
    _assert_no_sensitive_keys(body)


@pytest.mark.asyncio
async def test_five_user_suppression_hides_small_segments(client: AsyncClient, db_session: AsyncSession) -> None:
    admin_headers = await _headers(db_session)
    coupon_id, code = await _insert_coupon(
        db_session,
        applicable_plans=["pro"],
        max_uses=10,
        used_count=2,
        expires_at=ANCHOR + timedelta(days=30),
    )
    for index in range(2):
        user_id, _ = await _create_user(db_session, created_at=ANCHOR - timedelta(days=2))
        subscription_id = await _insert_subscription(
            db_session,
            user_id=user_id,
            status="active",
            plan_id="pro",
        )
        await _insert_redemption(
            db_session,
            coupon_id=coupon_id,
            user_id=user_id,
            subscription_id=subscription_id,
            redeemed_at=ANCHOR + timedelta(minutes=index),
        )
        await _insert_event(
            db_session,
            user_id=user_id,
            action=STUDENT_REQUESTED,
            metadata={"plan_id": "student"},
            created_at=ANCHOR + timedelta(minutes=index),
        )
        await _insert_event(
            db_session,
            user_id=user_id,
            action=STUDENT_VERIFIED,
            metadata={"plan_id": "student"},
            created_at=ANCHOR + timedelta(minutes=index + 1),
        )

    response = await client.get(ENDPOINT, params=_params(plan="pro"), headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert all(item["coupon_id"] != coupon_id for item in body["coupon"]["by_coupon"])
    assert code not in response.text
    assert body["coupon"]["suppressed_coupons"] >= 1
    assert body["student"]["applicable"] is False

    student_response = await client.get(ENDPOINT, params=_params(plan="student"), headers=admin_headers)
    student_body = student_response.json()
    assert student_body["student"]["requested_users"] >= 2
    assert all(item["users"] >= 5 for item in student_body["student"]["by_plan"])
    assert student_body["student"]["suppressed_segments"] >= 1


@pytest.mark.asyncio
async def test_admin_only_and_no_sensitive_data(client: AsyncClient, db_session: AsyncSession) -> None:
    user_headers = await _headers(db_session, role="user")
    support_headers = await _headers(db_session, role="support")
    admin_headers = await _headers(db_session, role="admin")

    for headers in (user_headers, support_headers):
        response = await client.get(ENDPOINT, params=_params(), headers=headers)
        assert response.status_code == 403

    admin_response = await client.get(ENDPOINT, params=_params(), headers=admin_headers)
    assert admin_response.status_code == 200
    body = admin_response.json()
    assert body["privacy"]["student_emails_returned"] is False
    assert body["privacy"]["verification_tokens_returned"] is False
    assert body["privacy"]["account_ids_returned"] is False
    assert body["privacy"]["event_metadata_returned"] is False
    _assert_no_sensitive_keys(body)
    assert "@example.com" not in admin_response.text


@pytest.mark.asyncio
async def test_invalid_range_is_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    admin_headers = await _headers(db_session)
    response = await client.get(
        ENDPOINT,
        params={
            "start": (ANCHOR + timedelta(days=1)).isoformat(),
            "end": ANCHOR.isoformat(),
        },
        headers=admin_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_lifecycle_events_persist_in_usage_analytics_jsonb(db_session: AsyncSession) -> None:
    user_id, _ = await _create_user(db_session)
    coupon_id, _ = await _insert_coupon(db_session)
    await record_coupon_reserved(db_session, user_id=user_id, coupon_id=coupon_id, plan_id="pro")
    await db_session.commit()
    await record_student_requested(db_session, user_id=user_id)
    await record_student_failure(db_session, user_id=None, reason="expired_or_invalid")

    rows = (
        await db_session.execute(
            select(
                UsageAnalytics.action,
                UsageAnalytics.user_id,
                UsageAnalytics.event_metadata,
            )
            .where(
                UsageAnalytics.action.in_(
                    (
                        "coupon_reserved",
                        "student_verification_requested",
                        "student_verification_failed",
                    )
                )
            )
            .order_by(UsageAnalytics.created_at)
        )
    ).all()
    assert {row.action for row in rows} == {
        "coupon_reserved",
        "student_verification_requested",
        "student_verification_failed",
    }
    coupon_event = next(row for row in rows if row.action == "coupon_reserved")
    assert coupon_event.user_id == user_id
    assert coupon_event.event_metadata["coupon_id"] == coupon_id
    assert coupon_event.event_metadata["plan_id"] == "pro"
    anonymous_failure = next(row for row in rows if row.action == "student_verification_failed")
    assert anonymous_failure.user_id is None
    assert anonymous_failure.event_metadata["reason"] == "expired_or_invalid"
    assert "token" not in anonymous_failure.event_metadata


def test_report_uses_existing_tables_and_billing_records_lifecycle_events() -> None:
    backend = Path(__file__).resolve().parents[1]
    service_source = (backend / "app/services/coupon_student_analytics_service.py").read_text()
    payment_source = (backend / "app/services/payment_service.py").read_text()
    assert set(Base.metadata.tables) >= {
        "coupon_codes",
        "coupon_redemptions",
        "subscriptions",
        "payments",
        "usage_analytics",
    }
    for hook in (
        "record_student_requested",
        "record_student_verified",
        "record_student_paid",
        "record_student_failure",
        "record_coupon_reserved",
        "record_coupon_redemption_status",
    ):
        assert hook in payment_source
    assert "alembic" not in service_source.lower()
