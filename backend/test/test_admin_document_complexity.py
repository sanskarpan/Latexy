"""Document-complexity metrics: buckets, reconciliation, suppression, privacy."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Compilation, JobFinalization, User
from app.services.compile_complexity import (
    MAX_PAGE_COUNT,
    MAX_SECTION_COUNT,
    count_sections,
    latency_bucket,
    normalize_page_count,
    page_bucket,
    section_bucket,
)

SECRET_ERROR_TEXT = "private compile marker 2078 must never be returned"
SECRET_LATEX = (
    r"\documentclass{article}\begin{document}"
    r"\section{Private experience}secret document marker\end{document}"
)


def _token(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
    name: str = "Complexity User",
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    token = f"test_sess_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, :name, :role, true, :plan, 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"test_complexity_{user_id.replace('-', '')}@example.com",
            "name": name,
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


async def _seed_compile(
    db: AsyncSession,
    user_id: str,
    *,
    status: str = "completed",
    plan: str | None = "pro",
    compiler: str | None = "pdflatex",
    template: str | None = None,
    page_count: int | None = None,
    section_count: int | None = None,
    duration: float | None = None,
    error_class: str | None = None,
    error_message: str | None = None,
    created_at: datetime | None = None,
) -> str:
    job_id = f"complexity_{uuid.uuid4().hex}"
    columns = [
        "id",
        "user_id",
        "job_id",
        "status",
        "plan_family",
        "compiler",
        "template_id",
        "page_count",
        "section_count",
        "compilation_time",
        "created_at",
    ]
    values = [
        ":id",
        ":uid",
        ":job",
        ":status",
        ":plan",
        ":compiler",
        ":template",
        ":page_count",
        ":section_count",
        ":duration",
        ":created",
    ]
    params = {
        "id": str(uuid.uuid4()),
        "uid": user_id,
        "job": job_id,
        "status": status,
        "plan": plan,
        "compiler": compiler,
        "template": template,
        "page_count": page_count,
        "section_count": section_count,
        "duration": duration,
        "created": created_at or datetime.now(timezone.utc) - timedelta(minutes=1),
    }
    if error_class is not None:
        columns.append("error_class")
        values.append(":error_class")
        params["error_class"] = error_class
    if error_message is not None:
        columns.append("error_message")
        values.append(":error_message")
        params["error_message"] = error_message
    await db.execute(
        text(f"INSERT INTO compilations ({', '.join(columns)}) VALUES ({', '.join(values)})"),
        params,
    )
    await db.commit()
    return job_id


class TestComplexityBuckets:
    @pytest.mark.parametrize(
        ("pages", "expected"),
        [
            (1, "1"),
            (2, "2"),
            (3, "3-4"),
            (4, "3-4"),
            (5, "5-6"),
            (6, "5-6"),
            (7, "7-10"),
            (10, "7-10"),
            (11, "11-20"),
            (20, "11-20"),
            (21, "21-50"),
            (50, "21-50"),
            (51, "51-100"),
            (100, "51-100"),
            (101, "101-250"),
            (250, "101-250"),
            (251, "251+"),
            (MAX_PAGE_COUNT, "251+"),
        ],
    )
    def test_page_bucket_boundaries(self, pages, expected):
        assert page_bucket(pages) == expected

    @pytest.mark.parametrize("value", [0, -1, MAX_PAGE_COUNT + 1, True, 2.5, "3", None])
    def test_page_count_bounds_reject_invalid_values(self, value):
        assert normalize_page_count(value) is None
        assert page_bucket(value) is None

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "<1s"),
            (0.999, "<1s"),
            (1.0, "1-2s"),
            (1.999, "1-2s"),
            (2.0, "2-5s"),
            (4.999, "2-5s"),
            (5.0, "5-10s"),
            (10.0, "10-30s"),
            (30.0, "30-60s"),
            (59.999, "30-60s"),
            (60.0, "60s+"),
        ],
    )
    def test_latency_bucket_boundaries(self, seconds, expected):
        assert latency_bucket(seconds) == expected

    @pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf"), True, "2", None])
    def test_latency_bucket_rejects_invalid_values(self, value):
        assert latency_bucket(value) is None

    @pytest.mark.parametrize(
        ("sections", "expected"),
        [
            (0, "0"),
            (1, "1-2"),
            (2, "1-2"),
            (3, "3-5"),
            (5, "3-5"),
            (6, "6-10"),
            (10, "6-10"),
            (11, "11-20"),
            (20, "11-20"),
            (21, "21-50"),
            (50, "21-50"),
            (51, "51+"),
        ],
    )
    def test_section_bucket_boundaries(self, sections, expected):
        assert section_bucket(sections) == expected

    def test_count_sections_ignores_comments_and_subsections(self):
        source = r"""
