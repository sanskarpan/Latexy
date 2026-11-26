"""Admin referral programme analytics (#2066).

Covers admin-only access, funnel/reconciliation, reward and rejection-reason
reporting, date/plan filters, time-to-qualify, five-user suppression, CSV,
fraud-review signals and privacy.  Everything is built from existing referral,
reward and billing tables; the suite intentionally creates no migration.
"""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PREFIX = "test_ref_admin_"
EMAIL_PATTERN = f"{PREFIX}%@example.com"

SECRET_EMAIL = "test_ref_admin_secret_person_2066@example.com"
SECRET_PROVIDER_PAYMENT_ID = "pay_secret_referral_2066"
SECRET_PAYMENT_METHOD = "card_secret_referral_2066"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _email(label: str = "user") -> str:
    return f"{PREFIX}{label}_{uuid.uuid4().hex[:10]}@example.com"


async def _clean_all_test_referral_rows(db: AsyncSession) -> None:
    """Remove referral rows owned by any test-prefixed account.

    The endpoint aggregates the whole table, so rows left behind by another
    test module in the shared test database would otherwise change this report's
    totals. Production accounts never match ``test_%``.
    """

    await db.execute(
        text(
            "DELETE FROM referral_rewards WHERE attribution_id IN ("
            "SELECT a.id FROM referral_attributions a JOIN users u "
            "ON u.id = a.referrer_user_id OR u.id = a.referred_user_id "
            "WHERE u.email LIKE 'test_%')"
        )
    )
    await db.execute(
        text(
            "DELETE FROM referral_attributions WHERE referrer_user_id IN ("
            "SELECT id FROM users WHERE email LIKE 'test_%') "
            "OR referred_user_id IN (SELECT id FROM users WHERE email LIKE 'test_%')"
        )
    )
    await db.execute(
        text(
            "DELETE FROM referral_identities WHERE user_id IN ("
            "SELECT id FROM users WHERE email LIKE 'test_%')"
        )
    )
    await db.commit()


async def _clean_referral_analytics_rows(db: AsyncSession) -> None:
    await db.execute(
        text(
            "DELETE FROM referral_rewards WHERE attribution_id IN ("
            "SELECT a.id FROM referral_attributions a JOIN users u "
            "ON u.id = a.referrer_user_id OR u.id = a.referred_user_id "
            "WHERE u.email LIKE :email)"
        ),
        {"email": EMAIL_PATTERN},
    )
    await db.execute(
        text(
            "DELETE FROM referral_attributions WHERE referrer_user_id IN ("
            "SELECT id FROM users WHERE email LIKE :email) "
            "OR referred_user_id IN (SELECT id FROM users WHERE email LIKE :email)"
        ),
        {"email": EMAIL_PATTERN},
    )
    await db.execute(
        text(
            "DELETE FROM referral_identities WHERE user_id IN ("
            "SELECT id FROM users WHERE email LIKE :email)"
        ),
        {"email": EMAIL_PATTERN},
    )
    await db.execute(
        text(
            "DELETE FROM payments WHERE user_id IN ("
            "SELECT id FROM users WHERE email LIKE :email)"
        ),
        {"email": EMAIL_PATTERN},
    )
    await db.execute(
        text(
            "DELETE FROM subscriptions WHERE user_id IN ("
            "SELECT id FROM users WHERE email LIKE :email)"
        ),
        {"email": EMAIL_PATTERN},
    )
    await db.execute(
        text('DELETE FROM session WHERE "userId" IN (SELECT id::text FROM users WHERE email LIKE :email)'),
        {"email": EMAIL_PATTERN},
    )
    await db.execute(
        text("DELETE FROM users WHERE email LIKE :email"),
        {"email": EMAIL_PATTERN},
    )
    await db.commit()


