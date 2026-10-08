"""Bounded, local parity probe for owned English resumes; no service dispatch.

Run from backend with PYTHONPATH=. and installed TeX/Poppler/SyncTeX. Each
condition has a fresh private workspace and normal engine confinement. Only
the fixed builder fixture enters TeX; source/format inputs are not accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import statistics
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from app.services.latex_service import (
    engine_env,
    engine_sandbox_flags,
    find_recorder_read_escape,
    native_engine_command,
)
from app.services.render_engine.managed_preamble import MANAGED_ENGLISH_FORMAT_ID, MANAGED_ENGLISH_PREAMBLE
from app.services.render_engine.passes import _RERUN
from app.services.render_engine.version import renderer_fingerprint
from app.services.resume_builder_service import resume_builder_service
from app.utils.bounded_io import MAX_COMPILE_LOG_BYTES, read_file_bounded, read_gzip_file_bounded
from scripts.benchmark_trusted_format import FIXTURE

CURRENT = r"\usepackage[hidelinks,bookmarks=false]{hyperref}"
PREVIOUS = r"\usepackage[hidelinks]{hyperref}"
EXPECTED_URLS = ["https://example.test/profile", "mailto:avery@example.test"]
PARITY_FIELDS = (
    "page_count", "text_sha256", "pixel_sha256", "geometry_sha256",
    "synctex_source_records_sha256", "synctex_view_coordinates", "annotation_urls",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def capture(command: list[str], directory: Path, env: dict[str, str], name: str) -> str:
    # Fixed, owned inputs only. Bound runtime and subsequent log reads as well.
    path = directory / name
    with path.open("wb") as output:
        result = subprocess.run(command, cwd=directory, env=env, stdout=output,
                                stderr=subprocess.STDOUT, timeout=30, check=False)
    log = read_file_bounded(path, MAX_COMPILE_LOG_BYTES).decode(errors="replace")
    if result.returncode:
        raise RuntimeError(f"{command[0]} failed: {log[-2000:]}")
    return log


def render(directory: Path, source: str, compiler: str, fmt: Path | None = None) -> dict:
    directory.mkdir()
    (directory / "resume.tex").write_text(source, encoding="utf-8")
    env = engine_env(directory, compiler)
    arguments = [*engine_sandbox_flags(compiler), "-interaction=nonstopmode", "-halt-on-error", "-synctex=1"]
    if fmt:
        shutil.copyfile(fmt, directory / fmt.name)
        arguments.append("-fmt=" + fmt.stem)
    command = native_engine_command(compiler, arguments + ["-jobname=resume", "resume.tex"], directory)
    started = time.perf_counter()
    warnings = []
    for number in (1, 2, 3):
        log = capture(command, directory, env, f"pass-{number}.txt")
        if find_recorder_read_escape(directory / "resume.fls", str(directory), require_recorder=True):
            raise RuntimeError("Recorder confinement failed")
        if re.search(r"Missing character|^!", log, re.M):
            raise RuntimeError("Missing glyph or TeX error; cannot establish parity")
        warnings.append([line for line in log.splitlines() if _RERUN.search(line)])
        if not _RERUN.search(log):
            break
    else:
        raise RuntimeError("Unchanged rerun policy did not converge in three passes")
    elapsed = time.perf_counter() - started
    capture(["pdftotext", "-layout", "resume.pdf", "text.txt"], directory, env, "text.log")
    capture(["pdftotext", "-bbox-layout", "resume.pdf", "geometry.xhtml"], directory, env, "bbox.log")
    geometry = [{"page": dict(page.attrib), "words": [
        {"text": word.text or "", **word.attrib} for word in page.iter()
        if word.tag.rsplit("}", 1)[-1] == "word"]}
        for page in ET.fromstring(read_file_bounded(directory / "geometry.xhtml", 1024 * 1024)).iter()
        if page.tag.rsplit("}", 1)[-1] == "page"]
    capture(["pdftoppm", "-r", "72", "-singlefile", "-png", "resume.pdf", "page"], directory, env, "pixels.log")
    info = capture(["pdfinfo", "resume.pdf"], directory, env, "info.log")
    pages = int(re.search(r"^Pages:\s*(\d+)", info, re.M)[1])
    if pages != 1:
        raise RuntimeError("Fixed fixture must remain one page; pixel probe covers one page")
    links = capture(["pdfinfo", "-url", "resume.pdf"], directory, env, "links.log")
    urls = sorted(set(re.findall(r"(?:https?://|mailto:)[^\s]+", links)))
    if urls != EXPECTED_URLS:
        raise RuntimeError("URL/email annotations were not retained")
    line = next(n for n, value in enumerate(source.splitlines(), 1) if "Avery Example" in value)
    view = capture(["synctex", "view", "-i", f"{line}:1:resume.tex", "-o", "resume.pdf"], directory, env, "sync.log")
    coordinates = re.findall(r"^(?:Page|h|v|W|H):(.+)$", view, re.M)
    if len(coordinates) != 5:
        raise RuntimeError("SyncTeX forward mapping unavailable")
    sync = read_gzip_file_bounded(directory / "resume.synctex.gz", max_compressed_bytes=1024 * 1024,
                                 max_decompressed_bytes=4 * 1024 * 1024).decode(errors="replace")
    tags = {tag for tag, filename in re.findall(r"^Input:(\d+):(.+)$", sync, re.M)
            if filename.endswith("/resume.tex") or filename == "resume.tex"}
    records = []
    for record in sync.splitlines():
        match = re.match(r"^.(-?\d+),(\d+)(?:,\d+)?:", record)
        if match and match[1] in tags:
            records.append(re.sub(r"^(.)(-?\d+),", r"\1SOURCE,", record))
    if not records:
        raise RuntimeError("SyncTeX source records unavailable")
    return {"elapsed_seconds": elapsed, "passes": number, "page_count": pages,
            "source_sha256": digest(source.encode()), "rerun_messages_by_pass": warnings,
            "text_sha256": digest(read_file_bounded(directory / "text.txt", 1024 * 1024)),
            "pixel_sha256": digest(read_file_bounded(directory / "page.png", 16 * 1024 * 1024)),
            "geometry_sha256": digest(json.dumps(geometry, sort_keys=True, separators=(",", ":")).encode()),
            "synctex_source_line": line, "synctex_view_coordinates": coordinates,
            "synctex_source_records": len(records), "synctex_source_records_sha256": digest("\n".join(records).encode()),
            "annotation_urls": urls, "missing_glyph_warning": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", choices=("lualatex", "pdflatex"), required=True)
    parser.add_argument("--pairs", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-owned-format", action="store_true",
                        help="Also privately build/render v2 pdflatex format; never installs an image asset")
    args = parser.parse_args()
    if not 1 <= args.pairs <= 5:
        parser.error("--pairs must be between 1 and 5")
    if args.verify_owned_format and args.compiler != "pdflatex":
        parser.error("Owned formats currently support pdflatex only")
    evidence = {"schema_version": 1, "compiler": args.compiler, "owned_format_id": MANAGED_ENGLISH_FORMAT_ID,
                "scope": "Fixed English builder with synthetic hyperlink probes; fresh workspaces; TeX process/convergence only; no latency SLO claim",
                "confinement": "Minimal engine environment, no-shell-escape, recorder checks; Lua uses mandatory Linux kernel launcher",
                "renderer_fingerprint": renderer_fingerprint(), "samples": [], "parity": []}
    try:
        original = resume_builder_service.render(FIXTURE, "ats_safe").latex_content
        if original.count(CURRENT) != 1 or original.count(PREVIOUS):
            raise RuntimeError("Expected exactly one current owned hyperref declaration")
        evidence["builder_source_sha256"] = digest(original.encode())
        candidate = original.replace(r"\end{document}", r"\par\href{mailto:avery@example.test}{Email probe} "
                                     r"\href{https://example.test/profile}{Website probe}" + "\n" + r"\end{document}")
        baseline = candidate.replace(CURRENT, PREVIOUS)
        if len(baseline.splitlines()) != len(candidate.splitlines()):
            raise RuntimeError("Source line identity changed")
        with tempfile.TemporaryDirectory(prefix="latexy-owned-bookmarks-") as temporary:
            root = Path(temporary)
            for pair in range(args.pairs):
                results = {}
                order = ("baseline", "candidate") if pair % 2 == 0 else ("candidate", "baseline")
                for condition in order:
                    result = render(root / f"pair-{pair}-{condition}", baseline if condition == "baseline" else candidate, args.compiler)
                    results[condition] = result
                    evidence["samples"].append({"pair": pair, "condition": condition, **result})
                    print(json.dumps({"pair": pair, "condition": condition, "passes": result["passes"],
                                      "elapsed_seconds": result["elapsed_seconds"]}), flush=True)
                parity = {field: results["baseline"][field] == results["candidate"][field] for field in PARITY_FIELDS}
                evidence["parity"].append({"pair": pair, **parity})
                if not all(parity.values()) or results["baseline"]["passes"] != 2 or results["candidate"]["passes"] != 1:
                    raise RuntimeError("Expected rendered/source parity and two-to-one pass reduction were not verified")
            if args.verify_owned_format:
                build = root / "format-build"
                build.mkdir()
                (build / "owned.tex").write_text(MANAGED_ENGLISH_PREAMBLE + "\\begin{document}\n\\end{document}\n", encoding="utf-8")
                capture(["pdflatex", "-ini", *engine_sandbox_flags("pdflatex"), "-interaction=nonstopmode", "-halt-on-error",
                         "-jobname=" + MANAGED_ENGLISH_FORMAT_ID, "&pdflatex", "mylatexformat.ltx", "owned.tex"],
                        build, engine_env(build, "pdflatex"), "build.log")
                if find_recorder_read_escape(build / (MANAGED_ENGLISH_FORMAT_ID + ".fls"), str(build), require_recorder=True):
                    raise RuntimeError("Format build recorder confinement failed")
                fmt = build / (MANAGED_ENGLISH_FORMAT_ID + ".fmt")
                if not 1024 <= fmt.stat().st_size <= 16 * 1024 * 1024:
                    raise RuntimeError("Format build outside trusted size bound")
                built = render(root / "owned-v2-render", candidate, "pdflatex", fmt)
                parity = {field: built[field] == results["candidate"][field] for field in PARITY_FIELDS}
                evidence["owned_format_build"] = {"format_size": fmt.stat().st_size, "format_sha256": digest(fmt.read_bytes()),
                                                 "render": built, "parity": parity}
                if not all(parity.values()) or built["passes"] != 1:
                    raise RuntimeError("Owned v2 private format changed output or convergence")
        evidence["medians_seconds"] = {condition: statistics.median(
            row["elapsed_seconds"] for row in evidence["samples"] if row["condition"] == condition)
            for condition in ("baseline", "candidate")}
        evidence["verified"] = True
    except Exception as exc:
        evidence["verified"] = False
        evidence["error"] = str(exc)
    args.output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if not evidence["verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
