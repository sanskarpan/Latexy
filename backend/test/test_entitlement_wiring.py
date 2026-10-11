"""Catalog coverage across server operations and explicitly client-only tools.

Real router deny/allow tests live in test_capability_route_policy.py. This guard
also catches entries without any declared enforcement point; client-only editor
controls must not be disguised as meaningless API gates.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.core.feature_registry import FEATURE_REGISTRY, feature_ancestry
from app.middleware.capability_router import ROUTE_CAPABILITIES

ROOT = Path(__file__).resolve().parents[2]


def test_every_gateable_key_has_server_or_client_enforcement():
    wired = {
        key for handlers in ROUTE_CAPABILITIES.values()
        for keys in handlers.values() for key in keys
    }
    # Owner/content-dependent gates live next to the resource they validate.
    sources = [
        *ROOT.glob("backend/app/api/*.py"),
        ROOT / "backend/app/middleware/capability_router.py",
        ROOT / "backend/app/services/api_key_service.py",
    ]
    for path in sources:
        text = path.read_text()
        wired.update(re.findall(r'''require_feature(?:_optional)?\(\s*["']([a-z_]+)["']''', text))
        wired.update(re.findall(r'''["']([a-i]\d\d)["']''', text))

    # Each client-only entry names real enforcement source files. The browser
    # extension lives outside frontend/src and uses a repository-relative path.
    policy = (ROOT / "frontend/src/lib/capability-ui-policy.ts").read_text()
    for key, paths in re.findall(r"^\s*([a-i]\d\d):\s*\[(.*)\],?$", policy, re.MULTILINE):
        source_paths = re.findall(r"'([^']+)'", paths)
        assert source_paths, key
        for relative in source_paths:
            path = ROOT / "frontend/src" / relative
            assert path.is_file(), (key, relative)
        wired.add(key)

    # A gated inventory child enforces its legacy coarse family too.
    for key in tuple(wired):
        wired.update(feature.key for feature in feature_ancestry(key))
    missing = sorted(feature.key for feature in FEATURE_REGISTRY if feature.gateable and feature.key not in wired)
    assert not missing, f"Capabilities without an enforcement point: {missing}"
