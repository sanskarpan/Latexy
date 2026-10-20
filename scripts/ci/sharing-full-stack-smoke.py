"""Add fresh loopback-only object storage to the existing full-stack suite.

Clean CI checkouts only: runtime dotenv files are rejected before any command.
No inherited provider secrets or existing Docker resources are consumed.
The accepted-PDF fixture runs against the same newly started host API as the
other smoke cases; storage uses the source-pinned CI MinIO recipe.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_KEYS = {"PATH", "LANG", "LC_ALL", "TERM", "PNPM_HOME", "COREPACK_HOME",
                "PLAYWRIGHT_BROWSERS_PATH", "VIRTUAL_ENV", "UV_CACHE_DIR"}


def reject_runtime_env_files(root: Path) -> None:
    # Application settings read root/backend .env; Next also loads mode/local
    # variants. Check names/existence only, never contents. Example templates
    # are not runtime-loaded and remain usable in a clean checkout.
    for directory in (root, root / "backend", root / "frontend"):
        for path in directory.iterdir():
            if ((path.name == ".env" or path.name.startswith(".env."))
                    and not path.name.endswith(".example")):
                raise RuntimeError("Sharing CI refuses runtime dotenv files in application directories")


class SharingCancelled(Exception):
    def __init__(self, signum: int):
        super().__init__("Isolated sharing acceptance cancelled")
        self.signum = signum


@contextmanager
def cancellation_guard():
    previous = signal.getsignal(signal.SIGTERM)
    cleaning = False
    cancelled = None

    @contextmanager
    def cleanup():
        nonlocal cleaning
        previous_cleaning = cleaning
        cleaning = True
        try:
            yield
        finally:
            cleaning = previous_cleaning
        if cancelled is not None:
            raise SharingCancelled(cancelled)

    def cancel(signum, _frame):
        nonlocal cancelled
        # Further cancellation must not interrupt the bounded process/storage
        # cleanup that unwinds below. Restore the caller's handler afterwards.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        cancelled = signum
        if not cleaning:
            raise SharingCancelled(signum)

    signal.signal(signal.SIGTERM, cancel)
    try:
        yield cleanup
    finally:
        signal.signal(signal.SIGTERM, previous)


def service_url(value: str, scheme: str, *, test_database: bool = False) -> str:
    target = urlsplit(value.replace("postgresql+asyncpg:", "postgresql:"))
    try:
        valid_port = target.port is not None and target.port > 0
    except ValueError:
        valid_port = False
    if (target.scheme != scheme or target.hostname not in {"localhost", "127.0.0.1", "::1"}
            or not valid_port or target.query or target.fragment
            or (test_database and not re.fullmatch(r"/[a-zA-Z0-9_]+_test", target.path))):
        raise RuntimeError("Sharing CI requires explicit loopback test services")
    return value


def test_environment(source: dict[str, str], home: Path) -> dict[str, str]:
    # Validate every inherited service before any build/container/migration.
    database = service_url(source.get("DATABASE_URL", ""), "postgresql", test_database=True)
    transport = {key: service_url(source.get(key, ""), "redis") for key in
                 ("REDIS_URL", "REDIS_CACHE_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND")}
    browser_cache = Path(source.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    if not browser_cache.is_absolute() or not browser_cache.is_dir():
        raise RuntimeError("Sharing CI requires the explicit installed Playwright browser cache")
    environment = {key: value for key, value in source.items() if key in RUNTIME_KEYS}
    environment.update(transport, DATABASE_URL=database, HOME=str(home), TMPDIR=str(home),
                       DOCKER_CONFIG=str(home / "docker-config"), CI="1", ENVIRONMENT="test",
                       DEPLOY_TARGET="local", BILLING_MODE="disabled", EMAIL_ENABLED="false",
                       NEXT_TELEMETRY_DISABLED="1", OTEL_ENABLED="false", OTEL_EXPORTER_MODE="none")
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
                "GEMINI_API_KEY", "RESEND_API_KEY", "GEOIP_PROVIDER_URL"):
        environment[key] = ""
    return environment


def stop_owned_process_group(process: subprocess.Popen) -> None:
    """Give Bash its EXIT cleanup, then bound any remaining owned descendants."""
    deadline = time.monotonic() + 15
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait(timeout=5)
        return
    while True:
        process.poll()  # Reap an exited leader before checking remaining group members.
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            break
        if time.monotonic() >= deadline:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            break
        time.sleep(0.1)
    process.wait(timeout=5)


def run_smoke(environment: dict[str, str], *, timeout: int = 1800, cleanup=nullcontext) -> int:
    # A new session makes this exact group ours. subprocess.run(timeout=...)
    # kills only Bash and can bypass its EXIT trap, leaking API/Next children.
    process = None
    try:
        # Defer a signal during child creation until its handle is recorded,
        # so the finally block can always stop the new owned group.
        with cleanup():
            process = subprocess.Popen(["bash", str(ROOT / "scripts/ci/full-stack-smoke.sh")],
                                       cwd=ROOT, env=environment, start_new_session=True)
        return process.wait(timeout=timeout)
    finally:
        if process is not None:
            with cleanup():
                stop_owned_process_group(process)


class SharingStorage:
    def __init__(self, environment: dict[str, str]):
        self.environment = environment
        self.run_id = uuid.uuid4().hex
        self.name = "latexy-sharing-" + self.run_id
        self.network = self.name + "-network"
        self.image = self.name + ":storage"
        self.image_attempted = self.network_attempted = self.container_attempted = False

    def docker(self, *arguments: str, timeout: int = 60) -> str:
        result = subprocess.run(["docker", *arguments], cwd=ROOT, env=self.environment,
                                capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode:
            # Docker arguments/environment include per-run credentials; do not echo them.
            raise RuntimeError(f"Owned sharing storage command failed ({arguments[0]}; exit {result.returncode})")
        return result.stdout.strip()

    def start(self) -> str:
        self.image_attempted = True
        self.docker("build", "--file", str(ROOT / "scripts/ci/Dockerfile.minio-ci"),
                    "--tag", self.image, str(ROOT / "scripts/ci"), timeout=900)
        self.network_attempted = True
        self.docker("network", "create", "--internal", "--label", "latexy.ci.run=" + self.run_id,
                    self.network)
        access, secret = "ci-" + uuid.uuid4().hex, uuid.uuid4().hex + uuid.uuid4().hex
        self.container_attempted = True
        self.docker("run", "--detach", "--name", self.name, "--network", self.network,
                    "--label", "latexy.ci.run=" + self.run_id, "--publish", "127.0.0.1::9000",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "256",
                    "--memory", "1g", "--cpus", "1",
                    "--tmpfs", "/tmp:rw,nosuid,size=64m,uid=65532,gid=65532,mode=0700",
                    "--tmpfs", "/data:rw,nosuid,size=512m,uid=65532,gid=65532,mode=0700",
                    "--env", "MINIO_ROOT_USER=" + access, "--env", "MINIO_ROOT_PASSWORD=" + secret,
                    self.image, "server", "/data", "--console-address", ":9001")
        state = json.loads(self.docker("inspect", self.name))[0]
        ports = state["NetworkSettings"]["Ports"]
        bindings = ports.get("9000/tcp") or []
        # Report fixed check names only, never raw inspect state (which includes
        # the generated storage credentials). Keep every isolation gate strict.
        binding = bindings[0] if len(bindings) == 1 else {}
        host_port = binding.get("HostPort", "")
        checks = {
            "owned_name": state["Name"] == "/" + self.name,
            "owned_label": state["Config"]["Labels"].get("latexy.ci.run") == self.run_id,
            "only_owned_network": set(state["NetworkSettings"]["Networks"]) == {self.network},
            "exactly_one_binding": len(bindings) == 1,
            "loopback_binding": binding.get("HostIp") == "127.0.0.1",
            "valid_port": bool(re.fullmatch(r"[0-9]{1,5}", host_port)) and 1024 <= int(host_port) <= 65535,
            "no_extra_published_ports": not any(value for key, value in ports.items() if key != "9000/tcp"),
        }
        if not all(checks.values()):
            failed = ",".join(key for key, passed in checks.items() if not passed)
            running = state.get("State", {}).get("Running") is True
            raise RuntimeError("Storage is not the exact owned loopback-only publication; failed checks: "
                               + failed + "; running=" + str(running))
        endpoint = "http://127.0.0.1:" + bindings[0]["HostPort"]
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with urlopen(endpoint + "/minio/health/ready", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("Owned storage did not become ready")
        backend_python = ROOT / "backend/.venv/bin/python"
        self.environment.update(MINIO_ENDPOINT=endpoint, MINIO_BUCKET=self.name,
            MINIO_ACCESS_KEY=access, MINIO_SECRET_KEY=secret,
            SHARING_ACCEPTANCE_DISPOSABLE="1", SHARING_ACCEPTANCE_STORAGE_MODE="host",
            SHARING_ACCEPTANCE_PYTHON=str(backend_python) if backend_python.is_file() else sys.executable,
            SHARING_ACCEPTANCE_STORAGE_ENDPOINT=endpoint,
            SHARING_ACCEPTANCE_PUBLIC_STORAGE_ENDPOINT=endpoint, SHARING_ACCEPTANCE_STORAGE_BUCKET=self.name)
        return endpoint

    def cleanup(self) -> None:
        # Exact generated names only; no prune, discovery, or existing resource removal.
        failures = []
        for attempted, arguments in (
            (self.container_attempted, ("rm", "--force", self.name)),
            (self.network_attempted, ("network", "rm", self.network)),
            (self.image_attempted, ("image", "rm", self.image)),
        ):
            if attempted:
                try:
                    self.docker(*arguments)
                except (OSError, RuntimeError, subprocess.TimeoutExpired):
                    failures.append(arguments[0])
        if failures:
            raise RuntimeError("Owned sharing storage cleanup incomplete")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-isolated-sharing-run", action="store_true", required=True)
    parser.parse_args()
    if os.name != "posix":
        raise RuntimeError("Sharing CI launcher requires the isolated Linux runner")
    reject_runtime_env_files(ROOT)
    with cancellation_guard() as cleanup:
        with tempfile.TemporaryDirectory(prefix="latexy-sharing-ci-") as directory:
            environment = test_environment(dict(os.environ), Path(directory))
            storage = SharingStorage(environment)
            try:
                storage.start()
                return run_smoke(environment, cleanup=cleanup)
            finally:
                with cleanup():
                    storage.cleanup()


def cli() -> int:
    try:
        return main()
    except SharingCancelled as error:
        print(str(error), file=sys.stderr)
        return 128 + error.signum
    except RuntimeError as error:
        # Only fixed, repository-owned messages; never subprocess argv/output.
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, subprocess.TimeoutExpired):
        print("Isolated sharing acceptance failed; inspect bounded CI evidence.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
