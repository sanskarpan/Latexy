"""Internal user notes, tags and the merged support timeline (issue #2129)."""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _token(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    email: str | None = None,
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    email = email or f"test_admin_notes_{user_id.replace('-', '')}@example.com"
    token = _token("test_sess_notes")
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Notes User', :role, true, 'pro', 'active', false)"
        ),
        {"id": user_id, "email": email, "role": role},
    )
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
    return user_id, {"Authorization": f"Bearer {token}"}


async def _audit(
    db: AsyncSession,
    *,
    target_user_id: str,
    action: str,
    before: dict | None = None,
    after: dict | None = None,
    metadata: dict | None = None,
    created_at: datetime | None = None,
) -> str:
    audit_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO admin_audit_log (id, actor_user_id, actor_email, action, "
            "target_type, target_id, reason, before, after, event_metadata, created_at) "
            "VALUES (:id, :actor, :actor_email, :action, 'user', :target, "
            "'Timeline seed', CAST(:before AS jsonb), CAST(:after AS jsonb), "
            "CAST(:metadata AS jsonb), :created)"
        ),
        {
            "id": audit_id,
            "actor": str(uuid.uuid4()),
            "actor_email": "internal-admin@example.com",
            "action": action,
            "target": target_user_id,
            "before": json.dumps(before or {}),
            "after": json.dumps(after or {}),
            "metadata": json.dumps(metadata or {}),
            "created": created_at or datetime.now(timezone.utc),
        },
    )
    await db.commit()
    return audit_id


async def _audit_text(db: AsyncSession, action: str, target_id: str) -> str:
    row = (
        await db.execute(
            text(
                "SELECT before, after, event_metadata, reason FROM admin_audit_log "
                "WHERE action = :action AND target_id = :target"
            ),
            {"action": action, "target": target_id},
        )
    ).mappings().all()
    return json.dumps([dict(item) for item in row], default=str)


async def _seed_billing(db: AsyncSession, *, user_id: str) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    payment_id = str(uuid.uuid4())
    subscription_id = str(uuid.uuid4())
    payment_provider_id = f"pay_notes_{uuid.uuid4().hex[:12]}"
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "plan_id, status, current_period_start, current_period_end, quoted_amount, created_at) "
            "VALUES (:id, :uid, 'dodo', :provider_sub, 'pro', 'active', :start, :end, 59900, :created)"
        ),
        {
            "id": subscription_id,
            "uid": user_id,
            "provider_sub": f"sub_notes_{uuid.uuid4().hex[:12]}",
            "start": now - timedelta(days=20),
            "end": now + timedelta(days=10),
            "created": now - timedelta(days=20),
        },
    )
    await db.execute(
        text(
            "INSERT INTO payments (id, user_id, subscription_id, provider, provider_payment_id, "
            "amount, currency, status, created_at) "
            "VALUES (:id, :uid, :sub, 'dodo', :provider_payment, 59900, 'INR', 'paid', :created)"
        ),
        {
            "id": payment_id,
            "uid": user_id,
            "sub": subscription_id,
            "provider_payment": payment_provider_id,
            "created": now - timedelta(days=5),
        },
    )
    await db.execute(
        text(
            "INSERT INTO payment_refunds (id, payment_id, provider, provider_refund_id, "
            "amount, currency, status, reason, created_at) "
            "VALUES (:id, :payment, 'dodo', :provider_refund, 1000, 'INR', 'succeeded', "
            "'goodwill', :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "payment": payment_id,
            "provider_refund": f"ref_notes_{uuid.uuid4().hex[:12]}",
            "created": now - timedelta(days=4),
        },
    )
    refund_request_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO admin_refund_requests (id, payment_id, status, amount, currency, "
            "provider_item_id, tax_inclusive, reason, requested_by, requested_email, "
            "requested_at, updated_at) "
            "VALUES (:id, :payment, 'executed', 1000, 'INR', NULL, true, "
            "'goodwill review', :requested_by, 'internal-admin@example.com', :requested_at, :requested_at)"
        ),
        {
            "id": refund_request_id,
            "payment": payment_id,
            "requested_by": str(uuid.uuid4()),
            "requested_at": now - timedelta(days=3),
        },
    )
    await db.execute(
        text(
            "INSERT INTO subscription_history (id, user_id, subscription_id, plan_id, "
            "previous_plan_id, status, previous_status, event_type, reason, source, effective_at) "
            "VALUES (:id, :uid, :sub, 'pro', 'basic', 'active', 'active', 'plan_changed', "
            "'payment_succeeded', 'billing', :effective)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "sub": subscription_id,
            "effective": now - timedelta(days=2),
        },
    )
    await db.commit()
    return {"payment_id": payment_id, "refund_request_id": refund_request_id, "payment_provider_id": payment_provider_id}


