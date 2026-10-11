"""Paired real S3 checks with an explicit simulated per-request RTT.

Loads the prior download implementation from a read-only Git source snapshot.
The registration baseline is the audited serial size-check loop; this probe
excludes PG locks, TeX, HTTP admission and browser paint. Synthetic objects only.
Never interpret these samples as measured production network latency.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.services import storage_service
from app.services.render_engine.retention import _storage_objects_present


def summary(values):
    values = sorted(values)
    return {"samples": len(values), "p50_ms": statistics.median(values),
            "p95_ms": values[math.ceil(.95 * len(values)) - 1]}


class DelayedClient:
    def __init__(self, client, delay):
        self.client, self.delay = client, delay
        self.counts = Counter()
        self.lock = threading.Lock()

    def __getattr__(self, name):
        function = getattr(self.client, name)
        if name not in {"get_object", "head_object"}:
            return function

        def request(**kwargs):
            with self.lock:
                self.counts[name] += 1
            time.sleep(self.delay)
            return function(**kwargs)
        return request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-storage", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--rtt-ms", type=float, default=40)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.samples < 30 or not 0 <= args.rtt_ms <= 250:
        parser.error("Requires >=30 pairs and a simulated RTT between 0 and 250ms")
    if not settings.DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0].endswith("_test"):
        raise RuntimeError("Probe requires an isolated *_test database and bucket")
    spec = importlib.util.spec_from_file_location("app.services._storage_latency_baseline", args.baseline_storage)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    original = storage_service._get_client
    client = DelayedClient(original(), args.rtt_ms / 1000)
    prefix = "test-storage-latency/" + uuid4().hex + "/"
    data = b"%PDF-synthetic storage transport probe"
    expected = [(prefix + kind, len(data)) for kind in ("pdf", "synctex", "geometry", "manifest")]
    rows = []
    try:
        for key, _ in expected:
            storage_service.upload_immutable_bytes(key, data)
        storage_service._get_client = baseline._get_client = lambda: client
        for number in range(args.samples):
            for operation in ("download", "publication_size_checks"):
                for condition in (("baseline", "candidate") if number % 2 == 0 else ("candidate", "baseline")):
                    client.counts.clear()
                    start = time.perf_counter()
                    if operation == "download":
                        module = baseline if condition == "baseline" else storage_service
                        assert module.download_bytes(expected[0][0], max_bytes=len(data)) == data
                    elif condition == "baseline":
                        assert all(storage_service.head_size(key) == size for key, size in expected)
                    else:
                        assert _storage_objects_present(expected)
                    rows.append({"pair": number, "operation": operation, "condition": condition,
                                 "elapsed_ms": (time.perf_counter() - start) * 1000,
                                 "requests": dict(client.counts)})
        aggregates = {operation: {condition: summary([row["elapsed_ms"] for row in rows
            if row["operation"] == operation and row["condition"] == condition])
            for condition in ("baseline", "candidate")} for operation in ("download", "publication_size_checks")}
        result = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
                  "source_commit": args.source_commit,
                  "baseline_storage_sha256": hashlib.sha256(args.baseline_storage.read_bytes()).hexdigest(),
                  "candidate_storage_sha256": hashlib.sha256(Path(storage_service.__file__).read_bytes()).hexdigest(),
                  "simulated_per_request_rtt_ms": args.rtt_ms,
                  "scope": "Real isolated S3, actual bounded downloads; audited serial vs actual concurrent size-check loop",
                  "limitations": ["Injected delay is not measured production RTT", "Excludes PG locks, TeX, admission and browser",
                                  "All size checks finish before releasing caller locks; sizes alone do not replace digest verification"],
                  "method": "30 alternating pairs per operation; same objects/client/process; no warmup samples",
                  "samples": rows, "aggregates": aggregates}
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(aggregates), flush=True)
    finally:
        storage_service._get_client = original
        for key, _ in expected:
            storage_service.delete_object(key)


if __name__ == "__main__":
    main()
