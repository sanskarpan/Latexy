"""Warm real-TeX benchmark with explicitly simulated Redis transport.

Run inside a credential-free, network-disabled TeX worker container. Mount the
backend read-only at /workspace and the evidence directory at /evidence. This
compares the original main render function with the current implementation;
artifact persistence, admission, dispatch, scoring and browser paint are excluded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import platform
import statistics
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import patch

logging.disable(logging.CRITICAL)
from app.workers import event_publisher, orchestrator

SOURCE = r"""\documentclass[10pt]{article}
\usepackage[margin=0.7in]{geometry}
\usepackage[T1]{fontenc}
\usepackage{hyperref}
\pagestyle{empty}
\begin{document}
{\Large Avery Example}\hfill Software Engineer\\
\href{mailto:avery@example.test}{avery@example.test}\hfill Example City
\section*{Summary}
Engineer building reliable services and accessible user experiences.
\section*{Experience}
\textbf{Example Systems}\hfill 2022--2025
\begin{itemize}
\item Built an internal service that reduced manual processing by 20 percent.
\item Collaborated with designers to improve onboarding for new customers.
\item Introduced monitoring and documented incident response procedures.
\item Reviewed changes, maintained test coverage and supported releases.
\end{itemize}
\textbf{Sample Software}\hfill 2020--2022
\begin{itemize}
\item Maintained data pipelines and investigated production issues.
\item Created reusable interface components and improved accessibility.
\item Documented service contracts and supported cross-team integration.
\end{itemize}
\section*{Education}
Bachelor of Science in Computer Science, Example University, 2020
\section*{Skills}
Python, TypeScript, SQL, distributed systems, product collaboration
\end{document}
"""


class Transport:
    """No real Redis. Every independent request incurs the chosen fixed RTT.

    Pipeline commands retain event ordering and share one simulated request.
    This models transport only; Redis Lua CPU, queues and persistence are omitted.
    """
    def __init__(self, rtt):
        self.rtt = rtt
        self.lock = threading.Lock()
        self.requests = self.sequence = 0
        self.events = []

    def request(self):
        with self.lock:
            self.requests += 1
        if self.rtt:
            time.sleep(self.rtt)

    def _eval(self, *args):
        event = json.loads(args[7])
        with self.lock:
            self.sequence += 1
            self.events.append(event)
            return [f"{self.sequence}-0", str(self.sequence), json.dumps(event)]

    def eval(self, *args):
        self.request()
        return self._eval(*args)

    def exists(self, *_):
        self.request()
        return 0

    def hget(self, *_):
        self.request()
        return None

    def pipeline(self, **_):
        transport = self
        class Pipeline:
            def __init__(self):
                self.commands = []
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def eval(self, *args):
                self.commands.append(args)
            def execute(self):
                transport.request()
                return [transport._eval(*args) for args in self.commands]
        return Pipeline()


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def extract(pdf):
    with tempfile.TemporaryDirectory() as directory:
        filename = Path(directory) / "sample.pdf"
        filename.write_bytes(pdf)
        text = subprocess.check_output(["pdftotext", str(filename), "-"], text=True)
        return " ".join(text.split())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--rtt-ms", type=float, nargs="+", default=[0, 5, 25])
    parser.add_argument("--extra-log-lines", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.extra_log_lines <= 200 or any(rtt < 0 for rtt in args.rtt_ms):
        parser.error("Require nonnegative RTT and 0–200 extra log lines")
    global SOURCE
    if args.extra_log_lines:
        SOURCE = SOURCE.replace(r"\end{document}", "\n".join(r"\typeout{BENCHMARK safe log line %d}" % index for index in range(args.extra_log_lines)) + "\n" + r"\end{document}")
    if args.samples < 20:
        parser.error("Use at least 20 measured samples per condition")
    namespace = dict(vars(orchestrator))
    exec(compile(Path(args.baseline).read_text(), args.baseline, "exec"), namespace)
    baseline = namespace["_run_latex_stage"]
    current = orchestrator._run_latex_stage
    report = {
        "scope": "Real warm pdflatex in isolated container; fixed simulated Redis transport; no production latency claims",
        "baseline_commit": "317b9b3d0b1cf05cb4a007dbf179129993d67ba5",
        "samples_per_condition": args.samples,
        "benchmark_order": "Alternating baseline/current order in paired iterations, separately for each RTT",
        "excluded": ["admission", "dispatch", "durable artifact storage", "scoring", "model generation", "PDF browser paint", "real Redis execution"],
        "python_version": platform.python_version(),
        "container_platform": platform.platform(),
        "baseline_function_sha256": hashlib.sha256(Path(args.baseline).read_bytes()).hexdigest(),
        "tex_version": subprocess.check_output(["pdflatex", "--version"], text=True).splitlines()[0],
        "extra_safe_typeout_log_lines": args.extra_log_lines,
        "fixture_source_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
        "conditions": [],
    }
    fingerprints = set()
    with tempfile.TemporaryDirectory(prefix="resume-render-benchmark-") as workspace:
        orchestrator.settings.TEMP_DIR = workspace
        orchestrator.settings.COMPILE_TIMEOUT = 30
        # Running inside a network-disabled Docker container; keep local engine
        # opt-in and the production -no-shell-escape/-recorder/read-confinement gates.
        orchestrator.docker_engine_available = lambda: False
        for rtt_ms in args.rtt_ms:
            rtt = rtt_ms / 1000
            measurements = {"baseline": [], "buffered": []}
            for iteration in range(args.samples + 2):
                renderers = [("baseline", baseline), ("buffered", current)]
                if iteration % 2:
                    renderers.reverse()
                for name, function in renderers:
                    samples = measurements[name]
                    transport = Transport(rtt)
                    event_publisher._worker_redis = transport
                    job_id = uuid.uuid4().hex
                    def cache_output(_job_id, directory):
                        return (directory / "resume.pdf").read_bytes()
                    with patch.object(orchestrator, "cache_compile_output", side_effect=cache_output), patch.object(orchestrator, "cache_compile_log"), patch.object(orchestrator, "record_compile"):
                        # Baseline globals were copied before patches; replace just
                        # artifact callbacks, keeping original stdout/control flow.
                        baseline.__globals__["cache_compile_output"] = cache_output
                        baseline.__globals__["cache_compile_log"] = lambda *_: None
                        baseline.__globals__["record_compile"] = lambda *_, **__: None
                        baseline.__globals__["docker_engine_available"] = lambda: False
                        started = time.perf_counter()
                        success, compiler_time, error, pages, pdf = function(job_id, SOURCE, timeout_seconds=30)
                        elapsed = time.perf_counter() - started
                    if not success or not pdf or not pdf.startswith(b"%PDF-"):
                        raise RuntimeError(f"{name} failed: {error}")
                    text = extract(pdf)
                    fingerprints.add((pages, hashlib.sha256(text.encode()).hexdigest()))
                    if iteration >= 2:
                        samples.append({"elapsed_seconds": elapsed, "reported_compile_seconds": compiler_time, "transport_requests": transport.requests, "log_events": len(transport.events), "pdf_bytes": len(pdf), "pages": pages})
            for name, samples in measurements.items():
                elapsed = [sample["elapsed_seconds"] for sample in samples]
                report["conditions"].append({"renderer": name, "simulated_rtt_ms": rtt * 1000, "warmups": 2, "p50_seconds": statistics.median(elapsed), "p95_seconds": percentile(elapsed, .95), "min_seconds": min(elapsed), "max_seconds": max(elapsed), "samples": samples})
        with patch.object(orchestrator.subprocess, "Popen") as spawn:
            hostile = SOURCE.replace("\\end{document}", "\\input{/etc/passwd}\\end{document}")
            result = current(uuid.uuid4().hex, hostile, timeout_seconds=30)
            report["hostile_input_rejected_before_spawn"] = not result[0] and not spawn.called
        looping = SOURCE.replace("\\end{document}", "\\loop\\iftrue\\repeat\\end{document}")
        started = time.perf_counter()
        result = current(uuid.uuid4().hex, looping, timeout_seconds=.15)
        report["timeout_check"] = {"success": result[0], "error": result[2], "elapsed_seconds": time.perf_counter() - started}
    report["pdf_text_and_page_count_equal_all_samples"] = len(fingerprints) == 1
    report["pdf_text_sha256"] = next(iter(fingerprints))[1]
    if not report["pdf_text_and_page_count_equal_all_samples"] or not report["hostile_input_rejected_before_spawn"] or report["timeout_check"]["success"]:
        raise RuntimeError("Correctness check failed")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
