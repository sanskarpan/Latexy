"""Linter rule frequency and fix-rate telemetry (issue #2148).

Covers payload redaction, rule-id allowlisting, batch deduplication, aggregate
frequency/fix-rate/trend reporting, five-user suppression, admin-only access and
the empty-data response.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UsageAnalytics
from app.services.linter_telemetry_service import (
    LINTER_ACTION,
    LINTER_RULE_IDS,
    admin_linter_rules_service,
)

ENDPOINT = "/admin/linter/rules"
INGEST_ENDPOINT = "/telemetry/linter"
SECRET_LATEX = r"\\section{Private Candidate} secret line 2148"
SECRET_DOCUMENT_ID = "resume_2148_private"


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    token = f"test_sess_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Linter Telemetry User', :role, true, 'free', 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"test_linter_{user_id.replace('-', '')}@example.com",
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


async def _seed_event(
    db: AsyncSession,
    *,
    user_id: str | None,
    rule_id: str = "deprecated-bf",
    severity: str = "warning",
    route: str = "/workspace/:resumeId/edit",
    fixed: bool = False,
    issue_count: int = 1,
    created_at: datetime | None = None,
    metadata: dict | None = None,
) -> None:
    db.add(
        UsageAnalytics(
            user_id=user_id,
            device_fingerprint=None,
            action=LINTER_ACTION,
            resource_type="linter",
            event_metadata=metadata
            if metadata is not None
            else {
                "rule_id": rule_id,
                "severity": severity,
                "route": route,
                "fixed": fixed,
                "issue_count": issue_count,
            },
            created_at=created_at or datetime.now(timezone.utc),
        )
    )
    await db.commit()


@pytest.fixture(autouse=True)
async def _clean_linter_rows(db_session: AsyncSession):
    await db_session.execute(delete(UsageAnalytics).where(UsageAnalytics.action == LINTER_ACTION))
    await db_session.commit()
    yield


class TestIngestion:
    async def test_payload_redaction_drops_content_and_document_ids(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user_id, headers = await _create_user(db_session)
        response = await client.post(
            INGEST_ENDPOINT,
            headers=headers,
            json={
                "events": [
                    {
                        "rule_id": "deprecated-bf",
                        "severity": "warning",
                        "route": f"/workspace/{SECRET_DOCUMENT_ID}/edit?token=secret",
                        "fixed": False,
                        "issue_count": 2,
                        # Hostile extras must never reach storage.
                        "latex_source": SECRET_LATEX,
                        "line_text": SECRET_LATEX,
                        "message": SECRET_LATEX,
                        "document_id": SECRET_DOCUMENT_ID,
                    }
                ],
                "latex_source": SECRET_LATEX,
            },
        )

        assert response.status_code == 202, response.text
        assert response.json() == {"accepted": 1, "rejected": 0, "deduplicated": 0}

        rows = (
            await db_session.execute(
                select(UsageAnalytics.event_metadata).where(UsageAnalytics.action == LINTER_ACTION)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0] == {
            "rule_id": "deprecated-bf",
            "severity": "warning",
            "route": "/workspace/:resumeId/edit",
            "fixed": False,
            "issue_count": 2,
        }
        assert SECRET_LATEX not in str(rows[0])
        assert SECRET_DOCUMENT_ID not in str(rows[0])

    async def test_unknown_rule_ids_are_rejected_and_batch_deduped(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user_id, headers = await _create_user(db_session)
        base_event = {
            "rule_id": "deprecated-bf",
            "severity": "warning",
            "route": "/workspace/:resumeId/edit",
            "fixed": False,
            "issue_count": 3,
        }
        response = await client.post(
            INGEST_ENDPOINT,
            headers=headers,
            json={
                "events": [
                    base_event,
                    dict(base_event),
                    {
                        "rule_id": "not-a-real-rule",
                        "severity": "warning",
                        "route": "/workspace/:resumeId/edit",
                        "fixed": False,
                        "issue_count": 1,
                    },
                ]
            },
        )

        assert response.status_code == 202, response.text
        assert response.json() == {"accepted": 1, "rejected": 1, "deduplicated": 1}

        stored = (
            await db_session.execute(
                select(func.count(UsageAnalytics.id)).where(UsageAnalytics.action == LINTER_ACTION)
            )
        ).scalar_one()
        assert stored == 1

    async def test_allowlist_contains_only_known_linter_rules(self) -> None:
        assert {
            "deprecated-bf",
            "deprecated-it",
            "wrong-quotes",
            "missing-glyphtounicode",
            "duplicate-label",
        } <= LINTER_RULE_IDS
        assert "not-a-real-rule" not in LINTER_RULE_IDS


class TestAggregation:
    async def test_frequency_fix_rate_trend_and_top_noisy_rules(
        self, db_session: AsyncSession
    ) -> None:
        users = [await _create_user(db_session) for _ in range(5)]
        now = datetime.now(timezone.utc)
        for index, (user_id, _headers) in enumerate(users):
            await _seed_event(
                db_session,
                user_id=user_id,
                rule_id="deprecated-bf",
                issue_count=2,
                created_at=now - timedelta(minutes=index + 1),
            )
            await _seed_event(
                db_session,
                user_id=user_id,
                rule_id="tabular-layout",
                severity="info",
                issue_count=1,
                created_at=now - timedelta(minutes=index + 1),
            )
        # Three of the five users applied the deprecated-bf fix.
        for user_id, _headers in users[:3]:
            await _seed_event(
                db_session,
                user_id=user_id,
                rule_id="deprecated-bf",
                fixed=True,
                issue_count=1,
                created_at=now,
            )
        # A one-user route cell must stay hidden even though the rule itself is visible.
        await _seed_event(
            db_session,
            user_id=users[0][0],
            rule_id="deprecated-bf",
            route="/try",
            issue_count=4,
            created_at=now,
        )

        snapshot = await admin_linter_rules_service.snapshot(db_session, days=30)

        assert snapshot["suppressed"] is False
        assert snapshot["summary"]["events"] == 14
        assert snapshot["summary"]["issues_detected"] == 19
        assert snapshot["summary"]["issues_fixed"] == 3
        assert snapshot["summary"]["fix_rate_pct"] == 15.79
        assert snapshot["summary"]["rules_seen"] == 2

        rules = {row["rule_id"]: row for row in snapshot["rules"]}
        assert rules["deprecated-bf"]["frequency"] == 6
        assert rules["deprecated-bf"]["issues_detected"] == 14
        assert rules["deprecated-bf"]["issues_fixed"] == 3
        assert rules["deprecated-bf"]["fix_rate_pct"] == 21.43
        assert rules["tabular-layout"]["fix_rate_pct"] == 0.0
        assert snapshot["top_noisy_rules"][0]["rule_id"] == "deprecated-bf"
        assert rules["deprecated-bf"]["top_routes"][0] == {
            "route": "/workspace/:resumeId/edit",
            "issues_detected": 10,
            "users": 5,
        }
        assert rules["deprecated-bf"]["suppressed_routes"] == 1

        assert len(snapshot["trend"]) == 1
        assert snapshot["trend"][0]["frequency"] == 11
        assert snapshot["trend"][0]["issues_detected"] == 19
        assert snapshot["trend"][0]["issues_fixed"] == 3
        assert snapshot["trend"][0]["fix_rate_pct"] == 15.79
        assert snapshot["privacy"]["per_user_rows"] is False
        assert "user_id" not in str(snapshot)

    async def test_rows_with_extra_or_invalid_metadata_are_ignored(
        self, db_session: AsyncSession
    ) -> None:
        users = [await _create_user(db_session) for _ in range(5)]
        for user_id, _headers in users:
            await _seed_event(
                db_session,
                user_id=user_id,
                metadata={
                    "rule_id": "deprecated-bf",
                    "severity": "warning",
                    "route": "/workspace/:resumeId/edit",
                    "fixed": False,
                    "issue_count": 1,
                    "latex_source": SECRET_LATEX,
                },
            )
        await _seed_event(
            db_session,
            user_id=users[0][0],
            metadata={"rule_id": "not-a-real-rule", "severity": "warning", "fixed": False, "issue_count": 1},
        )
        await _seed_event(
            db_session,
            user_id=users[0][0],
            metadata={
                "rule_id": "deprecated-bf",
                "severity": "warning",
                "fixed": False,
                "issue_count": "many",
            },
        )

        snapshot = await admin_linter_rules_service.snapshot(db_session, days=30)

        assert snapshot["summary"]["events"] == 5
        assert snapshot["summary"]["issues_detected"] == 5
        assert snapshot["reconciliation"]["invalid_rows"] == 2
        assert SECRET_LATEX not in str(snapshot)

    async def test_five_user_suppression_hides_counts_and_rows(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        users = [await _create_user(db_session) for _ in range(4)]
        for user_id, _headers in users:
            await _seed_event(db_session, user_id=user_id, rule_id="wrong-quotes", issue_count=2)

        response = await client.get(
            ENDPOINT,
            params={"days": 30},
            headers=users[0][1],
        )
        # A normal user is forbidden before suppression is ever considered.
        assert response.status_code == 403, response.text

        admin_id, admin_headers = await _create_user(db_session, role="admin")
        response = await client.get(ENDPOINT, params={"days": 30}, headers=admin_headers)
        assert response.status_code == 200, response.text
        payload = response.json()

        assert payload["suppressed"] is True
        assert payload["summary"]["events"] is None
        assert payload["summary"]["issues_detected"] is None
        assert payload["rules"] == []
        assert payload["top_noisy_rules"] == []
        assert payload["trend"] == []
        assert payload["suppression"]["minimum_users"] == 5

    async def test_empty_data_returns_explicit_empty_report(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _admin_id, admin_headers = await _create_user(db_session, role="admin")
        response = await client.get(ENDPOINT, params={"days": 30}, headers=admin_headers)

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["suppressed"] is False
        assert payload["summary"] == {
            "events": 0,
            "issues_detected": 0,
            "issues_fixed": 0,
            "fix_rate_pct": 0.0,
            "rules_seen": 0,
            "distinct_users": 0,
        }
        assert payload["rules"] == []
        assert payload["top_noisy_rules"] == []
        assert payload["trend"] == []
        assert payload["minimum_users"] == 5

    async def test_endpoint_requires_admin(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _user_id, headers = await _create_user(db_session)
        response = await client.get(ENDPOINT, headers=headers)
        assert response.status_code == 403, response.text

        anonymous = await client.get(ENDPOINT)
        assert anonymous.status_code in {401, 403}, anonymous.text
