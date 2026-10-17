"""Explicitly opt-in, isolated Modal API -> worker -> renderer acceptance run.

This script creates a unique nonproduction Modal app/environment and disposable
PostgreSQL, Redis, and Moto S3 services. It never looks up named production
Secrets, uses Volumes or public tunnels, or writes its private runtime report
inside the repository. Running it provisions paid infrastructure and requires
explicit confirmations for resource use, default function egress, the
nonproduction renderer binding, and the renderer boundary probe.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

_LABEL = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
_IMAGE_ID = re.compile(r"im-[A-Za-z0-9]{6,128}\Z")
_ROLES = frozenset({"service", "caller", "worker"})


def _safe_label(value: object) -> str:
    return value if isinstance(value, str) and _LABEL.fullmatch(value) else "unknown"


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

    def __init__(self, stage: str, failure_code: str):
        self.stage = _safe_label(stage)
        self.failure_code = _safe_label(failure_code)
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
        if moto is not None:
            moto.stop()
        service_subprocess.run(
            ["redis-cli", "-p", "6380", "-a", redis_password, "shutdown", "nosave"],
            capture_output=True, timeout=10,
        )
        service_subprocess.run(["pg_ctlcluster", "15", "main", "stop"], capture_output=True, timeout=25)


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


def run_latex_task(payload: dict[str, Any]) -> Any:
    """Preflight the exact worker invocation before entering the compile task."""
    report = _runtime_preflight("worker")
    if payload.get("__harness_preflight_only") is True:
        return report
    checks = report.get("checks")
    if isinstance(checks, Mapping) and checks.get("redis") == "reachable":
        _store_worker_identity(report["identity"])
    require_preflight(report)

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
              expected_region: str, run_id: str) -> dict[str, object]:
    """Preflight caller, then test one synthetic API submission and acceptance."""
    import asyncio
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
            app_name, "run_latex_task", environment_name=os.environ["MODAL_ENVIRONMENT"]
        ).remote({"__harness_preflight_only": True})
        report["runtimes"]["worker_preflight"] = worker_preflight.get("identity")
        report["connectivity"]["worker_preflight"] = worker_preflight.get("checks")
        reports = [service_preflight, caller_preflight, worker_preflight]
        require_preflight(worker_preflight)
        require_compatible_placement(reports, expected_region=expected_region)

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-id", required=True, help="Approved nonproduction API/LaTeX test image ID")
    parser.add_argument("--services-image-id", required=True,
                        help="Nonproduction image with PostgreSQL 15, Redis, Moto, and boto3")
    parser.add_argument("--renderer-image-id", required=True, help="Operator-reviewed bare renderer image ID")
    parser.add_argument("--renderer-assets-fingerprint", required=True,
                        help="Operator-reviewed renderer asset fingerprint")
    parser.add_argument("--region", default="us-east", help="Modal container region (default: us-east)")
    parser.add_argument("--private-report", required=True, help="Local report path outside this checkout")
    parser.add_argument("--confirm-isolated-modal-run", action="store_true",
                        help="Acknowledge that this provisions paid, disposable Modal resources")
    parser.add_argument("--confirm-nonproduction-renderer-binding", action="store_true",
                        help="Acknowledge the renderer assertion is confined to this test app/environment")
    parser.add_argument("--confirm-default-egress", action="store_true",
                        help="Acknowledge API/worker/service Functions use Modal's default outbound egress")
    parser.add_argument("--confirm-renderer-boundary-probe", action="store_true",
                        help="Acknowledge the renderer adapter probes /proc/1 and outbound network denial")
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
        if not args.confirm_isolated_modal_run:
            raise HarnessFailure("arguments", "isolated_modal_run_confirmation_required")
        if not args.confirm_nonproduction_renderer_binding:
            raise HarnessFailure("arguments", "nonproduction_renderer_binding_confirmation_required")
        if not args.confirm_default_egress:
            raise HarnessFailure("arguments", "default_function_egress_confirmation_required")
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

    run_id = uuid4().hex
    suffix = run_id[:10]
    environment = "latexy-harness-" + suffix
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
    report: dict[str, object] = terminal_failure_report("initialize", "acceptance_not_started")
    deployed = False
    service_call = None
    service_scope = None
    stop_queue = None
    ready_queue = None
    try:
        with modal.Queue.ephemeral() as ready_queue, modal.Queue.ephemeral() as stop_queue:
            service_scope = service_app.run(environment_name=environment)
            with service_scope:
                service_call = service_function.spawn(
                    ready_queue, stop_queue, db_password, redis_password,
                    s3_access_key, s3_secret_key, bucket,
                )
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
                runtime_env = {
                    "ENVIRONMENT": "test", "DEPLOY_TARGET": "modal", "MODAL_ENVIRONMENT": environment,
                    "BILLING_MODE": "disabled", "DODO_MODE": "test",
                    "OPENAI_API_KEY": "", "RESEND_API_KEY": "",
                    "PYTHONPATH": "/backend:/pkg", "NO_PROXY": address + ",localhost,127.0.0.1",
                    "MODAL_ENGINE_VM_CERTIFIED": "true",
                    "MODAL_ENGINE_VM_IMAGE_ID": args.renderer_image_id,
                    "MODAL_ENGINE_VM_ASSETS_FINGERPRINT": args.renderer_assets_fingerprint,
                }
                dispatch_app = modal.App(dispatch_app_name)
                secret = modal.Secret.from_dict(runtime_secrets)
                worker_function = dispatch_app.function(
                    image=image, env=runtime_env, secrets=[secret], volumes={},
                    i6pn=True, region=args.region, timeout=330, max_containers=1,
                    single_use_containers=True,
                )(run_latex_task)
                api_function = dispatch_app.function(
                    image=image, env=runtime_env, secrets=[secret], volumes={},
                    i6pn=True, region=args.region, timeout=480, max_containers=1,
                    single_use_containers=True,
                )(api_probe)
                dispatch_app.deploy(environment_name=environment)
                deployed = True

                report = api_function.remote(
                    dispatch_app_name,
                    {key: service_preflight[key] for key in ("status", "identity", "checks", "failure_code")},
                    args.region,
                    run_id,
                )
    except HarnessFailure as failure:
        report = terminal_failure_report(failure.stage, failure.failure_code)
    except Exception:
        report = terminal_failure_report("modal_acceptance", "modal_or_harness_failure")
    finally:
        if deployed:
            modal_cli = shutil.which("modal")
            if modal_cli:
                stopped = subprocess.run(
                    [modal_cli, "app", "stop", dispatch_app_name, "--env", environment, "--yes"],
                    capture_output=True, text=True, timeout=35,
                )
                report["dispatch_app_stopped"] = stopped.returncode == 0
            else:
                report["dispatch_app_stopped"] = False
        if stop_queue is not None:
            try:
                stop_queue.put("stop")
            except Exception:
                pass
        if service_call is not None:
            try:
                service_call.get(timeout=45)
                report["private_services_stopped"] = True
            except Exception:
                report["private_services_stopped"] = False

    private_report.parent.mkdir(parents=True, exist_ok=True)
    private_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = report.get("status", "failed")
    failure_code = report.get("failure_code")
    print(json.dumps({"status": status, **({"failure_code": failure_code} if failure_code else {})}, sort_keys=True))
    return 0 if status == "passed" and report.get("dispatch_app_stopped") is True and report.get("private_services_stopped") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
