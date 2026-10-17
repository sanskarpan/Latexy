from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.drain_modal_app import (
    DrainEvidenceError,
    main,
    stop_and_record,
    validate_evidence,
)

DEPLOY_SHA = "a" * 40
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def app_snapshot(state: str) -> str:
    return json.dumps({"apps": [{
        "app_id": "ap-production-123",
        "app_name": "latexy-backend",
        "state": state,
    }]})


def test_stop_and_record_stops_exact_app_then_records_fresh_stopped_readback(tmp_path: Path) -> None:
    snapshots = iter([app_snapshot("DEPLOYED"), app_snapshot("STOPPING"), app_snapshot("STOPPED")])
    commands: list[list[str]] = []
    clock = [0.0]

    def runner(command, **_kwargs):
        commands.append(command)
        if command[1:3] == ["app", "list"]:
            return subprocess.CompletedProcess(command, 0, next(snapshots), "")
        if command[1:3] == ["app", "stop"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"unexpected Modal command: {command}")

    evidence_path = tmp_path / "drain.json"
    evidence = stop_and_record(
        app_name="latexy-backend",
        environment="main",
        deploy_sha=DEPLOY_SHA,
        evidence_path=evidence_path,
        timeout_seconds=10,
        poll_interval_seconds=5,
        runner=runner,
        monotonic=lambda: clock[0],
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        now=lambda: NOW,
    )

    assert commands == [
        ["modal", "app", "list", "--env", "main", "--json", "--limit", "0"],
        ["modal", "app", "stop", "--env", "main", "--yes", "ap-production-123"],
        ["modal", "app", "list", "--env", "main", "--json", "--limit", "0"],
        ["modal", "app", "list", "--env", "main", "--json", "--limit", "0"],
    ]
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == evidence
    validate_evidence(
        evidence,
        app_name="latexy-backend",
        environment="main",
        deploy_sha=DEPLOY_SHA,
        now=NOW,
    )


def test_already_stopped_app_still_requires_and_records_a_fresh_readback(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, app_snapshot("STOPPED"), "")

    evidence = stop_and_record(
        app_name="latexy-backend",
        environment="main",
        deploy_sha=DEPLOY_SHA,
        evidence_path=tmp_path / "drain.json",
        runner=runner,
        now=lambda: NOW,
    )
    assert len(calls) == 2
    assert all(command[1:3] == ["app", "list"] for command in calls)
    assert evidence["state"] == "STOPPED"
    assert evidence["observed_at"] == "2026-10-17T12:00:00Z"


def test_missing_or_ambiguous_app_fails_without_stopping_anything(tmp_path: Path) -> None:
    for snapshot in (
        json.dumps({"apps": []}),
        json.dumps({"apps": [
            {"app_id": "ap-1", "app_name": "latexy-backend", "state": "DEPLOYED"},
            {"app_id": "ap-2", "app_name": "latexy-backend", "state": "DEPLOYED"},
        ]}),
    ):
        commands: list[list[str]] = []

        def runner(command, **_kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, snapshot, "")

        with pytest.raises(DrainEvidenceError):
            stop_and_record(
                app_name="latexy-backend",
                environment="main",
                deploy_sha=DEPLOY_SHA,
                evidence_path=tmp_path / "drain.json",
                runner=runner,
            )
        assert len(commands) == 1
        assert commands[0][1:3] == ["app", "list"]
        assert not (tmp_path / "drain.json").exists()


def test_invalid_state_command_failure_and_timeout_fail_without_evidence(tmp_path: Path) -> None:
    bad_outputs = ("not-json", json.dumps({"unexpected": []}), json.dumps({"apps": [{
        "app_id": "ap-production-123",
        "app_name": "latexy-backend",
    }]}))
    for output in bad_outputs:
        with pytest.raises(DrainEvidenceError):
            stop_and_record(
                app_name="latexy-backend",
                environment="main",
                deploy_sha=DEPLOY_SHA,
                evidence_path=tmp_path / "drain.json",
                runner=lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, output, ""),
            )

    def failed_stop(command, **_kwargs):
        if command[1:3] == ["app", "list"]:
            return subprocess.CompletedProcess(command, 0, app_snapshot("DEPLOYED"), "")
        return subprocess.CompletedProcess(command, 1, "", "stop failed")

    with pytest.raises(DrainEvidenceError, match="exit code 1"):
        stop_and_record(
            app_name="latexy-backend",
            environment="main",
            deploy_sha=DEPLOY_SHA,
            evidence_path=tmp_path / "drain.json",
            runner=failed_stop,
        )

    clock = [0.0]

    def never_stops(command, **_kwargs):
        state = "DEPLOYED" if command[1:3] == ["app", "list"] else ""
        return subprocess.CompletedProcess(command, 0, app_snapshot(state) if state else "", "")

    with pytest.raises(DrainEvidenceError, match="did not reach STOPPED"):
        stop_and_record(
            app_name="latexy-backend",
            environment="main",
            deploy_sha=DEPLOY_SHA,
            evidence_path=tmp_path / "drain.json",
            timeout_seconds=10,
            poll_interval_seconds=5,
            runner=never_stops,
            monotonic=lambda: clock[0],
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        )
    assert not (tmp_path / "drain.json").exists()


def valid_evidence() -> dict[str, object]:
    return {
        "evidence_version": 1,
        "source": "modal app list --json",
        "app_name": "latexy-backend",
        "app_id": "ap-production-123",
        "environment": "main",
        "state": "STOPPED",
        "deploy_sha": DEPLOY_SHA,
        "observed_at": "2026-10-17T11:59:00Z",
    }


def test_missing_stale_future_and_mismatched_evidence_fail_closed(tmp_path: Path) -> None:
    assert main([
            "require", "--app-name", "latexy-backend", "--environment", "main",
            "--deploy-sha", DEPLOY_SHA, "--evidence", str(tmp_path / "missing.json"),
        ]) == 1

    with pytest.raises(DrainEvidenceError, match="stale"):
        validate_evidence(
            valid_evidence(), app_name="latexy-backend", environment="main",
            deploy_sha=DEPLOY_SHA, now=NOW, max_age_seconds=30,
        )
    with pytest.raises(DrainEvidenceError, match="future"):
        future = valid_evidence()
        future["observed_at"] = (NOW + timedelta(seconds=1)).isoformat()
        validate_evidence(
            future, app_name="latexy-backend", environment="main", deploy_sha=DEPLOY_SHA, now=NOW,
        )

    for invalid in (
        {**valid_evidence(), "deploy_sha": "b" * 40},
        {**valid_evidence(), "environment": "dev"},
        {**valid_evidence(), "state": "DEPLOYED"},
        {**valid_evidence(), "source": "source-only-attestation"},
        {**valid_evidence(), "app_id": ""},
    ):
        with pytest.raises(DrainEvidenceError):
            validate_evidence(
                invalid, app_name="latexy-backend", environment="main", deploy_sha=DEPLOY_SHA, now=NOW,
            )
