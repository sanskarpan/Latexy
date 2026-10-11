"""Offline disposable-container probe; does not expose read file contents."""

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from app.services.latex_service import engine_env, find_recorder_read_escape


def probe(policy, safer, output_root=False):
    with tempfile.TemporaryDirectory(prefix="lua-path-audit-") as folder:
        root = Path(folder)
        outside = root.parent / (root.name + "-outside.lua")
        outside.write_text("return 'AUDIT CONSTANT'", encoding="utf-8")
        lua = """
local function mark(name, fn)
 local ok, value = pcall(fn)
 texio.write_nl('AUDIT '..name..' '..((ok and value) and 'ALLOWED' or 'DENIED'))
end
local function read(path)
 local f=io.open(path); if not f then return false end
 local x=f:read(1); f:close(); return x ~= nil
end
mark('HOSTNAME', function() return read('/etc/hostname') end)
mark('PASSWD', function() return read('/etc/passwd') end)
mark('ENVIRON', function() return read('/proc/self/environ') end)
mark('OUTSIDE', function() return read('OUTSIDE_PATH') end)
mark('ENCODED', function() return read(string.char(47,101,116,99,47,112,97,115,115,119,100)) end)
mark('LINES', function() local f=io.lines('/etc/passwd'); return f() ~= nil end)
mark('ENVLINES', function() local f=io.lines('/proc/self/environ'); return f() ~= nil end)
mark('LOADFILE', function() return loadfile('OUTSIDE_PATH') ~= nil end)
mark('DOFILE', function() return dofile('OUTSIDE_PATH') ~= nil end)
mark('EXECUTE', function() local ok=os.execute('/bin/true'); return ok ~= nil and ok ~= false end)
mark('POPEN', function() local f=io.popen('/bin/true'); if not f then return false end; f:close(); return true end)
mark('LOADLIB', function() return package.loadlib('/lib/x86_64-linux-gnu/libc.so.6','getpid') ~= nil end)
""".replace("OUTSIDE_PATH", str(outside))
        source = r"\documentclass{article}\begin{document}\directlua{" + lua + r"}x\end{document}"
        (root / "resume.tex").write_text(source, encoding="utf-8")
        env = engine_env(root)
        for table in root.glob("*.txt"):
            table.unlink()
        names = root / ".tex-cache/luatex-cache/generic/names"
        names.mkdir(parents=True, exist_ok=True)
        for name in ("luaotfload-names.lua.gz", "luaotfload-names.luc.gz"):
            shutil.copyfile(Path("/var/lib/texmf/luatex-cache/generic/names") / name, names / name)
        env["openin_any"] = policy
        if output_root:
            env["TEXMFOUTPUT"] = "/usr/share/texlive/texmf-dist"
        args = ["lualatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "-recorder"]
        if safer:
            args.append("--safer")
        args.append("resume.tex")
        started = time.monotonic()
        try:
            result = subprocess.run(
                args, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=25
            )
        except subprocess.TimeoutExpired as exc:
            print(
                json.dumps(
                    {
                        "policy": policy,
                        "safer": safer,
                        "timeout": True,
                        "seconds": time.monotonic() - started,
                        "cache_scan": b"Font names database not found" in (exc.stdout or b""),
                    }
                )
            )
            return
        output = result.stdout.decode("utf-8", "replace")
        recorder = root / "resume.fls"
        pdf = root / "resume.pdf"
        extracted = ""
        if pdf.exists():
            extracted = subprocess.run(
                ["pdftotext", str(pdf), "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3
            ).stdout.decode()
        print(
            json.dumps(
                {
                    "policy": policy,
                    "safer": safer,
                    "trusted_output_root": output_root,
                    "exit": result.returncode,
                    "seconds": time.monotonic() - started,
                    "read_allowed": "READ ALLOWED" in extracted,
                    "read_denied": "READ DENIED" in extracted,
                    "recorded_escape": find_recorder_read_escape(recorder, str(root)) if recorder.exists() else None,
                    "hostname_recorded": "hostname" in recorder.read_text() if recorder.exists() else False,
                    "passwd_recorded": "/etc/passwd" in recorder.read_text() if recorder.exists() else False,
                    "environ_recorded": "/proc/self/environ" in recorder.read_text() if recorder.exists() else False,
                    "outside_recorded": str(outside) in recorder.read_text() if recorder.exists() else False,
                    "class_missing": "article.cls' not found" in output,
                    "cache_scan": "Font names database not found" in output,
                    "last_error": next((line[:220] for line in output.splitlines() if line.startswith("!")), None),
                    "api_results": [line for line in output.splitlines() if line.startswith("AUDIT ")],
                }
            )
        )
        outside.unlink(missing_ok=True)


for policy, safer, output_root in (("r", True, False), ("p", False, True), ("p", True, True)):
    probe(policy, safer, output_root)
