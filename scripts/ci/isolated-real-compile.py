"""Bounded, opt-in candidate Linux functional proof using only owned resources.

This is not Modal certification or a timing SLO. Reuses Dockerfile.prod's exact
TeX assets/launcher, plus a CI-only hash-locked QA dependency layer. Runtime
containers have a fresh internal network, fresh data, no Docker socket, no beat,
no dotenv, no inherited credentials, and no provider/email/billing calls.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_KEYS = {"PATH", "LANG", "LC_ALL", "TERM", "CI", "PNPM_HOME", "COREPACK_HOME", "PLAYWRIGHT_BROWSERS_PATH"}
SERVICE_IMAGES = {
    "postgres": "pgvector/pgvector:pg16",
    "redis": "redis:7-alpine",
    "storage": "minio/minio:RELEASE.2025-04-22T22-12-26Z",
}


def clean_environment(home: Path) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key in RUNTIME_KEYS}
    environment.update(HOME=str(home), TMPDIR=str(home), NEXT_TELEMETRY_DISABLED="1", CI="1")
    return environment


def copy_candidate_context(root: Path, destination: Path) -> None:
    """An explicit source allowlist; no home/config/dotenv or dependency trees."""
    backend = root / "backend"
    destination.mkdir()
    allowed = ("app", "alembic", "scripts", "test", "requirements.lock", "requirements-dev.lock",
               "alembic.ini", "pytest.ini", "Dockerfile.prod")
    def ignore(directory, names):
        return [name for name in names if name.startswith(".") or name in {"__pycache__", "node_modules"}
                or name.endswith((".pyc", ".pem", ".key"))]
    for name in allowed:
        source = backend / name
        if source.is_symlink():
            raise RuntimeError("Candidate source context contains a symlink")
        if source.is_dir():
            # Refuse symlinks rather than follow one into operator files.
            if any(path.is_symlink() for path in source.rglob("*")):
                raise RuntimeError("Candidate source context contains a symlink")
            shutil.copytree(source, destination / name, ignore=ignore)
        else:
            shutil.copyfile(source, destination / name)
    dockerfile = destination / "Dockerfile.prod"
    dockerfile.write_text(dockerfile.read_text() + "\n"
        "# CI-only dependency layer; the production asset/launcher graph is unchanged.\n"
        "FROM production AS isolated-ci\nUSER root\n"
        "RUN /opt/venv/bin/pip install --no-cache-dir --require-hashes -r /app/requirements-dev.lock\n"
        "USER latexy\n", encoding="utf-8")
    (destination / "scripts/ci").mkdir(exist_ok=True)
    shutil.copyfile(root / "scripts/ci/local-job-smoke.py", destination / "scripts/ci/local-job-smoke.py")


def require_junit_cases(path: Path, expected: int) -> int:
    cases = list(ET.parse(path).getroot().iter("testcase"))
    if len(cases) != expected or any(case.find(tag) is not None for case in cases
                                  for tag in ("skipped", "error", "failure")):
        raise RuntimeError("Required integration cases were empty, skipped, or failed")
    return len(cases)


def context_digest(directory: Path, *, frontend: bool = False) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        parts = path.relative_to(directory).parts
        if frontend and (any(part in {"node_modules", ".git", ".next"} or part.startswith(".next-") for part in parts)
                or path.name.startswith(".env") or path.name == "tsconfig.tsbuildinfo"
                or parts[0] == "test-results" or parts[0].startswith("playwright-report")
                or parts[:2] == ("public", "monaco")):
            continue
        if path.is_file():
            digest.update(path.relative_to(directory).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def require_browser_proof(path: Path) -> None:
    value = json.loads(path.read_text())
    samples = value.get("samples", [])
    if (value.get("success") is not True or value.get("scenario") != "normal-guest-initial-and-latest-source"
            or value.get("admission_count") != 2 or len(samples) != 2
            or any(value.get(key) != 0 for key in ("runtime_error_count", "capture_error_count", "external_request_count"))
            or any(sample.get("terminal_status") != "completed" or sample.get("admission_http_status") != 200
                   or any(sample.get(key) is not True for key in ("websocket_artifact", "websocket_completed",
                       "canvas_painted", "expected_text_rendered", "synctex_mappable",
                       "pdf_geometry_synctex_fingerprint_matches")) for sample in samples)):
        raise RuntimeError("Required real browser proof was empty, partial, or failed")


def wait_until_ready(probe, alive, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not alive():
            raise RuntimeError("Owned service exited before readiness")
        if probe():
            return
        time.sleep(0.5)
    raise RuntimeError("Owned service did not become ready within its deadline")


def stop_owned_process(process: subprocess.Popen) -> None:
    # Never pkill/lsof an arbitrary listener: only the spawned process group.
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


class Harness:
    def __init__(self, root: Path, work: Path, evidence: Path):
        self.root, self.work, self.evidence = root, work, evidence
        self.run_id = uuid.uuid4().hex
        self.prefix = "latexy-ci-" + self.run_id
        self.network = self.prefix + "-network"
        self.image = self.prefix + ":candidate"
        self.environment = clean_environment(work / "home")
        Path(self.environment["HOME"]).mkdir()
        self.environment["DOCKER_CONFIG"] = str(work / "docker-config")
        self.names: list[str] = []
        self.network_created = False
        self.image_attempted = False
        self.image_built = False
        self.frontend = None
        self.frontend_log = None
        self.app_environment: dict[str, str] = {}
        self.frontend_reservation = None
        self.provenance: dict[str, str] = {}
        self.deadline = time.monotonic() + 45 * 60
        self.cleaning = False

    def phase_timeout(self, requested: float) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Isolated functional proof exceeded its overall deadline")
        return min(requested, remaining)

    def command(self, arguments: list[str], *, timeout: float = 60, capture: bool = False, cwd: Path | None = None):
        # Errors never echo argv because argv contains fresh synthetic secrets.
        result = subprocess.run(arguments, env=self.environment, cwd=cwd or self.root,
                                timeout=timeout if self.cleaning else self.phase_timeout(timeout),
                                stdout=subprocess.PIPE if capture else None,
                                stderr=subprocess.PIPE if capture else None, text=True, check=False)
        if result.returncode:
            raise RuntimeError(f"Owned CI command failed ({arguments[0]}; exit {result.returncode})")
        return result.stdout.strip() if capture else None

    def docker(self, *arguments: str, timeout: float = 60, capture: bool = False):
        return self.command(["docker", *arguments], timeout=timeout, capture=capture)

    def alive(self, name: str) -> bool:
        return self.docker("inspect", "--format", "{{.State.Running}}", name, capture=True) == "true"

    def start(self, role: str, image: str, options: list[str], command: list[str]) -> str:
        name = self.prefix + "-" + role
        # Register exact cleanup target before creation, including partial failure.
        self.names.append(name)
        self.docker("run", "--detach", "--name", name, "--label", "latexy.ci.run=" + self.run_id,
                    "--network", self.network, "--network-alias", role, *options, image, *command)
        return name

    def published_port(self, name: str, port: int) -> int:
        value = self.docker("port", name, f"{port}/tcp", capture=True)
        if not value.startswith("127.0.0.1:") or "\n" in value:
            raise RuntimeError("Owned service was not published exclusively on loopback")
        return int(value.rsplit(":", 1)[1])

    def app_options(self) -> list[str]:
        options = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "512",
                   "--memory", "3g", "--cpus", "2", "--tmpfs", "/tmp:rw,nosuid,size=512m",
                   "--mount", f"type=bind,src={self.evidence},dst=/evidence"]
        for key, value in self.app_environment.items():
            options.extend(["--env", key + "=" + value])
        return options

    def qa(self, command: list[str], *, timeout: float = 180) -> None:
        name = self.start("qa-" + uuid.uuid4().hex[:8], self.image, self.app_options(), command)
        code = int(self.docker("wait", name, timeout=timeout, capture=True))
        if code:
            # A bounded tail contains only synthetic fixture diagnostics.
            self.docker("logs", "--tail", "80", name)
            raise RuntimeError(f"Owned candidate QA process failed (exit {code})")

    def prepare(self) -> tuple[str, str]:
        context = self.work / "context"
        copy_candidate_context(self.root, context)
        self.provenance = {
            "source_head": self.command(["git", "rev-parse", "HEAD"], capture=True),
            "candidate_context_sha256": context_digest(context),
            "frontend_source_sha256": context_digest(self.root / "frontend", frontend=True),
            "pnpm_lock_sha256": hashlib.sha256((self.root / "pnpm-lock.yaml").read_bytes()).hexdigest(),
            "qa_layer": "isolated-ci: production assets plus hash-locked requirements-dev.lock",
        }
        self.image_attempted = True
        self.docker("build", "--target", "isolated-ci", "--file", str(context / "Dockerfile.prod"),
                    "--tag", self.image, str(context), timeout=2400)
        self.image_built = True
        self.provenance["candidate_image_id"] = self.docker("image", "inspect", "--format", "{{.Id}}", self.image, capture=True)
        # No host default config, registry credentials, or credential helpers.
        for image in SERVICE_IMAGES.values():
            self.docker("pull", image, timeout=300)
        # A timed-out Docker CLI can leave a created network behind.
        self.network_created = True
        self.docker("network", "create", "--internal", "--label", "latexy.ci.run=" + self.run_id, self.network)
        postgres = self.start("postgres", SERVICE_IMAGES["postgres"],
            ["--publish", "127.0.0.1::5432", "--env", "POSTGRES_USER=postgres",
             "--env", "POSTGRES_HOST_AUTH_METHOD=trust", "--env", "POSTGRES_DB=latexy_ci_test",
             "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,size=512m"], [])
        redis = self.start("redis", SERVICE_IMAGES["redis"], [], ["redis-server", "--save", "", "--appendonly", "no"])
        access = "ci-" + uuid.uuid4().hex
        secret = uuid.uuid4().hex + uuid.uuid4().hex
        storage = self.start("storage", SERVICE_IMAGES["storage"],
            ["--env", "MINIO_ROOT_USER=" + access, "--env", "MINIO_ROOT_PASSWORD=" + secret,
             "--tmpfs", "/data:rw,nosuid,size=512m"], ["server", "/data", "--console-address", ":9001"])
        def exec_ready(name, command):
            result = subprocess.run(["docker", "exec", name, *command], env=self.environment,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
            return result.returncode == 0
        wait_until_ready(lambda: exec_ready(postgres, ["pg_isready", "-U", "postgres"]), lambda: self.alive(postgres), 90)
        wait_until_ready(lambda: exec_ready(redis, ["redis-cli", "ping"]), lambda: self.alive(redis), 30)
        self.frontend_reservation = socket.socket()
        self.frontend_reservation.bind(("127.0.0.1", 0))
        frontend_port = self.frontend_reservation.getsockname()[1]
        frontend_origin = f"http://127.0.0.1:{frontend_port}"
        self.app_environment = {
            "LATEXY_ISOLATED_CI": "1", "ENVIRONMENT": "staging", "DEBUG": "false", "DEPLOY_TARGET": "local",
            "LATEXY_RENDER_BACKEND": "native", "DATABASE_URL": "postgresql+asyncpg://postgres@postgres:5432/latexy_ci_test",
            "TEST_DATABASE_URL": "postgresql+asyncpg://postgres@postgres:5432/latexy_ci_test",
            "REDIS_URL": "redis://redis:6379/0", "REDIS_CACHE_URL": "redis://redis:6379/1",
            "CELERY_BROKER_URL": "redis://redis:6379/0", "CELERY_RESULT_BACKEND": "redis://redis:6379/0",
            "TEST_REDIS_URL": "redis://redis:6379/15", "TEST_REDIS_CACHE_URL": "redis://redis:6379/14",
            "MINIO_ENDPOINT": "http://storage:9000", "MINIO_ACCESS_KEY": access, "MINIO_SECRET_KEY": secret,
            "MINIO_BUCKET": self.prefix, "JWT_SECRET_KEY": uuid.uuid4().hex + uuid.uuid4().hex,
            "BETTER_AUTH_SECRET": uuid.uuid4().hex + uuid.uuid4().hex,
            "API_KEY_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
            "BILLING_MODE": "disabled", "EMAIL_ENABLED": "false", "OPENAI_API_KEY": "", "OPENAI_BASE_URL": "",
            "ANTHROPIC_API_KEY": "", "OPENROUTER_API_KEY": "", "GEMINI_API_KEY": "", "RESEND_API_KEY": "",
            "GEOIP_PROVIDER_URL": "", "OTEL_ENABLED": "false", "OTEL_EXPORTER_MODE": "none",
            "FRONTEND_URL": frontend_origin, "CORS_ORIGINS": json.dumps([frontend_origin]), "UVICORN_WORKERS": "1",
        }
        # Bucket creation is the sole S3 setup write. With no policy/ACL set the
        # fresh bucket remains private; application accesses it via signed S3.
        self.qa(["python", "-c", """import time
