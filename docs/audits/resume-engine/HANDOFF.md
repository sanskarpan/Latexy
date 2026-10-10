# Resume engine handoff — October 7, 2026

**Historical snapshot:** the owner later explicitly approved continuation.
The [October 8 audit](release-audit-2026-10-08.md) supersedes authorization/status
below and records newer source, checks, preserved failures and remaining gates.
Read it first. This document retains the earlier checkpoint for provenance.

## Current authorization and branch

Draft PR: [#1833](https://github.com/sanskarpan/Latexy/pull/1833), branch `codex/resume-engine`, base `main`. The user requested a complete checkpoint and **no further implementation until they approve continuing**. This includes pausing new validation, cloud/paid-provider calls, deployment and merge. Do not infer approval from this document, the architecture proposal, an open issue or a green CI job.

The source checkpoint is `f814474952d62de15f8c961106aed0fe3908e131`, rebased cleanly onto `origin/main` at `f43307e6`. This handoff is a subsequent documentation commit on that same branch. The main checkout was not used for engine implementation. Another worktree should start from the PR branch, not from the older main-only architecture proposal.

The attached Windows checkout is `C:\Users\Sansk\.codex\worktrees\resume-engine\Latexy`. Paths below are repository-relative so they work in a different checkout. All scripts, fixtures, synthetic benchmark JSONs, selected browser screenshots and audit documents are checked in. Dependency directories, credentials, temporary compiler workspaces and bulk generated template previews are excluded; their regeneration commands are below.

## What to read first

1. [integration-checkpoint.md](integration-checkpoint.md): implementation scope, completed validation and outstanding gates.
2. [frontend-verification.md](frontend-verification.md): final seven production browser contracts, mocked versus live scope, real guest observations and Source/field concurrency limitations.
3. [renderer-migration-validation.md](renderer-migration-validation.md): renderer selection, confined I/O, real storage tests and native Windows proofs.
4. [render-benchmark.md](render-benchmark.md): simulated transport benchmark methodology; it must not be presented as a production benchmark.
5. [issue-tracking-links.md](issue-tracking-links.md) and [migration-tracking.json](migration-tracking.json): issue crosswalk and incomplete acceptance work.
6. [../../MODAL_RENDERER_CAPABILITY.md](../../MODAL_RENDERER_CAPABILITY.md): the closed cloud capability gate.
7. [../../RESUME_ENGINE_ARCHITECTURE.md](../../RESUME_ENGINE_ARCHITECTURE.md): intended architecture, not evidence that every phase is complete.

Epic [#1814](https://github.com/sanskarpan/Latexy/issues/1814) and implementation issues #1815–#1820 remain open. No release, deployment, issue closure or merge is claimed.

## Code map and invariants

| Area | Entry points / modules | Preserve during follow-up |
| --- | --- | --- |
| Renderer, passes and cache | `backend/app/services/render_engine/{backend,passes,cache_policy,auxiliary,trusted_profiles}.py` | Server-owned backend descriptors; explicit capability admission before quotas or paid work; no silent fallback; volatile source bypasses exact/aux caches; compiler/asset identity is part of cache validity. |
| Immutable preview artifacts | `render_engine/{artifacts,admission_cache,coalescing,retention,geometry}.py` | Bind source/revision/PDF hash and ownership/device epoch; keep artifacts private; completed reads use durable terminal authorization after ephemeral Redis ownership expires. |
| Confined diagnostics | `render_engine/quality.py`, `backend/test/test_bounded_io.py`, renderer audit | Read and validate the same file handle; reject links/reparse points/FIFOs; bound child-process time and output; label unavailable checks as unknown. Limited PDF checks are not an ATS certification. |
| Semantic runs and acceptance | `backend/app/services/resume_engine/{document,context,optimizer,semantic_patches,acceptance,ledger,memory,provider}.py` | Frozen evidence, source/node revisions, exact paid-stage replay and full reservation on unknown usage; accepted current wording is authoritative; candidate previews are not accepted exports. |
| Imported source identity | `resume_engine/{imported_identity,imported_identity_db}.py` | Persist identity only across unambiguous matching/reconciliation; regenerate spans from actual grammar; do not revive deleted IDs or enable unsupported imported AI edits. |
| Managed layout controls | `resume_engine/structure.py`, `backend/app/api/resume_structure_routes.py` | Complete sibling permutations, stable IDs, row-lock ownership checks and source/revision CAS; preserve opaque custom source. |
| Original PDF preservation | `resume_engine/pdf_imports.py`, `backend/app/api/pdf_import_routes.py` | Owner-only private original; hash/length validation; explicit supported-template adaptation; extraction confidence remains unknown. Backend tests are pending. |
| Frontend preview/review | `frontend/src/lib/{preview-scheduler,resume-engine-types,pdf-import-types}.ts`, editor components and `frontend/e2e/quality/` | One running/admitted preview plus replaceable latest source; lazy Source editor; fingerprint-bound exact-PDF overlays; post-await source/account guards; backend remains quota authority. |

Migrations included: `0060_semantic_resume_engine.py`, `0061_render_artifact_manifests.py`, `0062_compilation_artifact_acceptance.py`, `0063_imported_node_projection.py`, `0064_private_original_pdf_imports.py`. Fresh schema creation through 0062 was tested earlier; 0063 and 0064 were applied to isolated existing test databases. A fresh initial-to-0064 migration and rollback/data-lifecycle review remain pending.

Original PDF bytes are in a separate deferred database column, not hot Resume queries or Redis. Current bounds are 10 MiB, 1–50 pages, unencrypted PDFs, at most ten staged imports per owner and 24-hour staged expiry. Explicit adaptation binds the attachment to its new resume; bound records do not retain the staged expiry. User/resume deletion cascades. This preserves exact original bytes but does not make arbitrary original PDF layouts directly editable.

## Reproduced bugs, regression fixtures and open limits

The regression files below are checked in. A passing focused run is evidence for its recorded snapshot and scope; it does not establish that the entire frozen PR passes.

| Trigger / reproduction | Fix or limitation | Fixture / evidence |
| --- | --- | --- |
| Complete a render, remove ephemeral Redis job ownership, then request the completed artifact as its legitimate owner. | Durable terminal capability authorizes completed artifact reads; cross-owner access remains denied. Real storage checks passed. | `backend/test/test_render_storage_integration.py`, `test_render_artifact_access.py`, `test_owned_pdf_download_recovery.py`. |
| Guest render completes without a Compilation row; request PDF/geometry after completion. | Durable guest receipt/finalization supports this path. Real guest browser probes and storage integration passed. | `test_render_storage_integration.py`; `preview-browser-benchmark.json`; historical `preview-browser-pre-restart-diagnostic.json`. |
| Edit fields before the first PDF; trigger one preview; switch to Source only afterward. | Resume mode edits and first-use scheduling work without mounting Monaco. | `frontend/e2e/quality/resume-engine-preview.spec.ts`, `frontend/src/__tests__/preview-scheduler.test.ts`. |
| Delay an accepted field/structural response, then make a newer local Source edit while awaiting it. | Post-await guards preserve the newer buffer. Legacy whole-source save already requires `expected_latex_content` under a row lock; final cross-path concurrency review is still pending. | Managed production browser contract; `test_resume_structure_db.py`, `test_imported_identity_db.py`. |
| Replace or rename a compiler-output pathname while it is read; substitute links, junctions, gzip links or a FIFO. | Same-handle confined reads, bounded decompression and private verified diagnostic copies. Actual Linux cases and Windows pathname-race/junction proofs passed. Windows file-symlink fixture creation lacked host privilege. | `test_bounded_io.py`, `test_render_artifacts.py`, `test_pdf_artifact_paths.py`, renderer audit. |
| Compile hostile Lua that attempts an outside link/read. | The actual link-creation attempt was denied; do not claim it demonstrated a production link-creation exploit. Separate synthetic pre-existing link tests exercise the reader boundary. | `scripts/certify_docker_lua_engine.py`, renderer audit. |
| A Poppler child never exits, emits excessive output or watchdog startup fails. | Shared bounded deadline/output and cleanup; actual child-process tests passed. | `test_pdf_quality.py`, `test_process_watchdog.py`, `test_render_passes.py`. |
| Compile `clean_simple` with its section rule; inspect extracted Product label/page bounds. | Paragraph/section-rule fix and hyperlink presentation applied; final matrix passes. Not every template has been visually reviewed. | `template-clean-simple-visual-fix.json`, `template-certification-complete.json`, `scripts/certify_resume_templates.py`. |
| Apply Lua `--safer` to a fontspec/luaotfload document. | That rejected policy disables necessary font loading; historical failure retained. Local confinement is separate from that flag. | `template-certification-safer-rejected.json`, renderer audit. |
| Run actual cached Modal TeX 2022 CJK fixture. | Exit 1 despite PDF output; no retained diagnostic sufficient to establish cause. Broad cloud Lua remains uncertified and closed. Retention script was improved offline; no further cloud retries authorized now. | `scripts/certify_modal_vm_engine.py`, `docs/MODAL_RENDERER_CAPABILITY.md`. |
| Run source-contract/launcher tests on Windows with CRLF and descendant-process cleanup. | Fixtures normalize appropriate newline cases and preserve platform-specific privacy/cleanup assertions. | `frontend-verification.md`, `frontend/src/__tests__/`; final Linux unit/production checks. |
| Missing job requirements contain internal IDs but have a frozen supporting excerpt. | Review UI shows readable frozen evidence; it does not invent a requirement description. | Managed production browser contract in `resume-engine-preview.spec.ts`. |
| Supporting facts change after a suggestion, or a Quick-scope edit borrows unsupported facts. | Frozen evidence and dependency checks block factual additions/deletions; allowed current-run acceptance and unrelated edits remain explicit. | `test_resume_acceptance_dependencies.py`, `test_resume_durable_ledger.py`, `test_resume_semantic_engine.py`. |
| Reorder unchanged imported fields, delete/re-add a field, introduce ambiguous duplicates or concurrently seed metadata. | Persistent unique-field IDs, fresh IDs for ambiguity/reintroduction, verified source spans and database CAS. Fifteen focused cases passed. | `test_imported_identity.py`, `test_imported_identity_db.py`. |
| Reorder a subset, duplicate an ID or move an entry into another parent. | Reject incomplete/cross-scope permutations; valid managed heading/order changes retain identity and regenerate authoritative source. | `test_resume_structure.py`, `test_resume_structure_db.py`; `frontend/e2e/quality/resume-structure-flow.spec.ts`. |
| Skill matches confuse C with C++, aliases or negated mentions. | Boundary/alias/negation guards and context versioning. | `test_resume_skill_mentions.py`. |
| One tenant attempts to consume the global request/token cap; retry the same stage marker. | Atomic per-tenant and global capacity limits with idempotent stage markers. This is capacity capping, not queued fair scheduling. | `test_resume_provider_fairness.py`; 39-case focused run including actual Redis. |
| Stage original PDF, access as another owner, adapt twice, use stale extracted field revision, expire/discard or delete its resume. | Implemented hash/CAS/idempotency/privacy lifecycle; **backend verification pending**. Frontend covers receipt hash mismatch, unavailable extraction, explicit adaptation and original-byte viewing with mocked endpoints. | `test_pdf_imports.py`, `frontend/e2e/quality/pdf-import-flow.spec.ts`. |
| Full backend suite against a changing pre-checkpoint worktree. | 49 failures recorded. Subsequent focused renderer/provider/fixture repairs passed, but no frozen full-suite rerun establishes final status. These are not all proven production defects. | [backend-full-suite-post-rebase-summary.json](backend-full-suite-post-rebase-summary.json), targeted audit notes. |

The full-suite summary retains all 49 failed pytest node IDs, seven skip records, counts and a SHA-256 provenance hash of the local raw log. Raw environment-bearing logs are not committed. Re-run the named fixtures after approval instead of assuming a historical failure is still present or already fixed.

## Reproduction environment — commands for the next approved pass

These commands are documentation, not a request to run them before user approval. Use an isolated test database and Redis indices: fixtures clean up test data and flush their designated Redis databases. Never point them at a shared development or production database.

The completed local runs used Linux Python 3.12/TeX 2025, a QA image with the current hash-verified `requirements-dev.lock`, and Node 22 with pnpm 10.10.0. An older QA image had stale PyJWT and lacked git; resulting harness failures must not be attributed to the product. Do not override the precompiled `PYTHONPYCACHEPREFIX` with an empty cold mount: slow standard-library imports were observed under contention.

Portable QA Dockerfile is now committed as `backend/scripts/Dockerfile.engine-qa`. The exact tested local parent tag is retained. Building again can resolve newer OS packages, so inspect the new renderer asset fingerprint and retain its identity with new results rather than claiming identical image bytes.

```powershell
# From the worktree root, after approval. These build images; no deployment.
docker build -f backend/Dockerfile -t latexy-local-worker:latest backend
docker build -f backend/scripts/Dockerfile.engine-certification -t latexy-engine-certification:20261006 backend
docker build -f backend/scripts/Dockerfile.engine-qa -t latexy-engine-qa:20261007-v2 backend
```

Prepare a local ignored `engine-test.env` from `backend/.env.example`, with dummy local values only. Configure DATABASE_URL, REDIS_URL/REDIS_CACHE_URL, CELERY_BROKER_URL/CELERY_RESULT_BACKEND, TEMP_DIR, CORS_ORIGINS, JWT_SECRET_KEY and API_KEY_ENCRYPTION_KEY. For storage checks also set MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET and MINIO_SECURE=false. Set SKIP_ENV_VALIDATION=true, ENVIRONMENT=test, LATEXY_RENDER_BACKEND=native, DEFAULT_LATEX_COMPILER=pdflatex and RATE_LIMIT_ENABLED=false for isolated pytest runs. Leave paid provider keys blank and select local deployment. Setting SKIP_INFRA_CHECK=true is only appropriate for an explicitly infrastructure-free subset; it does not validate persistence or real Redis/storage.

The isolated existing local service names are `latexy-engine-migration-db-20261006` (PostgreSQL/pgvector), `latexy-engine-migration-redis-20261006` and `latexy-engine-migration-minio-20261006` (actually RustFS), on `latexy-engine-migration-20261006`. Their test credentials are dummy local values. Databases `latexy_test` and `latexy_engine_full_test` reached migration 0064. The root full run used Redis 13/12; other agents used different pairs. Serialize fixtures on the same pair. The live API on port 8530 and worker may still have old modules loaded: restart only these isolated services in an approved pass before asserting live latest-code behavior. Do not touch other main-checkout services.

```powershell
# Set task-specific variables for your isolated infrastructure.
$engineWorktree = (Get-Location).Path
$engineEnvFile = Join-Path $engineWorktree 'engine-test.env'
$engineTestDatabaseUrl = 'postgresql+asyncpg://latexy:latexy_test_password@latexy-engine-migration-db-20261006:5432/latexy_engine_full_test'
$engineTestRedisUrl = 'redis://latexy-engine-migration-redis-20261006:6379/13'
$engineTestCacheUrl = 'redis://latexy-engine-migration-redis-20261006:6379/12'

# Frozen full backend verification; retain its immutable commit and image identity.
docker run --rm --no-healthcheck --network latexy-engine-migration-20261006 `
  --env-file $engineEnvFile --mount "type=bind,source=$engineWorktree,target=/repo,readonly" `
  --workdir /repo/backend -e "DATABASE_URL=$engineTestDatabaseUrl" `
  -e "TEST_DATABASE_URL=$engineTestDatabaseUrl" -e "TEST_REDIS_URL=$engineTestRedisUrl" `
  -e "TEST_REDIS_CACHE_URL=$engineTestCacheUrl" -e PYTHONDONTWRITEBYTECODE=1 `
  -e TEMP_DIR=/tmp/engine-full-regression-final latexy-engine-qa:20261007-v2 `
  python -m pytest -p no:cacheprovider -ra `
  -W error::ResourceWarning -W error::RuntimeWarning `
  -W error::pytest.PytestUnraisableExceptionWarning
```

For targeted runs, use the same isolated Docker harness and replace its final pytest arguments with these paths. All are real tracked files; an earlier command used nonexistent `test/test_resume_engine_api.py` and stopped before collecting the PDF import suite.

```text
# Pending original-PDF backend lifecycle, including real PDF parser fixtures:
test/test_pdf_imports.py

# Imported identity and managed structure:
test/test_imported_identity.py test/test_imported_identity_db.py
test/test_resume_structure.py test/test_resume_structure_db.py

# Acceptance, paid-stage recovery, memory and capacity:
test/test_resume_acceptance_dependencies.py test/test_resume_durable_ledger.py
test/test_resume_decision_memory.py test/test_resume_provider_fairness.py

# Renderer boundaries and bounded diagnostics:
test/test_bounded_io.py test/test_render_artifacts.py test/test_render_passes.py
test/test_renderer_backend.py test/test_renderer_callsites.py test/test_pdf_quality.py

# Real PostgreSQL/Redis/private object-storage integration:
test/test_render_storage_integration.py
```

For the last file, additionally pass `-e RUN_RENDER_STORAGE_INTEGRATION=1` and supply the isolated storage configuration. Without it, the three cases intentionally skip. The older full run's other four skips were unavailable Apple host fonts, not evidence against Linux Noto glyph checks. Native Windows reparse tests require Windows; file-symlink creation may require privileges unavailable on this host.

Frontend checks from the root, after approval:

```powershell
pnpm install --frozen-lockfile --ignore-scripts
pnpm --filter Latexy-frontend prepare:monaco
pnpm --filter Latexy-frontend test:unit
pnpm --filter Latexy-frontend lint
pnpm --filter Latexy-frontend typecheck
pnpm --filter Latexy-frontend build
```

Run production browser contracts against a correctly configured standalone production server, not just a dev server. The quality config normally launches its own server; set `PLAYWRIGHT_REUSE_EXISTING_SERVER=1` and `PLAYWRIGHT_QUALITY_PORT` to reuse the prepared production server. Use `ENGINE_QA_CHROME=1` for installed Chrome. From `frontend`:

```powershell
pnpm exec playwright test --config=playwright.quality.config.ts --project=desktop-chromium e2e/quality/resume-engine-preview.spec.ts e2e/quality/pdf-import-flow.spec.ts e2e/quality/resume-structure-flow.spec.ts
```

The recorded seven passing production contracts used valid PDF bytes with mocked auth/API/stream responses. They do not establish live import backend behavior, model quality or production latency. Build with inert dummy authentication/database settings; no production credentials are necessary.

## Benchmarks and certification artifacts

| Evidence | Meaning and limits |
| --- | --- |
| `render-benchmark*.json`, `render_baseline.py`, `render-benchmark.md` | Real TeX with simulated Redis delays, paired baseline/current samples. Transport mechanism evidence, excluding real queue/storage/browser. |
| `render-pipeline-real-storage-contended.json` | 30 fresh and 30 cached direct worker/storage samples; fresh p50/p95 2.874/5.528s, exact 0.766/1.712s. Excludes HTTP admission, Celery queue and browser. |
| `render-pipeline-real-storage-quiet.json` | Fresh 3.807/9.064s, exact 0.907/2.034s. Despite the filename, a competing main process used about 104% CPU; this is not a controlled quiet-host result. |
| `trusted-preloaded-format*.json` | Format prototypes, not universal SLO proof. |
| `trusted-format-installed-certification.json` | Three owned English pdflatex profiles retain exact source/text/bounds/72-DPI rendering/forward mappings. Current default new-resume Lua path does not obtain these pdflatex format gains. |
| `template-certification-complete.json` | Final 61/61 fixtures, 122 two-pass CLI samples; compiler/recorder/extracted-text/font-glyph checks, including presentations. Resume p50 6.726s/p95 20.158s. Not all visuals or overlay interactions reviewed. |
| Earlier template reports (`final`, `font-*`, `safer-rejected`, etc.) | Historical diagnostic failures retained with their scope. `complete` is the final matrix; do not select an older report as current certification or silently remove evidence of failures. |
| `preview-browser-two-samples.json`, `preview-browser-benchmark.json` and PNGs | Three actual normal guest samples under contention, two contexts. Initial 2,331ms; identical-input 30,205ms; field-before-compile 29,259ms. Exact hit used zero TeX. Three samples are not percentiles. |

Scripts to regenerate evidence, from `backend` inside the matching renderer environment, after approval:

```text
python scripts/certify_resume_templates.py --samples 2 --timeout 120 --output /evidence/template-certification.json --render-directory /evidence/template-visuals
python scripts/verify_trusted_formats.py --output /evidence/trusted-format-certification.json
python scripts/benchmark_render_pipeline.py --samples 30 --host-load unspecified --output /evidence/render-pipeline.json
```

Mount a writable evidence directory separately from the read-only source. Template/format certification needs the actual TeX/fonts/confinement environment; the pipeline benchmark also needs isolated database/Redis/object storage. Inspect each script's arguments and retain image/fixture identity with the new report. The simulated baseline command and its required network-disabled mounts are documented in `render-benchmark.md`.

The live browser script is `frontend/scripts/benchmark-preview-browser.mjs`; its isolated endpoints are frontend 5361 and API 8530. `ENGINE_QA_FIELD_FIRST=1` exercises an edit before first compilation. It uses normal guest admissions and respects the existing five-minute cooldown; do not bypass quota or infer TeX time from user-action wall time. Development probes need the declared Turbopack path; production bundle correctness was verified separately.

Bulk generated final template PDFs/PNGs were outside the checkout at `C:\Users\Sansk\.codex\worktrees\resume-engine\template-final-visuals`. They can be regenerated with the command above. The final JSON retains per-fixture correctness data; selected browser PNGs are committed. Baselines and synthetic fixtures are portable without that temporary output directory.

## Required next gates after explicit approval

1. Freeze the reviewed branch and run the complete backend suite, including the unexecuted PDF import tests and opt-in real storage tests. Classify remaining failures with exact node IDs, reproduction and immutable commit/image identity. Do not add overlapping focused test counts together.
2. Validate initial-to-0064 schema creation, retention/cleanup, owner-only attachment access, idempotent adaptation and user/resume deletion against real services. Complete live Source/field/structural concurrency review.
3. Review representative template visuals, mixed scripts, columns and exact-PDF keyboard/mobile overlays. Unknown/ambiguous/rotated mappings must remain conservative.
4. Measure controlled fresh/cache distributions, production user-action-to-paint, queue/cold-start/burst and regional behavior. One-second fresh PDF and 500-ms cached paint targets are **not met or certified** by current evidence.
5. Keep broad Modal Lua disabled until separately authorized certification resolves the actual CJK failure. No additional cloud spend or paid-provider tests are authorized by this checkpoint. Paid-provider quality remains unmeasured.
6. Obtain independent PR review and required CI checks before any eventual merge. Leave this PR draft and all migration issues open until their acceptance gates are actually satisfied.

Until the user approves continuation, the complete action is to retain this checkpoint and report the draft PR.
