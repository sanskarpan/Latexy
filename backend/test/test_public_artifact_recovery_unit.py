"""Run isolated recovery unit tests in a subprocess to contain fake settings."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_public_artifact_recovery_standalone_harness():
    script = Path(__file__).parents[1] / "scripts" / "test_public_artifact_recovery_unit.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, f"Standalone recovery tests failed:\n{result.stdout}\n{result.stderr}"
