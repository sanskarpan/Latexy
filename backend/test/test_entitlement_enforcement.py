"""End-to-end entitlement enforcement via a real gated endpoint.

The gated route under test is ``POST /cover-letters/generate`` which declares
``dependencies=[Depends(require_feature("cover_letters"))]``. ``require_feature``
authenticates via ``get_current_user_required`` (a user_id string) and calls
``entitlement_service.has_feature`` which loads role/plan from the DB, so these
tests use REAL user + session rows.

GLOBAL STATE: the autouse ``_reset`` fixture restores the all-enabled baseline
AFTER every test so the plain cover-letter tests never see a disabled feature.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from _entitlement_reset import reset_entitlements_baseline
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.entitlement_service import entitlement_service


@pytest.fixture(autouse=True)
async def _reset():
    yield
    await reset_entitlements_baseline()


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _create_user(
    db: AsyncSession, *, role: str = "user", plan: str = "free"
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"test_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Enf User', :role, true, :plan, 'active', false)"
        ),
        {"id": user_id, "email": email, "role": role, "plan": plan},
    )
    await db.commit()
    return user_id, email


async def _create_session(db: AsyncSession, user_id: str) -> str:
    token = f"test_sess_{uuid.uuid4().hex}"
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {"id": str(uuid.uuid4()), "uid": user_id, "exp": expires_at, "tok": token},
    )
    await db.commit()
    return token


def _generate_payload() -> dict:
    # A well-formed body (passes pydantic validation) referencing a resume that
    # does not exist — so an ENABLED feature falls through to a 404, never a 403.
    return {
        "resume_id": str(uuid.uuid4()),
        "job_description": "We are hiring a backend engineer with strong Python skills.",
        "company_name": "Acme",
        "role_title": "Backend Engineer",
        "tone": "formal",
        "length_preference": "3_paragraphs",
    }


# ── (a) Enabled (default) → NOT a feature_disabled 403 ───────────────────────

async def test_enabled_feature_does_not_403(
    client: AsyncClient, db_session: AsyncSession
):
    user_id, _ = await _create_user(db_session, role="user", plan="free")
    token = await _create_session(db_session, user_id)

    resp = await client.post(
        "/cover-letters/generate",
        json=_generate_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    # Feature is enabled → the entitlement gate passes. It may 404 (resume
    # missing) but must NOT be the feature_disabled 403.
    assert resp.status_code != 403
    assert resp.status_code == 404  # resume not found (gate passed)


# ── (b) Matrix-disabled for free → 403 feature_disabled ──────────────────────

async def test_disabled_matrix_returns_feature_disabled_403(
    client: AsyncClient, db_session: AsyncSession
):
    user_id, _ = await _create_user(db_session, role="user", plan="free")
    token = await _create_session(db_session, user_id)

    await entitlement_service.set_matrix_cell("free", "cover_letters", False, db_session)

    resp = await client.post(
        "/cover-letters/generate",
        json=_generate_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403
    body = resp.json()
    detail = body.get("detail", body)
    # error_body envelope → {"error": {"code": "feature_disabled", ...}} or flat.
    code = None
    if isinstance(detail, dict):
        code = detail.get("code") or (detail.get("error") or {}).get("code")
    assert code == "feature_disabled", body


# ── (c) Admin role bypasses the disabled feature ─────────────────────────────

async def test_admin_role_bypasses_disabled_feature(
    client: AsyncClient, db_session: AsyncSession
):
    user_id, _ = await _create_user(db_session, role="admin", plan="free")
    token = await _create_session(db_session, user_id)

    # Disable via kill-switch (global) — admin must still pass the gate.
    await entitlement_service.set_kill_switch("cover_letters", False, db_session)

    resp = await client.post(
        "/cover-letters/generate",
        json=_generate_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    # Admin bypasses entitlement → gate passes → 404 (resume missing), not 403.
    assert resp.status_code != 403
    assert resp.status_code == 404
