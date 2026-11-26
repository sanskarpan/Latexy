"""Editor mode, auto-compile and SyncTeX analytics (issue #2077).

Covers payload redaction, server-derived plans, toggle deduplication, consent
gating on the client boundary, aggregate adoption/compile reconciliation,
five-user suppression, privacy and admin-only access.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Resume, UsageAnalytics
from app.services.editor_mode_analytics_service import (
    AUTO_COMPILE_TOGGLED,
    EDITOR_MODE_SELECTED,
    SYNCTEX_USED,
    editor_mode_analytics_service,
    hash_document_identifier,
)

INGEST_ENDPOINT = "/telemetry/editor"
ADMIN_ENDPOINT = "/admin/analytics/editor-modes"
SECRET_LATEX = r"\section{Private Candidate} secret line 2077"
SECRET_DOCUMENT_ID = "resume_2077_private"
SECRET_FILENAME = "private-resume-2077.tex"
# Unique plan families isolate aggregate assertions from other tests that share
# the database session and a 30-day window.
TEST_PLAN = "editor2077"
PLAN_A = "editor2077a"
PLAN_B = "editor2077b"


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
            "VALUES (:id, :email, 'Editor Analytics User', :role, true, :plan, 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"test_editor_{user_id.replace('-', '')}@example.com",
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


async def _create_resume(db: AsyncSession, *, user_id: str) -> str:
    resume = Resume(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title="Editor analytics resume",
        latex_content="\\documentclass{article}\\begin{document}x\\end{document}",
    )
    db.add(resume)
    await db.commit()
    return str(resume.id)


async def _seed_event(
    db: AsyncSession,
    *,
    user_id: str,
    action: str,
    document_hash: str | None,
    mode: str = "source",
    plan: str = "pro",
    route: str = "/workspace/:resumeId/edit",
    enabled: bool | None = None,
    direction: str | None = None,
    created_at: datetime | None = None,
    metadata: dict | None = None,
) -> None:
    payload = metadata
    if payload is None:
        payload = {
            "mode": mode,
            "plan": plan,
            "route": route,
            "document_hash": document_hash
            or hash_document_identifier(str(uuid.uuid4())),
        }
        if enabled is not None:
            payload["enabled"] = enabled
        if direction is not None:
            payload["direction"] = direction
    db.add(
        UsageAnalytics(
            user_id=user_id,
            device_fingerprint=None,
            action=action,
            resource_type="editor",
            event_metadata=payload,
            created_at=created_at or datetime.now(timezone.utc),
        )
    )
    await db.commit()


async def _seed_compile(
    db: AsyncSession,
    *,
    user_id: str,
    resume_id: str,
    status: str,
    duration: float | None,
    plan: str = "pro",
    created_at: datetime | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO compilations (id, user_id, resume_id, job_id, status, "
            "compilation_time, plan_family, created_at) "
            "VALUES (:id, :uid, :resume, :job, :status, :duration, :plan, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "resume": resume_id,
            "job": f"editor_{uuid.uuid4().hex}",
            "status": status,
            "duration": duration,
            "plan": plan,
            "created": created_at or datetime.now(timezone.utc),
        },
    )
    await db.commit()


@pytest.fixture(autouse=True)
async def _clean_editor_rows(db_session: AsyncSession):
    await db_session.execute(
        delete(UsageAnalytics).where(
            UsageAnalytics.action.in_(
                (EDITOR_MODE_SELECTED, AUTO_COMPILE_TOGGLED, SYNCTEX_USED)
            )
        )
    )
    await db_session.execute(
        text("DELETE FROM compilations WHERE job_id LIKE 'editor_%'")
    )
    await db_session.execute(
        text("DELETE FROM resumes WHERE title = 'Editor analytics resume'")
    )
    await db_session.commit()
    yield


class TestIngestion:
    async def test_payload_redaction_hashes_document_id_and_derives_plan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user_id, headers = await _create_user(db_session, plan="pro")
        response = await client.post(
            INGEST_ENDPOINT,
            headers=headers,
            json={
                "events": [
                    {
                        "event_type": "editor_mode_selected",
                        "mode": "wysiwyg",
                        "route": f"/workspace/{SECRET_DOCUMENT_ID}/edit?token=secret",
                        "document_id": SECRET_DOCUMENT_ID,
                        # Hostile extras must never reach storage.
                        "latex_source": SECRET_LATEX,
                        "filename": SECRET_FILENAME,
                        "prompt": SECRET_LATEX,
                        "plan": "enterprise-spoof",
                    }
                ],
                "latex_source": SECRET_LATEX,
            },
        )

        assert response.status_code == 202, response.text
        assert response.json() == {"accepted": 1, "rejected": 0, "deduplicated": 0}

        rows = (
            await db_session.execute(
                select(UsageAnalytics.event_metadata).where(
                    UsageAnalytics.action == EDITOR_MODE_SELECTED
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        stored = rows[0]
        assert stored == {
            "mode": "wysiwyg",
            "plan": "pro",
            "route": "/workspace/:resumeId/edit",
            "document_hash": hash_document_identifier(SECRET_DOCUMENT_ID),
        }
        serialized = str(stored)
        assert SECRET_LATEX not in serialized
        assert SECRET_DOCUMENT_ID not in serialized
        assert SECRET_FILENAME not in serialized

    async def test_unknown_modes_are_rejected_and_batch_deduped(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user_id, headers = await _create_user(db_session)
        document_hash = hash_document_identifier(SECRET_DOCUMENT_ID)
        base_event = {
            "event_type": "editor_mode_selected",
            "mode": "source",
            "route": "/workspace/:resumeId/edit",
            "document_hash": document_hash,
            "event_id": "editor-mode-2077-a",
        }
        response = await client.post(
            INGEST_ENDPOINT,
            headers=headers,
            json={
                "events": [
                    base_event,
                    dict(base_event),
                    {
                        "event_type": "editor_mode_selected",
                        "mode": "whiteboard",
                        "route": "/workspace/:resumeId/edit",
                        "document_hash": document_hash,
                    },
                ]
            },
        )

        assert response.status_code == 202, response.text
        assert response.json() == {"accepted": 1, "rejected": 1, "deduplicated": 1}

        stored = (
            await db_session.execute(
                select(func.count(UsageAnalytics.id)).where(
                    UsageAnalytics.action == EDITOR_MODE_SELECTED
                )
            )
        ).scalar_one()
        assert stored == 1

    async def test_event_id_retry_is_idempotent(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user_id, headers = await _create_user(db_session)
        event = {
            "event_type": "editor_mode_selected",
            "mode": "pdf",
            "route": "/workspace/:resumeId/edit",
            "document_hash": hash_document_identifier(SECRET_DOCUMENT_ID),
            "event_id": "editor-mode-2077-retry",
        }
        first = await client.post(INGEST_ENDPOINT, headers=headers, json={"events": [event]})
        second = await client.post(INGEST_ENDPOINT, headers=headers, json={"events": [event]})

        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert first.json()["accepted"] == 1
        assert second.json() == {"accepted": 0, "rejected": 0, "deduplicated": 1}

    async def test_auto_compile_toggle_deduplicates_repeated_state(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user_id, headers = await _create_user(db_session)
        document_hash = hash_document_identifier(SECRET_DOCUMENT_ID)
        enabled_event = {
            "event_type": "auto_compile_toggled",
            "mode": "source",
            "route": "/workspace/:resumeId/edit",
            "document_hash": document_hash,
            "enabled": True,
        }
        first = await client.post(
            INGEST_ENDPOINT, headers=headers, json={"events": [enabled_event]}
        )
        duplicate = await client.post(
            INGEST_ENDPOINT, headers=headers, json={"events": [enabled_event]}
        )
        disabled = await client.post(
            INGEST_ENDPOINT,
            headers=headers,
            json={"events": [{**enabled_event, "enabled": False}]},
        )

        assert first.json()["accepted"] == 1
        assert duplicate.json() == {"accepted": 0, "rejected": 0, "deduplicated": 1}
        assert disabled.json()["accepted"] == 1

        rows = (
            await db_session.execute(
                select(UsageAnalytics.event_metadata)
                .where(UsageAnalytics.action == AUTO_COMPILE_TOGGLED)
                .order_by(UsageAnalytics.created_at)
            )
        ).scalars().all()
        assert [row["enabled"] for row in rows] == [True, False]

    async def test_synctex_direction_is_allowlisted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user_id, headers = await _create_user(db_session)
        document_hash = hash_document_identifier(SECRET_DOCUMENT_ID)
        response = await client.post(
            INGEST_ENDPOINT,
            headers=headers,
            json={
                "events": [
                    {
                        "event_type": "synctex_used",
                        "mode": "source",
                        "route": "/workspace/:resumeId/edit",
                        "document_hash": document_hash,
                        "direction": "source_to_pdf",
                    },
                    {
                        "event_type": "synctex_used",
                        "mode": "source",
                        "route": "/workspace/:resumeId/edit",
                        "document_hash": document_hash,
                        "direction": "sideways",
                    },
                ]
            },
        )

        assert response.status_code == 202, response.text
        assert response.json() == {"accepted": 1, "rejected": 1, "deduplicated": 0}
        stored = (
            await db_session.execute(
                select(UsageAnalytics.event_metadata).where(
                    UsageAnalytics.action == SYNCTEX_USED
                )
            )
        ).scalar_one()
        assert stored["direction"] == "source_to_pdf"
        assert set(stored) == {"mode", "plan", "route", "document_hash", "direction"}


class TestAggregation:
    async def _seed_usage(
        self, db: AsyncSession, *, users: int, plan: str = TEST_PLAN
    ) -> tuple[list[str], list[str]]:
        now = datetime.now(timezone.utc)
        user_ids: list[str] = []
        resume_ids: list[str] = []
        for index in range(users):
            user_id, _headers = await _create_user(db, plan=plan)
            resume_id = await _create_resume(db, user_id=user_id)
            user_ids.append(user_id)
            resume_ids.append(resume_id)
            document_hash = hash_document_identifier(resume_id)

            await _seed_event(
                db,
                user_id=user_id,
                action=EDITOR_MODE_SELECTED,
                document_hash=document_hash,
                mode="source",
                plan=plan,
                created_at=now - timedelta(minutes=10, seconds=index),
            )
            await _seed_compile(
                db,
                user_id=user_id,
                resume_id=resume_id,
                status="completed",
                duration=float(index + 1),
                plan=plan,
                created_at=now - timedelta(minutes=9, seconds=index),
            )
            await _seed_event(
                db,
                user_id=user_id,
                action=EDITOR_MODE_SELECTED,
                document_hash=document_hash,
                mode="pdf",
                plan=plan,
                created_at=now - timedelta(minutes=8, seconds=index),
            )
            await _seed_compile(
                db,
                user_id=user_id,
                resume_id=resume_id,
                status="completed",
                duration=float(index + 2),
                plan=plan,
                created_at=now - timedelta(minutes=7, seconds=index),
            )
            await _seed_compile(
                db,
                user_id=user_id,
                resume_id=resume_id,
                status="failed",
                duration=None,
                plan=plan,
                created_at=now - timedelta(minutes=6, seconds=index),
            )
            await _seed_event(
                db,
                user_id=user_id,
                action=AUTO_COMPILE_TOGGLED,
                document_hash=document_hash,
                mode="pdf",
                plan=plan,
                enabled=True,
                created_at=now - timedelta(minutes=5, seconds=index),
            )
            await _seed_event(
                db,
                user_id=user_id,
                action=SYNCTEX_USED,
                document_hash=document_hash,
                mode="pdf",
                plan=plan,
                direction="source_to_pdf",
                created_at=now - timedelta(minutes=4, seconds=index),
            )
        return user_ids, resume_ids

    async def test_mode_adoption_compile_outcomes_and_tool_counts(
        self, db_session: AsyncSession
    ) -> None:
        await self._seed_usage(db_session, users=5)
        # Three extra PDF->source jumps keep SyncTeX above the mode count.
        now = datetime.now(timezone.utc)
        rows = (
            await db_session.execute(
                select(UsageAnalytics.user_id, UsageAnalytics.event_metadata)
                .where(UsageAnalytics.action == EDITOR_MODE_SELECTED, UsageAnalytics.event_metadata["mode"].as_string() == "pdf")
                .limit(3)
            )
        ).all()
        for user_id, metadata in rows:
            await _seed_event(
                db_session,
                user_id=user_id,
                action=SYNCTEX_USED,
                document_hash=metadata["document_hash"],
                mode="pdf",
                plan=metadata["plan"],
                direction="pdf_to_source",
                created_at=now - timedelta(minutes=3),
            )

        snapshot = await editor_mode_analytics_service.snapshot(
            db_session, days=30, plan=TEST_PLAN
        )

        assert snapshot["suppressed"] is False
        summary = snapshot["summary"]
        assert summary["mode_selections"] == 10
        assert summary["mode_users"] == 5
        assert summary["documents"] == 5
        assert summary["auto_compile_toggles"] == 5
        assert summary["auto_compile_enabled_toggles"] == 5
        assert summary["auto_compile_disabled_toggles"] == 0
        assert summary["synctex_events"] == 8
        assert summary["synctex_source_to_pdf"] == 5
        assert summary["synctex_pdf_to_source"] == 3
        assert summary["compilations"] == 15
        assert summary["attributed_compilations"] == 15
        assert summary["unknown_mode_compilations"] == 0
        assert summary["completed_compilations"] == 10
        assert summary["failed_compilations"] == 5
        assert summary["success_rate_pct"] == 66.67
        assert summary["p50_seconds"] == 3.5
        assert summary["p95_seconds"] == 5.55

        adoption = {row["mode"]: row for row in snapshot["adoption_by_mode"]}
        assert adoption["source"]["selections"] == 5
        assert adoption["pdf"]["selections"] == 5
        assert adoption["source"]["users"] == 5
        assert adoption["pdf"]["users"] == 5

        by_plan_mode = {
            (row["plan"], row["mode"]): row
            for row in snapshot["adoption_by_plan_mode"]
        }
        assert by_plan_mode[(TEST_PLAN, "source")]["selections"] == 5
        assert by_plan_mode[(TEST_PLAN, "pdf")]["selections"] == 5
        assert snapshot["suppression"]["suppressed_plan_mode_rows"] == 0

        compile_rows = {row["mode"]: row for row in snapshot["compile_by_mode"]}
        assert compile_rows["source"]["compilations"] == 5
        assert compile_rows["source"]["success_rate_pct"] == 100.0
        assert compile_rows["source"]["p50_seconds"] == 3.0
        assert compile_rows["source"]["p95_seconds"] == 4.8
        assert compile_rows["pdf"]["compilations"] == 10
        assert compile_rows["pdf"]["completed"] == 5
        assert compile_rows["pdf"]["failed"] == 5
        assert compile_rows["pdf"]["success_rate_pct"] == 50.0
        assert compile_rows["pdf"]["p50_seconds"] == 4.0
        assert compile_rows["pdf"]["p95_seconds"] == 5.8
        assert compile_rows["pdf"]["users"] == 5

        assert snapshot["auto_compile"]["toggles"] == 5
        assert snapshot["auto_compile"]["enabled"] == 5
        assert snapshot["auto_compile"]["users"] == 5
        assert snapshot["synctex"]["events"] == 8
        assert snapshot["synctex"]["users"] == 5
        directions = {row["direction"]: row["count"] for row in snapshot["synctex"]["by_direction"]}
        assert directions == {"source_to_pdf": 5, "pdf_to_source": 3}

        reconciliation = snapshot["reconciliation"]
        assert reconciliation["editor_events"] == 23
        assert reconciliation["mode_selections"] == 10
        assert reconciliation["compilations"] == 15
        assert reconciliation["attributed_compilations"] == 15
        assert snapshot["suppression"]["compile_totals_visible"] is True
        assert snapshot["privacy"]["per_user_rows"] is False

    async def test_plan_filter_restricts_all_sections(self, db_session: AsyncSession) -> None:
        await self._seed_usage(db_session, users=5, plan=PLAN_A)
        await self._seed_usage(db_session, users=5, plan=PLAN_B)
        snapshot = await editor_mode_analytics_service.snapshot(
            db_session, days=30, plan=PLAN_A
        )

        assert snapshot["filters"]["plan"] == PLAN_A
        assert snapshot["summary"]["mode_selections"] == 10
        assert snapshot["summary"]["compilations"] == 15
        assert [row["plan"] for row in snapshot["adoption_by_plan"]] == [PLAN_A]
        assert all(row["plan"] == PLAN_A for row in snapshot["adoption_by_plan_mode"])
        assert {row["mode"] for row in snapshot["adoption_by_plan_mode"]} == {
            "source",
            "pdf",
        }

    async def test_small_cohort_is_fully_suppressed(self, db_session: AsyncSession) -> None:
        await self._seed_usage(db_session, users=4)
        snapshot = await editor_mode_analytics_service.snapshot(
            db_session, days=30, plan=TEST_PLAN
        )

        assert snapshot["suppressed"] is True
        assert snapshot["summary"]["mode_selections"] is None
        assert snapshot["summary"]["auto_compile_toggles"] is None
        assert snapshot["summary"]["synctex_events"] is None
        assert snapshot["summary"]["compilations"] is None
        assert snapshot["adoption_by_mode"] == []
        assert snapshot["adoption_by_plan"] == []
        assert snapshot["compile_by_mode"] == []
        assert snapshot["trend"] == []
        assert snapshot["suppression"]["minimum_users"] == 5

    async def test_invalid_and_extra_metadata_is_ignored(
        self, db_session: AsyncSession
    ) -> None:
        now = datetime.now(timezone.utc)
        for index in range(5):
            user_id, _headers = await _create_user(db_session)
            await _seed_event(
                db_session,
                user_id=user_id,
                action=EDITOR_MODE_SELECTED,
                document_hash=hash_document_identifier(str(uuid.uuid4())),
                created_at=now - timedelta(minutes=index + 1),
                metadata={
                    "mode": "source",
                    "plan": TEST_PLAN,
                    "route": "/workspace/:resumeId/edit",
                    "document_hash": hash_document_identifier(str(uuid.uuid4())),
                    "latex_source": SECRET_LATEX,
                    "filename": SECRET_FILENAME,
                },
            )
        user_id = (await _create_user(db_session))[0]
        await _seed_event(
            db_session,
            user_id=user_id,
            action=EDITOR_MODE_SELECTED,
            document_hash=None,
            metadata={
                "mode": "whiteboard",
                "plan": TEST_PLAN,
                "route": "/workspace/:resumeId/edit",
                "document_hash": hash_document_identifier("invalid-mode"),
                "latex_source": SECRET_LATEX,
            },
        )
        await _seed_event(
            db_session,
            user_id=user_id,
            action=EDITOR_MODE_SELECTED,
            document_hash=None,
            metadata={
                "mode": "source",
                "plan": TEST_PLAN,
                "route": "/workspace/:resumeId/edit",
                "document_hash": "not-a-sha256",
                "latex_source": SECRET_LATEX,
            },
        )

        snapshot = await editor_mode_analytics_service.snapshot(
            db_session, days=30, plan=TEST_PLAN
        )

        assert snapshot["summary"]["mode_selections"] == 5
        assert snapshot["reconciliation"]["invalid_rows"] == 2
        serialized = str(snapshot)
        assert SECRET_LATEX not in serialized
        assert SECRET_FILENAME not in serialized
        assert "not-a-sha256" not in serialized
        assert "user_id" not in serialized

    async def test_empty_range_returns_explicit_zeroes(self, db_session: AsyncSession) -> None:
        snapshot = await editor_mode_analytics_service.snapshot(
            db_session,
            start_date=datetime(2016, 1, 1).date(),
            end_date=datetime(2016, 1, 2).date(),
        )

        assert snapshot["suppressed"] is False
        assert snapshot["summary"]["mode_selections"] == 0
        assert snapshot["summary"]["compilations"] == 0
        assert snapshot["adoption_by_mode"] == []
        assert snapshot["compile_by_mode"] == []
        assert snapshot["reconciliation"]["truncated_events"] is False


class TestAdminAccess:
    async def test_report_is_admin_only(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed_admin_access(db_session)
        _user_id, user_headers = await _create_user(db_session)
        response = await client.get(ADMIN_ENDPOINT, headers=user_headers)
        assert response.status_code in (401, 403), response.text

        response = await client.get(ADMIN_ENDPOINT)
        assert response.status_code in (401, 403), response.text

        _admin_id, admin_headers = await _create_user(db_session, role="admin")
        response = await client.get(ADMIN_ENDPOINT, headers=admin_headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["minimum_cohort_size"] == 5
        assert payload["privacy"]["aggregate_only"] is True
        assert "user_id" not in response.text

    async def test_invalid_date_range_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _admin_id, admin_headers = await _create_user(db_session, role="admin")
        response = await client.get(
            ADMIN_ENDPOINT,
            params={"start_date": "2026-02-08", "end_date": "2026-02-01"},
            headers=admin_headers,
        )
        assert response.status_code == 422, response.text


async def _seed_admin_access(db_session: AsyncSession) -> None:
    """Five users so the admin response is not suppressed by the cohort rule."""

    now = datetime.now(timezone.utc)
    for index in range(5):
        user_id, _headers = await _create_user(db_session)
        await _seed_event(
            db_session,
            user_id=user_id,
            action=EDITOR_MODE_SELECTED,
            document_hash=hash_document_identifier(str(uuid.uuid4())),
            created_at=now - timedelta(minutes=index + 1),
        )


def test_client_consent_gate_and_privacy_contract() -> None:
    """Static guard: the browser only emits after consent and never sends ids."""

    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "src"
    telemetry = (frontend / "lib" / "editor-mode-telemetry.ts").read_text(encoding="utf-8")
    page = (
        frontend / "app" / "workspace" / "[resumeId]" / "edit" / "page.tsx"
    ).read_text(encoding="utf-8")

    assert "readAnalyticsConsent" in telemetry
    assert "options.readConsent() !== 'granted'" in telemetry
    assert "'/telemetry/editor'" in telemetry
    assert "document_hash" in telemetry
    assert "document_id" not in telemetry.split("buildEditorTelemetryEvent")[1]
    assert "editorModeTelemetry.selectMode" in page
    assert "editorModeTelemetry.toggleAutoCompile" in page
    assert "editorModeTelemetry.synctex" in page
