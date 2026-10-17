"""Explicitly opt-in, isolated Modal API -> worker -> renderer acceptance run.

This script creates uniquely named nonproduction Modal apps in an explicitly
selected, pre-existing nonproduction Environment and disposable
PostgreSQL, Redis, and Moto S3 services. It never looks up named production
Secrets, uses Volumes or public tunnels, or writes its runtime report inside
the repository. It does not set report file permissions or ACLs. Running
it provisions paid infrastructure and requires explicit confirmations for
resource use, default function egress, the nonproduction renderer binding, and
(in boundary mode) the renderer boundary probe. Functional-only mode performs
the same API/worker/PDF acceptance flow without executing the renderer boundary
probe and never asserts certification. Before any functional run, the harness
also verifies a source-approved Environment ID and fresh read-only inventory of
named Secrets, Volumes, and active Apps without reading or printing Secret values.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import secrets
import shutil
import socket
import subprocess
import sys
import zipfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.services.render_engine.functional_acceptance_policy import (
    FunctionalAcceptanceEnvironmentApproval,
    functional_environment_inventory_sha256,
    get_functional_acceptance_environment_approval,
    is_trusted_functional_acceptance_environment,
)

_LABEL = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
_IMAGE_ID = re.compile(r"im-[A-Za-z0-9]{6,128}\Z")
_ROLES = frozenset({"service", "caller", "worker"})
_PRODUCTION_ENVIRONMENT_NAMES = frozenset({"main", "prod", "production"})
_PRODUCTION_ENVIRONMENT_ALIAS = re.compile(
    r"(?:^|[-_.:])(?:main|prod(?:uction)?|live)(?:$|[-_.:])", re.IGNORECASE,
)


def _safe_label(value: object) -> str:
    return value if isinstance(value, str) and _LABEL.fullmatch(value) else "unknown"


def validate_nonproduction_environment_name(name: str) -> str:
    """Require an explicit environment name and reject known production names."""
    if (
        not isinstance(name, str)
        or not _LABEL.fullmatch(name)
        or name.lower() in _PRODUCTION_ENVIRONMENT_NAMES
        or _PRODUCTION_ENVIRONMENT_ALIAS.search(name)
    ):
        raise HarnessFailure("arguments", "nonproduction_environment_required")
    return name


def validate_functional_acceptance_environment_name(name: str) -> str:
    """Require an exact, complete source-reviewed identity approval."""
    validate_nonproduction_environment_name(name)
    if get_functional_acceptance_environment_approval(name) is None:
        raise HarnessFailure("arguments", "functional_environment_not_allowlisted")
    return name


@dataclass(frozen=True)
class FunctionalEnvironmentInventory:
    environment_object_id: str
    binding_manifest_sha256: str
    secret_count: int
    volume_count: int
    active_app_count: int


def _read_named_object_identities(items: Sequence[Any]) -> tuple[tuple[str, str], ...]:
    identities = []
    for item in items:
        if isinstance(item, Mapping):
            name = item.get("name")
            object_id = item.get("object_id")
        else:
            name = getattr(item, "name", None)
            object_id = getattr(item, "object_id", None)
        if (not isinstance(name, str) or not name or any(ord(char) < 32 for char in name)
                or not isinstance(object_id, str) or not object_id or len(object_id) > 128
                or any(ord(char) < 32 for char in object_id)):
            raise HarnessFailure("environment_validation", "functional_inventory_identity_unavailable")
        identities.append((name, object_id))
    return tuple(sorted(identities))


def _read_cli_active_app_identities(items: Any) -> tuple[tuple[str, str], ...]:
    """Read live App metadata from the documented Modal CLI JSON listing."""
    if not isinstance(items, list):
        raise HarnessFailure("active_app_list", "functional_inventory_identity_unavailable")
    active_items = []
    for item in items:
        if not isinstance(item, Mapping):
            raise HarnessFailure("active_app_list", "functional_inventory_identity_unavailable")
        state = item.get("state")
        if not isinstance(state, str) or not state:
            raise HarnessFailure("active_app_list", "functional_inventory_identity_unavailable")
        # The CLI includes recently stopped records. Count anything not explicitly
        # stopped or disabled so an unknown state fails closed as an active binding.
        if state.casefold() in {"stopped", "disabled"}:
            continue
        active_items.append({"name": item.get("description"), "object_id": item.get("app_id")})
    return _read_named_object_identities(active_items)


def _modal_cli_error_class(stderr: str) -> str:
    """Classify CLI failures without returning provider text or resource metadata."""
    message = stderr.casefold()
    if any(term in message for term in ("permission denied", "permissiondenied", "forbidden", "not authorized")):
        return "PermissionDeniedError"
    if any(term in message for term in ("unauthenticated", "not authenticated", "unauthorized", "no modal token")):
        return "UnauthenticatedError"
    return "ModalCliCommandError"


def _read_active_app_identities(environment: Any, name: str) -> tuple[tuple[str, str], ...]:
    """Use Environment.apps when present; use the supported 1.5.x CLI otherwise."""
    apps_manager = getattr(environment, "apps", None)
    apps_list = getattr(apps_manager, "list", None)
    if callable(apps_list):
        return _read_named_object_identities(list(apps_list()))

    try:
        result = subprocess.run(
            [sys.executable, "-m", "modal", "app", "list", "--env", name, "--json"],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except Exception as error:
        raise HarnessFailure(
            "active_app_list", "functional_environment_inventory_failed", error_class=type(error).__name__,
        ) from None
    if result.returncode != 0:
        raise HarnessFailure(
            "active_app_list", "functional_environment_inventory_failed",
            error_class=_modal_cli_error_class(result.stderr),
        )
    try:
        items = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise HarnessFailure(
            "active_app_list", "functional_environment_inventory_failed", error_class=type(error).__name__,
        ) from None
    return _read_cli_active_app_identities(items)


def read_functional_environment_inventory(
    modal_sdk: Any, name: str,
) -> FunctionalEnvironmentInventory:
    """Read only environment identity plus Secret/Volume/live-App object metadata.

    Secret values are never requested or inspected. Any unsupported or incomplete
    listing fails closed so the approval cannot silently degrade to a name check.
    """
    stage = "environment_list"
    try:
        environments = list(modal_sdk.Environment.objects.list())
        matches = [environment for environment in environments
                   if getattr(environment, "name", None) == name]
        if len(matches) != 1:
            raise HarnessFailure("environment_validation", "environment_not_found")
        environment = matches[0]
        environment_object_id = getattr(environment, "object_id", None)
        if (not isinstance(environment_object_id, str) or not environment_object_id
                or len(environment_object_id) > 128
                or any(ord(char) < 32 for char in environment_object_id)):
            raise HarnessFailure("environment_validation", "functional_environment_identity_unavailable")

        # These list APIs return named object handles; no Secret contents are read.
        stage = "secret_list"
        secrets = list(modal_sdk.Secret.objects.list(environment_name=name))
        stage = "volume_list"
        volumes = list(modal_sdk.Volume.objects.list(environment_name=name))
        stage = "active_app_list"
        app_identities = _read_active_app_identities(environment, name)
        secret_identities = _read_named_object_identities(secrets)
        volume_identities = _read_named_object_identities(volumes)
    except HarnessFailure:
        raise
    except Exception as error:
        raise HarnessFailure(
            stage, "functional_environment_inventory_failed", error_class=type(error).__name__,
        ) from None

    fingerprint = functional_environment_inventory_sha256(
        name, environment_object_id,
        secret_identities=secret_identities,
        volume_identities=volume_identities,
        active_app_identities=app_identities,
    )
    return FunctionalEnvironmentInventory(
        environment_object_id=environment_object_id,
        binding_manifest_sha256=fingerprint,
        secret_count=len(secret_identities),
        volume_count=len(volume_identities),
        active_app_count=len(app_identities),
    )


def validate_existing_nonproduction_environment(
    modal_sdk: Any, name: str, *, functional_only: bool = False,
) -> str | FunctionalAcceptanceEnvironmentApproval:
    """Read-only environment check; functional mode requires exact identity and empty inventory."""
    name = (
        validate_functional_acceptance_environment_name(name)
        if functional_only else validate_nonproduction_environment_name(name)
    )
    if functional_only:
        approval = get_functional_acceptance_environment_approval(name)
        if approval is None:
            raise HarnessFailure("environment_validation", "functional_environment_not_allowlisted")
        inventory = read_functional_environment_inventory(modal_sdk, name)
        if inventory.environment_object_id != approval.environment_object_id:
            raise HarnessFailure("environment_validation", "functional_environment_identity_mismatch")
        if inventory.secret_count or inventory.volume_count or inventory.active_app_count:
            raise HarnessFailure("environment_validation", "functional_environment_not_empty")
        if not is_trusted_functional_acceptance_environment(
            name, inventory.environment_object_id, inventory.binding_manifest_sha256,
        ):
            raise HarnessFailure("environment_validation", "functional_environment_manifest_mismatch")
        return approval
    try:
        environments = modal_sdk.Environment.objects.list()
    except Exception:
        raise HarnessFailure("environment_validation", "environment_lookup_failed") from None
    if not any(getattr(environment, "name", None) == name for environment in environments):
        raise HarnessFailure("environment_validation", "environment_not_found")
    return name


def runtime_identity(role: str, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Record only provider and region; never include the broader runtime env."""
    if role not in _ROLES:
        raise ValueError("unsupported_runtime_role")
    if environ is None:
        import os

        environ = os.environ
    return {
        "role": role,
        "provider": _safe_label(environ.get("MODAL_CLOUD_PROVIDER")),
        "region": _safe_label(environ.get("MODAL_REGION")),
    }


