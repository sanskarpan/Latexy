"""Regression probes for typed durable-terminal payload completeness.

These cases deliberately exercise the read-only recovery service rather than
mutating terminal rows. A completed arbiter decision must remain durable, but a
typed success without its required generated output must not be exposed as a
successful empty result to REST/stream clients.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.job_routes import get_job_result, get_job_state
from app.database.models import JobFinalization, User
from app.main import app
from app.middleware.auth_middleware import get_current_user_optional
from app.services.job_result_recovery import recover_terminal_job
from app.workers.finalization_arbiter import (
    MAX_GENERATED_TEXT_BYTES,
    MAX_LATEX_BYTES,
    bounded_result_payload,
    typed_missing_output_fields,
)


def _expires() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=10)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_type", "payload", "required_output"),
    [
        ("ats_deep_analysis", {"success": True}, "deep_analysis"),
        (
            "ats_deep_analysis",
            {"success": True, "deep_analysis": {"overall_score": 90}},
            "deep_analysis",
        ),
        ("cover_letter_generation", {"success": True, "cover_letter_latex": ""}, "cover_letter_latex"),
        ("cover_letter_generation", {"success": True, "cover_letter_latex": 123}, "cover_letter_latex"),
    ],
)
async def test_typed_completed_row_cannot_recover_as_success_without_generated_output(
    db_session_factory,
    job_type: str,
    payload: dict,
    required_output: str,
):
    job_id = f"test_typed_integrity_{uuid4().hex}"
    user_id = str(uuid4())
    async with db_session_factory() as session:
        session.add(User(id=user_id, email=f"{job_id}@example.com"))
        await session.flush()
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                user_id=user_id,
                job_type=job_type,
                state="completed",
                terminal_result="completed",
                result_payload=payload,
                expires_at=_expires(),
            )
        )
        await session.commit()

    try:
        async with db_session_factory() as session:
            before = (
                await session.execute(select(JobFinalization).where(JobFinalization.job_id == job_id))
            ).scalar_one()
            before_snapshot = (before.state, before.terminal_result, dict(before.result_payload or {}))
            recovered = await recover_terminal_job(session, job_id=job_id, user_id=user_id)
            assert recovered is not None
            assert recovered["state"] == "completed"
            assert recovered["payload"].get("success") is False
            assert recovered["payload"].get("recovery_complete") is False
            assert recovered["payload"].get("error_code") == "output_unavailable"
            assert required_output in recovered["payload"]["omitted_output_fields"]
            after = (
                await session.execute(select(JobFinalization).where(JobFinalization.job_id == job_id))
            ).scalar_one()
            assert (after.state, after.terminal_result, dict(after.result_payload or {})) == before_snapshot
    finally:
        async with db_session_factory() as session:
            row = (
                await session.execute(select(JobFinalization).where(JobFinalization.job_id == job_id))
            ).scalar_one_or_none()
            if row is not None:
                await session.delete(row)
                await session.flush()
                await session.execute(User.__table__.delete().where(User.id == user_id))
                await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_type", "payload"),
    [
        ("cover_letter_generation", {"success": True, "cover_letter_latex": r"\\documentclass{letter}"}),
        (
            "ats_deep_analysis",
            {
                "success": True,
                "deep_analysis": {
                    "overall_score": 90,
                    "overall_feedback": "Strong match",
                    "sections": [
                        {
                            "name": "Experience",
                            "score": 80,
                            "strengths": ["Clear ownership"],
                            "improvements": ["Add dates"],
                        }
                    ],
                    "ats_compatibility": {"score": 90, "issues": [], "keyword_gaps": []},
                },
            },
        ),
        ("latex_compilation", {"success": True, "pdf_job_id": "compile-job"}),
    ],
)
async def test_present_typed_terminal_output_remains_recoverable(
    db_session_factory, job_type: str, payload: dict
):
    job_id = f"test_typed_present_{uuid4().hex}"
    user_id = str(uuid4())
    async with db_session_factory() as session:
        session.add(User(id=user_id, email=f"{job_id}@example.com"))
        await session.flush()
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                user_id=user_id,
                job_type=job_type,
                state="completed",
                terminal_result="completed",
                result_payload=payload,
                expires_at=_expires(),
            )
        )
        await session.commit()

    try:
        async with db_session_factory() as session:
            recovered = await recover_terminal_job(session, job_id=job_id, user_id=user_id)
        assert recovered is not None
        assert recovered["state"] == "completed"
        assert recovered["payload"]["success"] is True
        if job_type == "ats_deep_analysis":
            section = recovered["payload"]["deep_analysis"]["sections"][0]
            assert section["strengths"] == ["Clear ownership"]
            assert section["improvements"] == ["Add dates"]
    finally:
        async with db_session_factory() as session:
            row = (
                await session.execute(select(JobFinalization).where(JobFinalization.job_id == job_id))
            ).scalar_one_or_none()
            if row is not None:
                await session.delete(row)
                await session.flush()
                await session.execute(User.__table__.delete().where(User.id == user_id))
                await session.commit()


def test_rebounding_an_incomplete_payload_preserves_its_integrity_marker():
    first = bounded_result_payload(
        "test_rebound_incomplete",
        {"success": True, "cover_letter_latex": "x" * (MAX_LATEX_BYTES + 1)},
    )
    assert first["recovery_complete"] is False
    assert "cover_letter_latex" in first["omitted_output_fields"]

    rebound = bounded_result_payload("test_rebound_incomplete", first)
    assert rebound["recovery_complete"] is False
    assert "cover_letter_latex" in rebound["omitted_output_fields"]

    marked = bounded_result_payload(
        "test_rebound_known_fields",
        {
            "success": True,
            "recovery_complete": False,
            "omitted_output_fields": [
                "projects",
                "ats_details",
                "artifacts",
                "ats_compatibility",
                "job_match",
                "multi_dim_scores",
                "changes_made",
                "detailed_analysis",
                "extracted_text",
                "provider_secret",
                {"not": "a field"},
            ],
        },
    )
    assert marked["recovery_complete"] is False
    assert set(marked["omitted_output_fields"]) == {
        "projects",
        "ats_details",
        "artifacts",
        "ats_compatibility",
        "job_match",
        "multi_dim_scores",
        "changes_made",
        "detailed_analysis",
        "extracted_text",
    }


def _valid_jd_payload() -> dict:
    return {
        "success": True,
        "keywords": ["Python", "PostgreSQL"],
        "requirements": ["Build reliable services"],
        "preferred_qualifications": [],
        "detected_industry": "technology",
        "analysis_metrics": {"word_count": 12, "sentence_count": 2, "keyword_count": 2},
    }


def test_jd_bounded_lists_preserve_exact_long_text_and_closed_metrics():
    requirement = "Distributed systems with PostgreSQL — " * 130
    assert len(requirement.encode("utf-8")) > 2048
    payload = _valid_jd_payload()
    payload["requirements"] = [requirement]

    bounded = bounded_result_payload("test_jd_faithful_text", payload)

    assert bounded["requirements"] == [requirement]
    assert bounded["recovery_complete"] is True
    assert bounded["analysis_metrics"] == payload["analysis_metrics"]


def test_jd_utf8_boundary_and_rebound_preserve_exact_text():
    # Two-byte UTF-8 text exercises the byte boundary rather than Python's
    # code-point length. The exact aggregate limit is accepted unchanged.
    exact = "é" * (MAX_GENERATED_TEXT_BYTES // 2)
    payload = _valid_jd_payload()
    payload["requirements"] = [exact]

    bounded = bounded_result_payload("test_jd_utf8_boundary", payload)
    rebound = bounded_result_payload("test_jd_utf8_boundary", bounded)

    assert bounded["requirements"] == [exact]
    assert rebound["requirements"] == [exact]
    assert rebound["recovery_complete"] is True


def test_jd_multibyte_aggregate_overflow_is_not_truncated():
    # Each item is individually valid, but their aggregate crosses the limit.
    first = "é" * (MAX_GENERATED_TEXT_BYTES // 2)
    second = "é"
    payload = _valid_jd_payload()
    payload["requirements"] = [first, second]

    bounded = bounded_result_payload("test_jd_utf8_overflow", payload)

    assert bounded["recovery_complete"] is False
    assert "requirements" in bounded["omitted_output_fields"]
    assert "requirements" not in bounded


@pytest.mark.parametrize(
    "bad_field,bad_value",
    [
        ("requirements", ["valid", None]),
        ("requirements", ["x"] * 101),
        ("requirements", ["x" * (MAX_GENERATED_TEXT_BYTES + 1)]),
        ("analysis_metrics", {"word_count": True, "sentence_count": 2, "keyword_count": 1}),
        ("analysis_metrics", {"word_count": 1, "sentence_count": -1, "keyword_count": 1}),
        ("analysis_metrics", {"word_count": 1.0, "sentence_count": 2, "keyword_count": 1}),
        ("analysis_metrics", {"word_count": 1, "sentence_count": 2}),
    ],
)
def test_malformed_or_oversized_jd_field_is_omitted_and_stays_incomplete(bad_field, bad_value):
    payload = _valid_jd_payload()
    payload[bad_field] = bad_value

    bounded = bounded_result_payload("test_jd_invalid_field", payload)
    assert bounded["recovery_complete"] is False
    assert bad_field in bounded["omitted_output_fields"]
    assert bad_field not in bounded

    rebound = bounded_result_payload("test_jd_invalid_field", bounded)
    assert rebound["recovery_complete"] is False
    assert bad_field in rebound["omitted_output_fields"]
    assert bad_field not in rebound


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "keywords": ["Python"],
                "requirements": [None],
                "preferred_qualifications": [],
                "detected_industry": "technology",
                "analysis_metrics": {"word_count": 1, "sentence_count": 1, "keyword_count": 1},
            },
            ["requirements"],
        ),
        (
            {
                "keywords": ["Python"],
                "requirements": [],
                "preferred_qualifications": [],
                "detected_industry": "technology",
                "analysis_metrics": {"word_count": 1, "sentence_count": 1.5, "keyword_count": 1},
            },
            ["analysis_metrics"],
        ),
        (
            {
                "keywords": ["Python"],
                "requirements": [],
                "preferred_qualifications": [],
                "detected_industry": "technology",
            },
            ["analysis_metrics"],
        ),
    ],
)
def test_typed_missing_output_fields_reports_rejected_jd_shapes(payload, expected):
    assert typed_missing_output_fields("job_description_analysis", payload) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        # Legacy/generic PDF rows have no typed generated-output requirement.
        ({"success": True, "pdf_job_id": "legacy-pdf"}, {"success": True, "pdf_job_id": "legacy-pdf"}),
        ({"success": False, "error_code": "worker_failed"}, {"success": False, "error_code": "worker_failed"}),
        ({"success": False, "cancelled": True}, {"success": False, "cancelled": True}),
    ],
)
def test_legacy_pdf_and_non_success_terminal_markers_remain_bounded(payload: dict, expected: dict):
    bounded = bounded_result_payload("test_legacy_contract", payload)
    for key, value in expected.items():
        assert bounded[key] == value


class _RecoveryRedis:
    def __init__(self, job_id: str, user_id: str):
        self.job_id = job_id
        self.user_id = user_id

    async def get(self, key: str):
        if key.endswith(":meta"):
            return json.dumps({"job_id": self.job_id, "user_id": self.user_id})
        if key.endswith(":state"):
            return json.dumps({"status": "processing", "stage": "worker", "percent": 50, "last_updated": 1})
        return None


@pytest.mark.asyncio
async def test_route_functions_keep_completed_state_and_expose_delivery_error(
    db_session_factory,
):
    job_id = str(uuid4())
    user_id = str(uuid4())
    async with db_session_factory() as session:
        session.add(User(id=user_id, email=f"{job_id}@example.com"))
        await session.flush()
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                user_id=user_id,
                job_type="cover_letter_generation",
                state="completed",
                terminal_result="completed",
                result_payload={"success": True, "cover_letter_latex": ""},
                expires_at=_expires(),
            )
        )
        await session.commit()

    try:
        redis = _RecoveryRedis(job_id, user_id)
        async with db_session_factory() as session:
            with patch("app.api.job_routes.get_redis_client", new=AsyncMock(return_value=redis)):
                result = await get_job_result(job_id, session, user_id)
                state = await get_job_state(job_id, session, user_id)
            assert result.success is False
            assert result.result is not None
            assert result.result["success"] is False
            assert result.result["recovery_complete"] is False
            assert result.result["error_code"] == "output_unavailable"
            assert result.error == "Completed job output unavailable"
            assert state.status == "completed"
            assert state.stage == "recovered"
            row = (
                await session.execute(select(JobFinalization).where(JobFinalization.job_id == job_id))
            ).scalar_one()
            assert row.state == "completed"
            assert row.terminal_result == "completed"
            assert row.result_payload == {"success": True, "cover_letter_latex": ""}
    finally:
        async with db_session_factory() as session:
            row = (
                await session.execute(select(JobFinalization).where(JobFinalization.job_id == job_id))
            ).scalar_one_or_none()
            if row is not None:
                await session.delete(row)
                await session.flush()
                await session.execute(User.__table__.delete().where(User.id == user_id))
                await session.commit()


@pytest.mark.asyncio
async def test_completed_explicit_incomplete_marker_is_not_promoted(db_session_factory):
    job_id = f"test_explicit_marker_{uuid4().hex}"
    user_id = str(uuid4())
    payload = {
        "success": True,
        "pdf_job_id": "legacy-pdf",
        "recovery_complete": False,
        "omitted_output_fields": ["optimized_latex", "provider_secret"],
    }
    async with db_session_factory() as session:
        session.add(User(id=user_id, email=f"{job_id}@example.com"))
        await session.flush()
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                user_id=user_id,
                job_type="combined",
                state="completed",
                terminal_result="completed",
                result_payload=payload,
                expires_at=_expires(),
            )
        )
        await session.commit()
    try:
        async with db_session_factory() as session:
            recovered = await recover_terminal_job(session, job_id=job_id, user_id=user_id)
        assert recovered is not None
        assert recovered["state"] == "completed"
        assert recovered["output_unavailable"] is True
        assert recovered["payload"]["success"] is False
        assert recovered["payload"]["recovery_complete"] is False
        assert recovered["payload"]["omitted_output_fields"] == ["optimized_latex"]
        assert recovered["payload"]["error_code"] == "output_unavailable"
    finally:
        async with db_session_factory() as session:
            row = (
                await session.execute(select(JobFinalization).where(JobFinalization.job_id == job_id))
            ).scalar_one_or_none()
            if row is not None:
                await session.delete(row)
                await session.flush()
                await session.execute(User.__table__.delete().where(User.id == user_id))
                await session.commit()


@pytest.mark.asyncio
async def test_http_recovery_serializes_delivery_error_and_completed_state(
    db_session_factory, client
):
    job_id = str(uuid4())
    user_id = str(uuid4())
    async with db_session_factory() as session:
        session.add(User(id=user_id, email=f"{job_id}@example.com"))
        await session.flush()
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                user_id=user_id,
                job_type="cover_letter_generation",
                state="completed",
                terminal_result="completed",
                result_payload={"success": True, "cover_letter_latex": ""},
                expires_at=_expires(),
            )
        )
        await session.commit()

    redis = _RecoveryRedis(job_id, user_id)
    app.dependency_overrides[get_current_user_optional] = lambda: user_id
    try:
        with patch("app.api.job_routes.get_redis_client", new=AsyncMock(return_value=redis)):
            result_response = await client.get(f"/jobs/{job_id}/result")
            state_response = await client.get(f"/jobs/{job_id}/state")
        result = result_response.json()
        state = state_response.json()
        assert result_response.status_code == 200
        assert result["success"] is False
        assert result["result"]["success"] is False
        assert result["result"]["recovery_complete"] is False
        assert result["result"]["error_code"] == "output_unavailable"
        assert result["error"] == "Completed job output unavailable"
        assert state_response.status_code == 200
        assert state["status"] == "completed"
        assert state["stage"] == "recovered"
    finally:
        app.dependency_overrides.pop(get_current_user_optional, None)
        async with db_session_factory() as session:
            row = (
                await session.execute(select(JobFinalization).where(JobFinalization.job_id == job_id))
            ).scalar_one_or_none()
            if row is not None:
                await session.delete(row)
                await session.flush()
                await session.execute(User.__table__.delete().where(User.id == user_id))
                await session.commit()
