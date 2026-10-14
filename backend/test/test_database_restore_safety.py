"""Execute restore control flow with shell fakes; never connect to a database."""

import os
import re
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[2] / "scripts/backup/restore-database.sh"


def function_source(name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}", SOURCE.read_text(), re.M | re.S)
    assert match is not None
    return match.group()


def run_restore(tmp_path: Path, *, failure: str = "", compressed: bool = False):
    backup = tmp_path / ("synthetic.sql.gz" if compressed else "synthetic.sql")
    backup.write_text("SELECT 1;\n")
    calls = tmp_path / "calls"
    script = r'''
set -euo pipefail
log() { printf '%s\n' "$1"; }
verify_backup_file() { return 0; }
create_pre_restore_backup() { [[ "$FAILURE" != backup ]]; }
psql() {
    local args="$*"
    printf '%s\n' "${args//$'\n'/ }" >> "$CALLS"
    if [[ "$*" == *'DROP DATABASE'* && "$FAILURE" == drop ]]; then return 23; fi
    if [[ "$*" == *'CREATE DATABASE'* && "$FAILURE" == create ]]; then return 23; fi
    if [[ "$*" != *' -c '* ]]; then
        cat >/dev/null
        # Model psql's documented distinction: SQL errors are fatal only when
        # ON_ERROR_STOP is explicitly set. No SQL is actually interpreted here.
        if [[ "$FAILURE" == sql && "$*" == *'ON_ERROR_STOP=1'* ]]; then return 3; fi
    fi
    return 0
}
gunzip() { cat "$2"; [[ "$FAILURE" != decompress ]]; }
'''
    script += function_source("restore_database")
    # Match the real caller's conditional: errexit alone is not sufficient
    # inside a function called from an if statement.
    script += '\nif restore_database "$1" false; then exit 0; else exit 1; fi\n'
    result = subprocess.run(
        ["bash", "-s", "--", str(backup)], input=script, text=True,
        capture_output=True, timeout=5,
        env={"PATH": os.defpath, "DATABASE_URL": "postgresql://localhost/synthetic_test",
             "CALLS": str(calls), "FAILURE": failure},
    )
    return result, calls.read_text() if calls.exists() else ""


def test_failed_safety_backup_prevents_every_database_command(tmp_path):
    result, calls = run_restore(tmp_path, failure="backup")
    assert result.returncode == 1
    assert calls == ""


@pytest.mark.parametrize("failure", ["drop", "create"])
def test_database_recreation_error_stops_before_loading_backup(tmp_path, failure):
    result, calls = run_restore(tmp_path, failure=failure)
    assert result.returncode == 1
    assert "Database restored successfully" not in result.stdout
    assert len(calls.splitlines()) == (2 if failure == "drop" else 3)


@pytest.mark.parametrize("compressed", [False, True])
def test_restore_sql_errors_cannot_be_reported_as_success(tmp_path, compressed):
    result, calls = run_restore(tmp_path, failure="sql", compressed=compressed)
    assert result.returncode == 1
    assert "ON_ERROR_STOP=1" in calls.splitlines()[-1]
    assert "Database restored successfully" not in result.stdout


@pytest.mark.parametrize("compressed", [False, True])
def test_successful_restore_uses_error_stopping_sql_client(tmp_path, compressed):
    result, calls = run_restore(tmp_path, compressed=compressed)
    assert result.returncode == 0, result.stderr
    assert "ON_ERROR_STOP=1" in calls.splitlines()[-1]
    assert "Database restored successfully" in result.stdout


def test_decompression_failure_remains_fatal(tmp_path):
    result, _ = run_restore(tmp_path, failure="decompress", compressed=True)
    assert result.returncode == 1


def test_failed_safety_backup_compression_is_not_success(tmp_path):
    script = r'''
set -euo pipefail
log() { printf '%s\n' "$1"; }
pg_dump() { printf 'synthetic backup'; }
gzip() { return 23; }
'''
    script += function_source("create_pre_restore_backup")
    script += '\nif create_pre_restore_backup; then exit 0; else exit 1; fi\n'
    result = subprocess.run(
        ["bash", "-s"], input=script, text=True, capture_output=True, timeout=5,
        env={"PATH": os.defpath, "BACKUP_DIR": str(tmp_path),
             "DATABASE_URL": "postgresql://localhost/synthetic_test"},
    )
    assert result.returncode == 1
    assert "Pre-restore backup created" not in result.stdout


@pytest.mark.parametrize("failure", [False, True])
def test_s3_download_reserves_stdout_for_the_backup_path(tmp_path, failure):
    script = r'''
set -euo pipefail
log() { printf '%s\n' "$1"; }
aws() { printf 'download: synthetic progress\n'; [[ "$FAILURE" != true ]]; }
'''
    script += function_source("download_from_s3")
    script += '\nif result=$(download_from_s3 "synthetic.sql.gz"); then printf "%s\n" "$result"; else exit 1; fi\n'
    result = subprocess.run(
        ["bash", "-s"], input=script, text=True, capture_output=True, timeout=5,
        env={"PATH": os.defpath, "BACKUP_DIR": str(tmp_path),
             "S3_BUCKET": "synthetic-test-bucket", "FAILURE": str(failure).lower()},
    )
    assert result.returncode == (1 if failure else 0)
    assert result.stdout == ("" if failure else f"{tmp_path}/temp_synthetic.sql.gz\n")
    assert "Downloading backup from S3:" in result.stderr
    assert "download: synthetic progress" in result.stderr
    assert ("ERROR: Failed to download backup from S3" in result.stderr) is failure