def connectivity_report(
    role: str,
    *,
    environ: Mapping[str, str] | None = None,
    redis_probe: Callable[[], object],
    s3_probe: Callable[[], object],
) -> dict[str, object]:
    """Return bounded reachability statuses without exception/endpoint text."""
    identity = runtime_identity(role, environ)
    checks: dict[str, str] = {}
    for name, probe in (("redis", redis_probe), ("s3", s3_probe)):
        try:
            checks[name] = "reachable" if probe() else "unreachable"
        except Exception:
            checks[name] = "unreachable"
    failed = [name for name, result in checks.items() if result != "reachable"]
    return {
        "status": "failed" if failed else "passed",
        "identity": identity,
        "checks": checks,
        "failure_code": f"{role}_{failed[0]}_unreachable" if failed else None,
    }


class HarnessFailure(RuntimeError):
    """A fixed-code exception which cannot retain client exception contents."""

    def __init__(self, stage: str, failure_code: str, *, error_class: str | None = None):
        self.stage = _safe_label(stage)
        self.failure_code = _safe_label(failure_code)
        self.error_class = _safe_label(error_class) if error_class else None
        super().__init__(self.failure_code)


def terminal_failure_report(
    stage: str,
    failure_code: str,
    *,
    identity: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Build a local-only failure record with a bounded stage and failure code."""
    report: dict[str, object] = {
        "status": "failed",
        "stage": _safe_label(stage),
        "failure_code": _safe_label(failure_code),
    }
    if identity is not None:
        role = identity.get("role", "unknown")
        report["identity"] = {
            "role": role if role in _ROLES else "unknown",
            "provider": _safe_label(identity.get("provider")),
            "region": _safe_label(identity.get("region")),
        }
    return report


def require_preflight(report: Mapping[str, object]) -> None:
    """Refuse to continue to the compile submit unless both dependencies pass."""
    if report.get("status") == "passed":
        return
    code = report.get("failure_code")
    identity = report.get("identity")
    role = identity.get("role") if isinstance(identity, Mapping) else "runtime"
    raise HarnessFailure("connectivity_preflight", _safe_label(code or f"{role}_preflight_failed"))


def require_compatible_placement(
    reports: Sequence[Mapping[str, object]], *, expected_region: str,
) -> None:
    """Require observable same-provider placement before the synthetic compile."""
    identities = [report.get("identity") for report in reports]
    if len(identities) < 3 or not all(isinstance(item, Mapping) for item in identities):
        raise HarnessFailure("placement_preflight", "runtime_identity_missing")
    providers = {item.get("provider") for item in identities if isinstance(item, Mapping)}
    regions = {item.get("region") for item in identities if isinstance(item, Mapping)}
    if "unknown" in providers or len(providers) != 1:
        raise HarnessFailure("placement_preflight", "runtime_provider_mismatch")
    if regions != {expected_region}:
        raise HarnessFailure("placement_preflight", "runtime_region_mismatch")


def require_worker_placement(
    identity: Mapping[str, str], expected: Mapping[str, str] | None,
) -> None:
    """Enforce the API's preflight placement on the actual compile worker."""
    if not isinstance(expected, Mapping):
        raise HarnessFailure("worker_placement", "expected_placement_missing")
    provider = _safe_label(expected.get("provider"))
    region = _safe_label(expected.get("region"))
    if provider == "unknown" or region == "unknown":
        raise HarnessFailure("worker_placement", "expected_placement_missing")
    if identity.get("provider") != provider:
        raise HarnessFailure("worker_placement", "worker_provider_mismatch")
    if identity.get("region") != region:
        raise HarnessFailure("worker_placement", "worker_region_mismatch")


def function_runtime_environment(
    address: str, renderer_image_id: str, renderer_assets_fingerprint: str,
    *, renderer_mode: str = "boundary",
    functional_environment_approval: FunctionalAcceptanceEnvironmentApproval | None = None,
) -> dict[str, str]:
    """Build app settings without overriding Modal-owned runtime variables."""
    if renderer_mode not in {"boundary", "functional-only"}:
        raise ValueError("unsupported renderer acceptance mode")
    approval = functional_environment_approval
    if not isinstance(approval, FunctionalAcceptanceEnvironmentApproval):
        raise HarnessFailure("arguments", "functional_environment_approval_required")
    try:
        validate_nonproduction_environment_name(approval.name)
    except HarnessFailure:
        raise HarnessFailure("arguments", "functional_environment_approval_required") from None
    if not is_trusted_functional_acceptance_environment(
        approval.name, approval.environment_object_id, approval.binding_manifest_sha256,
    ):
        raise HarnessFailure("arguments", "functional_environment_approval_required")
    environment = {
        "ENVIRONMENT": "test", "DEPLOY_TARGET": "modal",
        # The hold is lifted only after exact source-reviewed Environment identity
        # and binding-manifest approval, for temporary test Functions in either mode.
        "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "false",
        "BILLING_MODE": "disabled", "DODO_MODE": "test",
        "OPENAI_API_KEY": "", "RESEND_API_KEY": "",
        "PYTHONPATH": "/backend:/pkg", "NO_PROXY": address + ",localhost,127.0.0.1",
        "MODAL_ENGINE_VM_IMAGE_ID": renderer_image_id,
        "MODAL_ENGINE_VM_ASSETS_FINGERPRINT": renderer_assets_fingerprint,
    }
    if renderer_mode == "boundary":
        environment["MODAL_ENGINE_VM_CERTIFIED"] = "true"
    else:
        # This opt-in is recognized only by the test-only backend gate. It is
        # intentionally distinct from the operator's production certification.
        # Empty also overrides a stale assertion baked into the test image.
        environment["MODAL_ENGINE_VM_CERTIFIED"] = ""
        environment["MODAL_ENGINE_VM_FUNCTIONAL_ONLY_ACCEPTANCE"] = "true"
        environment["MODAL_ENGINE_VM_FUNCTIONAL_ONLY_ENVIRONMENT_ID"] = approval.environment_object_id
        environment["MODAL_ENGINE_VM_FUNCTIONAL_ONLY_BINDING_MANIFEST_SHA256"] = (
            approval.binding_manifest_sha256
        )
    return environment


def _probe_redis(redis_url: str) -> bool:
    import redis

    client = redis.Redis.from_url(redis_url, socket_connect_timeout=3, socket_timeout=3)
    try:
        return client.ping() is True
    finally:
        client.close()


def _probe_s3(endpoint: str, bucket: str, access_key: str, secret_key: str) -> bool:
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=Config(connect_timeout=3, read_timeout=3, retries={"max_attempts": 0}),
    )
    client.head_bucket(Bucket=bucket)
    return True