from urllib.request import urlopen
from app.services.storage_service import _get_client
from app.core.config import settings
for _ in range(60):
    try:
        with urlopen('http://storage:9000/minio/health/ready', timeout=2) as r:
            if r.status == 200:
                break
    except OSError:
        pass
    time.sleep(0.5)
else:
    raise RuntimeError('Owned private storage did not become ready')
c = _get_client()
c.create_bucket(Bucket=settings.MINIO_BUCKET)
assert all(not grant.get('Grantee', {}).get('URI') for grant in c.get_bucket_acl(Bucket=settings.MINIO_BUCKET)['Grants'])
print('Fresh private artifact bucket ready')
"""], timeout=90)
        if not self.alive(storage):
            raise RuntimeError("Owned private storage exited")
        self.qa(["python", "-c", ("from pathlib import Path; import json; "
                 "p=Path('/opt/latexy-renderer-version.json'); value=json.loads(p.read_text()); "
                 "assert len(value['fingerprint_sha256']) == 64; "
                 "Path('/evidence/renderer-assets.json').write_text(json.dumps(value, indent=2))")], timeout=60)
        self.provenance["renderer_assets_fingerprint"] = json.loads(
            (self.evidence / "renderer-assets.json").read_text())["fingerprint_sha256"]
        self.qa(["alembic", "upgrade", "head"], timeout=180)
        self.qa(["python", "-m", "pytest", "test/test_converter_failure_ledger_integration.py", "-v",
                 "--junitxml=/evidence/converter-failure-ledger.xml"], timeout=240)
        require_junit_cases(self.evidence / "converter-failure-ledger.xml", expected=11)
        self.qa(["python", "scripts/certify_resume_templates.py", "--samples", "1", "--timeout", "40",
                 "--fixture", "ats_safe/ats_clean.tex", "--fixture", "ats_safe/hindi_professional.tex",
                 "--output", "/evidence/required-template-certification.json"], timeout=180)
        api = self.start("api", self.image, [*self.app_options(), "--publish", "127.0.0.1::8030"], [])
        worker = self.start("worker", self.image, self.app_options(),
            ["celery", "-A", "app.core.celery_app", "worker", "--queues", "latex", "--concurrency", "1",
             "--loglevel", "WARNING", "--without-gossip", "--without-mingle", "--hostname", "isolated@%h"])
        api_origin = "http://127.0.0.1:" + str(self.published_port(api, 8030))
        def healthy():
            try:
                with urlopen(api_origin + "/health", timeout=5) as response:
                    value = json.loads(response.read(64 * 1024))
                return value.get("status") == "healthy" and value.get("latex_available") is True
            except (OSError, ValueError):
                return False
        wait_until_ready(healthy, lambda: self.alive(api) and self.alive(worker), 90)
        for fixture in ("minimal", "hindi"):
            self.docker("exec", api, "python", "scripts/ci/local-job-smoke.py", "--base-url", "http://127.0.0.1:8030",
                        "--fixture", fixture, "--verify-isolated-storage", "--output", f"/evidence/real-job-{fixture}.json", timeout=180)
        postgres_origin = f"postgresql://postgres@127.0.0.1:{self.published_port(postgres, 5432)}/latexy_ci_test"
        self.environment.update({
            "REAL_PREVIEW_BASE_URL": frontend_origin, "REAL_PREVIEW_API_URL": api_origin,
            "CI_ISOLATED_EVIDENCE_DIR": str(self.evidence), "PLAYWRIGHT_PORT": str(frontend_port),
            "PLAYWRIGHT_SERVER_MODE": "production", "PLAYWRIGHT_APP_URL": frontend_origin,
            "PLAYWRIGHT_BACKEND_URL": api_origin, "PLAYWRIGHT_API_URL": api_origin,
            "PLAYWRIGHT_DATABASE_URL": postgres_origin, "PLAYWRIGHT_AUTH_URL": frontend_origin.replace("http:", "https:"),
            "PLAYWRIGHT_BETTER_AUTH_SECRET": self.app_environment["BETTER_AUTH_SECRET"],
            "NEXT_PUBLIC_WS_URL": api_origin.replace("http:", "ws:"),
        })
        return api_origin, frontend_origin

    def browser(self, api_origin: str, frontend_origin: str) -> None:
        if context_digest(self.root / "frontend", frontend=True) != self.provenance["frontend_source_sha256"]:
            raise RuntimeError("Frontend source changed since candidate provenance was recorded")
        self.frontend_log = (self.evidence / "frontend.log").open("w", encoding="utf-8")
        # Never reuse a listener, and release only our reserved random port.
        self.frontend_reservation.close()
        self.frontend_reservation = None
        self.frontend = subprocess.Popen(["node", "scripts/playwright-server.mjs", "--port", self.environment["PLAYWRIGHT_PORT"],
                                         "--mode", "production"], cwd=self.root / "frontend", env=self.environment,
                                         stdout=self.frontend_log, stderr=subprocess.STDOUT, start_new_session=True)
        def frontend_ready():
            try:
                with urlopen(frontend_origin + "/try", timeout=5) as response:
                    return response.status == 200
            except OSError:
                return False
        wait_until_ready(frontend_ready, lambda: self.frontend.poll() is None, self.phase_timeout(1200))
        self.command(["pnpm", "exec", "playwright", "test", "--config=playwright.real-preview.config.ts"],
                     timeout=900, cwd=self.root / "frontend")
        require_junit_cases(self.evidence / "real-preview.xml", expected=1)
        require_browser_proof(self.evidence / "browser-proof.json")
        if context_digest(self.root / "frontend", frontend=True) != self.provenance["frontend_source_sha256"]:
            raise RuntimeError("Frontend source changed during its real functional proof")

    def cleanup(self) -> list[str]:
        # Always keep exact-owned cleanup available after the proof deadline.
        self.cleaning = True
        failures = []
        if self.frontend_reservation:
            self.frontend_reservation.close()
        if self.frontend:
            try:
                stop_owned_process(self.frontend)
            except (OSError, subprocess.TimeoutExpired):
                failures.append("frontend")
        if self.frontend_log:
            self.frontend_log.close()
        for name in reversed(self.names):
            try:
                self.docker("rm", "--force", "--volumes", name, timeout=30, capture=True)
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                failures.append(name)
        if self.network_created:
            try:
                self.docker("network", "rm", self.network, timeout=30, capture=True)
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                failures.append("network")
        if self.image_attempted:
            try:
                self.docker("image", "rm", self.image, timeout=30, capture=True)
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                # A failed build can leave no tagged image; do not prune caches.
                if self.image_built:
                    failures.append("candidate-image")
        return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-isolated-ci-run", action="store_true")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.confirm_isolated_ci_run:
        parser.error("Explicit isolated CI opt-in is required")
    if not os.sys.platform.startswith("linux"):
        parser.error("This candidate functional proof requires Linux")
    evidence = args.evidence_dir.resolve()
    # Fresh evidence prevents a failed revision from uploading a stale pass.
    evidence.mkdir(parents=True, exist_ok=False)
    evidence.chmod(0o777)  # Non-root containers write only this fresh synthetic directory.
    with tempfile.TemporaryDirectory(prefix="latexy-ci-") as temporary:
        harness = Harness(ROOT, Path(temporary), evidence)
        def interrupted(signum, frame):
            raise RuntimeError("Isolated CI run interrupted")
        previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
        passed = False
        try:
            api, frontend = harness.prepare()
            harness.browser(api, frontend)
            passed = True
        finally:
            failures = harness.cleanup()
            (evidence / "isolated-run.json").write_text(json.dumps({
                "scope": "candidate Linux real runtime functional proof; excludes Modal certification and timing SLO",
                "success": passed and not failures, "cleanup_success": not failures,
                "run_id": harness.run_id, "cleanup_failures": failures,
                **harness.provenance,
            }, indent=2) + "\n", encoding="utf-8")
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            if failures:
                raise RuntimeError("Owned CI resource cleanup did not complete")


if __name__ == "__main__":
    main()
