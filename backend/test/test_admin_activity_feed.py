"""Admin live activity feed: authorization, cursor, categories and redaction.

Rows are inserted on the test-owned session without committing. The route uses
the same session through the ``get_db`` override, and the service wraps live
reads in a savepoint, so a forced live-source failure can fall back without
losing the test fixture rows. The fixture rollback removes everything at the end
of each test.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import admin_activity_service

BASE = datetime.now(timezone.utc) + timedelta(days=3650)
ALLOWED_ITEM_KEYS = {"id", "category", "event", "created_at", "href"}


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    email_prefix: str = "activity",
) -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, created_at) "
            "VALUES (:id, :email, 'Activity User', :role, true, 'free', 'active', false, :created)"
        ),
        {
            "id": user_id,
            "email": f"{email_prefix}_{user_id.replace('-', '')}@example.com",
            "role": role,
            "created": BASE,
        },
    )
    return user_id


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"activity_sess_{uuid.uuid4().hex}"
    await db.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    return {"Authorization": f"Bearer {token}"}


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    return await _session_headers(db, await _create_user(db, role="admin"))


async def _insert_resume(db: AsyncSession, user_id: str) -> str:
    resume_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content, created_at, updated_at) "
            "VALUES (:id, :uid, 'Activity Resume', 'SECRET_LATEX_BODY', :created, :created)"
        ),
        {"id": resume_id, "uid": user_id, "created": BASE},
    )
    return resume_id


async def _insert_compilation(
    db: AsyncSession,
    user_id: str,
    *,
    status: str = "completed",
    created_at: datetime | None = None,
    error_message: str | None = None,
) -> str:
    compilation_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO compilations "
            "(id, user_id, job_id, status, error_message, pdf_path, created_at) "
            "VALUES (:id, :uid, :job, :status, :error, :pdf, :created)"
        ),
        {
            "id": compilation_id,
            "uid": user_id,
            "job": f"activity_{uuid.uuid4().hex}",
            "status": status,
            "error": error_message,
            "pdf": "/private/secret.pdf",
            "created": created_at or BASE,
        },
    )
    return compilation_id


async def _insert_payment(
    db: AsyncSession,
    user_id: str,
    *,
    status: str = "paid",
    created_at: datetime | None = None,
) -> str:
    payment_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO payments "
            "(id, user_id, provider, provider_payment_id, amount, currency, status, "
            "payment_method, created_at) "
            "VALUES (:id, :uid, 'dodo', :provider_id, 499900, 'INR', :status, "
            "'SECRET_CARD_METHOD', :created)"
        ),
        {
            "id": payment_id,
            "uid": user_id,
            "provider_id": f"pay_SECRET_{uuid.uuid4().hex}",
            "status": status,
            "created": created_at or BASE,
        },
    )
    return payment_id


async def _insert_optimization(
    db: AsyncSession,
    user_id: str,
    resume_id: str,
    *,
    created_at: datetime | None = None,
) -> str:
    optimization_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO optimizations "
            "(id, user_id, resume_id, job_description, original_latex, optimized_latex, "
            "provider, model, tokens_used, created_at) "
            "VALUES (:id, :uid, :resume, 'SECRET_JOB_DESCRIPTION', 'SECRET_ORIGINAL', "
            "'SECRET_OPTIMIZED', 'openai', 'gpt-4o-mini', 10, :created)"
        ),
        {
            "id": optimization_id,
            "uid": user_id,
            "resume": resume_id,
            "created": created_at or BASE,
        },
    )
    return optimization_id


async def _insert_usage(
    db: AsyncSession,
    user_id: str,
    *,
    action: str,
    metadata: dict | None = None,
    created_at: datetime | None = None,
) -> str:
    usage_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO usage_analytics "
            "(id, user_id, action, resource_type, event_metadata, ip_address, user_agent, created_at) "
            "VALUES (:id, :uid, :action, 'activity', CAST(:metadata AS jsonb), "
            "'203.0.113.77', 'SecretBrowser/1.0', :created)"
        ),
        {
            "id": usage_id,
            "uid": user_id,
            "action": action,
            "metadata": "{}" if metadata is None else json.dumps(metadata),
            "created": created_at or BASE,
        },
    )
    return usage_id


def _feed_ids(payload: dict) -> set[str]:
    return {item["id"] for item in payload["items"]}


async def test_activity_feed_is_admin_only(client: AsyncClient, db_session: AsyncSession):
    unauthenticated = await client.get("/admin/analytics/activity")
    assert unauthenticated.status_code == 401

    support_headers = await _session_headers(db_session, await _create_user(db_session, role="support"))
    forbidden_support = await client.get("/admin/analytics/activity", headers=support_headers)
    assert forbidden_support.status_code == 403

    user_headers = await _session_headers(db_session, await _create_user(db_session, role="user"))
    forbidden_user = await client.get("/admin/analytics/activity", headers=user_headers)
    assert forbidden_user.status_code == 403

    admin_headers = await _admin_headers(db_session)
    allowed = await client.get("/admin/analytics/activity", headers=admin_headers)
    assert allowed.status_code == 200, allowed.text
    assert allowed.headers["cache-control"] == "no-store"
    payload = allowed.json()
    assert payload["mode"] == "live"
    assert payload["degraded"] is False
    assert payload["detail"] is None
    assert isinstance(payload["items"], list)
    assert payload["has_more"] in {True, False}
    assert payload["generated_at"]


async def test_activity_feed_maps_all_five_categories(client: AsyncClient, db_session: AsyncSession):
    admin_headers = await _admin_headers(db_session)
    signup_id = await _create_user(db_session, email_prefix="activity_signup")
    payment_id = await _insert_payment(db_session, signup_id)
    completed_id = await _insert_compilation(db_session, signup_id, status="completed")
    failed_id = await _insert_compilation(db_session, signup_id, status="failed")
    resume_id = await _insert_resume(db_session, signup_id)
    optimization_id = await _insert_optimization(db_session, signup_id, resume_id)

    response = await client.get("/admin/analytics/activity?limit=100", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    items = {item["id"]: item for item in payload["items"]}

    assert items[f"signup:{signup_id}"]["category"] == "signup"
    assert items[f"signup:{signup_id}"]["event"] == "signup_completed"
    assert items[f"payment:{payment_id}"]["category"] == "payment"
    assert items[f"payment:{payment_id}"]["event"] == "payment_succeeded"
    assert items[f"compile:{completed_id}"]["category"] == "compile"
    assert items[f"compile:{completed_id}"]["event"] == "compile_completed"
    assert items[f"compile:{failed_id}"]["category"] == "error"
    assert items[f"compile:{failed_id}"]["event"] == "compile_failed"
    assert items[f"optimize:{optimization_id}"]["category"] == "optimize"
    assert items[f"optimize:{optimization_id}"]["event"] == "optimize_completed"

    observed = {
        items[f"signup:{signup_id}"]["category"],
        items[f"payment:{payment_id}"]["category"],
        items[f"compile:{completed_id}"]["category"],
        items[f"compile:{failed_id}"]["category"],
        items[f"optimize:{optimization_id}"]["category"],
    }
    assert observed == {"signup", "payment", "compile", "optimize", "error"}
    for item in payload["items"]:
        assert set(item) == ALLOWED_ITEM_KEYS
        assert item["href"] is None or item["href"].startswith("/admin?tab=")


async def test_activity_feed_incremental_cursor_has_no_duplicates(client: AsyncClient, db_session: AsyncSession):
    admin_headers = await _admin_headers(db_session)
    user_id = await _create_user(db_session, email_prefix="activity_cursor")
    first_id = await _insert_compilation(
        db_session, user_id, status="completed", created_at=BASE + timedelta(seconds=1)
    )
    second_id = await _insert_compilation(
        db_session, user_id, status="completed", created_at=BASE + timedelta(seconds=2)
    )

    initial = await client.get("/admin/analytics/activity?limit=2", headers=admin_headers)
    assert initial.status_code == 200, initial.text
    initial_payload = initial.json()
    assert initial_payload["next_cursor"]
    initial_ids = _feed_ids(initial_payload)
    assert f"compile:{second_id}" in initial_ids
    assert f"compile:{first_id}" in initial_ids

    third_id = await _insert_compilation(
        db_session, user_id, status="completed", created_at=BASE + timedelta(seconds=3)
    )
    next_page = await client.get(
        "/admin/analytics/activity",
        params={"limit": 2, "cursor": initial_payload["next_cursor"]},
        headers=admin_headers,
    )
    assert next_page.status_code == 200, next_page.text
    next_payload = next_page.json()
    next_ids = _feed_ids(next_payload)
    assert next_ids == {f"compile:{third_id}"}
    assert next_ids.isdisjoint(initial_ids)
    assert next_payload["has_more"] is False

    # Replaying the same cursor after a dropped response is idempotent: only the
    # already-seen row is available, and the returned cursor does not move back.
    replay = await client.get(
        "/admin/analytics/activity",
        params={"limit": 2, "cursor": initial_payload["next_cursor"]},
        headers=admin_headers,
    )
    assert replay.status_code == 200, replay.text
    replay_payload = replay.json()
    assert _feed_ids(replay_payload) == {f"compile:{third_id}"}
    assert replay_payload["next_cursor"] == next_payload["next_cursor"]

    empty = await client.get(
        "/admin/analytics/activity",
        params={"limit": 2, "cursor": next_payload["next_cursor"]},
        headers=admin_headers,
    )
    assert empty.status_code == 200, empty.text
    empty_payload = empty.json()
    assert empty_payload["items"] == []
    assert empty_payload["next_cursor"] == next_payload["next_cursor"]


async def test_activity_feed_breaks_timestamp_ties_by_event_id(client: AsyncClient, db_session: AsyncSession):
    admin_headers = await _admin_headers(db_session)
    user_id = await _create_user(db_session, email_prefix="activity_tie")
    tied_at = BASE + timedelta(seconds=7)
    first_id = await _insert_compilation(db_session, user_id, status="completed", created_at=tied_at)
    second_id = await _insert_compilation(db_session, user_id, status="completed", created_at=tied_at)
    cursor = admin_activity_service.encode_cursor(tied_at, "compile:00000000-0000-0000-0000-000000000000")

    response = await client.get(
        "/admin/analytics/activity",
        params={"limit": 100, "cursor": cursor},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    ids = _feed_ids(response.json())
    assert {f"compile:{first_id}", f"compile:{second_id}"} <= ids


async def test_activity_feed_fallback_is_redacted_and_degraded(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    admin_headers = await _admin_headers(db_session)
    user_id = await _create_user(db_session, email_prefix="activity_fallback")
    compile_usage_id = await _insert_usage(
        db_session,
        user_id,
        action="compile",
        metadata={
            "email": "fallback_secret@example.com",
            "latex_content": "SECRET_LATEX_CONTENT",
            "prompt": "SECRET_PROMPT",
            "resume_content": "SECRET_RESUME",
        },
    )
    optimize_usage_id = await _insert_usage(db_session, user_id, action="optimize", metadata={"token": "SECRET_TOKEN"})
    await _insert_usage(db_session, user_id, action="page_view")

    async def _unavailable(*args, **kwargs):
        raise RuntimeError("live source offline")

    monkeypatch.setattr(admin_activity_service, "_load_live_events", _unavailable)

    response = await client.get("/admin/analytics/activity?limit=50", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mode"] == "fallback"
    assert payload["degraded"] is True
    assert payload["detail"]
    items = {item["id"]: item for item in payload["items"]}
    assert items[f"usage:{compile_usage_id}"]["category"] == "compile"
    assert items[f"usage:{compile_usage_id}"]["event"] == "compile"
    assert items[f"usage:{optimize_usage_id}"]["category"] == "optimize"
    assert items[f"usage:{optimize_usage_id}"]["event"] == "optimize"

    body = response.text
    for forbidden in (
        "fallback_secret@example.com",
        "SECRET_LATEX_CONTENT",
        "SECRET_PROMPT",
        "SECRET_RESUME",
        "SECRET_TOKEN",
        "203.0.113.77",
        "SecretBrowser/1.0",
        "page_view",
    ):
        assert forbidden not in body
    for item in payload["items"]:
        assert set(item) == ALLOWED_ITEM_KEYS

    # Unclassified usage rows must still advance the fallback cursor so the
    # feed cannot stall when the newest actions are page views.
    await _insert_usage(
        db_session,
        user_id,
        action="page_view",
        created_at=BASE + timedelta(seconds=1),
    )
    quiet = await client.get(
        "/admin/analytics/activity",
        params={"limit": 50, "cursor": payload["next_cursor"]},
        headers=admin_headers,
    )
    assert quiet.status_code == 200, quiet.text
    quiet_payload = quiet.json()
    assert quiet_payload["mode"] == "fallback"
    assert quiet_payload["items"] == []
    assert quiet_payload["next_cursor"] != payload["next_cursor"]

    late_compile_id = await _insert_usage(
        db_session,
        user_id,
        action="compile",
        created_at=BASE + timedelta(seconds=2),
    )
    caught_up = await client.get(
        "/admin/analytics/activity",
        params={"limit": 50, "cursor": quiet_payload["next_cursor"]},
        headers=admin_headers,
    )
    assert caught_up.status_code == 200, caught_up.text
    assert f"usage:{late_compile_id}" in _feed_ids(caught_up.json())


async def test_activity_feed_live_response_never_contains_document_or_payment_fields(
    client: AsyncClient, db_session: AsyncSession
):
    admin_headers = await _admin_headers(db_session)
    user_id = await _create_user(db_session, email_prefix="activity_privacy")
    await _insert_payment(db_session, user_id)
    await _insert_compilation(
        db_session,
        user_id,
        status="failed",
        error_message="SECRET_COMPILER_ERROR",
    )
    resume_id = await _insert_resume(db_session, user_id)
    await _insert_optimization(db_session, user_id, resume_id)

    response = await client.get("/admin/analytics/activity?limit=100", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.text
    for forbidden in (
        "SECRET_LATEX_BODY",
        "SECRET_JOB_DESCRIPTION",
        "SECRET_ORIGINAL",
        "SECRET_OPTIMIZED",
        "SECRET_COMPILER_ERROR",
        "SECRET_CARD_METHOD",
        "pay_SECRET_",
        "/private/secret.pdf",
        "activity_privacy_",
        "@example.com",
    ):
        assert forbidden not in body
    for item in response.json()["items"]:
        assert set(item) == ALLOWED_ITEM_KEYS


async def test_activity_feed_bounds_limit_and_cursor(client: AsyncClient, db_session: AsyncSession):
    admin_headers = await _admin_headers(db_session)

    too_small = await client.get("/admin/analytics/activity?limit=0", headers=admin_headers)
    assert too_small.status_code == 422

    too_large = await client.get("/admin/analytics/activity?limit=101", headers=admin_headers)
    assert too_large.status_code == 422

    bounded = await client.get("/admin/analytics/activity?limit=100", headers=admin_headers)
    assert bounded.status_code == 200, bounded.text
    assert len(bounded.json()["items"]) <= 100

    invalid_cursor = await client.get("/admin/analytics/activity?cursor=not-a-cursor", headers=admin_headers)
    assert invalid_cursor.status_code == 422
    assert "cursor" in invalid_cursor.json()["detail"].lower()

    oversized_cursor = await client.get(
        "/admin/analytics/activity",
        params={"cursor": "x" * 600},
        headers=admin_headers,
    )
    assert oversized_cursor.status_code == 422


def test_cursor_round_trip_and_rejects_tampering():
    created_at = BASE.replace(microsecond=123456)
    token = admin_activity_service.encode_cursor(created_at, "compile:123e4567-e89b-12d3-a456-426614174000")
    decoded = admin_activity_service.decode_cursor(token)
    assert decoded is not None
    assert decoded.created_at == created_at
    assert decoded.event_id == "compile:123e4567-e89b-12d3-a456-426614174000"

    for bad in ("not-base64", "e30", "eyJ2IjoxLCJ0Ijoibm93IiwiaSI6ImJhZCJ9"):
        with pytest.raises(ValueError):
            admin_activity_service.decode_cursor(bad)
    assert admin_activity_service.decode_cursor("") is None
    assert admin_activity_service.decode_cursor(None) is None
