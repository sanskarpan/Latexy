"""Guard: every risk-class setting is documented in .env.example (#980).

The risk class is a config default that is **empty** or points at **localhost** —
exactly the defaults that are silently wrong in a deployed environment (a boot
assert fires, or a service quietly talks to a Redis/Minio/URL that isn't there).
Genuinely-safe defaults (timeouts, pool sizes, feature flags) are not the concern.

This test parses ``app/core/config.py`` for those settings and asserts each is
present in ``.env.example``, so the deployed Modal secret has a source of truth
and new empty/localhost settings can't be added without documenting them.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_CONFIG = _BACKEND / "app" / "core" / "config.py"
_ENV_EXAMPLE = _BACKEND / ".env.example"


def _string_default(value: ast.expr | None) -> str | None:
    """Extract a string default from an annotation value, or None if not a plain string.

    Handles both ``NAME: str = "..."`` and ``NAME: str = Field(default="...")`` /
    ``Field("...")``. Non-string defaults (Field(default_factory=...), numbers,
    bools) return None and are ignored.
    """
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    if isinstance(value, ast.Call) and getattr(value.func, "id", None) == "Field":
        for kw in value.keywords:
            if kw.arg == "default" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value
        for arg in value.args:  # Field's first positional is the default
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return arg.value
    return None


def _is_risk_default(default: str) -> bool:
    return default == "" or "localhost" in default or "127.0.0.1" in default


def _risk_settings() -> dict[str, str]:
    tree = ast.parse(_CONFIG.read_text())
    settings_cls = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "Settings"),
        None,
    )
    assert settings_cls is not None, "Settings class not found in config.py"

    risk: dict[str, str] = {}
    for stmt in settings_cls.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            default = _string_default(stmt.value)
            if default is not None and _is_risk_default(default):
                risk[stmt.target.id] = default
    return risk


def _documented_keys() -> set[str]:
    keys: set[str] = set()
    for line in _ENV_EXAMPLE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return keys


def test_risk_class_settings_are_documented_in_env_example():
    risk = _risk_settings()
    documented = _documented_keys()
    missing = sorted(k for k in risk if k not in documented)
    assert not missing, (
        "These settings default to empty-or-localhost but are undocumented in "
        f".env.example (see #980): {missing}"
    )


def test_finds_a_meaningful_number_of_risk_settings():
    # Sanity check the parser actually resolves defaults (guards against a silent
    # parse change that would make the guard above vacuously pass).
    risk = _risk_settings()
    assert "REDIS_CACHE_URL" in risk
    assert "DATABASE_URL" in risk
    assert len(risk) >= 20