def _runtime_preflight(role: str) -> dict[str, object]:
    import os

    return connectivity_report(
        role,
        environ=os.environ,
        redis_probe=lambda: (
            _probe_redis(os.environ["REDIS_URL"])
            and _probe_redis(os.environ["REDIS_CACHE_URL"])
        ),
        s3_probe=lambda: _probe_s3(
            os.environ["MINIO_ENDPOINT"], os.environ["MINIO_BUCKET"],
            os.environ["MINIO_ACCESS_KEY"], os.environ["MINIO_SECRET_KEY"],
        ),
    )


def run_services(
    ready_queue: Any,
    stop_queue: Any,
    db_password: str,
    redis_password: str,
    s3_access_key: str,
    s3_secret_key: str,
    bucket: str,
) -> None:
    """Run only disposable loopback PostgreSQL, Redis, and Moto S3 services."""
    import os
    import subprocess as service_subprocess

    from moto.server import ThreadedMotoServer

    moto = None

    def command(args: list[str], timeout: int = 25) -> None:
        result = service_subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise HarnessFailure("service_startup", "disposable_service_start_failed")

    try:
        with open("/etc/postgresql/15/main/postgresql.conf", "a", encoding="utf-8") as handle:
            handle.write("\nlisten_addresses = '*'\n")
        with open("/etc/postgresql/15/main/pg_hba.conf", "a", encoding="utf-8") as handle:
            handle.write("\nhost all all fdaa::/16 scram-sha-256\n")
        command(["pg_ctlcluster", "15", "main", "start"], timeout=55)
        command([
            "runuser", "-u", "postgres", "--", "psql", "-v", "ON_ERROR_STOP=1",
            "-c", "CREATE ROLE root LOGIN SUPERUSER PASSWORD '" + db_password + "'",
        ])
        command(["runuser", "-u", "postgres", "--", "createdb", "-O", "root", "latexy_test"])
        command([
            "redis-server", "--port", "6380", "--bind", "::", "127.0.0.1",
            "--protected-mode", "yes", "--requirepass", redis_password, "--daemonize", "yes",
        ])
        moto = ThreadedMotoServer(ip_address="::", port=9000)
        moto.start()
        import boto3

        s3 = boto3.client(
            "s3", endpoint_url="http://[::1]:9000", aws_access_key_id=s3_access_key,
            aws_secret_access_key=s3_secret_key, region_name="us-east-1",
        )
        s3.create_bucket(Bucket=bucket)
        address = socket.getaddrinfo("i6pn.modal.local", None, socket.AF_INET6)[0][4][0]
        service_report = connectivity_report(
            "service",
            environ=os.environ,
            redis_probe=lambda: (
                _probe_redis("redis://:" + redis_password + "@127.0.0.1:6380/0")
                and _probe_redis("redis://:" + redis_password + "@127.0.0.1:6380/1")
            ),
            s3_probe=lambda: _probe_s3(
                "http://[::1]:9000", bucket, s3_access_key, s3_secret_key,
            ),
        )
        ready_queue.put({**service_report, "address": address})
        if service_report["status"] == "passed":
            stop_queue.get(timeout=500)
    except HarnessFailure as failure:
        ready_queue.put(terminal_failure_report(failure.stage, failure.failure_code,
                                                identity=runtime_identity("service")))
    except Exception:
        ready_queue.put(terminal_failure_report("service_startup", "disposable_service_start_failed",
                                                identity=runtime_identity("service")))
    finally:
        _stop_disposable_services(moto, redis_password, runner=service_subprocess.run)


