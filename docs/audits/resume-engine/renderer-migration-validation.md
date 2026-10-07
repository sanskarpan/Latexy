# Renderer migration validation

Worktree only. No production latency claim follows from these local results.

## Actual infrastructure integration

`backend/test/test_render_storage_integration.py` runs against isolated real PostgreSQL, Redis Lua and RustFS (the repository's S3-compatible local storage engine). The conditional immutable-write test proves first upload, identical reuse and rejection of different bytes at the same key through the actual boto3 SDK.

The admitted render test performs a real one-page pdflatex compile, persists immutable PDF, SyncTeX and verified PDF text geometry, publishes `artifact.ready` before `job.completed`, and commits the owner-bound manifest through the durable finalization arbiter. Redis contains compact pointers rather than PDF or SyncTeX binaries. A second direct job reuses checked PDF bytes with compiler spawning forbidden, while receiving its own manifest/owner/job identity. A third admitted combined render stage reuses those bytes as a candidate, permits authenticated preview/SyncTeX/geometry, and rejects authoritative export before acceptance. Full accepted-candidate receipt behavior is separately owned by the semantic acceptance tests.

This integration uncovered a real endpoint defect: terminal publication removes the Redis owner field, so the first version of the completed artifact read fence rejected successful jobs. The endpoint owner corrected this while retaining refreshed durable owner-token hashing, epoch, cancellation, pointer and conflicting-owner checks.

Three actual storage/renderer integration tests passed after adding guest coverage. The guest test proves first compile plus exact cache, completed durable manifest PDF binding without a Compilation row or a legacy upload, device retention at most 24 hours, completed PDF/geometry/SyncTeX/export and wrong-fingerprint rejection. It caught and fixed a guest-only finalization bug: private immutable manifest binding originally ran only when a Compilation row existed.

Eleven tests initially passed together: two actual storage/renderer integrations plus nine volatile-source cache-policy cases. Thirty-eight renderer/artifact/retention/pass/coalescing/cache-policy/log-gating tests subsequently passed after enforced Lua launcher integration. The actual S3 integration uses pdflatex; Lua kernel security and full template certification are independent evidence.

## Warm actual pipeline benchmark

Script: `backend/scripts/benchmark_render_pipeline.py`. Evidence: `render-pipeline-real-storage-contended.json`.

Thirty fresh distinct one-page synthetic resume renders and thirty exact-cache renders alternate deterministically, with three fresh warmups and an exact cache seed excluded. Geometry is enabled. Every measured operation uses actual pdflatex, Redis Lua, PostgreSQL and S3 storage. Wall time includes eager direct-worker execution, worker ownership admission, artifact publication, geometry and durable finalization. Public HTTP quota admission, Celery queue transport, AI, browser paint and cold image startup are excluded. Synthetic row setup occurs before timing; cleanup deletes only this script's own rows and never flushes Redis.

The first run shared a 12-logical-CPU Docker VM with the 61-template certification (2 CPU limit), API/Celery and Next development/browser QA. It is explicitly a contended-host run, with no resource-controlled baseline.

| Condition | Samples | p50 | p95 |
| --- | ---: | ---: | ---: |
| Fresh render wall | 30 | 2.874 s | 5.528 s |
| Exact-cache wall | 30 | 0.766 s | 1.712 s |
| Fresh TeX process totals | 30 | 1.715 s | 3.546 s |
| Fresh output drain totals | 30 | 0.028 s | 0.060 s |
| Fresh buffered event publication totals | 30 | 0.012 s | 0.038 s |
| Fresh object PUT totals | 30 | 0.147 s | 0.526 s |

Phase durations overlap and cannot be added to infer total wall time. The initial storage phase excludes registry DB and HEAD operations. Subsequent instrumentation includes manifest registry storage and finalization/cache-lookup spans; that difference must be retained when comparing the next quiet-host run. The fresh p95 below one second target and below two seconds milestone were both unmet in this contended run. A quiet-host rerun is required before diagnosing stable latency or making claims about deployment behavior.

### Project-heavy-tests-paused rerun

Evidence: `render-pipeline-real-storage-quiet.json`. Certification and browser workloads were paused by the coordinator. This filename describes that requested rerun, not a resource-isolated host: the existing main backend was sampled at about 104% CPU while isolated API/worker were below 1%. Main services remained untouched. Results do not demonstrate a quiet-host speedup.

| Condition | Samples | p50 | p95 |
| --- | ---: | ---: | ---: |
| Fresh render wall | 30 | 3.807 s | 9.064 s |
| Exact-cache wall | 30 | 0.907 s | 2.034 s |
| Fresh TeX process totals | 30 | 2.317 s | 5.561 s |
| Fresh output drain totals | 30 | 0.033 s | 0.102 s |
| Fresh artifact storage including registry | 30 | 0.338 s | 1.251 s |
| Fresh terminal finalization | 30 | 0.257 s | 0.638 s |
| Exact-cache artifact storage including registry | 30 | 0.268 s | 0.556 s |
| Exact-cache terminal finalization | 30 | 0.284 s | 0.730 s |

The fresh targets remain unmet. The best fresh sample was 1.841 seconds. Actual compiler transcripts confirm two pdflatex passes: a first `rerunfilecheck` warning about `resume.out`, followed by a clean second pass. There were no observed mktex font-generation lines. Buffer drainage is a small measured component; TeX execution and durable storage/finalization require separate investigation. Appropriate next experiments are a resource-controlled hardware profile, certified one-pass templates and a dependency-validated trusted template preloaded format. Skipping convergence or removing ownership/storage checks would invalidate correctness.

To reproduce, run the certification worker image with backend mounted read-only, evidence mounted writable, dummy isolated S3 credentials and explicit isolated `DATABASE_URL`, `REDIS_URL`, `REDIS_CACHE_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` and `MINIO_BUCKET`. Set `PYTHONPATH=/app`, `ENVIRONMENT=test`, `SKIP_ENV_VALIDATION=true`, and job-local `TEMP_DIR`; invoke `python scripts/benchmark_render_pipeline.py --samples 30 --host-load contended --output /evidence/result.json`. The script refuses a database whose name does not end with `_test`.

## Supported behavior and limits

- Exact cache identity covers tenant scope, prepared source, all compile settings including bibliography, compiler, image/assets fingerprint, Lua confinement policy and renderer epoch. Raw draft-source SHA remains separate from prepared render-source SHA. Visible date/time/random/ambient-file primitives and unresolved dynamically assembled names bypass reuse. This optimization scanner does not prove arbitrary opaque TeX/package determinism; supported resume capability profiles must not add hidden dependencies.
- Auxiliary reuse serializes a bounded document-profile lease and restores only numeric label facts from a closed grammar. A restored snapshot forces a fresh verification pass. Arbitrary executable `.aux`/`.bbl` content is not restored.
- At most three TeX passes share one original compile deadline. Classic BibTeX supports the isolated `references.bib` datasource and six installed styles. Biber fails explicitly until an isolated datasource adapter exists.
- Verified PDF semantic geometry uses actual text bounding boxes, strict source/document/revision identity, unique text matches and per-page rotation checks. Ambiguous, unsupported, rotated or budget-exhausted mappings remain read-only. No guessed SyncTeX geometry is exposed.
- Lua logs remain private until every pass clears recorder confinement; failed, canceled and timed-out unverified transcripts are withheld. Native and Docker Lua command construction uses the enforced kernel launcher; environments incapable of establishing it fail closed. Kernel launcher security/certification belongs to separate evidence.
- Reference-aware GC with a bounded object count and a soft wall budget between SDK operations protects live shared manifests and accepted authenticated compilation pointers beyond job TTL, preserves an orphan-upload grace, and cannot promote an unaccepted candidate. An immutable bucket/database binding rejects cleanup against an unintended database; deployments must use consistent normalized database endpoint identity.

## Trusted static format certification

The [mylatexformat package](https://ctan.org/pkg/mylatexformat) supports dumping an initialized preamble. The image build script accepts no source arguments: it uses only the shared repository-owned English builder preamble, installs a root-owned readonly pdflatex format and a bounded manifest, and runs before renderer fingerprint generation. Runtime verification checks the fixed profile ID/preamble, compiler binary, format size/hash and manifest identity. Missing, mismatched, writable or symlinked assets, changed preambles, other compilers and unverified external Docker image dispatch use ordinary rendering. The format identity participates in exact cache identity; admission and worker asset disagreement therefore causes a cache miss. Original source lines remain intact and all required convergence passes remain enabled.

`trusted-preloaded-format-all-records.json` records ten alternating prototype pairs. Every pair had identical extracted text, rendered first-page PNG, forward SyncTeX coordinates and all 306 source-addressed SyncTeX records, including box and leaf records. Both paths required two passes. This proves equivalence for that fixture, not the latency objective: runs had uncontrolled host CPU contention, and measured p95 remained well above one second. The initial narrower experiment is retained separately. `scripts/verify_trusted_formats.py` additionally certifies the actual installed profile selected by runtime verification across three managed body/category variants; the installed profile passed for `ats_safe`, `executive` and `graduate` in `latexy-engine-formats:20261007`. Evidence is `trusted-format-installed-certification.json`: all three preserve original source SHA, text, PDF word-box geometry, page PNG and every source-addressed SyncTeX record (358, 351 and 360 records). The image asset fingerprint is `e0af4b7700173a60e6de53460015c98f68cbdf8972d5175ef2b3c02b7fc7e7d0`. Eleven identity/fallback unit cases, including same-size post-verification asset mutation, pass. These are correctness checks; they do not establish the latency target.

Legacy asynchronous compilation now reuses the shared convergence policy after its first recorder check. Its cancellation event terminates threaded auxiliary work and waits for that work to finish before workspace cleanup, including repeated cancellation. Additional failures return bounded safe errors. Target verification includes a real reference-resolution document and cancellation cleanup ordering; full backend verification remains required.


## Renderer backend selection and bounded inspection

The server-owned renderer descriptor now drives direct compilation, combined rendering, auto-fit probes and auxiliary passes. Effective backend/image/assets/policy identity is selected before exact-cache lookup. A mutable Docker image tag is explicitly unverified and disables exact and auxiliary reuse; an unavailable selected Docker backend fails instead of silently switching execution policy. Native rendering retains the enforced Lua kernel launcher. Modal Lua requires an explicitly certified pinned bare image and actual assets fingerprint; the certified production gate remains closed pending successful full capability proof.

Modal process adapters preserve one per-job session across additional TeX and classical BibTeX passes, with the original deadline, workspace and immutable image/policy. Cancellation closes the whole session; outer workflow cleanup closes successful or failed sessions. Raw engine exit is measured before bounded remote output export, which remains output-drain time. Seven focused callsite cases cover backend cache identity, same-session passes, missing-session failure, combined safe/escaped Lua output and cancellation. This adapter integration does not itself certify a cloud deployment or a latency SLO.

PDF semantic geometry inspection captures Poppler output through a bounded pipe, shares a six-second deadline across its commands, and kills/reaps children on overflow or silent timeout. Oversized XML can no longer grow a temporary extraction file before the cap is checked. Every page rotation remains checked; extraction failure preserves a read-only PDF. Actual child-process cleanup regressions cover overflow and silence.


## Generated-file trust boundary

Generated file readers now open the final file atomically without following links and inspect the same open handle for regular-file type and size. POSIX uses `O_NOFOLLOW`, `O_NONBLOCK` and `fstat`; Windows uses `CreateFileW(FILE_FLAG_OPEN_REPARSE_POINT)`, same-handle reparse attributes and descriptor-backed reads. The gzip reader shares this boundary. Direct and combined workers classify untrusted filesystem outputs as terminal confinement failures. Geometry reads validated PDF bytes through this boundary, verifies their PDF hash and gives Poppler a private bounded copy, so subsequent replacement of the original path cannot redirect extraction.

Actual POSIX fixtures reject ordinary and gzip output symlinks, FIFOs without blocking, and a pathname replaced with a symlink at the moment of open. Actual confined Lua link creation was rejected by the preserved no-shell-escape policy with `LuaTeX: operation not permitted`; this experiment does **not** establish a production link-creation exploit. A separate synthetic pre-existing workspace-link rename fixture exercises the reader boundary without granting protected source reads. Generated links are rejected regardless of compiler behavior.

The Windows regular-file handle was exercised natively. The written Windows regression intercepts actual handle creation only to replace its pathname immediately after open; the read still returns the original safe file bytes, proving post-open pathname replacement cannot redirect the same-handle read. An actual Windows directory junction was additionally rejected through its open reparse-point handle. Creation of a file symbolic-link fixture was denied by host privileges, so that particular native negative fixture remains unavailable. The final-file no-follow behavior follows the [Microsoft CreateFileW contract](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew); the same-handle attribute checks reject reparse points and directories before reading payload bytes.

After post-rebase fixture repair, all six formerly failing renderer files passed together (222 tests). A subsequent bounded-I/O/artifact/pass/backend/retention/workspace/legacy-convergence gate passed 95 tests. Image source parity and compact LLM deadline checks are owned by separate verification. These test counts describe those runs, not a claim that the final full suite has passed.

The latest opt-in integration against actual isolated RustFS, PostgreSQL and Redis passed all three cases after the backend descriptor, geometry private-copy and no-follow-reader changes: immutable conditional writes; authenticated direct/exact-cache/combined-candidate preview and export fences; and guest first/exact-cache completed PDF, geometry, SyncTeX and export.

Final latest-source renderer verification passed **275 tests**, with one expected Linux skip for the native Windows handle fixture, across beamer, compile timeout, sandbox, orchestrator, direct worker, timing, bounded I/O, backend callsites and artifacts. The written Windows handle fixture was executed separately on the native Windows host and passed. Ruff passed on every changed renderer/utility/fixture file. The broader backend full-suite gate remains separately coordinated.
