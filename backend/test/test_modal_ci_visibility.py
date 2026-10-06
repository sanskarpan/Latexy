"""Offline execution tests for the deploy workflow's CI visibility gate."""

import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-modal.yml"
DEPLOY_SHA = "a" * 40


def _validation_script() -> str:
    workflow = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Validate immutable main revision and canonical CI success"
    start = workflow.index("        run: |", workflow.index(marker)) + len("        run: |\n")
    end = workflow.index("\n      - name:", start)
    return textwrap.dedent(workflow[start:end])


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_validator(
    tmp_path: Path,
    payloads: dict[int, str],
    *,
    last_payload: str | None = None,
    gh_failures: int = 0,
    ancestor: bool = True,
) -> tuple[subprocess.CompletedProcess[str], list[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    for attempt, payload in payloads.items():
        (payload_dir / f"{attempt}.json").write_text(payload, encoding="utf-8")
    if last_payload is not None:
        (payload_dir / "last.json").write_text(last_payload, encoding="utf-8")

    count_file = tmp_path / "gh-count"
    call_log = tmp_path / "gh-calls"
    sleep_log = tmp_path / "sleep-calls"
    github_env = tmp_path / "github-env"

    _write_executable(
        bin_dir / "git",
        """#!/usr/bin/env bash
set -u
case "${1:-}" in
  fetch) exit 0 ;;
  rev-parse) printf '%s\\n' "$DEPLOY_SHA" ;;
  merge-base)
    [[ "${FAIL_ANCESTOR:-0}" != 1 ]]
    ;;
  *) exit 64 ;;
esac
""",
    )
    _write_executable(
        bin_dir / "timeout",
        """#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == "--kill-after=5s" ]]
[[ "${2:-}" == "20s" ]]
shift 2
exec "$@"
""",
    )
    _write_executable(
        bin_dir / "sleep",
        """#!/usr/bin/env bash
set -u
printf '%s\\n' "$1" >> "$SLEEP_LOG"
""",
    )
    _write_executable(
        bin_dir / "gh",
        """#!/usr/bin/env bash
set -u
[[ "${1:-}" == api ]]
printf '%s\\n' "$*" >> "$GH_CALL_LOG"
count=0
if [[ -f "$GH_COUNT_FILE" ]]; then
  count="$(<"$GH_COUNT_FILE")"
fi
count=$((count + 1))
printf '%s' "$count" > "$GH_COUNT_FILE"
if [[ "$count" -le "$GH_FAILURES" ]]; then
  exit 1
fi
payload="$GH_PAYLOAD_DIR/${count}.json"
if [[ ! -f "$payload" ]]; then
  payload="$GH_PAYLOAD_DIR/last.json"
fi
[[ -f "$payload" ]]
cat "$payload"
""",
    )

    env = {
        "PATH": f"{bin_dir}:{os.defpath}",
        "DEPLOY_REF": "main",
        "DEPLOY_SHA": DEPLOY_SHA,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REPOSITORY": "synthetic/repository",
        "GH_TOKEN": "synthetic-token-not-real",
        "GH_PAYLOAD_DIR": str(payload_dir),
        "GH_COUNT_FILE": str(count_file),
        "GH_CALL_LOG": str(call_log),
        "GH_FAILURES": str(gh_failures),
        "FAIL_ANCESTOR": "0" if ancestor else "1",
        "SLEEP_LOG": str(sleep_log),
        "GITHUB_ENV": str(github_env),
    }
    result = subprocess.run(
        ["bash", "-c", _validation_script()],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
    sleeps = sleep_log.read_text(encoding="utf-8").splitlines() if sleep_log.exists() else []
    return result, calls, "\n".join(sleeps)


def _success_payload(sha: str = DEPLOY_SHA) -> str:
    return (
        '{"workflow_runs":[{"head_sha":"'
        + sha
        + '","head_branch":"main","conclusion":"success"}]}'
    )


def test_ci_lookup_retries_visibility_then_accepts_exact_success(tmp_path):
    result, calls, sleeps = _run_validator(
        tmp_path,
        {1: '{"workflow_runs":[]}', 2: _success_payload()},
        last_payload=_success_payload(),
    )

    assert result.returncode == 0, result.stderr
    assert len(calls) == 2
    assert sleeps == "5"
    expected_endpoint = (
        "api repos/synthetic/repository/actions/workflows/ci.yml/runs?"
        f"head_sha={DEPLOY_SHA}&branch=main&status=completed&per_page=100"
    )
    assert calls == [expected_endpoint, expected_endpoint]
    assert "DEPLOY_SHA=" + DEPLOY_SHA in (tmp_path / "github-env").read_text()
    assert "workflow_runs" not in result.stdout + result.stderr


def test_ci_lookup_accepts_immediately_without_sleeping(tmp_path):
    result, calls, sleeps = _run_validator(
        tmp_path,
        {1: _success_payload()},
        last_payload=_success_payload(),
    )

    assert result.returncode == 0, result.stderr
    assert len(calls) == 1
    assert sleeps == ""


def test_ci_lookup_accepts_a_valid_run_among_invalid_entries(tmp_path):
    mixed = (
        '{"workflow_runs":['
        '{"head_sha":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
        '"head_branch":"main","conclusion":"success"},'
        + _success_payload()[len('{"workflow_runs":[') : -2]
        + "]}"
    )
    result, calls, sleeps = _run_validator(
        tmp_path,
        {1: mixed},
        last_payload=mixed,
    )

    assert result.returncode == 0, result.stderr
    assert len(calls) == 1
    assert sleeps == ""


@pytest.mark.parametrize(
    ("name", "payload", "gh_failures"),
    [
        ("permanent-missing", '{"workflow_runs":[]}', 0),
        ("non-array-workflow-runs", '{"workflow_runs":{}}', 0),
        (
            "wrong-fields",
            '{"workflow_runs":['
            '{"head_sha":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
            '"head_branch":"main","conclusion":"success"},'
            '{"head_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
            '"head_branch":"release","conclusion":"success"},'
            '{"head_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
            '"head_branch":"main","conclusion":"failure"}]}',
            0,
        ),
        ("malformed-json", "{not-json", 0),
        ("api-failure", "", 6),
    ],
)
def test_ci_lookup_fails_closed_after_bounded_invalid_results(
    tmp_path,
    name,
    payload,
    gh_failures,
):
    result, calls, sleeps = _run_validator(
        tmp_path,
        {1: payload} if not gh_failures else {},
        last_payload=payload if not gh_failures else None,
        gh_failures=gh_failures,
    )

    assert result.returncode != 0, name
    assert len(calls) == 6, name
    assert sleeps.splitlines() == ["5"] * 5, name
    assert "Refusing to deploy" in result.stderr
    assert "not-json" not in result.stdout + result.stderr


def test_ancestry_rejection_precedes_ci_lookup(tmp_path):
    result, calls, sleeps = _run_validator(
        tmp_path,
        {1: _success_payload()},
        last_payload=_success_payload(),
        ancestor=False,
    )

    assert result.returncode != 0
    assert calls == []
    assert sleeps == ""
    assert "not reachable from main" in result.stderr
