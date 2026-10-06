"""Optional credential-free Modal VM bridge; cloud runtime is not certified here.

SDK contract verified against the official modal 1.5.4 wheel (deployment pin).
VM selection in that SDK uses experimental_options={"vm_runtime": True},
not the newer runtime='vm' argument. API references:
https://modal.com/docs/guide/vm-sandboxes
https://modal.com/docs/reference/modal.Sandbox
No Sandbox may be created unless the explicit operator capability gate is on.
"""

import base64
import math
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ...utils.bounded_io import MAX_COMPILE_LOG_BYTES, MAX_COMPILED_PDF_BYTES, read_file_bounded

_REMOTE = "/workspace"
_BOOTSTRAP = "/tmp/latexy-sandbox-bootstrap"
_INPUT_LIMIT = 32 * 1024 * 1024
_OUTPUT_LIMITS = {
    ".pdf": MAX_COMPILED_PDF_BYTES,
    ".synctex.gz": 8 * 1024 * 1024,
    ".fls": 2 * 1024 * 1024,
    ".log": MAX_COMPILE_LOG_BYTES,
    ".aux": 512 * 1024,
    ".out": 512 * 1024,
    ".toc": 512 * 1024,
    ".bbl": 512 * 1024,
    ".blg": MAX_COMPILE_LOG_BYTES,
}
_IMAGE_PREFLIGHT = """import os,json,ctypes
keys={'OPENAI_API_KEY','DATABASE_URL','REDIS_PASSWORD','API_KEY_ENCRYPTION_KEY','MODAL_TOKEN_ID','MODAL_TOKEN_SECRET','MODAL_IDENTITY_TOKEN'}
libc=ctypes.CDLL(None);libc.syscall.restype=ctypes.c_long
print(json.dumps({'credential_env_present':bool(keys.intersection(os.environ)),
 'application_source_present':os.path.exists('/backend') or os.path.exists('/app'),
 'dotenv_present':any(os.path.exists(p) for p in ['/.env','/root/.env','/app/.env','/backend/.env']),
 'landlock_abi':libc.syscall(444,0,0,1)}))
"""
_BOUNDED_EXPORT = """import os,sys,stat,base64
p=sys.argv[1];limit=int(sys.argv[2])
if not p.startswith('/workspace/') or '/' in p[len('/workspace/'):] or limit<1 or limit>33554432:sys.exit(78)
try:fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
except FileNotFoundError:sys.exit(44)
s=os.fstat(fd)
if not stat.S_ISREG(s.st_mode) or s.st_size>limit:os.close(fd);sys.exit(78)
with os.fdopen(fd,'rb') as f:data=f.read(limit+1)
if len(data)>limit:sys.exit(78)
sys.stdout.buffer.write(base64.b64encode(data))
"""
_VM_BOUNDARY_PREFLIGHT = """import os,socket,json
os.setgroups([]);os.setgid(65534);os.setuid(65534)
result={'uid':os.getuid(),'private_process_read':False,'network_connect':False}
try:
 with open('/proc/1/environ','rb') as f:result['private_process_read']=bool(f.read(1))
except PermissionError:pass
for host,port in [('1.1.1.1',443),('169.254.169.254',80)]:
 s=socket.socket();s.settimeout(2)
 try:s.connect((host,port));result['network_connect']=True
 except OSError:pass
 finally:s.close()
print(json.dumps(result))
"""


