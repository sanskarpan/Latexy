"""The local launcher must sign and verify sessions with the same dotenv value."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("root_value", "backend_value", "explicit", "expected"),
    [
        ('"root-test-secret"', None, None, "root-test-secret"),
        ("root-test-secret", "'backend-test-secret'", None, "backend-test-secret"),
        ("root-test-secret", "backend-test-secret", "process-test-secret", "process-test-secret"),
        (None, None, None, ""),
    ],
)
def test_launcher_secret_resolution(root_value, backend_value, explicit, expected, tmp_path):
    repository = Path(__file__).resolve().parents[2]
    (tmp_path / "backend").mkdir()
    for path, value in [(tmp_path / ".env", root_value), (tmp_path / "backend/.env", backend_value)]:
        if value is not None:
            path.write_text(f"BETTER_AUTH_SECRET={value}\n")
    # Load function definitions only. Do not execute migrations or app startup.
    source = (repository / "scripts/dev.sh").read_text().split("# ── Main", 1)[0]
    environment = dict(os.environ, LOCAL_AUTH_FIXTURE=str(tmp_path), LOCAL_AUTH_PYTHON=sys.executable)
    environment.pop("BETTER_AUTH_SECRET", None)
    if explicit is not None:
        environment["BETTER_AUTH_SECRET"] = explicit
    process = subprocess.run(
        ["bash", "-c", 'source /dev/stdin; PROJECT_ROOT="$LOCAL_AUTH_FIXTURE"; resolve_dev_auth_secret "$LOCAL_AUTH_PYTHON"'],
        input=source,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert process.stdout == expected


def test_every_local_app_receives_the_resolved_signing_secret():
    repository = Path(__file__).resolve().parents[2]
    source = (repository / "scripts/dev.sh").read_text()
    # Uvicorn, Celery worker, beat, and Next all use the single resolved value.
    assert source.count('BETTER_AUTH_SECRET="$DEV_AUTH_SECRET" \\') == 4
