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


def test_full_stack_keys_are_ephemeral_valid_and_never_inherit_credentials():
    repository = Path(__file__).resolve().parents[2]
    prefix = (repository / "scripts/ci/full-stack-smoke.sh").read_text().split('backend_pid=""', 1)[0]
    probe = """
import base64, hashlib, json, os
keys = [os.environ[k] for k in ('BETTER_AUTH_SECRET', 'JWT_SECRET_KEY', 'API_KEY_ENCRYPTION_KEY')]
assert all(k != 'synthetic-inherited-value' for k in keys)
assert len(keys[0]) >= 32 and len(keys[1]) >= 32
assert len(base64.urlsafe_b64decode(keys[2])) == 32
assert not os.environ['OPENAI_API_KEY'] and not os.environ['RESEND_API_KEY']
print(json.dumps([hashlib.sha256(k.encode()).hexdigest() for k in keys]))
"""
    environment = dict(os.environ, DATABASE_URL="postgresql://localhost:5434/latexy_test",
                       BETTER_AUTH_SECRET="synthetic-inherited-value", JWT_SECRET_KEY="synthetic-inherited-value",
                       API_KEY_ENCRYPTION_KEY="synthetic-inherited-value", OPENAI_API_KEY="synthetic-model",
                       RESEND_API_KEY="synthetic-email")
    digests = []
    for _ in range(2):
        process = subprocess.run(["bash", "-c", 'source /dev/stdin; "$1" -c "$2"', "smoke", sys.executable, probe],
                                 input=prefix, env=environment, capture_output=True, text=True, timeout=10, check=True)
        digests.append(json.loads(process.stdout))
    assert set(digests[0]).isdisjoint(digests[1])


@pytest.mark.parametrize("database", ["postgresql://remote.invalid/latexy_test", "postgresql://localhost/latexy"])
def test_full_stack_rejects_nonisolated_database_before_startup(database):
    repository = Path(__file__).resolve().parents[2]
    prefix = (repository / "scripts/ci/full-stack-smoke.sh").read_text().split('backend_pid=""', 1)[0]
    process = subprocess.run(["bash", "-c", 'source /dev/stdin; echo unsafe-startup'], input=prefix,
                             env=dict(os.environ, DATABASE_URL=database), capture_output=True, text=True, timeout=10)
    assert process.returncode != 0
    assert "unsafe-startup" not in process.stdout
    assert "loopback *_test database" in process.stderr
