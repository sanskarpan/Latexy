"""Trusted remote runner: bound SDK-visible output before untrusted TeX starts."""

import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path


def _disable_privilege_gain():
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        raise OSError("VM child privilege restriction failed")


def main():
    if len(sys.argv) < 4:
        raise SystemExit(78)
    workspace, compiler = sys.argv[1:3]
    if compiler not in {"lualatex", "pdflatex", "xelatex", "bibtex"}:
        raise SystemExit(78)
    launcher = Path(__file__).with_name("linux_engine_sandbox.py")
    arguments = sys.argv[3:]
    command = [sys.executable, str(launcher), workspace, compiler, *arguments]
    options = {}
    if arguments and arguments[0] == "--credential-free-vm":
        # Dedicated per-job VM boundary, not Landlock equivalence. Only this
        # trusted bridge starts as root; the engine cannot read root daemon
        # process environments or modify the bootstrap outside its workspace.
        import shutil

        if os.getuid() != 0 or workspace != "/workspace":
            raise SystemExit(78)
        cache = Path(workspace) / ".tex-cache/luatex-cache/generic/names"
        if not cache.resolve().is_relative_to(Path(workspace).resolve()):
            raise SystemExit(78)
        cache.mkdir(parents=True, exist_ok=True)
        for name in ("luaotfload-names.lua.gz", "luaotfload-names.luc.gz"):
            seed = Path("/var/lib/texmf/luatex-cache/generic/names") / name
            if (cache / name).is_symlink():
                raise SystemExit(78)
            if seed.is_file() and seed.stat().st_size <= 16 * 1024 * 1024:
                shutil.copyfile(seed, cache / name)
        for current, directories, files in os.walk(workspace, followlinks=False):
            os.chown(current, 65534, 65534)
            for name in directories + files:
                os.chown(os.path.join(current, name), 65534, 65534, follow_symlinks=False)
        command = [compiler, *arguments[1:]]
        options = {"user": 65534, "group": 65534, "extra_groups": [], "preexec_fn": _disable_privilege_gain,
                   "env": {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": workspace,
                           "LANG": "C.UTF-8", "TMPDIR": workspace,
                           "TEXMFVAR": workspace + "/.tex-cache",
                           "TEXMFCACHE": workspace + "/.tex-cache:/var/lib/texmf",
                           "openin_any": "r", "openout_any": "p", "shell_escape": "f",
                           "max_print_line": "10000"}}
    output_fd = os.open(os.path.join(workspace, "engine.stdout"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    if not stat.S_ISREG(os.fstat(output_fd).st_mode):
        os.close(output_fd)
        raise SystemExit(78)
    process = subprocess.Popen(
        command,
        cwd=workspace,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        close_fds=True,
        **options,
    )
    remaining = 256 * 1024
    with os.fdopen(output_fd, "wb") as output:
        while chunk := process.stdout.read(8192):
            output.write(chunk[:remaining])
            remaining = max(0, remaining - len(chunk))
    code = process.wait()
    if options:
        # A malicious VM job may have forked. Root controller reaps every
        # process under the dedicated job UID before fixed artifact export.
        for _ in range(100):
            remaining_pids = []
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    status = (entry / "status").read_text()
                    if any(line.startswith("State:") and "Z" in line for line in status.splitlines()):
                        continue
                    uid_line = next(line for line in status.splitlines() if line.startswith("Uid:"))
                    if int(uid_line.split()[1]) == 65534:
                        remaining_pids.append(int(entry.name))
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    continue
            if not remaining_pids:
                break
            for pid in remaining_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            time.sleep(0.01)
        else:
            raise SystemExit(78)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
