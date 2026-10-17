"""Read-only gate for an external production drain procedure and Modal state."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_MAX_AGE_SECONDS = 300
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_APP_ID = re.compile(r"^ap-[A-Za-z0-9]{22}$")


class DrainPrerequisiteError(RuntimeError):
    """An external drain record or live Modal App check is absent or inconsistent."""


@dataclass(frozen=True)
class ModalAppSnapshot:
    app_id: str
    state: str


def _parse_modal_app_list(payload: str | bytes | Sequence[Any]) -> list[ModalAppSnapshot]:
    """Parse the Modal 1.5.4 `modal app list --json` table schema.

    The pinned CLI serializes `app_id`, `description`, `state`, `tasks`,
    `created_at`, and `stopped_at`. Description is not a stable App name and is
    deliberately ignored; name resolution uses Modal's public `App.lookup`.
    """
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DrainPrerequisiteError("Modal App list output is not UTF-8") from exc
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DrainPrerequisiteError("Modal App list output is not valid JSON") from exc
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise DrainPrerequisiteError("Modal 1.5.4 App list JSON must be an array")

    snapshots: list[ModalAppSnapshot] = []
    for row in payload:
        if not isinstance(row, Mapping):
            raise DrainPrerequisiteError("Modal App list contains a malformed row")
        app_id = row.get("app_id")
        state = row.get("state")
        if not isinstance(app_id, str) or not _APP_ID.fullmatch(app_id):
            raise DrainPrerequisiteError("Modal App list row has an invalid app_id")
        if not isinstance(state, str) or not state.strip():
            raise DrainPrerequisiteError("Modal App list row has no state")
        snapshots.append(ModalAppSnapshot(app_id=app_id, state=state.strip().casefold()))
    return snapshots


def _lookup_modal_app_id(app_name: str, environment: str) -> str:
    """Resolve a Modal App name through the public, non-creating SDK lookup."""
    try:
        import modal

        app = modal.App.lookup(
            app_name,
            environment_name=environment,
            create_if_missing=False,
        )
    except Exception as exc:  # Modal client/network/auth errors all fail closed.
        raise DrainPrerequisiteError("Modal App name lookup failed") from exc
    app_id = getattr(app, "app_id", None)
    if not isinstance(app_id, str) or not _APP_ID.fullmatch(app_id):
        raise DrainPrerequisiteError("Modal App name lookup returned no valid app_id")
    return app_id


def _run_app_list(
    environment: str,
    runner: Callable[..., Any],
) -> str:
    try:
        result = runner(
            ["modal", "app", "list", "--env", environment, "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DrainPrerequisiteError("Modal App state query failed") from exc
    if result.returncode != 0:
        raise DrainPrerequisiteError("Modal App state query failed")
    return result.stdout


def _parse_utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DrainPrerequisiteError("external drain record timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise DrainPrerequisiteError("external drain record timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def verify_prerequisite(
    *,
    app_name: str,
    environment: str,
    expected_deploy_sha: str,
    external_record_sha: str,
    external_record_app_id: str,
    external_record_completed_at: str,
    external_record_reference: str,
    now: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    runner: Callable[..., Any] = subprocess.run,
    app_lookup: Callable[[str, str], str] = _lookup_modal_app_id,
) -> ModalAppSnapshot:
    """Require a fresh external procedure record and current stopped App state.

    The record SHA is compared with the requested candidate SHA. It is not
    represented as a SHA observed from Modal. The only runtime facts read here
    are the App ID resolved by name and its current lifecycle state.
    """
    if environment != "main":
        raise DrainPrerequisiteError("production drain verification only supports environment 'main'")
    if not _SHA1.fullmatch(expected_deploy_sha):
        raise DrainPrerequisiteError("requested deployment SHA is invalid")
    if external_record_sha != expected_deploy_sha:
        raise DrainPrerequisiteError("external drain record does not match the requested deployment SHA")
    if not _APP_ID.fullmatch(external_record_app_id):
        raise DrainPrerequisiteError("external drain record has no valid pre-drain Modal App ID")
    if not external_record_reference.strip():
        raise DrainPrerequisiteError("external drain procedure reference is missing")
    if max_age_seconds <= 0:
        raise DrainPrerequisiteError("external drain record max age must be positive")

    completed_at = _parse_utc_timestamp(external_record_completed_at)
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        raise DrainPrerequisiteError("verification clock must include a timezone")
    age = checked_at.astimezone(timezone.utc) - completed_at
    if age < timedelta(0):
        raise DrainPrerequisiteError("external drain record timestamp is in the future")
    if age > timedelta(seconds=max_age_seconds):
        raise DrainPrerequisiteError("external drain procedure record is stale")

    # Bracket the state query with the public name resolver so a redeployment
    # during this verification window is detected. This cannot make the later
    # database migration atomic with Modal App lifecycle changes.
    try:
        app_id_before = app_lookup(app_name, environment)
    except DrainPrerequisiteError:
        raise
    except Exception as exc:
        raise DrainPrerequisiteError("Modal App name lookup failed") from exc
    if app_id_before != external_record_app_id:
        raise DrainPrerequisiteError("current Modal App ID differs from the external drain record")

    snapshots = _parse_modal_app_list(_run_app_list(environment, runner))
    matches = [item for item in snapshots if item.app_id == external_record_app_id]
    if len(matches) != 1:
        raise DrainPrerequisiteError("external drain App ID is missing or ambiguous in the live App list")
    current = matches[0]
    if current.state != "stopped":
        raise DrainPrerequisiteError(f"current Modal App state is {current.state!r}, not 'stopped'")

    try:
        app_id_after = app_lookup(app_name, environment)
    except DrainPrerequisiteError:
        raise
    except Exception as exc:
        raise DrainPrerequisiteError("Modal App name lookup failed after state query") from exc
    if app_id_after != app_id_before:
        raise DrainPrerequisiteError("Modal App identity changed during the state verification")
    return current


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--environment", default="main")
    parser.add_argument("--expected-deploy-sha", required=True)
    parser.add_argument("--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., Any] = subprocess.run,
    app_lookup: Callable[[str, str], str] = _lookup_modal_app_id,
    now: datetime | None = None,
) -> int:
    args = _parser().parse_args(argv)
    source = environ if environ is not None else os.environ
    try:
        current = verify_prerequisite(
            app_name=args.app_name,
            environment=args.environment,
            expected_deploy_sha=args.expected_deploy_sha,
            external_record_sha=source.get("MODAL_DRAIN_PROCEDURE_APPROVED_FOR_SHA", ""),
            external_record_app_id=source.get("MODAL_DRAIN_PROCEDURE_APP_ID", ""),
            external_record_completed_at=source.get("MODAL_DRAIN_PROCEDURE_COMPLETED_AT", ""),
            external_record_reference=source.get("MODAL_DRAIN_PROCEDURE_EVIDENCE_REFERENCE", ""),
            max_age_seconds=args.max_age_seconds,
            runner=runner,
            app_lookup=app_lookup,
            now=now,
        )
    except DrainPrerequisiteError as exc:
        print(f"Modal migration prerequisite failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "external_procedure_reference_supplied": True,
        "external_record_sha_matches_requested_sha": True,
        "external_record_contents_authenticated_by_this_check": False,
        "current_modal_app_id": current.app_id,
        "current_modal_app_state": current.state,
        "settled_queued_or_inflight_work_verified_by_this_check": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
