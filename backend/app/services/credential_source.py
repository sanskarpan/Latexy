"""Non-secret credential-source labels for first-party LLM usage.

The admin analytics surface must never read key material, ciphertext, key names
or per-key fingerprints.  It only needs to answer one question for each run:
was the provider call paid for with the operator's platform key or with a key
the account supplied (BYOK)?

Semantic resume-engine runs persist a keyed HMAC ``credential_scope`` and now
also persist a non-secret ``credential_source`` label beside the run context.
Older rows have no explicit label, so this module preserves the previous
classification rule: compare the stored scope against the fingerprints of the
currently configured platform keys, and treat any other keyed fingerprint as
BYOK.  Anything unclassifiable stays ``unknown``.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..core.config import settings

CREDENTIAL_SOURCES = ("byok", "platform", "unknown")
CREDENTIAL_SOURCE_ORDER = {source: index for index, source in enumerate(CREDENTIAL_SOURCES)}

_HEX_HASH = re.compile(r"^[0-9a-f]{64}$")
_PLATFORM_SCOPE_PREFIXES = ("platform", "managed", "system", "server")
_BYOK_SCOPE_PREFIXES = ("byok", "user", "custom", "own")


def normalize_credential_source(value: Any) -> str | None:
    """Return a known source label, or ``None`` for arbitrary client data."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in CREDENTIAL_SOURCES else None


def configured_platform_keys() -> tuple[str, ...]:
    """The operator's configured provider keys, never a user's stored key."""
    return tuple(
        key
        for key in (
            settings.OPENAI_API_KEY,
            settings.ANTHROPIC_API_KEY,
            settings.OPENROUTER_API_KEY,
            settings.GEMINI_API_KEY,
        )
        if isinstance(key, str) and key
    )


def platform_credential_scopes() -> set[str]:
    """Fingerprints of configured platform keys, never the keys themselves."""
    try:
        from .resume_engine.credential_scope import credential_scope
    except Exception:  # pragma: no cover - configuration failure falls back to unknown
        return set()

    scopes: set[str] = set()
    for key in configured_platform_keys():
        try:
            scopes.add(credential_scope(key))
        except Exception:
            continue
    return scopes


def credential_source_from_scope(
    scope: Any,
    platform_scopes: Iterable[str],
    persisted_source: Any = None,
) -> str:
    """Classify one persisted run without exposing its credential fingerprint.

    A valid server-written label wins over inference.  The stored HMAC is only
    compared in memory with the current platform-key fingerprint set; it is
    never returned to the caller.
    """
    explicit = normalize_credential_source(persisted_source)
    if explicit is not None:
        return explicit

    if not isinstance(scope, str) or not scope.strip():
        return "unknown"
    normalized = scope.strip().lower()
    if normalized.startswith(_PLATFORM_SCOPE_PREFIXES):
        return "platform"
    if normalized.startswith(_BYOK_SCOPE_PREFIXES):
        return "byok"
    if normalized in set(platform_scopes):
        return "platform"
    # Durable resume-engine scopes are keyed HMAC fingerprints.  Anything that is
    # a fingerprint but not the platform key must have come from a user key.
    if _HEX_HASH.match(normalized):
        return "byok"
    return "unknown"


def credential_source_for_api_key(api_key: Any) -> str:
    """Label a just-admitted run's key without persisting the key.

    Platform keys are compared by exact value.  A non-empty key that is not a
    configured platform key is a BYOK key; an absent key is unknown.
    """
    if not isinstance(api_key, str) or not api_key:
        return "unknown"
    if api_key in configured_platform_keys():
        return "platform"
    return "byok"
