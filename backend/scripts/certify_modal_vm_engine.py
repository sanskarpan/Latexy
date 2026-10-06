"""Explicit operator-only cached-image VM proof; never deploys an application.

One VM, 300-second hard TTL, 2 CPU/2 GiB ceiling. No image build, secrets,
volumes, networking or OIDC. Only booleans and fabricated probe text printed.
"""

import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.render_engine.modal_sandbox import ModalEngineProcess, create_modal_engine


def audit_denials(output: bytes, expected: int) -> bool:
    # TeX can append page/font diagnostics to the same line after a marker.
    audits = re.findall(r"(?m)^\s*AUDIT [A-Z]+ (DENIED|ALLOWED)\b", output.decode("utf-8", "replace"))
    return len(audits) == expected and all(verdict == "DENIED" for verdict in audits)


def main():
    import modal

    image_id = "im-1fho7eMXjj9Z60ziS7Kf6J"
    sandbox = None
    with tempfile.TemporaryDirectory(prefix="latexy-vm-proof-") as directory:
        workspace = Path(directory)
        lua = r"""
local function audit(name,fn)
 local ok,value=pcall(fn)
 texio.write_nl('AUDIT '..name..' '..((ok and value) and 'ALLOWED' or 'DENIED'))
end
audit('ROOT',function() return io.open('/root/private-probe') end)
audit('ENVIRON',function() local it=io.lines('/proc/1/environ'); return it() end)
audit('BOOTSTRAP',function() return io.open('/tmp/latexy-sandbox-bootstrap/sandbox_io_bridge.py','w') end)
"""
        source = r"\documentclass[11pt]{article}\usepackage{fontspec}\begin{document}Latin \textbf{Bold}\directlua{" + lua + r"}\end{document}"
        (workspace / "resume.tex").write_text(source, encoding="utf-8")
        arguments = ["-no-shell-escape", "-recorder", "-interaction=nonstopmode", "-halt-on-error", "resume.tex"]
        app = modal.App("latexy-engine-vm-certification-20261007")
        try:
            with app.run():
                process = create_modal_engine(workspace=workspace, compiler="lualatex", arguments=arguments,
                                              timeout=300, sdk=modal, app=app, enabled=True, image_id=image_id,
                                              policy="credential_free_vm")
                sandbox = process.sandbox
                code = process.wait(timeout=90)
                output = b""
                while chunk := process.stdout.read(8192):
                    output += chunk
                denied = audit_denials(output, 3)
                print(json.dumps({"case": "fontspec_and_hostile_reads", "returncode": code,
                                  "pdf": (workspace / "resume.pdf").is_file(),
                                  "three_private_denied": denied}))
                if code or not denied:
                    evidence = Path(__file__).resolve().parents[1] / "temp" / ("vm-certification-failure-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
                    evidence.mkdir(parents=True, exist_ok=False)
                    for name in ("resume.tex", "resume.log", "resume.fls"):
                        if (workspace / name).is_file():
                            shutil.copyfile(workspace / name, evidence / name)
                    (evidence / "engine.stdout").write_bytes(output)
                    print(json.dumps({"private_failure_artifacts": str(evidence)}))
                    raise RuntimeError("VM confinement/fontspec proof failed")
                cases = {
                    "hindi": r"\documentclass[11pt]{article}\usepackage{fontspec}\usepackage{polyglossia}\setmainlanguage{english}\setotherlanguage{hindi}\newfontfamily\hindifont[Renderer=HarfBuzz,Script=Devanagari]{Noto Sans Devanagari}\begin{document}\texthindi{हिंदी}\end{document}",
                    "cjk": r"\documentclass{article}\usepackage{luatexja-fontspec}\setmainjfont{Noto Sans CJK JP}\begin{document}日本語\end{document}",
                }
                for name, text in cases.items():
                    (workspace / "resume.pdf").unlink(missing_ok=True)
                    sandbox.filesystem.write_bytes(text.encode("utf-8"), "/workspace/resume.tex")
                    remote = sandbox.exec("python3", "/tmp/latexy-sandbox-bootstrap/sandbox_io_bridge.py",
                                          "/workspace", "lualatex", "--credential-free-vm", *arguments, timeout=75,
                                          workdir="/workspace", text=False, secrets=[])
                    child = ModalEngineProcess(sandbox, remote, workspace, "resume")
                    code = child.wait(timeout=80)
                    print(json.dumps({"case": name, "returncode": code, "pdf": (workspace / "resume.pdf").is_file()}))
                    if code or not (workspace / "resume.pdf").is_file():
                        raise RuntimeError("VM multilingual proof failed")
        finally:
            if sandbox is not None:
                sandbox.terminate(wait=False)


if __name__ == "__main__":
    main()
