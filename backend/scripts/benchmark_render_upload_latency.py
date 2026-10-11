"""Alternating serial/concurrent binary writes against isolated real S3.

The injected request delay is synthetic, never a production measurement.
"""
import argparse
import gzip
import hashlib
import json
import math
import statistics
import threading
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.services import storage_service
from app.services.render_engine import artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--rtt-ms", type=float, default=40)
    args = parser.parse_args()
    if args.samples < 30 or not 0 <= args.rtt_ms <= 250:
        parser.error("Requires >=30 alternating pairs and 0..250ms synthetic delay")
    if not settings.DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0].endswith("_test"):
        raise RuntimeError("Requires an isolated *_test database/bucket")
    original = storage_service._get_client
    actual = original()
    counts, lock = Counter(), threading.Lock()

    class Client:
        def __getattr__(self, name):
            method = getattr(actual, name)
            if name != "put_object":
                return method

            def call(**kwargs):
                with lock:
                    counts[name] += 1
                time.sleep(args.rtt_ms / 1000)
                return method(**kwargs)
            return call

    scope = artifacts.sha256("user:test-upload-latency-" + uuid4().hex)
    pdf = b"%PDF-synthetic binary transport " + uuid4().hex.encode()
    synctex = gzip.compress(b"synthetic SyncTeX " + uuid4().hex.encode(), mtime=0)
    keys = [artifacts.binary_key(scope, artifacts.sha256(data), kind)
            for kind, data in (("pdf", pdf), ("synctex", synctex))]
    rows = []
    storage_service._get_client = lambda: Client()
    try:
        for number in range(args.samples):
            for condition in (("serial", "concurrent") if number % 2 == 0 else ("concurrent", "serial")):
                # Each timed condition executes fresh immutable conditional writes.
                for key in keys:
                    storage_service.delete_object(key)
                counts.clear()
                started = time.perf_counter()
                if condition == "serial":
                    refs = (artifacts._put(scope, "pdf", pdf, "application/pdf"),
                            artifacts._put(scope, "synctex", synctex, "application/gzip"))
                else:
                    refs = artifacts._put_render_binaries(scope, pdf, synctex)
                elapsed = (time.perf_counter() - started) * 1000
                assert [ref.key for ref in refs] == keys
                assert storage_service.download_bytes(keys[0], max_bytes=len(pdf)) == pdf
                assert storage_service.download_bytes(keys[1], max_bytes=len(synctex)) == synctex
                rows.append({"pair": number, "condition": condition, "elapsed_ms": elapsed, "requests": dict(counts)})
        aggregates = {}
        for condition in ("serial", "concurrent"):
            values = sorted(row["elapsed_ms"] for row in rows if row["condition"] == condition)
            aggregates[condition] = {"samples": len(values), "p50_ms": statistics.median(values),
                                     "p95_ms": values[math.ceil(.95 * len(values)) - 1]}
        args.output.write_text(json.dumps({"scope": "Real isolated S3 conditional PDF/SyncTeX writes; both verified by GET outside measured interval",
            "candidate_artifacts_sha256": hashlib.sha256(Path(artifacts.__file__).read_bytes()).hexdigest(),
            "simulated_per_request_rtt_ms": args.rtt_ms,
            "limitations": ["Delay is synthetic", "Excludes geometry, manifest/PG fences, TeX, HTTP and browser paint"],
            "samples": rows, "aggregates": aggregates}, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(aggregates), flush=True)
    finally:
        storage_service._get_client = original
        for key in keys:
            storage_service.delete_object(key)


if __name__ == "__main__":
    main()
