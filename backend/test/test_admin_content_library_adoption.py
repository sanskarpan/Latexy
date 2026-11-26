"""Content-library adoption analytics (#2146).

Covers admin-only access, time-bounded aggregation/reconciliation, five-user
suppression, stale/unused detection, deleted-snippet tombstones, CSV safety and
privacy.  The suite intentionally relies on existing tables only; the global
Alembic head test in ``test_capability_migration.py`` also guards the
no-migration requirement.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SECRET_SNIPPET_BODY = "SECRET_SNIPPET_BODY_2146_MUST_NOT_LEAK"
SECRET_SNIPPET_DESCRIPTION = "SECRET_SNIPPET_DESCRIPTION_2146_MUST_NOT_LEAK"
SECRET_MACRO_NAME = "SECRET_MACRO_NAME_2146_MUST_NOT_LEAK"
SECRET_MACRO_SCRIPT = 'append "SECRET_MACRO_SCRIPT_2146_MUST_NOT_LEAK"'
SECRET_MACRO_ACTION = "SECRET_MACRO_ACTION_2146_MUST_NOT_LEAK"


def _marker() -> str:
    return uuid.uuid4().hex[:10]


def _email(prefix: str) -> str:
    return f"test_content_lib_{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    token = f"test_sess_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Content Library User', :role, true, :plan, 'active', false)"
        ),
        {
            "id": user_id,
            "email": _email(role),
            "role": role,
            "plan": plan,
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


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    _user_id, headers = await _create_user(db, role="admin")
    return headers


async def _create_snippet(
    db: AsyncSession,
    *,
    author_id: str | None,
    title: str,
    category: str,
    is_official: bool = False,
    installs_count: int = 0,
    upvotes_count: int = 0,
    created_at: datetime | None = None,
) -> str:
    snippet_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO snippets "
            "(id, author_id, title, description, content, category, tags, "
            "is_official, installs_count, upvotes_count, created_at) "
            "VALUES (:id, :author_id, :title, :description, :content, :category, "
            "'{}'::text[], :official, :installs, :upvotes, :created_at)"
        ),
        {
            "id": snippet_id,
            "author_id": author_id,
            "title": title,
            "description": SECRET_SNIPPET_DESCRIPTION,
            "content": SECRET_SNIPPET_BODY,
            "category": category,
            "official": is_official,
            "installs": installs_count,
            "upvotes": upvotes_count,
            "created_at": created_at or datetime.now(timezone.utc) - timedelta(days=2),
        },
    )
    await db.commit()
    return snippet_id


async def _seed_install(
    db: AsyncSession,
    *,
    snippet_id: str,
    user_id: str,
    installed_at: datetime,
) -> None:
    await db.execute(
        text(
            "INSERT INTO snippet_installs (snippet_id, user_id, installed_at) "
            "VALUES (:snippet_id, :user_id, :installed_at)"
        ),
        {"snippet_id": snippet_id, "user_id": user_id, "installed_at": installed_at},
    )
    await db.commit()


async def _seed_upvote(
    db: AsyncSession,
    *,
    snippet_id: str,
    user_id: str,
) -> None:
    await db.execute(
        text("INSERT INTO snippet_upvotes (snippet_id, user_id) VALUES (:snippet_id, :user_id)"),
        {"snippet_id": snippet_id, "user_id": user_id},
    )
    await db.commit()


async def _seed_insert_event(
    db: AsyncSession,
    *,
    snippet_id: str,
    user_id: str,
    created_at: datetime,
    category: str = "misc",
    is_official: bool = False,
) -> None:
    await db.execute(
        text(
            "INSERT INTO usage_analytics "
            "(id, user_id, action, resource_type, event_metadata, created_at) "
            "VALUES (:id, :uid, 'snippet_insert', 'snippet', CAST(:metadata AS JSONB), :created_at)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "metadata": json.dumps(
                {
                    "snippet_id": snippet_id,
                    "category": category,
                    "is_official": is_official,
                }
            ),
            "created_at": created_at,
        },
    )
    await db.commit()


async def _create_macro(
    db: AsyncSession,
    *,
    owner_id: str,
    name: str,
    script: str | None,
    created_at: datetime | None = None,
) -> str:
    macro_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO user_macros "
            "(id, user_id, name, description, actions, script, script_version, script_hash, created_at, updated_at) "
            "VALUES (:id, :owner, :name, 'description', CAST(:actions AS JSONB), :script, 1, :script_hash, :created, :created)"
        ),
        {
            "id": macro_id,
            "owner": owner_id,
            "name": name,
            "actions": json.dumps([{"type": "insert", "text": SECRET_MACRO_ACTION}]),
            "script": script,
            "script_hash": (hashlib.sha256(script.encode("utf-8")).hexdigest() if script is not None else None),
            "created": created_at or datetime.now(timezone.utc) - timedelta(days=1),
        },
    )
    await db.commit()
    return macro_id


async def _seed_macro_use(
    db: AsyncSession,
    *,
    macro_id: str,
    user_id: str,
    created_at: datetime,
    script_version: int = 1,
) -> None:
    await db.execute(
        text(
            "INSERT INTO usage_analytics "
            "(id, user_id, action, resource_type, event_metadata, created_at) "
            "VALUES (:id, :uid, 'macro_use', 'macro', CAST(:metadata AS JSONB), :created_at)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "metadata": json.dumps({"macro_id": macro_id, "script_version": script_version}),
            "created_at": created_at,
        },
    )
    await db.commit()


class TestContentLibraryAdoptionAccess:
    async def test_admin_only_access(self, client: AsyncClient, db_session: AsyncSession):
        _user_id, user_headers = await _create_user(db_session, role="user")
        denied = await client.get("/admin/content-library/adoption", headers=user_headers)
        assert denied.status_code == 403

        _support_id, support_headers = await _create_user(db_session, role="support")
        support_denied = await client.get("/admin/content-library/adoption", headers=support_headers)
        assert support_denied.status_code == 403

        anonymous = await client.get("/admin/content-library/adoption")
        assert anonymous.status_code == 401

        admin = await _admin_headers(db_session)
        allowed = await client.get("/admin/content-library/adoption", headers=admin)
        assert allowed.status_code == 200, allowed.text


class TestContentLibraryAggregation:
    async def test_marketplace_insert_is_time_bounded_and_idempotent_for_installs(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        marker = _marker()
        category = f"test_cl_insert_{marker}"
        users = [await _create_user(db_session) for _ in range(5)]
        user_ids = [item[0] for item in users]
        snippet_id = await _create_snippet(
            db_session,
            author_id=user_ids[0],
            title=f"Inserted snippet {marker}",
            category=category,
        )

        for user_id, headers in users:
            installed = await client.post(f"/snippets/{snippet_id}/install", headers=headers)
            assert installed.status_code == 204, installed.text
        # A second call is an idempotent install but a real marketplace insert.
        replay = await client.post(f"/snippets/{snippet_id}/install", headers=users[0][1])
        assert replay.status_code == 204, replay.text

        admin = await _admin_headers(db_session)
        response = await client.get(
            "/admin/content-library/adoption",
            params={"days": 30, "category": category},
            headers=admin,
        )
        assert response.status_code == 200, response.text
        row = response.json()["ranking"][0]
        assert row["inserts"] == 5
        assert row["installers"] == 5
        assert row["uses"] == 6
        assert row["users"] == 5
        assert row["active_users"] == 5

    async def test_time_bounded_aggregates_reconcile(self, client: AsyncClient, db_session: AsyncSession):
        marker = _marker()
        category = f"test_cl_aggregate_{marker}"
        users = [await _create_user(db_session) for _ in range(5)]
        user_ids = [item[0] for item in users]
        snippet_id = await _create_snippet(
            db_session,
            author_id=user_ids[0],
            title=f"Aggregate snippet {marker}",
            category=category,
            installs_count=5,
            upvotes_count=4,
        )

        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=2)
        old = now - timedelta(days=60)

        # Five lifetime installers, only three inside the selected range.
        for user_id in user_ids[:3]:
            await _seed_install(db_session, snippet_id=snippet_id, user_id=user_id, installed_at=recent)
        for user_id in user_ids[3:]:
            await _seed_install(db_session, snippet_id=snippet_id, user_id=user_id, installed_at=old)
        for user_id in user_ids[:4]:
            await _seed_upvote(db_session, snippet_id=snippet_id, user_id=user_id)

        # Four recent insert events and two older ones.
        for user_id in user_ids[:4]:
            await _seed_insert_event(
                db_session,
                snippet_id=snippet_id,
                user_id=user_id,
                created_at=recent,
                category=category,
            )
        for user_id in user_ids[3:]:
            await _seed_insert_event(
                db_session,
                snippet_id=snippet_id,
                user_id=user_id,
                created_at=old,
                category=category,
            )

        admin = await _admin_headers(db_session)
        response = await client.get(
            "/admin/content-library/adoption",
            params={"days": 30, "category": category},
            headers=admin,
        )
        assert response.status_code == 200, response.text
        payload = response.json()

        assert payload["minimum_users"] == 5
        assert payload["candidate_snippets"] == 1
        assert payload["suppressed_snippets"] == 0
        assert len(payload["ranking"]) == 1
        row = payload["ranking"][0]
        assert row["snippet_id"] == snippet_id
        assert row["users"] == 5
        assert row["active_users"] == 4
        assert row["installers"] == 3
        assert row["inserts"] == 3
        assert row["uses"] == 4
        assert row["upvotes"] == 4
        assert row["lifetime_installs"] == 5
        assert row["lifetime_upvotes"] == 4
        assert row["upvote_ratio"] == 80.0
        assert row["active"] is True
        assert row["stale"] is False
        assert row["unused"] is False
        assert row["last_used_at"] is not None

        assert payload["totals"]["installs"] == 3
        assert payload["totals"]["uses"] == 4
        assert payload["totals"]["upvotes"] == 4
        assert payload["totals"]["lifetime_installs"] == 5
        recon = payload["reconciliation"]
        assert recon["source_installs"] == 3
        assert recon["visible_installs"] == 3
        assert recon["suppressed_installs"] == 0
        assert recon["source_uses"] == 4
        assert recon["source_upvotes"] == 4
        assert recon["counter_install_drift"] == 0
        assert recon["counter_upvote_drift"] == 0
        assert recon["reconciled"] is True

        # A 30-day window excludes the old rows but the lifetime audience and
        # upvotes remain visible by definition.
        narrow = await client.get(
            "/admin/content-library/adoption",
            params={"days": 7, "category": category},
            headers=admin,
        )
        assert narrow.status_code == 200, narrow.text
        narrow_row = narrow.json()["ranking"][0]
        assert narrow_row["inserts"] == 3
        assert narrow_row["uses"] == 4
        assert narrow_row["lifetime_installs"] == 5

        single = await client.get(
            "/admin/content-library/adoption",
            params={"days": 30, "snippet": snippet_id},
            headers=admin,
        )
        assert single.status_code == 200, single.text
        assert [row["snippet_id"] for row in single.json()["ranking"]] == [snippet_id]

    async def test_small_cohorts_suppressed_but_unused_and_stale_visible(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        marker = _marker()
        category = f"test_cl_small_{marker}"
        users = [await _create_user(db_session) for _ in range(5)]
        user_ids = [item[0] for item in users]
        now = datetime.now(timezone.utc)

        small_id = await _create_snippet(
            db_session,
            author_id=user_ids[0],
            title=f"Small cohort {marker}",
            category=category,
            installs_count=4,
        )
        for user_id in user_ids[:4]:
            await _seed_install(
                db_session,
                snippet_id=small_id,
                user_id=user_id,
                installed_at=now - timedelta(days=2),
            )

        unused_id = await _create_snippet(
            db_session,
            author_id=user_ids[0],
            title=f"Unused snippet {marker}",
            category=category,
            created_at=now - timedelta(days=3),
        )

        healthy_id = await _create_snippet(
            db_session,
            author_id=user_ids[0],
            title=f"Healthy cohort {marker}",
            category=category,
            installs_count=5,
        )
        for user_id in user_ids:
            await _seed_install(
                db_session,
                snippet_id=healthy_id,
                user_id=user_id,
                installed_at=now - timedelta(days=1),
            )

        stale_id = await _create_snippet(
            db_session,
            author_id=user_ids[0],
            title=f"Stale snippet {marker}",
            category=category,
            installs_count=5,
            created_at=now - timedelta(days=60),
        )
        for user_id in user_ids:
            await _seed_install(
                db_session,
                snippet_id=stale_id,
                user_id=user_id,
                installed_at=now - timedelta(days=50),
            )

        admin = await _admin_headers(db_session)
        response = await client.get(
            "/admin/content-library/adoption",
            params={"days": 30, "category": category},
            headers=admin,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        visible = {row["snippet_id"]: row for row in payload["ranking"]}
        assert small_id not in visible
        assert payload["suppressed_snippets"] == 1
        assert visible[unused_id]["unused"] is True
        assert visible[unused_id]["users"] == 0
        assert visible[healthy_id]["active"] is True
        assert visible[stale_id]["stale"] is True

        unused = await client.get(
            "/admin/content-library/adoption",
            params={"days": 30, "category": category, "status": "unused"},
            headers=admin,
        )
        assert unused.status_code == 200, unused.text
        assert [row["snippet_id"] for row in unused.json()["ranking"]] == [unused_id]

        stale = await client.get(
            "/admin/content-library/adoption",
            params={"days": 30, "category": category, "status": "stale"},
            headers=admin,
        )
        assert stale.status_code == 200, stale.text
        assert [row["snippet_id"] for row in stale.json()["ranking"]] == [stale_id]

    async def test_deleted_snippet_retains_aggregate_snapshot_only(self, client: AsyncClient, db_session: AsyncSession):
        marker = _marker()
        category = f"test_cl_deleted_{marker}"
        author_id, author_headers = await _create_user(db_session)
        users = [await _create_user(db_session) for _ in range(4)]
        user_ids = [author_id] + [item[0] for item in users]
        snippet_id = await _create_snippet(
            db_session,
            author_id=author_id,
            title=f"Deleted snippet {marker}",
            category=category,
            installs_count=5,
            upvotes_count=2,
        )
        now = datetime.now(timezone.utc)
        for user_id in user_ids:
            await _seed_install(
                db_session,
                snippet_id=snippet_id,
                user_id=user_id,
                installed_at=now - timedelta(days=2),
            )
        for user_id in user_ids[:2]:
            await _seed_upvote(db_session, snippet_id=snippet_id, user_id=user_id)

        deleted = await client.delete(f"/snippets/{snippet_id}", headers=author_headers)
        assert deleted.status_code == 204, deleted.text

        admin = await _admin_headers(db_session)
        response = await client.get(
            "/admin/content-library/adoption",
            params={"days": 30, "category": category, "status": "deleted"},
            headers=admin,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert len(payload["ranking"]) == 1
        row = payload["ranking"][0]
        assert row["deleted"] is True
        assert row["snippet_id"] == snippet_id
        assert row["title"] == f"Deleted snippet {marker}"
        assert row["lifetime_installs"] == 5
        assert row["lifetime_upvotes"] == 2
        assert row["users"] == 5
        assert row["deleted_at"] is not None
        assert "content" not in row
        assert "description" not in row
        assert "author_id" not in row
        assert SECRET_SNIPPET_BODY not in response.text
        assert SECRET_SNIPPET_DESCRIPTION not in response.text
        assert "@example.com" not in response.text
        assert "user_id" not in response.text

    async def test_csv_export_is_aggregate_only_and_formula_safe(self, client: AsyncClient, db_session: AsyncSession):
        marker = _marker()
        category = f"test_cl_csv_{marker}"
        users = [await _create_user(db_session) for _ in range(5)]
        user_ids = [item[0] for item in users]
        snippet_id = await _create_snippet(
            db_session,
            author_id=user_ids[0],
            title="=2+2",
            category=category,
            installs_count=5,
            upvotes_count=3,
        )
        for user_id in user_ids:
            await _seed_install(
                db_session,
                snippet_id=snippet_id,
                user_id=user_id,
                installed_at=datetime.now(timezone.utc) - timedelta(days=1),
            )

        admin = await _admin_headers(db_session)
        response = await client.get(
            "/admin/content-library/adoption/export.csv",
            params={"days": 30, "category": category},
            headers=admin,
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        assert 'attachment; filename="content-library-adoption-' in response.headers["content-disposition"]
        assert "private, no-store" in response.headers["cache-control"]
        assert SECRET_SNIPPET_BODY not in response.text
        assert SECRET_SNIPPET_DESCRIPTION not in response.text
        assert "@example.com" not in response.text

        rows = list(csv.reader(io.StringIO(response.text)))
        header = rows[0]
        assert header[0] == "rank"
        assert "snippet_title" in header
        assert "upvote_ratio" in header
        assert "content" not in header
        assert "description" not in header
        assert len(rows) == 2
        title_index = header.index("snippet_title")
        assert rows[1][title_index] == "'=2+2"

        alias = await client.get(
            "/admin/content-library/adoption",
            params={"days": 30, "category": category, "format": "csv"},
            headers=admin,
        )
        assert alias.status_code == 200
        assert alias.headers["content-type"].startswith("text/csv")

    async def test_macro_adoption_is_aggregate_only_and_suppressed_below_floor(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        marker = _marker()
        users = [await _create_user(db_session) for _ in range(5)]
        user_ids = [item[0] for item in users]
        now = datetime.now(timezone.utc)
        macro_ids: list[str] = []
        for index, user_id in enumerate(user_ids):
            script_id = await _create_macro(
                db_session,
                owner_id=user_id,
                name=f"{SECRET_MACRO_NAME}_{marker}_{index}_script",
                script=SECRET_MACRO_SCRIPT,
            )
            recorded_id = await _create_macro(
                db_session,
                owner_id=user_id,
                name=f"{SECRET_MACRO_NAME}_{marker}_{index}_recorded",
                script=None,
            )
            macro_ids.extend([script_id, recorded_id])
        old_macro_id = await _create_macro(
            db_session,
            owner_id=user_ids[0],
            name=f"{SECRET_MACRO_NAME}_{marker}_old",
            script=SECRET_MACRO_SCRIPT,
            created_at=now - timedelta(days=90),
        )
        for index, macro_id in enumerate([macro_ids[0], macro_ids[2], macro_ids[4]]):
            await _seed_macro_use(
                db_session,
                macro_id=macro_id,
                user_id=user_ids[index],
                created_at=now - timedelta(days=1),
            )

        executed = await client.post(
            f"/macros/{macro_ids[0]}/execute",
            headers=users[0][1],
            json={"document": "start", "expected_script_version": 1},
        )
        assert executed.status_code == 200, executed.text

        admin = await _admin_headers(db_session)
        response = await client.get("/admin/content-library/adoption", params={"days": 30}, headers=admin)
        assert response.status_code == 200, response.text
        payload = response.json()
        summary = payload["macro_summary"]
        assert payload["macro_suppressed"] is False
        assert summary is not None
        assert summary["owners"] >= 5
        assert summary["total_macros"] >= 11
        assert summary["script_macros"] >= 6
        assert summary["recorded_macros"] >= 5
        assert summary["used_macros"] >= 3
        assert summary["use_events"] >= 4
        assert summary["active_owners"] >= 3
        assert summary["unused_macros"] >= 1
        assert summary["stale_macros"] >= 1
        assert summary["created_in_range"] >= 10
        assert summary["last_used_at"] is not None
        assert old_macro_id  # seeded for stale coverage

        assert SECRET_MACRO_NAME not in response.text
        assert SECRET_MACRO_SCRIPT not in response.text
        assert SECRET_MACRO_ACTION not in response.text
        assert "@example.com" not in response.text
        assert "user_id" not in response.text

    async def test_filters_reject_invalid_ranges_and_unknown_status(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin = await _admin_headers(db_session)
        bad_range = await client.get(
            "/admin/content-library/adoption",
            params={"start_date": "2026-02-01", "end_date": "2026-01-01"},
            headers=admin,
        )
        assert bad_range.status_code == 422

        too_long = await client.get(
            "/admin/content-library/adoption",
            params={"start_date": "2024-01-01", "end_date": "2026-11-26"},
            headers=admin,
        )
        assert too_long.status_code == 422

        bad_status = await client.get(
            "/admin/content-library/adoption",
            params={"status": "not-a-status"},
            headers=admin,
        )
        assert bad_status.status_code == 422

        too_many_categories = await client.get(
            "/admin/content-library/adoption",
            params={"category": ",".join(f"category-{index}" for index in range(11))},
            headers=admin,
        )
        assert too_many_categories.status_code == 422

        bad_snippet = await client.get(
            "/admin/content-library/adoption",
            params={"snippet": "not-a-uuid"},
            headers=admin,
        )
        assert bad_snippet.status_code == 422
