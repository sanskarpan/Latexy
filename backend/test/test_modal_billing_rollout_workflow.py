"""Exercise only the deployment guard's shell contract with a synthetic Modal CLI."""

import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/deploy-modal.yml"


def rollout_script():
    source = WORKFLOW.read_text()
    marker = source.index("      - name: Validate read-only billing rollout safety")
    start = source.index("        run: |\n", marker) + len("        run: |\n")
    # Keep this shell fixture scoped to this step when another preflight is
    # inserted before migrations. Comments and adjacent YAML are not shell.
    lines = []
    for line in source[start:].splitlines():
        if line.strip() and not line.startswith("          "):
            break
        lines.append(line)
    return textwrap.dedent("\n".join(lines))


def run_guard(tmp_path, accepted, result=0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command = bin_dir / "modal"
    command.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$CALL_LOG"\nexit "$MODAL_EXIT"\n')
    command.chmod(command.stat().st_mode | stat.S_IXUSR)
    env = {"PATH": f"{bin_dir}:{os.defpath}", "DEPLOY_SHA": "a" * 40,
           "CALL_LOG": str(tmp_path / "calls"), "MODAL_EXIT": str(result)}
    if accepted is not None:
        env["DODO_LIVE_BILLING_ACCEPTED"] = accepted
    executed = subprocess.run(["bash", "-c", rollout_script() + '\nprintf "continued"'],
                              env=env, capture_output=True, text=True, timeout=5)
    return executed, (tmp_path / "calls").read_text().splitlines()


@pytest.mark.parametrize("value,approved", [(None, False), ("", False), ("false", False),
                                          ("True", False), ("1", False), ("unexpected", False), ("true", True)])
def test_rollout_acceptance_defaults_false_and_requires_exact_operator_value(tmp_path, value, approved):
    result, args = run_guard(tmp_path, value)
    assert result.returncode == 0
    assert args == ["run", "--env", "main", "modal_app.py::billing_preflight", "--source-revision", "a" * 40,
                    "--expected-environment", "main", "--purpose", "rollout"] + (["--allow-configured-live"] if approved else [])
    assert result.stdout == "continued"


def test_failed_rollout_guard_stops_following_commands(tmp_path):
    result, _ = run_guard(tmp_path, None, result=23)
    assert result.returncode == 23
    assert "continued" not in result.stdout


def test_rollout_guard_keeps_production_and_main_boundaries_and_precedes_migration():
    source = WORKFLOW.read_text()
    guard = source.index("- name: Validate read-only billing rollout safety")
    renderer = source.index("- name: Check renderer configuration before migrations")
    migrate = source.index("- name: Apply production database migrations")
    deploy = source.index("- name: Deploy backend with a rolling update")
    assert source.index("- name: Validate immutable main revision and canonical CI success") < guard < renderer < migrate < deploy
    assert "environment: Production" in source
    assert "git merge-base --is-ancestor" in source
    assert "branches: [main]" in source
    assert 'vars.DODO_LIVE_BILLING_ACCEPTED' in source[guard:migrate]
    assert "continue-on-error" not in source[guard:deploy]
    assert "always()" not in source[guard:deploy]
    assert "secrets." not in source[guard:migrate]
