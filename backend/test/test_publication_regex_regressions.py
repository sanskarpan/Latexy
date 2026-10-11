"""Adversarial controls for regex findings raised during publication."""

import subprocess
import sys
import time

import pytest


@pytest.mark.parametrize("case", ["metrics", "authors", "bibtex"])
def test_large_failed_matches_finish_without_quadratic_backtracking(case, tmp_path):
    # Enforce the regex deadline independently of application import startup.
    script = {
        "metrics": """
from app.services.bullet_metric_service import replace_unverified_metrics
assert replace_unverified_metrics('0' * 100_000 + 'a') == '0' * 100_000 + 'a'
assert replace_unverified_metrics('0,' * 50_000 + 'a').endswith(',a')
assert replace_unverified_metrics('0' + ',0' * 50_000 + 'a') == '[X],0a'
assert replace_unverified_metrics('Led,12 engineers; cost,$23.') == 'Led,[X] engineers; cost,$[X].'
""",
        "authors": """
from app.api.reference_routes import _author_surnames
assert _author_surnames(' ' * 100_000) == set()
assert _author_surnames('Lovelace, Ada and Turing, Alan') == {'lovelace', 'turing'}
assert _author_surnames('Lovelace, Ada\\tAND\\nTuring, Alan') == {'lovelace', 'turing'}
""",
        "bibtex": """
from app.services.reference_service import ReferenceService
try:
    ReferenceService.parse_bibtex_entries('@article{' + ' ' * 100_000 + '!}')
except ValueError as exc:
    assert 'cite key' in str(exc)
else:
    raise AssertionError('Malformed key accepted')
""",
    }[case]
    imports, checks = script.strip().split("\n", 1)
    ready = tmp_path / "imports-ready"
    bootstrap = f"{imports}\nfrom pathlib import Path\nPath({str(ready)!r}).touch()\n{checks}"
    log = tmp_path / "regex-process.log"
    with log.open("w") as output:
        process = subprocess.Popen([sys.executable, "-c", bootstrap], stdout=output, stderr=output)
        try:
            startup_deadline = time.monotonic() + 60
            while not ready.exists() and process.poll() is None:
                if time.monotonic() >= startup_deadline:
                    pytest.fail("Application imports did not finish within 60 seconds")
                time.sleep(0.05)
            # A catastrophic regex still cannot hang pytest, including on Windows.
            process.wait(timeout=8)
            assert process.returncode == 0, log.read_text()
            assert ready.exists(), "Regex checks did not reach their import boundary"
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
