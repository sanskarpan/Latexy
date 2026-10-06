"""Kernel filesystem confinement for an engine subprocess, never the worker.

The launcher fails closed when Linux Landlock or seccomp is unavailable.
Trusted image assets are readable; only the exact job workspace is writable.
Seccomp denies network and cross-process capabilities. Kernel documentation:
https://docs.kernel.org/userspace-api/landlock.html
"""

import ctypes
import os
import platform
import shutil
import sys
from pathlib import Path


class ConfinementUnavailable(RuntimeError):
    pass


def _deny_ambient_capabilities(libc):
    """A small deny filter supplements filesystem rules without Lua patches."""
    if platform.machine() == "x86_64":
        arch = 0xC000003E
        forbidden = [
            41,
            42,
            43,
            44,
            45,
            46,
            47,
            48,
            49,
            50,
            53,
            288,
            299,
            307,
            101,
            310,
            311,
            438,
            62,
            200,
            234,
            424,
            298,
            321,
            425,
            426,
            427,
            56,
            57,
            58,
            435,
        ]
    else:
        arch = 0xC00000B7
        forbidden = [
            198,
            199,
            200,
            201,
            202,
            203,
            206,
            207,
            211,
            212,
            242,
            243,
            269,
            117,
            270,
            271,
            438,
            129,
            130,
            131,
            424,
            241,
            280,
            425,
            426,
            427,
            220,
            435,
        ]

    class Instruction(ctypes.Structure):
        _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte), ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint32)]

    class Program(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ushort), ("filter", ctypes.POINTER(Instruction))]

    # Reject a different syscall ABI, then deny sockets/process inspection/signals.
    instructions = [(0x20, 0, 0, 4), (0x15, 1, 0, arch), (0x06, 0, 0, 0x80000000), (0x20, 0, 0, 0)]
    for number in forbidden:
        instructions += [(0x15, 0, 1, number), (0x06, 0, 0, 0x00050001)]
    # x32 syscalls share the audit architecture but carry this ABI bit.
    if platform.machine() == "x86_64":
        instructions += [(0x45, 0, 1, 0x40000000), (0x06, 0, 0, 0x00050001)]
    instructions += [(0x06, 0, 0, 0x7FFF0000)]
    array = (Instruction * len(instructions))(*(Instruction(*row) for row in instructions))
    program = Program(len(instructions), array)
    if libc.prctl(22, 2, ctypes.byref(program), 0, 0) != 0:
        raise ConfinementUnavailable("Seccomp capability filter unavailable")


def confine_engine(workspace: str) -> int:
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise ConfinementUnavailable("Unsupported engine kernel")
    root = Path(workspace).resolve(strict=True)
    if not root.is_dir() or str(root) in {"/", "/tmp", "/app", "/workspace/.."}:
        raise ConfinementUnavailable("Invalid job workspace")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise ConfinementUnavailable("Landlock ABI 3 required")
    # V3 adds truncation. Handle every filesystem right up through that ABI;
    # later rights do not make file contents or file creation less restricted.
    rights = (1 << 15) - 1

    class Ruleset(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class PathRule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]

    rule = Ruleset(rights)
    ruleset = libc.syscall(444, ctypes.byref(rule), ctypes.sizeof(rule), 0)
    if ruleset < 0:
        raise ConfinementUnavailable("Landlock ruleset unavailable")

    def add(path: str, allowed: int):
        item = Path(path)
        if not item.exists():
            return
        if not item.is_dir():
            allowed &= 1 | 2 | 4 | (1 << 14)
        fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
        try:
            attribute = PathRule(allowed, fd)
            if libc.syscall(445, ruleset, 1, ctypes.byref(attribute), 0) < 0:
                raise ConfinementUnavailable("Landlock path rule rejected")
        finally:
            os.close(fd)

    try:
        for path in (
            "/usr/share/texlive",
            "/usr/share/texmf",
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            "/var/lib/texmf",
            "/var/cache/fontconfig",
            "/etc/texmf",
            "/etc/fonts",
            "/etc/ld.so.cache",
            "/etc/localtime",
        ):
            add(path, 4 | 8)
        for path in ("/usr/bin", "/bin", "/usr/lib", "/usr/local/lib", "/lib", "/lib64"):
            add(path, 1 | 4 | 8)
        add("/dev/null", 2 | 4)
        add("/dev/urandom", 4)
        add(str(root), rights)
        if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.syscall(446, ruleset, 0) < 0:
            raise ConfinementUnavailable("Landlock activation failed")
        _deny_ambient_capabilities(libc)
        return abi
    finally:
        os.close(ruleset)


def main():
    # The application supplies positional argv, never shell source.
    if len(sys.argv) < 3 or sys.argv[2] not in {"lualatex", "pdflatex", "xelatex", "bibtex"}:
        raise SystemExit(78)
    executable = shutil.which(sys.argv[2])
    if not executable:
        raise SystemExit(78)
    try:
        if sys.argv[2] == "lualatex":
            root = Path(sys.argv[1]).resolve(strict=True)
            cache = root / ".tex-cache"
            names = cache / "luatex-cache/generic/names"
            if not names.resolve().is_relative_to(root):
                raise ConfinementUnavailable("Private font cache escapes workspace")
            names.mkdir(parents=True, exist_ok=True)
            for name in ("luaotfload-names.lua.gz", "luaotfload-names.luc.gz"):
                source = Path("/var/lib/texmf/luatex-cache/generic/names") / name
                target = names / name
                if target.is_symlink():
                    raise ConfinementUnavailable("Private font index escapes workspace")
                if source.is_file() and not target.exists():
                    with source.open("rb") as stream:
                        data = stream.read(16 * 1024 * 1024 + 1)
                    if len(data) > 16 * 1024 * 1024:
                        raise ConfinementUnavailable("Image font index exceeds limit")
                    target.write_bytes(data)
            os.environ.update(
                TEXMFVAR=str(cache),
                TEXMFCACHE=str(cache) + ":/var/lib/texmf",
                TEXMFOUTPUT="/usr/share/texlive/texmf-dist",
            )
        os.closerange(3, 1048576)
        confine_engine(sys.argv[1])
    except (ConfinementUnavailable, OSError):
        sys.stderr.write("Engine kernel confinement unavailable\n")
        raise SystemExit(78) from None
    try:
        # Only the already confined engine receives the compatible input mode.
        os.environ["openin_any"] = "r"
        os.execv(executable, [executable, *sys.argv[3:]])
    except OSError:
        sys.stderr.write("Engine kernel confinement unavailable\n")
        raise SystemExit(78) from None


if __name__ == "__main__":
    main()
