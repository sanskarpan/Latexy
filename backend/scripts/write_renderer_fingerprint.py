"""Build-time engine/font/format identity; contains no application credentials."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def tree_digest(roots: list[Path], suffixes: set[str]) -> str:
    digest = hashlib.sha256()
    files = sorted({path.resolve() for root in roots if root.is_dir() for path in root.rglob("*")
                    if path.is_file() and path.suffix.lower() in suffixes})
    for path in files:
        digest.update(str(path).encode())
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def main():
    def kpse(name):
        return Path(subprocess.check_output(["kpsewhich", f"-var-value={name}"], text=True).strip())

    engines = {}
    for name in ("pdflatex", "xelatex", "lualatex"):
        binary = Path(shutil.which(name) or "")
        if not binary.is_file():
            raise RuntimeError("Required compiler unavailable at image build")
        engines[name] = {
            "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "version": subprocess.check_output([name, "--version"], text=True).splitlines()[0],
        }
    packages = subprocess.check_output(["dpkg-query", "-W", "-f=${Package}=${Version}\n"], text=True)
    selected = sorted(line for line in packages.splitlines() if line.startswith(("texlive", "fonts-", "fontconfig", "libfreetype", "libharfbuzz")))
    seed = Path("/usr/local/bin/latexy-warm-tex-cache")
    report = {
        "schema_version": 1,
        "compilers": engines,
        "packages_sha256": hashlib.sha256("\n".join(selected).encode()).hexdigest(),
        "font_assets_sha256": tree_digest([kpse("TEXMFDIST") / "fonts", Path("/usr/share/fonts"), Path("/usr/local/share/fonts")],
                                           {".otf", ".ttf", ".ttc", ".tfm", ".pfb", ".afm"}),
        "format_assets_sha256": tree_digest([kpse("TEXMFSYSVAR") / "web2c"], {".fmt", ".base"}),
        "trusted_format_manifest_sha256": hashlib.sha256(Path("/opt/latexy-trusted-formats.json").read_bytes()).hexdigest()
            if Path("/opt/latexy-trusted-formats.json").is_file() else "unavailable",
        "cache_seed_script_sha256": os.environ.get("LATEXY_CACHE_SEED_SHA256") or (hashlib.sha256(seed.read_bytes()).hexdigest() if seed.exists() else "unavailable"),
    }
    report["fingerprint_sha256"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    output = Path("/opt/latexy-renderer-version.json")
    output.write_text(json.dumps(report, sort_keys=True, indent=2), encoding="utf-8")
    output.chmod(0o444)
    print(json.dumps({"renderer_assets_fingerprint": report["fingerprint_sha256"]}))


if __name__ == "__main__":
    main()