@pytest.fixture(autouse=True)
async def _clean_referral_analytics(db_session: AsyncSession):
    await _clean_all_test_referral_rows(db_session)
    await _clean_referral_analytics_rows(db_session)
    yield
    await _clean_referral_analytics_rows(db_session)
    await _clean_all_test_referral_rows(db_session)


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
    email: str | None = None,
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    token = f"test_sess_ref_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Referral Analytics User', :role, true, :plan, 'active', false)"
        ),
        {
            "id": user_id,
            "email": email or _email(role),
            "role": role,
            "plan": plan,
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
    _user_id, headers = await _create_user(db, role="admin")
    return headers


async def _seed_identity(db: AsyncSession, referrer_user_id: str) -> str:
    identity_id = str(uuid.uuid4())
    code = uuid.uuid4().hex.upper()
    await db.execute(
        text(
            "INSERT INTO referral_identities (id, user_id, code, code_digest, created_at) "
            "VALUES (:id, :user_id, :code, :digest, :created_at)"
        ),
        {
            "id": identity_id,
            "user_id": referrer_user_id,
            "code": code,
            "digest": hashlib.sha256(code.encode("ascii")).hexdigest(),
            "created_at": _now() - timedelta(days=2),
        },
    )
    return identity_id


async def _seed_attribution(
    db: AsyncSession,
    *,
    identity_id: str,
    referrer_user_id: str,
    referred_user_id: str,
    status: str,
    captured_at: datetime,
    qualified_at: datetime | None = None,
    reversed_at: datetime | None = None,
    rejection_reason: str | None = None,
    plan: str = "pro",
    payment_status: str | None = None,
    reward_status: str | None = None,
    reward_value: int = 7,
    reward_issued_at: datetime | None = None,
    reward_reversed_at: datetime | None = None,
) -> str:
    payment_id = None
    if payment_status is not None:
        subscription_id = str(uuid.uuid4())
        payment_id = str(uuid.uuid4())
        payment_created_at = captured_at + timedelta(hours=1)
        await db.execute(
            text(
                "INSERT INTO subscriptions "
                "(id, user_id, provider, plan_id, status, created_at, updated_at) "
                "VALUES (:id, :user_id, 'dodo', :plan, 'active', :created_at, :created_at)"
            ),
            {
                "id": subscription_id,
                "user_id": referred_user_id,
                "plan": plan,
                "created_at": payment_created_at,
            },
        )
        await db.execute(
            text(
                "INSERT INTO payments "
                "(id, user_id, subscription_id, provider, provider_payment_id, amount, "
                "currency, status, payment_method, created_at) "
                "VALUES (:id, :user_id, :subscription_id, 'dodo', :provider_payment_id, "
                "100, 'INR', :status, :payment_method, :created_at)"
            ),
            {
                "id": payment_id,
                "user_id": referred_user_id,
                "subscription_id": subscription_id,
                "provider_payment_id": f"{SECRET_PROVIDER_PAYMENT_ID}_{uuid.uuid4().hex[:8]}",
                "status": payment_status,
                "payment_method": SECRET_PAYMENT_METHOD,
                "created_at": payment_created_at,
            },
        )

    attribution_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO referral_attributions "
            "(id, referral_identity_id, referrer_user_id, referred_user_id, status, "
            "rejection_reason, qualifying_payment_id, captured_at, qualified_at, reversed_at) "
            "VALUES (:id, :identity_id, :referrer_user_id, :referred_user_id, :status, "
            ":rejection_reason, :payment_id, :captured_at, :qualified_at, :reversed_at)"
        ),
        {
            "id": attribution_id,
            "identity_id": identity_id,
            "referrer_user_id": referrer_user_id,
            "referred_user_id": referred_user_id,
            "status": status,
            "rejection_reason": rejection_reason,
            "payment_id": payment_id,
            "captured_at": captured_at,
            "qualified_at": qualified_at,
            "reversed_at": reversed_at,
        },
    )

    if reward_status is not None:
        assert payment_id is not None
        await db.execute(
            text(
                "INSERT INTO referral_rewards "
                "(id, attribution_id, referrer_user_id, qualifying_payment_id, "
                "reward_type, reward_value, status, issued_at, reversed_at, created_at) "
                "VALUES (:id, :attribution_id, :referrer_user_id, :payment_id, "
                "'subscription_extension_days', :reward_value, :status, :issued_at, "
                ":reversed_at, :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "attribution_id": attribution_id,
                "referrer_user_id": referrer_user_id,
                "payment_id": payment_id,
                "reward_value": reward_value,
                "status": reward_status,
                "issued_at": reward_issued_at,
                "reversed_at": reward_reversed_at,
                "created_at": reward_issued_at or captured_at,
            },
        )
    return attribution_id


