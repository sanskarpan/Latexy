# Latency priority pass — October 8, 2026

Source change: `36de1a5100ac35e3eb961227f49d61d228edce74`, backend tree
`e2e997bfe6475c847bf52934b5aface464099f3c`, in `codex/resume-engine` / PR #1833.
Main `bdee48926ce0e2e6c9c5e2b281d2ab07c4355b98` was refetched and remains an
ancestor. No main-checkout services or dependencies were changed.

## Changes and safeguards

Bounded storage downloads now use one GET. Its response length is checked before
reading the body; missing or dishonest metadata still cannot bypass the bounded
stream read. The response closes on success, oversize and read failures. GET 404
and NoSuchKey preserve the missing-object contract. Artifact size/SHA-256 checks,
authorization, ownership, expiry and export policy remain mandatory. A HEAD
preflight cannot protect the GET bytes against replacement between requests.

Manifest registration checks up to four independent object sizes concurrently.
It holds the same sorted database advisory locks until all requests finish,
including after an exception or size mismatch. All checks remain required before
database registration and `artifact.ready`. The per-call executor is bounded to
four threads, joins on exit, and is created after worker forks. Immutable writes,
the database/bucket binding and GC reference checks remain in place.

The new single-request regression was run against the prior frozen backend:
`test_bounded_io.py::test_storage_bounded_download_uses_one_request_and_checks_actual_bytes`
failed at the redundant HEAD with `AssertionError: redundant storage round trip`.
The modified source passes that test. Concurrent-check fixtures require all four
requests to reach a barrier, reject mismatched sizes, join other checks on an
error, and reject zero or more than four requested checks.

## Verified results

[Focused and real-storage counts/hashes](latency-storage-test-summary-2026-10-08.json):
75 focused tests passed, zero failed/errors, one platform-specific Windows test
skipped on Linux; all three opt-in real S3 cases passed, zero skips. PostgreSQL,
Redis and private S3 were real isolated services. The real cases cover user and
guest fresh/cache renders, preview/export/SyncTeX/geometry, combined candidates,
candidate export rejection, and identical/conflicting immutable writes.
Changed source, fixtures and benchmark script pass Ruff; Git whitespace checks
pass. These are incremental suites, not another full backend-suite claim.

Actual execution image:
`sha256:df9a8c1332fb3ec4fe80891ff102145f6689810b1f2fa9032916a2b107b59db6`.
Backend source was copied from a Git archive into a new read-only Linux volume,
not edited in the running API/worker volume. Tests and eager benchmarks used
`latexy_engine_root_20261008_test`, Redis 13/12 and its separately bound bucket.
The actual guest used `latexy_test`, Redis 3/2 and its existing private bucket.

## Measurements and their limits

| Probe | Baseline | Candidate | Valid interpretation |
| --- | --- | --- | --- |
| Bounded download, 30 alternating pairs, real S3 + explicitly injected 40 ms per request | median 89.83 ms / p95 103.20 ms; HEAD + GET | median 45.05 ms / p95 47.49 ms; GET only | Removes one RTT; injected delay is not measured production RTT. |
| Four publication size checks, same paired experiment | median 179.68 ms / p95 190.01 ms; serial | median 57.65 ms / p95 69.94 ms; bounded concurrent | Overlaps independent storage RTTs; excludes DB locks and full publication. |
| Actual managed-English Lua eager worker, 30 fresh/cache pairs | fresh median 1.008 s / p95 1.188 s; cache 0.246 s / 0.340 s | fresh 1.644 s / 2.095 s; cache 0.430 s / 0.598 s | Host load changed. This is not a controlled source speedup/regression comparison. |
| Production browser guest field save | 1,833.7 ms action-to-paint; 497.5 ms verified-blob-to-paint | 5,667.3 ms action-to-paint; 728.3 ms verified-blob-to-paint | Baseline used existing warm services; candidate was the restarted prepared worker's first task. Different startup/load conditions; one sample each. |

[Paired transport raw data](storage-rtt-paired-2026-10-08.json),
[baseline 30-pair worker data](render-pipeline-latency-baseline-2026-10-08.json),
[candidate 30-pair worker data](render-pipeline-latency-candidate-2026-10-08.json).
Both worker reports declared `host_load=quiet` when dispatched. Main's separate
worker subsequently showed 32.84% CPU during the candidate run; TeX p50 rose from
0.657 to 1.016 s, and DB/storage/finalization also rose. The candidate run must be
treated as contended despite that original CLI label. No samples were dropped.
The paired transport experiment alternates conditions in the same process/client
and records actual GET/HEAD counts. The download baseline is loaded from the
prior Git snapshot; the size-check baseline is the audited prior serial loop.
It is a mechanism experiment, not a production or whole-engine benchmark.

The old 22.367-second browser sample and contended Lua reports remain preserved.
The new idle-host baseline demonstrates why that number must not be treated as
a universal product latency or as proof of a source change's speedup.

[Warm baseline browser data](browser-2026-10-08-latency-baseline/preview-browser-benchmark.json),
[first-task candidate browser data](browser-2026-10-08-latency-candidate-cold/preview-browser-benchmark.json).
Both used the existing production UI (UI commit `15540528`), actual HTTP guest
admission, prefork Celery, pdfLaTeX, private S3 and SHA-verified PDF bytes. Both
passed seven geometry overlays, keyboard selection, mobile field selection,
Source on demand, and had no runtime/console errors. Screenshots are retained
alongside the reports; the candidate desktop screenshot was visually reviewed.
Candidate job `09128d44-0b0a-4376-b303-e526d26a2b1c` was the first task after worker
readiness at 16:17:00 UTC. Its admission took 393 ms; PDF retrieval took 157 ms.
Baseline job `9dc0f8cf-e166-4927-b807-43e4d6166c88` admission/retrieval took 200/85 ms.
No guest quota reset, cooldown bypass or deadline extension was used.