def _stop_disposable_services(
    moto: Any, redis_password: str, *, runner: Callable[..., Any],
) -> None:
    """Attempt every service teardown and fail the Function if any stop fails."""
    failures = []
    if moto is not None:
        try:
            moto.stop()
        except Exception:
            failures.append("moto_stop_failed")

    commands = (
        (
            ["redis-cli", "-p", "6380", "-a", redis_password, "shutdown", "nosave"],
            10,
            "redis_shutdown_failed",
        ),
        (["pg_ctlcluster", "15", "main", "stop"], 25, "postgres_stop_failed"),
    )
    for args, timeout, failure_code in commands:
        try:
            result = runner(args, capture_output=True, timeout=timeout)
            if result.returncode != 0:
                failures.append(failure_code)
        except Exception:
            failures.append(failure_code)

    if failures:
        raise HarnessFailure("service_shutdown", failures[0])


def _store_worker_identity(identity: Mapping[str, str]) -> None:
    """Retain the actual spawned worker identity only in disposable test Redis."""
    import os

    import redis

    run_id = os.environ.get("HARNESS_RUN_ID")
    if not run_id:
        return
    client = redis.Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=3, socket_timeout=3)
    try:
        client.set("latexy-harness:runtime:" + run_id, json.dumps(dict(identity)), ex=1800)
    finally:
        client.close()


def _placement_key(run_id: str) -> str:
    return "latexy-harness:expected:" + run_id


def _worker_failure_key(run_id: str) -> str:
    return "latexy-harness:failure:" + run_id


def _store_expected_placement(run_id: str, identity: Mapping[str, str]) -> None:
    """Store only the checked provider/region in disposable test Redis."""
    import os

    import redis

    provider = _safe_label(identity.get("provider"))
    region = _safe_label(identity.get("region"))
    if provider == "unknown" or region == "unknown":
        raise HarnessFailure("placement_preflight", "runtime_identity_missing")
    client = redis.Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=3, socket_timeout=3)
    try:
        stored = client.set(_placement_key(run_id), json.dumps({
            "provider": provider, "region": region,
        }), ex=1800)
        if not stored:
            raise HarnessFailure("placement_preflight", "expected_placement_store_failed")
    except HarnessFailure:
        raise
    except Exception:
        raise HarnessFailure("placement_preflight", "expected_placement_store_failed") from None
    finally:
        client.close()


def _read_expected_placement(run_id: str) -> dict[str, str] | None:
    import os

    import redis

    client = redis.Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=3, socket_timeout=3)
    try:
        value = client.get(_placement_key(run_id))
    except Exception:
        raise HarnessFailure("worker_placement", "expected_placement_unavailable") from None
    finally:
        client.close()
    if value is None:
        return None
    try:
        candidate = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(candidate, dict):
        return None
    return {
        "provider": _safe_label(candidate.get("provider")),
        "region": _safe_label(candidate.get("region")),
    }


def _record_worker_failure(run_id: str, stage: str, failure_code: str) -> None:
    import os

    import redis

    client = redis.Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=3, socket_timeout=3)
    try:
        client.set(_worker_failure_key(run_id), json.dumps({
            "stage": _safe_label(stage), "failure_code": _safe_label(failure_code),
        }), ex=1800)
    finally:
        client.close()


def _read_worker_failure(run_id: str) -> dict[str, str] | None:
    import os

    import redis

    client = redis.Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=3, socket_timeout=3)
    try:
        value = client.get(_worker_failure_key(run_id))
    except Exception:
        raise HarnessFailure("worker_failure", "worker_failure_unavailable") from None
    finally:
        client.close()
    if value is None:
        return None
    try:
        candidate = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(candidate, dict):
        return None
    stage = _safe_label(candidate.get("stage"))
    failure_code = _safe_label(candidate.get("failure_code"))
    if stage == "unknown" or failure_code == "unknown":
        return None
    return {"stage": stage, "failure_code": failure_code}


def _cleanup_private_service(stop_queue: Any, service_call: Any, report: dict[str, object]) -> None:
    """Signal and join disposable services before their Modal scope exits."""
    if service_call is None:
        return
    try:
        stop_queue.put("stop")
        report["service_stop_signal_sent"] = True
    except Exception:
        report["service_stop_signal_sent"] = False
    try:
        service_call.get(timeout=45)
        report["private_services_stopped"] = True
    except Exception:
        report["private_services_stopped"] = False


