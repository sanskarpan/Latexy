"""Opt-in isolated warm renderer benchmark with real TeX/Redis/PG/S3.

No mocked transport or artifact storage. Measures eager direct-worker task wall
latency including worker ownership admission, artifacts, geometry and durable
finalization. Excludes public HTTP quota admission, Celery transport, AI, browser
paint and cold image startup. Refuses non-test databases. Only synthetic rows
created here are deleted; Redis databases are never flushed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import statistics
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from benchmark_resume_render import SOURCE
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import engine_observability
from app.core.config import settings
from app.database.models import Compilation, JobFinalization, Resume, User
from app.services.render_engine import process_timing
from app.services.render_engine.artifacts import sha256
from app.services.render_engine.version import renderer_fingerprint
from app.workers import event_publisher, job_lifecycle, latex_worker


def summary(values):
    values = sorted(values)
    return {"samples": len(values), "p50_seconds": statistics.median(values),
            "p95_seconds": values[max(0, math.ceil(.95 * len(values)) - 1)],
            "min_seconds": values[0], "max_seconds": values[-1]}


async def benchmark(samples, host_load, profile, guest, compiler="pdflatex"):
    if not settings.DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0].endswith("_test"):
        raise RuntimeError("Benchmark requires an explicitly isolated *_test database")
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id, resume_id = (None, None) if guest else (str(uuid4()), str(uuid4()))
    fingerprint = "bench_guest_" + uuid4().hex if guest else None
    base_source = SOURCE
    if profile == "managed_english":
        from benchmark_trusted_format import FIXTURE

        from app.services.resume_builder_service import resume_builder_service

        base_source = resume_builder_service.render(FIXTURE, "ats_safe").latex_content
    if profile == "one_pass_no_hyperref":
        base_source = base_source.replace(r"\usepackage{hyperref}", "").replace(
            r"\href{mailto:avery@example.test}{avery@example.test}", "avery@example.test")
    prefix = "bench_pipeline_" + uuid4().hex
    event_publisher.initialize_worker_redis(settings.REDIS_URL)
    redis = event_publisher.get_worker_redis()
    rows, jobs = [], []
    phases = []
    original_record = engine_observability.record_phase

    def measured_phase(phase, seconds, outcome="success"):
        phases.append({"phase": phase, "seconds": seconds, "outcome": outcome})
        original_record(phase, seconds, outcome)
    engine_observability.record_phase = measured_phase
    process_timing.record_phase = measured_phase
    try:
        if not guest:
            async with factory() as session:
                session.add(User(id=user_id, email=prefix + "@example.test"))
                await session.flush()
                session.add(Resume(id=resume_id, user_id=user_id, title="Synthetic benchmark", latex_content=base_source))
                await session.commit()
        # Three warmup fresh runs and one cache seed are excluded. Interleave
        # measured fresh/cache jobs to reduce systematic host-load order bias.
        conditions = [("warmup", n) for n in range(3)] + [("cache_seed", 0)]
        conditions += [(condition, n) for n in range(samples) for condition in
                       (("fresh", "exact_cache") if n % 2 == 0 else ("exact_cache", "fresh"))]
        for condition, n in conditions:
            job = prefix + "_" + uuid4().hex
            jobs.append(job)
            source = base_source if condition in {"exact_cache", "cache_seed"} else base_source.replace(
                "\\end{document}", f"\\par Measurement sequence {condition} {n}.\n\\end{{document}}")
            async with factory() as session:
                if not guest:
                    session.add(Compilation(id=str(uuid4()), job_id=job, user_id=user_id, resume_id=resume_id, status="processing"))
                session.add(JobFinalization(id=str(uuid4()), job_id=job, user_id=user_id, resume_id=resume_id,
                    job_type="latex_compilation", owner_epoch=0, state="pending",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
                await session.commit()
            redis.set(f"latexy:job:{job}:meta", json.dumps({"user_id": user_id, "job_type": "latex_compilation", "device_fingerprint": fingerprint}))
            assert job_lifecycle.begin_dispatch(redis, job)
            assert job_lifecycle.mark_dispatch_accepted(redis, job)
            document = {"document_id": resume_id or "guest", "content_revision": 1, "source_sha256": sha256(source),
                "nodes": [{"node_id": "name", "node_revision": sha256("Avery Example"), "kind": "name",
                    "text": "Avery Example", "editable": True,
                    "source_span": {"start": source.index("Avery Example"), "end": source.index("Avery Example") + 13}}]}
            kwargs = {"latex_content": source, "job_id": job, "user_id": user_id, "resume_id": resume_id,
                "compiler": compiler, "timeout_seconds": 30, "metadata": {"skip_auto_save": True},
                "render_request": {"document_id": resume_id or "guest", "content_revision": 1, "source_document": document},
                "device_fingerprint": fingerprint, "watermark": "Latexy" if guest else None}
            phases.clear()
            started = time.perf_counter()
            result = await asyncio.to_thread(lambda: latex_worker.compile_latex_task.apply(kwargs=kwargs, throw=True).get())
            elapsed = time.perf_counter() - started
            if not result.get("success") or result.get("page_count") != 1 or not result.get("artifact"):
                raise RuntimeError("Benchmark render failed or was not one page")
            if condition == "exact_cache" and result.get("compilation_time") != 0:
                raise RuntimeError("Expected exact-cache condition spawned a compiler")
            tex_passes = sum(value["phase"] == "tex_process" for value in phases)
            if profile == "one_pass_no_hyperref" and condition == "fresh" and tex_passes != 1:
                raise RuntimeError("One-pass capability fixture unexpectedly required additional TeX passes")
            if condition in {"fresh", "exact_cache"}:
                row = {"condition": condition, "pair": n, "elapsed_seconds": elapsed,
                    "compiler_seconds": result.get("compilation_time"), "tex_passes": tex_passes, "pdf_size": result["artifact"]["pdf_size"],
                    "page_count": result["page_count"], "phases": list(phases)}
                rows.append(row)
                print(json.dumps({"condition": condition, "pair": n, "elapsed_seconds": round(elapsed, 4)}), flush=True)
        aggregates = {}
        for condition in ("fresh", "exact_cache"):
            selected = [row for row in rows if row["condition"] == condition]
            aggregated_phases = defaultdict(list)
            for row in selected:
                per_job = defaultdict(float)
                for observation in row["phases"]:
                    per_job[observation["phase"]] += observation["seconds"]
                for phase, seconds in per_job.items():
                    aggregated_phases[phase].append(seconds)
            aggregates[condition] = {"wall": summary([row["elapsed_seconds"] for row in selected]),
                "phase_totals_per_job": {phase: summary(values) for phase, values in aggregated_phases.items()}}
        return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
            "host_load": host_load, "profile": profile, "compiler": compiler,
            "fixture_source_sha256": sha256(base_source), "guest": guest, "watermark": "Latexy" if guest else None,
            "renderer_fingerprint": renderer_fingerprint(),
            "benchmark_container_cpu_limit": "none", "scope": f"warm eager direct-worker task; actual {compiler}+Redis Lua+PostgreSQL+S3; geometry enabled",
            "exclusions": ["public HTTP admission/quota", "Celery transport", "AI", "browser paint", "cold image startup"],
            "method": "3 fresh warmups +1 exact seed excluded; 30 or more deterministic alternating fresh/cache pairs; distinct fresh source",
            "phase_warning": "phase intervals overlap; sums are not total wall latency", "samples": rows, "aggregates": aggregates,
            "fresh_target_p95_below_1s_met": aggregates["fresh"]["wall"]["p95_seconds"] < 1,
            "fresh_milestone_p95_below_2s_met": aggregates["fresh"]["wall"]["p95_seconds"] < 2}
    finally:
        engine_observability.record_phase = original_record
        process_timing.record_phase = original_record
        async with factory() as session:
            await session.execute(delete(JobFinalization).where(JobFinalization.job_id.in_(jobs)))
            await session.execute(delete(Compilation).where(Compilation.job_id.in_(jobs)))
            await session.execute(delete(Resume).where(Resume.id == resume_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-load", choices=["contended", "quiet", "unspecified"], default="unspecified")
    parser.add_argument("--profile", choices=["hyperref", "one_pass_no_hyperref", "managed_english"], default="hyperref")
    parser.add_argument("--compiler", choices=["pdflatex", "lualatex", "xelatex"], default="pdflatex")
    parser.add_argument("--source-commit", help="Immutable source commit used for this run")
    parser.add_argument("--image-id", help="Actual Docker image ID used for this run")
    parser.add_argument("--guest", action="store_true")
    args = parser.parse_args()
    if args.samples < 30:
        parser.error("At least 30 measured pairs required")
    logging.disable(logging.CRITICAL)
    result = asyncio.run(benchmark(args.samples, args.host_load, args.profile, args.guest, args.compiler))
    result["source_commit"] = args.source_commit
    result["image_id"] = args.image_id
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
