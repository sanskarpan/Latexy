"""Explicit operator-only cached-image VM proof; never deploys an application.

One VM, 300-second hard TTL, 2 CPU/2 GiB ceiling. No image build, secrets,
volumes, networking or OIDC. Only booleans and fabricated probe text printed.
"""

import json
import os
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.render_engine.modal_sandbox import ModalEngineProcess, create_modal_engine

MAX_FIXTURE_PDF_BYTES = 4 * 1024 * 1024
MAX_FIXTURE_TEXT_BYTES = 256 * 1024
PDFTOTEXT_TIMEOUT_SECONDS = 10


def audit_denials(output: bytes, expected: int) -> bool:
    # TeX can append page/font diagnostics to the same line after a marker.
    audits = re.findall(r"(?m)^\s*AUDIT [A-Z]+ (DENIED|ALLOWED)\b", output.decode("utf-8", "replace"))
    return len(audits) == expected and all(verdict == "DENIED" for verdict in audits)


def _extract_fixture_text(pdf: Path, pdftotext_bin: str) -> str | None:
    """Extract bounded fixture text with the production primary Poppler tool."""
    if pdf.stat().st_size > MAX_FIXTURE_PDF_BYTES:
        return None

    process = None
    selector = None
    output = bytearray()
    deadline = time.monotonic() + PDFTOTEXT_TIMEOUT_SECONDS
    try:
        process = subprocess.Popen(
            [pdftotext_bin, "-layout", "-enc", "UTF-8", str(pdf), "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        if process.stdout is None:
            return None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                return None
            chunk = os.read(process.stdout.fileno(), min(8192, MAX_FIXTURE_TEXT_BYTES + 1 - len(output)))
            if not chunk:
                process.wait(timeout=max(0, deadline - time.monotonic()))
                if process.returncode != 0:
                    return None
                return output.decode("utf-8", errors="strict")
            output.extend(chunk)
            if len(output) > MAX_FIXTURE_TEXT_BYTES:
                return None
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError, ValueError):
        return None
    finally:
        if selector is not None:
            selector.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=1)
                except subprocess.SubprocessError:
                    pass
            if process.stdout is not None:
                process.stdout.close()


def verify_fixture(
    workspace: Path, basename: str, expected_text: str, *, pdftotext_bin: str | None = None
) -> bool:
    """A stale/empty PDF or missing glyphs cannot certify a language fixture."""
    pdf, log = workspace / f"{basename}.pdf", workspace / f"{basename}.log"
    if not pdf.is_file() or not log.is_file() or not pdf.stat().st_size:
        return False
    if re.search(r"Missing character|^!", log.read_text(encoding="utf-8", errors="replace"), re.MULTILINE):
        return False
    pdftotext_bin = pdftotext_bin or shutil.which("pdftotext")
    if not pdftotext_bin:
        return False
    extracted = _extract_fixture_text(pdf, pdftotext_bin)
    if extracted is None:
        return False
    extracted = unicodedata.normalize("NFKC", extracted)
    return unicodedata.normalize("NFKC", expected_text) in extracted


def main():
    pdftotext_bin = shutil.which("pdftotext")
    if not pdftotext_bin:
        raise RuntimeError("pdftotext (Poppler) is required in the operator environment before VM certification")

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
                marker = sandbox.exec(
                    "python3", "-c",
                    "import json; print(json.load(open('/opt/latexy-renderer-version.json')).get('fingerprint_sha256'))",
                    timeout=10, text=False, secrets=[],
                )
                marker_output = marker.stdout.read()
                assets = marker_output.decode("ascii", errors="replace").strip() if len(marker_output) <= 128 else ""
                asset_fingerprint_discovered = marker.wait() == 0 and bool(re.fullmatch(r"[0-9a-f]{64}", assets))
                print(json.dumps({"image_id": image_id,
                                  "assets_fingerprint": assets if asset_fingerprint_discovered else None,
                                  "asset_fingerprint_discovered": asset_fingerprint_discovered,
                                  "asset_identity_comparison": "not_configured"}))
                code = process.wait(timeout=90)
                output = b""
                while chunk := process.stdout.read(8192):
                    output += chunk
                denied = audit_denials(output, 3)
                text_checked = verify_fixture(workspace, "resume", "Latin", pdftotext_bin=pdftotext_bin)
                print(json.dumps({"case": "fontspec_and_hostile_reads", "returncode": code,
                                  "pdf": (workspace / "resume.pdf").is_file(),
                                  "three_private_denied": denied, "text_and_glyphs_checked": text_checked}))
                if code or not denied or not text_checked:
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
                    # Unrelated documents must not inherit each other's aux
                    # macros or a stale PDF. Keep the VM/font cache warm, but
                    # give every fixture its own TeX output namespace.
                    case_arguments = [f"-jobname={name}", *arguments]
                    sandbox.filesystem.write_bytes(text.encode("utf-8"), "/workspace/resume.tex")
                    remote = sandbox.exec("python3", "/tmp/latexy-sandbox-bootstrap/sandbox_io_bridge.py",
                                          "/workspace", "lualatex", "--credential-free-vm", *case_arguments, timeout=75,
                                          workdir="/workspace", text=False, secrets=[])
                    child = ModalEngineProcess(sandbox, remote, workspace, name)
                    code = child.wait(timeout=80)
                    text_checked = verify_fixture(
                        workspace,
                        name,
                        "हिंदी" if name == "hindi" else "日本語",
                        pdftotext_bin=pdftotext_bin,
                    )
                    print(json.dumps({"case": name, "returncode": code, "pdf": (workspace / f"{name}.pdf").is_file(),
                                      "text_and_glyphs_checked": text_checked}))
                    if code or not text_checked:
                        evidence = Path(__file__).resolve().parents[1] / "temp" / ("vm-certification-failure-" + name + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
                        evidence.mkdir(parents=True, exist_ok=False)
                        for artifact in ("resume.tex", f"{name}.log", f"{name}.fls", f"{name}.pdf"):
                            if (workspace / artifact).is_file():
                                shutil.copyfile(workspace / artifact, evidence / artifact)
                        (evidence / "engine.stdout").write_bytes(child.stdout.read(262144))
                        print(json.dumps({"private_failure_artifacts": str(evidence)}))
                        raise RuntimeError("VM multilingual proof failed")
                if not asset_fingerprint_discovered:
                    raise RuntimeError("VM fixtures passed but immutable renderer asset identity is unavailable")
        finally:
            if sandbox is not None:
                sandbox.terminate(wait=False)


if __name__ == "__main__":
    main()
