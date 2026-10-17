"""Run all dependency-free synthetic tests for the private Modal harness."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_TEST_PATTERN = "test_modal_spawn_diagnostics.py"
_MINIMUM_EXPECTED_TESTS = 26


def main() -> int:
    test_dir = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(
        str(test_dir), pattern=_TEST_PATTERN, top_level_dir=str(test_dir),
    )
    selected = suite.countTestCases()
    if selected < _MINIMUM_EXPECTED_TESTS:
        print(
            f"Expected at least {_MINIMUM_EXPECTED_TESTS} harness tests; selected {selected}.",
            file=sys.stderr,
        )
        return 2

    print(f"Selected {selected} synthetic Modal harness tests.")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
