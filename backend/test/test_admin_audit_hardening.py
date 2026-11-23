"""Hardening tests for the append-only admin audit log.

Covers the keyset cursor, filter echo, bounded page size, redaction of
before/after payloads, the absence of mutation routes, and the database-role
hardening script.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AdminAuditLog
from app.services import admin_audit_service
from app.services.admin_audit_service import AdminActor, record_admin_audit

ROLE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "harden_admin_audit_role.sql"


async def _create_user(db: AsyncSession, *, role: str = "user") -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, :name, :role, true, 'free', 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"test_audit_{user_id.replace('-', '')}@example.com",
            "name": "Audit Fixture User",
            "role": role,
        },
    )
    await db.commit()
    return user_id


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_audit_{uuid.uuid4().hex}"
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


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    return await _session_headers(db, await _create_user(db, role="admin"))


async def _seed_audit_rows(
    db: AsyncSession,
    *,
    target_id: str,
    created_at: datetime,
    count: int,
    actor_user_id: str = "audit-fixture-actor",
    action: str = "audit.test.pagination",
    target_type: str = "audit_fixture",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> list[str]:
    rows: list[AdminAuditLog] = []
    for index in range(count):
        row = AdminAuditLog(
            id=str(uuid.uuid4()),
            actor_user_id=actor_user_id,
            actor_email=f"{actor_user_id}@example.com",
            action=action,
            target_type=target_type,
            target_id=target_id,
            before_state=before if before is not None else {"index": index},
            after_state=after if after is not None else {"index": index},
            created_at=created_at,
        )
        db.add(row)
        rows.append(row)
    await db.commit()
    return [row.id for row in rows]


def _split_sql(sql: str) -> list[str]:
    """Split PostgreSQL statements while respecting quotes and DO $$ blocks."""
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    dollar_tag: str | None = None
    index = 0
    while index < len(sql):
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                current.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
            else:
                current.append(sql[index])
                index += 1
            continue
        char = sql[index]
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "$" and not in_single and not in_double:
            match = re.match(r"\$[A-Za-z0-9_]*\$", sql[index:])
            if match:
                dollar_tag = match.group(0)
                current.append(dollar_tag)
                index += len(dollar_tag)
                continue
        elif char == ";" and not in_single and not in_double:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _role_script(role: str) -> str:
    content = ROLE_SCRIPT.read_text(encoding="utf-8")
    executable = "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith(("--", "\\"))
    )
    return executable.replace(":'app_role'", f"'{role}'").replace(':"app_role"', f'"{role}"')


class TestAuditCursorPagination:
    async def test_equal_timestamps_paginate_without_duplicates_or_gaps(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        target_id = f"audit-page-{uuid.uuid4()}"
        timestamp = datetime(2026, 1, 2, 3, 4, 5, 654321, tzinfo=timezone.utc)
        expected_ids = await _seed_audit_rows(
            db_session,
            target_id=target_id,
            created_at=timestamp,
            count=7,
        )

        seen: list[str] = []
        cursor: str | None = None
        pages = 0
        while True:
            params: dict[str, Any] = {"target_id": target_id, "limit": 3}
            if cursor:
                params["cursor"] = cursor
            response = await client.get("/admin/audit", params=params, headers=headers)
            assert response.status_code == 200
            body = response.json()
            assert body["total"] == 7
            assert body["limit"] == 3
            assert body["filters"]["target_id"] == target_id
            assert len(body["items"]) <= 3
            seen.extend(item["id"] for item in body["items"])
            pages += 1
            assert pages < 10
            if not body["has_more"]:
                assert body["next_cursor"] is None
                break
            assert body["next_cursor"]
            cursor = body["next_cursor"]

        assert pages == 3
        assert len(seen) == len(set(seen)) == len(expected_ids)
        assert seen == sorted(expected_ids, reverse=True)

    async def test_cursor_filters_echo_and_time_range(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        target_a = f"audit-filter-a-{uuid.uuid4()}"
        target_b = f"audit-filter-b-{uuid.uuid4()}"
        actor_a = f"audit-actor-a-{uuid.uuid4().hex[:12]}"
        actor_b = f"audit-actor-b-{uuid.uuid4().hex[:12]}"
        fixture_type = f"audit_filter_{uuid.uuid4().hex[:10]}"
        other_type = f"other_filter_{uuid.uuid4().hex[:10]}"
        action_a = f"audit.test.filter.a.{uuid.uuid4().hex[:8]}"
        action_b = f"audit.test.filter.b.{uuid.uuid4().hex[:8]}"
        start = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
        rows = {
            "a": await _seed_audit_rows(
                db_session,
                target_id=target_a,
                created_at=start,
                count=1,
                actor_user_id=actor_a,
                action=action_a,
                target_type=fixture_type,
            ),
            "b": await _seed_audit_rows(
                db_session,
                target_id=target_b,
                created_at=start + timedelta(seconds=1),
                count=1,
                actor_user_id=actor_b,
                action=action_b,
                target_type=fixture_type,
            ),
            "c": await _seed_audit_rows(
                db_session,
                target_id=target_a,
                created_at=start + timedelta(seconds=2),
                count=1,
                actor_user_id=actor_a,
                action=action_b,
                target_type=other_type,
            ),
        }

        cases = [
            ({"actor_user_id": actor_a}, {"a", "c"}),
            ({"action": action_a}, {"a"}),
            ({"target_type": fixture_type}, {"a", "b"}),
            ({"target_id": target_a}, {"a", "c"}),
            (
                {
                    "target_id": target_a,
                    "created_after": (start + timedelta(seconds=1)).isoformat(),
                },
                {"c"},
            ),
            (
                {
                    "target_id": target_a,
                    "created_before": (start + timedelta(seconds=1)).isoformat(),
                },
                {"a"},
            ),
            (
                {"actor_user_id": actor_a, "target_type": other_type},
                {"c"},
            ),
        ]
        lookup = {row[0]: key for key, row in rows.items()}

        for params, expected_keys in cases:
            response = await client.get("/admin/audit", params=params, headers=headers)
            assert response.status_code == 200
            body = response.json()
            assert body["total"] == len(expected_keys)
            assert {lookup[item["id"]] for item in body["items"]} == expected_keys
            for key, value in params.items():
                assert body["filters"][key] == value

    async def test_page_size_bounds_and_invalid_cursor(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)

        too_small = await client.get("/admin/audit", params={"limit": 0}, headers=headers)
        assert too_small.status_code == 422
        too_large = await client.get("/admin/audit", params={"limit": 201}, headers=headers)
        assert too_large.status_code == 422
        maximum = await client.get("/admin/audit", params={"limit": 200}, headers=headers)
        assert maximum.status_code == 200
        assert maximum.json()["limit"] == 200

        invalid = await client.get(
            "/admin/audit", params={"cursor": "not-a-real-cursor"}, headers=headers
        )
        assert invalid.status_code == 400
        assert "cursor" in invalid.json()["detail"].lower()


class TestAuditAppendOnlySurface:
    def test_no_update_or_delete_route_exists(self, test_application):
        paths = test_application.openapi()["paths"]
        audit_paths = {
            path: methods
            for path, methods in paths.items()
            if path == "/admin/audit" or path.startswith("/admin/audit/")
        }
        assert audit_paths
        assert set(audit_paths) == {"/admin/audit"}
        methods = set(audit_paths["/admin/audit"])
        assert methods == {"get"}
        assert not methods & {"post", "put", "patch", "delete"}
        assert not [
            name
            for name in dir(admin_audit_service)
            if name.startswith(("delete_", "update_"))
        ]

    async def test_database_rejects_audit_update_and_delete(
        self, db_session: AsyncSession
    ):
        target_id = f"audit-append-{uuid.uuid4()}"
        row_ids = await _seed_audit_rows(
            db_session,
            target_id=target_id,
            created_at=datetime.now(timezone.utc),
            count=1,
        )
        row_id = row_ids[0]

        for statement in (
            "UPDATE admin_audit_log SET reason = 'rewritten' WHERE id = :id",
            "DELETE FROM admin_audit_log WHERE id = :id",
        ):
            with pytest.raises(Exception):
                await db_session.execute(text(statement), {"id": row_id})
                await db_session.commit()
            await db_session.rollback()

        surviving = (
            await db_session.execute(
                text("SELECT count(*) FROM admin_audit_log WHERE id = :id"),
                {"id": row_id},
            )
        ).scalar_one()
        assert surviving == 1


class TestAuditRedaction:
    async def test_before_after_keep_only_changed_safe_fields(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        target_id = f"audit-redaction-{uuid.uuid4()}"
        actor = AdminActor(
            user_id=str(uuid.uuid4()),
            email="audit-admin@example.com",
            role="admin",
        )
        await record_admin_audit(
            db_session,
            actor=actor,
            action="user.role.change",
            target_type="user",
            target_id=target_id,
            before={
                "role": "user",
                "plan": "free",
                "password": "old-password-value",
                "email": "old-customer@example.com",
                "profile": {"name": "Ada Lovelace", "team": "ops"},
            },
            after={
                "role": "admin",
                "plan": "free",
                "password": "new-password-value",
                "email": "new-customer@example.com",
                "profile": {"name": "Ada Lovelace", "team": "security"},
            },
            metadata={"token": "bearer super-secret-token", "event": "safe"},
        )
        await db_session.commit()

        response = await client.get(
            "/admin/audit",
            params={"target_id": target_id, "action": "user.role.change"},
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["before"] == {"role": "user", "profile": {"team": "ops"}}
        assert item["after"] == {"role": "admin", "profile": {"team": "security"}}
        assert item["metadata"] == {"token": "[redacted]", "event": "safe"}
        serialized = response.text
        for secret in (
            "old-password-value",
            "new-password-value",
            "old-customer@example.com",
            "new-customer@example.com",
            "Ada Lovelace",
            "super-secret-token",
        ):
            assert secret not in serialized


class TestAuditRoleHardeningScript:
    def test_script_documents_the_least_privilege_grants(self):
        script = ROLE_SCRIPT.read_text(encoding="utf-8")
        assert "app_role" in script
        assert "REVOKE ALL PRIVILEGES ON TABLE admin_audit_log" in script
        assert "GRANT SELECT, INSERT ON TABLE admin_audit_log" in script
        assert "admin_audit_log_append_only" in script

    async def test_script_grants_only_select_insert_to_the_app_role(
        self, db_session: AsyncSession
    ):
        role = f"test_audit_app_{uuid.uuid4().hex[:10]}"
        quoted_role = f'"{role}"'
        await db_session.execute(text(f"DROP ROLE IF EXISTS {quoted_role}"))
        await db_session.execute(text(f"CREATE ROLE {quoted_role} NOLOGIN"))
        try:
            for statement in _split_sql(_role_script(role)):
                await db_session.execute(text(statement))

            for privilege, expected in {
                "SELECT": True,
                "INSERT": True,
                "UPDATE": False,
                "DELETE": False,
                "TRUNCATE": False,
            }.items():
                granted = (
                    await db_session.execute(
                        text(
                            "SELECT has_table_privilege("
                            ":role, 'public.admin_audit_log', :privilege)"
                        ),
                        {"role": role, "privilege": privilege},
                    )
                ).scalar_one()
                assert bool(granted) is expected

            grants = (
                await db_session.execute(
                    text(
                        "SELECT privilege_type "
                        "FROM information_schema.role_table_grants "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'admin_audit_log' "
                        "AND grantee = :role"
                    ),
                    {"role": role},
                )
            ).scalars().all()
            assert set(grants) == {"SELECT", "INSERT"}
        finally:
            await db_session.rollback()
            await db_session.execute(text(f"DROP ROLE IF EXISTS {quoted_role}"))
            await db_session.commit()
