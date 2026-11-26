"""Admin template health status, evidence links, retry audit and auth."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SECRET_TEMPLATE_SOURCE = "SECRET_TEMPLATE_SOURCE_HEALTH_2144_MUST_NOT_LEAK"
COMMIT_SHA = "a" * 40


def _token(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _email(prefix: str) -> str:
    return f"test_template_health_{prefix}_{uuid.uuid4().hex[:8]}@example.com"


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
            "VALUES (:id, :email, 'Template Health User', :role, true, :plan, 'active', false)"
        ),
        {"id": user_id, "email": _email(role), "role": role, "plan": plan},
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


async def _create_template(
    db: AsyncSession,
    *,
    name: str | None = None,
    category: str = "finance",
    latex_content: str = "\\documentclass{article}\\begin{document}test\\end{document}",
    is_active: bool = True,
) -> str:
    template_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO resume_templates (id, name, category, latex_content, is_active) "
            "VALUES (:id, :name, :category, :latex, :active)"
        ),
        {
            "id": template_id,
            "name": name or f"test_tmpl_{_token('health')}",
            "category": category,
            "latex": latex_content,
            "active": is_active,
        },
    )
    await db.commit()
    return template_id


async def _seed_compilation(
    db: AsyncSession,
    *,
    user_id: str,
    template_id: str,
    status: str,
    error_class: str = "unknown",
    created_at: datetime | None = None,
    compilation_time: float | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO compilations "
            "(id, user_id, job_id, status, plan_family, template_id, error_class, created_at, compilation_time) "
            "VALUES (:id, :uid, :job_id, :status, 'pro', :template, :error_class, :created, :seconds)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "job_id": _token("test_template_health_compile"),
            "status": status,
            "template": template_id,
            "error_class": error_class,
            "created": created_at or datetime.now(timezone.utc) - timedelta(hours=1),
            "seconds": compilation_time,
        },
    )
    await db.commit()


async def _insert_health(
    db: AsyncSession,
    *,
    template_id: str,
    status: str,
    checked_at: datetime,
    error_class: str | None = None,
    visual_test: str = "unknown",
) -> None:
    await db.execute(
        text(
            "INSERT INTO template_health_checks "
            "(id, template_id, status, error_class, visual_test, source, idempotency_key, checked_at) "
            "VALUES (:id, :template, :status, :error_class, :visual, 'ci', :key, :checked)"
        ),
        {
            "id": str(uuid.uuid4()),
            "template": template_id,
            "status": status,
            "error_class": error_class,
            "visual": visual_test,
            "key": _token("test_health_insert"),
            "checked": checked_at,
        },
    )
    await db.commit()


async def _row_for(payload: dict, template_id: str) -> dict:
    return next(row for row in payload["templates"] if row["template_id"] == template_id)


class TestAdminTemplateHealth:
    async def test_admin_only_access(self, client: AsyncClient, db_session: AsyncSession):
        anonymous = await client.get("/admin/templates/health")
        assert anonymous.status_code == 401

        _user_id, user_headers = await _create_user(db_session, role="user")
        denied = await client.get("/admin/templates/health", headers=user_headers)
        assert denied.status_code == 403

        _support_id, support_headers = await _create_user(db_session, role="support")
        support_denied = await client.get("/admin/templates/health", headers=support_headers)
        assert support_denied.status_code == 403

        admin = await _admin_headers(db_session)
        allowed = await client.get("/admin/templates/health", headers=admin)
        assert allowed.status_code == 200, allowed.text
        assert "templates" in allowed.json()

    async def test_health_report_marks_missing_evidence_unknown(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        template_id = await _create_template(db_session)
        headers = await _admin_headers(db_session)
        response = await client.get("/admin/templates/health", headers=headers)
        assert response.status_code == 200, response.text
        row = await _row_for(response.json(), template_id)

        assert row["status"] == "unknown"
        assert row["recorded_status"] is None
        assert row["stale"] is False
        assert row["evidence_present"] is False
        assert row["status_reason"] == "no_evidence"
        assert row["last_verified_at"] is None
        assert row["evidence"]["ci_url"].startswith("https://github.com/sanskarpan/Latexy/actions/")

    async def test_stale_evidence_downgrades_to_unknown_but_keeps_history(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        template_id = await _create_template(db_session)
        await _insert_health(
            db_session,
            template_id=template_id,
            status="pass",
            checked_at=datetime.now(timezone.utc) - timedelta(hours=100),
        )
        headers = await _admin_headers(db_session)
        response = await client.get(
            "/admin/templates/health?stale_after_hours=72",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        row = await _row_for(response.json(), template_id)

        assert row["status"] == "unknown"
        assert row["recorded_status"] == "pass"
        assert row["stale"] is True
        assert row["status_reason"] == "stale_evidence"
        assert row["last_verified_at"] is not None

    async def test_retry_records_missing_asset_failure_and_audit(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        template_id = await _create_template(db_session)
        headers = await _admin_headers(db_session)
        request_id = _token("retry_missing")

        from app.services import storage_service

        monkeypatch.setattr(storage_service, "file_exists", lambda _key: False)

        response = await client.post(
            f"/admin/templates/{template_id}/health/retry",
            headers=headers,
            json={
                "reason": "Investigate missing template preview asset",
                "confirm": True,
                "request_id": request_id,
                "commit_sha": COMMIT_SHA,
                "ci_run_id": "123456",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "fail"
        assert payload["error_class"] == "missing_asset"
        assert payload["assets_present"] is False
        assert payload["commit_sha"] == COMMIT_SHA
        assert payload["ci_run_id"] == "123456"
        assert payload["duplicate"] is False
        assert payload["evidence"]["commit_url"].endswith(COMMIT_SHA)
        assert payload["evidence"]["ci_url"].endswith("/actions/runs/123456")
        assert payload["evidence"]["log_url"].endswith("/actions/runs/123456")
        assert SECRET_TEMPLATE_SOURCE not in json.dumps(payload)

        health = await client.get("/admin/templates/health", headers=headers)
        row = await _row_for(health.json(), template_id)
        assert row["status"] == "fail"
        assert row["error_class"] == "missing_asset"

        audit = (
            await db_session.execute(
                text(
                    "SELECT action, reason, after FROM admin_audit_log "
                    "WHERE target_type = 'template_health' AND target_id = :id"
                ),
                {"id": template_id},
            )
        ).all()
        assert len(audit) == 1
        assert audit[0].action == "template.health.retry"
        assert "missing template preview asset" in (audit[0].reason or "").lower()
        assert audit[0].after["status"] == "fail"
        assert audit[0].after["request_id"] == request_id

    async def test_retry_detects_repeated_compile_failures(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        template_id = await _create_template(db_session)
        user_id, _headers = await _create_user(db_session)
        for _ in range(5):
            await _seed_compilation(
                db_session,
                user_id=user_id,
                template_id=template_id,
                status="failed",
                error_class="syntax",
            )

        from app.services import storage_service

        monkeypatch.setattr(storage_service, "file_exists", lambda _key: True)
        headers = await _admin_headers(db_session)
        response = await client.post(
            f"/admin/templates/{template_id}/health/retry",
            headers=headers,
            json={
                "reason": "Re-check repeated compile failures",
                "confirm": True,
                "request_id": _token("retry_compile"),
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "fail"
        assert payload["error_class"] == "syntax"
        assert payload["compile_samples"] == 5
        assert payload["compile_failures"] == 5
        assert payload["status_detail"] == "recent_compile_failure_rate"

    async def test_retry_visual_failure_is_recorded(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        template_id = await _create_template(db_session)
        from app.services import storage_service

        monkeypatch.setattr(storage_service, "file_exists", lambda _key: True)
        headers = await _admin_headers(db_session)
        response = await client.post(
            f"/admin/templates/{template_id}/health/retry",
            headers=headers,
            json={
                "reason": "Visual regression assignment",
                "confirm": True,
                "request_id": _token("retry_visual"),
                "visual_test": "fail",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "fail"
        assert payload["error_class"] == "visual_regression"
        assert payload["visual_test"] == "fail"

        report = await client.get(
            f"/admin/templates/health?template={template_id}",
            headers=headers,
        )
        assert report.status_code == 200
        assert report.json()["templates"][0]["status"] == "fail"

    async def test_retry_is_idempotent_and_audits_once(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        template_id = await _create_template(db_session)
        from app.services import storage_service

        monkeypatch.setattr(storage_service, "file_exists", lambda _key: True)
        headers = await _admin_headers(db_session)
        request_id = _token("retry_replay")
        body = {
            "reason": "Replay the same verification request",
            "confirm": True,
            "request_id": request_id,
        }

        first = await client.post(
            f"/admin/templates/{template_id}/health/retry",
            headers=headers,
            json=body,
        )
        second = await client.post(
            f"/admin/templates/{template_id}/health/retry",
            headers=headers,
            json=body,
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["duplicate"] is False
        assert second.json()["duplicate"] is True
        assert first.json()["id"] == second.json()["id"]

        count = (
            await db_session.execute(
                text("SELECT count(*) FROM template_health_checks WHERE template_id = :id"),
                {"id": template_id},
            )
        ).scalar_one()
        assert count == 1
        audit_count = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM admin_audit_log "
                    "WHERE target_type = 'template_health' AND target_id = :id"
                ),
                {"id": template_id},
            )
        ).scalar_one()
        assert audit_count == 1

    async def test_health_report_never_returns_template_source_or_user_data(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        template_id = await _create_template(
            db_session,
            latex_content=SECRET_TEMPLATE_SOURCE,
        )
        _user_id, user_headers = await _create_user(db_session)
        await _insert_health(
            db_session,
            template_id=template_id,
            status="pass",
            checked_at=datetime.now(timezone.utc),
        )
        admin = await _admin_headers(db_session)
        response = await client.get("/admin/templates/health", headers=admin)
        assert response.status_code == 200, response.text
        body = response.text
        assert SECRET_TEMPLATE_SOURCE not in body
        assert "latex_content" not in body
        assert user_headers["Authorization"].split()[1] not in body

    async def test_retry_validates_template_confirm_and_request_id(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        missing = await client.post(
            f"/admin/templates/{uuid.uuid4()}/health/retry",
            headers=headers,
            json={
                "reason": "Missing confirmation",
                "request_id": _token("retry_missing_confirm"),
            },
        )
        assert missing.status_code == 422

        unknown = await client.post(
            f"/admin/templates/{uuid.uuid4()}/health/retry",
            headers=headers,
            json={
                "reason": "Unknown template",
                "confirm": True,
                "request_id": _token("retry_unknown"),
            },
        )
        assert unknown.status_code == 404

        template_id = await _create_template(db_session)
        short_request = await client.post(
            f"/admin/templates/{template_id}/health/retry",
            headers=headers,
            json={
                "reason": "Short request id",
                "confirm": True,
                "request_id": "short",
            },
        )
        assert short_request.status_code == 422

        bad_commit = await client.post(
            f"/admin/templates/{template_id}/health/retry",
            headers=headers,
            json={
                "reason": "Malformed commit",
                "confirm": True,
                "request_id": _token("retry_bad_commit"),
                "commit_sha": "not-a-sha",
            },
        )
        assert bad_commit.status_code == 422

    async def test_status_filter_and_inactive_templates(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        active_id = await _create_template(db_session)
        inactive_id = await _create_template(db_session, is_active=False)
        from app.services import storage_service

        monkeypatch.setattr(storage_service, "file_exists", lambda _key: True)
        headers = await _admin_headers(db_session)
        await client.post(
            f"/admin/templates/{active_id}/health/retry",
            headers=headers,
            json={
                "reason": "Verify active template",
                "confirm": True,
                "request_id": _token("retry_active"),
            },
        )

        passed = await client.get(
            "/admin/templates/health?status=pass",
            headers=headers,
        )
        assert passed.status_code == 200
        assert active_id in {row["template_id"] for row in passed.json()["templates"]}
        assert inactive_id not in {row["template_id"] for row in passed.json()["templates"]}

        with_inactive = await client.get(
            "/admin/templates/health?include_inactive=true",
            headers=headers,
        )
        assert with_inactive.status_code == 200
        inactive = await _row_for(with_inactive.json(), inactive_id)
        assert inactive["active"] is False
