"""Trial-to-paid cohort attribution regressions (issue #2108)."""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.services.trial_attribution_service import MIN_COHORT_SIZE

PREFIX = "ta_test_"
TRAFFIC_COOKIE = "latexy_traffic_visitor"


@pytest.fixture(autouse=True)
async def _clean_trial_attribution_rows(db_session: AsyncSession):
    """Isolate these tests from reruns without touching other suites' rows."""

    async def clean() -> None:
        await db_session.execute(
            text(
                "DELETE FROM trial_attributions WHERE trial_id IN ("
                "SELECT id FROM device_trials WHERE device_fingerprint LIKE :prefix)"
            ),
            {"prefix": f"{PREFIX}%"},
        )
        await db_session.execute(
            text("DELETE FROM device_trials WHERE device_fingerprint LIKE :prefix"),
            {"prefix": f"{PREFIX}%"},
        )
        await db_session.execute(
            text("DELETE FROM users WHERE email LIKE :email"),
            {"email": "test_trial_attr_%"},
        )
        await db_session.commit()

    await clean()
    yield
    await clean()


async def _create_user(
    db: AsyncSession,
    *,
    created_at: datetime | None = None,
    role: str = "user",
) -> str:
    user_id = str(uuid.uuid4())
    db.add(
        models.User(
            id=user_id,
            email=f"test_trial_attr_{user_id.replace('-', '')}@example.com",
            name="Trial Attribution User",
            role=role,
            email_verified=True,
            subscription_plan="free",
            subscription_status="inactive",
            trial_used=True,
            created_at=created_at or datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return user_id


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_trial_attr_{uuid.uuid4().hex}"
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc).replace(year=2099),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    admin_id = await _create_user(db, role="admin")
    return await _session_headers(db, admin_id)


def _fingerprint() -> str:
    return f"{PREFIX}{uuid.uuid4().hex}"


def _visitor() -> str:
    return str(uuid.uuid4())


async def _create_trial(
    db: AsyncSession,
    *,
    fingerprint: str,
    created_at: datetime,
    usage_count: int = 1,
) -> models.DeviceTrial:
    trial = models.DeviceTrial(
        device_fingerprint=fingerprint,
        usage_count=usage_count,
        blocked=False,
        created_at=created_at,
        last_used=created_at,
    )
    db.add(trial)
    await db.commit()
    await db.refresh(trial)
    return trial


async def _seed_subscription(
    db: AsyncSession,
    *,
    user_id: str,
    plan_id: str = "pro",
    status: str = "active",
    created_at: datetime,
) -> models.Subscription:
    subscription = models.Subscription(
        user_id=user_id,
        provider="dodo",
        provider_subscription_id=f"test_sub_{uuid.uuid4().hex}",
        plan_id=plan_id,
        status=status,
        created_at=created_at,
        current_period_start=created_at,
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    return subscription


async def _seed_attribution(
    db: AsyncSession,
    *,
    trial: models.DeviceTrial,
    source: str | None,
    user_id: str | None = None,
    subscription_id: str | None = None,
    plan_id: str | None = None,
    trial_started_at: datetime | None = None,
    signup_at: datetime | None = None,
    paid_at: datetime | None = None,
    consent_granted: bool = True,
) -> models.TrialAttribution:
    row = models.TrialAttribution(
        trial_id=trial.id,
        user_id=user_id,
        subscription_id=subscription_id,
        consent_granted=consent_granted,
        acquisition_source=source,
        acquisition_medium="cpc" if source else None,
        acquisition_campaign="launch" if source else None,
        landing_path="/pricing" if source else None,
        referrer_host="www.google.com" if source else None,
        plan_id=plan_id,
        trial_started_at=trial_started_at or trial.created_at,
        signup_at=signup_at,
        paid_at=paid_at,
    )
    db.add(row)
    await db.commit()
    return row


async def _seed_landing_row(
    db: AsyncSession,
    *,
    visitor_id: str,
    source: str,
    created_at: datetime | None = None,
) -> None:
    db.add(
        models.UsageAnalytics(
            action="traffic_landing",
            resource_type="traffic_source",
            event_metadata={
                "visitor_id": visitor_id,
                "session_id": str(uuid.uuid4()),
                "landing_path": "/pricing",
                "utm_source": source,
                "utm_medium": "cpc",
                "utm_campaign": "launch",
                "referrer_host": "www.google.com",
            },
            ip_address=None,
            user_agent=None,
            created_at=created_at or datetime.now(timezone.utc),
        )
    )
    await db.commit()


class TestTrialStartCapture:
    async def test_consented_landing_is_attached_to_anonymous_trial(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        fingerprint = _fingerprint()
        landing = await client.post(
            "/analytics/traffic/landing",
            json={
                "landing_path": "/pricing",
                "referrer": "https://www.google.com/search?q=latexy",
                "utm_source": "Google",
                "utm_medium": "cpc",
                "utm_campaign": "launch",
            },
        )
        assert landing.status_code == 202, landing.text

        response = await client.get(f"/public/trial-status?fingerprint={fingerprint}")
        assert response.status_code == 200, response.text

        row = (
            await db_session.execute(
                select(models.TrialAttribution)
                .join(
                    models.DeviceTrial,
                    models.DeviceTrial.id == models.TrialAttribution.trial_id,
                )
                .where(models.DeviceTrial.device_fingerprint == fingerprint)
            )
        ).scalar_one()
        assert row.user_id is None
        assert row.consent_granted is True
        assert row.acquisition_source == "google"
        assert row.acquisition_medium == "cpc"
        assert row.acquisition_campaign == "launch"
        assert row.referrer_host == "www.google.com"
        assert row.landing_path == "/pricing"

    async def test_trial_without_consented_landing_stays_unattributed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        fingerprint = _fingerprint()
        response = await client.get(f"/public/trial-status?fingerprint={fingerprint}")
        assert response.status_code == 200, response.text
        count = (
            await db_session.execute(
                select(func.count(models.TrialAttribution.id))
                .join(
                    models.DeviceTrial,
                    models.DeviceTrial.id == models.TrialAttribution.trial_id,
                )
                .where(models.DeviceTrial.device_fingerprint == fingerprint)
            )
        ).scalar_one()
        assert count == 0


class TestClaim:
    async def test_claim_links_user_and_existing_paid_subscription(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        trial_started = datetime(2020, 1, 5, 12, tzinfo=timezone.utc)
        signup_at = datetime(2020, 1, 10, 12, tzinfo=timezone.utc)
        paid_at = datetime(2020, 1, 12, 12, tzinfo=timezone.utc)
        fingerprint = _fingerprint()
        visitor = _visitor()
        trial = await _create_trial(
            db_session, fingerprint=fingerprint, created_at=trial_started
        )
        await _seed_landing_row(db_session, visitor_id=visitor, source="google")
        user_id = await _create_user(db_session, created_at=signup_at)
        subscription = await _seed_subscription(
            db_session, user_id=user_id, plan_id="pro", created_at=paid_at
        )
        headers = await _session_headers(db_session, user_id)
        client.cookies.set(TRAFFIC_COOKIE, visitor)

        response = await client.post(
            "/analytics/trial/claim",
            headers=headers,
            json={
                "device_fingerprint": fingerprint,
                "consent_granted": True,
            },
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["recorded"] is True
        assert body["source_recorded"] is True

        row = (
            await db_session.execute(
                select(models.TrialAttribution).where(
                    models.TrialAttribution.trial_id == trial.id
                )
            )
        ).scalar_one()
        assert row.user_id == user_id
        assert row.acquisition_source == "google"
        assert row.subscription_id == subscription.id
        assert row.plan_id == "pro"
        assert row.paid_at == paid_at
        assert row.signup_at == signup_at

        repeat = await client.post(
            "/analytics/trial/claim",
            headers=headers,
            json={
                "device_fingerprint": fingerprint,
                "consent_granted": True,
            },
        )
        assert repeat.status_code == 202
        assert repeat.json()["reason"] == "already_linked"

    async def test_late_paid_subscription_is_persisted_on_the_link(
        self, db_session: AsyncSession
    ):
        from app.services.trial_attribution_service import link_subscription_for_user

        trial_started = datetime(2020, 2, 1, 12, tzinfo=timezone.utc)
        signup_at = datetime(2020, 2, 2, 12, tzinfo=timezone.utc)
        paid_at = datetime(2020, 2, 9, 12, tzinfo=timezone.utc)
        fingerprint = _fingerprint()
        trial = await _create_trial(
            db_session, fingerprint=fingerprint, created_at=trial_started
        )
        user_id = await _create_user(db_session, created_at=signup_at)
        row = await _seed_attribution(
            db_session,
            trial=trial,
            source="google",
            user_id=user_id,
            signup_at=signup_at,
            trial_started_at=trial_started,
        )
        subscription = await _seed_subscription(
            db_session, user_id=user_id, plan_id="pro", created_at=paid_at
        )

        linked = await link_subscription_for_user(
            db_session,
            user_id=user_id,
            subscription_id=subscription.id,
            plan_id=subscription.plan_id,
            paid_at=paid_at,
        )
        assert linked is True
        await db_session.refresh(row)
        assert row.subscription_id == subscription.id
        assert row.plan_id == "pro"
        assert row.paid_at == paid_at

        repeated = await link_subscription_for_user(
            db_session,
            user_id=user_id,
            subscription_id=subscription.id,
            plan_id="pro",
            paid_at=paid_at,
        )
        assert repeated is False

    async def test_claim_without_consent_records_no_linkage(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        trial_started = datetime(2020, 1, 5, 12, tzinfo=timezone.utc)
        fingerprint = _fingerprint()
        visitor = _visitor()
        trial = await _create_trial(
            db_session, fingerprint=fingerprint, created_at=trial_started
        )
        await _seed_landing_row(
            db_session, visitor_id=visitor, source="google", created_at=trial_started
        )
        user_id = await _create_user(db_session, created_at=trial_started)
        headers = await _session_headers(db_session, user_id)
        client.cookies.set(TRAFFIC_COOKIE, visitor)

        response = await client.post(
            "/analytics/trial/claim",
            headers=headers,
            json={
                "device_fingerprint": fingerprint,
                "consent_granted": False,
            },
        )
        assert response.status_code == 202, response.text
        assert response.json() == {"recorded": False, "reason": "consent_required"}

        row = (
            await db_session.execute(
                select(models.TrialAttribution).where(
                    models.TrialAttribution.trial_id == trial.id
                )
            )
        ).scalar_one_or_none()
        assert row is None


class TestAdminCohort:
    async def _seed_google_cohort(
        self,
        db: AsyncSession,
        *,
        base: datetime,
        paid_offsets: list[int],
    ) -> list[str]:
        from datetime import timedelta

        user_ids: list[str] = []
        for index in range(MIN_COHORT_SIZE):
            trial_started = base + timedelta(days=index)
            trial = await _create_trial(
                db=db,
                fingerprint=_fingerprint(),
                created_at=trial_started,
            )
            offset = paid_offsets[index]
            signup_at = trial_started + timedelta(days=1)
            paid_at = trial_started + timedelta(days=offset)
            user_id = await _create_user(db, created_at=signup_at)
            subscription = await _seed_subscription(
                db, user_id=user_id, plan_id="pro", created_at=paid_at
            )
            await _seed_attribution(
                db,
                trial=trial,
                source="google",
                user_id=user_id,
                subscription_id=subscription.id,
                plan_id="pro",
                signup_at=signup_at,
                paid_at=paid_at,
            )
            user_ids.append(user_id)

        # Anonymous trials with the same consented source prove the cohort
        # denominator is trial starts, not just signed-up accounts.
        for index in range(MIN_COHORT_SIZE):
            trial_started = base + timedelta(days=index, hours=6)
            trial = await _create_trial(
                db=db,
                fingerprint=_fingerprint(),
                created_at=trial_started,
            )
            await _seed_attribution(
                db, trial=trial, source="google", trial_started_at=trial_started
            )
        return user_ids

    async def test_cohorts_windows_reconcile_and_hide_small_cells(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from datetime import timedelta

        headers = await _admin_headers(db_session)
        base = datetime(2020, 6, 1, 12, tzinfo=timezone.utc)
        user_ids = await self._seed_google_cohort(
            db_session, base=base, paid_offsets=[1, 5, 10, 40, 100]
        )
        assert len(user_ids) == MIN_COHORT_SIZE

        # A second, visible source with no signups must show zero rather than
        # disappearing or being treated as a 1-4 user cell.
        for index in range(MIN_COHORT_SIZE):
            trial_started = base + timedelta(days=index, hours=12)
            trial = await _create_trial(
                db=db_session,
                fingerprint=_fingerprint(),
                created_at=trial_started,
            )
            await _seed_attribution(
                db_session, trial=trial, source="direct", trial_started_at=trial_started
            )

        response = await client.get(
            "/admin/analytics/trial-attribution"
            "?start_date=2020-06-01&end_date=2020-12-31",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["minimum_cohort_size"] == MIN_COHORT_SIZE
        assert body["conversion_windows_days"] == [7, 30, 90]
        assert body["totals"]["trial_starts"] == 15
        assert body["totals"]["linked_trials"] == MIN_COHORT_SIZE
        assert body["totals"]["signups"] == MIN_COHORT_SIZE
        assert body["totals"]["paid_users"] == MIN_COHORT_SIZE
        assert body["totals"]["source_attributed_trials"] == 15
        assert body["totals"]["paid_within_7d"] == 2
        assert body["totals"]["paid_within_30d"] == 3
        assert body["totals"]["paid_within_90d"] == 4

        google = next(row for row in body["by_source"] if row["label"] == "google")
        assert google["trial_starts"] == 10
        assert google["signups"] == MIN_COHORT_SIZE
        assert google["paid_users"] == MIN_COHORT_SIZE
        assert google["trial_to_paid_pct"] == 50.0
        assert google["median_days_to_signup"] == 1.0
        assert google["median_days_to_paid"] == 10.0
        assert google["paid_within_7d"] == 2
        assert google["paid_within_30d"] == 3
        assert google["paid_within_90d"] == 4

        direct = next(row for row in body["by_source"] if row["label"] == "direct")
        assert direct["trial_starts"] == MIN_COHORT_SIZE
        assert direct["signups"] == 0
        assert direct["paid_users"] == 0
        assert direct["trial_to_paid_pct"] == 0.0

        plan = next(row for row in body["by_plan"] if row["label"] == "pro")
        assert plan["trial_starts"] == MIN_COHORT_SIZE
        assert plan["signups"] == MIN_COHORT_SIZE
        assert plan["paid_users"] == MIN_COHORT_SIZE
        month = next(row for row in body["by_signup_month"] if row["label"] == "2020-06")
        assert month["trial_starts"] == MIN_COHORT_SIZE

        reconciliation = body["reconciliation"]
        assert reconciliation["period_trial_starts"] == 15
        assert reconciliation["linked_trials"] == MIN_COHORT_SIZE
        assert reconciliation["anonymous_trials"] == 10
        assert reconciliation["cohort_signups"] == MIN_COHORT_SIZE
        assert reconciliation["cohort_paid_users"] == MIN_COHORT_SIZE
        assert reconciliation["period_signups"] == MIN_COHORT_SIZE
        assert reconciliation["period_paid_subscriptions"] == MIN_COHORT_SIZE
        assert reconciliation["period_paid_users"] == MIN_COHORT_SIZE
        assert reconciliation["unattributed_signups"] == 0
        assert reconciliation["unattributed_paid_users"] == 0

        serialized = json.dumps(body).lower()
        assert PREFIX not in serialized
        assert "@example.com" not in serialized
        assert "ip_address" not in serialized
        assert "device_fingerprint" not in serialized
        assert "user_agent" not in serialized
        assert "test_trial_attr_" not in serialized

    async def test_small_cohorts_and_small_cells_are_suppressed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from datetime import timedelta

        headers = await _admin_headers(db_session)
        base = datetime(2021, 3, 1, 12, tzinfo=timezone.utc)

        # Five trials is enough to show the cohort, but only two signups is a
        # 1-4 user cell and must be nulled.
        for index in range(MIN_COHORT_SIZE):
            trial_started = base + timedelta(days=index)
            trial = await _create_trial(
                db=db_session,
                fingerprint=_fingerprint(),
                created_at=trial_started,
            )
            user_id = None
            if index < 2:
                user_id = await _create_user(
                    db_session, created_at=trial_started + timedelta(days=1)
                )
            await _seed_attribution(
                db_session,
                trial=trial,
                source="visible",
                user_id=user_id,
                signup_at=(
                    trial_started + timedelta(days=1) if user_id is not None else None
                ),
                trial_started_at=trial_started,
            )

        for index in range(MIN_COHORT_SIZE - 1):
            trial_started = base + timedelta(days=index, hours=6)
            trial = await _create_trial(
                db=db_session,
                fingerprint=_fingerprint(),
                created_at=trial_started,
            )
            await _seed_attribution(
                db_session,
                trial=trial,
                source="tiny",
                trial_started_at=trial_started,
            )

        response = await client.get(
            "/admin/analytics/trial-attribution"
            "?start_date=2021-03-01&end_date=2021-03-31",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()

        labels = {row["label"] for row in body["by_source"]}
        assert "visible" in labels
        assert "tiny" not in labels
        assert body["suppressed"]["source"] >= 1

        visible = next(row for row in body["by_source"] if row["label"] == "visible")
        assert visible["trial_starts"] == MIN_COHORT_SIZE
        assert visible["signups"] is None
        assert visible["trial_to_signup_pct"] is None
        assert "signups" in visible["suppressed_cells"]

    async def test_deleted_users_become_anonymous_without_retained_identity(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from datetime import timedelta

        headers = await _admin_headers(db_session)
        base = datetime(2022, 1, 3, 12, tzinfo=timezone.utc)
        user_ids: list[str] = []
        for index in range(MIN_COHORT_SIZE):
            trial_started = base + timedelta(days=index)
            trial = await _create_trial(
                db=db_session,
                fingerprint=_fingerprint(),
                created_at=trial_started,
            )
            user_id = await _create_user(
                db_session, created_at=trial_started + timedelta(days=1)
            )
            subscription = await _seed_subscription(
                db_session,
                user_id=user_id,
                plan_id="pro",
                created_at=trial_started + timedelta(days=2),
            )
            await _seed_attribution(
                db_session,
                trial=trial,
                source="deleted-source",
                user_id=user_id,
                subscription_id=subscription.id,
                plan_id="pro",
                signup_at=trial_started + timedelta(days=1),
                paid_at=trial_started + timedelta(days=2),
            )
            user_ids.append(user_id)

        await db_session.execute(
            text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids}
        )
        await db_session.commit()

        linked = (
            await db_session.execute(
                select(func.count(models.TrialAttribution.id)).where(
                    models.TrialAttribution.user_id.is_not(None)
                )
            )
        ).scalar_one()
        assert linked == 0

        response = await client.get(
            "/admin/analytics/trial-attribution"
            "?start_date=2022-01-01&end_date=2022-01-31",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["totals"]["trial_starts"] == MIN_COHORT_SIZE
        assert body["totals"]["linked_trials"] == 0
        assert body["totals"]["unlinked_trials"] == MIN_COHORT_SIZE
        assert body["totals"]["source_attributed_trials"] == 0
        assert body["reconciliation"]["anonymous_trials"] == MIN_COHORT_SIZE
        assert body["reconciliation"]["deleted_user_attributions"] == 0
        assert body["by_source"] == []

        serialized = json.dumps(body).lower()
        for user_id in user_ids:
            assert user_id not in serialized
        assert "@example.com" not in serialized
        assert PREFIX not in serialized

    async def test_admin_cohort_requires_admin(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id = await _create_user(db_session)
        headers = await _session_headers(db_session, user_id)
        forbidden = await client.get(
            "/admin/analytics/trial-attribution", headers=headers
        )
        assert forbidden.status_code == 403

        anonymous = await client.get("/admin/analytics/trial-attribution")
        assert anonymous.status_code == 401


def test_trial_attribution_migration_declares_isolated_revision():
    """Our migration must not assert or depend on a repository-wide head."""

    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0084_trial_attribution.py"
    )
    spec = importlib.util.spec_from_file_location(
        "trial_attribution_migration", path
    )
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    assert migration.revision == "0084_trial_attribution"
    assert migration.down_revision == "0082_signup_funnel_providers"
