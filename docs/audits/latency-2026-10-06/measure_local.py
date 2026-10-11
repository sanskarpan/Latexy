"""Repeatable local evidence for the latency architecture audit.

Runs the existing section parser against shipped templates without importing
application settings, loading credentials, invoking a model, or compiling TeX.
The round-trip examples are calculations, not production measurements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SOURCE_FILES = (
    "backend/app/api/job_routes.py",
    "backend/app/core/modal_dispatch.py",
    "backend/app/services/latex_section_parser.py",
    "backend/app/services/llm_service.py",
    "backend/app/workers/event_publisher.py",
    "backend/app/workers/latex_worker.py",
    "backend/app/workers/llm_worker.py",
    "backend/app/workers/orchestrator.py",
    "backend/modal_app.py",
    "frontend/src/components/LaTeXEditor.tsx",
    "frontend/src/components/PDFPreview.tsx",
    "frontend/src/components/VisualResumeEditor.tsx",
    "frontend/src/lib/wysiwyg/visual-projection.ts",
    "frontend/src/hooks/useJobStream.reducer.ts",
    "frontend/src/hooks/useJobStream.ts",
    "frontend/src/app/workspace/[resumeId]/edit/page.tsx",
)


def p95(values: list[float]) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 1000:
        parser.error("--repeats must be between 1 and 1000")

    sys.path.insert(0, str(ROOT / "backend"))
    from app.services.latex_section_parser import extract_sections

    templates = sorted((ROOT / "backend/app/data/templates").rglob("*.tex"))
    samples: list[float] = []
    rows = []
    for path in templates:
        source = path.read_text(encoding="utf-8")
        _, sections = extract_sections(source)
        durations = []
        for _ in range(args.repeats):
            start = time.perf_counter_ns()
            extract_sections(source)
            durations.append((time.perf_counter_ns() - start) / 1_000_000)
        samples.extend(durations)
        rows.append({
            "path": path.relative_to(ROOT).as_posix(),
            "source_chars": len(source),
            "sections_recognized": len(sections),
            "parser_p50_ms": round(statistics.median(durations), 4),
            "parser_p95_ms": round(p95(durations), 4),
        })

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
        text=True, check=True,
    ).stdout.strip()
    result = {
        "scope": "Local section-parser microbenchmark and source inventory only",
        "production_compile_or_model_latency_measured": False,
        "commit": commit,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "repeats_per_template": args.repeats,
        "templates": len(templates),
        "parser_calls": len(samples),
        "parser_p50_ms": round(statistics.median(samples), 4),
        "parser_p95_ms": round(p95(samples), 4),
        "templates_with_no_recognized_section": sum(r["sections_recognized"] == 0 for r in rows),
        "template_source_chars_p50": statistics.median(r["source_chars"] for r in rows),
        "available_compilers_on_path": {name: shutil.which(name) for name in
                                       ("pdflatex", "xelatex", "lualatex", "tectonic", "typst", "docker")},
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in SOURCE_FILES if (ROOT / name).is_file()},
        "round_trip_calculations": [
            {"events": n, "assumed_rtt_ms": rtt, "serial_publication_seconds": n * rtt / 1000}
            for n in (200, 1200) for rtt in (1, 10, 20, 50)
        ],
        "template_results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"template_results", "source_sha256"}}, indent=2))


if __name__ == "__main__":
    main()
