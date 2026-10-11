"""Offline reproduction of the credential-free VM UID/cache profile."""

import ast
import json
import subprocess
import sys
from pathlib import Path


def main():
    root = Path("/workspace")
    root.mkdir(exist_ok=True)
    # Read only constant fixture assignments from the certificate, preserving
    # precisely the same TeX/Lua tokenization as the failed cloud proof.
    tree = ast.parse(Path(__file__).with_name("certify_modal_vm_engine.py").read_text(encoding="utf-8"))
    lua = next(node.value.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "lua" for t in node.targets))
    source = r"\documentclass[11pt]{article}\usepackage{fontspec}\begin{document}Latin \textbf{Bold}\directlua{" + lua + r"}\end{document}"
    bridge = Path(__file__).resolve().parents[1] / "app/utils/sandbox_io_bridge.py"
    cases = next(ast.literal_eval(node.value) for node in ast.walk(tree) if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "cases" for t in node.targets))
    for name, text in {"fontspec_and_hostile_reads": source, **cases}.items():
        (root / "resume.pdf").unlink(missing_ok=True)
        (root / "resume.tex").write_text(text, encoding="utf-8")
        outcome = subprocess.run([sys.executable, str(bridge), str(root), "lualatex", "--credential-free-vm",
                              "-no-shell-escape", "-recorder", "-interaction=nonstopmode", "-halt-on-error", "resume.tex"],
                             capture_output=True, timeout=45)
        output = (root / "engine.stdout").read_text(encoding="utf-8", errors="replace")
        print(json.dumps({"case": name, "returncode": outcome.returncode, "pdf": (root / "resume.pdf").is_file()}))
    # This fixed fabricated Latin fixture contains no user data or credentials.
        if outcome.returncode:
            print(output[-2500:])
            print(outcome.stderr.decode("utf-8", "replace")[-1000:])
            raise SystemExit(1)


if __name__ == "__main__":
    main()
