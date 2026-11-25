"""Admin compile-error taxonomy: reconciliation, filters, links and access."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SECRET_COMPILE_TEXT = "private compile marker 2114 must never be returned"


def _token(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


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
            "VALUES (:id, :email, 'Compile Error User', :role, true, :plan, 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"test_compile_errors_{user_id.replace('-', '')}@example.com",
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


async def _create_template(db: AsyncSession, *, name: str) -> str:
    template_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO resume_templates (id, name, category, latex_content) "
            "VALUES (:id, :name, 'resume', '\\\\documentclass{article}')"
        ),
        {"id": template_id, "name": name},
    )
    await db.commit()
    return template_id


async def _seed_failure(
    db: AsyncSession,
    user_id: str,
    *,
    compiler: str,
    error_class: str | None,
    template_id: str | None = None,
    created_at: datetime | None = None,
    error_message: str = SECRET_COMPILE_TEXT,
) -> str:
    job_id = _token("compile_error")
    columns = [
        "id",
        "user_id",
        "job_id",
        "status",
        "compiler",
        "error_message",
        "template_id",
        "created_at",
    ]
    values = [
        ":id",
        ":uid",
        ":job",
        "'failed'",
        ":compiler",
        ":error_message",
        ":template",
        ":created",
    ]
    params = {
        "id": str(uuid.uuid4()),
        "uid": user_id,
        "job": job_id,
        "compiler": compiler,
        "error_message": error_message,
        "template": template_id,
        "created": created_at or datetime.now(timezone.utc) - timedelta(minutes=2),
    }
    if error_class is not None:
        columns.append("error_class")
        values.append(":error_class")
        params["error_class"] = error_class
    await db.execute(
        text(f"INSERT INTO compilations ({', '.join(columns)}) VALUES ({', '.join(values)})"),
        params,
    )
    await db.commit()
    return job_id


class TestCompileErrorTaxonomyEndpoint:
    async def test_class_totals_reconcile_and_templates_link(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        user_id, _ = await _create_user(db_session)
        compiler = _token("taxonomy_compiler")
        syntax_template_name = _token("Syntax Template")
        package_template_name = _token("Package Template")
        syntax_template = await _create_template(db_session, name=syntax_template_name)
        package_template = await _create_template(db_session, name=package_template_name)

        for _ in range(2):
            await _seed_failure(
                db_session,
                user_id,
                compiler=compiler,
                error_class="syntax",
                template_id=syntax_template,
                error_message="! Undefined control sequence.",
            )
        await _seed_failure(
            db_session,
            user_id,
            compiler=compiler,
            error_class="missing_package",
            template_id=package_template,
            error_message="! LaTeX Error: File `missing.sty' not found.",
        )
        await _seed_failure(
            db_session,
            user_id,
            compiler=compiler,
            error_class="timeout",
            error_message="compile_timeout",
        )
        # Omit the column to exercise the migration default for legacy rows.
        await _seed_failure(
            db_session,
            user_id,
            compiler=compiler,
            error_class=None,
            error_message="legacy failure without a classification",
        )

        response = await client.get(
            f"/admin/analytics/compile-errors?days=30&compiler={compiler}",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()

        assert payload["totals"]["failed_compilations"] == 5
        assert payload["totals"]["class_total"] == 5
        assert payload["totals"]["reconciled"] is True
        assert payload["totals"]["unknown_compilations"] == 1
        assert sum(item["count"] for item in payload["top_errors"]) == 5

        by_class = {item["error_class"]: item for item in payload["top_errors"]}
        assert by_class["syntax"]["count"] == 2
        assert by_class["syntax"]["affected_templates"][0]["template_id"] == syntax_template
        assert by_class["syntax"]["affected_templates"][0]["template_name"] == syntax_template_name
        assert by_class["syntax"]["affected_templates"][0]["href"] == (f"/templates?preview={syntax_template}")
        assert by_class["missing_package"]["affected_templates"][0]["template_id"] == package_template
        assert by_class["timeout"]["unattributed_templates"] == 1
        assert by_class["unknown"]["count"] == 1

        # The endpoint must never echo raw compiler messages or document text.
        assert SECRET_COMPILE_TEXT not in response.text

        # Trend buckets reconcile to the same failed-compilation total.
        assert sum(point["failed_compilations"] for point in payload["trend"]) == 5
        assert all(point["failed_compilations"] == sum(point["by_class"].values()) for point in payload["trend"])

    async def test_days_range_and_class_filter(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        user_id, _ = await _create_user(db_session)
        compiler = _token("taxonomy_range")

        await _seed_failure(
            db_session,
            user_id,
            compiler=compiler,
            error_class="syntax",
            created_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        await _seed_failure(
            db_session,
            user_id,
            compiler=compiler,
            error_class="timeout",
            created_at=datetime.now(timezone.utc) - timedelta(days=45),
        )

        thirty = await client.get(
            f"/admin/analytics/compile-errors?days=30&compiler={compiler}",
            headers=headers,
        )
        assert thirty.status_code == 200, thirty.text
        assert thirty.json()["totals"]["failed_compilations"] == 1
        assert thirty.json()["filters"]["error_class"] is None

        ninety = await client.get(
            f"/admin/analytics/compile-errors?days=90&compiler={compiler}",
            headers=headers,
        )
        assert ninety.status_code == 200, ninety.text
        assert ninety.json()["totals"]["failed_compilations"] == 2

        filtered = await client.get(
            f"/admin/analytics/compile-errors?days=90&compiler={compiler}&error_class=syntax",
            headers=headers,
        )
        assert filtered.status_code == 200, filtered.text
        filtered_payload = filtered.json()
        assert filtered_payload["filters"]["error_class"] == "syntax"
        assert [item["error_class"] for item in filtered_payload["top_errors"]] == ["syntax"]
        # Totals still describe the full scope so reconciliation is visible.
        assert filtered_payload["totals"]["failed_compilations"] == 2
        assert filtered_payload["totals"]["class_total"] == 2

        invalid = await client.get(
            "/admin/analytics/compile-errors?error_class=not-a-class",
            headers=headers,
        )
        assert invalid.status_code == 422

    async def test_endpoint_is_admin_only(self, client: AsyncClient, db_session: AsyncSession):
        _user_id, headers = await _create_user(db_session, role="user")
        response = await client.get("/admin/analytics/compile-errors", headers=headers)
        assert response.status_code == 403

        anonymous = await client.get("/admin/analytics/compile-errors")
        assert anonymous.status_code in {401, 403}
