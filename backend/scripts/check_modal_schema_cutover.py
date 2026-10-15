"""Fail closed before a Modal schema migration; make no production calls.

The source and CI checks are minimum rejection checks, not proof that a
recovery image is deployable or that every artifact reader is compatible.
Those facts require a separate, commit-scoped operator attestation.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence

SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
LEGACY_BILLING_ID = re.compile(r"razorpay_(?:payment|subscription)_id", re.IGNORECASE)
ACCEPTED_FILTER = "Compilation.artifact_accepted.is_(True)"


class CutoverBlocked(ValueError):
    """A required cutover fact is absent or contradicted."""


def _result(runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]],
            args: Sequence[str], failure: str) -> str:
    try:
        result = runner(args)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CutoverBlocked(failure) from exc
    if result.returncode != 0:
        raise CutoverBlocked(failure)
    return result.stdout


def validate(env: Mapping[str, str], runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]]) -> None:
    deploy = env.get("DEPLOY_SHA", "")
    rollback = env.get("MODAL_FORWARD_ROLLBACK_SHA", "")
    repository = env.get("GITHUB_REPOSITORY", "")
    if not SHA.fullmatch(deploy):
        raise CutoverBlocked("Deployment SHA is invalid")
    if env.get("MODAL_SCHEMA_CUTOVER_APPROVED_SHA") != deploy:
        raise CutoverBlocked("Cutover approval is absent or stale")
    if not SHA.fullmatch(rollback) or rollback == deploy:
        raise CutoverBlocked("Distinct recovery SHA is required")
    if env.get("MODAL_RECOVERY_VERIFIED_FOR_SHA") != deploy:
        raise CutoverBlocked("Recovery image and artifact-reader attestation is absent or stale")
    if not REPOSITORY.fullmatch(repository):
        raise CutoverBlocked("GitHub repository identity is invalid")

    _result(runner, ["git", "merge-base", "--is-ancestor", rollback, deploy],
            "Recovery SHA is not an ancestor of the deployment SHA")
    routes = _result(runner, ["git", "show", f"{rollback}:backend/app/api/resume_routes.py"],
                     "Recovery artifact reader source is unavailable")
    billing = _result(runner, ["git", "show", f"{rollback}:backend/app/services/payment_service.py"],
                      "Recovery billing source is unavailable")
    if routes.count(ACCEPTED_FILTER) < 2 or LEGACY_BILLING_ID.search(billing):
        raise CutoverBlocked("Recovery source minimum compatibility checks failed")

    api_path = (f"repos/{repository}/actions/workflows/ci.yml/runs?head_sha={rollback}"
                "&branch=main&status=completed&per_page=100")
    ci_text = _result(runner, ["gh", "api", api_path], "Canonical recovery CI lookup failed")
    try:
        runs = json.loads(ci_text)["workflow_runs"]
        valid = isinstance(runs, list) and any(
            isinstance(run, dict)
            and run.get("head_sha") == rollback
            and run.get("head_branch") == "main"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            for run in runs
        )
    except (ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise CutoverBlocked("Recovery SHA has no successful canonical main CI run")


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)


def main() -> int:
    try:
        validate(os.environ, _run)
    except CutoverBlocked as exc:
        print(f"Modal schema cutover blocked: {exc}", file=sys.stderr)
        return 1
    print("Modal schema cutover source and CI checks passed; operator attestations supplied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
