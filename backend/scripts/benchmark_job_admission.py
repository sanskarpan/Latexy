"""Compare committed sequential admission with atomic initialization on test Redis.

Run from backend with TEST_REDIS_URL selecting a dedicated nonzero Redis DB:
  python scripts/benchmark_job_admission.py --output ../docs/audits/resume-engine/admission-benchmark.json
Only synthetic, uniquely named benchmark keys are written and deleted. The
report excludes credentials and measures Redis initialization, not whole jobs.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import redis.asyncio as aioredis

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.job_admission_state import initialize_job_state  # noqa: E402

BASELINE_REF = "317b9b3d0b1cf05cb4a007dbf179129993d67ba5"


def summarize(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {"samples_ms": samples, "sample_count": len(samples),
            "median_ms": statistics.median(samples),
            "p95_ms": ordered[math.ceil(len(samples) * .95) - 1]}


async def benchmark(args) -> dict:
    url = os.environ.get("TEST_REDIS_URL", "")
    endpoint = urlparse(url)
    database = endpoint.path.strip("/")
    if endpoint.scheme not in {"redis", "rediss"} or not database.isdigit() or int(database) == 0:
        raise ValueError("TEST_REDIS_URL must explicitly select a dedicated, nonzero test Redis database")
    root = Path(__file__).resolve().parents[2]
    source = subprocess.run(
        ["git", "show", f"{args.baseline_ref}:backend/app/api/job_routes.py"],
        cwd=root, text=True, capture_output=True, check=True,
    ).stdout
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_write_initial_redis_state")
    client = aioredis.from_url(url, decode_responses=True, socket_connect_timeout=3, socket_timeout=5)

    async def get_client():
        return client

    scope = {"get_redis_client": get_client, "json": json, "time": time, "uuid": uuid,
             "Optional": Optional, "_JOB_TTL": 60}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<committed admission baseline>", "exec"), scope)
    baseline = scope["_write_initial_redis_state"]
    owner = f"test_admission_benchmark_{uuid.uuid4().hex}"
    job_ids = []
    measurements = {}
    try:
        await client.ping()
        for implementation in ["old_sequential", "new_atomic"]:
            samples = []
            for index in range(args.samples + args.warmups):
                job_id = f"test_admission_benchmark_{uuid.uuid4().hex}"
                job_ids.append(job_id)
                started = time.perf_counter()
                if implementation == "old_sequential":
                    await baseline(job_id, "combined", owner, 25)
                else:
                    await initialize_job_state(client, job_id=job_id, job_type="combined", user_id=owner,
                                               estimated_seconds=25, ttl=60)
                elapsed = (time.perf_counter() - started) * 1000
                if index >= args.warmups:
                    samples.append(elapsed)
            measurements[implementation] = summarize(samples)
        return {"recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                "baseline_ref": args.baseline_ref, "python_version": platform.python_version(),
                "platform": platform.system(), "warmup_samples_per_implementation": args.warmups,
                "redis_endpoint": {"host": endpoint.hostname, "port": endpoint.port or 6379,
                                   "database": int(database), "tls": endpoint.scheme == "rediss"},
                "percentile_method": "nearest rank",
                "scope": "Redis initialization only, with owning-user index; excludes auth, durable admission, quotas, dispatch, and PDF compilation",
                "limitations": "Local component benchmark with synthetic IDs; does not establish production admission latency or PDF performance",
                "measurements": measurements,
                "median_speedup": measurements["old_sequential"]["median_ms"] / measurements["new_atomic"]["median_ms"]}
    finally:
        keys = [f"latexy:job:{job_id}:{suffix}" for job_id in job_ids for suffix in ["state", "meta", "seq"]]
        keys += [f"latexy:stream:{job_id}" for job_id in job_ids]
        keys.append(f"latexy:user:{owner}:jobs")
        try:
            await client.delete(*keys)
        finally:
            await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--baseline-ref", default=BASELINE_REF)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.samples <= 1000 or not 0 <= args.warmups <= 100:
        parser.error("samples must be 1–1000 and warmups 0–100")
    report = asyncio.run(benchmark(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # Avoid printing the Redis URL, credentials, source, or synthetic owner IDs.
    print(json.dumps({name: {key: value for key, value in result.items() if key != "samples_ms"}
                      for name, result in report["measurements"].items()}))


if __name__ == "__main__":
    main()
