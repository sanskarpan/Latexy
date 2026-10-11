"""Optional industry profiles are captured at admission, never client-owned."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.entitlement_service import entitlement_service
from app.workers import ats_worker, orchestrator


@pytest.mark.parametrize("enabled", [False, True])
def test_combined_profile_decision_overwrites_input_and_survives_later_switch(enabled, monkeypatch):
    snapshot = MagicMock(return_value=enabled)
    dispatch = MagicMock()
    monkeypatch.setattr(entitlement_service, "sync_has_feature", snapshot)
    monkeypatch.setattr(orchestrator.optimize_and_compile_task, "apply_async", dispatch)
    original = {"_ats_generic_only": enabled, "resume_id": "owned-resume"}
    orchestrator.submit_optimize_and_compile(
        "source", "Software engineering role", "admitted-job", user_plan="pro_annual", metadata=original,
    )
    captured = dispatch.call_args.kwargs["kwargs"]["metadata"]
    assert captured["_ats_generic_only"] is not enabled
    assert original["_ats_generic_only"] is enabled  # No mutation of caller-owned metadata.
    snapshot.assert_called_once_with("d19", "pro_annual", user_id=None)

    # The worker consumes the captured choice even if an administrator changes
    # the flag while this task is sitting in the queue. No live provider used.
    snapshot.return_value = not enabled
    scorer = AsyncMock(return_value=SimpleNamespace(
        overall_score=75, category_scores={}, recommendations=[], strengths=[], warnings=[],
    ))
    monkeypatch.setattr(orchestrator.ats_scoring_service, "score_resume", scorer)
    score, _ = orchestrator._run_ats_stage(
        "admitted-job", "source", "Software engineering role", force_generic=captured["_ats_generic_only"],
    )
    assert score == 75
    assert scorer.await_args.kwargs["industry"] == (None if enabled else "generic")
    assert snapshot.call_count == 1  # Execution does not re-decide admission.


@pytest.mark.parametrize("enabled", [False, True])
def test_ats_submission_cannot_force_disabled_profile_or_locale(enabled, monkeypatch):
    monkeypatch.setattr(entitlement_service, "sync_has_feature", MagicMock(return_value=enabled))
    dispatch = MagicMock()
    monkeypatch.setattr(ats_worker.score_resume_ats_task, "apply_async", dispatch)
    ats_worker.submit_ats_scoring(
        "source", "ats-job", job_description="Software engineering role", industry="technology",
        industry_profile_key="tech_saas", locale_key="india", user_plan="pro",
    )
    captured = dispatch.call_args.kwargs["kwargs"]
    assert captured["industry"] == ("technology" if enabled else "generic")
    assert captured["industry_profile_key"] == ("tech_saas" if enabled else "generic")
    assert captured["locale_key"] == ("india" if enabled else "global")
