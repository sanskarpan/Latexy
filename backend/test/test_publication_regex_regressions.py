"""Adversarial controls for regex findings raised during publication."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("case", ["metrics", "authors", "bibtex"])
def test_large_failed_matches_finish_without_quadratic_backtracking(case):
    # Enforce a process deadline: a future regex regression cannot hang pytest.
    script = {
        "metrics": """
from app.services.bullet_metric_service import replace_unverified_metrics
assert replace_unverified_metrics('0' * 100_000 + 'a') == '0' * 100_000 + 'a'
assert replace_unverified_metrics('0,' * 50_000 + 'a').endswith(',a')
assert replace_unverified_metrics('0' + ',0' * 50_000 + 'a').endswith(',a')
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
    subprocess.run([sys.executable, "-c", script], timeout=8, check=True, capture_output=True)
