"""Two-person approval queue and maker-checker enforcement."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.services import admin_approval_service
from test.test_admin_control_room_api import (
    _create_paid_subscription,
    _create_user,
    _session_headers,
)


async def _admin(db: AsyncSession) -> tuple[dict[str, str], str]:
    user_id, _ = await _create_user(db, role="admin")
    return await _session_headers(db, user_id), user_id


def _detail_code(response) -> str | None:
    body = response.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        if "code" in detail:
            return str(detail["code"])
        nested = detail.get("error")
        if isinstance(nested, dict) and "code" in nested:
            return str(nested["code"])
    error = body.get("error")
    if isinstance(error, dict) and "code" in error:
        return str(error["code"])
    return None


async def _create_role_approval(
    client: AsyncClient,
    db: AsyncSession,
    *,
    target_user_id: str,
    headers: dict[str, str],
) -> dict:
    response = await client.post(
        "/admin/approvals",
        json={
            "request_type": "role_escalation",
            "payload": {
                "target_user_id": target_user_id,
                "previous_role": "user",
                "new_role": "admin",
            },
            "reason": "Promote a second on-call administrator",
            "expires_in_hours": 24,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _insert_expired_role_approval(
    db: AsyncSession,
    *,
    target_user_id: str,
    requested_by: str,
) -> str:
    payload = admin_approval_service.normalize_payload(
        "role_escalation",
        {
            "target_user_id": target_user_id,
            "previous_role": "user",
            "new_role": "admin",
        },
    )
    approval_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO admin_approvals "
            "(id, request_type, resource_type, resource_id, payload_hash, payload, reason, "
            "status, requested_by, requested_at, expires_at) "
            "VALUES (:id, 'role_escalation', 'user', :resource_id, :hash, CAST(:payload AS jsonb), "
            ":reason, 'pending', :requested_by, :requested_at, :expires_at)"
        ),
        {
            "id": approval_id,
            "resource_id": target_user_id,
            "hash": admin_approval_service.payload_hash("role_escalation", payload),
            "payload": json.dumps(payload),
            "reason": "Expired promotion request",
            "requested_by": requested_by,
            "requested_at": now - timedelta(hours=3),
            "expires_at": now - timedelta(hours=1),
        },
    )
    await db.commit()
    return approval_id


class TestApprovalQueue:
    async def test_non_admin_cannot_read_or_create_approvals(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, _ = await _create_user(db_session)
        headers = await _session_headers(db_session, user_id)
        assert (await client.get("/admin/approvals", headers=headers)).status_code == 403
        assert (
            await client.post(
                "/admin/approvals",
                json={
                    "request_type": "bulk_entitlement_change",
                    "payload": {"changes": []},
                    "reason": "Should not be reachable",
                },
                headers=headers,
            )
        ).status_code == 403

    async def test_self_approval_is_rejected_and_remains_pending(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        requester_headers, requester_id = await _admin(db_session)
        target_id, _ = await _create_user(db_session)
        approval = await _create_role_approval(
            client, db_session, target_user_id=target_id, headers=requester_headers
        )
        assert approval["status"] == "pending"
        assert approval["requested_by"] == requester_id
        assert approval["payload_hash"] and len(approval["payload_hash"]) == 64

        self_approval = await client.post(
            f"/admin/approvals/{approval['id']}/approve",
            json={"note": "I approve my own request"},
            headers=requester_headers,
        )
        assert self_approval.status_code == 409, self_approval.text
        assert _detail_code(self_approval) == "approval_self_review"

        queue = await client.get(
            "/admin/approvals", params={"status": "pending"}, headers=requester_headers
        )
        item = next(row for row in queue.json()["items"] if row["id"] == approval["id"])
        assert item["status"] == "pending"

    async def test_duplicate_open_payload_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        requester_headers, _ = await _admin(db_session)
        target_id, _ = await _create_user(db_session)
        first = await _create_role_approval(
            client, db_session, target_user_id=target_id, headers=requester_headers
        )
        duplicate = await client.post(
            "/admin/approvals",
            json={
                "request_type": "role_escalation",
                "payload": {
                    "target_user_id": target_id,
                    "previous_role": "user",
                    "new_role": "admin",
                },
                "reason": "The same open request should not be duplicated",
                "expires_in_hours": 24,
            },
            headers=requester_headers,
        )
        assert duplicate.status_code == 409, duplicate.text
        assert _detail_code(duplicate) == "approval_conflict"
        assert duplicate.json()["detail"]["approval_id"] == first["id"]

    async def test_impersonation_is_reserved_and_cannot_execute_without_a_surface(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        requester_headers, _ = await _admin(db_session)
        approver_headers, _ = await _admin(db_session)
        target_id, _ = await _create_user(db_session)
        created = await client.post(
            "/admin/approvals",
            json={
                "request_type": "impersonation",
                "payload": {"target_user_id": target_id, "mode": "view_as"},
                "reason": "Investigating a support escalation",
                "expires_in_hours": 1,
            },
            headers=requester_headers,
        )
        assert created.status_code == 201, created.text
        approved = await client.post(
            f"/admin/approvals/{created.json()['id']}/approve",
            json={"note": "Approved for read-only support triage"},
            headers=approver_headers,
        )
        assert approved.status_code == 200, approved.text

        blocked = await client.post(
            f"/admin/approvals/{created.json()['id']}/execute",
            json={"note": "Attempt execution"},
            headers=requester_headers,
        )
        assert blocked.status_code == 409, blocked.text
        assert "impersonation" in blocked.text.lower()

        row = await db_session.get(models.AdminApproval, created.json()["id"])
        assert row is not None
        assert row.status == "approved"


class TestRoleEscalation:
    async def test_role_escalation_requires_approval_and_is_bound_to_payload(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        requester_headers, _requester_id = await _admin(db_session)
        approver_headers, approver_id = await _admin(db_session)
        target_id, _ = await _create_user(db_session)

        missing = await client.patch(
            f"/admin/users/{target_id}/role",
            json={"role": "admin", "reason": "Needs an admin seat"},
            headers=requester_headers,
        )
        assert missing.status_code == 409, missing.text
        assert _detail_code(missing) == "approval_required"

        approval = await _create_role_approval(
            client, db_session, target_user_id=target_id, headers=requester_headers
        )
        approved = await client.post(
            f"/admin/approvals/{approval['id']}/approve",
            json={"note": "Verified on-call rotation and least privilege"},
            headers=approver_headers,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert approved.json()["approved_by"] == approver_id

        promoted = await client.patch(
            f"/admin/users/{target_id}/role",
            json={
                "role": "admin",
                "reason": "Promotion approved by a second admin",
                "approval_id": approval["id"],
            },
            headers=requester_headers,
        )
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["role"] == "admin"

        replay = await client.post(
            f"/admin/approvals/{approval['id']}/execute",
            json={"note": "Try to reuse the approval"},
            headers=requester_headers,
        )
        assert replay.status_code == 409, replay.text
        assert _detail_code(replay) == "approval_replayed"

        audit_rows = (
            await db_session.execute(
                select(models.AdminAuditLog).where(
                    models.AdminAuditLog.target_id == approval["id"]
                )
            )
        ).scalars().all()
        actions = {row.action for row in audit_rows}
        assert {"admin.approval.requested", "admin.approval.approved", "admin.approval.executed"} <= actions
        role_audit = (
            await db_session.execute(
                select(models.AdminAuditLog).where(
                    models.AdminAuditLog.action == "user.role.change",
                    models.AdminAuditLog.target_id == target_id,
                )
            )
        ).scalars().all()
        assert len(role_audit) == 1
        assert role_audit[0].event_metadata["approval_id"] == approval["id"]

    async def test_stale_payload_is_rejected_before_mutation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        requester_headers, _ = await _admin(db_session)
        approver_headers, _ = await _admin(db_session)
        target_id, _ = await _create_user(db_session)
        approval = await _create_role_approval(
            client, db_session, target_user_id=target_id, headers=requester_headers
        )
        assert (
            await client.post(
                f"/admin/approvals/{approval['id']}/approve",
                json={"note": "Approved for the original role state"},
                headers=approver_headers,
            )
        ).status_code == 200

        # The target changed after approval. The same approval id must not be
        # accepted for a different role transition.
        await db_session.execute(
            text("UPDATE users SET role = 'support' WHERE id = :id"), {"id": target_id}
        )
        await db_session.commit()

        stale = await client.patch(
            f"/admin/users/{target_id}/role",
            json={
                "role": "admin",
                "reason": "Attempt with an approval for a stale role",
                "approval_id": approval["id"],
            },
            headers=requester_headers,
        )
        assert stale.status_code == 409, stale.text
        assert _detail_code(stale) == "approval_payload_mismatch"

        current_role = (
            await db_session.execute(text("SELECT role FROM users WHERE id = :id"), {"id": target_id})
        ).scalar_one()
        assert current_role == "support"
        approval_row = await db_session.get(models.AdminApproval, approval["id"])
        assert approval_row is not None
        assert approval_row.status == "approved"


class TestExpiryAndExecution:
    async def test_expired_approval_fails_and_is_audited(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        requester_headers, requester_id = await _admin(db_session)
        approver_headers, _ = await _admin(db_session)
        target_id, _ = await _create_user(db_session)
        approval_id = await _insert_expired_role_approval(
            db_session, target_user_id=target_id, requested_by=requester_id
        )

        expired = await client.post(
            f"/admin/approvals/{approval_id}/approve",
            json={"note": "Too late to approve"},
            headers=approver_headers,
        )
        assert expired.status_code == 409, expired.text
        assert _detail_code(expired) == "approval_expired"

        row = await db_session.get(models.AdminApproval, approval_id)
        assert row is not None
        assert row.status == "expired"
        audit = (
            await db_session.execute(
                select(models.AdminAuditLog).where(
                    models.AdminAuditLog.action == "admin.approval.expired",
                    models.AdminAuditLog.target_id == approval_id,
                )
            )
        ).scalars().all()
        assert len(audit) == 1

    async def test_bulk_entitlement_change_executes_once_and_replays_fail(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        requester_headers, _ = await _admin(db_session)
        approver_headers, _ = await _admin(db_session)

        from app.services.entitlement_service import entitlement_service

        before = await entitlement_service.get_state(db_session)
        current = before["matrix"].get("pro", {}).get("cover_letters")
        changes = [
            {
                "scope": "plan",
                "plan_family": "pro",
                "feature_key": "cover_letters",
                "enabled": bool(current),
            }
        ]
        created = await client.post(
            "/admin/approvals",
            json={
                "request_type": "bulk_entitlement_change",
                "payload": {"changes": changes},
                "reason": "Apply a reviewed plan-wide capability change",
                "expires_in_hours": 24,
            },
            headers=requester_headers,
        )
        assert created.status_code == 201, created.text
        approval_id = created.json()["id"]

        approved = await client.post(
            f"/admin/approvals/{approval_id}/approve",
            json={"note": "Reviewed the affected plan cell"},
            headers=approver_headers,
        )
        assert approved.status_code == 200, approved.text

        first = await client.post(
            f"/admin/approvals/{approval_id}/execute",
            json={"note": "Apply once"},
            headers=requester_headers,
        )
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "executed"

        second = await client.post(
            f"/admin/approvals/{approval_id}/execute",
            json={"note": "Apply twice"},
            headers=requester_headers,
        )
        assert second.status_code == 409, second.text
        assert _detail_code(second) == "approval_replayed"

        mutation_audits = (
            await db_session.execute(
                select(models.AdminAuditLog).where(
                    models.AdminAuditLog.action == "entitlement.bulk.update"
                )
            )
        ).scalars().all()
        matching = [
            row for row in mutation_audits
            if (row.event_metadata or {}).get("approval_id") == approval_id
        ]
        assert len(matching) == 1

        after = await entitlement_service.get_state(db_session)
        assert after["matrix"]["pro"]["cover_letters"] == bool(current)


class TestWorkflowBridges:
    async def test_refund_request_enters_queue_and_shared_approval(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        requester_headers, _ = await _admin(db_session)
        approver_headers, _ = await _admin(db_session)
        user_id, _ = await _create_user(db_session)
        _, payment_id = await _create_paid_subscription(db_session, user_id=user_id)

        created = await client.post(
            "/admin/billing/refunds",
            json={"payment_id": payment_id, "reason": "Duplicate charge review"},
            headers=requester_headers,
        )
        assert created.status_code == 200, created.text
        refund_id = created.json()["id"]

        queue = await client.get(
            "/admin/approvals",
            params={"status": "pending", "request_type": "refund"},
            headers=approver_headers,
        )
        assert queue.status_code == 200, queue.text
        item = next(row for row in queue.json()["items"] if row["resource_id"] == refund_id)
        assert item["request_type"] == "refund"
        assert item["payload"]["refund_request_id"] == refund_id

        self_approval = await client.post(
            f"/admin/approvals/{item['id']}/approve",
            json={"note": "Approving my own refund"},
            headers=requester_headers,
        )
        assert self_approval.status_code == 409, self_approval.text

        approved = await client.post(
            f"/admin/approvals/{item['id']}/approve",
            json={"note": "Verified duplicate charge"},
            headers=approver_headers,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

        refund = await client.get(
            "/admin/billing/refunds", params={"status": "approved"}, headers=approver_headers
        )
        assert any(row["id"] == refund_id for row in refund.json()["items"])

    async def test_account_deletion_enters_queue_and_review_approves_it(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, _ = await _create_user(db_session)
        user_headers = await _session_headers(db_session, user_id)
        admin_headers, _ = await _admin(db_session)

        requested = await client.post(
            "/account/gdpr/deletion",
            json={"confirmation": "DELETE MY ACCOUNT", "reason": "Please erase my account"},
            headers=user_headers,
        )
        assert requested.status_code == 202, requested.text
        gdpr_request_id = requested.json()["request"]["id"]

        queue = await client.get(
            "/admin/approvals",
            params={"status": "pending", "request_type": "account_deletion"},
            headers=admin_headers,
        )
        assert queue.status_code == 200, queue.text
        item = next(row for row in queue.json()["items"] if row["resource_id"] == gdpr_request_id)
        assert item["requested_by"] == user_id
        assert item["payload"]["user_id"] == user_id

        approved = await client.post(
            f"/admin/approvals/{item['id']}/approve",
            json={"note": "Counsel approved the deletion request"},
            headers=admin_headers,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

        gdpr_row = await db_session.get(models.GdprRequest, gdpr_request_id)
        assert gdpr_row is not None
        assert gdpr_row.legal_review_status == "approved"