\section{Experience}
\section*{Skills}
% \section{Commented out}
\subsection{Education}
Text 100\% complete \section{After literal percent}
"""
        assert count_sections(source) == 3
        assert count_sections("") is None
        assert count_sections(None) is None

    def test_count_sections_is_capped(self):
        assert count_sections(r"\section{Repeated}" * (MAX_SECTION_COUNT + 25)) == MAX_SECTION_COUNT

    def test_migration_declares_bounded_additive_columns(self):
        path = Path(__file__).parents[1] / "alembic/versions/0092_document_complexity.py"
        spec = importlib.util.spec_from_file_location("document_complexity_migration", path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        calls: list[tuple] = []

        class FakeOp:
            def add_column(self, table: str, column) -> None:
                calls.append(("add_column", table, column))

            def drop_column(self, table: str, column: str) -> None:
                calls.append(("drop_column", table, column))

            def create_check_constraint(self, name: str, table: str, condition: str) -> None:
                calls.append(("create_check_constraint", name, table, condition))

            def drop_constraint(self, name: str, table: str, type_: str) -> None:
                calls.append(("drop_constraint", name, table, type_))

        assert migration.revision == "0092_document_complexity"
        assert migration.down_revision == "0091_dunning_history"
        migration.op = FakeOp()
        migration.upgrade()
        added = {call[2].name: call[2] for call in calls if call[0] == "add_column"}
        assert set(added) == {"page_count", "section_count"}
        assert all(column.nullable is True for column in added.values())
        constraints = {call[1]: call[3] for call in calls if call[0] == "create_check_constraint"}
        assert "ck_compilations_page_count_bounded" in constraints
        assert "ck_compilations_section_count_bounded" in constraints
        assert "10000" in constraints["ck_compilations_page_count_bounded"]
        assert "500" in constraints["ck_compilations_section_count_bounded"]

        calls.clear()
        migration.downgrade()
        assert [call[0] for call in calls] == [
            "drop_constraint",
            "drop_constraint",
            "drop_column",
            "drop_column",
        ]


class TestDocumentComplexityReport:
    async def test_page_latency_windows_and_segmentation(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        users = [(await _create_user(db_session))[0] for _ in range(5)]
        compiler = _token("doccomplex_compiler")
        plan_a = _token("plan_a")
        plan_b = _token("plan_b")
        plan_c = _token("plan_c")
        templates = [str(uuid.uuid4()) for _ in range(3)]
        now = datetime.now(timezone.utc)

        cohorts = [
            (2, plan_a, templates[0], [1, 2, 3, 4, 5], [0.5, 1.5, 2.5, 3.5, 4.5]),
            (10, plan_b, templates[1], [7, 10, 11, 20, 21], [5, 10, 30, 60, 120]),
            (60, plan_c, templates[2], [1, 1, 1, 1, 1], [1, 1, 1, 1, 1]),
            (120, plan_a, templates[0], [1, 1, 1, 1, 1], [1, 1, 1, 1, 1]),
        ]
        for day, plan, template, pages, durations in cohorts:
            for index, user_id in enumerate(users):
                await _seed_compile(
                    db_session,
                    user_id,
                    plan=plan,
                    compiler=compiler,
                    template=template,
                    page_count=pages[index],
                    section_count=index + 1,
                    duration=durations[index],
                    created_at=now - timedelta(days=day),
                )

        # Compiler segmentation uses an isolated plan with three compilers.
        compiler_plan = _token("plan_compiler")
        compiler_values = [_token("compiler_a"), _token("compiler_b"), _token("compiler_c")]
        for compiler_value in compiler_values:
            for index, user_id in enumerate(users):
                await _seed_compile(
                    db_session,
                    user_id,
                    plan=compiler_plan,
                    compiler=compiler_value,
                    template=templates[index % 3],
                    page_count=index + 1,
                    section_count=2,
                    duration=1.0 + index,
                    created_at=now - timedelta(days=3),
                )

        seven = await client.get(
            f"/admin/analytics/document-complexity?days=7&compiler={compiler}",
            headers=headers,
        )
        assert seven.status_code == 200, seven.text
        seven_payload = seven.json()
        assert seven_payload["days"] == 7
        assert seven_payload["presets"] == [7, 30, 90]
        assert seven_payload["totals"]["compilations"] == 5
        assert seven_payload["totals"]["completed_compilations"] == 5
        assert seven_payload["page_count"]["samples"] == 5
        assert seven_payload["page_count"]["buckets"][0]["bucket"] == "1"
        assert seven_payload["page_count"]["buckets"][0]["count"] == 1

        thirty = await client.get(
            f"/admin/analytics/document-complexity?days=30&compiler={compiler}",
            headers=headers,
        )
        assert thirty.status_code == 200, thirty.text
        payload = thirty.json()
        assert payload["totals"]["compilations"] == 10
        assert payload["totals"]["completed_compilations"] == 10
        assert payload["page_count"]["samples"] == 10
        assert payload["page_count"]["p50"] == pytest.approx(6.0)
        assert payload["latency"]["samples"] == 10
        assert payload["latency"]["p50_seconds"] == pytest.approx(4.75)
        assert payload["latency"]["p95_seconds"] == pytest.approx(93.0)
        assert payload["reconciliation"]["reconciled"] is True
        assert payload["reconciliation"]["anonymous_excluded"] == 0

        page_counts = {bucket["bucket"]: bucket["count"] for bucket in payload["page_count"]["buckets"]}
        assert page_counts["1"] == 1
        assert page_counts["2"] == 1
        assert page_counts["3-4"] == 2
        assert page_counts["5-6"] == 1
        assert page_counts["7-10"] == 2
        assert page_counts["11-20"] == 2
        assert page_counts["21-50"] == 1
        assert page_counts["101-250"] == 0
        assert sum(page_counts.values()) == payload["page_count"]["samples"]

        latency_counts = {bucket["bucket"]: bucket["count"] for bucket in payload["latency"]["buckets"]}
        assert latency_counts["<1s"] == 1
        assert latency_counts["2-5s"] == 3
        assert latency_counts["60s+"] == 2
        assert sum(latency_counts.values()) == payload["latency"]["samples"]

        by_plan = {row["value"]: row for row in payload["by_plan"]}
        assert set(by_plan) == {plan_a, plan_b}
        assert by_plan[plan_a]["users"] == 5
        assert by_plan[plan_a]["compilations"] == 5
        assert by_plan[plan_b]["page_count"]["p95"] == pytest.approx(20.8)

        by_template = {row["value"]: row for row in payload["by_template"]}
        assert set(by_template) == {templates[0], templates[1]}
        assert by_template[templates[0]]["page_count"]["buckets"][0]["bucket"] == "1"
        assert by_template[templates[0]]["page_count"]["buckets"][0]["count"] == 1

        by_compiler = {row["value"]: row for row in payload["by_compiler"]}
        assert set(by_compiler) == {compiler}
        assert by_compiler[compiler]["users"] == 5

        ninety = await client.get(
            f"/admin/analytics/document-complexity?days=90&compiler={compiler}",
            headers=headers,
        )
        assert ninety.status_code == 200, ninety.text
        assert ninety.json()["totals"]["compilations"] == 15
        assert {row["value"] for row in ninety.json()["by_plan"]} == {
            plan_a,
            plan_b,
            plan_c,
        }

        compiler_segments = await client.get(
            f"/admin/analytics/document-complexity?days=30&plan={compiler_plan}",
            headers=headers,
        )
        assert compiler_segments.status_code == 200, compiler_segments.text
        compiler_payload = compiler_segments.json()
        assert compiler_payload["totals"]["compilations"] == 15
        assert compiler_payload["totals"]["distinct_users"] == 5
        assert {row["value"] for row in compiler_payload["by_compiler"]} == set(compiler_values)
        assert all(row["users"] == 5 for row in compiler_payload["by_compiler"])

    async def test_failure_classes_are_mutually_exclusive_and_reconcile(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        users = [(await _create_user(db_session))[0] for _ in range(5)]
        compiler = _token("doccomplex_failures")
        now = datetime.now(timezone.utc)

        seeded = [
            ("syntax", "! Undefined control sequence."),
            ("syntax", "! Missing $ inserted."),
            ("missing_package", "! LaTeX Error: File `missing.sty' not found."),
            ("timeout", "compile_timeout"),
            ("pdf_limit", "pdf_too_large"),
            (None, "legacy failure without a class"),
        ]
        for index, (error_class, message) in enumerate(seeded):
            await _seed_compile(
                db_session,
                users[index % len(users)],
                status="failed",
                plan="pro",
                compiler=compiler,
                page_count=None,
                duration=1.0,
                error_class=error_class,
                error_message=message,
                created_at=now - timedelta(days=1),
            )
        await _seed_compile(
            db_session,
            users[0],
            status="completed",
            plan="pro",
            compiler=compiler,
            page_count=2,
            duration=2.0,
            created_at=now - timedelta(days=1),
        )

        response = await client.get(
            f"/admin/analytics/document-complexity?days=30&compiler={compiler}",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()

        assert payload["totals"]["compilations"] == 7
        assert payload["totals"]["failed_compilations"] == 6
        assert payload["totals"]["completed_compilations"] == 1
        assert payload["failure_classes"]["failed_compilations"] == 6
        assert payload["failure_classes"]["class_total"] == 6
        assert payload["failure_classes"]["reconciled"] is True
        classes = {item["error_class"]: item for item in payload["failure_classes"]["classes"]}
        assert classes["syntax"]["count"] == 2
        assert classes["missing_package"]["count"] == 1
        assert classes["timeout"]["count"] == 1
        assert classes["pdf_limit"]["count"] == 1
        assert classes["unknown"]["count"] == 1
        assert classes["storage"]["count"] == 0
        assert sum(item["count"] for item in classes.values()) == 6
        assert payload["overflow"]["pdf_limit_failures"] == 1
        # Failed compiles do not contribute page-count samples.
        assert payload["page_count"]["samples"] == 1
        assert payload["page_count"]["missing"] == 0

    async def test_five_user_suppression_and_segment_suppression(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        compiler = _token("doccomplex_suppress")
        plan_a = _token("suppress_a")
        plan_b = _token("suppress_b")
        now = datetime.now(timezone.utc)

        first_four = [(await _create_user(db_session))[0] for _ in range(4)]
        for user_id in first_four:
            await _seed_compile(
                db_session,
                user_id,
                plan=plan_a,
                compiler=compiler,
                page_count=2,
                duration=1.0,
                created_at=now - timedelta(days=1),
            )

        suppressed = await client.get(
            f"/admin/analytics/document-complexity?days=30&compiler={compiler}",
            headers=headers,
        )
        assert suppressed.status_code == 200, suppressed.text
        suppressed_payload = suppressed.json()
        assert suppressed_payload["suppressed"] is True
        assert suppressed_payload["suppression"]["filtered_suppressed"] is True
        assert suppressed_payload["totals"]["compilations"] == 0
        assert suppressed_payload["page_count"]["samples"] == 0
        assert suppressed_payload["by_plan"] == []
        assert suppressed_payload["by_compiler"] == []
        assert suppressed_payload["by_template"] == []
        assert suppressed_payload["failure_classes"]["failed_compilations"] == 0

        fifth_id = (await _create_user(db_session))[0]
        await _seed_compile(
            db_session,
            fifth_id,
            plan=plan_a,
            compiler=compiler,
            page_count=3,
            duration=1.5,
            created_at=now - timedelta(days=1),
        )
        for user_id in first_four[:2]:
            await _seed_compile(
                db_session,
                user_id,
                plan=plan_b,
                compiler=compiler,
                page_count=9,
                duration=2.5,
                created_at=now - timedelta(days=1),
            )

        visible = await client.get(
            f"/admin/analytics/document-complexity?days=30&compiler={compiler}",
            headers=headers,
        )
        assert visible.status_code == 200, visible.text
        visible_payload = visible.json()
        assert visible_payload["suppressed"] is False
        assert visible_payload["totals"]["compilations"] == 7
        assert visible_payload["totals"]["distinct_users"] == 5
        assert {row["value"] for row in visible_payload["by_plan"]} == {plan_a}
        assert visible_payload["suppression"]["by_dimension"]["plan"] == 1
        assert visible_payload["suppression"]["hidden_by_dimension"]["plan"] == 1
        assert visible_payload["by_plan"][0]["users"] == 5

    async def test_privacy_never_returns_content_messages_or_identities(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        headers = await _admin_headers(db_session)
        users = [(await _create_user(db_session))[0] for _ in range(5)]
        compiler = _token("doccomplex_privacy")
        now = datetime.now(timezone.utc)
        for index, user_id in enumerate(users):
            await _seed_compile(
                db_session,
                user_id,
                status="completed" if index else "failed",
                plan="pro",
                compiler=compiler,
                template=None,
                page_count=2 if index else None,
                section_count=count_sections(SECRET_LATEX),
                duration=1.0,
                error_class="syntax" if index == 0 else None,
                error_message=SECRET_ERROR_TEXT if index == 0 else None,
                created_at=now - timedelta(days=1),
            )

        response = await client.get(
            f"/admin/analytics/document-complexity?days=30&compiler={compiler}",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert SECRET_ERROR_TEXT not in response.text
        assert "secret document marker" not in response.text
        assert "\\section" not in response.text
        assert "error_message" not in response.text
        assert "latex_content" not in response.text
        assert "@example.com" not in response.text
        for user_id in users:
            assert user_id not in response.text

        payload = response.json()
        assert payload["privacy"]["aggregate_only"] is True
        assert payload["privacy"]["per_user_rows"] is False
        assert payload["privacy"]["content_fields_excluded"]
        assert payload["sections"]["samples"] == 5
        assert payload["sections"]["p50"] == pytest.approx(1.0)

    async def test_endpoint_is_admin_only(self, client: AsyncClient, db_session: AsyncSession):
        _user_id, headers = await _create_user(db_session, role="user")
        response = await client.get("/admin/analytics/document-complexity", headers=headers)
        assert response.status_code == 403

        anonymous = await client.get("/admin/analytics/document-complexity")
        assert anonymous.status_code in {401, 403}

    async def test_invalid_template_filter_is_rejected(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        response = await client.get(
            "/admin/analytics/document-complexity?template=not-a-uuid",
            headers=headers,
        )
        assert response.status_code == 422

    async def test_submission_persists_section_count_without_source(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _user_id, headers = await _create_user(db_session, plan="pro")
        latex = (
            r"\documentclass{article}\begin{document}"
            r"\section{Experience}\section*{Skills}\section{Education}"
            r"% \section{Commented out}"
            r"\end{document}"
        )

        with patch("app.api.job_routes.submit_latex_compilation", return_value=None):
            response = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "latex_compilation",
                    "latex_content": latex,
                    "compiler": "pdflatex",
                },
                headers=headers,
            )
        assert response.status_code == 200, response.text
        job_id = response.json()["job_id"]
        compilation = (await db_session.execute(select(Compilation).where(Compilation.job_id == job_id))).scalar_one()
        assert compilation.section_count == 3
        assert compilation.page_count is None
        stored_columns = {column.name for column in Compilation.__table__.columns}
        assert "latex_content" not in stored_columns


class TestPageCountPersistence:
    def _session_factory(self, rowcounts: list[int]):
        session = MagicMock()
        lookup = MagicMock()
        lookup.scalar_one_or_none.return_value = SimpleNamespace(status="processing", pdf_path=None)
        session.execute = AsyncMock(side_effect=[lookup, *[MagicMock(rowcount=rowcount) for rowcount in rowcounts]])
        session.scalar = AsyncMock(return_value=None)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        class _Factory:
            def __call__(self):
                return self

            async def __aenter__(self):
                return session

            async def __aexit__(self, *exc):
                return False

        return _Factory(), session

    async def test_legacy_terminal_update_persists_bounded_page_count(self):
        from app.workers.latex_worker import _update_compilation_record

        factory, session = self._session_factory([1])
        lifecycle_redis = MagicMock()
        lifecycle_redis.hget.side_effect = lambda key, field: {
            "status": "running",
            "owner": "owner-a",
            "lease_until": "9999999999",
        }.get(field)
        with (
            patch("app.services.storage_service.upload_bytes") as mock_upload,
            patch("app.workers.latex_worker.get_worker_redis", return_value=lifecycle_redis),
        ):
            mock_upload.return_value = "compilations/job/resume.pdf"
            outcome = await _update_compilation_record(
                job_id="complexity-write",
                status="completed",
                compilation_time=1.0,
                pdf_bytes=b"%PDF-1.7",
                error_message=None,
                lifecycle_owner="owner-a",
                terminal_result={"page_count": 3},
                session_factory=factory,
            )

        assert outcome.value == "success"
        statement = session.execute.await_args_list[1].args[0]
        assert statement.compile().params["page_count"] == 3

    async def test_out_of_bound_page_count_is_not_persisted(self):
        from app.workers.latex_worker import _update_compilation_record

        factory, session = self._session_factory([1])
        lifecycle_redis = MagicMock()
        lifecycle_redis.hget.side_effect = lambda key, field: {
            "status": "running",
            "owner": "owner-a",
            "lease_until": "9999999999",
        }.get(field)
        with (
            patch("app.services.storage_service.upload_bytes") as mock_upload,
            patch("app.workers.latex_worker.get_worker_redis", return_value=lifecycle_redis),
        ):
            mock_upload.return_value = "compilations/job/resume.pdf"
            await _update_compilation_record(
                job_id="complexity-write-invalid",
                status="completed",
                compilation_time=1.0,
                pdf_bytes=b"%PDF-1.7",
                error_message=None,
                lifecycle_owner="owner-a",
                terminal_result={"page_count": MAX_PAGE_COUNT + 1},
                session_factory=factory,
            )

        statement = session.execute.await_args_list[1].args[0]
        assert statement.compile().params["page_count"] is None

    async def test_finalization_commit_persists_page_count(self, db_session_factory, monkeypatch):
        from app.workers.latex_worker import commit_latex_finalization

        user_id = str(uuid.uuid4())
        job_id = f"test_complexity_finalization_{uuid.uuid4().hex}"
        owner = f"owner:{uuid.uuid4()}"
        future = datetime.now(timezone.utc) + timedelta(minutes=10)
        async with db_session_factory() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"test_complexity_finalization_{user_id}@example.com",
                    name="Complexity Finalization",
                )
            )
            await session.commit()

        async with db_session_factory() as session:
            session.add(
                Compilation(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    job_id=job_id,
                    status="processing",
                    plan_family="pro",
                    compiler="pdflatex",
                    section_count=4,
                )
            )
            session.add(
                JobFinalization(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    user_id=user_id,
                    owner_token=owner,
                    owner_epoch=1,
                    state="pending",
                    lease_expires_at=future,
                    expires_at=future,
                )
            )
            await session.commit()

        from app.services.storage_service import compilation_pdf_key

        monkeypatch.setattr(
            "app.services.storage_service.upload_compilation_pdf",
            lambda job, token, data: (
                compilation_pdf_key(job, token),
                hashlib.sha256(data).hexdigest(),
            ),
        )
        try:
            accepted = await asyncio.to_thread(
                commit_latex_finalization,
                job_id,
                owner,
                1,
                {"success": True, "job_id": job_id, "page_count": 3},
                b"%PDF-1.7 complexity",
                1.25,
            )
            assert accepted

            async with db_session_factory() as session:
                compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
                assert compilation is not None
                assert compilation.page_count == 3
                assert compilation.section_count == 4
                assert compilation.status == "completed"
        finally:
            async with db_session_factory() as session:
                await session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
                await session.execute(delete(Compilation).where(Compilation.job_id == job_id))
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