def _read_remote_bounded(sandbox, path, limit):
    # SDK stream.read is whole-stream, so the trusted exporter itself imposes
    # a hard byte ceiling before producing base64. No deprecated FileIO RPC.
    process = sandbox.exec("python3", "-c", _BOUNDED_EXPORT, path, str(limit),
                           timeout=30, text=False, secrets=[])
    encoded = process.stdout.read()
    code = process.wait()
    if code == 44:
        raise FileNotFoundError(path)
    if code != 0 or not isinstance(encoded, bytes) or len(encoded) > 4 * ((limit + 2) // 3):
        raise ModalEngineUnavailable("Remote artifact export rejected")
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ModalEngineUnavailable("Invalid remote artifact encoding") from exc
    if len(data) > limit:
        raise ModalEngineUnavailable("Remote artifact exceeds limit")
    return data


class ModalEngineUnavailable(RuntimeError):
    pass


class _BoundedRemoteReader:
    def __init__(self, process):
        self.process = process
        self.file = None
        self.read_bytes = 0

    def read(self, size):
        if type(size) is not int or not 1 <= size <= MAX_COMPILE_LOG_BYTES:
            raise ValueError("Bounded read required")
        if self.file is None:
            self.process.wait()
            if self.process.killed:
                return b""
            import io

            self.file = io.BytesIO(_read_remote_bounded(self.process.sandbox, _REMOTE + "/engine.stdout",
                                                       MAX_COMPILE_LOG_BYTES))
        remaining = MAX_COMPILE_LOG_BYTES - self.read_bytes
        if remaining <= 0:
            return b""
        chunk = self.file.read(min(size, remaining))
        if not isinstance(chunk, bytes) or len(chunk) > min(size, remaining):
            raise ModalEngineUnavailable("Invalid remote bounded stream")
        self.read_bytes += len(chunk)
        return chunk

    def close(self):
        if self.file:
            self.file.close()


class ModalEngineProcess:
    """Popen-compatible bounded reader, poll/wait/kill and local output files.

    Output becomes readable after the engine exits. Existing watchdogs can
    terminate the whole VM while a silent process is being awaited. The SDK
    transport itself is best-effort cancellation; this is not a hard RPC kill.
    """

    def __init__(self, sandbox, process, workspace: Path, basename: str):
        self.sandbox, self.process, self.workspace, self.basename = sandbox, process, workspace, basename
        self.pid = "modal-vm"
        self.killed = False
        self.stdout = _BoundedRemoteReader(self)
        self.stderr = None
        self._lock = threading.Lock()
        self._copied = False
        self.remote_workspace = _REMOTE

    @property
    def returncode(self):
        return self.process.returncode

    def poll(self):
        return self.process.poll()

    def kill(self):
        self.killed = True
        timer = getattr(self, "_deadline_timer", None)
        if timer is not None:
            timer.cancel()
        self.sandbox.terminate(wait=False)

    terminate = kill

    def wait(self, timeout=None):
        try:
            return self._wait_and_copy(timeout)
        except BaseException:
            self.kill()
            raise

    def _wait_and_copy(self, timeout=None):
        if timeout is not None:
            deadline = time.monotonic() + timeout
            while self.poll() is None:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired("modal-engine", timeout)
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        code = self.process.wait()
        with self._lock:
            if not self._copied and not self.killed:
                # Kernel profile denies forks; the VM root bridge reaps its
                # dedicated UID before returning. Export itself remains
                # no-follow, regular-file-only and bounded even on races.
                for suffix, limit in _OUTPUT_LIMITS.items():
                    remote = _REMOTE + "/" + self.basename + suffix
                    try:
                        data = _read_remote_bounded(self.sandbox, remote, limit)
                    except FileNotFoundError:
                        continue
                    target = self.workspace / (self.basename + suffix)
                    if target.is_symlink():
                        raise ModalEngineUnavailable("Local artifact target escapes workspace")
                    target.write_bytes(data)
                self._copied = True
        return code

    def close(self):
        self.stdout.close()
        self.kill()


def create_modal_engine(
    *,
    workspace: str | Path,
    compiler: str,
    arguments: list[str],
    timeout: float,
    sdk: Any = None,
    enabled: bool | None = None,
    image_id: str | None = None,
    image: Any = None,
    app: Any = None,
    policy: str = "kernel",
) -> ModalEngineProcess:
    """Explicitly gated SDK adapter; never inherits worker secrets or mounts."""
    enabled = enabled if enabled is not None else os.getenv("MODAL_ENGINE_VM_SANDBOX_ENABLED") == "true"
    image_id = image_id or os.getenv("MODAL_ENGINE_VM_IMAGE_ID", "")
    if not enabled or (image is None and not re.fullmatch(r"im-[A-Za-z0-9]{1,128}", image_id)):
        raise ModalEngineUnavailable("Modal VM engine capability is not configured")
    if compiler not in {"lualatex", "pdflatex", "xelatex", "bibtex"} or not 0 < timeout <= 300:
        raise ModalEngineUnavailable("Invalid isolated engine request")
    if policy not in {"kernel", "credential_free_vm"}:
        raise ModalEngineUnavailable("Invalid isolated engine policy")
    root = Path(workspace).resolve(strict=True)
    inputs, total = [], 0
    for path in root.iterdir():
        if path.is_symlink():
            raise ModalEngineUnavailable("Sandbox inputs cannot be symlinks")
        if path.is_file() and path.suffix in {".tex", ".bib", ".aux", ".out", ".toc", ".png", ".jpg", ".jpeg"}:
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", path.name):
                raise ModalEngineUnavailable("Invalid sandbox input name")
            data = read_file_bounded(path, _INPUT_LIMIT)
            total += len(data)
            if total > _INPUT_LIMIT or len(inputs) >= 128:
                raise ModalEngineUnavailable("Sandbox input budget exceeded")
            inputs.append((path.name, data))
    source = next((arg for arg in reversed(arguments) if arg.endswith(".tex")), "resume.tex")
    basename = Path(source).stem
    if "-jobname" in arguments:
        index = arguments.index("-jobname")
        if index + 1 == len(arguments):
            raise ModalEngineUnavailable("Missing engine basename")
        basename = arguments[index + 1]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", basename):
        raise ModalEngineUnavailable("Invalid engine basename")
    if sdk is None:
        import modal as sdk
    # A deployment can supply its already-built bare texlive_image object;
    # never pass a worker image containing application code or credentials.
    image = image if image is not None else sdk.Image.from_id(image_id)
    options = {
        "image": image,
        "app": app,
        "timeout": math.ceil(timeout),
        "experimental_options": {"vm_runtime": True},
        "block_network": True,
        "secrets": [],
        "volumes": {},
        "network_file_systems": {},
        "include_oidc_identity_token": False,
        "cpu": (1, 2),
        "memory": (1024, 2048),
        "env": {
            "TEXMFCACHE": "/var/lib/texmf",
            "openin_any": "p",
            "openout_any": "p",
            "shell_escape": "f",
            "max_print_line": "10000",
        },
    }
    # Arm before the creation RPC: a late returned VM is still terminated.
    # SDK calls themselves cannot be forcibly interrupted by this thread.
    deadline = time.monotonic() + timeout
    holder, lock = {}, threading.Lock()

    def expire():
        with lock:
            holder["expired"] = True
            current = holder.get("sandbox")
        if current is not None:
            current.terminate(wait=False)

    timer = threading.Timer(timeout, expire)
    timer.daemon = True
    timer.start()
    sandbox = None

    def check_deadline():
        if holder.get("expired") or time.monotonic() >= deadline:
            raise ModalEngineUnavailable("Modal engine creation deadline exceeded")

    try:
        sandbox = sdk.Sandbox.create("sleep", str(math.ceil(timeout)), **options)
        with lock:
            holder["sandbox"] = sandbox
        check_deadline()
        import json

        check = sandbox.exec("python3", "-c", _IMAGE_PREFLIGHT, timeout=min(15, math.ceil(timeout)), text=False, secrets=[])
        check_output = check.stdout.read()
        if check.wait() != 0 or len(check_output) > 4096:
            raise ModalEngineUnavailable("Sandbox image preflight failed")
        observed = json.loads(check_output)
        if (observed.get("credential_env_present") or observed.get("application_source_present")
                or observed.get("dotenv_present") or type(observed.get("landlock_abi")) is not int
                or (policy == "kernel" and observed["landlock_abi"] < 3)):
            # Deliberately expose only bounded capability booleans/ABI, never
            # environment values, image paths, or untrusted engine output.
            safe = {key: bool(observed.get(key)) for key in (
                "credential_env_present", "application_source_present", "dotenv_present")}
            safe["landlock_abi"] = observed.get("landlock_abi") if type(observed.get("landlock_abi")) is int else None
            raise ModalEngineUnavailable("Sandbox image preflight rejected: " + json.dumps(safe, sort_keys=True))
        if policy == "credential_free_vm":
            check_deadline()
            boundary = sandbox.exec("python3", "-c", _VM_BOUNDARY_PREFLIGHT, timeout=10, text=False, secrets=[])
            output = boundary.stdout.read()
            if boundary.wait() != 0 or len(output) > 4096:
                raise ModalEngineUnavailable("VM boundary preflight failed")
            proof = json.loads(output)
            if proof != {"uid": 65534, "private_process_read": False, "network_connect": False}:
                raise ModalEngineUnavailable("VM boundary isolation rejected")
        sandbox.filesystem.make_directory(_REMOTE)
        sandbox.filesystem.make_directory(_BOOTSTRAP)
        for name, data in inputs:
            check_deadline()
            sandbox.filesystem.write_bytes(data, _REMOTE + "/" + name)
        utilities = Path(__file__).resolve().parents[2] / "utils"
        for name in ("linux_engine_sandbox.py", "sandbox_io_bridge.py"):
            check_deadline()
            sandbox.filesystem.write_bytes(read_file_bounded(utilities / name, 65536), _BOOTSTRAP + "/" + name)
        remote_arguments = [(_REMOTE if arg == str(root) else _REMOTE + "/" + Path(arg).name
                             if Path(arg).is_absolute() and Path(arg).parent == root else arg)
                            for arg in arguments]
        check_deadline()
        process = sandbox.exec(
            "python3",
            _BOOTSTRAP + "/sandbox_io_bridge.py",
            _REMOTE,
            compiler,
            *(["--credential-free-vm"] if policy == "credential_free_vm" else []),
            *remote_arguments,
            timeout=max(1, math.ceil(deadline - time.monotonic())),
            workdir=_REMOTE,
            text=False,
            secrets=[],
        )
        check_deadline()
        result = ModalEngineProcess(sandbox, process, root, basename)
        result._deadline_timer = timer
        result.policy_identity = "lua-credential-free-vm-v1" if policy == "credential_free_vm" else "lua-landlock-seccomp-v2"
        return result
    except BaseException:
        timer.cancel()
        if sandbox is not None:
            sandbox.terminate(wait=False)
        raise
