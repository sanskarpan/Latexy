"""Credential-free real-TeX certification matrix, separate from browser SLOs.

Run in the worker image with --network none and a read-only backend mount.
Every shipped fixture is compiled with the same template preprocessing/default
engine, recorder confinement, bounded diagnostics and PDF checks. Raw timings
are retained; failed fixtures cannot enter the certified warm-path corpus.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from app.scripts.compile_templates import _prepare_template
from app.services.latex_service import (
    engine_env,
    engine_sandbox_flags,
    find_recorder_read_escape,
    native_engine_command,
)
from app.utils.bounded_io import MAX_COMPILED_PDF_BYTES, read_file_bounded


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else None


def certify(path: Path, root: Path, samples: int, timeout: float, render_directory: Path | None = None) -> dict:
    original = path.read_text(encoding="utf-8")
    source, compiler = _prepare_template(original)
    entry = {
        "fixture": path.relative_to(root).as_posix(),
        "category": path.parent.name,
        "source_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "prepared_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "compiler": compiler,
        "capacity_class": "presentation" if path.parent.name == "presentation" else "resume",
        "samples": [],
    }
    for index in range(samples):
        with tempfile.TemporaryDirectory(prefix="resume-cert-") as directory:
            workspace = Path(directory)
            (workspace / "resume.tex").write_text(source, encoding="utf-8")
            sample = {"index": index, "passes_seconds": [], "success": False}
            started = time.perf_counter()
            try:
                for pass_index in range(2):
                    tick = time.perf_counter()
                    with (workspace / "diagnostics.txt").open("wb") as transcript:
                        result = subprocess.run(
                            native_engine_command(compiler, ["-interaction=nonstopmode", "-halt-on-error", "-synctex=1",
                             *engine_sandbox_flags(compiler), "resume.tex"], workspace),
                            cwd=workspace, env=engine_env(workspace, compiler), stdout=transcript,
                            stderr=subprocess.STDOUT, timeout=timeout,
                        )
                    sample["passes_seconds"].append(time.perf_counter() - tick)
                    escape = find_recorder_read_escape(
                        workspace / "resume.fls", str(workspace), require_recorder=result.returncode == 0,
                    )
                    if escape:
                        raise RuntimeError("recorder_confinement_failed")
                    if result.returncode != 0:
                        diagnostic = read_file_bounded(workspace / "diagnostics.txt", 2 * 1024 * 1024).decode("utf-8", errors="replace")
                        sample["diagnostics"] = [line[:300] for line in diagnostic.splitlines() if line.startswith(("!", "l."))][-8:]
                        raise RuntimeError(f"tex_pass_{pass_index + 1}_exit_{result.returncode}")
                pdf = read_file_bounded(workspace / "resume.pdf", MAX_COMPILED_PDF_BYTES)
                if not pdf.startswith(b"%PDF-"):
                    raise RuntimeError("invalid_pdf_header")
                extraction = subprocess.run(
                    ["pdftotext", "-layout", str(workspace / "resume.pdf"), str(workspace / "text.txt")],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                )
                if extraction.returncode:
                    raise RuntimeError("text_extraction_failed")
                text = read_file_bounded(workspace / "text.txt", 2 * 1024 * 1024).decode("utf-8", errors="replace")
                if not text.strip():
                    raise RuntimeError("empty_pdf_text")
                info = subprocess.run(["pdfinfo", str(workspace / "resume.pdf")], capture_output=True, text=True, timeout=10)
                pages = next((int(line.partition(":")[2].strip()) for line in info.stdout.splitlines() if line.startswith("Pages:")), None)
                log = read_file_bounded(workspace / "resume.log", 2 * 1024 * 1024).decode("utf-8", errors="replace")
                sample["missing_glyphs"] = log.count("Missing character:")
                sample["font_substitutions"] = sum(
                    "undefined" in line and "Font shape" in line
                    or "Some font shapes were not available" in line
                    for line in log.splitlines()
                )
                sample["font_diagnostics"] = [line[:300] for line in log.splitlines()
                    if "Missing character:" in line or "Font shape" in line
                    or "Some font shapes were not available" in line][:30]
                if sample["missing_glyphs"] or sample["font_substitutions"]:
                    raise RuntimeError("font_or_glyph_quality_failed")
                if pages is None or pages < 1:
                    raise RuntimeError("invalid_pdf_page_count")
                sample.update(success=True, pdf_bytes=len(pdf), page_count=pages,
                              text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                              overfull_boxes=sum("Overfull \\" in line for line in log.splitlines()),
                              rerun_requested="Rerun to get" in log or "rerunfilecheck Warning" in log)
                if render_directory is not None and index == samples - 1:
                    render_directory.mkdir(parents=True, exist_ok=True)
                    basename = entry["fixture"].replace("/", "--").removesuffix(".tex")
                    shutil.copyfile(workspace / "resume.pdf", render_directory / (basename + ".pdf"))
                    subprocess.run(["pdftoppm", "-f", "1", "-singlefile", "-scale-to", "1600", "-png",
                                    str(workspace / "resume.pdf"), str(render_directory / basename)],
                                   check=True, capture_output=True, timeout=30)
            except Exception as exc:
                sample["error"] = str(exc)[:200] if isinstance(exc, RuntimeError) else type(exc).__name__
            sample["total_seconds"] = time.perf_counter() - started
            entry["samples"].append(sample)
    entry["certified"] = all(sample["success"] for sample in entry["samples"])
    return entry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("app/data/templates"))
    parser.add_argument("--samples", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=40)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fixture", action="append", default=[], help="Exact root-relative fixture to diagnose")
    parser.add_argument("--render-directory", type=Path, help="Retain last certified PDF and first-page PNG for visual QA")
    args = parser.parse_args()
    if not 1 <= args.samples <= 20 or not 1 <= args.timeout <= 120:
        parser.error("samples/timeout out of bounds")
    entries = []
    for path in sorted(args.root.rglob("*.tex")):
        if args.fixture and path.relative_to(args.root).as_posix() not in args.fixture:
            continue
        entries.append(certify(path, args.root, args.samples, args.timeout, args.render_directory))
        print(json.dumps({"fixture": entries[-1]["fixture"], "certified": entries[-1]["certified"]}), flush=True)
    good = [sample["total_seconds"] for entry in entries if entry["capacity_class"] == "resume" and entry["certified"] for sample in entry["samples"]]
    report = {
        "scope": "isolated network-disabled worker; actual TeX two-pass template runs + confinement + extraction; excludes API/Redis/storage/model/browser",
        "platform": platform.platform(), "sample_count": sum(len(entry["samples"]) for entry in entries),
        "fixtures": entries, "resume_p50_seconds": percentile(good, .5), "resume_p95_seconds": percentile(good, .95),
        "certified_count": sum(entry["certified"] for entry in entries), "fixture_count": len(entries),
    }
    encoded = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
