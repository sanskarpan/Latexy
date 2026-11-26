"""Admin template catalog performance: tracking, ranking, privacy and CSV."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SECRET_TEMPLATE_SOURCE = "SECRET_TEMPLATE_SOURCE_2143_MUST_NOT_LEAK"


def _token(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _email(prefix: str) -> str:
    return f"test_template_perf_{prefix}_{uuid.uuid4().hex[:8]}@example.com"


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
            "VALUES (:id, :email, 'Template Perf User', :role, true, :plan, 'active', false)"
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
    _user_id, headers = await _create_user(db, role="admin", plan="pro")
    return headers


async def _create_template(
    db: AsyncSession,
    *,
    name: str,
    category: str = "finance",
    latex_content: str = "\\documentclass{article}\\begin{document}test\\end{document}",
) -> str:
    template_id = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO resume_templates (id, name, category, latex_content) VALUES (:id, :name, :category, :latex)"),
        {"id": template_id, "name": name, "category": category, "latex": latex_content},
    )
    await db.commit()
    return template_id


async def _seed_event(
    db: AsyncSession,
    *,
    user_id: str,
    template_id: str,
    action: str,
    plan: str,
    created_at: datetime | None = None,
    event_id: str | None = None,
    extra: dict | None = None,
) -> None:
    metadata: dict = {"template_id": template_id, "plan": plan}
    if event_id:
        metadata["event_id"] = event_id
    if extra:
        metadata.update(extra)
    await db.execute(
        text(
            "INSERT INTO usage_analytics (id, user_id, action, resource_type, event_metadata, created_at) "
            "VALUES (:id, :uid, :action, 'template', CAST(:metadata AS JSONB), :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "action": action,
            "metadata": json.dumps(metadata),
            "created": created_at or datetime.now(timezone.utc) - timedelta(hours=2),
        },
    )
    await db.commit()


async def _seed_compilation(
    db: AsyncSession,
    *,
    user_id: str,
    template_id: str | None,
    plan_family: str,
    status: str,
    created_at: datetime | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO compilations (id, user_id, job_id, status, plan_family, template_id, created_at) "
            "VALUES (:id, :uid, :job_id, :status, :plan, :template, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "job_id": _token("test_template_perf_compile"),
            "status": status,
            "plan": plan_family,
            "template": template_id,
            "created": created_at or datetime.now(timezone.utc) - timedelta(hours=1),
        },
    )
    await db.commit()


async def _seed_view_event(
    db: AsyncSession,
    *,
    user_id: str,
    template_id: str,
    plan: str,
    created_at: datetime | None = None,
) -> None:
    await _seed_event(
        db,
        user_id=user_id,
        template_id=template_id,
        action="template_view",
        plan=plan,
        created_at=created_at,
    )


class TestTemplatePerformanceEndpoint:
    async def test_admin_only_access(self, client: AsyncClient, db_session: AsyncSession):
        _user_id, user_headers = await _create_user(db_session, role="user")
        denied = await client.get("/admin/templates/performance", headers=user_headers)
        assert denied.status_code == 403

        _support_id, support_headers = await _create_user(db_session, role="support")
        support_denied = await client.get("/admin/templates/performance", headers=support_headers)
        assert support_denied.status_code == 403

        anonymous = await client.get("/admin/templates/performance")
        assert anonymous.status_code == 401

        admin = await _admin_headers(db_session)
        allowed = await client.get("/admin/templates/performance", headers=admin)
        assert allowed.status_code == 200, allowed.text

    async def test_template_events_are_idempotent_and_plan_is_server_derived(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, headers = await _create_user(db_session, plan="pro")
        template_id = await _create_template(db_session, name=f"test_tmpl_{_token('idempotent')}")
        event_id = uuid.uuid4().hex

        first = await client.post(
            f"/templates/{template_id}/events",
            headers=headers,
            json={"event": "view", "event_id": event_id},
        )
        second = await client.post(
            f"/templates/{template_id}/events",
            headers=headers,
            json={"event": "view", "event_id": event_id},
        )
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()["duplicate"] is False
        assert second.json()["duplicate"] is True
        assert first.json()["plan"] == "pro"

        count = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM usage_analytics "
                    "WHERE user_id = :uid AND action = 'template_view' "
                    "AND event_metadata->>'event_id' = :event_id"
                ),
                {"uid": user_id, "event_id": event_id},
            )
        ).scalar_one()
        assert count == 1

        stored = (
            await db_session.execute(
                text(
                    "SELECT event_metadata FROM usage_analytics "
                    "WHERE user_id = :uid AND action = 'template_view' "
                    "AND event_metadata->>'event_id' = :event_id"
                ),
                {"uid": user_id, "event_id": event_id},
            )
        ).scalar_one()
        assert stored["template_id"] == template_id
        assert stored["plan"] == "pro"
        assert "document_content" not in stored

    async def test_compile_event_is_idempotent_and_carries_template_attribution(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, headers = await _create_user(db_session, plan="pro")
        template_id = await _create_template(db_session, name=f"test_tmpl_{_token('compile_event')}")
        job_id = _token("test_template_perf_job")
        await db_session.execute(
            text(
                "INSERT INTO compilations (id, user_id, job_id, status, plan_family, template_id) "
                "VALUES (:id, :uid, :job_id, 'completed', 'pro', :template)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "job_id": job_id,
                "template": template_id,
            },
        )
        await db_session.commit()

        for _ in range(2):
            response = await client.post(
                f"/analytics/track/compilation?compilation_id={job_id}&status=completed",
                headers=headers,
            )
            assert response.status_code == 201, response.text

        count = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM usage_analytics "
                    "WHERE user_id = :uid AND action = 'compile' "
                    "AND event_metadata->>'compilation_id' = :job_id"
                ),
                {"uid": user_id, "job_id": job_id},
            )
        ).scalar_one()
        assert count == 1

        metadata = (
            await db_session.execute(
                text(
                    "SELECT event_metadata FROM usage_analytics "
                    "WHERE user_id = :uid AND action = 'compile' "
                    "AND event_metadata->>'compilation_id' = :job_id"
                ),
                {"uid": user_id, "job_id": job_id},
            )
        ).scalar_one()
        assert metadata["template_id"] == template_id
        assert metadata["plan"] == "pro"
        assert metadata["status"] == "completed"

    async def test_ranking_reconciles_with_compilations_and_orders_by_exports(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        plan = f"test_plan_{uuid.uuid4().hex[:8]}"
        users = [await _create_user(db_session, plan="pro") for _ in range(10)]
        user_ids = [item[0] for item in users]

        exporting_template = await _create_template(db_session, name=f"test_tmpl_{_token('export_leader')}")
        compiling_template = await _create_template(db_session, name=f"test_tmpl_{_token('compile_leader')}")

        # Five users on each template so both rows clear the suppression floor.
        for index, user_id in enumerate(user_ids[:5]):
            await _seed_view_event(db_session, user_id=user_id, template_id=exporting_template, plan=plan)
            await _seed_event(
                db_session,
                user_id=user_id,
                template_id=exporting_template,
                action="template_use",
                plan=plan,
            )
            if index < 5:
                await _seed_event(
                    db_session,
                    user_id=user_id,
                    template_id=exporting_template,
                    action="export",
                    plan=plan,
                )
            await _seed_compilation(
                db_session,
                user_id=user_id,
                template_id=exporting_template,
                plan_family=plan,
                status="completed",
            )
            await _seed_compilation(
                db_session,
                user_id=user_id,
                template_id=exporting_template,
                plan_family=plan,
                status="failed",
            )

        for user_id in user_ids[5:]:
            await _seed_view_event(db_session, user_id=user_id, template_id=compiling_template, plan=plan)
            await _seed_compilation(
                db_session,
                user_id=user_id,
                template_id=compiling_template,
                plan_family=plan,
                status="completed",
            )

        # Outside the selected window: must not affect the 30-day report.
        await _seed_event(
            db_session,
            user_id=user_ids[0],
            template_id=compiling_template,
            action="export",
            plan=plan,
            created_at=datetime.now(timezone.utc) - timedelta(days=45),
        )
        await _seed_compilation(
            db_session,
            user_id=user_ids[0],
            template_id=compiling_template,
            plan_family=plan,
            status="completed",
            created_at=datetime.now(timezone.utc) - timedelta(days=45),
        )

        headers = await _admin_headers(db_session)
        response = await client.get(
            f"/admin/templates/performance?days=30&plan={plan}",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()

        assert [row["template_id"] for row in payload["ranking"]][:2] == [
            exporting_template,
            compiling_template,
        ]
        leader = payload["ranking"][0]
        assert leader["exports"] == 5
        assert leader["uses"] == 5
        assert leader["views"] == 5
        assert leader["compile_success"] == 5
        assert leader["compile_failed"] == 5
        assert leader["success_rate"] == 50.0
        assert leader["users"] == 5

        compile_leader = payload["ranking"][1]
        assert compile_leader["exports"] == 0
        assert compile_leader["compile_success"] == 5
        assert compile_leader["users"] == 5

        assert payload["totals"]["exports"] == 5
        assert payload["totals"]["compile_success"] == 10
        assert payload["totals"]["compile_failed"] == 5
        assert payload["reconciliation"]["source"] == "compilations"
        assert payload["reconciliation"]["reconciled"] is True
        assert payload["reconciliation"]["compilation_success"] == 10
        assert payload["reconciliation"]["compilation_failed"] == 5
        assert payload["reconciliation"]["ranked_compile_success"] == 10
        assert payload["reconciliation"]["suppressed_compile_success"] == 0

        # Trend buckets reconcile to the same attributed compilation totals.
        assert sum(point["exports"] for point in payload["trend"]) == 5
        assert sum(point["compile_success"] for point in payload["trend"]) == 10
        assert sum(point["compile_failed"] for point in payload["trend"]) == 5

        # Deleting the catalog row keeps historical aggregates visible, labelled
        # as deleted, because compilation/event rows are deliberately not FK-bound.
        await db_session.execute(
            text("DELETE FROM resume_templates WHERE id = :id"),
            {"id": exporting_template},
        )
        await db_session.commit()
        db_session.expire_all()

        after_delete = await client.get(
            f"/admin/templates/performance?days=30&plan={plan}",
            headers=headers,
        )
        assert after_delete.status_code == 200, after_delete.text
        deleted_row = next(row for row in after_delete.json()["ranking"] if row["template_id"] == exporting_template)
        assert deleted_row["deleted"] is True
        assert deleted_row["template_name"] is None
        assert deleted_row["exports"] == 5
        assert deleted_row["compile_success"] == 5

        # The public template source is never part of the aggregate response.
        secret_template = await _create_template(
            db_session,
            name=f"test_tmpl_{_token('secret')}",
            latex_content=SECRET_TEMPLATE_SOURCE,
        )
        for user_id in user_ids[:5]:
            await _seed_view_event(db_session, user_id=user_id, template_id=secret_template, plan=plan)
        leak_check = await client.get(
            f"/admin/templates/performance?days=30&plan={plan}",
            headers=headers,
        )
        assert leak_check.status_code == 200
        assert SECRET_TEMPLATE_SOURCE not in leak_check.text
        assert "latex_content" not in leak_check.text
        for user_id in user_ids:
            assert user_id not in leak_check.text

    async def test_suppression_hides_small_template_cohorts(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"test_plan_{uuid.uuid4().hex[:8]}"
        users = [await _create_user(db_session, plan="pro") for _ in range(9)]
        user_ids = [item[0] for item in users]

        small_template = await _create_template(db_session, name=f"test_tmpl_{_token('small')}")
        visible_template = await _create_template(db_session, name=f"test_tmpl_{_token('visible')}")

        for user_id in user_ids[:4]:
            await _seed_view_event(db_session, user_id=user_id, template_id=small_template, plan=plan)
            await _seed_compilation(
                db_session,
                user_id=user_id,
                template_id=small_template,
                plan_family=plan,
                status="completed",
            )
        for user_id in user_ids[4:]:
            await _seed_view_event(db_session, user_id=user_id, template_id=visible_template, plan=plan)
            await _seed_compilation(
                db_session,
                user_id=user_id,
                template_id=visible_template,
                plan_family=plan,
                status="completed",
            )

        headers = await _admin_headers(db_session)
        response = await client.get(
            f"/admin/templates/performance?days=30&plan={plan}",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()

        assert [row["template_id"] for row in payload["ranking"]] == [visible_template]
        assert payload["suppressed_templates"] == 1
        assert payload["totals"]["compile_success"] == 5
        assert payload["reconciliation"]["suppressed_compile_success"] == 4
        assert payload["reconciliation"]["reconciled"] is True

        # A filter that leaves only the four-user cohort suppresses the whole view.
        filtered = await client.get(
            f"/admin/templates/performance?days=30&plan={plan}&template={small_template}",
            headers=headers,
        )
        assert filtered.status_code == 200
        assert filtered.json()["ranking"] == []
        assert filtered.json()["suppressed"] is True
        assert filtered.json()["suppressed_templates"] == 1

    async def test_csv_export_is_aggregate_only(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"test_plan_{uuid.uuid4().hex[:8]}"
        users = [await _create_user(db_session, plan="pro") for _ in range(5)]
        user_ids = [item[0] for item in users]
        template_id = await _create_template(db_session, name=f"test_tmpl_{_token('csv')}")
        for user_id in user_ids:
            await _seed_view_event(db_session, user_id=user_id, template_id=template_id, plan=plan)
            await _seed_event(
                db_session,
                user_id=user_id,
                template_id=template_id,
                action="export",
                plan=plan,
            )
            await _seed_compilation(
                db_session,
                user_id=user_id,
                template_id=template_id,
                plan_family=plan,
                status="completed",
            )

        headers = await _admin_headers(db_session)
        response = await client.get(
            f"/admin/templates/performance?days=30&plan={plan}&format=csv",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        assert 'attachment; filename="template-performance-' in response.headers["content-disposition"]

        lines = [line for line in response.text.splitlines() if line]
        assert lines[0].split(",")[:4] == ["rank", "template_id", "template_name", "category"]
        assert len(lines) == 2
        cells = lines[1].split(",")
        assert cells[0] == "1"
        assert cells[1] == template_id
        assert cells[5] == "5"  # users
        assert cells[6] == "5"  # views
        assert cells[9] == "5"  # exports
        assert cells[10] == "5"  # compile success
        for user_id in user_ids:
            assert user_id not in response.text
        assert SECRET_TEMPLATE_SOURCE not in response.text

        assert (
            await client.get(
                f"/admin/templates/performance?days=30&plan={plan}",
                headers={"Authorization": "Bearer invalid"},
            )
        ).status_code == 401

    async def test_invalid_range_and_template_filter_return_422(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        invalid_range = await client.get(
            "/admin/templates/performance?start_date=2026-02-01&end_date=2026-01-01",
            headers=headers,
        )
        assert invalid_range.status_code == 422
        invalid_template = await client.get(
            "/admin/templates/performance?template=not-a-uuid",
            headers=headers,
        )
        assert invalid_template.status_code == 422
