"""Fail closed before a Modal schema migration; make no production calls.

The source and CI checks are minimum rejection checks, not proof that a
recovery image is deployable or that every artifact reader is compatible.
Those facts require a separate, commit-scoped operator attestation.
"""

from __future__ import annotations

import argparse
import ast
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
PUBLIC_REDIS_FALLBACK_GUARD = "if recovery is None and not pdf_available and result and result.get(\"success\")"
PUBLIC_PDF_ACCEPTANCE_GUARD = 'if recovery["state"] != "completed" or not recovery.get("pdf_path"):'
PUBLIC_DURABLE_ROW_QUERY = "select(JobFinalization.id).where(JobFinalization.job_id == job_id).limit(1)"
PUBLIC_DURABLE_HELPER_GUARD = "return not await has_durable_job_record(db, job_id=job_id)"
PUBLIC_STATUS_DURABLE_GUARD = "and await _legacy_pdf_transport_allowed(job_id, db)"
PUBLIC_PDF_DURABLE_GUARD = "if not await _legacy_pdf_transport_allowed(job_id, db):"


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


def _function_source(source: str, name: str) -> str:
    """Inspect only the named top-level reader, not unrelated source text."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    return ""


def _public_pdf_transport_is_fenced(recovery: str, public_api: str) -> bool:
    durable = _function_source(recovery, "has_durable_job_record")
    helper = _function_source(public_api, "_legacy_pdf_transport_allowed")
    status = _function_source(public_api, "get_job_v1")
    download = _function_source(public_api, "download_job_pdf_v1")
    # These are minimum source guards. A separate operator attestation must
    # still verify every reader and the actual deployable recovery image.
    return (
        PUBLIC_DURABLE_ROW_QUERY in durable
        and all(f"JobFinalization.{field}" not in durable for field in ("state", "expires_at", "user_id"))
        and PUBLIC_DURABLE_HELPER_GUARD in helper
        and 'raise HTTPException(status_code=503' in helper
        and PUBLIC_REDIS_FALLBACK_GUARD in status
        and PUBLIC_STATUS_DURABLE_GUARD in status
        and "await r.exists(" in status
        and status.index(PUBLIC_STATUS_DURABLE_GUARD) < status.index("await r.exists(")
        and PUBLIC_PDF_ACCEPTANCE_GUARD in download
        and PUBLIC_PDF_DURABLE_GUARD in download
        and "await get_redis_client(" in download
        and "get_job_files(" in download
        and download.index(PUBLIC_PDF_DURABLE_GUARD) < download.index("await get_redis_client(")
        and download.index(PUBLIC_PDF_DURABLE_GUARD) < download.index("get_job_files(")
    )


def validate_approval_inputs(env: Mapping[str, str]) -> None:
    """Reject invalid supplied approvals without I/O or verifying recovery facts."""
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


def validate(env: Mapping[str, str], runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]]) -> None:
    validate_approval_inputs(env)
    deploy = env["DEPLOY_SHA"]
    rollback = env["MODAL_FORWARD_ROLLBACK_SHA"]
    repository = env["GITHUB_REPOSITORY"]

    _result(runner, ["git", "merge-base", "--is-ancestor", rollback, deploy],
            "Recovery SHA is not an ancestor of the deployment SHA")
    routes = _result(runner, ["git", "show", f"{rollback}:backend/app/api/resume_routes.py"],
                     "Recovery artifact reader source is unavailable")
    billing = _result(runner, ["git", "show", f"{rollback}:backend/app/services/payment_service.py"],
                      "Recovery billing source is unavailable")
    recovery = _result(runner, ["git", "show", f"{rollback}:backend/app/services/job_result_recovery.py"],
                       "Recovery job artifact source is unavailable")
    public_api = _result(runner, ["git", "show", f"{rollback}:backend/app/api/public_api_routes.py"],
                         "Recovery public artifact source is unavailable")
    if (routes.count(ACCEPTED_FILTER) < 2
            or ACCEPTED_FILTER not in recovery
            or '"pdf_path": None' not in recovery
            or not _public_pdf_transport_is_fenced(recovery, public_api)
            or LEGACY_BILLING_ID.search(billing)):
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approvals-only", action="store_true",
                        help="Check supplied approval inputs locally; do not verify recovery or drain")
    args = parser.parse_args(argv)
    try:
        if args.approvals_only:
            validate_approval_inputs(os.environ)
        else:
            validate(os.environ, _run)
    except CutoverBlocked as exc:
        print(f"Modal schema cutover blocked: {exc}", file=sys.stderr)
        return 1
    if args.approvals_only:
        print("Approval inputs accepted; recovery and drain remain unverified")
    else:
        print("Modal schema cutover source and CI checks passed; operator attestations supplied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