@contextmanager
def _private_service_lifetime(stop_queue: Any, service_call: Any, report: dict[str, object]):
    """Guarantee service cleanup while the queue and app run contexts are open."""
    try:
        yield
    finally:
        _cleanup_private_service(stop_queue, service_call, report)


def _ephemeral_queue(modal_sdk: Any, environment_name: str) -> Any:
    """Always scope ephemeral control queues to the selected test Environment."""
    return modal_sdk.Queue.ephemeral(environment_name=environment_name)


def _deploy_dispatch_app(app: Any, environment: str, state: dict[str, bool]) -> None:
    """Record an attempt before deploy, so partial deployments are stoppable."""
    state["attempted"] = True
    app.deploy(environment_name=environment)


def _stop_dispatch_app(
    app_name: str, environment: str, *, attempted: bool,
    modal_cli: str | None = None, runner: Callable[..., Any] = subprocess.run,
) -> bool | None:
    """Best-effort bounded stop; return None when deployment was never attempted."""
    if not attempted:
        return None
    try:
        executable = modal_cli if modal_cli is not None else shutil.which("modal")
        if not executable:
            return False
        result = runner(
            [executable, "app", "stop", app_name, "--env", environment, "--yes"],
            capture_output=True, text=True, timeout=35,
        )
    except Exception:
        return False
    return result.returncode == 0


def _finalize_cleanup_status(report: dict[str, object]) -> None:
    """A passing job stays passing only if every teardown step succeeded."""
    if report.get("status") != "passed":
        return
    for key, failure_code in (
        ("service_stop_signal_sent", "service_stop_signal_failed"),
        ("private_services_stopped", "private_services_stop_failed"),
        ("dispatch_app_stopped", "dispatch_app_stop_failed"),
    ):
        if report.get(key) is not True:
            report.update({"status": "failed", "stage": "cleanup", "failure_code": failure_code})
            return


def _public_summary(report: Mapping[str, object]) -> dict[str, object]:
    status = _safe_label(report.get("status"))
    failure_code = report.get("failure_code")
    return {
        "status": status,
        **({"failure_code": _safe_label(failure_code)} if failure_code else {}),
    }


def _acceptance_exit_code(report: Mapping[str, object]) -> int:
    return 0 if report.get("status") == "passed" else 1


def run_latex_task(payload: dict[str, Any]) -> Any:
    """Preflight the exact worker invocation before entering the compile task."""
    import os

    report = _runtime_preflight("worker")
    if payload.get("__harness_preflight_only") is True:
        return report
    checks = report.get("checks")
    run_id = os.environ.get("HARNESS_RUN_ID")
    if isinstance(checks, Mapping) and checks.get("redis") == "reachable":
        _store_worker_identity(report["identity"])
    try:
        require_preflight(report)
        if not run_id:
            raise HarnessFailure("worker_placement", "expected_placement_missing")
        expected = _read_expected_placement(run_id)
        require_worker_placement(report["identity"], expected)
    except HarnessFailure as failure:
        if run_id and isinstance(checks, Mapping) and checks.get("redis") == "reachable":
            try:
                _record_worker_failure(run_id, failure.stage, failure.failure_code)
            except Exception:
                pass
        raise

    from app.core.tracing import worker_trace
    from modal_app import _init_worker_redis

    task_payload = dict(payload)
    with worker_trace(task_payload.pop("_trace_context", None)):
        _init_worker_redis()
        from app.workers.latex_worker import compile_latex_task

        outcome = compile_latex_task.apply(kwargs=task_payload, throw=False)
        value = outcome.result
        if not isinstance(value, dict) or value.get("success") is not True:
            raise HarnessFailure("worker_compile", "worker_compile_failed")


def _read_actual_worker_identity(run_id: str) -> dict[str, str] | None:
    import os

    import redis

    client = redis.Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=3, socket_timeout=3)
    try:
        value = client.get("latexy-harness:runtime:" + run_id)
    finally:
        client.close()
    if value is None:
        return None
    try:
        candidate = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(candidate, dict) or candidate.get("role") != "worker":
        return None
    return runtime_identity("worker", {
        "MODAL_CLOUD_PROVIDER": str(candidate.get("provider", "")),
        "MODAL_REGION": str(candidate.get("region", "")),
    })


