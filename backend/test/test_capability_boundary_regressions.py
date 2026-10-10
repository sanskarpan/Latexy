"""Direct-call, downgrade and live-connection regressions without providers."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.api import resume_routes
from app.api.routes import router
from app.database.connection import get_db
from app.middleware.auth_middleware import get_current_user_optional, get_current_user_required
from app.middleware.capability_router import CapabilityRouter, payload_capabilities
from app.services.entitlement_service import entitlement_service

OWNER = "11111111-1111-4111-8111-111111111111"
ACTOR = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def guarded_app(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_optional] = lambda: OWNER
    app.dependency_overrides[get_current_user_required] = lambda: OWNER
    db = AsyncMock()
    db.execute.side_effect = AssertionError("Disabled admission reached the database")
    app.dependency_overrides[get_db] = lambda: db
    checker = AsyncMock(return_value=True)
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    return app, db, checker


@pytest.mark.parametrize("value", [True, "true", "TRUE", "yes", "on", "1", 1, 1.0])
@pytest.mark.parametrize("path,method,field,key", [
    (f"/resumes/{OWNER}", "PUT", "portfolio_visible", "g12"),
    (f"/resumes/{OWNER}/share", "POST", "review_comments", "f03"),
    (f"/resumes/{OWNER}/builder", "PATCH", "force_reattach", "b09"),
])
async def test_boolean_coercion_cannot_bypass_granular_gate(value, path, method, field, key, guarded_app):
    app, db, checker = guarded_app
    checker.side_effect = lambda candidate, **kwargs: candidate != key
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.request(method, path, json={field: value}, headers={"content-type": "Application/JSON"})
    assert response.status_code == 403, response.text
    assert key in response.text
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("value", [False, "false", "FALSE", "no", "off", "0", 0, 0.0])
def test_boolean_coercion_preserves_revocations(value):
    assert payload_capabilities("portfolio_routes", "setup_portfolio", {"portfolio_enabled": value}, {}, {}) == ()
    assert payload_capabilities("tracker_workflow_routes", "update_alert", {"active": value}, {}, {}) == ()
    assert payload_capabilities("resume_routes", "create_share_link", {"review_comments": value}, {}, {}) == ()
    assert payload_capabilities("resume_routes", "create_share_link", {"anonymous": value}, {}, {}) == ("f01",)


def test_unclassified_http_handler_fails_registration():
    async def future_expensive_operation():
        return {"unsafe": True}
    future_expensive_operation.__module__ = "app.api.ai_routes"
    with pytest.raises(RuntimeError, match="Unclassified capability policy"):
        CapabilityRouter().add_api_route("/new", future_expensive_operation, methods=["POST"])


def test_malformed_role_stays_validation_input():
    assert payload_capabilities("resume_routes", "update_collaborator_role", {"role": []}, {}, {}) == ("f04",)


@pytest.mark.parametrize("path,body", [
    ("/ats/deep-analyze", {"latex_content": "source", "industry_override": "tech_saas"}),
    ("/ats/recommendations", {"industry": "technology"}),
])
async def test_alternate_ats_operations_cannot_bypass_industry_profile_gate(path, body, guarded_app):
    app, db, checker = guarded_app
    checker.side_effect = lambda candidate, **kwargs: candidate != "d19"
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(path, json=body)
    assert response.status_code == 403, response.text
    assert "d19" in response.text
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("disabled_user", [OWNER, ACTOR])
async def test_collaborator_existing_source_requires_actor_and_owner_grants(monkeypatch, disabled_user):
    resume = SimpleNamespace(user_id=OWNER)
    result = MagicMock()
    result.one_or_none.return_value = (resume, "viewer")
    db = AsyncMock()
    db.execute.return_value = result
    checker = AsyncMock(side_effect=lambda key, user: user != disabled_user)
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    with pytest.raises(HTTPException) as denied:
        await resume_routes._get_resume_document_access(db, OWNER, ACTOR)
    assert denied.value.status_code == 403
    checker.reset_mock()
    assert await resume_routes._get_resume_document_access(db, OWNER, OWNER) == (resume, "owner")
    checker.assert_not_awaited()


async def test_review_only_revoke_keeps_blind_link_and_never_dispatches(monkeypatch):
    now = datetime.now(timezone.utc)
    resume = SimpleNamespace(
        user_id=OWNER, share_token="existing", share_token_created_at=now,
        resume_settings={"share_anonymous": True, "share_review_comments": True},
    )
    db = AsyncMock()
    db.scalar.return_value = resume
    monkeypatch.setattr(resume_routes, "_verify_resume_ownership", AsyncMock(return_value=resume))
    from app.workers import latex_worker
    submit = MagicMock(side_effect=AssertionError("Revocation must not submit work"))
    monkeypatch.setattr(latex_worker, "submit_latex_compilation", submit)
    result = await resume_routes.create_share_link(
        OWNER, resume_routes.ShareLinkRequest(review_comments="false"), db, OWNER,
    )
    assert result.anonymous is True
    assert result.review_comments is False
    assert result.share_token == "existing"
    assert resume.resume_settings == {"share_anonymous": True, "share_review_comments": False}
    submit.assert_not_called()
    db.commit.assert_awaited_once()


async def test_review_only_revoke_cannot_create_new_share_link(monkeypatch):
    resume = SimpleNamespace(user_id=OWNER, share_token=None, resume_settings={})
    db = AsyncMock()
    db.scalar.return_value = resume
    monkeypatch.setattr(resume_routes, "_verify_resume_ownership", AsyncMock(return_value=resume))
    with pytest.raises(HTTPException) as denied:
        await resume_routes.create_share_link(OWNER, resume_routes.ShareLinkRequest(review_comments=False), db, OWNER)
    assert denied.value.status_code == 404
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("delivery", ["broadcast", "send_to", "incoming"])
async def test_disabled_idle_socket_cannot_receive_or_persist_and_can_rejoin(monkeypatch, delivery):
    from app.services import collab_manager as collab
    room = collab.CollabRoom(OWNER)
    ws = AsyncMock()
    live = AsyncMock(return_value=False)
    await room.add("peer", ws, {"user_id": ACTOR, "role": "editor"}, access_check=live)
    persist = AsyncMock()
    monkeypatch.setattr(collab, "_persist_update", persist)
    if delivery == "broadcast":
        await room.broadcast(b"private content")
    elif delivery == "send_to":
        await room.send_to("peer", b"private content")
    else:
        await collab.handle_collab_message(OWNER, "peer", b"\x00\x02\x01x", room)
    ws.send_bytes.assert_not_awaited()
    ws.close.assert_awaited_once()
    persist.assert_not_awaited()
    assert room.size == 0
    live.return_value = True
    await room.add("new-peer", ws, {"user_id": ACTOR, "role": "editor"}, access_check=live)
    await room.send_to("new-peer", b"allowed after reenable")
    ws.send_bytes.assert_awaited_once_with(b"allowed after reenable")


@pytest.mark.parametrize("enabled", [False, True])
def test_compiler_customization_snapshots_current_owner_grant(monkeypatch, enabled):
    from app.workers import latex_worker
    checker = MagicMock(return_value=enabled)
    dispatch = MagicMock()
    monkeypatch.setattr(entitlement_service, "sync_has_feature", checker)
    monkeypatch.setattr(latex_worker.compile_latex_task, "apply_async", dispatch)
    config = {"draft_mode": True}
    latex_worker.submit_latex_compilation("source", "queued-job", user_id=OWNER, user_plan="pro", compile_settings=config)
    captured = dispatch.call_args.kwargs["kwargs"]
    assert captured["compile_settings"] == (config if enabled else None)
    assert config == {"draft_mode": True}
    checker.assert_called_once_with("c07", "pro", user_id=OWNER)


async def test_recurring_alert_is_paused_not_consumed_and_reenables(monkeypatch):
    from app.workers import tracker_notification_worker as worker
    now = datetime.now(timezone.utc)
    alert = SimpleNamespace(
        id="saved-alert", query="Python", source_url="https://example.com/jobs", frequency="daily",
        last_notified_at=None, created_at=now-timedelta(days=2),
    )
    user = SimpleNamespace(id=OWNER, name="Owner", email="test@example.com", email_notifications={})
    db = AsyncMock()
    empty, due = MagicMock(), MagicMock()
    empty.all.return_value = []
    due.all.return_value = [(alert, user)]
    checker = AsyncMock(return_value=False)
    claim, current, persist, send = AsyncMock(return_value="claim"), AsyncMock(return_value=True), AsyncMock(return_value=True), AsyncMock(return_value=True)
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    monkeypatch.setattr(worker, "_claim_row", claim)
    monkeypatch.setattr(worker, "_claim_is_current", current)
    monkeypatch.setattr(worker, "_persist_delivery_state", persist)
    db.execute.side_effect = [empty, due]
    assert await worker.deliver_tracker_notifications(db, now=now, send_email=send) == {"reminders": 0, "alerts": 0, "failed": 0}
    claim.assert_not_awaited()
    send.assert_not_awaited()
    persist.assert_not_awaited()
    checker.assert_awaited_once_with("e06", user=OWNER)
    checker.return_value = True
    db.execute.side_effect = [empty, due]
    assert (await worker.deliver_tracker_notifications(db, now=now, send_email=send))["alerts"] == 1
    send.assert_awaited_once()


async def test_github_import_cannot_use_disabled_stored_byok_before_admission(monkeypatch):
    from app.api import github_routes
    db = AsyncMock()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = SimpleNamespace(github_access_token="encrypted", subscription_plan="pro")
    db.execute.return_value = user_result
    db.scalar.return_value = "stored-key-id"
    checker, quota = AsyncMock(return_value=False), AsyncMock()
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    monkeypatch.setattr(entitlement_service, "enforce_quota", quota)
    dispatch = MagicMock()
    monkeypatch.setattr(github_routes, "submit_github_import", dispatch)
    with pytest.raises(HTTPException) as denied:
        await github_routes.import_github_projects(db, OWNER)
    assert denied.value.status_code == 403
    assert "d25" in str(denied.value.detail)
    quota.assert_not_awaited()
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    dispatch.assert_not_called()


async def test_github_worker_does_not_acquire_byok_added_after_disabled_admission(monkeypatch):
    from contextlib import asynccontextmanager

    from app.services.encryption_service import encryption_service
    from app.workers.github_import_worker import _resolve_import_credentials
    db = AsyncMock()
    db.scalar.return_value = "encrypted-github"
    db.execute.side_effect = AssertionError("Must not fetch a BYOK key for a disabled admission")

    @asynccontextmanager
    async def session_factory():
        yield db

    decrypt = MagicMock(return_value="github-token")
    monkeypatch.setattr(encryption_service, "decrypt", decrypt)
    assert await _resolve_import_credentials(OWNER, session_factory=session_factory, allow_byok=False) == ("github-token", None)
    db.execute.assert_not_awaited()
    decrypt.assert_called_once_with("encrypted-github")


@pytest.mark.parametrize("enabled", [True, False])
def test_deep_analysis_snapshots_industry_permission_before_queue(monkeypatch, enabled):
    from app.workers import ats_worker
    checker, dispatch = MagicMock(return_value=enabled), MagicMock()
    monkeypatch.setattr(entitlement_service, "sync_has_feature", checker)
    monkeypatch.setattr(ats_worker.deep_analyze_ats_task, "apply_async", dispatch)
    ats_worker.submit_deep_analyze_ats("source", "deep-job", metadata={"user_id": OWNER})
    assert dispatch.call_args.kwargs["kwargs"]["industry_override"] == (None if enabled else "generic")
    checker.assert_called_once_with("d19", "free", user_id=OWNER)


@pytest.mark.parametrize("enabled", [True, False])
def test_automatic_checkpoint_is_optional_new_admission(monkeypatch, enabled):
    from app.workers import auto_save_worker
    checker, dispatch = MagicMock(return_value=enabled), MagicMock()
    monkeypatch.setattr(entitlement_service, "sync_has_feature", checker)
    monkeypatch.setattr(auto_save_worker.record_auto_save_checkpoint, "apply_async", dispatch)
    auto_save_worker.submit_auto_save_checkpoint("owned-resume", OWNER, "source")
    assert dispatch.call_count == int(enabled)
    checker.assert_called_once_with("c22", "free", user_id=OWNER)


async def test_disabled_linked_visibility_does_not_regenerate_background_variants(monkeypatch):
    db = AsyncMock()
    monkeypatch.setattr(entitlement_service, "has_feature", AsyncMock(return_value=False))
    await resume_routes._sync_linked_variants(SimpleNamespace(structured_content={"name": "Owner"}, user_id=OWNER), db)
    db.execute.assert_not_awaited()


async def test_deep_generic_snapshot_suppresses_job_description_autodetection(monkeypatch):
    import json

    from app.workers import ats_worker
    analysis = {
        "overall_score": 75, "overall_feedback": "Clear experience.",
        "sections": [{"name": "Experience", "score": 70, "strengths": [], "improvements": [], "rewrite_suggestion": None}],
        "ats_compatibility": {"score": 80, "issues": [], "keyword_gaps": []}, "job_match": None,
    }
    provider = MagicMock()
    provider.__aenter__ = AsyncMock(return_value=provider)
    provider.__aexit__ = AsyncMock(return_value=False)
    provider.chat.completions.create = AsyncMock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(analysis)))],
        usage=SimpleNamespace(total_tokens=10),
    ))
    monkeypatch.setattr("openai.AsyncOpenAI", MagicMock(return_value=provider))
    monkeypatch.setattr(ats_worker, "_deep_job_cancelled", MagicMock(return_value=False))
    monkeypatch.setattr(ats_worker, "publish_event", MagicMock(return_value="1-0"))
    monkeypatch.setattr(ats_worker, "publish_job_result", MagicMock(return_value=True))
    monkeypatch.setattr(ats_worker.ats_scoring_service, "_extract_text_from_latex", lambda _: "Engineer")
    scorer = AsyncMock(return_value=SimpleNamespace(multi_dim_scores={}, industry_key="generic", industry_label=None))
    monkeypatch.setattr(ats_worker.ats_scoring_service, "score_resume", scorer)
    assert await ats_worker._async_deep_analyze(None, "source", "deep-job", "Python software engineer", "test-key", "generic")
    assert scorer.await_args.kwargs["industry"] == "generic"
    assert scorer.await_args.kwargs["industry_profile_key"] == "generic"