async def _seed_standard_cohort(
    db: AsyncSession,
    *,
    referrer_user_id: str,
    identity_id: str,
    now: datetime,
) -> None:
    """Five issued, five pending, one reversed, five rejected, one unqualified."""

    for _ in range(5):
        referred_id, _ = await _create_user(db, plan="pro")
        captured_at = now - timedelta(days=2)
        await _seed_attribution(
            db,
            identity_id=identity_id,
            referrer_user_id=referrer_user_id,
            referred_user_id=referred_id,
            status="qualified",
            captured_at=captured_at,
            qualified_at=captured_at + timedelta(hours=6),
            plan="pro",
            payment_status="paid",
            reward_status="issued",
            reward_value=7,
            reward_issued_at=captured_at + timedelta(hours=6),
        )

    for _ in range(5):
        referred_id, _ = await _create_user(db, plan="pro")
        captured_at = now - timedelta(days=2)
        await _seed_attribution(
            db,
            identity_id=identity_id,
            referrer_user_id=referrer_user_id,
            referred_user_id=referred_id,
            status="qualified",
            captured_at=captured_at,
            qualified_at=captured_at + timedelta(hours=6),
            plan="pro",
            payment_status="paid",
            reward_status="pending",
            reward_value=7,
        )

    referred_id, _ = await _create_user(db, plan="pro")
    captured_at = now - timedelta(days=2)
    await _seed_attribution(
        db,
        identity_id=identity_id,
        referrer_user_id=referrer_user_id,
        referred_user_id=referred_id,
        status="reversed",
        captured_at=captured_at,
        qualified_at=captured_at + timedelta(hours=6),
        reversed_at=captured_at + timedelta(days=1),
        plan="pro",
        payment_status="refunded",
        reward_status="reversed",
        reward_value=7,
        reward_issued_at=captured_at + timedelta(hours=6),
        reward_reversed_at=captured_at + timedelta(days=1),
    )

    for _ in range(5):
        referred_id, _ = await _create_user(db, plan="pro")
        await _seed_attribution(
            db,
            identity_id=identity_id,
            referrer_user_id=referrer_user_id,
            referred_user_id=referred_id,
            status="rejected",
            captured_at=now - timedelta(days=2),
            rejection_reason="outside_attribution_window",
            plan="pro",
        )

    referred_id, _ = await _create_user(db, plan="pro")
    await _seed_attribution(
        db,
        identity_id=identity_id,
        referrer_user_id=referrer_user_id,
        referred_user_id=referred_id,
        status="captured",
        captured_at=now - timedelta(days=2),
        plan="pro",
    )

    # Outside the default 30-day window; only a 90-day query includes it.
    referred_id, _ = await _create_user(db, plan="pro")
    old_capture = now - timedelta(days=60)
    await _seed_attribution(
        db,
        identity_id=identity_id,
        referrer_user_id=referrer_user_id,
        referred_user_id=referred_id,
        status="qualified",
        captured_at=old_capture,
        qualified_at=old_capture + timedelta(hours=6),
        plan="pro",
        payment_status="paid",
        reward_status="issued",
        reward_value=7,
        reward_issued_at=old_capture + timedelta(hours=6),
    )
    await db.commit()


class TestAdminReferralAnalyticsAccess:
    async def test_admin_only_and_filter_validation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _user_id, user_headers = await _create_user(db_session, role="user")
        denied = await client.get("/admin/referrals/summary", headers=user_headers)
        assert denied.status_code == 403

        _support_id, support_headers = await _create_user(db_session, role="support")
        support_denied = await client.get("/admin/referrals/summary", headers=support_headers)
        assert support_denied.status_code == 403

        anonymous = await client.get("/admin/referrals/summary")
        assert anonymous.status_code == 401

        admin = await _admin_headers(db_session)
        allowed = await client.get("/admin/referrals/summary", headers=admin)
        assert allowed.status_code == 200, allowed.text
        payload = allowed.json()
        assert payload["funnel"]["captured"] == 0
        assert payload["suppressed"] is False
        assert payload["minimum_users"] == 5

        bad_plan = await client.get(
            "/admin/referrals/summary", params={"plan": "not-a-plan"}, headers=admin
        )
        assert bad_plan.status_code == 422
        bad_range = await client.get(
            "/admin/referrals/summary",
            params={"start_date": "2026-03-01", "end_date": "2026-02-01"},
            headers=admin,
        )
        assert bad_range.status_code == 422


