"""Career-feature adoption: events, reconciliation, filters, suppression, privacy."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UsageAnalytics

SECRET_COVER_LETTER = "SECRET_COVER_LETTER_2093_MUST_NOT_LEAK"
SECRET_JOB_DESCRIPTION = "SECRET_JOB_DESCRIPTION_2093_MUST_NOT_LEAK"
SECRET_INTERVIEW = "SECRET_INTERVIEW_QUESTION_2093_MUST_NOT_LEAK"
SECRET_CAREER = "SECRET_CAREER_ANALYSIS_2093_MUST_NOT_LEAK"

_CREATED_USER_IDS: list[str] = []


async def _create_user(
    db: AsyncSession,
    *,
    plan: str,
    role: str = "user",
    created_at: datetime | None = None,
    email: str | None = None,
) -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, created_at) "
            "VALUES (:id, :email, 'Career Adoption User', :role, true, :plan, 'active', false, :created)"
        ),
        {
            "id": user_id,
            "email": email or f"test_career_adoption_{uuid.uuid4().hex}@example.com",
            "role": role,
            "plan": plan,
            "created": created_at or datetime.now(timezone.utc),
        },
    )
    await db.commit()
    _CREATED_USER_IDS.append(user_id)
    return user_id


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_career_adoption_{uuid.uuid4().hex}"
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
    return {"Authorization": f"Bearer {token}"}


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    admin_plan = f"ca_admin_{uuid.uuid4().hex[:6]}"
    user_id = await _create_user(db, plan=admin_plan, role="admin")
    return await _session_headers(db, user_id)


async def _create_resume(db: AsyncSession, *, user_id: str) -> str:
    resume_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content, metadata, created_at) "
            "VALUES (:id, :uid, 'Career Adoption Resume', :latex, CAST(:metadata AS jsonb), :created)"
        ),
        {
            "id": resume_id,
            "uid": user_id,
            "latex": "SECRET_RESUME_SOURCE_2093",
            "metadata": json.dumps({}),
            "created": datetime.now(timezone.utc) - timedelta(days=1),
        },
    )
    await db.commit()
    return resume_id


async def _seed_event(
    db: AsyncSession,
    user_id: str | None,
    *,
    action: str,
    metadata: dict | None = None,
    created_at: datetime | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO usage_analytics (id, user_id, action, resource_type, event_metadata, created_at) "
            "VALUES (:id, :uid, :action, 'feature', CAST(:metadata AS JSONB), :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "action": action,
            "metadata": json.dumps(metadata) if metadata is not None else None,
            "created": created_at or datetime.now(timezone.utc) - timedelta(hours=2),
        },
    )
    await db.commit()


async def _seed_cover_letter(
    db: AsyncSession,
    *,
    user_id: str,
    resume_id: str,
    created_at: datetime | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO cover_letters "
            "(id, user_id, resume_id, job_description, company_name, role_title, tone, "
            "length_preference, latex_content, created_at, updated_at) "
            "VALUES (:id, :uid, :resume, :jd, 'Secret Co', 'Secret Role', 'formal', "
            "'3_paragraphs', :latex, :created, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "resume": resume_id,
            "jd": SECRET_JOB_DESCRIPTION,
            "latex": SECRET_COVER_LETTER,
            "created": created_at or datetime.now(timezone.utc) - timedelta(hours=1),
        },
    )
    await db.commit()


async def _seed_interview_prep(
    db: AsyncSession,
    *,
    user_id: str,
    resume_id: str,
    created_at: datetime | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO interview_prep "
            "(id, user_id, resume_id, job_description, questions, created_at, updated_at) "
            "VALUES (:id, :uid, :resume, :jd, CAST(:questions AS jsonb), :created, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "resume": resume_id,
            "jd": SECRET_JOB_DESCRIPTION,
            "questions": json.dumps([{"question": SECRET_INTERVIEW}]),
            "created": created_at or datetime.now(timezone.utc) - timedelta(hours=1),
        },
    )
    await db.commit()


async def _seed_career_analysis(
    db: AsyncSession,
    *,
    user_id: str,
    resume_id: str,
    created_at: datetime | None = None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO career_analyses "
            "(id, user_id, resume_id, current_skills, gap_skills, llm_analysis, created_at) "
            "VALUES (:id, :uid, :resume, ARRAY[]::text[], ARRAY[]::text[], :analysis, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "resume": resume_id,
            "analysis": SECRET_CAREER,
            "created": created_at or datetime.now(timezone.utc) - timedelta(hours=1),
        },
    )
    await db.commit()


async def _safe_execute(db: AsyncSession, statement, params: dict | None = None) -> None:
    """Best-effort cleanup that survives a shared test database deadlock."""
    try:
        await db.execute(statement, params or {})
        await db.commit()
    except Exception:
        await db.rollback()


async def _cleanup(db: AsyncSession, user_ids: list[str] | None = None) -> None:
    cleanup_ids = list(dict.fromkeys([*(user_ids or []), *_CREATED_USER_IDS]))
    _CREATED_USER_IDS.clear()
    await _safe_execute(
        db, text("DELETE FROM session WHERE token LIKE 'test_sess_career_adoption_%'")
    )
    if cleanup_ids:
        await _safe_execute(
            db,
            text("DELETE FROM cover_letters WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": cleanup_ids},
        )
        await _safe_execute(
            db,
            text("DELETE FROM interview_prep WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": cleanup_ids},
        )
        await _safe_execute(
            db,
            text("DELETE FROM career_analyses WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": cleanup_ids},
        )
        await _safe_execute(
            db,
            text("DELETE FROM optimizations WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": cleanup_ids},
        )
        await _safe_execute(
            db,
            text("DELETE FROM usage_analytics WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": cleanup_ids},
        )
        await _safe_execute(
            db,
            text("DELETE FROM resumes WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": cleanup_ids},
        )
        await _safe_execute(
            db,
            text("DELETE FROM subscriptions WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": cleanup_ids},
        )
        await _safe_execute(
            db,
            text("DELETE FROM users WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": cleanup_ids},
        )


def _feature(body: dict, key: str) -> dict:
    return next(feature for feature in body["features"] if feature["key"] == key)


def _month_label(value: datetime) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _previous_month_start() -> datetime:
    this_month = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (this_month - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class TestCareerAdoptionEvents:
    async def test_cover_letter_generation_records_no_content_event(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id = await _create_user(db_session, plan="pro")
        resume_id = await _create_resume(db_session, user_id=user_id)
        headers = await _session_headers(db_session, user_id)
        try:
            with (
                patch(
                    "app.api.cover_letter_routes.submit_cover_letter_generation",
                    MagicMock(return_value="job-id"),
                ),
                patch(
                    "app.api.cover_letter_routes.api_key_service.get_user_provider",
                    AsyncMock(return_value="test-key"),
                ),
            ):
                response = await client.post(
                    "/cover-letters/generate",
                    headers=headers,
                    json={
                        "resume_id": resume_id,
                        "job_description": SECRET_JOB_DESCRIPTION,
                        "company_name": "Secret Co",
                        "role_title": "Secret Role",
                    },
                )
            assert response.status_code == 200, response.text

            row = (
                await db_session.execute(
                    select(UsageAnalytics).where(
                        UsageAnalytics.user_id == user_id,
                        UsageAnalytics.action == "cover_letter_generated",
                    )
                )
            ).scalar_one()
            metadata = row.event_metadata or {}
            assert metadata["feature"] == "cover_letters"
            assert row.resource_type == "feature"
            assert row.ip_address is None
            assert row.user_agent is None
            serialized = json.dumps(metadata)
            assert SECRET_JOB_DESCRIPTION not in serialized
            assert SECRET_COVER_LETTER not in serialized
            assert "job_description" not in metadata
            assert "latex_content" not in metadata
        finally:
            await _cleanup(db_session, [user_id])

    async def test_interview_prep_generation_records_no_content_event(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id = await _create_user(db_session, plan="pro")
        resume_id = await _create_resume(db_session, user_id=user_id)
        headers = await _session_headers(db_session, user_id)
        try:
            with patch(
                "app.api.interview_routes.submit_interview_prep_generation",
                MagicMock(return_value="job-id"),
            ):
                response = await client.post(
                    "/interview-prep/generate",
                    headers=headers,
                    json={
                        "resume_id": resume_id,
                        "job_description": SECRET_JOB_DESCRIPTION,
                        "company_name": "Secret Co",
                    },
                )
            assert response.status_code == 201, response.text

            row = (
                await db_session.execute(
                    select(UsageAnalytics).where(
                        UsageAnalytics.user_id == user_id,
                        UsageAnalytics.action == "interview_prep_generated",
                    )
                )
            ).scalar_one()
            metadata = row.event_metadata or {}
            assert metadata["feature"] == "interview_prep"
            assert SECRET_JOB_DESCRIPTION not in json.dumps(metadata)
            assert row.ip_address is None
            assert row.user_agent is None
        finally:
            await _cleanup(db_session, [user_id])

    async def test_career_analysis_records_no_content_event(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id = await _create_user(db_session, plan="pro")
        resume_id = await _create_resume(db_session, user_id=user_id)
        headers = await _session_headers(db_session, user_id)
        analysis = SimpleNamespace(
            id=str(uuid.uuid4()),
            user_id=user_id,
            resume_id=resume_id,
            target_role_id=None,
            target_role_freetext="Staff Engineer",
            current_skills=[],
            gap_skills=[],
            skill_taxonomy=None,
            skill_taxonomy_language=None,
            skill_taxonomy_mappings=None,
            path_role_ids=None,
            timeline_months=None,
            llm_analysis=SECRET_CAREER,
            created_at=datetime.now(timezone.utc),
        )
        try:
            with (
                patch(
                    "app.api.career_routes.career_path_service.run_full_analysis",
                    AsyncMock(return_value=analysis),
                ),
                patch(
                    "app.api.career_routes.api_key_service.get_user_provider",
                    AsyncMock(return_value="test-key"),
                ),
            ):
                response = await client.post(
                    "/career/analyze",
                    headers=headers,
                    json={"resume_id": resume_id, "target_role_title": "Staff Engineer"},
                )
            assert response.status_code == 200, response.text

            row = (
                await db_session.execute(
                    select(UsageAnalytics).where(
                        UsageAnalytics.user_id == user_id,
                        UsageAnalytics.action == "career_analysis_generated",
                    )
                )
            ).scalar_one()
            metadata = row.event_metadata or {}
            assert metadata["feature"] == "career_paths"
            assert SECRET_CAREER not in json.dumps(metadata)
            assert row.ip_address is None
            assert row.user_agent is None
        finally:
            await _cleanup(db_session, [user_id])


class TestCareerAdoptionReport:
    async def test_no_events_and_deleted_users_are_excluded(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        plan = f"ca_empty_{uuid.uuid4().hex[:6]}"
        user_ids: list[str] = []
        try:
            user_ids = [
                await _create_user(db_session, plan=plan, created_at=datetime.now(timezone.utc))
                for _ in range(5)
            ]
            deleted_id = await _create_user(db_session, plan=plan)
            deleted_resume = await _create_resume(db_session, user_id=deleted_id)
            await _seed_cover_letter(
                db_session,
                user_id=deleted_id,
                resume_id=deleted_resume,
            )
            await _seed_event(
                db_session,
                deleted_id,
                action="cover_letter_generated",
                metadata={"feature": "cover_letters"},
            )
            await db_session.execute(
                text("DELETE FROM users WHERE id = :id"), {"id": deleted_id}
            )
            await db_session.commit()
            await _seed_event(
                db_session,
                None,
                action="cover_letter_generated",
                metadata={"feature": "cover_letters"},
            )

            headers = await _admin_headers(db_session)
            response = await client.get(
                f"/admin/analytics/career-adoption?days=30&plan={plan}",
                headers=headers,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["audience_users"] == 5
            cover = _feature(body, "cover_letters")
            assert cover["adoption"]["users"] == 0
            assert cover["adoption"]["runs"] == 0
            assert body["reconciliation"]["features"]["cover_letters"]["events"] == 0
            assert body["reconciliation"]["features"]["cover_letters"]["table_rows"] == 0
            assert deleted_id not in response.text
        finally:
            await _cleanup(db_session, user_ids)

    async def test_reconciliation_repeat_use_and_cross_sell(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        plan = f"ca_recon_{uuid.uuid4().hex[:6]}"
        user_ids: list[str] = []
        now = datetime.now(timezone.utc)
        try:
            user_ids = [
                await _create_user(db_session, plan=plan, created_at=now) for _ in range(5)
            ]
            resume_ids = []
            for user_id in user_ids:
                resume_ids.append(await _create_resume(db_session, user_id=user_id))

            cover_counts = [2, 2, 1, 1, 1]
            for index, (user_id, count) in enumerate(zip(user_ids, cover_counts, strict=True)):
                for run in range(count):
                    await _seed_event(
                        db_session,
                        user_id,
                        action="cover_letter_generated",
                        metadata={"feature": "cover_letters"},
                        created_at=now - timedelta(hours=2, minutes=50 - run),
                    )
                    await _seed_cover_letter(
                        db_session,
                        user_id=user_id,
                        resume_id=resume_ids[index],
                        created_at=now - timedelta(hours=2, minutes=50 - run),
                    )
                if index < 3:
                    await _seed_event(
                        db_session,
                        user_id,
                        action="optimize",
                        metadata={"optimization_id": str(uuid.uuid4())},
                        created_at=now - timedelta(hours=3),
                    )

            # The legacy browser label can describe the same cover-letter run as
            # the new server event. It must not double-count adoption.
            await _seed_event(
                db_session,
                user_ids[0],
                action="feature_usage",
                metadata={"feature": "cover_letter_generation"},
                created_at=now - timedelta(hours=2, minutes=48),
            )

            for index, user_id in enumerate(user_ids):
                await _seed_event(
                    db_session,
                    user_id,
                    action="interview_prep_generated",
                    metadata={"feature": "interview_prep"},
                    created_at=now - timedelta(hours=2),
                )
                await _seed_interview_prep(
                    db_session,
                    user_id=user_id,
                    resume_id=resume_ids[index],
                    created_at=now - timedelta(hours=2),
                )

            for index in range(3):
                created = now - timedelta(hours=2, minutes=index)
                await _seed_event(
                    db_session,
                    user_ids[0],
                    action="career_analysis_generated",
                    metadata={"feature": "career_paths"},
                    created_at=created,
                )
                await _seed_career_analysis(
                    db_session,
                    user_id=user_ids[0],
                    resume_id=resume_ids[0],
                    created_at=created,
                )

            headers = await _admin_headers(db_session)
            response = await client.get(
                f"/admin/analytics/career-adoption?days=30&plan={plan}",
                headers=headers,
            )
            assert response.status_code == 200, response.text
            body = response.json()

            cover = _feature(body, "cover_letters")
            assert cover["adoption"]["users"] == 5
            assert cover["adoption"]["runs"] == 7
            assert cover["adoption"]["repeat_users"] == 2
            assert cover["adoption"]["repeat_rate"] == 40.0
            assert cover["adoption"]["after_optimization_users"] == 3
            assert cover["adoption"]["after_optimization_rate"] == 60.0

            interview = _feature(body, "interview_prep")
            assert interview["adoption"]["users"] == 5
            assert interview["adoption"]["runs"] == 5
            assert interview["adoption"]["repeat_users"] == 0

            career = _feature(body, "career_paths")
            assert career["adoption"]["users"] == 1
            assert career["adoption"]["runs"] == 3
            assert career["adoption"]["repeat_users"] == 1

            plan_segment = next(
                segment for segment in cover["segments"] if segment["dimension"] == "plan"
            )
            assert plan_segment["denominator"] == 5
            assert plan_segment["users"] == 5
            assert plan_segment["runs"] == 7
            assert plan_segment["repeat_users"] == 2
            assert plan_segment["after_optimization_users"] == 3

            reconciliation = body["reconciliation"]
            assert reconciliation["features"]["cover_letters"]["events"] == 7
            assert reconciliation["features"]["cover_letters"]["table_rows"] == 7
            assert reconciliation["features"]["interview_prep"]["events"] == 5
            assert reconciliation["features"]["career_paths"]["events"] == 3
            assert reconciliation["totals"]["events"] == 15
            assert reconciliation["totals"]["table_rows"] == 15
            assert reconciliation["totals"]["matched"] == 15
            assert reconciliation["totals"]["unmatched_events"] == 0
            assert reconciliation["totals"]["unmatched_rows"] == 0
        finally:
            await _cleanup(db_session, user_ids)

    async def test_plan_and_cohort_filters(self, client: AsyncClient, db_session: AsyncSession):
        plan_a = f"ca_plan_a_{uuid.uuid4().hex[:5]}"
        plan_b = f"ca_plan_b_{uuid.uuid4().hex[:5]}"
        now = datetime.now(timezone.utc)
        previous_start = _previous_month_start()
        previous_label = _month_label(previous_start)
        current_label = _month_label(now)
        user_ids: list[str] = []
        try:
            current_ids = [
                await _create_user(db_session, plan=plan_a, created_at=now) for _ in range(5)
            ]
            previous_ids = [
                await _create_user(
                    db_session,
                    plan=plan_b,
                    created_at=previous_start + timedelta(days=2),
                )
                for _ in range(5)
            ]
            user_ids = [*current_ids, *previous_ids]
            for user_id in current_ids:
                await _seed_event(
                    db_session,
                    user_id,
                    action="cover_letter_generated",
                    metadata={"feature": "cover_letters"},
                )
            for user_id in previous_ids:
                await _seed_event(
                    db_session,
                    user_id,
                    action="interview_prep_generated",
                    metadata={"feature": "interview_prep"},
                )

            headers = await _admin_headers(db_session)
            plan_a_body = (
                await client.get(
                    f"/admin/analytics/career-adoption?days=90&plan={plan_a}",
                    headers=headers,
                )
            ).json()
            assert _feature(plan_a_body, "cover_letters")["adoption"]["users"] == 5
            assert _feature(plan_a_body, "interview_prep")["adoption"]["users"] == 0
            assert {
                segment["key"]
                for segment in plan_a_body["features"][0]["segments"]
                if segment["dimension"] == "plan"
            } == {plan_a}
            assert {
                segment["key"]
                for segment in plan_a_body["features"][0]["segments"]
                if segment["dimension"] == "cohort"
            } == {current_label}

            plan_b_body = (
                await client.get(
                    f"/admin/analytics/career-adoption?days=90&plan={plan_b}",
                    headers=headers,
                )
            ).json()
            assert _feature(plan_b_body, "interview_prep")["adoption"]["users"] == 5
            assert _feature(plan_b_body, "cover_letters")["adoption"]["users"] == 0
            assert {
                segment["key"]
                for segment in plan_b_body["features"][0]["segments"]
                if segment["dimension"] == "cohort"
            } == {previous_label}

            cohort_body = (
                await client.get(
                    f"/admin/analytics/career-adoption?days=90&cohort={previous_label}",
                    headers=headers,
                )
            ).json()
            cohort_plan_keys = {
                segment["key"]
                for segment in cohort_body["features"][0]["segments"]
                if segment["dimension"] == "plan"
            }
            assert plan_b in cohort_plan_keys
            assert plan_a not in cohort_plan_keys
        finally:
            await _cleanup(db_session, user_ids)

    async def test_five_user_suppression(self, client: AsyncClient, db_session: AsyncSession):
        big_plan = f"ca_big_{uuid.uuid4().hex[:5]}"
        small_plan = f"ca_small_{uuid.uuid4().hex[:5]}"
        user_ids: list[str] = []
        try:
            big_ids = [
                await _create_user(db_session, plan=big_plan, created_at=datetime.now(timezone.utc))
                for _ in range(5)
            ]
            small_ids = [
                await _create_user(db_session, plan=small_plan, created_at=datetime.now(timezone.utc))
                for _ in range(4)
            ]
            user_ids = [*big_ids, *small_ids]
            for user_id in user_ids:
                await _seed_event(
                    db_session,
                    user_id,
                    action="cover_letter_generated",
                    metadata={"feature": "cover_letters"},
                )

            headers = await _admin_headers(db_session)
            combined_response = await client.get(
                f"/admin/analytics/career-adoption?days=30&plan={big_plan},{small_plan}",
                headers=headers,
            )
            assert combined_response.status_code == 200, combined_response.text
            combined = combined_response.json()
            plan_keys = {
                segment["key"]
                for segment in combined["features"][0]["segments"]
                if segment["dimension"] == "plan"
            }
            assert big_plan in plan_keys
            assert small_plan not in plan_keys
            assert combined["suppressed_segments"]["plan"] >= 1

            headers = await _admin_headers(db_session)
            small_response = await client.get(
                f"/admin/analytics/career-adoption?days=30&plan={small_plan}",
                headers=headers,
            )
            assert small_response.status_code == 200, small_response.text
            small = small_response.json()
            assert small["suppressed"] is True
            assert small["features"][0]["adoption"] is None
            assert small["reconciliation"]["suppressed"] is True
            assert small["suppressed_segments"] == {"plan": 1, "cohort": 1}
        finally:
            await _cleanup(db_session, user_ids)

    async def test_privacy_excludes_content_and_identities(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        plan = f"ca_priv_{uuid.uuid4().hex[:6]}"
        user_ids: list[str] = []
        now = datetime.now(timezone.utc)
        try:
            user_ids = [
                await _create_user(db_session, plan=plan, created_at=now) for _ in range(5)
            ]
            for user_id in user_ids:
                resume_id = await _create_resume(db_session, user_id=user_id)
                await _seed_event(
                    db_session,
                    user_id,
                    action="cover_letter_generated",
                    metadata={
                        "feature": "cover_letters",
                        "raw_text": SECRET_COVER_LETTER,
                        "job_description": SECRET_JOB_DESCRIPTION,
                    },
                )
                await _seed_cover_letter(
                    db_session,
                    user_id=user_id,
                    resume_id=resume_id,
                )
                await _seed_interview_prep(
                    db_session,
                    user_id=user_id,
                    resume_id=resume_id,
                )
                await _seed_career_analysis(
                    db_session,
                    user_id=user_id,
                    resume_id=resume_id,
                )

            headers = await _admin_headers(db_session)
            response = await client.get(
                f"/admin/analytics/career-adoption?days=30&plan={plan}",
                headers=headers,
            )
            assert response.status_code == 200, response.text
            payload = response.text
            for secret in (
                SECRET_COVER_LETTER,
                SECRET_JOB_DESCRIPTION,
                SECRET_INTERVIEW,
                SECRET_CAREER,
            ):
                assert secret not in payload
            for user_id in user_ids:
                assert user_id not in payload
            assert "event_metadata" not in payload
            assert "user_id" not in payload
            assert "cover_letter_id" not in payload
            assert "resume_id" not in payload
            assert "job_description" not in payload
            assert "latex_content" not in payload
            assert "questions" not in payload
            assert "llm_analysis" not in payload
            body = response.json()
            assert body["privacy"]["aggregate_only"] is True
            assert body["privacy"]["per_user_rows"] is False
        finally:
            await _cleanup(db_session, user_ids)

    async def test_analytics_storage_reuses_existing_usage_analytics_jsonb(self):
        from sqlalchemy import JSON

        column = UsageAnalytics.__table__.c.event_metadata
        assert isinstance(column.type, (JSON, JSONB))
        assert column.nullable is True
        versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
        added = [
            path.name
            for path in versions.glob("*.py")
            if "2093" in path.name or "career_adoption" in path.name
        ]
        assert added == []


class TestCareerAdoptionAccess:
    async def test_endpoint_is_admin_only(self, client: AsyncClient, db_session: AsyncSession):
        plan = f"ca_access_{uuid.uuid4().hex[:6]}"
        user_id = await _create_user(db_session, plan=plan)
        headers = await _session_headers(db_session, user_id)
        try:
            assert (
                await client.get("/admin/analytics/career-adoption?days=7")
            ).status_code == 401
            assert (
                await client.get("/admin/analytics/career-adoption?days=7", headers=headers)
            ).status_code == 403

            admin = await _admin_headers(db_session)
            allowed = await client.get(
                "/admin/analytics/career-adoption?days=7", headers=admin
            )
            assert allowed.status_code == 200
            assert allowed.json()["privacy"]["aggregate_only"] is True
            alias = await client.get(
                "/admin/analytics/career-feature-adoption?days=7", headers=admin
            )
            assert alias.status_code == 200
        finally:
            await _cleanup(db_session, [user_id])
