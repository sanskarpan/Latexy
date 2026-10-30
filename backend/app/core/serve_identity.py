"""Validated serving-revision provenance for health attestation.

The deployment workflow verifies an exact commit, then bakes `DEPLOY_SHA` into
every Modal image. Modal's own deployment pointer can therefore be checked with
``scripts/verify_modal_deployment_identity.py``. That pointer, however, only
proves what was *deployed*: it cannot prove which revision the containers that
answer a given request are actually running, and it silently reports success
while an older fleet is still draining.

Reading the revision from the process that serves the request closes that gap.
This module keeps the value strictly validated: only a lowercase 40-character
hexadecimal SHA is ever reported, and anything else (including a hostile or
mistyped environment value) is reported as unknown rather than echoed onto a
public endpoint.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping

from .deployment_hold import modal_redis_secret_name

DEPLOY_SHA_ENV = "DEPLOY_SHA"
DEPLOY_TARGET_ENV = "DEPLOY_TARGET"
ENVIRONMENT_ENV = "ENVIRONMENT"

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_PRODUCTION_ENVIRONMENTS = frozenset({"prod", "production"})


def serving_revision(environ: Mapping[str, str] | None = None) -> str | None:
    """Return the validated serving revision, or ``None`` when it is unknown.

    Only an exact lowercase 40-hex commit is accepted. Unset, blank, malformed,
    uppercase, or over/under-length values are all treated as unattested.
    """
    source = os.environ if environ is None else environ
    value = source.get(DEPLOY_SHA_ENV, "").strip().lower()
    return value if _GIT_SHA.fullmatch(value) else None


def deployment_target(environ: Mapping[str, str] | None = None) -> str:
    """Return a coarse serving target label for observability.

    This is descriptive metadata only. It never participates in authorization,
    capability admission, or the traffic hold.
    """
    source = os.environ if environ is None else environ
    if source.get(DEPLOY_TARGET_ENV, "").strip().lower() == "modal":
        return "modal"
    if source.get(ENVIRONMENT_ENV, "").strip().lower() in _PRODUCTION_ENVIRONMENTS:
        return "production"
    return "local"


def redis_binding_fingerprint(environ: Mapping[str, str] | None = None) -> str | None:
    """Attest the selected nonsecret label, never credentials or secret contents.

    This detects a selector change between held qualification and release. It
    cannot certify the mutable contents of a provider secret or Redis authority.
    """
    source = os.environ if environ is None else environ
    try:
        label = modal_redis_secret_name(source.get("MODAL_REDIS_SECRET_NAME"))
    except ValueError:
        return None
    return hashlib.sha256(("latexy-modal-redis-binding:v1\0" + label).encode()).hexdigest()
