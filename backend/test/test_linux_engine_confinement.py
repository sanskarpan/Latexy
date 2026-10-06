"""Real kernel denials, executed only in child processes; never sandbox pytest."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.latex_service import engine_env, engine_sandbox_flags, native_engine_command
from app.utils import linux_engine_sandbox as sandbox


def test_unavailable_kernel_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox.platform, "machine", lambda: "unsupported")
    with pytest.raises(sandbox.ConfinementUnavailable):
        sandbox.confine_engine(str(tmp_path))


@pytest.mark.skipif(sys.platform != "linux", reason="Linux kernel proof")
def test_real_kernel_blocks_network_reads_writes_and_process_control(tmp_path):
    code = """
import json,socket,os,sys
from app.utils.linux_engine_sandbox import confine_engine
abi=confine_engine(sys.argv[1]); result={"abi":abi}
for name,fn in [("tcp",lambda:socket.socket(socket.AF_INET,socket.SOCK_STREAM)),
                ("udp",lambda:socket.socket(socket.AF_INET,socket.SOCK_DGRAM)),
                ("unix",lambda:socket.socket(socket.AF_UNIX)),
                ("read",lambda:open('/etc/passwd')),
                ("write",lambda:open(sys.argv[2],'w')),
                ("signal",lambda:os.kill(os.getpid(),0)),
                ("fork",lambda:os.fork())]:
    try: fn();result[name]='ALLOWED'
    except PermissionError: result[name]='DENIED'
open(sys.argv[1]+'/allowed','w').write('OK')
print(json.dumps(result))
"""
    workspace = tmp_path / "job"
    workspace.mkdir()
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    result = subprocess.run(
        [sys.executable, "-c", code, str(workspace), str(tmp_path / "outside")],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        close_fds=True,
    )
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome.pop("abi") >= 3
    assert set(outcome.values()) == {"DENIED"}
    assert (workspace / "allowed").read_text() == "OK"


@pytest.mark.skipif(
    sys.platform != "linux"
    or not shutil.which("lualatex")
    or not Path("/var/lib/texmf/luatex-cache/generic/names/luaotfload-names.lua.gz").exists(),
    reason="Requires warmed production TeX image",
)
def test_real_lua_cannot_leak_raw_reads_loads_relative_or_symlink(tmp_path):
    workspace = tmp_path / "job"
    workspace.mkdir()
    secret = tmp_path / "outside.lua"
    secret.write_text("return 'AUDIT_PRIVATE_SENTINEL'", encoding="utf-8")
    (workspace / "linked.lua").symlink_to(secret)
    lua = """
local function audit(name,fn)
 local ok,value=pcall(fn)
 texio.write_nl('AUDIT '..name..' '..((ok and value) and 'ALLOWED' or 'DENIED'))
end
audit('OPEN',function() return io.open('/etc/passwd') end)
audit('LINES',function() local it=io.lines('/etc/passwd'); return it() end)
audit('ENVIRON',function() local it=io.lines('/proc/self/environ'); return it() end)
audit('LOADFILE',function() return loadfile('../outside.lua') end)
audit('DOFILE',function() return dofile('../outside.lua') end)
audit('SYMLINK',function() return io.open('linked.lua') end)
audit('WRITE',function() return io.open('../outside-write','w') end)
"""
    source = (
        r"\documentclass[11pt]{article}\usepackage{fontspec}\begin{document}Latin \textbf{Bold}\directlua{"
        + lua
        + r"}\end{document}"
    )
    (workspace / "resume.tex").write_text(source, encoding="utf-8")
    command = native_engine_command(
        "lualatex",
        [*engine_sandbox_flags("lualatex"), "-interaction=nonstopmode", "-halt-on-error", "resume.tex"],
        workspace,
    )
    result = subprocess.run(
        command,
        cwd=workspace,
        env=engine_env(workspace, "lualatex"),
        capture_output=True,
        text=True,
        timeout=25,
        close_fds=True,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr
    audits = [line for line in result.stdout.splitlines() if line.startswith("AUDIT ")]
    assert len(audits) == 7 and all(line.strip().endswith("DENIED") for line in audits)
    assert "AUDIT_PRIVATE_SENTINEL" not in result.stdout + (workspace / "resume.log").read_text()
    extracted = subprocess.run(
        ["pdftotext", str(workspace / "resume.pdf"), "-"], capture_output=True, text=True, check=True, timeout=5
    ).stdout
    assert "Latin" in extracted and "AUDIT_PRIVATE_SENTINEL" not in extracted
