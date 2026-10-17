"""Stop the current production Modal App and gate migrations on fresh readback."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

EVIDENCE_VERSION = 1
EVIDENCE_SOURCE = "modal app list --json"
DEFAULT_EVIDENCE_MAX_AGE_SECONDS = 300
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_STOPPED_STATES = frozenset({"STOPPED", "APP_STATE_STOPPED"})
_STOPPING_STATES = frozenset({"STOPPING", "APP_STATE_STOPPING"})


class DrainEvidenceError(RuntimeError):
    """Raised when the old Modal App is not proven stopped."""


def _records(payload: str | bytes | Mapping[str, Any] | Sequence[Any]) -> list[Mapping[str, Any]]:
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DrainEvidenceError("Modal app list output is not UTF-8") from exc
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DrainEvidenceError("Modal app list output is not valid JSON") from exc

    if isinstance(payload, Mapping):
        for key in ("apps", "items", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                payload = candidate
                break
        else:
            if any(key in payload for key in ("app_name", "appName", "name")):
                payload = [payload]
            else:
                raise DrainEvidenceError("Modal app list JSON has no app collection")

    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise DrainEvidenceError("Modal app list JSON must contain an app array")
    if not all(isinstance(item, Mapping) for item in payload):
        raise DrainEvidenceError("Modal app list JSON contains a malformed app entry")
    return list(payload)


def _field(app: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = app.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _state(app: Mapping[str, Any]) -> str:
    value = app.get("state", app.get("status"))
    if isinstance(value, Mapping):
        value = value.get("name", value.get("value", value.get("state")))
    if not isinstance(value, str) or not value.strip():
        return ""
    return value.strip().upper().replace(" ", "_")


def _find_app(snapshot: str | bytes | Mapping[str, Any] | Sequence[Any], app_name: str) -> tuple[str, str]:
    matches = [
        app for app in _records(snapshot)
        if _field(app, "app_name", "appName", "name") == app_name
    ]
    if not matches:
        raise DrainEvidenceError(f"Modal environment has no listed App named {app_name!r}")
    if len(matches) != 1:
        raise DrainEvidenceError(f"Modal environment has multiple listed Apps named {app_name!r}")
    app = matches[0]
    app_id = _field(app, "app_id", "appId", "id")
    state = _state(app)
    if not app_id:
        raise DrainEvidenceError(f"Modal App {app_name!r} has no app ID in the state response")
    if not state:
        raise DrainEvidenceError(f"Modal App {app_name!r} has no state in the state response")
    return app_id, state


def _run_modal(args: list[str], runner: Callable[..., Any]) -> str:
    result = runner(["modal", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise DrainEvidenceError(f"Modal command failed with exit code {result.returncode}")
    return result.stdout


def _list_snapshot(environment: str, runner: Callable[..., Any]) -> str:
    return _run_modal(
        ["app", "list", "--env", environment, "--json", "--limit", "0"],
        runner,
    )


def _timestamp(value: datetime | None = None) -> str:
    observed_at = value or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        raise DrainEvidenceError("drain evidence clock must include a timezone")
    return observed_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def stop_and_record(
    *,
    app_name: str,
    environment: str,
    deploy_sha: str,
    evidence_path: Path,
    timeout_seconds: int = 300,
    poll_interval_seconds: int = 5,
    runner: Callable[..., Any] = subprocess.run,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    """Stop the named App, then record only after a fresh STOPPED readback."""
    if environment != "main":
        raise DrainEvidenceError("production drain evidence is only supported for Modal environment 'main'")
    if not _SHA1.fullmatch(deploy_sha.lower()):
        raise DrainEvidenceError("deployment SHA must be a full 40-character Git commit SHA")
    if timeout_seconds <= 0 or poll_interval_seconds <= 0:
        raise DrainEvidenceError("drain timeout and poll interval must be positive")

    before = _list_snapshot(environment, runner)
    app_id, before_state = _find_app(before, app_name)
    if before_state not in _STOPPED_STATES | _STOPPING_STATES:
        _run_modal(["app", "stop", "--env", environment, "--yes", app_id], runner)

    deadline = monotonic() + timeout_seconds
    while True:
        snapshot = _list_snapshot(environment, runner)
        current_id, current_state = _find_app(snapshot, app_name)
        if current_id != app_id:
            raise DrainEvidenceError("Modal App identity changed while stop verification was in progress")
        if current_state in _STOPPED_STATES:
            evidence = {
                "evidence_version": EVIDENCE_VERSION,
                "source": EVIDENCE_SOURCE,
                "app_name": app_name,
                "app_id": app_id,
                "environment": environment,
                "state": "STOPPED",
                "deploy_sha": deploy_sha.lower(),
                "observed_at": _timestamp(now()),
            }
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = evidence_path.with_name(f"{evidence_path.name}.tmp")
            temporary_path.write_text(json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8")
            temporary_path.replace(evidence_path)
            return evidence

        remaining = deadline - monotonic()
        if remaining <= 0:
            raise DrainEvidenceError(
                f"Modal App {app_name!r} did not reach STOPPED state (last state: {current_state})"
            )
        sleep(min(poll_interval_seconds, remaining))


def validate_evidence(
    evidence: Mapping[str, Any],
    *,
    app_name: str,
    environment: str,
    deploy_sha: str,
    now: datetime | None = None,
    max_age_seconds: int = DEFAULT_EVIDENCE_MAX_AGE_SECONDS,
) -> None:
    """Require exact, current evidence from the Modal state readback."""
    if environment != "main":
        raise DrainEvidenceError("migration drain evidence must target Modal environment 'main'")
    if not _SHA1.fullmatch(deploy_sha.lower()):
        raise DrainEvidenceError("expected deployment SHA must be a full 40-character Git commit SHA")
    if max_age_seconds <= 0:
        raise DrainEvidenceError("evidence max age must be positive")
    expected = {
        "evidence_version": EVIDENCE_VERSION,
        "source": EVIDENCE_SOURCE,
        "app_name": app_name,
        "environment": environment,
        "state": "STOPPED",
        "deploy_sha": deploy_sha.lower(),
    }
    for key, value in expected.items():
        if evidence.get(key) != value:
            raise DrainEvidenceError(f"drain evidence has an invalid {key}")
    if not _field(evidence, "app_id"):
        raise DrainEvidenceError("drain evidence is missing the Modal App ID")

    raw_observed_at = evidence.get("observed_at")
    if not isinstance(raw_observed_at, str):
        raise DrainEvidenceError("drain evidence is missing its observation timestamp")
    try:
        observed_at = datetime.fromisoformat(raw_observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DrainEvidenceError("drain evidence timestamp is invalid") from exc
    if observed_at.tzinfo is None:
        raise DrainEvidenceError("drain evidence timestamp must include a timezone")

    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        raise DrainEvidenceError("evidence validation clock must include a timezone")
    age = checked_at.astimezone(timezone.utc) - observed_at.astimezone(timezone.utc)
    if age < timedelta(0):
        raise DrainEvidenceError("drain evidence timestamp is in the future")
    if age > timedelta(seconds=max_age_seconds):
        raise DrainEvidenceError("drain evidence is stale")


def _load_evidence(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DrainEvidenceError("same-run Modal drain evidence is missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise DrainEvidenceError("same-run Modal drain evidence is unreadable or invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise DrainEvidenceError("Modal drain evidence must be a JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    stop_parser = subparsers.add_parser("stop-and-record")
    stop_parser.add_argument("--app-name", required=True)
    stop_parser.add_argument("--environment", default="main")
    stop_parser.add_argument("--deploy-sha", required=True)
    stop_parser.add_argument("--evidence", type=Path, required=True)
    stop_parser.add_argument("--timeout-seconds", type=int, default=300)
    stop_parser.add_argument("--poll-interval-seconds", type=int, default=5)

    require_parser = subparsers.add_parser("require")
    require_parser.add_argument("--app-name", required=True)
    require_parser.add_argument("--environment", default="main")
    require_parser.add_argument("--deploy-sha", required=True)
    require_parser.add_argument("--evidence", type=Path, required=True)
    require_parser.add_argument("--max-age-seconds", type=int, default=DEFAULT_EVIDENCE_MAX_AGE_SECONDS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "stop-and-record":
            evidence = stop_and_record(
                app_name=args.app_name,
                environment=args.environment,
                deploy_sha=args.deploy_sha,
                evidence_path=args.evidence,
                timeout_seconds=args.timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
            print(json.dumps({"state": evidence["state"], "app_id": evidence["app_id"], "observed_at": evidence["observed_at"]}))
            return 0

        evidence = _load_evidence(args.evidence)
        validate_evidence(
            evidence,
            app_name=args.app_name,
            environment=args.environment,
            deploy_sha=args.deploy_sha,
            max_age_seconds=args.max_age_seconds,
        )
        print("Verified fresh Modal STOPPED readback for the exact deployment SHA")
        return 0
    except DrainEvidenceError as exc:
        print(f"Modal old-App drain gate failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
