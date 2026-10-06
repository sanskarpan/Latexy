"""Build an immutable pdflatex format from repository-owned source at image build.

There is deliberately no source/format argument. Runtime jobs cannot call this
script to dump user documents, and absent assets always use ordinary pdflatex.
"""
from __future__ import annotations

import hashlib
import json
import runpy
import shutil
import subprocess
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    owned = Path(__file__).resolve().parents[1] / "app/services/render_engine/managed_preamble.py"
    constants = runpy.run_path(str(owned))
    preamble = constants["MANAGED_ENGLISH_PREAMBLE"]
    name = constants["MANAGED_ENGLISH_FORMAT_ID"]
    binary = Path(shutil.which("pdflatex") or "").resolve(strict=True)
    version = subprocess.check_output([str(binary), "--version"], text=True).splitlines()[0]
    with tempfile.TemporaryDirectory(prefix="latexy-owned-format-") as temporary:
        workspace = Path(temporary)
        source = workspace / "owned.tex"
        source.write_text(preamble + r"\begin{document}" + "\n" + r"\end{document}" + "\n", encoding="utf-8")
        result = subprocess.run([str(binary), "-ini", "-recorder", "-interaction=nonstopmode",
            "-halt-on-error", "-no-shell-escape", "-jobname=" + name,
            "&pdflatex", "mylatexformat.ltx", "owned.tex"], cwd=workspace,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, check=False)
        if result.returncode:
            raise RuntimeError("Owned format build failed: " + result.stdout.decode(errors="replace")[-2000:])
        dependencies = {}
        for line in (workspace / (name + ".fls")).read_text().splitlines():
            if line.startswith("INPUT "):
                path = Path(line[6:])
                path = (workspace / path).resolve() if not path.is_absolute() else path.resolve()
                if path.is_file() and not path.is_relative_to(workspace):
                    dependencies[str(path)] = sha256(path)
        if not dependencies:
            raise RuntimeError("Owned format build has no recorded dependencies")
        generated = workspace / (name + ".fmt")
        size = generated.stat().st_size
        if not 1024 <= size <= 16 * 1024 * 1024:
            raise RuntimeError("Owned format size outside trusted bound")
        target = Path("/var/lib/texmf/web2c/pdftex") / generated.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(generated, target)
        target.chmod(0o444)
        profile = {"profile_id": name, "compiler": "pdflatex", "format_path": str(target),
            "format_size": size, "format_sha256": sha256(target),
            "preamble_sha256": hashlib.sha256(preamble.encode()).hexdigest(),
            "compiler_binary_sha256": sha256(binary), "compiler_version": version,
            "dependencies_sha256": hashlib.sha256(json.dumps(dependencies, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        profile["identity_sha256"] = hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        output = Path("/opt/latexy-trusted-formats.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"schema_version": 1, "profiles": [profile]}, sort_keys=True, indent=2), encoding="utf-8")
        output.chmod(0o444)
        subprocess.run(["mktexlsr", "/var/lib/texmf"], check=True, timeout=60)
        print(json.dumps({"owned_format_identity": profile["identity_sha256"], "format_size": size}))


if __name__ == "__main__":
    main()