## Reproduction and remaining work

Run the existing `scripts/benchmark_render_pipeline.py` with `--samples 30
--profile managed_english --compiler lualatex`, the exact source/image identities,
and an explicitly isolated test DB/bucket. Keep the compiler and fixture identical
between conditions. Measure host load throughout, not only before launching.

For the new transport probe, mount the prior backend Git archive read-only at
`/baseline`, current backend at `/app`, and invoke:

```sh
python scripts/benchmark_render_storage_latency.py \
  --baseline-storage /baseline/app/services/storage_service.py \
  --source-commit 36de1a5100ac35e3eb961227f49d61d228edce74 \
  --samples 30 --rtt-ms 40 --output /evidence/storage-rtt.json
```

The probe refuses a database whose name does not end in `_test`, creates only
four synthetic objects under a random test prefix, and cleans up those objects.
It never resets Redis or changes quota settings. Harness script SHA-256 for this
run: `72587bb9070a552ea5cd8ab0fb60b3462b08f78f08066bc2f30cc659d2747f5c`.
One initial mount attempt failed because a new file could not be mounted into
an existing read-only source volume; no measurements ran. Mounting the probe at
`/probe.py` with `PYTHONPATH=/app` resolved that harness issue. An initial Ruff
invocation tried to write its cache into the read-only source; `--no-cache` and
the repository configuration were used for the passing check.

The one-second fresh action-to-paint and 500-ms cached-paint targets remain
uncertified. Direct-worker exact-cache latency is not cached browser paint.
Remaining priorities: controlled cold/warm browser distributions, startup and
durable admission breakdown, renderer CPU/resource headroom under bursts, and
certification of the actual default Lua image/owned-format/assets/region.
The immutable Modal image and independently expected asset fingerprint remain
unprovided; the cloud Lua capability stays closed. No merge, release, production
migration or paid cloud/provider call occurred in this pass. Track #1815, #1820,
#1862 and epic #1814; they remain open.

For the next compiler optimization, keep the existing pdfLaTeX trusted format
separate from Lua acceptance. The [mylatexformat package's build recipe](https://www.ctan.org/tex-archive/macros/latex/contrib/mylatexformat)
documents preamble dumping with an e-TeX/pdfLaTeX format. The
[LuaTeX manual, section 10.1.2](https://tug.ctan.org/systems/doc/luatex/luatex.pdf)
describes bytecode-register persistence and excludes upvalues. These sources do
not certify a direct transfer of our pdfLaTeX preloaded preamble to Lua, including
font state and callbacks. The inference is that a Lua acceleration needs a
separate owned build and content/link/layout/SyncTeX/isolation proof. No source
change in this pass silently switches compilers or enables an uncertified format.

## Additional first-task repair: configure ORM metadata before readiness

Source `d095fb837aef3c599a2a5089c110e6a0eb20a583` prepares all ORM relationships
after required imports and before worker readiness/fork. The previously prepared
worker still deferred all **59** model mappings to the first ownership query.
A clean-process diagnostic observed 0.2936 s for that first configuration. The
new helper leaves zero unconfigured models; a subsequent configuration call
took 0.000265 s. This moves CPU work into startup; it does not eliminate startup
cost or establish a full-render speedup. Database engines, sessions and sockets
are not created by preparation. Failed mappings abort readiness without caching
a successful preparation. [Exact diagnostic](worker-mapper-preparation-2026-10-08.json).

The clean-process invariant fails on the prior source. The initial combined
test run exposed an existing fixture leak: patching SQLAlchemy's engine factory
before importing retention caused retention to retain the raising mock after
pytest restored SQLAlchemy. That produced two real-storage failures. The fixture
now imports the alias before patching both locations; initial import safety is
tested separately in a clean child process. The corrected startup/cold-import
and actual-S3 suites pass together: **8 passed, zero failed/skipped**, 33.923 s.
The three S3 cases overlap the earlier three and must not be added as unique tests.
[All before/failed/fixed counts, node IDs and hashes](mapper-preparation-test-summary-2026-10-08.json).
Ruff and whitespace checks pass. Test tree `524c1f0f...` differs from committed
backend tree `d6c7663f...` only by an import-spacing fix in the test fixture.

The new frozen worker reached readiness at 16:35:34 UTC; its first real job was
`b20a2aaa-9559-4c02-848f-cd94b4537a4b`. The same production guest field flow passed
actual admission, PDF SHA verification, seven overlays, keyboard/mobile editing
and Source on demand. No browser/runtime errors or deadline/quota bypass occurred.
[Full first-task report and screenshots](browser-2026-10-08-mappers-first/preview-browser-benchmark.json).
Action-to-paint was **24,888.9 ms** and verified-blob-to-paint **1,046.9 ms**.
The host became substantially slower while the diagnostic tools ran as well;
this result is retained and does not satisfy the latency gate. One sample cannot
establish a production distribution or attribute that increase to the code.

Current live isolated worker: `latexy-engine-worker-mappers-20261008`, source
`d095fb83`, backend tree `d6c7663f38a516d26b94237d39fb717f6dcc6d26`. The API retains
the storage repair source `36de1a51`; the modified preparation helper runs in the
worker. The production UI is unchanged. All startup and first-task measurements
remain local/native; independently pinned cloud acceptance is still outstanding.
