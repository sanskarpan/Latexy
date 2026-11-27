"""Audited read-only view-as-user snapshots (issue #2125).

Covers RBAC, self-target eligibility, two-person approval, single-use start,
bounded expiry, cross-user token isolation, write refusal, CSRF, audit and the
privacy allowlist (no document content, raw PII, target sessions or user agents).
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models


def _detail_code(response) -> str | None:
    detail = response.json().get("detail")
    if isinstance(detail, dict):
        return str(detail.get("code")) if detail.get("code") else None
    return None


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "free",
    status: str = "active",
    name: str = "View As Target",
    email: str | None = None,
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    resolved_email = email or f"test_view_as_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, :name, :role, true, :plan, :status, false)"
        ),
        {
            "id": user_id,
            "email": resolved_email,
            "name": name,
            "role": role,
            "plan": plan,
            "status": status,
        },
    )
    await db.commit()
    return user_id, resolved_email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_{uuid.uuid4().hex}"
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


async def _admin(db: AsyncSession) -> tuple[dict[str, str], str]:
    user_id, _ = await _create_user(db, role="admin", name="View As Admin")
    return await _session_headers(db, user_id), user_id


async def _request_view_as(
    client: AsyncClient,
    headers: dict[str, str],
    target_user_id: str,
    *,
    minutes: int = 15,
    reason: str = "Investigating support ticket 4242 in read-only mode",
) -> dict:
    response = await client.post(
        "/admin/view-as/requests",
        json={
            "target_user_id": target_user_id,
            "reason": reason,
            "expires_in_minutes": minutes,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _approve(
    client: AsyncClient,
    headers: dict[str, str],
    approval_id: str,
    *,
    note: str = "Approved for read-only support triage",
) -> dict:
    response = await client.post(
        f"/admin/approvals/{approval_id}/approve",
        json={"note": note},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _start(
    client: AsyncClient,
    headers: dict[str, str],
    approval_id: str,
    *,
    note: str = "Starting a bounded read-only review",
) -> dict:
    response = await client.post(
        "/admin/view-as/sessions",
        json={"approval_id": approval_id, "note": note},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _approved_session(
    client: AsyncClient,
    db: AsyncSession,
    *,
    target_plan: str = "pro",
):
    requester_headers, requester_id = await _admin(db)
    approver_headers, approver_id = await _admin(db)
    target_id, target_email = await _create_user(db, plan=target_plan)
    requested = await _request_view_as(client, requester_headers, target_id)
    await _approve(client, approver_headers, requested["approval"]["id"])
    started = await _start(client, requester_headers, requested["approval"]["id"])
    return {
        "requester_headers": requester_headers,
        "requester_id": requester_id,
        "approver_headers": approver_headers,
        "approver_id": approver_id,
        "target_id": target_id,
        "target_email": target_email,
        "requested": requested,
        "started": started,
    }


async def _audit_rows(
    db: AsyncSession, action: str, target_id: str
) -> list[models.AdminAuditLog]:
    rows = (
        await db.execute(
            select(models.AdminAuditLog)
            .where(
                models.AdminAuditLog.action == action,
                models.AdminAuditLog.target_id == target_id,
            )
            .order_by(models.AdminAuditLog.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


class TestViewAsRequest:
    async def test_non_admin_cannot_request_start_list_or_read(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, _ = await _create_user(db_session)
        headers = await _session_headers(db_session, user_id)
        target_id, _ = await _create_user(db_session)

        request_response = await client.post(
            "/admin/view-as/requests",
            json={
                "target_user_id": target_id,
                "reason": "Should not be reachable by a normal user",
                "expires_in_minutes": 15,
            },
            headers=headers,
        )
        assert request_response.status_code == 403
        assert (await client.get("/admin/view-as/sessions", headers=headers)).status_code == 403
        assert (await client.get(f"/admin/view-as/sessions/{uuid.uuid4()}", headers=headers)).status_code == 403
        assert (
            await client.post(
                "/admin/view-as/sessions",
                json={"approval_id": str(uuid.uuid4())},
                headers=headers,
            )
        ).status_code == 403

    async def test_self_target_request_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers, admin_id = await _admin(db_session)
        response = await client.post(
            "/admin/view-as/requests",
            json={
                "target_user_id": admin_id,
                "reason": "I want to preview my own account",
                "expires_in_minutes": 15,
            },
            headers=headers,
        )
        assert response.status_code == 409, response.text
        assert _detail_code(response) == "view_as_conflict"

    async def test_request_creates_pending_approval_and_request_audit(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        requester_headers, requester_id = await _admin(db_session)
        target_id, target_email = await _create_user(db_session)
        body = await _request_view_as(client, requester_headers, target_id)

        approval = body["approval"]
        assert approval["request_type"] == "impersonation"
        assert approval["status"] == "pending"
        assert approval["requested_by"] == requester_id
        assert approval["payload"] == {"target_user_id": target_id, "mode": "view_as"}
        assert approval["resource_type"] == "user"
        assert approval["resource_id"] == target_id
        assert body["expires_in_minutes"] == 15

        assert body["target"]["id"] == target_id
        assert body["target"]["email"] != target_email
        assert "*" in (body["target"]["email"] or "")
        assert body["target"]["pii_masked"] is True

        audits = await _audit_rows(db_session, "admin.view_as.requested", target_id)
        assert audits
        assert audits[0].actor_user_id == requester_id
        assert "read-only" in (audits[0].reason or "").lower()
        assert audits[0].request_id

    async def test_requester_cannot_approve_their_own_view_as_request(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers, _ = await _admin(db_session)
        target_id, _ = await _create_user(db_session)
        body = await _request_view_as(client, headers, target_id)

        response = await client.post(
            f"/admin/approvals/{body['approval']['id']}/approve",
            json={"note": "I approve my own request"},
            headers=headers,
        )
        assert response.status_code == 409, response.text
        assert _detail_code(response) == "approval_self_review"

    async def test_start_before_second_approval_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers, _ = await _admin(db_session)
        target_id, _ = await _create_user(db_session)
        body = await _request_view_as(client, headers, target_id)

        response = await client.post(
            "/admin/view-as/sessions",
            json={"approval_id": body["approval"]["id"]},
            headers=headers,
        )
        assert response.status_code == 409, response.text
        assert _detail_code(response) == "approval_required"


class TestViewAsSnapshot:
    async def test_full_flow_is_single_use_and_contains_no_document_content(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        session = await _approved_session(client, db_session)
        target_id = session["target_id"]
        started = session["started"]

        # A private resume body and a stored user agent must never enter the
        # snapshot. Only the title/timestamps are part of the read surface.
        resume_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO resumes (id, user_id, title, latex_content, structured_content) "
                "VALUES (:id, :uid, 'Support Review Resume', :latex, CAST(:structured AS jsonb))"
            ),
            {
                "id": resume_id,
                "uid": target_id,
                "latex": "% secret_latex_body_do_not_leak",
                "structured": '{"secret": "structured_secret_do_not_leak"}',
            },
        )
        await db_session.execute(
            text(
                "INSERT INTO usage_analytics (id, user_id, action, resource_type, ip_address, user_agent) "
                "VALUES (:id, :uid, 'compile', 'resume', '203.0.113.9', 'secret-user-agent')"
            ),
            {"id": str(uuid.uuid4()), "uid": target_id},
        )
        await db_session.commit()

        token = started["token"]
        assert token.startswith("lx_view_")
        preview = started["session"]
        assert preview["scope"] == "read_only"
        assert preview["read_only"] is True
        assert preview["target"]["id"] == target_id
        assert preview["status"] == "active"
        expires_at = datetime.fromisoformat(preview["expires_at"])
        remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
        assert 0 < remaining <= 15 * 60
        assert started["approval"]["status"] == "executed"

        snapshot_response = await client.get(
            f"/admin/view-as/sessions/{preview['id']}",
            headers={**session["requester_headers"], "X-View-As-Token": token},
        )
        assert snapshot_response.status_code == 200, snapshot_response.text
        body = snapshot_response.json()
        serialized = snapshot_response.text

        assert body["session"]["id"] == preview["id"]
        assert body["session"]["banner"].startswith("READ-ONLY")
        assert body["dashboard"]["resumes"] == 1
        assert body["dashboard"]["usage_events_30d"] == 1
        assert [row["id"] for row in body["resumes"]] == [resume_id]
        assert body["resumes"][0]["title"] == "Support Review Resume"
        assert body["plan"]["subscription_plan"] == "pro"
        assert "support_timeline" in body
        assert body["limitations"]

        assert "secret_latex_body_do_not_leak" not in serialized
        assert "structured_secret_do_not_leak" not in serialized
        assert "secret-user-agent" not in serialized
        assert session["target_email"] not in serialized
        assert "View As Target" not in serialized
        assert token not in serialized
        assert '"structured_content"' not in serialized
        assert '"latex_content"' not in serialized

        audits = await _audit_rows(db_session, "admin.view_as.started", target_id)
        assert audits
        assert audits[0].actor_user_id == session["requester_id"]
        assert audits[0].request_id
        assert token not in (audits[0].event_metadata or {}).values()

        replay = await client.post(
            "/admin/view-as/sessions",
            json={"approval_id": session["requested"]["approval"]["id"]},
            headers=session["requester_headers"],
        )
        assert replay.status_code == 409, replay.text
        assert _detail_code(replay) in {"approval_replayed", "view_as_conflict"}

    async def test_expired_token_is_refused_and_audited_once(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        session = await _approved_session(client, db_session)
        preview = session["started"]["session"]
        await db_session.execute(
            text(
                "UPDATE admin_view_as_sessions "
                "SET created_at = now() - interval '2 minutes', "
                "    expires_at = now() - interval '1 minute' "
                "WHERE id = :id"
            ),
            {"id": preview["id"]},
        )
        await db_session.commit()

        response = await client.get(
            f"/admin/view-as/sessions/{preview['id']}",
            headers={
                **session["requester_headers"],
                "X-View-As-Token": session["started"]["token"],
            },
        )
        assert response.status_code == 403, response.text
        assert _detail_code(response) == "view_as_expired"

        stored = await db_session.get(models.AdminViewAsSession, preview["id"])
        assert stored is not None
        assert stored.ended_at is not None
        assert stored.end_reason == "expired"

        audits = await _audit_rows(db_session, "admin.view_as.expired", session["target_id"])
        assert len(audits) == 1
        assert audits[0].actor_user_id == session["requester_id"]

    async def test_cross_user_and_wrong_token_are_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        session = await _approved_session(client, db_session)
        preview_id = session["started"]["session"]["id"]
        token = session["started"]["token"]
        other_headers, _ = await _admin(db_session)

        cross_user = await client.get(
            f"/admin/view-as/sessions/{preview_id}",
            headers={**other_headers, "X-View-As-Token": token},
        )
        assert cross_user.status_code == 403, cross_user.text
        assert _detail_code(cross_user) == "view_as_forbidden"

        wrong_token = await client.get(
            f"/admin/view-as/sessions/{preview_id}",
            headers={
                **session["requester_headers"],
                "X-View-As-Token": "lx_view_not_the_real_token",
            },
        )
        assert wrong_token.status_code == 403, wrong_token.text
        assert _detail_code(wrong_token) == "view_as_forbidden"

    async def test_write_with_preview_token_is_refused_and_target_is_unchanged(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        session = await _approved_session(client, db_session)
        target_id = session["target_id"]
        headers = {
            **session["requester_headers"],
            "X-View-As-Token": session["started"]["token"],
        }

        mutation = await client.post(
            f"/admin/users/{target_id}/plan",
            json={"plan": "free", "status": "inactive", "reason": "Refused write"},
            headers=headers,
        )
        assert mutation.status_code == 403, mutation.text
        assert _detail_code(mutation) == "view_as_read_only"

        second = await client.post(
            "/admin/view-as/requests",
            json={
                "target_user_id": target_id,
                "reason": "Refused second preview request",
                "expires_in_minutes": 15,
            },
            headers=headers,
        )
        assert second.status_code == 403
        assert _detail_code(second) == "view_as_read_only"

        plan = await db_session.scalar(
            text("SELECT subscription_plan FROM users WHERE id = :uid"),
            {"uid": target_id},
        )
        assert plan == "pro"

    async def test_end_is_idempotent_and_snapshot_is_refused_after_end(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        session = await _approved_session(client, db_session)
        preview_id = session["started"]["session"]["id"]

        ended = await client.post(
            f"/admin/view-as/sessions/{preview_id}/end",
            json={"reason": "Support triage complete"},
            headers=session["requester_headers"],
        )
        assert ended.status_code == 200, ended.text
        assert ended.json()["status"] == "ended"
        assert ended.json()["end_reason"] == "Support triage complete"

        again = await client.post(
            f"/admin/view-as/sessions/{preview_id}/end",
            json={"reason": "Support triage complete again"},
            headers=session["requester_headers"],
        )
        assert again.status_code == 200, again.text
        assert again.json()["status"] == "ended"

        after = await client.get(
            f"/admin/view-as/sessions/{preview_id}",
            headers={
                **session["requester_headers"],
                "X-View-As-Token": session["started"]["token"],
            },
        )
        assert after.status_code == 403, after.text
        assert _detail_code(after) == "view_as_forbidden"

        audits = await _audit_rows(db_session, "admin.view_as.ended", session["target_id"])
        assert len(audits) == 1
        assert audits[0].reason == "Support triage complete"

    async def test_session_list_never_returns_a_token(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        session = await _approved_session(client, db_session)
        response = await client.get(
            "/admin/view-as/sessions",
            headers=session["requester_headers"],
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == session["started"]["session"]["id"]
        assert session["started"]["token"] not in response.text
        assert "token_hash" not in response.text


def test_view_as_migration_is_additive_after_daily_metrics() -> None:
    path = Path(__file__).parents[1] / "alembic/versions/0101_view_as_user.py"
    spec = importlib.util.spec_from_file_location("view_as_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "0101_view_as_user"
    assert migration.down_revision == "0100_daily_metrics"
    source = path.read_text()
    assert "admin_view_as_sessions" in source
    assert "token_hash" in source
    assert "latex_content" not in source
    assert "structured_content" not in source


class TestViewAsCSRF:
    async def test_cookie_authenticated_cross_site_request_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        target_id, _ = await _create_user(db_session)
        response = await client.post(
            "/admin/view-as/requests",
            json={
                "target_user_id": target_id,
                "reason": "Cross-site request should not be allowed",
                "expires_in_minutes": 15,
            },
            headers={
                "Cookie": "better-auth.session_token=some-ambient-cookie",
                "Origin": "https://evil.example",
            },
        )
        assert response.status_code == 403, response.text
        assert "cross-site" in response.text.lower()
