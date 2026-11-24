"""Admin compile-latency percentiles, filters, gaps and raw reconciliation."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Compilation, Resume, ResumeTemplate

VALID_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\begin{document}
Compile latency fixture
\end{document}
"""


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
            "VALUES (:id, :email, 'Latency User', :role, true, :plan, 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"test_compile_latency_{user_id.replace('-', '')}@example.com",
            "role": role,
            "plan": plan,
        },
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


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    _user_id, headers = await _create_user(db, role="admin", plan="pro")
    return headers


async def _seed_compile(
    db: AsyncSession,
    user_id: str,
    *,
    plan: str | None,
    compiler: str | None,
    template: str | None,
    duration: float | None,
    created_at: datetime | None = None,
) -> str:
    job_id = f"latency_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO compilations (id, user_id, job_id, status, compilation_time, "
            "plan_family, compiler, template_id, created_at) "
            "VALUES (:id, :uid, :job, 'completed', :duration, :plan, :compiler, :template, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "job": job_id,
            "duration": duration,
            "plan": plan,
            "compiler": compiler,
            "template": template,
            "created": created_at or datetime.now(timezone.utc) - timedelta(minutes=1),
        },
    )
    await db.commit()
    return job_id


def _raw_count_query() -> str:
    return (
        "SELECT COUNT(*) FROM compilations "
        "WHERE compiler = :compiler AND status = 'completed' "
        "AND compilation_time IS NOT NULL AND compilation_time >= 0 "
        "AND created_at >= :start AND created_at < :end"
    )


