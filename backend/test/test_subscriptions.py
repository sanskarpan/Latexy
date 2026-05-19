from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TeamSeat


async def _ensure_subscription_extension_schema(db: AsyncSession) -> None:
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS team_seats (
              id UUID PRIMARY KEY,
              owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              member_email TEXT NOT NULL,
              member_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
              status TEXT NOT NULL DEFAULT 'invited',
              invited_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              joined_at TIMESTAMPTZ,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              CONSTRAINT uq_team_seats_owner_email UNIQUE (owner_user_id, member_email)
            )
            """
        )
    )
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS coupon_codes (
              id UUID PRIMARY KEY,
              code TEXT NOT NULL UNIQUE,
              discount_percent INTEGER NOT NULL,
              applicable_plans TEXT[],
              max_uses INTEGER,
              used_count INTEGER NOT NULL DEFAULT 0,
              expires_at TIMESTAMPTZ,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS coupon_redemptions (
              id UUID PRIMARY KEY,
              coupon_id UUID REFERENCES coupon_codes(id) ON DELETE SET NULL,
              user_id UUID REFERENCES users(id) ON DELETE SET NULL,
              redeemed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    await db.commit()


async def _create_user(db: AsyncSession, plan: str = "free") -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"test_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            """
            INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used)
            VALUES (:id, :email, 'Billing Test', true, :plan, 'active', false)
            """
        ),
        {"id": user_id, "email": email, "plan": plan},
    )
    await db.commit()
    return user_id, email


async def _create_session(db: AsyncSession, user_id: str) -> str:
    token = f"test_sess_{uuid.uuid4().hex}"
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {"id": str(uuid.uuid4()), "uid": user_id, "exp": expires_at, "tok": token},
    )
    await db.commit()
    return token


class TestAdvancedSubscriptions:
    async def test_validate_coupon_accepts_valid_code(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_subscription_extension_schema(db_session)
        await db_session.execute(
            text(
                """
                INSERT INTO coupon_codes (id, code, discount_percent, applicable_plans, used_count)
                VALUES (:id, 'SAVE20', 20, ARRAY['pro'], 0)
                ON CONFLICT (code) DO UPDATE SET discount_percent = EXCLUDED.discount_percent
                """
            ),
            {"id": str(uuid.uuid4())},
        )
        await db_session.commit()

        response = await client.post(
            "/billing/validate-coupon",
            json={"code": "SAVE20", "planId": "pro", "billingPeriod": "monthly"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["valid"] is True
        assert payload["discountPercent"] == 20

    async def test_validate_coupon_rejects_expired_code(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_subscription_extension_schema(db_session)
        await db_session.execute(
            text(
                """
                INSERT INTO coupon_codes (id, code, discount_percent, expires_at, used_count)
                VALUES (:id, 'OLD50', 50, NOW() - INTERVAL '1 day', 0)
                ON CONFLICT (code) DO UPDATE SET expires_at = EXCLUDED.expires_at
                """
            ),
            {"id": str(uuid.uuid4())},
        )
        await db_session.commit()

        response = await client.post(
            "/billing/validate-coupon",
            json={"code": "OLD50", "planId": "pro", "billingPeriod": "monthly"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["valid"] is False

    async def test_student_plan_rejects_non_academic_email(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_subscription_extension_schema(db_session)
        user_id, email = await _create_user(db_session, plan="free")
        session_token = await _create_session(db_session, user_id)

        with patch("app.api.routes.feature_flag_service.get_flag", new=AsyncMock(return_value=True)):
            response = await client.post(
                "/subscription/create",
                json={
                    "planId": "student",
                    "customerEmail": email,
                    "customerName": "Student User",
                    "studentEmail": "student@gmail.com",
                },
                headers={"Authorization": f"Bearer {session_token}"},
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is False
        assert "academic email" in payload["error"]

    async def test_student_plan_sends_verification_for_valid_academic_email(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_subscription_extension_schema(db_session)
        user_id, email = await _create_user(db_session, plan="free")
        session_token = await _create_session(db_session, user_id)

        with (
            patch("app.api.routes.feature_flag_service.get_flag", new=AsyncMock(return_value=True)),
            patch("app.services.payment_service.email_service.send_email", new=AsyncMock(return_value=True)) as send_email,
        ):
            response = await client.post(
                "/subscription/create",
                json={
                    "planId": "student",
                    "customerEmail": email,
                    "customerName": "Student User",
                    "studentEmail": "student@university.edu",
                },
                headers={"Authorization": f"Bearer {session_token}"},
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["verificationRequired"] is True
        send_email.assert_awaited()

    async def test_team_invite_creates_seat_record(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_subscription_extension_schema(db_session)
        user_id, _ = await _create_user(db_session, plan="team")
        session_token = await _create_session(db_session, user_id)

        with patch("app.api.team_routes.email_service.send_email", new=AsyncMock(return_value=True)):
            response = await client.post(
                "/team/invite",
                json={"email": "colleague@example.com"},
                headers={"Authorization": f"Bearer {session_token}"},
            )

        assert response.status_code == 201
        payload = response.json()
        assert payload["member_email"] == "colleague@example.com"
        seat = (
            await db_session.execute(select(TeamSeat).where(TeamSeat.owner_user_id == user_id))
        ).scalar_one()
        assert seat.status == "invited"

    async def test_team_invite_respects_five_seat_limit(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_subscription_extension_schema(db_session)
        user_id, _ = await _create_user(db_session, plan="team")
        session_token = await _create_session(db_session, user_id)

        for idx in range(5):
            await db_session.execute(
                text(
                    """
                    INSERT INTO team_seats (id, owner_user_id, member_email, status)
                    VALUES (:id, :owner, :email, 'invited')
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "owner": user_id,
                    "email": f"member{idx}@example.com",
                },
            )
        await db_session.commit()

        with patch("app.api.team_routes.email_service.send_email", new=AsyncMock(return_value=True)):
            response = await client.post(
                "/team/invite",
                json={"email": "overflow@example.com"},
                headers={"Authorization": f"Bearer {session_token}"},
            )

        assert response.status_code == 400
