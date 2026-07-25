"""Regression guard: every gateable feature key must be enforced on a route.

The audit found gateable features in the registry that had NO
``require_feature`` / ``require_feature_optional`` reference on any API route,
so admins could disable them and the endpoint would still run (silent
non-enforcement). This test scans ``app/api/*.py`` for those dependency
references and asserts that every ``gateable_keys()`` entry appears at least
once. If a new gateable feature is added to the registry without wiring an
enforcement dependency, this test FAILS and names the unwired keys.
"""

from __future__ import annotations

import glob
import os
import re

from app.core.feature_registry import gateable_keys

# Matches require_feature("key") and require_feature_optional("key").
_REF_RE = re.compile(r'require_feature(?:_optional)?\(\s*["\']([a-z_]+)["\']\s*\)')

_API_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app",
    "api",
)


def _wired_keys() -> set[str]:
    wired: set[str] = set()
    for path in glob.glob(os.path.join(_API_DIR, "*.py")):
        with open(path, encoding="utf-8") as fh:
            for match in _REF_RE.finditer(fh.read()):
                wired.add(match.group(1))
    return wired


def test_every_gateable_key_is_enforced_on_a_route() -> None:
    wired = _wired_keys()
    missing = sorted(k for k in gateable_keys() if k not in wired)
    assert not missing, (
        "Gateable feature keys with NO require_feature/"
        "require_feature_optional enforcement on any app/api route: "
        f"{missing}. Wire an enforcement dependency on the primary entry "
        "route, or mark the feature gateable=False in the registry."
    )