class TestCompileLatencyPercentiles:
    async def test_percentile_math_and_reconciliation_to_raw_rows(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        user_id, _ = await _create_user(db_session)
        compiler = _token("compiler")
        plan = _token("plan")
        template = str(uuid.uuid4())
        for duration in (1.0, 2.0, 3.0, 4.0):
            await _seed_compile(
                db_session,
                user_id,
                plan=plan,
                compiler=compiler,
                template=template,
                duration=duration,
            )
        # Outside the selected window: must not change the percentiles.
        await _seed_compile(
            db_session,
            user_id,
            plan=plan,
            compiler=compiler,
            template=template,
            duration=500.0,
            created_at=datetime.now(timezone.utc) - timedelta(days=45),
        )

        response = await client.get(
            f"/admin/analytics/compile-latency?days=30&compiler={compiler}",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["days"] == 30
        assert body["filters"]["compiler"] == compiler
        assert body["sparse_threshold"] == 20
        assert body["duration_unit"] == "seconds"
        assert body["overall"]["samples"] == 4
        assert body["overall"]["p50_seconds"] == pytest.approx(2.5)
        assert body["overall"]["p95_seconds"] == pytest.approx(3.85)
        assert body["overall"]["p99_seconds"] == pytest.approx(3.97)
        assert body["overall"]["mean_seconds"] == pytest.approx(2.5)
        assert body["overall"]["max_seconds"] == pytest.approx(4.0)
        assert body["overall"]["sparse"] is True
        assert body["overall"]["sample_status"] == "insufficient_samples"

        assert [bucket["value"] for bucket in body["by_plan"]] == [plan]
        assert [bucket["value"] for bucket in body["by_compiler"]] == [compiler]
        assert [bucket["value"] for bucket in body["by_template"]] == [template]
        assert body["by_compiler"][0]["p95_seconds"] == pytest.approx(3.85)
        assert body["missing_dimensions"] == {"plan": 0, "compiler": 0, "template": 0}

        start = datetime.fromisoformat(body["window"]["start"])
        end = datetime.fromisoformat(body["window"]["end"])
        raw = await db_session.scalar(
            text(_raw_count_query()),
            {"compiler": compiler, "start": start, "end": end},
        )
        assert raw == body["totals"]["timed_compilations"] == 4
        assert body["totals"]["completed_compilations"] == 4
        assert sum(bucket["samples"] for bucket in body["by_plan"]) == raw
        assert sum(bucket["samples"] for bucket in body["by_compiler"]) == raw
        assert sum(bucket["samples"] for bucket in body["by_template"]) == raw

    async def test_dimension_filters_are_independent(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        user_id, _ = await _create_user(db_session)
        first = {
            "plan": _token("plan_a"),
            "compiler": _token("compiler_a"),
            "template": str(uuid.uuid4()),
        }
        second = {
            "plan": _token("plan_b"),
            "compiler": _token("compiler_b"),
            "template": str(uuid.uuid4()),
        }
        await _seed_compile(db_session, user_id, duration=1.0, **first)
        await _seed_compile(db_session, user_id, duration=2.0, **first)
        await _seed_compile(db_session, user_id, duration=30.0, **second)
        await _seed_compile(db_session, user_id, duration=40.0, **second)

        by_plan = await client.get(
            f"/admin/analytics/compile-latency?days=30&plan={first['plan']}",
            headers=headers,
        )
        assert by_plan.status_code == 200
        assert {bucket["value"] for bucket in by_plan.json()["by_plan"]} == {first["plan"]}
        assert by_plan.json()["overall"]["samples"] == 2

        by_compiler = await client.get(
            f"/admin/analytics/compile-latency?days=30&compiler={second['compiler']}",
            headers=headers,
        )
        assert by_compiler.status_code == 200
        assert {bucket["value"] for bucket in by_compiler.json()["by_compiler"]} == {
            second["compiler"]
        }
        assert by_compiler.json()["overall"]["p50_seconds"] == pytest.approx(35.0)

        by_template = await client.get(
            f"/admin/analytics/compile-latency?days=30&template={first['template']}",
            headers=headers,
        )
        assert by_template.status_code == 200
        assert {bucket["value"] for bucket in by_template.json()["by_template"]} == {
            first["template"]
        }
        assert by_template.json()["overall"]["samples"] == 2

        combined = await client.get(
            "/admin/analytics/compile-latency"
            f"?days=30&plan={first['plan']}&compiler={second['compiler']}",
            headers=headers,
        )
        assert combined.status_code == 200
        assert combined.json()["overall"]["samples"] == 0
        assert combined.json()["by_plan"] == []

    async def test_missing_dimensions_are_counted_and_not_guessed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        user_id, _ = await _create_user(db_session)
        compiler = _token("missing")
        plan_a = _token("plan_a")
        plan_b = _token("plan_b")
        template_a = str(uuid.uuid4())
        template_b = str(uuid.uuid4())

        await _seed_compile(
            db_session, user_id, plan=plan_a, compiler=compiler, template=template_a, duration=1.0
        )
        await _seed_compile(
            db_session, user_id, plan=None, compiler=compiler, template=template_a, duration=2.0
        )
        await _seed_compile(
            db_session, user_id, plan=plan_a, compiler=compiler, template=None, duration=3.0
        )
        await _seed_compile(
            db_session, user_id, plan=plan_b, compiler=compiler, template=template_b, duration=4.0
        )
        # Missing compiler is visible when filtering only by plan.
        await _seed_compile(
            db_session, user_id, plan=plan_a, compiler=None, template=template_a, duration=5.0
        )

        by_compiler = await client.get(
            f"/admin/analytics/compile-latency?days=30&compiler={compiler}",
            headers=headers,
        )
        assert by_compiler.status_code == 200
        body = by_compiler.json()
        assert body["overall"]["samples"] == 4
        assert body["missing_dimensions"] == {"plan": 1, "compiler": 0, "template": 1}
        assert sum(bucket["samples"] for bucket in body["by_plan"]) == 3
        assert sum(bucket["samples"] for bucket in body["by_template"]) == 3
        assert body["totals"]["missing_dimension_fields"] == 2

        by_plan = await client.get(
            f"/admin/analytics/compile-latency?days=30&plan={plan_a}",
            headers=headers,
        )
        assert by_plan.status_code == 200
        plan_body = by_plan.json()
        assert plan_body["overall"]["samples"] == 3
        assert plan_body["missing_dimensions"]["compiler"] == 1
        assert plan_body["missing_dimensions"]["template"] == 1

    async def test_sparse_buckets_are_marked_and_slowest_is_ranked(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        user_id, _ = await _create_user(db_session)
        plan = _token("shared_plan")
        dense_compiler = _token("dense")
        sparse_compiler = _token("sparse")
        template = str(uuid.uuid4())

        for duration in range(1, 21):
            await _seed_compile(
                db_session,
                user_id,
                plan=plan,
                compiler=dense_compiler,
                template=template,
                duration=float(duration),
            )
        for duration in (100.0, 110.0, 120.0):
            await _seed_compile(
                db_session,
                user_id,
                plan=plan,
                compiler=sparse_compiler,
                template=template,
                duration=duration,
            )

        response = await client.get(
            f"/admin/analytics/compile-latency?days=30&plan={plan}",
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()

        buckets = {bucket["value"]: bucket for bucket in body["by_compiler"]}
        assert buckets[dense_compiler]["samples"] == 20
        assert buckets[dense_compiler]["sparse"] is False
        assert buckets[dense_compiler]["sample_status"] == "ok"
        assert buckets[sparse_compiler]["samples"] == 3
        assert buckets[sparse_compiler]["sparse"] is True
        assert buckets[sparse_compiler]["sample_status"] == "insufficient_samples"
        assert body["by_plan"][0]["sparse"] is False

        slowest = body["slowest"]
        assert slowest[0]["dimension"] == "compiler"
        assert slowest[0]["value"] == sparse_compiler
        assert slowest[0]["sparse"] is True
        assert slowest[0]["p95_seconds"] == pytest.approx(119.0)


class TestCompileLatencyAccess:
    async def test_requires_admin_and_rejects_malformed_template(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _user_id, user_headers = await _create_user(db_session, plan="free")
        forbidden = await client.get("/admin/analytics/compile-latency", headers=user_headers)
        assert forbidden.status_code == 403

        admin_headers = await _admin_headers(db_session)
        malformed = await client.get(
            "/admin/analytics/compile-latency?template=not-a-uuid",
            headers=admin_headers,
        )
        assert malformed.status_code == 422


class TestCompileAttribution:
    @pytest.mark.parametrize(("plan", "plan_family"), [("free", "free"), ("pro", "pro")])
    async def test_first_party_submission_records_server_side_dimensions(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        plan: str,
        plan_family: str,
    ):
        user_id, headers = await _create_user(db_session, plan=plan)
        template = ResumeTemplate(
            name=f"test_tmpl_latency_{uuid.uuid4().hex[:8]}",
            category="test",
            latex_content=VALID_LATEX,
            document_type="resume",
        )
        db_session.add(template)
        await db_session.flush()
        resume = Resume(
            user_id=user_id,
            title="Latency attribution",
            latex_content=VALID_LATEX + "% saved revision\n",
            selected_template_id=template.id,
            resume_settings={"compiler": "lualatex"},
        )
        db_session.add(resume)
        await db_session.commit()

        with patch("app.api.job_routes.submit_latex_compilation", return_value=None):
            response = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "latex_compilation",
                    "latex_content": VALID_LATEX,
                    "compiler": "xelatex",
                    "metadata": {"resume_id": resume.id},
                },
                headers=headers,
            )
        assert response.status_code == 200, response.text
        job_id = response.json()["job_id"]
        compilation = (
            await db_session.execute(select(Compilation).where(Compilation.job_id == job_id))
        ).scalar_one()
        assert compilation.plan_family == plan_family
        assert compilation.compiler == "xelatex"
        assert compilation.template_id == template.id
        assert compilation.resume_id == resume.id

    async def test_developer_compile_records_plan_family_and_compiler(self):
        from app.api.public_api_routes import V1CompileRequest, compile_v1

        db = MagicMock()
        db.flush = AsyncMock()
        db.delete = AsyncMock()
        api_key = SimpleNamespace(user_id="developer-user", id="developer-key")
        with (
            patch(
                "app.api.public_api_routes._authorize",
                AsyncMock(return_value=("student", None)),
            ),
            patch("app.api.public_api_routes._write_initial_redis_state", AsyncMock()),
            patch("app.api.public_api_routes._mark_dispatch_started", AsyncMock()),
            patch("app.api.public_api_routes._mark_dispatch_accepted", AsyncMock()),
            patch("app.api.public_api_routes.submit_latex_compilation"),
        ):
            response = await compile_v1(
                V1CompileRequest(latex_content=VALID_LATEX, compiler="xelatex"),
                api_key=api_key,
                db=db,
            )

        assert response.status == "queued"
        records = [
            call.args[0]
            for call in db.add.call_args_list
            if isinstance(call.args[0], Compilation)
        ]
        assert len(records) == 1
        assert records[0].plan_family == "pro"
        assert records[0].compiler == "xelatex"
        assert records[0].template_id is None