class TestAdminReferralAnalyticsAggregation:
    async def test_funnel_reconciliation_rewards_rejection_and_filters(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        referrer_id, _ = await _create_user(db_session)
        identity_id = await _seed_identity(db_session, referrer_id)
        await _seed_standard_cohort(
            db_session,
            referrer_user_id=referrer_id,
            identity_id=identity_id,
            now=_now(),
        )
        admin = await _admin_headers(db_session)

        response = await client.get(
            "/admin/referrals/summary",
            params={"days": 30, "plan": "pro"},
            headers=admin,
        )
        assert response.status_code == 200, response.text
        payload = response.json()

        funnel = payload["funnel"]
        assert funnel["captured"] == 17
        assert funnel["qualified"] == 11
        assert funnel["paid"] == 11
        assert funnel["currently_qualified"] == 10
        assert funnel["reversed"] == 1
        assert funnel["qualified_conversion_pct"] == 64.71
        assert funnel["paid_conversion_pct"] == 64.71
        assert funnel["paid_conversion_rate"] == funnel["paid_conversion_pct"]
        assert payload["totals"]["captured"] == 17
        assert payload["conversion"]["paid_conversion_rate"] == 64.71

        rewards = payload["reward_summary"]
        assert rewards["total_rewards"] == 11
        assert rewards["issued"] == 5
        assert rewards["pending"] == 5
        assert rewards["reversed"] == 1
        assert rewards["total_value_days"] == 77
        assert rewards["issued_value_days"] == 35
        assert rewards["pending_value_days"] == 35
        assert rewards["reversed_value_days"] == 7

        reasons = payload["rejection_reasons"]["items"]
        visible = {item["reason"]: item["count"] for item in reasons}
        assert visible["outside_attribution_window"] == 5
        assert "payment_refunded" not in visible  # one-user group suppressed
        assert payload["rejection_reasons"]["suppressed_reasons"] == 1

        timing = payload["time_to_qualify"]
        assert timing["sample_size"] == 11
        assert timing["median_hours"] == 6.0
        assert timing["average_hours"] == 6.0
        assert timing["median_days"] == 0.25
        assert {bucket["key"] for bucket in timing["buckets"]} == {"1_to_24_hours"}

        assert [row["plan"] for row in payload["by_plan"]] == ["pro"]
        assert payload["by_plan"][0]["captured"] == 17
        assert payload["by_plan"][0]["paid_conversion_pct"] == 64.71

        reconciliation = payload["reconciliation"]
        assert reconciliation["reconciled"] is True
        assert reconciliation["counts"]["source_attributions"] == 17
        assert reconciliation["counts"]["source_rewards"] == 11
        assert reconciliation["counts"]["reward_total"] == 11
        assert reconciliation["missing_payments"] == 0
        assert reconciliation["qualified_without_reward"] == 0

        # Plan filter that matches nothing is an honest empty cohort.
        free = await client.get(
            "/admin/referrals/summary",
            params={"days": 30, "plan": "free"},
            headers=admin,
        )
        assert free.status_code == 200, free.text
        assert free.json()["funnel"]["captured"] == 0
        assert free.json()["suppressed"] is False

        # The old row is outside 30 days but inside 90.
        wide = await client.get(
            "/admin/referrals/summary",
            params={"days": 90, "plan": "pro"},
            headers=admin,
        )
        assert wide.status_code == 200, wide.text
        wide_payload = wide.json()
        assert wide_payload["funnel"]["captured"] == 18
        assert wide_payload["funnel"]["qualified"] == 12
        assert wide_payload["reward_summary"]["issued"] == 6
        assert wide_payload["reconciliation"]["reconciled"] is True

        # Explicit date range uses the same capture-cohort semantics.
        today = _now().date()
        explicit = await client.get(
            "/admin/referrals/summary",
            params={
                "start_date": (today - timedelta(days=3)).isoformat(),
                "end_date": today.isoformat(),
                "plan": "pro",
            },
            headers=admin,
        )
        assert explicit.status_code == 200, explicit.text
        assert explicit.json()["funnel"]["captured"] == 17


class TestAdminReferralAnalyticsSuppression:
    async def test_five_user_suppression_and_hidden_breakdowns(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        referrer_id, _ = await _create_user(db_session)
        identity_id = await _seed_identity(db_session, referrer_id)
        admin = await _admin_headers(db_session)
        now = _now()

        for _ in range(4):
            referred_id, _ = await _create_user(db_session, plan="pro")
            await _seed_attribution(
                db_session,
                identity_id=identity_id,
                referrer_user_id=referrer_id,
                referred_user_id=referred_id,
                status="captured",
                captured_at=now - timedelta(days=1),
                plan="pro",
            )
        await db_session.commit()

        denied = await client.get(
            "/admin/referrals/summary", params={"days": 30}, headers=admin
        )
        assert denied.status_code == 200, denied.text
        payload = denied.json()
        assert payload["suppressed"] is True
        assert payload["suppression"]["applied"] is True
        assert payload["funnel"]["captured"] is None
        assert payload["funnel"]["paid_conversion_pct"] is None
        assert payload["reward_summary"]["total_rewards"] is None
        assert payload["by_plan"] == []
        assert payload["fraud_review"]["signals"] == []

        csv_response = await client.get(
            "/admin/referrals/summary", params={"days": 30, "format": "csv"}, headers=admin
        )
        assert csv_response.status_code == 200, csv_response.text
        csv_text = csv_response.text
        assert "suppression" in csv_text
        assert "captured" not in csv_text

        # Adding two pro users makes pro visible; three free users remain below
        # the floor, so only the pro breakdown row is emitted.
        for _ in range(2):
            referred_id, _ = await _create_user(db_session, plan="pro")
            await _seed_attribution(
                db_session,
                identity_id=identity_id,
                referrer_user_id=referrer_id,
                referred_user_id=referred_id,
                status="captured",
                captured_at=now - timedelta(days=1),
                plan="pro",
            )
        for _ in range(3):
            referred_id, _ = await _create_user(db_session, plan="free")
            await _seed_attribution(
                db_session,
                identity_id=identity_id,
                referrer_user_id=referrer_id,
                referred_user_id=referred_id,
                status="captured",
                captured_at=now - timedelta(days=1),
                plan="free",
            )
        await db_session.commit()

        visible = await client.get(
            "/admin/referrals/summary", params={"days": 30}, headers=admin
        )
        assert visible.status_code == 200, visible.text
        visible_payload = visible.json()
        assert visible_payload["suppressed"] is False
        assert visible_payload["funnel"]["captured"] == 9
        assert [row["plan"] for row in visible_payload["by_plan"]] == ["pro"]
        assert visible_payload["by_plan"][0]["captured"] == 6
        assert visible_payload["suppression"]["suppressed_groups"] >= 1


class TestAdminReferralAnalyticsPrivacy:
    async def test_csv_and_json_never_leak_referral_or_payment_secrets(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        referrer_id, _ = await _create_user(db_session)
        identity_id = await _seed_identity(db_session, referrer_id)
        identity_secrets = (
            await db_session.execute(
                text(
                    "SELECT code, code_digest FROM referral_identities WHERE id = :id"
                ),
                {"id": identity_id},
            )
        ).one()
        now = _now()
        for index in range(5):
            referred_id, _ = await _create_user(
                db_session,
                plan="pro",
                email=SECRET_EMAIL if index == 0 else None,
            )
            await _seed_attribution(
                db_session,
                identity_id=identity_id,
                referrer_user_id=referrer_id,
                referred_user_id=referred_id,
                status="qualified",
                captured_at=now - timedelta(days=1),
                qualified_at=now - timedelta(hours=12),
                plan="pro",
                payment_status="paid",
                reward_status="issued",
                reward_issued_at=now - timedelta(hours=12),
            )
        await db_session.commit()

        admin = await _admin_headers(db_session)
        response = await client.get(
            "/admin/referrals/summary", params={"days": 30}, headers=admin
        )
        assert response.status_code == 200, response.text
        body = response.text
        assert response.json()["privacy"]["aggregate_only"] is True
        assert response.json()["privacy"]["reads_consent_gated_analytics"] is False

        csv_response = await client.get(
            "/admin/referrals/summary/export.csv",
            params={"days": 30, "plan": "pro"},
            headers=admin,
        )
        assert csv_response.status_code == 200, csv_response.text
        assert csv_response.headers["content-type"].startswith("text/csv")
        assert "attachment;" in csv_response.headers["content-disposition"]
        csv_text = csv_response.text

        for secret in (
            identity_secrets.code,
            identity_secrets.code_digest,
            SECRET_EMAIL,
            SECRET_PROVIDER_PAYMENT_ID,
            SECRET_PAYMENT_METHOD,
            referrer_id,
        ):
            assert secret not in body
            assert secret not in csv_text

        rows = list(csv.DictReader(io.StringIO(csv_text)))
        captured = next(row for row in rows if row["key"] == "captured")
        assert captured["count"] == "5"
        assert all("email" not in (row["key"] or "") for row in rows)


class TestAdminReferralAnalyticsReasonAllowlist:
    async def test_unknown_free_form_reason_is_not_echoed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        referrer_id, _ = await _create_user(db_session)
        identity_id = await _seed_identity(db_session, referrer_id)
        now = _now()
        secret_value = f"{SECRET_EMAIL} BEARER-CODE-2066"
        for _ in range(5):
            referred_id, _ = await _create_user(db_session, plan="pro")
            await _seed_attribution(
                db_session,
                identity_id=identity_id,
                referrer_user_id=referrer_id,
                referred_user_id=referred_id,
                status="rejected",
                captured_at=now - timedelta(days=1),
                rejection_reason=secret_value,
                plan="pro",
            )
        await db_session.commit()

        admin = await _admin_headers(db_session)
        response = await client.get(
            "/admin/referrals/summary", params={"days": 30}, headers=admin
        )
        assert response.status_code == 200, response.text
        body = response.text
        assert SECRET_EMAIL not in body
        assert "BEARER-CODE-2066" not in body
        reasons = {item["reason"]: item["count"] for item in response.json()["rejection_reasons"]["items"]}
        assert reasons == {"other": 5}


class TestAdminReferralAnalyticsFraudReview:
    async def test_fraud_queue_is_aggregate_and_manual_only(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        now = _now()
        referrer_ids: list[str] = []
        for _ in range(5):
            referrer_id, _ = await _create_user(db_session)
            referrer_ids.append(referrer_id)
            identity_id = await _seed_identity(db_session, referrer_id)
            for _ in range(3):
                referred_id, _ = await _create_user(db_session, plan="pro")
                await _seed_attribution(
                    db_session,
                    identity_id=identity_id,
                    referrer_user_id=referrer_id,
                    referred_user_id=referred_id,
                    status="captured",
                    captured_at=now - timedelta(minutes=30),
                    plan="pro",
                )
        await db_session.commit()

        admin = await _admin_headers(db_session)
        response = await client.get(
            "/admin/referrals/summary", params={"days": 30}, headers=admin
        )
        assert response.status_code == 200, response.text
        payload = response.json()

        fraud = payload["fraud_review"]
        signals = {item["key"]: item for item in fraud["signals"]}
        assert signals["rapid_capture_burst"]["referrers"] == 5
        assert signals["rapid_capture_burst"]["captured"] == 15
        assert signals["rapid_capture_burst"]["suppressed"] is False
        assert payload["fraud_signals"][0]["key"] == "rapid_capture_burst"
        assert payload["fraud_review_queue"] == fraud["queue"]
        assert fraud["queue"]
        assert all(item["recommended_action"] == "manual_review" for item in fraud["queue"])
        assert all(item["automatic_action"] is False for item in fraud["queue"])
        assert payload["automation"]["automatic_payout"] is False
        assert payload["automation"]["automatic_punishment"] is False
        assert fraud["manual_review_required"] is True

        body = response.text
        for referrer_id in referrer_ids:
            assert referrer_id not in body