async def _seed_approval(db: AsyncSession, *, user_id: str, now: datetime) -> str:
    approval_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO admin_approvals (id, request_type, resource_type, resource_id, "
            "payload_hash, payload, reason, status, requested_by, approved_by, "
            "requested_at, expires_at, decided_at, executed_at) "
            "VALUES (:id, 'role_escalation', 'user', :target, :hash, CAST(:payload AS jsonb), "
            "'Timeline approval seed', 'executed', :requested_by, :approved_by, "
            ":requested_at, :expires_at, :decided_at, :executed_at)"
        ),
        {
            "id": approval_id,
            "target": user_id,
            "hash": "a" * 64,
            "payload": json.dumps(
                {"target_user_id": user_id, "previous_role": "support", "new_role": "admin"}
            ),
            "requested_by": str(uuid.uuid4()),
            "approved_by": str(uuid.uuid4()),
            "requested_at": now - timedelta(days=1, hours=2),
            "expires_at": now + timedelta(days=1),
            "decided_at": now - timedelta(days=1, hours=1),
            "executed_at": now - timedelta(days=1),
        },
    )
    await db.commit()
    return approval_id


async def _create_note(
    client: AsyncClient,
    headers: dict[str, str],
    user_id: str,
    *,
    body: str = "Customer asked for an invoice copy; next step is billing review.",
    tags: list[str] | None = None,
    visibility: str = "internal",
    reason: str = "Ticket 1234 billing follow-up",
) -> dict:
    response = await client.post(
        f"/admin/users/{user_id}/notes",
        json={
            "body": body,
            "tags": tags or [],
            "visibility": visibility,
            "reason": reason,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestNoteCrud:
    async def test_note_crud_audit_soft_delete_and_retention(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, admin_headers = await _create_user(db_session, role="admin")
        target_id, _ = await _create_user(db_session)
        note = await _create_note(
            client,
            admin_headers,
            target_id,
            tags=["billing", "ticket-123"],
        )
        assert note["author_role"] == "admin"
        assert note["visibility"] == "internal"
        assert note["version"] == 1
        assert note["can_edit"] is True
        assert note["tags"] == ["billing", "ticket-123"]

        listed = await client.get(f"/admin/users/{target_id}/notes", headers=admin_headers)
        assert listed.status_code == 200, listed.text
        payload = listed.json()
        assert payload["total"] == 1
        assert payload["items"][0]["body"] == note["body"]
        assert payload["available_tags"] == ["billing", "ticket-123"]
        assert payload["retention"]["soft_delete"] is True
        assert payload["retention"]["automatic_purge"] is False

        create_audit = await _audit_text(db_session, "admin.user_note.create", note["id"])
        assert note["body"] not in create_audit
        assert "note_digest" in create_audit
        assert "billing" in create_audit

        missing_confirm = await client.patch(
            f"/admin/users/{target_id}/notes/{note['id']}",
            json={
                "expected_version": 1,
                "body": "Updated operational context.",
                "reason": "Ticket 1234 correction",
            },
            headers=admin_headers,
        )
        assert missing_confirm.status_code == 422

        stale = await client.patch(
            f"/admin/users/{target_id}/notes/{note['id']}",
            json={
                "expected_version": 9,
                "body": "Updated operational context.",
                "reason": "Ticket 1234 correction",
                "confirm": True,
            },
            headers=admin_headers,
        )
        assert stale.status_code == 409

        updated = await client.patch(
            f"/admin/users/{target_id}/notes/{note['id']}",
            json={
                "expected_version": 1,
                "body": "Updated operational context without identifiers.",
                "tags": ["billing-review"],
                "reason": "Ticket 1234 correction",
                "confirm": True,
            },
            headers=admin_headers,
        )
        assert updated.status_code == 200, updated.text
        updated_note = updated.json()
        assert updated_note["version"] == 2
        assert updated_note["edited_at"] is not None
        assert updated_note["tags"] == ["billing-review"]

        update_audit = await _audit_text(db_session, "admin.user_note.update", note["id"])
        assert "Updated operational context" not in update_audit
        assert "changed_fields" in update_audit

        not_confirmed = await client.request(
            "DELETE",
            f"/admin/users/{target_id}/notes/{note['id']}",
            json={"expected_version": 2, "reason": "Ticket 1234 closed"},
            headers=admin_headers,
        )
        assert not_confirmed.status_code == 422

        deleted = await client.request(
            "DELETE",
            f"/admin/users/{target_id}/notes/{note['id']}",
            json={"expected_version": 2, "reason": "Ticket 1234 closed", "confirm": True},
            headers=admin_headers,
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_at"] is not None
        assert deleted.json()["already_deleted"] is False

        active = await client.get(f"/admin/users/{target_id}/notes", headers=admin_headers)
        assert active.json()["total"] == 0
        deleted_view = await client.get(
            f"/admin/users/{target_id}/notes?include_deleted=true",
            headers=admin_headers,
        )
        assert deleted_view.status_code == 200
        assert deleted_view.json()["total"] == 1
        assert deleted_view.json()["items"][0]["body"].startswith("Updated operational")

        delete_audit = await _audit_text(db_session, "admin.user_note.delete", note["id"])
        assert "Updated operational context" not in delete_audit
        assert "soft_delete" in delete_audit

        timeline = await client.get(
            f"/admin/users/{target_id}/support-timeline", headers=admin_headers
        )
        assert timeline.status_code == 200
        assert all(item["kind"] != "note" for item in timeline.json()["items"])

        support_headers = (await _create_user(db_session, role="support"))[1]
        support_deleted = await client.get(
            f"/admin/users/{target_id}/notes?include_deleted=true",
            headers=support_headers,
        )
        assert support_deleted.status_code == 403

    async def test_active_legal_hold_blocks_note_and_tag_removal(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, admin_headers = await _create_user(db_session, role="admin")
        target_id, _ = await _create_user(db_session)
        note = await _create_note(client, admin_headers, target_id)
        tag = (
            await client.post(
                f"/admin/users/{target_id}/tags",
                json={"tag": "legal-review", "reason": "Ticket 1234"},
                headers=admin_headers,
            )
        ).json()
        await db_session.execute(
            text(
                "INSERT INTO gdpr_legal_holds (id, user_id, active, reason, placed_by) "
                "VALUES (:id, :uid, true, 'Pending litigation', :placed_by)"
            ),
            {"id": str(uuid.uuid4()), "uid": target_id, "placed_by": str(uuid.uuid4())},
        )
        await db_session.commit()

        blocked_note = await client.request(
            "DELETE",
            f"/admin/users/{target_id}/notes/{note['id']}",
            json={
                "expected_version": 1,
                "reason": "Ticket 1234 closed",
                "confirm": True,
            },
            headers=admin_headers,
        )
        assert blocked_note.status_code == 409
        assert "legal hold" in blocked_note.text

        blocked_tag = await client.request(
            "DELETE",
            f"/admin/users/{target_id}/tags/{tag['id']}",
            json={"reason": "Ticket 1234 closed", "confirm": True},
            headers=admin_headers,
        )
        assert blocked_tag.status_code == 409

        notes = await client.get(f"/admin/users/{target_id}/notes", headers=admin_headers)
        assert notes.status_code == 200
        assert notes.json()["total"] == 1

    async def test_support_author_scope_and_admin_only_notes(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        support_id, support_headers = await _create_user(db_session, role="support")
        other_support_id, other_support_headers = await _create_user(
            db_session, role="support"
        )
        _admin_id, admin_headers = await _create_user(db_session, role="admin")
        target_id, _ = await _create_user(db_session)

        own_note = await _create_note(
            client, support_headers, target_id, tags=["support-owned"]
        )
        assert own_note["author_user_id"] == support_id

        admin_note = await _create_note(
            client,
            admin_headers,
            target_id,
            body="Admin-only escalation context.",
            tags=["escalation"],
            visibility="admin_only",
        )
        assert admin_note["visibility"] == "admin_only"

        forbidden_visibility = await client.post(
            f"/admin/users/{target_id}/notes",
            json={
                "body": "Support cannot create admin-only context.",
                "visibility": "admin_only",
                "reason": "Ticket 1234",
            },
            headers=support_headers,
        )
        assert forbidden_visibility.status_code == 403

        support_list = await client.get(
            f"/admin/users/{target_id}/notes", headers=support_headers
        )
        assert support_list.status_code == 200
        support_items = support_list.json()["items"]
        assert [item["id"] for item in support_items] == [own_note["id"]]
        assert "Admin-only escalation context" not in support_list.text
        assert admin_note["id"] not in support_list.text

        blocked_edit = await client.patch(
            f"/admin/users/{target_id}/notes/{admin_note['id']}",
            json={
                "expected_version": 1,
                "body": "Support should not edit this.",
                "reason": "Ticket 1234",
                "confirm": True,
            },
            headers=support_headers,
        )
        assert blocked_edit.status_code == 404

        blocked_delete = await client.request(
            "DELETE",
            f"/admin/users/{target_id}/notes/{admin_note['id']}",
            json={"expected_version": 1, "reason": "Ticket 1234", "confirm": True},
            headers=support_headers,
        )
        assert blocked_delete.status_code == 404

        cannot_edit_other = await client.patch(
            f"/admin/users/{target_id}/notes/{own_note['id']}",
            json={
                "expected_version": 1,
                "body": "Another support agent cannot edit this.",
                "reason": "Ticket 1234",
                "confirm": True,
            },
            headers=other_support_headers,
        )
        assert cannot_edit_other.status_code == 404

        support_edit = await client.patch(
            f"/admin/users/{target_id}/notes/{own_note['id']}",
            json={
                "expected_version": 1,
                "body": "Support-owned note updated with new context.",
                "reason": "Ticket 1234 follow-up",
                "confirm": True,
            },
            headers=support_headers,
        )
        assert support_edit.status_code == 200, support_edit.text
        assert support_edit.json()["version"] == 2

        admin_can_edit = await client.patch(
            f"/admin/users/{target_id}/notes/{own_note['id']}",
            json={
                "expected_version": 2,
                "body": "Admin edited the support-owned internal note.",
                "reason": "Escalation review",
                "confirm": True,
            },
            headers=admin_headers,
        )
        assert admin_can_edit.status_code == 200
        assert admin_can_edit.json()["edited_at"] is not None

        support_360 = await client.get(
            f"/admin/users/{target_id}/360", headers=support_headers
        )
        assert support_360.status_code == 200, support_360.text
        support_block = support_360.json()["support"]
        assert [note["id"] for note in support_block["notes"]] == [own_note["id"]]
        assert admin_note["id"] not in support_360.text
        assert "Admin-only escalation context" not in support_360.text

        admin_360 = await client.get(f"/admin/users/{target_id}/360", headers=admin_headers)
        assert admin_360.status_code == 200
        admin_block = admin_360.json()["support"]
        assert {note["id"] for note in admin_block["notes"]} == {
            own_note["id"],
            admin_note["id"],
        }

        user_headers = (await _create_user(db_session, role="user"))[1]
        forbidden = await client.get(f"/admin/users/{target_id}/notes", headers=user_headers)
        assert forbidden.status_code == 403
        forbidden_timeline = await client.get(
            f"/admin/users/{target_id}/support-timeline", headers=user_headers
        )
        assert forbidden_timeline.status_code == 403

    async def test_target_isolation_for_notes_tags_and_timeline(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, admin_headers = await _create_user(db_session, role="admin")
        first_id, _ = await _create_user(db_session)
        second_id, _ = await _create_user(db_session)
        note = await _create_note(
            client, admin_headers, first_id, body="Only for the first account."
        )
        tag_response = await client.post(
            f"/admin/users/{first_id}/tags",
            json={"tag": "first-only", "reason": "Ticket 1234"},
            headers=admin_headers,
        )
        assert tag_response.status_code == 201, tag_response.text
        tag_id = tag_response.json()["id"]

        second_notes = await client.get(
            f"/admin/users/{second_id}/notes", headers=admin_headers
        )
        assert second_notes.status_code == 200
        assert second_notes.json()["total"] == 0
        assert note["id"] not in second_notes.text

        cross_edit = await client.patch(
            f"/admin/users/{second_id}/notes/{note['id']}",
            json={
                "expected_version": 1,
                "body": "Cross-target edit must fail.",
                "reason": "Ticket 1234",
                "confirm": True,
            },
            headers=admin_headers,
        )
        assert cross_edit.status_code == 404

        cross_delete = await client.request(
            "DELETE",
            f"/admin/users/{second_id}/notes/{note['id']}",
            json={"expected_version": 1, "reason": "Ticket 1234", "confirm": True},
            headers=admin_headers,
        )
        assert cross_delete.status_code == 404

        second_tags = await client.get(
            f"/admin/users/{second_id}/tags", headers=admin_headers
        )
        assert second_tags.status_code == 200
        assert second_tags.json()["total"] == 0

        cross_remove = await client.request(
            "DELETE",
            f"/admin/users/{second_id}/tags/{tag_id}",
            json={"reason": "Ticket 1234", "confirm": True},
            headers=admin_headers,
        )
        assert cross_remove.status_code == 404

        second_timeline = await client.get(
            f"/admin/users/{second_id}/support-timeline", headers=admin_headers
        )
        assert second_timeline.status_code == 200
        assert second_timeline.json()["total"] == 0
        assert note["id"] not in second_timeline.text

        second_360 = await client.get(
            f"/admin/users/{second_id}/360", headers=admin_headers
        )
        assert second_360.status_code == 200
        assert second_360.json()["support"]["notes"] == []
        assert note["id"] not in second_360.text

    async def test_note_validation_rejects_identifiers_secrets_and_markup(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, admin_headers = await _create_user(db_session, role="admin")
        target_id, _ = await _create_user(db_session)
        rejected_bodies = [
            "Contact the customer at person@example.com for details.",
            "National id 123-45-6789 is on the ticket.",
            "Use sk_live_abcdefgh1234 to reproduce the billing issue.",
            "Paste <script>alert('x')</script> into the note.",
            "Call the customer on +1 415 555 0123 after lunch.",
            "Here is the document: \\documentclass{article}",
        ]
        for body in rejected_bodies:
            response = await client.post(
                f"/admin/users/{target_id}/notes",
                json={"body": body, "reason": "Ticket 1234"},
                headers=admin_headers,
            )
            assert response.status_code == 422, body

        invalid_tag = await client.post(
            f"/admin/users/{target_id}/notes",
            json={
                "body": "Operational context.",
                "tags": ["Not A Tag!"],
                "reason": "Ticket 1234",
            },
            headers=admin_headers,
        )
        assert invalid_tag.status_code == 422

        inert_markup = await _create_note(
            client,
            admin_headers,
            target_id,
            body="Customer asks about <b>bold</b> text in a template.",
        )
        # React renders this as text. The API never accepts executable tags.
        assert "<b>bold</b>" in inert_markup["body"]


class TestTags:
    async def test_tags_crud_soft_delete_and_audit(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        support_id, support_headers = await _create_user(db_session, role="support")
        _admin_id, admin_headers = await _create_user(db_session, role="admin")
        target_id, _ = await _create_user(db_session)

        created = await client.post(
            f"/admin/users/{target_id}/tags",
            json={"tag": "Billing-Review", "reason": "Ticket 1234"},
            headers=support_headers,
        )
        assert created.status_code == 201, created.text
        tag = created.json()
        assert tag["tag"] == "billing-review"
        assert tag["created_by"] == support_id
        assert tag["created_by_role"] == "support"
        assert tag["created"] is True

        duplicate = await client.post(
            f"/admin/users/{target_id}/tags",
            json={"tag": "billing-review", "reason": "Ticket 1234"},
            headers=support_headers,
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["created"] is False
        assert duplicate.json()["id"] == tag["id"]

        listed = await client.get(f"/admin/users/{target_id}/tags", headers=support_headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        user_headers = (await _create_user(db_session, role="user"))[1]
        forbidden = await client.post(
            f"/admin/users/{target_id}/tags",
            json={"tag": "user-tag", "reason": "Ticket 1234"},
            headers=user_headers,
        )
        assert forbidden.status_code == 403

        other_support_headers = (await _create_user(db_session, role="support"))[1]
        other_remove = await client.request(
            "DELETE",
            f"/admin/users/{target_id}/tags/{tag['id']}",
            json={"reason": "Ticket 1234", "confirm": True},
            headers=other_support_headers,
        )
        assert other_remove.status_code == 404

        missing_confirm = await client.request(
            "DELETE",
            f"/admin/users/{target_id}/tags/{tag['id']}",
            json={"reason": "Ticket 1234"},
            headers=admin_headers,
        )
        assert missing_confirm.status_code == 422

        removed = await client.request(
            "DELETE",
            f"/admin/users/{target_id}/tags/{tag['id']}",
            json={"reason": "Ticket 1234 resolved", "confirm": True},
            headers=admin_headers,
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["removed_at"] is not None
        assert removed.json()["already_removed"] is False

        active = await client.get(f"/admin/users/{target_id}/tags", headers=admin_headers)
        assert active.json()["total"] == 0
        historical = await client.get(
            f"/admin/users/{target_id}/tags?include_removed=true", headers=admin_headers
        )
        assert historical.status_code == 200
        assert historical.json()["total"] == 1

        create_audit = await _audit_text(db_session, "admin.user_tag.create", tag["id"])
        assert "billing-review" in create_audit
        remove_audit = await _audit_text(db_session, "admin.user_tag.remove", tag["id"])
        assert "billing-review" in remove_audit

    async def test_invalid_tag_and_cross_target_removal(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, admin_headers = await _create_user(db_session, role="admin")
        first_id, _ = await _create_user(db_session)
        second_id, _ = await _create_user(db_session)
        for value in ("Has Space", "UPPER!", "a" * 33):
            response = await client.post(
                f"/admin/users/{first_id}/tags",
                json={"tag": value, "reason": "Ticket 1234"},
                headers=admin_headers,
            )
            assert response.status_code == 422, value
        created = await client.post(
            f"/admin/users/{first_id}/tags",
            json={"tag": "vip", "reason": "Ticket 1234"},
            headers=admin_headers,
        )
        assert created.status_code == 201
        cross = await client.request(
            "DELETE",
            f"/admin/users/{second_id}/tags/{created.json()['id']}",
            json={"reason": "Ticket 1234", "confirm": True},
            headers=admin_headers,
        )
        assert cross.status_code == 404


class TestSupportTimeline:
    async def test_timeline_merges_orders_paginates_and_dedupes(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, admin_headers = await _create_user(db_session, role="admin")
        target_id, _ = await _create_user(db_session)
        now = datetime.now(timezone.utc)
        note = await _create_note(
            client,
            admin_headers,
            target_id,
            body="Timeline note context, no identifiers.",
        )
        edited = await client.patch(
            f"/admin/users/{target_id}/notes/{note['id']}",
            json={
                "expected_version": 1,
                "body": "Timeline note context after an internal edit.",
                "reason": "Timeline correction",
                "confirm": True,
            },
            headers=admin_headers,
        )
        assert edited.status_code == 200

        await _audit(
            db_session,
            target_user_id=target_id,
            action="user.role.change",
            before={"role": "user"},
            after={"role": "support"},
            created_at=now - timedelta(days=10),
        )
        await _audit(
            db_session,
            target_user_id=target_id,
            action="user.feature.grant",
            before={"override": None},
            after={"override": True},
            metadata={"feature_key": "exports"},
            created_at=now - timedelta(days=9),
        )
        await _audit(
            db_session,
            target_user_id=target_id,
            action="user.trial.extend",
            before={"extended_until": None},
            after={"extended_until": (now + timedelta(days=7)).isoformat()},
            created_at=now - timedelta(days=8),
        )
        await _audit(
            db_session,
            target_user_id=target_id,
            action="user.quota.reset.completed",
            before={"dimensions": ["compilations"]},
            after={"deleted_keys": 1},
            created_at=now - timedelta(days=7),
        )
        await _audit(
            db_session,
            target_user_id=target_id,
            action="user.session.revoke",
            before={"active": True, "kind": "session"},
            after={"active": False, "kind": "session"},
            metadata={"kind": "session", "item_id": str(uuid.uuid4())},
            created_at=now - timedelta(days=6),
        )
        billing = await _seed_billing(db_session, user_id=target_id)
        approval_id = await _seed_approval(db_session, user_id=target_id, now=now)

        first = await client.get(
            f"/admin/users/{target_id}/support-timeline?limit=4&offset=0",
            headers=admin_headers,
        )
        assert first.status_code == 200, first.text
        timeline = first.json()
        assert timeline["order"] == "desc"
        assert timeline["limit"] == 4
        assert timeline["offset"] == 0
        assert timeline["has_more"] is True
        assert timeline["next_offset"] == 4
        assert timeline["viewer_role"] == "admin"
        assert timeline["sources"]["notes"] == 1
        assert timeline["sources"]["payments"] == 1
        assert timeline["sources"]["refunds"] == 1
        assert timeline["sources"]["refund_requests"] == 1
        assert timeline["sources"]["subscription_history"] == 1
        assert timeline["sources"]["approvals"] == 1
        first_ids = [item["id"] for item in timeline["items"]]
        assert len(first_ids) == len(set(first_ids)) == 4
        timestamps = [item["occurred_at"] for item in timeline["items"]]
        assert timestamps == sorted(timestamps, reverse=True)
        kinds = {item["kind"] for item in timeline["items"]}
        assert "approval" in kinds
        assert "note" in kinds or "payment" in kinds

        all_items: list[dict] = []
        offset = 0
        while True:
            page = await client.get(
                f"/admin/users/{target_id}/support-timeline?limit=4&offset={offset}",
                headers=admin_headers,
            )
            assert page.status_code == 200, page.text
            body = page.json()
            assert body["total"] == timeline["total"]
            all_items.extend(body["items"])
            if not body["has_more"]:
                break
            offset = body["next_offset"]
        ids = [item["id"] for item in all_items]
        assert len(ids) == len(set(ids)) == timeline["total"]
        # One created and one edited note event, and no duplicate from the audit log.
        note_events = [item for item in all_items if item["kind"] == "note"]
        assert {item["id"] for item in note_events} == {
            f"note:{note['id']}:created",
            f"note:{note['id']}:edited",
        }
        assert sum(1 for item in all_items if item["kind"] == "approval") == 3
        assert {item["kind"] for item in all_items} >= {
            "role_change",
            "entitlement_change",
            "trial_change",
            "quota_change",
            "credential_revocation",
            "payment",
            "refund",
            "refund_request",
            "subscription",
            "approval",
            "note",
        }
        dump = json.dumps(all_items)
        assert note["body"] not in dump
        assert "Timeline note context" not in dump
        assert "internal-admin@example.com" not in dump
        assert "Timeline approval seed" not in dump
        assert billing["payment_provider_id"] in dump
        assert approval_id in dump

        notes_only = await client.get(
            f"/admin/users/{target_id}/support-timeline?kind=note&limit=10",
            headers=admin_headers,
        )
        assert notes_only.status_code == 200
        assert notes_only.json()["total"] == 2
        assert {item["kind"] for item in notes_only.json()["items"]} == {"note"}

        bad_kind = await client.get(
            f"/admin/users/{target_id}/support-timeline?kind=unknown",
            headers=admin_headers,
        )
        assert bad_kind.status_code == 422

    async def test_support_timeline_hides_admin_only_events(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _admin_id, admin_headers = await _create_user(db_session, role="admin")
        _support_id, support_headers = await _create_user(db_session, role="support")
        target_id, _ = await _create_user(db_session)
        await _create_note(
            client, admin_headers, target_id, body="Internal context for all roles."
        )
        await _create_note(
            client,
            admin_headers,
            target_id,
            body="Restricted admin escalation note.",
            visibility="admin_only",
        )
        await _audit(
            db_session,
            target_user_id=target_id,
            action="user.pii.reveal",
            before={"pii_masked": True, "field": "email"},
            after={"pii_masked": False, "field": "email"},
            metadata={"field": "email"},
        )
        await _seed_approval(db_session, user_id=target_id, now=datetime.now(timezone.utc))

        support = await client.get(
            f"/admin/users/{target_id}/support-timeline", headers=support_headers
        )
        assert support.status_code == 200, support.text
        support_body = support.json()
        assert support_body["viewer_role"] == "support"
        assert set(support_body["restricted_kinds"]) == {"approval", "pii_reveal"}
        assert all(not item["admin_only"] for item in support_body["items"])
        assert all(item["kind"] != "approval" for item in support_body["items"])
        assert all(item["kind"] != "pii_reveal" for item in support_body["items"])
        assert "Restricted admin escalation note" not in support.text
        assert support_body["sources"]["approvals"] == 0

        admin = await client.get(
            f"/admin/users/{target_id}/support-timeline", headers=admin_headers
        )
        assert admin.status_code == 200
        admin_body = admin.json()
        assert admin_body["restricted_kinds"] == []
        assert any(item["kind"] == "approval" for item in admin_body["items"])
        assert any(item["kind"] == "pii_reveal" for item in admin_body["items"])
        assert admin_body["sources"]["approvals"] == 1

    async def test_user_360_support_block_is_live_and_never_cached(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from app.services import admin_user_service

        class FakeCache:
            def __init__(self):
                self.values: dict[str, object] = {}

            async def get(self, key: str):
                return self.values.get(key)

            async def set(self, key: str, value, ttl: int = 3600):
                self.values[key] = value

            async def delete(self, key: str):
                self.values.pop(key, None)

        fake = FakeCache()
        monkeypatch.setattr(admin_user_service, "cache_manager", fake)
        _admin_id, admin_headers = await _create_user(db_session, role="admin")
        target_id, _ = await _create_user(db_session)

        empty = await client.get(f"/admin/users/{target_id}/360", headers=admin_headers)
        assert empty.status_code == 200
        assert empty.json()["support"]["notes"] == []
        assert empty.json()["support"]["timeline"]["total"] == 0
        assert fake.values
        cached = next(iter(fake.values.values()))
        assert "support" not in cached

        note = await _create_note(client, admin_headers, target_id, tags=["timeline"])
        refreshed = await client.get(f"/admin/users/{target_id}/360", headers=admin_headers)
        assert refreshed.status_code == 200
        support_block = refreshed.json()["support"]
        assert [item["id"] for item in support_block["notes"]] == [note["id"]]
        assert support_block["timeline"]["total"] >= 1
        assert support_block["available_tags"] == ["timeline"]
        assert support_block["retention"]["automatic_purge"] is False


def test_migration_0102_is_additive_reversible_and_rechained_from_0100():
    path = Path(__file__).parents[1] / "alembic/versions/0102_admin_user_notes.py"
    spec = importlib.util.spec_from_file_location("latexy_notes_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "0102_admin_user_notes"
    assert migration.down_revision == "0100_daily_metrics"

    calls: list[tuple[str, str]] = []

    class FakeOp:
        def create_table(self, name, *columns, **kwargs):
            calls.append(("create_table", name))

        def create_index(self, name, table, *args, **kwargs):
            calls.append(("create_index", f"{table}.{name}"))

        def drop_index(self, name, *, table_name):
            calls.append(("drop_index", f"{table_name}.{name}"))

        def drop_table(self, name):
            calls.append(("drop_table", name))

    migration.op = FakeOp()
    migration.upgrade()
    assert calls[:2] == [
        ("create_table", "admin_user_notes"),
        ("create_index", "admin_user_notes.idx_admin_user_notes_target_created"),
    ]
    assert ("create_table", "admin_user_tags") in calls
    assert ("create_index", "admin_user_tags.uq_admin_user_tags_active") in calls
    calls.clear()
    migration.downgrade()
    assert calls[0] == ("drop_index", "admin_user_tags.idx_admin_user_tags_target_created")
    assert ("drop_table", "admin_user_tags") in calls
    assert calls[-1] == ("drop_table", "admin_user_notes")
