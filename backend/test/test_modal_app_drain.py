"""Read-only check for an external drain procedure and current Modal App state."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from typing import Any

import pytest

from scripts.verify_modal_drain import (
    DrainPrerequisiteError,
    ModalAppSnapshot,
    _lookup_modal_app_id,
    _parse_modal_app_list,
    main,
    verify_prerequisite,
)

DEPLOY_SHA = "a" * 40
APP_ID = "ap-" + "a" * 22
RECREATED_APP_ID = "ap-" + "b" * 22
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def app_list(state: str, app_id: str = APP_ID) -> str:
    # Modal 1.5.4 rows use these stable keys. Description is deliberately not
    # used as a name because it is a human-readable label, not deployment ID.
    return json.dumps([{
        "app_id": app_id,
        "description": "workspace-generated description",
        "state": state,
        "tasks": "0",
        "created_at": "2026-10-17T11:00:00+00:00",
        "stopped_at": "2026-10-17T11:59:30+00:00",
    }])


def valid_record() -> dict[str, str]:
    return {
        "external_record_sha": DEPLOY_SHA,
        "external_record_app_id": APP_ID,
        "external_record_completed_at": "2026-10-17T11:59:00Z",
        "external_record_reference": "change-record:drain-2026-10-17-01",
    }


def run_verifier(
    *,
    state: str = "stopped",
    output: str | None = None,
    lookup_ids: list[str] | None = None,
    **overrides: Any,
) -> tuple[ModalAppSnapshot, list[list[str]], list[tuple[str, str]]]:
    commands: list[list[str]] = []
    lookups: list[tuple[str, str]] = []
    records = valid_record() | overrides
    app_lookup_ids = iter(lookup_ids or [APP_ID, APP_ID])

    def runner(command, **kwargs):
        commands.append(command)
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 30
        return subprocess.CompletedProcess(command, 0, output or app_list(state), "")

    def lookup(name: str, environment: str) -> str:
        lookups.append((name, environment))
        return next(app_lookup_ids)

    result = verify_prerequisite(
        app_name="latexy-backend",
        environment="main",
        expected_deploy_sha=DEPLOY_SHA,
        now=NOW,
        runner=runner,
        app_lookup=lookup,
        **records,
    )
    return result, commands, lookups


def test_matches_external_record_to_live_named_app_and_stopped_state_read_only() -> None:
    result, commands, lookups = run_verifier(output=app_list("stopped"))

    assert result == ModalAppSnapshot(app_id=APP_ID, state="stopped")
    assert lookups == [("latexy-backend", "main"), ("latexy-backend", "main")]
    assert commands == [["modal", "app", "list", "--env", "main", "--json"]]
    assert all("stop" not in command for command in commands)


def test_current_state_query_is_bracketed_by_name_identity_lookups() -> None:
    events: list[str] = []

    def runner(command, **_kwargs):
        events.append("current-app-state")
        return subprocess.CompletedProcess(command, 0, app_list("stopped"), "")

    def lookup(_name: str, _environment: str) -> str:
        events.append("current-app-name-resolution")
        return APP_ID

    verify_prerequisite(
        app_name="latexy-backend",
        environment="main",
        expected_deploy_sha=DEPLOY_SHA,
        now=NOW,
        runner=runner,
        app_lookup=lookup,
        **valid_record(),
    )
    assert events == [
        "current-app-name-resolution",
        "current-app-state",
        "current-app-name-resolution",
    ]


def test_name_lookup_prefers_current_deployment_id(monkeypatch) -> None:
    import scripts.verify_modal_drain as drain

    calls: list[tuple[str, str]] = []

    def fake_fetch(app_name: str, environment: str) -> tuple[str, str]:
        calls.append((app_name, environment))
        return APP_ID, RECREATED_APP_ID

    monkeypatch.setattr(drain, "_fetch_deployment_name_ids", fake_fetch)
    assert _lookup_modal_app_id("latexy-backend", "main") == APP_ID
    assert calls == [("latexy-backend", "main")]


def test_stopped_app_resolves_through_previous_deployment_id(monkeypatch) -> None:
    """A stopped App has no current deployment: the RPC reports it as previous.

    This is the exact production failure: `modal.App.lookup` raises
    NotFoundError for a stopped App, which made the drain gate unpassable in
    precisely the state it requires. The deployment-name RPC still resolves
    the stopped App's ID as `previous_app_id`.
    """
    import scripts.verify_modal_drain as drain

    def fake_fetch(app_name: str, environment: str) -> tuple[str, str]:
        assert (app_name, environment) == ("latexy-backend", "main")
        return "", APP_ID

    monkeypatch.setattr(drain, "_fetch_deployment_name_ids", fake_fetch)
    assert _lookup_modal_app_id("latexy-backend", "main") == APP_ID


def test_name_lookup_rejects_missing_or_malformed_ids(monkeypatch) -> None:
    import scripts.verify_modal_drain as drain

    for ids in [("", ""), ("not-an-id", ""), ("", "also-not-an-id")]:
        monkeypatch.setattr(drain, "_fetch_deployment_name_ids", lambda *_a, **_k: ids)
        with pytest.raises(DrainPrerequisiteError, match="no valid app_id"):
            _lookup_modal_app_id("latexy-backend", "main")


def test_name_lookup_failure_fails_closed(monkeypatch) -> None:
    import scripts.verify_modal_drain as drain

    def fake_fetch(app_name: str, environment: str) -> tuple[str, str]:
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(drain, "_fetch_deployment_name_ids", fake_fetch)
    with pytest.raises(DrainPrerequisiteError, match="Modal App name lookup failed"):
        _lookup_modal_app_id("latexy-backend", "main")


def test_modal_154_list_schema_ignores_description_as_identity() -> None:
    rows = json.loads(app_list("stopped"))
    assert _parse_modal_app_list(rows) == [ModalAppSnapshot(APP_ID, "stopped")]

    name_only = [{
        "description": "latexy-backend",
        "state": "stopped",
        "tasks": "0",
        "created_at": None,
        "stopped_at": None,
    }]
    with pytest.raises(DrainPrerequisiteError, match="app_id"):
        _parse_modal_app_list(name_only)


def test_live_app_fails_closed_even_when_external_record_matches() -> None:
    commands: list[list[str]] = []

    def runner(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, app_list("deployed"), "")

    with pytest.raises(DrainPrerequisiteError, match="not 'stopped'"):
        verify_prerequisite(
            app_name="latexy-backend",
            environment="main",
            expected_deploy_sha=DEPLOY_SHA,
            now=NOW,
            runner=runner,
            app_lookup=lambda _name, _env: APP_ID,
            **valid_record(),
        )
    assert commands == [["modal", "app", "list", "--env", "main", "--json"]]


def test_recreated_app_id_fails_even_if_old_id_remains_listed_as_stopped() -> None:
    with pytest.raises(DrainPrerequisiteError, match="identity changed"):
        run_verifier(
            output=app_list("stopped", APP_ID),
            lookup_ids=[APP_ID, RECREATED_APP_ID],
        )


def test_current_name_mapping_to_a_recreated_app_id_is_rejected() -> None:
    with pytest.raises(DrainPrerequisiteError, match="differs from the external drain record"):
        run_verifier(lookup_ids=[RECREATED_APP_ID, RECREATED_APP_ID])


def test_stale_external_record_fails_before_any_modal_query() -> None:
    commands: list[list[str]] = []
    lookups: list[tuple[str, str]] = []
    records = valid_record()
    records["external_record_completed_at"] = "2026-10-17T11:50:00Z"

    with pytest.raises(DrainPrerequisiteError, match="stale"):
        verify_prerequisite(
            app_name="latexy-backend",
            environment="main",
            expected_deploy_sha=DEPLOY_SHA,
            now=NOW,
            runner=lambda command, **_kwargs: commands.append(command),
            app_lookup=lambda name, env: lookups.append((name, env)),
            **records,
        )
    assert commands == []
    assert lookups == []


def test_candidate_sha_mismatch_fails_before_any_modal_query() -> None:
    commands: list[list[str]] = []
    lookups: list[tuple[str, str]] = []
    with pytest.raises(DrainPrerequisiteError, match="does not match"):
        verify_prerequisite(
            app_name="latexy-backend",
            environment="main",
            expected_deploy_sha=DEPLOY_SHA,
            now=NOW,
            runner=lambda command, **_kwargs: commands.append(command),
            app_lookup=lambda name, env: lookups.append((name, env)),
            **(valid_record() | {"external_record_sha": "b" * 40}),
        )
    assert commands == []
    assert lookups == []


@pytest.mark.parametrize("missing_field", [
    "external_record_sha",
    "external_record_app_id",
    "external_record_completed_at",
    "external_record_reference",
])
def test_missing_external_record_field_fails_closed(missing_field: str) -> None:
    record = valid_record()
    record[missing_field] = ""
    commands: list[list[str]] = []
    lookups: list[tuple[str, str]] = []
    with pytest.raises(DrainPrerequisiteError):
        verify_prerequisite(
            app_name="latexy-backend",
            environment="main",
            expected_deploy_sha=DEPLOY_SHA,
            now=NOW,
            runner=lambda command, **_kwargs: commands.append(command),
            app_lookup=lambda name, env: lookups.append((name, env)),
            **record,
        )
    assert commands == []
    assert lookups == []


def test_automatic_workflow_run_refuses_when_external_record_is_missing(capsys) -> None:
    lookups: list[tuple[str, str]] = []
    commands: list[list[str]] = []
    env = {
        "MODAL_DRAIN_PROCEDURE_APPROVED_FOR_SHA": "",
        "MODAL_DRAIN_PROCEDURE_APP_ID": "",
        "MODAL_DRAIN_PROCEDURE_COMPLETED_AT": "",
        "MODAL_DRAIN_PROCEDURE_EVIDENCE_REFERENCE": "",
    }
    result = main(
        ["--app-name", "latexy-backend", "--environment", "main",
         "--expected-deploy-sha", DEPLOY_SHA],
        environ=env,
        runner=lambda command, **_kwargs: commands.append(command),
        app_lookup=lambda name, environment: lookups.append((name, environment)),
        now=NOW,
    )
    captured = capsys.readouterr()
    assert result == 1
    assert "external drain record" in captured.err
    assert captured.out == ""
    assert commands == []
    assert lookups == []


def test_success_output_does_not_claim_requested_sha_was_observed_from_modal(capsys) -> None:
    env = {
        "MODAL_DRAIN_PROCEDURE_APPROVED_FOR_SHA": DEPLOY_SHA,
        "MODAL_DRAIN_PROCEDURE_APP_ID": APP_ID,
        "MODAL_DRAIN_PROCEDURE_COMPLETED_AT": "2026-10-17T11:59:00Z",
        "MODAL_DRAIN_PROCEDURE_EVIDENCE_REFERENCE": "change-record:drain-2026-10-17-01",
    }
    assert main(
        ["--app-name", "latexy-backend", "--expected-deploy-sha", DEPLOY_SHA],
        environ=env,
        runner=lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, app_list("stopped"), ""),
        app_lookup=lambda _name, _environment: APP_ID,
        now=NOW,
    ) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["external_procedure_reference_supplied"] is True
    assert report["external_record_sha_matches_requested_sha"] is True
    assert report["external_record_contents_authenticated_by_this_check"] is False
    assert report["current_modal_app_id"] == APP_ID
    assert report["current_modal_app_state"] == "stopped"
    assert report["settled_queued_or_inflight_work_verified_by_this_check"] is False
    assert "observed_modal_deploy_sha" not in report
    assert DEPLOY_SHA not in json.dumps(report)
