"""Ordinary tests must never inherit live dispatch settings from developer env."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_conftest_forces_local_dispatch_and_test_environment():
    backend = Path(__file__).resolve().parents[1]
    environment = dict(
        os.environ,
        DEPLOY_TARGET="modal",
        ENVIRONMENT="production",
        RESEND_API_KEY="synthetic-test-provider-key",
    )
    process = subprocess.run(
        [sys.executable, "-c", """
import importlib.util
import json
import os
spec = importlib.util.spec_from_file_location('isolation_probe', 'test/conftest.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps({
    'target': os.environ['DEPLOY_TARGET'],
    'environment': os.environ['ENVIRONMENT'],
    'live_openai_disabled': not bool(os.environ['OPENAI_API_KEY']),
    'live_email_disabled': not bool(os.environ['RESEND_API_KEY']),
}))
"""],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    payload = json.loads(process.stdout.strip().splitlines()[-1])
    assert payload == {
        "target": "local",
        "environment": "test",
        "live_openai_disabled": True,
        "live_email_disabled": True,
    }


@pytest.mark.parametrize(
    ("script", "boundary", "expected_environment"),
    [
        ("scripts/dev.sh", "# PID file", "development"),
        ("scripts/ci/full-stack-smoke.sh", 'backend_pid=""', "production"),
    ],
)
def test_local_launchers_override_inherited_modal_dispatch(script, boundary, expected_environment):
    repository = Path(__file__).resolve().parents[2]
    # Execute only environment setup, never migrations, servers, or consumers.
    prefix = (repository / script).read_text().split(boundary, 1)[0]
    process = subprocess.run(
        ["bash", "-c", 'source /dev/stdin; printf "%s\\n%s\\n" "$DEPLOY_TARGET" "$ENVIRONMENT"'],
        input=prefix,
        env=dict(os.environ, DEPLOY_TARGET="modal", ENVIRONMENT="production"),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert process.stdout.splitlines() == ["local", expected_environment]
