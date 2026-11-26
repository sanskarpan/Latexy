"""Quarterly admin access review (#2137).

Covers admin-only access, privileged roster enumeration, two-factor/passkey
state, stale/never-used detection, CSV redaction, quarterly attestation
auditing, role/posture changes between load and submit, and read-only
behaviour. The review relies on existing Better Auth and audit tables, so no
migration is required.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SECRET_SESSION_TOKEN = "test_sess_access_review_SECRET_TOKEN_2137"
SECRET_IP = "203.0.113.213"
SECRET_USER_AGENT = "AccessReviewSecretAgent/2137"


def _email(prefix: str) -> str:
    return f"test_access_review_{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "admin",
    two_factor_enabled: bool = False,
    created_days_ago: int = 1,
    name: str = "Access Review User",
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = _email(role)
    created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "two_factor_enabled, subscription_plan, subscription_status, "
            "trial_used, created_at) "
            "VALUES (:id, :email, :name, :role, true, :twofa, 'free', "
            "'inactive', false, :created_at)"
        ),
        {
            "id": user_id,
            "email": email,
            "name": name,
            "role": role,
            "twofa": two_factor_enabled,
            "created_at": created_at,
        },
    )
    await db.commit()
    return user_id, email


async def _create_session(
    db: AsyncSession,
    user_id: str,
    *,
    created_days_ago: int = 0,
    token: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> str:
    session_token = token or f"test_sess_{uuid.uuid4().hex}"
    created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token, "ipAddress", '
            '"userAgent", "createdAt", "updatedAt") '
            "VALUES (:id, :uid, :expires, :token, :ip, :agent, :created_at, :created_at)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "expires": datetime.now(timezone.utc) + timedelta(days=1),
            "token": session_token,
            "ip": ip_address,
            "agent": user_agent,
            "created_at": created_at,
        },
    )
    await db.commit()
    return session_token


async def _create_passkey(db: AsyncSession, user_id: str) -> str:
    passkey_id = f"test_passkey_{uuid.uuid4().hex}"
    await db.execute(
        text(
            'INSERT INTO passkey (id, name, "publicKey", "userId", "credentialID", '
            'counter, "deviceType", "backedUp", "createdAt") '
            "VALUES (:id, :name, :public_key, :uid, :credential, 0, 'singleDevice', "
            "false, :created_at)"
        ),
        {
            "id": passkey_id,
            "name": "Test passkey",
            "public_key": "test_public_key_material",
            "uid": user_id,
            "credential": f"test_credential_{uuid.uuid4().hex}",
            "created_at": datetime.now(timezone.utc),
        },
    )
    await db.commit()
    return passkey_id


async def _headers(
    db: AsyncSession,
    *,
    role: str = "admin",
    two_factor_enabled: bool = False,
) -> tuple[str, dict[str, str]]:
    user_id, _email_value = await _create_user(db, role=role, two_factor_enabled=two_factor_enabled)
    token = await _create_session(db, user_id)
    return user_id, {"Authorization": f"Bearer {token}"}


async def _snapshot(client: AsyncClient, headers: dict[str, str]) -> tuple[dict, str]:
    response = await client.get("/admin/access-review", headers=headers)
    assert response.status_code == 200, response.text
    return response.json(), response.text


def _expected_accounts(snapshot: dict) -> list[dict[str, str]]:
    return [{"user_id": account["user_id"], "role": account["role"]} for account in snapshot["accounts"]]


def _attest_body(
    snapshot: dict,
    *,
    note: str = "Quarterly privileged-access review completed; all accounts confirmed.",
    decision: str = "attested",
    idempotency_key: str | None = None,
) -> dict:
    return {
        "quarter": snapshot["quarter"],
        "expected_snapshot_hash": snapshot["snapshot_hash"],
        "expected_accounts": _expected_accounts(snapshot),
        "decision": decision,
        "note": note,
        "confirm": True,
        "idempotency_key": idempotency_key or f"test_review_{uuid.uuid4().hex}",
    }


async def _audit_count(db: AsyncSession, idempotency_key: str) -> int:
    return int(
        (
            await db.execute(
                text(
                    "SELECT count(*) FROM admin_audit_log "
                    "WHERE action = 'access_review.attest' "
                    "AND target_type = 'access_review' "
                    "AND event_metadata ->> 'idempotency_key' = :key"
                ),
                {"key": idempotency_key},
            )
        ).scalar_one()
    )


class TestAccessReviewAccess:
    async def test_admin_only_access(self, client: AsyncClient, db_session: AsyncSession):
        anonymous = await client.get("/admin/access-review")
        assert anonymous.status_code == 401

        _user_id, user_headers = await _headers(db_session, role="user")
        user_denied = await client.get("/admin/access-review", headers=user_headers)
        assert user_denied.status_code == 403

        _support_id, support_headers = await _headers(db_session, role="support")
        support_denied = await client.get("/admin/access-review", headers=support_headers)
        assert support_denied.status_code == 403

        _admin_id, admin_headers = await _headers(db_session)
        allowed = await client.get("/admin/access-review", headers=admin_headers)
        assert allowed.status_code == 200, allowed.text

    async def test_csv_and_attestation_are_admin_only(self, client: AsyncClient, db_session: AsyncSession):
        _support_id, support_headers = await _headers(db_session, role="support")
        assert (await client.get("/admin/access-review/export.csv", headers=support_headers)).status_code == 403
        assert (
            await client.post(
                "/admin/access-review/attest",
                json={
                    "quarter": "2026-Q4",
                    "expected_snapshot_hash": "a" * 64,
                    "expected_accounts": [],
                    "decision": "attested",
                    "note": "Attempted by support.",
                    "confirm": True,
                },
                headers=support_headers,
            )
        ).status_code == 403


class TestAccessReviewRoster:
    async def test_lists_admins_and_support_without_regular_users(self, client: AsyncClient, db_session: AsyncSession):
        admin_id, admin_email = await _create_user(db_session, role="admin")
        support_id, support_email = await _create_user(db_session, role="support")
        regular_id, regular_email = await _create_user(db_session, role="user")

        _actor_id, headers = await _headers(db_session)
        snapshot, response_text = await _snapshot(client, headers)
        accounts = {account["user_id"]: account for account in snapshot["accounts"]}

        assert accounts[admin_id]["role"] == "admin"
        assert accounts[support_id]["role"] == "support"
        assert regular_id not in accounts
        assert admin_email not in response_text
        assert support_email not in response_text
        assert regular_email not in response_text
        assert accounts[admin_id]["email_masked"] != admin_email
        assert "*" in (accounts[admin_id]["email_masked"] or "")
        assert snapshot["summary"]["admins"] >= 1
        assert snapshot["summary"]["support"] >= 1
        assert re.fullmatch(r"\d{4}-Q[1-4]", snapshot["quarter"])
        assert re.fullmatch(r"[a-f0-9]{64}", snapshot["snapshot_hash"])
        assert snapshot["review_policy"]["read_only"] is True
        assert snapshot["review_policy"]["automatic_demotion"] is False
        assert snapshot["privacy"]["per_user_histories"] is False

    async def test_two_factor_and_passkey_flags(self, client: AsyncClient, db_session: AsyncSession):
        no_2fa_admin_id, _ = await _create_user(db_session, role="admin", two_factor_enabled=False)
        two_factor_admin_id, _ = await _create_user(db_session, role="admin", two_factor_enabled=True)
        passkey_admin_id, _ = await _create_user(db_session, role="admin", two_factor_enabled=False)
        await _create_passkey(db_session, passkey_admin_id)
        no_2fa_support_id, _ = await _create_user(db_session, role="support", two_factor_enabled=False)

        _actor_id, headers = await _headers(db_session)
        snapshot, response_text = await _snapshot(client, headers)
        accounts = {account["user_id"]: account for account in snapshot["accounts"]}

        missing = accounts[no_2fa_admin_id]
        assert missing["two_factor_enabled"] is False
        assert missing["missing_two_factor"] is True
        assert missing["missing_strong_auth"] is True
        assert "missing_two_factor" in missing["flags"]

        totp = accounts[two_factor_admin_id]
        assert totp["two_factor_enabled"] is True
        assert totp["missing_two_factor"] is False
        assert totp["missing_strong_auth"] is False

        passkey = accounts[passkey_admin_id]
        assert passkey["two_factor_enabled"] is False
        assert passkey["passkey_count"] == 1
        assert passkey["strong_auth"] is True
        assert passkey["missing_two_factor"] is True
        assert passkey["missing_strong_auth"] is False

        support = accounts[no_2fa_support_id]
        assert support["role"] == "support"
        assert support["missing_two_factor"] is True

        assert snapshot["summary"]["admins_without_2fa"] >= 1
        assert snapshot["summary"]["support_without_2fa"] >= 1
        flag_codes = {flag["code"] for flag in snapshot["flags"]}
        assert "admin_without_2fa" in flag_codes
        admin_flag = next(flag for flag in snapshot["flags"] if flag["code"] == "admin_without_2fa")
        assert no_2fa_admin_id in admin_flag["account_ids"]
        assert "SECRET" not in response_text

    async def test_stale_and_never_used_detection(self, client: AsyncClient, db_session: AsyncSession):
        never_used_id, _ = await _create_user(db_session, role="admin", created_days_ago=120)
        stale_id, _ = await _create_user(db_session, role="admin", created_days_ago=200)
        await _create_session(db_session, stale_id, created_days_ago=120)
        fresh_id, _ = await _create_user(db_session, role="support", created_days_ago=10)
        await _create_session(db_session, fresh_id, created_days_ago=1)

        _actor_id, headers = await _headers(db_session)
        snapshot, _ = await _snapshot(client, headers)
        accounts = {account["user_id"]: account for account in snapshot["accounts"]}

        never_used = accounts[never_used_id]
        assert never_used["never_used"] is True
        assert never_used["stale"] is True
        assert never_used["last_login_at"] is None
        assert never_used["account_age_days"] >= 119

        stale = accounts[stale_id]
        assert stale["never_used"] is False
        assert stale["stale"] is True
        assert stale["last_login_at"] is not None
        assert stale["session_count"] >= 1

        fresh = accounts[fresh_id]
        assert fresh["never_used"] is False
        assert fresh["stale"] is False
        assert fresh["active_sessions"] >= 1
        assert fresh["account_age_days"] >= 9

        assert snapshot["summary"]["never_used_admins"] >= 1
        assert snapshot["summary"]["stale_admins"] >= 2
        flag_codes = {flag["code"] for flag in snapshot["flags"]}
        assert "stale_admin" in flag_codes
        assert "never_used_admin" in flag_codes

    async def test_session_tokens_ips_and_user_agents_never_returned(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, _ = await _create_user(db_session, role="admin")
        await _create_session(
            db_session,
            user_id,
            token=SECRET_SESSION_TOKEN,
            ip_address=SECRET_IP,
            user_agent=SECRET_USER_AGENT,
        )

        _actor_id, headers = await _headers(db_session)
        _snapshot_data, response_text = await _snapshot(client, headers)
        assert SECRET_SESSION_TOKEN not in response_text
        assert SECRET_IP not in response_text
        assert SECRET_USER_AGENT not in response_text
        assert "userAgent" not in response_text
        assert '"token"' not in response_text


class TestAccessReviewCsv:
    async def test_csv_is_redacted_and_formula_safe(self, client: AsyncClient, db_session: AsyncSession):
        target_id, target_email = await _create_user(db_session, role="admin", name="=2+2")
        _actor_id, headers = await _headers(db_session)

        response = await client.get("/admin/access-review/export.csv", headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        assert "admin-access-review-" in response.headers["content-disposition"]
        assert "private, no-store" in response.headers["cache-control"]
        assert target_email not in response.text
        assert SECRET_SESSION_TOKEN not in response.text
        assert "userAgent" not in response.text

        rows = list(csv.reader(io.StringIO(response.text)))
        header = rows[0]
        assert header[0] == "quarter"
        assert "email_masked" in header
        assert "two_factor_enabled" in header
        assert "last_login_at" in header
        assert "stale" in header
        assert "never_used" in header
        assert "token" not in header
        assert "ip_address" not in header
        assert "user_agent" not in header

        target_row = next(row for row in rows[1:] if row[1] == target_id)
        email_column = header.index("email_masked")
        name_column = header.index("name_masked")
        assert target_row[email_column] != target_email
        assert "*" in target_row[email_column]
        assert target_row[name_column].startswith("'=")

        alias = await client.get("/admin/access-review", params={"format": "csv"}, headers=headers)
        assert alias.status_code == 200
        assert alias.headers["content-type"].startswith("text/csv")


class TestAccessReviewAttestation:
    async def test_attestation_is_audited_idempotent_and_read_only(self, client: AsyncClient, db_session: AsyncSession):
        target_id, _ = await _create_user(db_session, role="admin", two_factor_enabled=False)
        actor_id, headers = await _headers(db_session)
        snapshot, _ = await _snapshot(client, headers)
        idempotency_key = f"test_review_{uuid.uuid4().hex}"
        body = _attest_body(snapshot, idempotency_key=idempotency_key)

        response = await client.post("/admin/access-review/attest", json=body, headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["duplicate"] is False
        assert payload["automatic_demotion"] is False
        assert payload["quarter"] == snapshot["quarter"]
        attestation = payload["attestation"]
        assert attestation["decision"] == "attested"
        assert attestation["snapshot_hash"] == snapshot["snapshot_hash"]
        assert attestation["roster_size"] == snapshot["summary"]["total"]
        assert attestation["admins_without_2fa"] >= 1
        assert attestation["attested_by_email_masked"]
        assert attestation["attested_at"] is not None

        assert await _audit_count(db_session, idempotency_key) == 1
        row = (
            (
                await db_session.execute(
                    text(
                        "SELECT actor_user_id, target_id, reason, event_metadata "
                        "FROM admin_audit_log WHERE action = 'access_review.attest' "
                        "AND event_metadata ->> 'idempotency_key' = :key"
                    ),
                    {"key": idempotency_key},
                )
            )
            .mappings()
            .one()
        )
        assert row["actor_user_id"] == actor_id
        assert row["target_id"] == snapshot["quarter"]
        assert row["reason"] == body["note"]
        assert row["event_metadata"]["automatic_demotion"] is False
        assert row["event_metadata"]["read_only"] is True
        assert row["event_metadata"]["snapshot_hash"] == snapshot["snapshot_hash"]

        # The attestation is an audit write only: every reviewed role survives.
        roles = {
            str(user_id): role
            for user_id, role in (
                await db_session.execute(
                    text("SELECT id, role FROM users WHERE id IN (:actor, :target)"),
                    {"actor": actor_id, "target": target_id},
                )
            ).all()
        }
        assert roles[actor_id] == "admin"
        assert roles[target_id] == "admin"

        refresh, _ = await _snapshot(client, headers)
        assert refresh["attestation"]["current"] is True
        assert refresh["attestation"]["latest"]["audit_id"] == attestation["audit_id"]
        assert refresh["attestation"]["latest"]["note"] == body["note"]
        assert any(item["audit_id"] == attestation["audit_id"] for item in refresh["attestation"]["history"])

        replay = await client.post("/admin/access-review/attest", json=body, headers=headers)
        assert replay.status_code == 200, replay.text
        assert replay.json()["duplicate"] is True
        assert replay.json()["attestation"]["audit_id"] == attestation["audit_id"]
        assert await _audit_count(db_session, idempotency_key) == 1

    async def test_role_change_between_load_and_submit_conflicts(self, client: AsyncClient, db_session: AsyncSession):
        target_id, _ = await _create_user(db_session, role="admin")
        _actor_id, headers = await _headers(db_session)
        snapshot, _ = await _snapshot(client, headers)
        idempotency_key = f"test_review_{uuid.uuid4().hex}"
        body = _attest_body(snapshot, idempotency_key=idempotency_key)

        await db_session.execute(
            text("UPDATE users SET role = 'support' WHERE id = :id"),
            {"id": target_id},
        )
        await db_session.commit()

        response = await client.post("/admin/access-review/attest", json=body, headers=headers)
        assert response.status_code == 409, response.text
        error = response.json()["error"]
        assert error["code"] == "roster_changed"
        conflicts = error["details"]
        changed = {item["user_id"]: item for item in conflicts["role_changes"]}
        assert changed[target_id]["expected_role"] == "admin"
        assert changed[target_id]["current_role"] == "support"
        assert conflicts["current_snapshot_hash"] != snapshot["snapshot_hash"]
        assert await _audit_count(db_session, idempotency_key) == 0

        await db_session.execute(
            text("UPDATE users SET role = 'admin' WHERE id = :id"),
            {"id": target_id},
        )
        await db_session.commit()

    async def test_added_and_removed_admins_conflict(self, client: AsyncClient, db_session: AsyncSession):
        _actor_id, headers = await _headers(db_session)
        snapshot, _ = await _snapshot(client, headers)

        added_id, _ = await _create_user(db_session, role="admin")
        added_body = _attest_body(snapshot)
        added = await client.post("/admin/access-review/attest", json=added_body, headers=headers)
        assert added.status_code == 409, added.text
        added_conflicts = added.json()["error"]["details"]
        assert any(item["user_id"] == added_id for item in added_conflicts["added"])
        assert await _audit_count(db_session, added_body["idempotency_key"]) == 0

        snapshot_with_added, _ = await _snapshot(client, headers)
        removed_body = _attest_body(snapshot_with_added)
        await db_session.execute(
            text("UPDATE users SET role = 'user' WHERE id = :id"),
            {"id": added_id},
        )
        await db_session.commit()
        removed = await client.post("/admin/access-review/attest", json=removed_body, headers=headers)
        assert removed.status_code == 409, removed.text
        removed_conflicts = removed.json()["error"]["details"]
        assert any(item["user_id"] == added_id for item in removed_conflicts["removed"])
        assert await _audit_count(db_session, removed_body["idempotency_key"]) == 0

    async def test_snapshot_hash_alone_detects_role_change(self, client: AsyncClient, db_session: AsyncSession):
        target_id, _ = await _create_user(db_session, role="admin")
        _actor_id, headers = await _headers(db_session)
        snapshot, _ = await _snapshot(client, headers)
        body = _attest_body(snapshot)
        body.pop("expected_accounts")

        await db_session.execute(
            text("UPDATE users SET role = 'support' WHERE id = :id"),
            {"id": target_id},
        )
        await db_session.commit()

        response = await client.post("/admin/access-review/attest", json=body, headers=headers)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "roster_changed"
        assert await _audit_count(db_session, body["idempotency_key"]) == 0

        await db_session.execute(
            text("UPDATE users SET role = 'admin' WHERE id = :id"),
            {"id": target_id},
        )
        await db_session.commit()

    async def test_posture_change_between_load_and_submit_conflicts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        target_id, _ = await _create_user(db_session, role="support", two_factor_enabled=False)
        _actor_id, headers = await _headers(db_session)
        snapshot, _ = await _snapshot(client, headers)
        body = _attest_body(snapshot)

        await db_session.execute(
            text("UPDATE users SET two_factor_enabled = true WHERE id = :id"),
            {"id": target_id},
        )
        await db_session.commit()

        response = await client.post("/admin/access-review/attest", json=body, headers=headers)
        assert response.status_code == 409, response.text
        error = response.json()["error"]
        assert error["code"] == "review_changed"
        assert error["details"]["current_snapshot_hash"] != snapshot["snapshot_hash"]
        assert await _audit_count(db_session, body["idempotency_key"]) == 0

    async def test_validation_and_quarter_guards(self, client: AsyncClient, db_session: AsyncSession):
        _actor_id, headers = await _headers(db_session)
        snapshot, _ = await _snapshot(client, headers)
        body = _attest_body(snapshot)

        no_confirm = await client.post(
            "/admin/access-review/attest",
            json={**body, "confirm": False},
            headers=headers,
        )
        assert no_confirm.status_code == 422
        assert no_confirm.json()["error"]["code"] == "confirmation_required"

        short_note = await client.post(
            "/admin/access-review/attest",
            json={**body, "note": "too short"},
            headers=headers,
        )
        assert short_note.status_code == 422

        bad_hash = await client.post(
            "/admin/access-review/attest",
            json={**body, "expected_snapshot_hash": "not-a-hash"},
            headers=headers,
        )
        assert bad_hash.status_code == 422

        bad_quarter = await client.post(
            "/admin/access-review/attest",
            json={**body, "quarter": "1999-Q1"},
            headers=headers,
        )
        assert bad_quarter.status_code == 409
        assert bad_quarter.json()["error"]["code"] == "quarter_changed"

        stale_roster = await client.post(
            "/admin/access-review/attest",
            json={
                **body,
                "expected_accounts": [{"user_id": str(uuid.uuid4()), "role": "admin"}],
            },
            headers=headers,
        )
        assert stale_roster.status_code == 409
        assert stale_roster.json()["error"]["code"] == "roster_changed"
