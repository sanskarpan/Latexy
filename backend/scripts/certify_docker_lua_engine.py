"""Offline real Docker helper proof; cached image only, no build or network."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.latex_service import docker_engine_command, docker_sandbox_args


def main():
    docker = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe" if sys.platform == "win32" else "docker"
    with tempfile.TemporaryDirectory(prefix="latexy-docker-lua-") as directory:
        root = Path(directory)
        lua = r"""
local function audit(name,fn)
 local ok,value=pcall(fn)
 texio.write_nl('AUDIT '..name..' '..((ok and value) and 'ALLOWED' or 'DENIED'))
end
audit('OPEN',function() return io.open('/etc/passwd') end)
audit('LINES',function() local it=io.lines('/etc/passwd'); return it() end)
audit('ENVIRON',function() local it=io.lines('/proc/self/environ'); return it() end)
audit('WRITE',function() return io.open('/tmp/outside-write','w') end)
"""
        source = r"\documentclass[11pt]{article}\usepackage{fontspec}\begin{document}Latin \textbf{Bold}\directlua{" + lua + r"}\end{document}"
        (root / "resume.tex").write_text(source, encoding="utf-8")
        command = [docker, "run", "--rm", *docker_sandbox_args("/workspace", "lualatex"),
                   "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m", "-v", f"{root}:/workspace:rw",
                   "-w", "/workspace", "latexy-engine-certification:20261006",
                   *docker_engine_command("lualatex", ["-no-shell-escape", "-recorder", "-interaction=nonstopmode",
                                                        "-halt-on-error", "resume.tex"])]
        outcome = subprocess.run(command, capture_output=True, timeout=60)
        lines = outcome.stdout.decode("utf-8", "replace").splitlines()
        audits = [line for line in lines if line.startswith("AUDIT ")]
        result = {"returncode": outcome.returncode, "pdf": (root / "resume.pdf").is_file(),
                  "four_denied": len(audits) == 4 and all(line.strip().endswith("DENIED") for line in audits)}
        print(json.dumps(result))
        if outcome.returncode or not result["pdf"] or not result["four_denied"]:
            print(outcome.stderr.decode("utf-8", "replace")[-2000:])
            raise SystemExit(1)


if __name__ == "__main__":
    main()