def api_probe(app_name: str, service_preflight: dict[str, object],
              expected_region: str, run_id: str, environment_name: str) -> dict[str, object]:
    """Preflight caller, then test one synthetic API submission and acceptance."""
    import io
    import os
    import subprocess as probe_subprocess
    import sys

    import boto3
    import httpx
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    caller_preflight = _runtime_preflight("caller")
    report: dict[str, object] = {
        "status": "failed",
        "stage": "connectivity_preflight",
        "runtimes": {
            "service": service_preflight.get("identity"),
            "caller": caller_preflight.get("identity"),
        },
        "connectivity": {
            "service": service_preflight.get("checks"),
            "caller": caller_preflight.get("checks"),
        },
    }
    current_identity = caller_preflight.get("identity")
    try:
        require_preflight(service_preflight)
        require_preflight(caller_preflight)
        report["stage"] = "migration"
        migrated = probe_subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd="/backend", capture_output=True, text=True, timeout=180,
        )
        if migrated.returncode:
            raise HarnessFailure("migration", "migration_failed")

        s3 = boto3.client(
            "s3", endpoint_url=os.environ["MINIO_ENDPOINT"],
            aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
            aws_secret_access_key=os.environ["MINIO_SECRET_KEY"], region_name="us-east-1",
        )
        sync_db_url = os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg2")
        engine = create_engine(sync_db_url)
        from app.database.models import Resume, User

        user_id, resume_id = str(uuid4()), str(uuid4())
        source = r"\documentclass{article}\begin{document}Synthetic Latexy acceptance proof.\end{document}"
        token = os.environ["SYNTHETIC_AUTH_TOKEN"]
        with engine.begin() as connection:
            connection.execute(text(
                'CREATE TABLE IF NOT EXISTS session (id VARCHAR(255) PRIMARY KEY, '
                '"userId" VARCHAR(255) NOT NULL, "expiresAt" TIMESTAMPTZ NOT NULL, '
                'token VARCHAR(255) NOT NULL UNIQUE)'
            ))
        with Session(engine) as session:
            session.add(User(id=user_id, email="synthetic_" + user_id.replace("-", "") + "@example.test",
                             name="Synthetic User", email_verified=True, subscription_plan="free",
                             subscription_status="active"))
            session.add(Resume(id=resume_id, user_id=user_id, title="Synthetic Resume", latex_content=source))
            session.commit()
        with engine.begin() as connection:
            connection.execute(text(
                'INSERT INTO session (id, "userId", "expiresAt", token) '
                'VALUES (:id,:uid,:exp,:tok)'
            ), {"id": str(uuid4()), "uid": user_id,
                "exp": datetime.now(timezone.utc) + timedelta(days=1), "tok": token})
        headers = {"Authorization": "Bearer " + token}
        from app.core import modal_dispatch

        modal_dispatch._APP_NAME = app_name
        from app.main import app as api_app

        # This is the last network/placement check before the API route submits
        # the synthetic compile into the real named worker.
        report["stage"] = "worker_preflight"
        import modal

        worker_preflight = modal.Function.from_name(
            app_name, "run_latex_task", environment_name=environment_name
        ).remote({"__harness_preflight_only": True})
        report["runtimes"]["worker_preflight"] = worker_preflight.get("identity")
        report["connectivity"]["worker_preflight"] = worker_preflight.get("checks")
        reports = [service_preflight, caller_preflight, worker_preflight]
        require_preflight(worker_preflight)
        require_compatible_placement(reports, expected_region=expected_region)
        worker_identity = worker_preflight.get("identity")
        if not isinstance(worker_identity, Mapping):
            raise HarnessFailure("placement_preflight", "runtime_identity_missing")
        _store_expected_placement(run_id, worker_identity)

        async def request_flow() -> None:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app),
                                         base_url="http://localhost", timeout=60) as client:
                report["stage"] = "api_submit"
                submission = await client.post("/jobs/submit", headers=headers, json={
                    "job_type": "latex_compilation", "latex_content": source,
                    "compiler": "lualatex", "metadata": {"resume_id": resume_id},
                })
                report["submit_http"] = submission.status_code
                if submission.status_code != 200:
                    raise HarnessFailure("api_submit", "synthetic_submit_rejected")
                job_id = submission.json()["job_id"]
                report["stage"] = "await_worker_finalization"
                row = final = None
                for _ in range(120):
                    with engine.connect() as connection:
                        row = connection.execute(text(
                            "SELECT status,artifact_accepted,pdf_path FROM compilations WHERE job_id=:job"
                        ), {"job": job_id}).first()
                        final = connection.execute(text(
                            "SELECT state,failure_code FROM job_finalizations WHERE job_id=:job"
                        ), {"job": job_id}).first()
                    if final is not None and final.state in {"completed", "failed", "cancelled"}:
                        break
                    worker_failure = _read_worker_failure(run_id)
                    if worker_failure is not None:
                        raise HarnessFailure(worker_failure["stage"], worker_failure["failure_code"])
                    await asyncio.sleep(2)
                report["worker_actual"] = _read_actual_worker_identity(run_id)
                if row is None or final is None or final.state not in {"completed", "failed", "cancelled"}:
                    raise HarnessFailure("await_worker_finalization", "job_not_terminal_before_deadline")
                if final.state != "completed" or row.status != "completed" or row.artifact_accepted is not True or not row.pdf_path:
                    raise HarnessFailure("worker_finalization", "worker_reported_terminal_failure")

                report["stage"] = "accepted_artifact"
                accepted_key = row.pdf_path
                accepted_pdf = s3.get_object(Bucket=os.environ["MINIO_BUCKET"], Key=accepted_key)["Body"].read()
                if not accepted_pdf.startswith(b"%PDF-"):
                    raise HarnessFailure("accepted_artifact", "stored_pdf_invalid")
                latest = await client.get(f"/resumes/{resume_id}/latest-accepted-artifact", headers=headers)
                report["latest_http"] = latest.status_code
                if latest.status_code != 200 or not latest.json().get("artifact"):
                    raise HarnessFailure("accepted_artifact", "latest_artifact_missing")
                artifact_id = latest.json()["artifact"]["artifact_id"]
                preview = await client.get(f"/download/{job_id}/preview/{artifact_id}", headers=headers)
                report["preview_http"] = preview.status_code
                report["preview_matches_accepted_pdf"] = preview.status_code == 200 and preview.content == accepted_pdf
                if not report["preview_matches_accepted_pdf"]:
                    raise HarnessFailure("accepted_artifact", "preview_pdf_mismatch")

                report["stage"] = "candidate_visibility"
                candidate_key = "synthetic/candidate.pdf"
                s3.put_object(Bucket=os.environ["MINIO_BUCKET"], Key=candidate_key,
                              Body=b"%PDF-1.7\nUNACCEPTED-CANDIDATE\n")
                with engine.begin() as connection:
                    connection.execute(text(
                        "INSERT INTO compilations (id,user_id,resume_id,job_id,status,pdf_path,"
                        "artifact_branch,artifact_accepted,created_at) VALUES (:id,:uid,:rid,:jid,"
                        "'completed',:path,'candidate',false,:created)"
                    ), {"id": str(uuid4()), "uid": user_id, "rid": resume_id,
                        "jid": str(uuid4()), "path": candidate_key,
                        "created": datetime.now(timezone.utc) + timedelta(seconds=10)})
                share = await client.post(f"/resumes/{resume_id}/share", headers=headers, json={})
                if share.status_code != 200:
                    raise HarnessFailure("candidate_visibility", "share_creation_failed")
                viewed = await client.get("/share/" + share.json()["share_token"])
                share_path = urlparse(viewed.json().get("pdf_url") or "").path if viewed.status_code == 200 else ""
                report["share_selects_accepted"] = (
                    viewed.status_code == 200 and accepted_key in share_path and candidate_key not in share_path
                )
                bulk = await client.get("/resumes/export/bulk?format=pdf", headers=headers)
                report["bulk_http"] = bulk.status_code
                if bulk.status_code != 200:
                    raise HarnessFailure("candidate_visibility", "bulk_export_failed")
                with zipfile.ZipFile(io.BytesIO(bulk.content)) as archive:
                    pdf_bytes = [archive.read(name) for name in archive.namelist() if name.endswith(".pdf")]
                report["bulk_selects_accepted"] = len(pdf_bytes) == 1 and pdf_bytes[0] == accepted_pdf
                if not report["share_selects_accepted"] or not report["bulk_selects_accepted"]:
                    raise HarnessFailure("candidate_visibility", "unaccepted_candidate_visible")

        asyncio.run(request_flow())
        report["status"] = "passed"
        report["stage"] = "complete"
    except HarnessFailure as failure:
        report.update(terminal_failure_report(failure.stage, failure.failure_code,
                                             identity=current_identity if isinstance(current_identity, Mapping) else None))
    except Exception:
        report.update(terminal_failure_report(
            str(report.get("stage", "unknown")), "unexpected_harness_error",
            identity=current_identity if isinstance(current_identity, Mapping) else None,
        ))
    return report


