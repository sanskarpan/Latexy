"""Team-seat utilization and invite-to-active analytics (issue #2110).

Covers status reconciliation, conversion rates, aging invites, median accept
time, utilization versus the team plan cap, owner/tenant/date filters, tenant
isolation, five-seat suppression, privacy and admin-only access. The report must
work on the existing schema without applying a migration.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ENDPOINT = "/admin/analytics/team-seats"
TEAM_SEAT_CAP = 5


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "team",
    status: str = "active",
) -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Team Seat Test User', :role, true, :plan, :status, false)"
        ),
        {
            "id": user_id,
            "email": f"test_teamseat_{user_id.replace('-', '')}@example.com",
            "role": role,
            "plan": plan,
            "status": status,
        },
    )
    await db.commit()
    return user_id


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_teamseat_sess_{uuid.uuid4().hex}"
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
    return {"Authorization": f"Bearer {token}"}


class SeatSeed:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_ids: list[str] = []
        self.tenant_ids: list[str] = []
        self.invitee_emails: list[str] = []
        self.member_user_ids: list[str] = []

    async def user(
        self,
        *,
        role: str = "user",
        plan: str = "team",
        status: str = "active",
    ) -> str:
        user_id = await _create_user(self.db, role=role, plan=plan, status=status)
        self.user_ids.append(user_id)
        return user_id

    async def admin_headers(self) -> dict[str, str]:
        admin_id = await self.user(role="admin", plan="free")
        return await _session_headers(self.db, admin_id)

    async def tenant(
        self,
        owner_id: str,
        *,
        name: str,
        max_members: int = 50,
        plan_id: str = "agency",
    ) -> str:
        tenant_id = str(uuid.uuid4())
        await self.db.execute(
            text(
                "INSERT INTO tenants (id, slug, name, owner_id, plan_id, max_members, active) "
                "VALUES (:id, :slug, :name, :owner, :plan, :cap, true)"
            ),
            {
                "id": tenant_id,
                "slug": f"test-teamseat-{tenant_id[:12]}",
                "name": name,
                "owner": owner_id,
                "plan": plan_id,
                "cap": max_members,
            },
        )
        await self.db.execute(
            text("INSERT INTO tenant_members (tenant_id, user_id, role) VALUES (:tid, :uid, 'admin')"),
            {"tid": tenant_id, "uid": owner_id},
        )
        await self.db.commit()
        self.tenant_ids.append(tenant_id)
        return tenant_id

    async def tenant_member(self, tenant_id: str, user_id: str) -> None:
        await self.db.execute(
            text("INSERT INTO tenant_members (tenant_id, user_id, role) VALUES (:tid, :uid, 'member')"),
            {"tid": tenant_id, "uid": user_id},
        )
        await self.db.commit()

    async def subscription(
        self,
        owner_id: str,
        *,
        plan_id: str = "team",
        status: str = "active",
    ) -> str:
        subscription_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await self.db.execute(
            text(
                "INSERT INTO subscriptions (id, user_id, provider, plan_id, status, "
                "current_period_start, current_period_end, created_at, updated_at) "
                "VALUES (:id, :uid, 'test', :plan, :status, :start, :end, :created, :updated)"
            ),
            {
                "id": subscription_id,
                "uid": owner_id,
                "plan": plan_id,
                "status": status,
                "start": now - timedelta(days=1),
                "end": now + timedelta(days=30),
                "created": now,
                "updated": now,
            },
        )
        await self.db.commit()
        return subscription_id

    async def seat(
        self,
        owner_id: str,
        *,
        status: str = "active",
        invited_days_ago: float = 5,
        accept_hours: float | None = None,
        invitee_email: str | None = None,
        member_user_id: str | None = None,
    ) -> str:
        seat_id = str(uuid.uuid4())
        invited_at = datetime.now(timezone.utc) - timedelta(days=invited_days_ago)
        joined_at = invited_at + timedelta(hours=accept_hours) if accept_hours is not None else None
        email = invitee_email or f"test_teamseat_invitee_{seat_id.replace('-', '')}@example.com"
        self.invitee_emails.append(email)
        if member_user_id is not None:
            self.member_user_ids.append(member_user_id)
        await self.db.execute(
            text(
                "INSERT INTO team_seats "
                "(id, owner_user_id, member_email, member_user_id, status, invited_at, joined_at, created_at) "
                "VALUES (:id, :owner, :email, :member, :status, :invited, :joined, :created)"
            ),
            {
                "id": seat_id,
                "owner": owner_id,
                "email": email,
                "member": member_user_id,
                "status": status,
                "invited": invited_at,
                "joined": joined_at,
                "created": invited_at,
            },
        )
        await self.db.commit()
        return seat_id

    async def cleanup(self) -> None:
        # A failed insert can leave the shared test session in an aborted
        # transaction; roll back so cleanup still removes this test's rows.
        try:
            await self.db.rollback()
        except Exception:
            pass
        await self.db.execute(text("DELETE FROM session WHERE token LIKE 'test_teamseat_sess_%'"))
        if self.user_ids:
            await self.db.execute(
                text("DELETE FROM team_seats WHERE owner_user_id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": self.user_ids},
            )
            await self.db.execute(
                text("DELETE FROM subscriptions WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": self.user_ids},
            )
        if self.tenant_ids:
            await self.db.execute(
                text("DELETE FROM tenant_members WHERE tenant_id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": self.tenant_ids},
            )
            await self.db.execute(
                text("DELETE FROM tenants WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": self.tenant_ids},
            )
        if self.user_ids:
            await self.db.execute(
                text("DELETE FROM users WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": self.user_ids},
            )
        await self.db.commit()


@pytest.fixture
async def seat_seed(db_session: AsyncSession):
    seed = SeatSeed(db_session)
    yield seed
    await seed.cleanup()


async def _report(
    client: AsyncClient,
    headers: dict[str, str],
    **params: object,
) -> dict:
    response = await client.get(ENDPOINT, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _owner_report(
    client: AsyncClient,
    headers: dict[str, str],
    owner_id: str,
    **params: object,
) -> dict:
    return await _report(client, headers, owner_id=owner_id, **params)


def _assert_no_invitee_identity(body: dict, seed: SeatSeed) -> None:
    serialized = json.dumps(body)
    for email in seed.invitee_emails:
        assert email not in serialized
    for member_id in seed.member_user_ids:
        assert member_id not in serialized
    assert '"member_email":' not in serialized
    assert '"member_user_id":' not in serialized
    assert "invite_token" not in serialized


class TestAccessAndValidation:
    async def test_endpoint_is_admin_only(self, client: AsyncClient, db_session: AsyncSession, seat_seed: SeatSeed):
        owner_id = await seat_seed.user()
        for index in range(5):
            await seat_seed.seat(owner_id, invited_days_ago=index + 1, accept_hours=1)

        unauthenticated = await client.get(ENDPOINT, params={"owner_id": owner_id})
        assert unauthenticated.status_code == 401

        member_headers = await _session_headers(db_session, await seat_seed.user(plan="free"))
        forbidden = await client.get(ENDPOINT, params={"owner_id": owner_id}, headers=member_headers)
        assert forbidden.status_code == 403

        support_headers = await _session_headers(db_session, await seat_seed.user(role="support", plan="free"))
        support_forbidden = await client.get(ENDPOINT, params={"owner_id": owner_id}, headers=support_headers)
        assert support_forbidden.status_code == 403

        admin_headers = await seat_seed.admin_headers()
        allowed = await client.get(ENDPOINT, params={"owner_id": owner_id}, headers=admin_headers)
        assert allowed.status_code == 200

    async def test_invalid_filters_return_422(self, client: AsyncClient, seat_seed: SeatSeed):
        headers = await seat_seed.admin_headers()
        invalid_owner = await client.get(ENDPOINT, params={"owner_id": "not-a-uuid"}, headers=headers)
        assert invalid_owner.status_code == 422
        invalid_tenant = await client.get(ENDPOINT, params={"tenant_id": "not-a-uuid"}, headers=headers)
        assert invalid_tenant.status_code == 422
        unknown_tenant = await client.get(
            ENDPOINT,
            params={"tenant_id": str(uuid.uuid4())},
            headers=headers,
        )
        assert unknown_tenant.status_code == 422
        reversed_range = await client.get(
            ENDPOINT,
            params={"start_date": "2026-02-02", "end_date": "2026-02-01"},
            headers=headers,
        )
        assert reversed_range.status_code == 422


class TestSeatReconciliation:
    async def test_status_counts_rates_and_capacity_reconcile(
        self, client: AsyncClient, db_session: AsyncSession, seat_seed: SeatSeed
    ):
        owner_id = await seat_seed.user(plan="team")
        await seat_seed.subscription(owner_id, plan_id="team", status="active")
        # 3 active (2 accepted + 1 accepted), 1 pending, 1 removed (accepted).
        await seat_seed.seat(owner_id, status="active", invited_days_ago=4, accept_hours=2)
        await seat_seed.seat(owner_id, status="active", invited_days_ago=3, accept_hours=4)
        await seat_seed.seat(owner_id, status="active", invited_days_ago=2, accept_hours=6)
        await seat_seed.seat(owner_id, status="invited", invited_days_ago=1)
        await seat_seed.seat(
            owner_id,
            status="removed",
            invited_days_ago=6,
            accept_hours=8,
        )

        headers = await seat_seed.admin_headers()
        body = await _owner_report(client, headers, owner_id, days=30)

        current = body["summary"]["current"]
        assert current["owners"] == 1
        assert current["seats"] == 5
        assert current["accepted_ever"] == 4
        assert current["active"] == 3
        assert current["pending"] == 1
        assert current["removed"] == 1
        assert current["other"] == 0
        assert current["seat_cap"] == TEAM_SEAT_CAP
        assert current["seat_capacity"] == TEAM_SEAT_CAP
        assert current["utilization_pct"] == 60.0
        assert current["over_capacity"] == 0
        assert current["at_or_over_cap"] is False

        invitations = body["summary"]["invitations"]
        assert invitations["invited"] == 5
        assert invitations["accepted_ever"] == 4
        assert invitations["active_now"] == 3
        assert invitations["pending_now"] == 1
        assert invitations["removed_now"] == 1
        assert invitations["invite_to_accept_pct"] == 80.0
        assert invitations["invite_to_active_pct"] == 60.0
        # Four accepted samples is below the five-seat publication floor.
        assert invitations["accept_samples"] == 4
        assert invitations["median_accept_hours"] is None
        assert invitations["median_accept_suppressed"] is True

        assert body["summary"]["team_plan_owners"] == 1
        assert body["summary"]["owners_at_or_over_cap"] == 0
        assert len(body["owners"]) == 1
        owner = body["owners"][0]
        assert owner["owner_user_id"] == owner_id
        assert owner["team_plan_active"] is True
        assert owner["subscription"]["plan_id"] == "team"
        assert owner["current"] == current
        assert owner["invitations"] == invitations

        reconciled = body["reconciliation"]
        assert reconciled["all_checks_passed"] is True
        assert reconciled["seats_scanned"] == 5
        assert reconciled["seats_after_filters"] == 5
        assert reconciled["unassigned_seats"] == 5
        assert reconciled["tenant_attributed_seats"] == 0
        assert reconciled["rows_truncated"] is False

        grouped = (
            await db_session.execute(
                text("SELECT status, count(*) FROM team_seats WHERE owner_user_id = :owner GROUP BY status"),
                {"owner": owner_id},
            )
        ).all()
        assert dict(grouped) == {"active": 3, "invited": 1, "removed": 1}

    async def test_at_cap_and_over_cap_utilization(self, client: AsyncClient, seat_seed: SeatSeed):
        at_cap_owner = await seat_seed.user(plan="team")
        over_cap_owner = await seat_seed.user(plan="team")
        for index in range(5):
            await seat_seed.seat(at_cap_owner, invited_days_ago=index + 1, accept_hours=1)
        for index in range(6):
            await seat_seed.seat(over_cap_owner, invited_days_ago=index + 1, accept_hours=1)

        headers = await seat_seed.admin_headers()
        at_cap = await _owner_report(client, headers, at_cap_owner)
        over_cap = await _owner_report(client, headers, over_cap_owner)

        assert at_cap["summary"]["current"]["utilization_pct"] == 100.0
        assert at_cap["summary"]["current"]["at_or_over_cap"] is True
        assert at_cap["summary"]["owners_at_or_over_cap"] == 1
        assert over_cap["summary"]["current"]["utilization_pct"] == 120.0
        assert over_cap["summary"]["current"]["over_capacity"] == 1
        assert over_cap["summary"]["current"]["active"] == 6


class TestInviteAging:
    async def test_stale_pending_invites_are_bucketed_and_oldest_is_visible(
        self, client: AsyncClient, seat_seed: SeatSeed
    ):
        owner_id = await seat_seed.user(plan="team")
        for age in (2, 8, 15, 31, 45):
            await seat_seed.seat(owner_id, status="invited", invited_days_ago=age)

        headers = await seat_seed.admin_headers()
        body = await _owner_report(client, headers, owner_id, days=30)

        current = body["summary"]["current"]
        aging = current["aging_invites"]
        assert current["pending"] == 5
        assert aging["pending"] == 5
        assert aging["over_7_days"] == 4
        assert aging["over_14_days"] == 3
        assert aging["over_30_days"] == 2
        assert aging["oldest_pending_days"] >= 45
        assert body["owners"][0]["current"]["aging_invites"] == aging


class TestMedianAcceptTime:
    async def test_median_accept_time_uses_accepted_seats_in_the_window(self, client: AsyncClient, seat_seed: SeatSeed):
        owner_id = await seat_seed.user(plan="team")
        for hours in (2, 4, 6, 8, 10):
            await seat_seed.seat(
                owner_id,
                status="active",
                invited_days_ago=10,
                accept_hours=hours,
            )

        headers = await seat_seed.admin_headers()
        body = await _owner_report(client, headers, owner_id, days=30)

        invitations = body["summary"]["invitations"]
        assert invitations["invited"] == 5
        assert invitations["accepted_ever"] == 5
        assert invitations["accept_samples"] == 5
        assert invitations["median_accept_hours"] == 6.0
        assert invitations["median_accept_suppressed"] is False
        assert body["owners"][0]["invitations"]["median_accept_hours"] == 6.0

    async def test_date_filter_limits_the_invitation_cohort_not_current_seats(
        self, client: AsyncClient, seat_seed: SeatSeed
    ):
        owner_id = await seat_seed.user(plan="team")
        for hours in (1, 2, 3, 4, 5):
            await seat_seed.seat(
                owner_id,
                status="active",
                invited_days_ago=5,
                accept_hours=hours,
            )
        # One older active seat stays visible in current utilization but is
        # outside a seven-day invitation window.
        await seat_seed.seat(
            owner_id,
            status="active",
            invited_days_ago=60,
            accept_hours=1,
        )

        headers = await seat_seed.admin_headers()
        all_time = await _owner_report(client, headers, owner_id, days=90)
        recent = await _owner_report(client, headers, owner_id, days=7)

        assert all_time["summary"]["current"]["seats"] == 6
        assert all_time["summary"]["invitations"]["invited"] == 6
        assert all_time["summary"]["current"]["active"] == 6

        assert recent["summary"]["current"]["seats"] == 6
        assert recent["summary"]["current"]["active"] == 6
        assert recent["summary"]["invitations"]["invited"] == 5
        assert recent["summary"]["invitations"]["accept_samples"] == 5
        assert recent["summary"]["invitations"]["median_accept_hours"] == 3.0


class TestTenantIsolationAndFilters:
    async def test_tenant_filter_never_returns_another_tenants_seats(self, client: AsyncClient, seat_seed: SeatSeed):
        owner_a = await seat_seed.user(plan="team")
        owner_b = await seat_seed.user(plan="team")
        unassigned = await seat_seed.user(plan="team")
        tenant_a = await seat_seed.tenant(owner_a, name="Tenant Alpha")
        tenant_b = await seat_seed.tenant(owner_b, name="Tenant Beta")

        for index in range(5):
            await seat_seed.seat(owner_a, invited_days_ago=index + 1, accept_hours=1)
            await seat_seed.seat(owner_b, invited_days_ago=index + 1, accept_hours=2)
        for index in range(5):
            await seat_seed.seat(unassigned, invited_days_ago=index + 1, accept_hours=3)

        headers = await seat_seed.admin_headers()
        body_a = await _report(client, headers, tenant_id=tenant_a)
        body_b = await _report(client, headers, tenant_id=tenant_b)

        assert [row["owner_user_id"] for row in body_a["owners"]] == [owner_a]
        assert [row["tenant_id"] for row in body_a["tenants"]] == [tenant_a]
        assert body_a["summary"]["current"]["active"] == 5
        assert body_a["summary"]["current"]["seats"] == 5
        assert body_a["filters"]["tenant_name"] == "Tenant Alpha"

        serialized_a = json.dumps(body_a)
        assert "Tenant Beta" not in serialized_a
        assert owner_b not in serialized_a
        assert unassigned not in serialized_a

        assert [row["owner_user_id"] for row in body_b["owners"]] == [owner_b]
        assert [row["tenant_id"] for row in body_b["tenants"]] == [tenant_b]
        assert body_b["summary"]["current"]["active"] == 5
        serialized_b = json.dumps(body_b)
        assert "Tenant Alpha" not in serialized_b
        assert owner_a not in serialized_b
        assert unassigned not in serialized_b

    async def test_owner_filter_is_strict(self, client: AsyncClient, seat_seed: SeatSeed):
        owner_a = await seat_seed.user(plan="team")
        owner_b = await seat_seed.user(plan="team")
        for index in range(5):
            await seat_seed.seat(owner_a, invited_days_ago=index + 1, accept_hours=1)
            await seat_seed.seat(owner_b, invited_days_ago=index + 1, accept_hours=2)

        headers = await seat_seed.admin_headers()
        body = await _owner_report(client, headers, owner_a)
        assert [row["owner_user_id"] for row in body["owners"]] == [owner_a]
        serialized = json.dumps(body)
        assert owner_b not in serialized
        assert body["summary"]["current"]["seats"] == 5


class TestSuppressionAndPrivacy:
    async def test_owner_below_five_seats_is_withheld(self, client: AsyncClient, seat_seed: SeatSeed):
        small_owner = await seat_seed.user(plan="team")
        for index in range(4):
            await seat_seed.seat(small_owner, invited_days_ago=index + 1, accept_hours=1)

        headers = await seat_seed.admin_headers()
        body = await _owner_report(client, headers, small_owner)

        assert body["summary"]["current"] is None
        assert body["summary"]["invitations"] is None
        assert body["owners"] == []
        assert body["suppression"]["summary_suppressed"] is True
        assert body["suppression"]["suppressed_owner_rows"] == 1
        assert body["suppressed"] is True

    async def test_invitation_section_below_five_is_suppressed_but_current_remains(
        self, client: AsyncClient, seat_seed: SeatSeed
    ):
        owner_id = await seat_seed.user(plan="team")
        # Five currently active seats: four invited in the last week and one
        # legacy seat outside the thirty-day invitation window.
        for index in range(4):
            await seat_seed.seat(
                owner_id,
                status="active",
                invited_days_ago=index + 1,
                accept_hours=1,
            )
        await seat_seed.seat(
            owner_id,
            status="active",
            invited_days_ago=60,
            accept_hours=1,
        )

        headers = await seat_seed.admin_headers()
        body = await _owner_report(client, headers, owner_id, days=30)

        assert body["summary"]["current"]["seats"] == 5
        assert body["summary"]["current"]["active"] == 5
        assert body["summary"]["invitations"] is None
        assert body["suppression"]["invitation_section_suppressed"] is True
        assert body["owners"][0]["invitations"] is None
        assert body["owners"][0]["invitation_suppressed"] is True

        wider = await _owner_report(client, headers, owner_id, days=90)
        assert wider["summary"]["invitations"]["invited"] == 5

    async def test_tenant_row_is_withheld_when_seats_and_members_are_small(
        self, client: AsyncClient, seat_seed: SeatSeed
    ):
        owner_id = await seat_seed.user(plan="team")
        tenant_id = await seat_seed.tenant(owner_id, name="Tiny Tenant", max_members=50)
        for index in range(4):
            await seat_seed.seat(owner_id, invited_days_ago=index + 1, accept_hours=1)
        # Tenant owner membership plus one member keeps the member cohort at
        # two, also below the publication floor.
        await seat_seed.tenant_member(tenant_id, await seat_seed.user(plan="free"))

        headers = await seat_seed.admin_headers()
        body = await _report(client, headers, tenant_id=tenant_id)

        assert body["tenants"] == []
        assert body["suppression"]["suppressed_tenant_rows"] == 1
        assert body["summary"]["current"] is None

    async def test_response_never_contains_invitee_email_or_member_id(self, client: AsyncClient, seat_seed: SeatSeed):
        owner_id = await seat_seed.user(plan="team")
        member_id = await seat_seed.user(plan="free")
        for index in range(5):
            await seat_seed.seat(
                owner_id,
                status="active",
                invited_days_ago=index + 1,
                accept_hours=1,
                invitee_email=f"test_teamseat_secret_{index}@example.com",
                member_user_id=member_id if index == 0 else None,
            )

        headers = await seat_seed.admin_headers()
        body = await _owner_report(client, headers, owner_id)

        _assert_no_invitee_identity(body, seat_seed)
        assert body["privacy"]["invitee_emails_included"] is False
        assert body["privacy"]["invitee_user_ids_included"] is False
        assert body["privacy"]["aggregate_only"] is True
        assert "team_seats.member_email" in body["privacy"]["fields_excluded"]
        assert "team_seats.member_user_id" in body["privacy"]["fields_excluded"]

    async def test_report_uses_existing_schema_without_applying_a_migration(
        self, client: AsyncClient, db_session: AsyncSession, seat_seed: SeatSeed
    ):
        owner_id = await seat_seed.user(plan="team")
        for index in range(5):
            await seat_seed.seat(owner_id, invited_days_ago=index + 1, accept_hours=1)

        before = (await db_session.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        headers = await seat_seed.admin_headers()
        body = await _owner_report(client, headers, owner_id)
        after = (await db_session.execute(text("SELECT version_num FROM alembic_version"))).scalar()

        assert after == before
        assert body["reconciliation"]["source_tables"] == [
            "team_seats",
            "users",
            "subscriptions",
            "tenants",
            "tenant_members",
        ]
        assert body["reconciliation"]["all_checks_passed"] is True
