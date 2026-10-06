"""Disposable trusted managed-preamble format experiment; never product dispatch.

Only the fixed repository-owned English builder fixture enters the format dump.
The requested compiler is explicitly pdflatex; no user format flags are accepted.
Runtime sources retain every original preamble line for SyncTeX verification.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from app.services.latex_service import engine_env, engine_sandbox_flags, find_recorder_read_escape
from app.services.render_engine.passes import _RERUN
from app.services.render_engine.version import renderer_fingerprint
from app.services.resume_builder_service import resume_builder_service

FIXTURE = {"basics": {"name": "Avery Example", "label": "Software Engineer", "email": "avery@example.test",
    "location": "Example City", "summary": "Engineer building reliable services and accessible user experiences."},
    "experience": [{"id": "entry-1", "title": "Software Engineer", "company": "Example Systems",
        "start_date": "2022", "end_date": "2025", "bullets": [
            "Built an internal service that reduced manual processing by 20 percent.",
            "Collaborated with designers to improve onboarding for new customers.",
            "Introduced monitoring and documented incident response procedures.",
            "Reviewed changes, maintained test coverage and supported releases."]}],
    "skills": [{"id": "skills-1", "name": "Core Skills", "keywords": ["Python", "TypeScript", "SQL", "Product collaboration"]}]}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stats(values):
    values = sorted(values)
    return {"samples": len(values), "p50_seconds": statistics.median(values),
        "p95_seconds": values[math.ceil(.95 * len(values)) - 1], "min_seconds": values[0], "max_seconds": values[-1]}


def capture(command, directory, env, log_name, timeout=30):
    with (directory / log_name).open("wb") as output:
        result = subprocess.run(command, cwd=directory, env=env, stdout=output,
            stderr=subprocess.STDOUT, timeout=timeout, check=False)
    log = (directory / log_name).read_text(errors="replace")
    if result.returncode:
        raise RuntimeError("Trusted format experiment failed: " + log[-2000:])
    return log


def render(directory, source, fmt):
    directory.mkdir()
    (directory / "resume.tex").write_text(source, encoding="utf-8")
    if isinstance(fmt, Path):
        shutil.copyfile(fmt, directory / "trusted-builder.fmt")
    env = engine_env(directory, "pdflatex")
    command = ["pdflatex", *engine_sandbox_flags("pdflatex"), "-interaction=nonstopmode", "-halt-on-error", "-synctex=1"]
    if fmt == "installed":
        from app.services.render_engine.trusted_profiles import trusted_format_flags
        flags = trusted_format_flags(source, "pdflatex")
        if not flags:
            raise RuntimeError("Image-built trusted profile was not selected")
        command += flags
    elif fmt:
        command.append("-fmt=trusted-builder")
    command += ["-jobname=resume", "resume.tex"]
    started = time.perf_counter()
    passes = 0
    for number in (1, 2, 3):
        log = capture(command, directory, env, f"pass-{number}.txt")
        passes += 1
        if find_recorder_read_escape(directory / "resume.fls", str(directory), require_recorder=True):
            raise RuntimeError("Experiment failed recorder confinement")
        if not _RERUN.search(log):
            break
    else:
        raise RuntimeError("Experiment did not converge in three passes")
    elapsed = time.perf_counter() - started
    capture(["pdftotext", "-layout", "resume.pdf", "text.txt"], directory, env, "extract.txt")
    capture(["pdftoppm", "-r", "72", "-singlefile", "-png", "resume.pdf", "page"], directory, env, "pixels.txt")
    info = capture(["pdfinfo", "resume.pdf"], directory, env, "info.txt")
    pages = int(re.search(r"^Pages:\s*(\d+)", info, re.M)[1])
    line = next(n for n, value in enumerate(source.splitlines(), 1) if "Avery Example" in value)
    sync = capture(["synctex", "view", "-i", f"{line}:1:resume.tex", "-o", "resume.pdf"], directory, env, "sync.txt")
    coords = re.findall(r"^(?:Page|h|v|W|H):(.+)$", sync, re.M)
    compressed = gzip.decompress((directory / "resume.synctex.gz").read_bytes())
    source_tags = [tag for tag, filename in re.findall(r"^Input:(\d+):(.+)$", compressed.decode(errors="replace"), re.M)
        if filename.endswith("/resume.tex") or filename == "resume.tex"]
    source_records = []
    for record in compressed.decode(errors="replace").splitlines():
        match = re.match(r"^.(-?\d+),(\d+)(?:,\d+)?:", record)
        if match and match[1] in source_tags:
            source_records.append(re.sub(r"^(.)(-?\d+),", r"\1SOURCE,", record))
    if not source_records:
        raise RuntimeError("SyncTeX contains no source records; parity cannot be certified")
    return {"elapsed_seconds": elapsed, "passes": passes, "page_count": pages,
        "text_sha256": digest((directory / "text.txt").read_bytes()),
        "pixel_sha256": digest((directory / "page.png").read_bytes()),
        "synctex_source_line": line, "synctex_view_coordinates": coords,
        "synctex_has_expected_input": b"resume.tex" in compressed,
        "synctex_source_records": len(source_records),
        "synctex_source_records_sha256": digest("\n".join(source_records).encode())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 10:
        parser.error("At least 10 alternating pairs required")
    source = resume_builder_service.render(FIXTURE, "professional").latex_content
    preamble = source.split(r"\begin{document}", 1)[0]
    evidence = {"schema_version": 1, "scope": "trusted static English managed builder; TeX process+convergence only; no production shipping",
        "source_sha256": digest(source.encode()), "preamble_sha256": digest(preamble.encode()),
        "renderer_fingerprint": renderer_fingerprint(), "samples": []}
    try:
        with tempfile.TemporaryDirectory(prefix="latexy-trusted-format-") as temporary:
            root = Path(temporary)
            build = root / "build"
            build.mkdir()
            (build / "trusted.tex").write_text(source, encoding="utf-8")
            start = time.perf_counter()
            command = ["pdflatex", "-ini", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape",
                "-jobname=trusted-builder", "&pdflatex", "mylatexformat.ltx", "trusted.tex"]
            capture(command, build, engine_env(build, "pdflatex"), "format-build.txt")
            fmt = build / "trusted-builder.fmt"
            evidence["format_build_seconds"] = time.perf_counter() - start
            evidence["format_size"] = fmt.stat().st_size
            evidence["format_sha256"] = digest(fmt.read_bytes())
            baseline = render(root / "warm-default", source, None)
            preloaded = render(root / "warm-preloaded", source, fmt)
            evidence["warmup_equal_text"] = baseline["text_sha256"] == preloaded["text_sha256"]
            evidence["warmup_equal_pixels"] = baseline["pixel_sha256"] == preloaded["pixel_sha256"]
            evidence["warmup_equal_synctex_coordinates"] = baseline["synctex_view_coordinates"] == preloaded["synctex_view_coordinates"]
            evidence["warmup_equal_source_synctex_records"] = baseline["synctex_source_records_sha256"] == preloaded["synctex_source_records_sha256"]
            for n in range(args.samples):
                pair = {}
                for condition in (("default", "preloaded") if n % 2 == 0 else ("preloaded", "default")):
                    value = render(root / f"pair-{n}-{condition}", source, fmt if condition == "preloaded" else None)
                    pair[condition] = value
                    evidence["samples"].append({"pair": n, "condition": condition, **value})
                    print(json.dumps({"pair": n, "condition": condition, "elapsed_seconds": value["elapsed_seconds"]}), flush=True)
                if (pair["default"]["text_sha256"] != pair["preloaded"]["text_sha256"]
                    or pair["default"]["pixel_sha256"] != pair["preloaded"]["pixel_sha256"]
                    or pair["default"]["synctex_source_records_sha256"] != pair["preloaded"]["synctex_source_records_sha256"]):
                    raise RuntimeError("Trusted format changed rendered text, pixels, or source SyncTeX records")
            evidence["aggregates"] = {condition: stats([v["elapsed_seconds"] for v in evidence["samples"] if v["condition"] == condition])
                for condition in ("default", "preloaded")}
            evidence["all_source_synctex_records_equal"] = all(
                next(v for v in evidence["samples"] if v["pair"] == n and v["condition"] == "default")["synctex_source_records_sha256"]
                == next(v for v in evidence["samples"] if v["pair"] == n and v["condition"] == "preloaded")["synctex_source_records_sha256"]
                for n in range(args.samples))
            evidence["supported"] = True
    except Exception as exc:
        evidence["supported"] = False
        evidence["error"] = str(exc)
    args.output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