def _private_report_path(path_value: str) -> Path:
    path = Path(path_value).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    try:
        path.relative_to(repo_root)
    except ValueError:
        return path
    raise HarnessFailure("arguments", "private_report_must_be_outside_repository")


def _set_renderer_report_scope(report: dict[str, object], renderer_mode: str) -> None:
    if renderer_mode not in {"boundary", "functional-only"}:
        raise HarnessFailure("arguments", "invalid_renderer_mode")
    report["renderer_mode"] = renderer_mode
    report["renderer_boundary_probe"] = "not_run" if renderer_mode == "functional-only" else "enabled"
    report["production_certification_claimed"] = False


def _acceptance_report(renderer_mode: str) -> dict[str, object]:
    report = terminal_failure_report("initialize", "acceptance_not_started")
    _set_renderer_report_scope(report, renderer_mode)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-id", required=True, help="Approved nonproduction API/LaTeX test image ID")
    parser.add_argument("--services-image-id", required=True,
                        help="Nonproduction image with PostgreSQL 15, Redis, Moto, and boto3")
    parser.add_argument("--renderer-image-id", required=True, help="Operator-reviewed bare renderer image ID")
    parser.add_argument("--renderer-assets-fingerprint", required=True,
                        help="Operator-reviewed renderer asset fingerprint")
    parser.add_argument(
        "--renderer-mode", choices=("boundary", "functional-only"), default="boundary",
        help="boundary runs the security probe; functional-only runs API/worker/PDF checks only",
    )
    parser.add_argument("--region", default="us-east", help="Modal container region (default: us-east)")
    parser.add_argument(
        "--environment-name", required=True,
        help=("Existing nonproduction Modal Environment; functional-only currently requires a reviewed "
              "name/object-ID/empty-binding-manifest approval (none is configured)"),
    )
    parser.add_argument(
        "--private-report", required=True,
        help="Report path outside this checkout; access permissions are managed by the operator",
    )
    parser.add_argument("--confirm-isolated-modal-run", action="store_true",
                        help="Acknowledge that this provisions paid, disposable Modal resources")
    parser.add_argument("--confirm-nonproduction-environment", action="store_true",
                        help="Confirm the named existing Modal Environment is nonproduction")
    parser.add_argument("--confirm-nonproduction-renderer-binding", action="store_true",
                        help="Acknowledge the renderer assertion is confined to this test app/environment")
    parser.add_argument("--confirm-default-egress", action="store_true",
                        help="Acknowledge API/worker/service Functions use Modal's default outbound egress")
    parser.add_argument("--confirm-renderer-boundary-probe", action="store_true",
                        help="Acknowledge the renderer adapter probes /proc/1 and outbound network denial")
    parser.add_argument("--confirm-functional-renderer-binding", action="store_true",
                        help="Bind this renderer tuple for nonproduction functional testing only; does not certify it")
    args = parser.parse_args(argv)
    try:
        private_report = _private_report_path(args.private_report)
        if not _IMAGE_ID.fullmatch(args.image_id):
            raise HarnessFailure("arguments", "invalid_image_id")
        if not _IMAGE_ID.fullmatch(args.services_image_id):
            raise HarnessFailure("arguments", "invalid_services_image_id")
        if not _IMAGE_ID.fullmatch(args.renderer_image_id):
            raise HarnessFailure("arguments", "invalid_renderer_image_id")
        if not re.fullmatch(r"[0-9a-f]{64}", args.renderer_assets_fingerprint):
            raise HarnessFailure("arguments", "invalid_renderer_assets_fingerprint")
        if not _LABEL.fullmatch(args.region) or args.region == "unknown":
            raise HarnessFailure("arguments", "invalid_region")
        if args.renderer_mode == "functional-only":
            validate_functional_acceptance_environment_name(args.environment_name)
        else:
            validate_nonproduction_environment_name(args.environment_name)
        if not args.confirm_isolated_modal_run:
            raise HarnessFailure("arguments", "isolated_modal_run_confirmation_required")
        if not args.confirm_nonproduction_environment:
            raise HarnessFailure("arguments", "nonproduction_environment_confirmation_required")
        if args.renderer_mode == "functional-only":
            if args.confirm_renderer_boundary_probe:
                raise HarnessFailure("arguments", "boundary_probe_confirmation_not_allowed_in_functional_mode")
            if not args.confirm_default_egress:
                raise HarnessFailure("arguments", "default_function_egress_confirmation_required")
            if not args.confirm_functional_renderer_binding:
                raise HarnessFailure("arguments", "functional_renderer_binding_confirmation_required")
        else:
            if not args.confirm_nonproduction_renderer_binding:
                raise HarnessFailure("arguments", "nonproduction_renderer_binding_confirmation_required")
            if not args.confirm_default_egress:
                raise HarnessFailure("arguments", "default_function_egress_confirmation_required")
            if args.confirm_functional_renderer_binding:
                raise HarnessFailure("arguments", "functional_renderer_binding_not_allowed_in_boundary_mode")
            if not args.confirm_renderer_boundary_probe:
                raise HarnessFailure("arguments", "renderer_boundary_probe_confirmation_required")
    except HarnessFailure as failure:
        print(json.dumps({"status": "blocked", "failure_code": failure.failure_code}, sort_keys=True))
        return 2

    try:
        import modal
    except Exception:
        print(json.dumps({"status": "blocked", "failure_code": "modal_sdk_unavailable"}, sort_keys=True))
        return 2

    try:
        environment = validate_existing_nonproduction_environment(
            modal, args.environment_name, functional_only=True,
        )
    except HarnessFailure as failure:
        print(json.dumps({"status": "blocked", "failure_code": failure.failure_code}, sort_keys=True))
        return 2

    environment_approval = (
        environment if isinstance(environment, FunctionalAcceptanceEnvironmentApproval) else None
    )
    environment_name = environment_approval.name if environment_approval else environment

    run_id = uuid4().hex
    suffix = run_id[:10]
    service_app_name = "latexy-harness-services-" + suffix
    dispatch_app_name = "latexy-harness-dispatch-" + suffix
    bucket = "latexy-harness-" + suffix
    image = modal.Image.from_id(args.image_id)
    services_image = modal.Image.from_id(args.services_image_id)
    service_app = modal.App(service_app_name)

    db_password = secrets.token_urlsafe(32)
    redis_password = secrets.token_urlsafe(32)
    s3_access_key = secrets.token_urlsafe(24)
    s3_secret_key = secrets.token_urlsafe(40)
    runtime_secrets = {
        "MINIO_ACCESS_KEY": s3_access_key,
        "MINIO_SECRET_KEY": s3_secret_key,
        "BETTER_AUTH_SECRET": secrets.token_urlsafe(40),
        "JWT_SECRET_KEY": secrets.token_urlsafe(40),
        "SYNTHETIC_AUTH_TOKEN": secrets.token_urlsafe(36),
    }
    service_function = service_app.function(
        image=services_image, i6pn=True, region=args.region, secrets=[], volumes={},
        timeout=550, memory=(2048, 2048), max_containers=1, single_use_containers=True,
    )(run_services)
    report = _acceptance_report(args.renderer_mode)
    dispatch_deploy_state = {"attempted": False}
    service_call = None
    try:
        with _ephemeral_queue(modal, environment_name) as ready_queue, _ephemeral_queue(
            modal, environment_name,
        ) as stop_queue:
            with service_app.run(environment_name=environment_name):
                service_call = service_function.spawn(
                    ready_queue, stop_queue, db_password, redis_password,
                    s3_access_key, s3_secret_key, bucket,
                )
                with _private_service_lifetime(stop_queue, service_call, report):
                    service_preflight = ready_queue.get(timeout=100)
                    if service_preflight.get("status") != "passed":
                        raise HarnessFailure(
                            "service_preflight",
                            _safe_label(service_preflight.get("failure_code") or "service_preflight_failed"),
                        )
                    address = service_preflight["address"]
                    host = "[" + address + "]"
                    runtime_secrets.update({
                        "DATABASE_URL": "postgresql+asyncpg://root:" + db_password + "@" + host + ":5432/latexy_test",
                        "REDIS_URL": "redis://:" + redis_password + "@" + host + ":6380/0",
                        "REDIS_CACHE_URL": "redis://:" + redis_password + "@" + host + ":6380/1",
                        "REDIS_PASSWORD": redis_password,
                        "CELERY_BROKER_URL": "redis://:" + redis_password + "@" + host + ":6380/0",
                        "CELERY_RESULT_BACKEND": "redis://:" + redis_password + "@" + host + ":6380/0",
                        "MINIO_ENDPOINT": "http://" + host + ":9000",
                        "MINIO_BUCKET": bucket,
                        "HARNESS_RUN_ID": run_id,
                    })
                    runtime_env = function_runtime_environment(
                        address, args.renderer_image_id, args.renderer_assets_fingerprint,
                        renderer_mode=args.renderer_mode,
                        functional_environment_approval=environment_approval,
                    )
                    dispatch_app = modal.App(dispatch_app_name)
                    secret = modal.Secret.from_dict(runtime_secrets)
                    _worker_function = dispatch_app.function(
                        image=image, env=runtime_env, secrets=[secret], volumes={},
                        i6pn=True, region=args.region, timeout=330, max_containers=1,
                        single_use_containers=True,
                    )(run_latex_task)
                    api_function = dispatch_app.function(
                        image=image, env=runtime_env, secrets=[secret], volumes={},
                        i6pn=True, region=args.region, timeout=480, max_containers=1,
                        single_use_containers=True,
                    )(api_probe)
                    _deploy_dispatch_app(dispatch_app, environment_name, dispatch_deploy_state)

                    report.update(api_function.remote(
                        dispatch_app_name,
                        {key: service_preflight[key] for key in ("status", "identity", "checks", "failure_code")},
                        args.region,
                        run_id,
                        environment_name,
                    ))
    except HarnessFailure as failure:
        report.update(terminal_failure_report(failure.stage, failure.failure_code))
    except Exception:
        report.update(terminal_failure_report("modal_acceptance", "modal_or_harness_failure"))
    finally:
        stopped = _stop_dispatch_app(
            dispatch_app_name, environment_name, attempted=dispatch_deploy_state["attempted"],
        )
        if stopped is not None:
            report["dispatch_app_stopped"] = stopped
        _finalize_cleanup_status(report)

    _set_renderer_report_scope(report, args.renderer_mode)
    private_report.parent.mkdir(parents=True, exist_ok=True)
    private_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(_public_summary(report), sort_keys=True))
    return _acceptance_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
