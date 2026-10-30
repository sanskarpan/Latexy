"""Pure environment parsing for the process-local deployment traffic hold."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

DEPLOYMENT_TRAFFIC_HOLD_ENV = "MODAL_DEPLOYMENT_TRAFFIC_HOLD"
MODAL_REDIS_SECRET_NAME_ENV = "MODAL_REDIS_SECRET_NAME"
DEFAULT_MODAL_REDIS_SECRET_NAME = "latexy-redis"
_PRODUCTION_MODAL_ENVIRONMENTS = frozenset({"main", "prod", "production"})
_DEVELOPMENT_MODAL_ENVIRONMENTS = frozenset({"dev", "development", "local", "test"})
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_MODAL_SECRET_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def modal_redis_secret_name(value: str | None = None) -> str:
    """Resolve a Redis Modal secret label without normalizing operator input."""
    if value is None or value == "":
        return DEFAULT_MODAL_REDIS_SECRET_NAME
    if not _MODAL_SECRET_LABEL.fullmatch(value):
        raise ValueError(f"{MODAL_REDIS_SECRET_NAME_ENV} must be a valid Modal secret label")
    return value


def deployment_traffic_held(
    environ: Mapping[str, str] | None = None,
    *,
    source_deployment: bool = False,
) -> bool:
    """Return the validated process-local traffic hold state.

    An unset hold preserves local development by default. Modal production
    processes and Modal source imports default to held. Unknown values fail
    closed. A source import may only select an unheld production deployment
    when the exact deployment SHA has the workflow's release approval.
    """
    source = os.environ if environ is None else environ
    redis_secret_name = modal_redis_secret_name(source.get(MODAL_REDIS_SECRET_NAME_ENV))
    value = source.get(DEPLOYMENT_TRAFFIC_HOLD_ENV, "")
    normalized = value.strip().lower()

    # An alternate authority can only be selected by an explicitly held
    # process. Enforce this at both Modal source import and runtime startup so
    # an approved SHA cannot accidentally release an alternate Redis binding.
    if redis_secret_name != DEFAULT_MODAL_REDIS_SECRET_NAME and normalized != "true":
        raise ValueError(
            "alternate Redis Modal secret requires MODAL_DEPLOYMENT_TRAFFIC_HOLD=true"
        )

    if normalized == "":
        if source_deployment or _is_production_modal_process(source):
            return True
        return False

    if normalized == "true":
        return True

    if normalized == "false":
        if source_deployment:
            environment = source.get("MODAL_ENVIRONMENT", "").strip().lower()
            if environment in _PRODUCTION_MODAL_ENVIRONMENTS:
                deploy_sha = source.get("DEPLOY_SHA", "").strip().lower()
                approved_sha = source.get("MODAL_TRAFFIC_RELEASE_APPROVED_SHA", "").strip().lower()
                if not _GIT_SHA.fullmatch(deploy_sha) or approved_sha != deploy_sha:
                    raise ValueError(
                        "unheld production Modal deploy requires the exact approved DEPLOY_SHA"
                    )
            elif environment not in _DEVELOPMENT_MODAL_ENVIRONMENTS:
                raise ValueError(
                    "unheld Modal source imports require MODAL_ENVIRONMENT=dev or an approved main SHA"
                )
        return False

    raise ValueError(f"{DEPLOYMENT_TRAFFIC_HOLD_ENV} must be true or false")


def _is_production_modal_process(source: Mapping[str, str]) -> bool:
    """Treat Modal and production-tagged runtimes as held when unset."""
    deployment_target = source.get("DEPLOY_TARGET", "").strip().lower()
    application_environment = source.get("ENVIRONMENT", "").strip().lower()
    modal_environment = source.get("MODAL_ENVIRONMENT", "").strip().lower()
    return (
        deployment_target == "modal"
        or application_environment in {"prod", "production"}
        or modal_environment in _PRODUCTION_MODAL_ENVIRONMENTS
    )
