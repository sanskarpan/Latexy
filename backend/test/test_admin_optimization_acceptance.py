"""Admin optimization acceptance: reconciliation, filters, suppression, CSV."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SECRET_PATCH_TEXT = "SECRET_PATCH_TEXT_2092_MUST_NOT_LEAK"
SECRET_RESUME = "SECRET_RESUME_CONTENT_2092_MUST_NOT_LEAK"
SECRET_SUGGESTION = "SECRET_SUGGESTION_TEXT_2092_MUST_NOT_LEAK"


@pytest.fixture(autouse=True)
async def _isolate_acceptance_sources(db_session: AsyncSession):
    await db_session.execute(text("DELETE FROM resume_suggestion_decisions"))
    await db_session.execute(text("DELETE FROM resume_optimization_runs"))
    await db_session.commit()
    yield


def _email(prefix: str) -> str:
    return f"test_acceptance_{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
) -> tuple[str, dict[str, str]]:
    user_id = str(uuid.uuid4())
    token = f"test_sess_acceptance_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Acceptance User', :role, true, :plan, 'active', false)"
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


async def _create_resume(
    db: AsyncSession,
    *,
    user_id: str,
    persona: str = "startup",
) -> str:
    resume_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content, metadata, created_at) "
            "VALUES (:id, :uid, 'Acceptance Resume', :latex, CAST(:metadata AS jsonb), :created)"
        ),
        {
            "id": resume_id,
            "uid": user_id,
            "latex": SECRET_RESUME,
            "metadata": json.dumps({"last_persona": persona}),
            "created": datetime.now(timezone.utc) - timedelta(days=1),
        },
    )
    await db.commit()
    return resume_id


async def _seed_run(
    db: AsyncSession,
    *,
    user_id: str,
    resume_id: str,
    patches: list[dict],
    decisions: dict[str, str],
    updated_at: datetime,
    persona: str = "startup",
) -> str:
    job_id = f"test_acceptance_job_{uuid.uuid4().hex}"
    await db.execute(
        text(
            "INSERT INTO job_finalizations "
            "(id, job_id, user_id, job_type, resume_id, state, owner_epoch, expires_at, created_at) "
            "VALUES (:id, :job_id, :uid, 'llm_optimization', :resume, 'completed', 1, :expires, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "job_id": job_id,
            "uid": user_id,
            "resume": resume_id,
            "expires": updated_at + timedelta(days=7),
            "created": updated_at - timedelta(hours=1),
        },
    )
    run_id = f"test_acceptance_run_{uuid.uuid4().hex}"
    result = {
        "patches": patches,
        "candidate_source_sha256": "c" * 64,
        "candidate_structured_content": {"secret": SECRET_RESUME},
        "status": "completed",
    }
    await db.execute(
        text(
            "INSERT INTO resume_optimization_runs "
            "(id, job_id, resume_id, user_id, base_revision, source_sha256, context_hash, "
            "effort, provider, model, credential_scope, status, snapshot, context_payload, "
            "budget, result, decisions, expires_at, created_at, updated_at) "
            "VALUES (:id, :job_id, :resume, :uid, 1, :sha, :sha, 'standard', 'openai', 'gpt-4o-mini', "
            "'platform', 'completed', '{}'::jsonb, CAST(:context AS jsonb), '{}'::jsonb, "
            "CAST(:result AS jsonb), CAST(:decisions AS jsonb), :expires, :created, :updated)"
        ),
        {
            "id": run_id,
            "job_id": job_id,
            "resume": resume_id,
            "uid": user_id,
            "sha": "a" * 64,
            "context": json.dumps({"direction": {"persona": persona}, "private": SECRET_PATCH_TEXT}),
            "result": json.dumps(result),
            "decisions": json.dumps({"patches": decisions}),
            "expires": updated_at + timedelta(days=7),
            "created": updated_at - timedelta(hours=1),
            "updated": updated_at,
        },
    )
    await db.commit()
    return run_id


async def _seed_suggestion(
    db: AsyncSession,
    *,
    user_id: str,
    resume_id: str,
    status: str,
    created_at: datetime,
) -> str:
    suggestion_id = f"suggestion.{SECRET_SUGGESTION}.{uuid.uuid4().hex[:8]}"
    await db.execute(
        text(
            "INSERT INTO resume_suggestion_decisions "
            "(id, resume_id, suggestion_id, status, decided_by_user_id, decided_by_role, "
            "expected_content_sha256, result_content, created_at) "
            "VALUES (:id, :resume, :suggestion, :status, :uid, 'owner', :sha, :content, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "resume": resume_id,
            "suggestion": suggestion_id,
            "status": status,
            "uid": user_id,
            "sha": "b" * 64,
            "content": SECRET_RESUME if status == "accepted" else "",
            "created": created_at,
        },
    )
    await db.commit()
    return suggestion_id


async def _seed_five_run_users(
    db: AsyncSession,
    *,
    plan: str,
    persona: str,
    updated_at: datetime,
    feature_node: str = "experience.abc",
) -> list[tuple[str, str, dict[str, str]]]:
    users = [await _create_user(db, plan=plan) for _ in range(5)]
    for index, (user_id, _headers) in enumerate(users):
        resume_id = await _create_resume(db, user_id=user_id, persona=persona)
        await _seed_run(
            db,
            user_id=user_id,
            resume_id=resume_id,
            patches=[
                {"patch_id": f"patch.accepted.{index}", "node_id": feature_node, "text": SECRET_PATCH_TEXT},
                {"patch_id": f"patch.rejected.{index}", "node_id": feature_node, "text": SECRET_PATCH_TEXT},
                {"patch_id": f"patch.undecided.{index}", "node_id": feature_node, "text": SECRET_PATCH_TEXT},
                # A duplicated candidate id must not inflate the denominator.
                {"patch_id": f"patch.accepted.{index}", "node_id": feature_node, "text": SECRET_PATCH_TEXT},
            ],
            decisions={
                f"patch.accepted.{index}": "accepted",
                f"patch.rejected.{index}": "rejected",
            },
            updated_at=updated_at,
            persona=persona,
        )
    return users


class TestOptimizationAcceptanceEndpoint:
    async def test_admin_only_access(self, client: AsyncClient, db_session: AsyncSession):
        _uid, user_headers = await _create_user(db_session)
        assert (await client.get("/admin/analytics/optimization-acceptance", headers=user_headers)).status_code == 403

        _sid, support_headers = await _create_user(db_session, role="support")
        assert (
            await client.get("/admin/analytics/optimization-acceptance", headers=support_headers)
        ).status_code == 403
        assert (await client.get("/admin/analytics/optimization-acceptance")).status_code == 401

        admin = await _admin_headers(db_session)
        allowed = await client.get("/admin/analytics/optimization-acceptance", headers=admin)
        assert allowed.status_code == 200, allowed.text
        assert (await client.get("/admin/analytics/optimization-acceptance/export.csv", headers=admin)).status_code == 200

    async def test_rates_reconcile_and_duplicate_decisions_do_not_double_count(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        now = datetime.now(timezone.utc) - timedelta(hours=2)
        users = await _seed_five_run_users(db_session, plan="pro", persona="startup", updated_at=now)

        # Five accepted, three rejected and two conflicted suggestion decisions.
        for index, status in enumerate(
            ["accepted"] * 5 + ["rejected"] * 3 + ["conflicted"] * 2
        ):
            user_id, _headers = users[index % len(users)]
            resume_id = await _create_resume(db_session, user_id=user_id, persona="startup")
            await _seed_suggestion(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                status=status,
                created_at=now + timedelta(minutes=index),
            )

        headers = await _admin_headers(db_session)
        response = await client.get(
            "/admin/analytics/optimization-acceptance?days=30", headers=headers
        )
        assert response.status_code == 200, response.text
        payload = response.json()

        totals = payload["totals"]
        # Runs: 5 accepted + 5 rejected + 5 undecided, duplicates ignored.
        # Suggestions: 5 accepted + 3 rejected + 2 discarded (conflicted).
        assert totals == {
            "candidates_shown": 25,
            "decided": 20,
            "accepted": 10,
            "rejected": 8,
            "discarded": 2,
            "undecided": 5,
            "acceptance_rate_pct": 50.0,
            "decision_rate_pct": 80.0,
            "accepted_of_shown_pct": 40.0,
            "users": 5,
        }

        reconciliation = payload["reconciliation"]
        assert reconciliation["tables"] == [
            "resume_optimization_runs",
            "resume_suggestion_decisions",
        ]
        assert reconciliation["run_candidates_shown"] == 15
        assert reconciliation["run_decision_keys"] == 10
        assert reconciliation["run_duplicate_patch_ids"] == 5
        assert reconciliation["suggestion_rows_scanned"] == 10
        assert reconciliation["candidates_shown"] == 25
        assert reconciliation["decided"] == 20
        assert reconciliation["reconciled"] is True
        assert reconciliation["hidden_by_suppression"] is False

        assert payload["by_feature"] == sorted(
            payload["by_feature"], key=lambda row: (-row["decided"], -row["candidates_shown"], row["feature"])
        )
        run_feature = next(row for row in payload["by_feature"] if row["feature"] == "experience")
        assert run_feature["candidates_shown"] == 15
        assert run_feature["decided"] == 10
        assert run_feature["users"] == 5
        suggestion_feature = next(
            row for row in payload["by_feature"] if row["feature"] == "inline_suggestions"
        )
        assert suggestion_feature["candidates_shown"] == 10
        assert suggestion_feature["decided"] == 10
        assert suggestion_feature["discarded"] == 2

        assert sum(point["candidates_shown"] for point in payload["by_day"]) == 25
        assert sum(point["decided"] for point in payload["by_day"]) == 20

        # Aggregate-only: no decision text, suggestion id, resume source or user id.
        for user_id, _headers in users:
            assert user_id not in response.text
        for secret in (SECRET_PATCH_TEXT, SECRET_RESUME, SECRET_SUGGESTION):
            assert secret not in response.text
        assert "patch.accepted" not in response.text
        assert "suggestion_id" not in response.text
        assert "result_content" not in response.text

    async def test_filters_by_plan_persona_feature_and_date(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=3)
        await _seed_five_run_users(
            db_session, plan="pro", persona="startup", updated_at=now, feature_node="experience.abc"
        )
        await _seed_five_run_users(
            db_session, plan="free", persona="finance", updated_at=old, feature_node="summary.abc"
        )

        headers = await _admin_headers(db_session)

        in_range = await client.get(
            "/admin/analytics/optimization-acceptance?days=30&plan=pro&persona=startup&feature=experience",
            headers=headers,
        )
        assert in_range.status_code == 200, in_range.text
        filtered = in_range.json()
        assert filtered["filters"]["plan"] == ["pro"]
        assert filtered["filters"]["persona"] == "startup"
        assert filtered["filters"]["feature"] == "experience"
        assert filtered["totals"]["candidates_shown"] == 15
        assert [row["plan"] for row in filtered["by_plan"]] == ["pro"]
        assert [row["persona"] for row in filtered["by_persona"]] == ["startup"]
        assert [row["feature"] for row in filtered["by_feature"]] == ["experience"]

        wide = await client.get(
            "/admin/analytics/optimization-acceptance?days=90", headers=headers
        )
        assert wide.status_code == 200, wide.text
        assert wide.json()["totals"]["candidates_shown"] == 30
        assert {row["plan"] for row in wide.json()["by_plan"]} == {"pro", "free"}
        assert {row["feature"] for row in wide.json()["by_feature"]} == {"experience", "summary"}

        explicit = await client.get(
            "/admin/analytics/optimization-acceptance"
            f"?start_date={now.date().isoformat()}&end_date={now.date().isoformat()}",
            headers=headers,
        )
        assert explicit.status_code == 200, explicit.text
        assert explicit.json()["totals"]["candidates_shown"] == 15

        invalid = await client.get(
            "/admin/analytics/optimization-acceptance?start_date=2026-02-01&end_date=2026-01-01",
            headers=headers,
        )
        assert invalid.status_code == 422

    async def test_five_user_suppression(self, client: AsyncClient, db_session: AsyncSession):
        now = datetime.now(timezone.utc) - timedelta(hours=1)
        small_users = [await _create_user(db_session, plan="pro") for _ in range(4)]
        for index, (user_id, _headers) in enumerate(small_users):
            resume_id = await _create_resume(db_session, user_id=user_id, persona="small")
            await _seed_run(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                patches=[
                    {"patch_id": f"patch.small.accepted.{index}", "node_id": "experience.abc"},
                    {"patch_id": f"patch.small.rejected.{index}", "node_id": "experience.abc"},
                ],
                decisions={
                    f"patch.small.accepted.{index}": "accepted",
                    f"patch.small.rejected.{index}": "rejected",
                },
                updated_at=now,
                persona="small",
            )

        headers = await _admin_headers(db_session)
        suppressed = await client.get(
            "/admin/analytics/optimization-acceptance?days=30&persona=small", headers=headers
        )
        assert suppressed.status_code == 200, suppressed.text
        payload = suppressed.json()
        assert payload["suppressed"] is True
        assert payload["totals"] == {
            "candidates_shown": 0,
            "decided": 0,
            "accepted": 0,
            "rejected": 0,
            "discarded": 0,
            "undecided": 0,
            "acceptance_rate_pct": 0.0,
            "decision_rate_pct": 0.0,
            "accepted_of_shown_pct": 0.0,
            "users": 0,
        }
        assert payload["by_feature"] == []
        assert payload["by_day"] == []
        assert payload["reconciliation"]["hidden_by_suppression"] is True
        for user_id, _headers in small_users:
            assert user_id not in suppressed.text

        await _seed_five_run_users(
            db_session, plan="pro", persona="visible", updated_at=now
        )
        visible = await client.get(
            "/admin/analytics/optimization-acceptance?days=30&persona=visible", headers=headers
        )
        assert visible.status_code == 200, visible.text
        assert visible.json()["suppressed"] is False
        assert visible.json()["totals"]["candidates_shown"] == 15
        assert visible.json()["totals"]["users"] == 5

    async def test_idempotent_suggestion_decisions_are_not_double_counted(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from sqlalchemy.exc import IntegrityError

        now = datetime.now(timezone.utc) - timedelta(minutes=5)
        seeded: list[tuple[str, str, str, str]] = []
        for _index in range(5):
            user_id, _headers = await _create_user(db_session, plan="pro")
            resume_id = await _create_resume(db_session, user_id=user_id, persona="startup")
            suggestion_id = await _seed_suggestion(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                status="accepted",
                created_at=now,
            )
            seeded.append((user_id, resume_id, suggestion_id, "accepted"))

        _user_id, resume_id, suggestion_id, _status = seeded[0]
        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(
                    "INSERT INTO resume_suggestion_decisions "
                    "(id, resume_id, suggestion_id, status, decided_by_user_id, decided_by_role, "
                    "expected_content_sha256, result_content) "
                    "VALUES (:id, :resume, :suggestion, 'rejected', :uid, 'owner', :sha, '')"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "resume": resume_id,
                    "suggestion": suggestion_id,
                    "uid": _user_id,
                    "sha": "b" * 64,
                },
            )
            await db_session.commit()
        await db_session.rollback()

        headers = await _admin_headers(db_session)
        response = await client.get(
            "/admin/analytics/optimization-acceptance?days=30", headers=headers
        )
        assert response.status_code == 200, response.text
        totals = response.json()["totals"]
        assert totals["candidates_shown"] == 5
        assert totals["decided"] == 5
        assert totals["accepted"] == 5
        assert totals["users"] == 5
        assert response.json()["reconciliation"]["suggestion_rows_scanned"] == 5

    async def test_csv_export_is_aggregate_only(self, client: AsyncClient, db_session: AsyncSession):
        now = datetime.now(timezone.utc) - timedelta(hours=2)
        users = await _seed_five_run_users(db_session, plan="pro", persona="startup", updated_at=now)
        for index, status in enumerate(["accepted", "accepted", "rejected", "conflicted", "rejected"]):
            user_id, _headers = users[index]
            resume_id = await _create_resume(db_session, user_id=user_id, persona="startup")
            await _seed_suggestion(
                db_session,
                user_id=user_id,
                resume_id=resume_id,
                status=status,
                created_at=now + timedelta(minutes=index),
            )

        headers = await _admin_headers(db_session)
        response = await client.get(
            "/admin/analytics/optimization-acceptance?days=30&format=csv", headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        assert 'attachment; filename="optimization-acceptance-' in response.headers["content-disposition"]

        lines = [line for line in response.text.splitlines() if line]
        assert lines[0].split(",") == [
            "dimension",
            "key",
            "candidates_shown",
            "decided",
            "accepted",
            "rejected",
            "discarded",
            "undecided",
            "acceptance_rate_pct",
            "decision_rate_pct",
            "accepted_of_shown_pct",
            "users",
        ]
        total = lines[1].split(",")
        assert total[:2] == ["total", "all"]
        assert total[2:8] == ["20", "15", "7", "7", "1", "5"]
        assert any(line.startswith("feature,experience,") for line in lines)
        assert any(line.startswith("feature,inline_suggestions,") for line in lines)
        assert any(line.startswith("date,") for line in lines)
        assert any(line.startswith("source,resume_optimization_runs,") for line in lines)
        assert any(line.startswith("source,resume_suggestion_decisions,") for line in lines)

        for user_id, _headers in users:
            assert user_id not in response.text
        for secret in (SECRET_PATCH_TEXT, SECRET_RESUME, SECRET_SUGGESTION):
            assert secret not in response.text

        alias = await client.get(
            "/admin/analytics/optimization-acceptance/export.csv?days=30", headers=headers
        )
        assert alias.status_code == 200
        assert alias.headers["content-type"].startswith("text/csv")
