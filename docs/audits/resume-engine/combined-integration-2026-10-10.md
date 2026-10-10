# Engine and guided-builder integration — October 10, 2026

## Status and provenance

This records the reviewed integration for [PR #1833](https://github.com/sanskarpan/Latexy/pull/1833)
after [PR #1834](https://github.com/sanskarpan/Latexy/pull/1834). It is not an
exact-head CI, production deployment, renderer certification or latency acceptance
report. PR #1834 merged as `fb68ae0652a7b95f9d6d22861eee8e73f86d3408`.
Its tree is identical to the reviewed incoming head. The actual-main merge
retained the prepared implementation tree byte-for-byte. The published combined
head must still pass the repository gates.

- Published engine head at preparation: `680bfc5c87084a408a290c3aaec976a29c970557`.
- Incoming billing/builder head: `6e9a1612f03f9a5141fb025f4331dcb23450b78b`
  (tree `46014b646cb683f38e236a63fd6164fd71de90c5`).
- Prepared implementation tree before this report:
  `3d3130ff1c9e2f272edcefa80a1415021f13a1b0`.
- Main at preparation: `c21bcc20f7060b09269375f1b1f8f0b4f8229bae`.
- Integrated actual main: `fb68ae0652a7b95f9d6d22861eee8e73f86d3408`.
- The 21 initial conflicts were resolved locally; the later source-identity and
  final UI corrections from PR #1834 were reconciled as well.

## Scope reviewed

The remaining engine delta is a broad release, not a telemetry-only patch. It
includes persistent semantic documents/import identity, provider-backed reviewed
optimization, immutable PDF/SyncTeX/geometry artifacts, renderer/cache/convergence
policies, admission/finalization/recovery, editor modes and preview scheduling,
and deployment capability checks. Historical audit assets account for a large
part of the file count and are evidence, not additional runtime modules.

The integration preserves PR #1834's Dodo-only implementation, migrations through
`0068`, read-only billing rollout guard, versioned new-only billing/builder
mutations, builder capability gating, source-change detachment/cache helper,
owner checks and fresh locked-row validation. The authentication and callback
fixes already on main remain in the integration. Shared billing runtime and
preflight files were compared against the incoming head rather than reconstructed
from the older engine branch.

The deployment workflow orders billing configuration checks, renderer
configuration checks, database migrations and deployment. It does not expand the
existing secret bindings or deployment permissions.

## Corrected integration defects

1. Managed engine edits, reorder and accepted semantic changes now advance the
   existing builder compare-and-swap token exactly once for an actual change.
   They preserve the managed attachment and synchronize linked variants. Raw
   source writers continue to use the incoming detachment helper. Projection
   defaults, reads, rejected/replayed decisions and no-ops do not create changes.
2. Later-pass cancellation and timeout retain their terminal outcome, quota
   metadata and accepted-finalization-only refund behavior. Interrupted output
   does not become a successful artifact or published diagnostic.
3. The editor has one guarded automatic-preview scheduler. Manual admission
   supersedes older pending automatic work without dropping a newer edit made
   during its acknowledgement or result. Owner/incarnation changes fence old
   callbacks.
4. Resume, Source and legacy Visual modes retain source bytes and saved
   preferences. Comments and deep links remain reachable with existing access
   restrictions. A missing supported engine capability uses the explicit source
   fallback; authentication failures remain distinct.
5. The engine's first-use source is compatible with its bounded parser without
   widening the parser or changing the existing legacy Visual sample.
6. Incoming UI fixes are retained: saved XeLaTeX is not silently remapped; PDF
   cache identity includes all seven forwarded compile settings; the AI Apply
   click does not pass a mouse event as source; one-line opaque environments do
   not hide following editable prose.
7. Browser editor fixtures explicitly select Source mode and mock capability and
   absent original-import reads. They retain unknown-request rejection and the
   actual compile, PDF, SyncTeX and cadence assertions.

Independent source reviews covered the backend merge, managed writer invariants,
render terminal behavior and final editor/scheduler integration. They found no
remaining blocker in those bounded reviewed changes. This is not a claim that
all possible behaviors in the broad release were independently certified.

## Verification on the prepared implementation

Counts below overlap and must not be added together as a unique-test total.

- Frontend: 1,561 tests across 224 files passed, full ESLint passed and
  nonincremental TypeScript passed.
- Backend merge: 67 selected DB-free tests passed; full backend Ruff passed.
- Managed-source integration: 88 tests across seven files passed, including 21
  new cases and independently committed PostgreSQL stale-session scenarios.
  The 32 incoming source-mutation regressions also passed.
- Renderer terminal behavior: 30 focused tests passed, including 24 new cases
  covering cancellation, timeout and generic failure across plan/ownership and
  finalization outcomes.
- Billing/renderer preflight and deployment parity: 81 selected tests passed.
- Actual engine projection/edit of the new first-use source: six tests passed.
- Latency and readiness contracts: 72 tests passed with the isolated PostgreSQL
  and Redis test environment, including phase boundaries, worker preparation,
  parallel upload/check completion, quick ATS scoring and complete job timing
  logs. A preliminary no-infrastructure run passed 53 but could not set up six
  endpoint cases; the infrastructure-backed run supersedes those setup errors.
  These are functional contracts, not end-to-end production latency samples.
- The dedicated integration database upgraded through migration `0068` without
  altering the separate billing test database.

The complete combined backend suite and exact combined browser gates still
require CI. Three local benign real-pdfLaTeX convergence tests could not compile
because this host lacks a usable `pdflatex.fmt`; their environment failure is not
a passing renderer proof. No security-sensitive probes were performed during
this integration review.

The canonical production build compiled locally, then the process was killed
with exit 137 during Next's combined type/lint phase. A single solo retry with a
1.5 GB Node heap compiled in 19 seconds and ended with the same exit. Standalone
types and lint passed, but a complete production build/artifact pass is not
claimed. Exact combined Linux CI must close this gate; no build guard was disabled.

Published engine head `680bfc5c` previously passed 142 cross-browser quality tests
with three skips. Its later explicit editor/Settings stage passed 46 and failed
five editor fixture setups before Monaco mounted; hydration was consequently
skipped. The local fixture repair and newer integration scheduler changes need
fresh exact-head browser results. PR #1834's passing build and browser results
cannot stand in for the combined engine result.

## Deployment and latency acceptance remain separate

The renderer preflight checks only the required configuration tuple using the
existing bound runtime. It cannot establish that the configured image or asset
fingerprint has been independently certified, and its report always leaves
`certification_verified` false. Missing configuration stops automatic backend
rollout before migrations. The frontend capability fallback protects the
corresponding version skew. No certification flag or image identifier was
invented to make deployment pass.

The historical production audit remains the production baseline: guest compile
to visible PDF 18.823 seconds, overlapping saved compile 57.736 seconds, and an
import conversion stuck beyond three minutes in the then-observed model/retry
failure. No new production timings were collected here. Existing local paired
worker measurements are slower on the candidate and need controlled alternating
runs to separate host effects from regression. Simulated storage-delay savings
are not production speedups.

The one-second fresh-PDF and 500-millisecond cached-first-paint acceptance targets
remain open. The next authorized performance run must identify the deployed
commit/image/profile and measure cold, warm, exact-cache and overlapping/burst
cases with end-to-end browser paint and stage timing. Initialization, source
preparation, queue wait, compile, upload/manifest/finalization and PDF paint must
be interpreted separately, with no source/user content in telemetry. Neither
mergeability nor mock-based tests establish production latency or paid-provider
quality.

## Remaining reasons PR #1833 is not acceptance-complete

The corrected defects above are implemented and reviewed; they are not requests
for another speculative rewrite. The outstanding evidence is:

1. **Exact integrated-head gates:** the complete backend suite, canonical
   production build/artifacts, every browser stage and other required PR checks
   must finish on the published merge with actual main. Earlier engine and
   builder heads do not establish this result. At this documentation checkpoint,
   the refreshed combined publication/CI result has not been established.
2. **Local validation limits:** the two canonical build attempts ended with exit
   137 after compilation; browser launch is blocked by the recorded host
   `EPERM`; three real pdfLaTeX convergence cases lack a usable `pdflatex.fmt`.
   These are unresolved environment/evidence limits, not passing gates or proof
   of a product defect. Use the exact-head Linux runner rather than disabling
   checks or retrying the restricted browser on this host.
3. **Deployment prerequisites:** the configuration-only renderer preflight is
   required alongside billing preflight. No independently certified production
   Lua image/assets/default-flow tuple has been established by this integration.
   A well-formed configuration is insufficient to authorize rollout.
4. **Production performance:** cold/warm/cache/overlap/burst action-to-paint
   distributions are unmeasured for the combined deployment. Historical
   production timings are slow, and the fresh/cached acceptance targets remain
   open. Mocked browser contracts and phase instrumentation cannot close them.
5. **Slower local candidate:** the recorded whole-worker candidate is slower
   than its baseline; host effects versus code regression remain unresolved.
   Smaller isolated transport savings do not resolve that comparison.
6. **Configured-provider conversion:** code fixes and controlled tests cover
   the previously stranded conversion, but successful live configured-model
   output, prompt terminal failure and exactly-once quota refund/recovery still
   need separately authorized acceptance. Provider quality/availability and the
   broader engine release must not be inferred from these mocks.

## Operator handoff checklist

This is an execution plan, **not permission to deploy, spend provider/cloud
quota, create credentials or perform security probes**. None of those actions
was executed for this checklist. Obtain the applicable authorization first.
Use synthetic resumes and ordinary authorized QA accounts; never bypass quotas,
reset cooldowns or weaken ownership, durability, compiler policy or test guards.
All shell examples below use repository-relative paths. Variables denote
operator-supplied, verified identities/paths, not values to invent.

### A. Freeze and close current exact-head CI

- [ ] Record the published PR head SHA, its tree, actual-main merge parent, CI
  run URL, runner/platform and dependency lock identities. Confirm the tested
  checkout is that exact head. Update this artifact/PR with terminal job results,
  failed node IDs and retained artifact IDs/hashes; a pending, skipped-required,
  cancelled or superseded run is not acceptance.
- [ ] Follow [the current CI workflow](../../../.github/workflows/ci.yml), using
  Python 3.12, Node 22 and pnpm 10.10.0 with committed locks. Require the full
  backend tests, backend/frontend lint, frontend units/build, deployment parity,
  template extraction, cross-browser quality, full-stack smoke and every other
  required check. Explain any classifier skip against the actual changed paths;
  do not manually narrow the merge gate to the new tests only. Include required
  external review/check results on the same head.
- [ ] The workflow's backend reproduction commands, from `backend`, are below.
  Use its isolated PostgreSQL/Redis configuration and complete dependency/tool
  setup. Tests can clean up data; never use a shared or production database.

  ```sh
  uv pip sync --require-hashes --verify-hashes requirements-dev.lock
  uv run alembic upgrade head
  uv run pytest --tb=short -q \
    -W error::ResourceWarning -W error::RuntimeWarning \
    -W error::pytest.PytestUnraisableExceptionWarning
  uv run ruff check app/ test/
  ```

  Retain migration-through-`0068` output and classify actual compiler/platform
  skips. For the separate real private-storage gate, use the existing isolated
  harness in [HANDOFF.md](HANDOFF.md#reproduction-environment--commands-for-the-next-approved-pass)
  with `RUN_RENDER_STORAGE_INTEGRATION=1` and
  `test/test_render_storage_integration.py`; absent that opt-in its skips are not
  storage acceptance. The older handoff's historical migration/status statements
  do not replace the current `0068` integration evidence.
- [ ] From `frontend`, with the workflow's synthetic build settings, run the
  tracked canonical commands. Keep production HTTPS auth validation and all
  build checks enabled. `pnpm build` already runs artifact validation after
  Next; standalone type/lint results cannot replace it.

  ```sh
  pnpm install --frozen-lockfile
  pnpm test:unit
  pnpm lint
  pnpm exec tsc --noEmit --incremental false
  pnpm build
  node scripts/validate-build.mjs artifacts
  ```

  Closure requires nonempty `BUILD_ID`, build/prerender/routes/app-paths
  manifests and the standalone `[frontend/]server.js` entrypoint, as enforced by
  [validate-build.mjs](../../../frontend/scripts/validate-build.mjs), not merely
  “Compiled successfully”. Record the runner's actual resource limits if a
  repeat is killed; do not suppress lint/types to manufacture a build pass.
- [ ] On the authorized Linux browser runner, execute **all three** workflow
  browser stages. Install engines using the workflow's
  `pnpm exec playwright install --with-deps chromium firefox webkit` setup.
  From `frontend`, the commands are:

  ```sh
  pnpm test:quality
  PLAYWRIGHT_PORT=5183 PLAYWRIGHT_SERVER_MODE=production \
    pnpm exec playwright test e2e/editor-compile-sync.spec.ts \
    e2e/resume-builder.spec.ts e2e/builder-capabilities.spec.ts \
    e2e/billing-developer.spec.ts \
    e2e/settings-provider-action-owner-isolation.spec.ts \
    e2e/onboarding-owner-isolation.spec.ts \
    e2e/settings-preferences-owner-race.spec.ts \
    e2e/settings-legacy-callback-owner-isolation.spec.ts \
    --project=chromium --workers=1 --retries=0 --trace=on --reporter=line \
    --output=test-results/editor-compile-sync
  HYDRATION_AUTH_CLIENT_BASELINE=0 \
    pnpm exec playwright test e2e/hydration-session-store.opt-in.ts \
    --config=playwright.hydration.config.ts --workers=1 --retries=0 \
    --trace=on --reporter=line --output=test-results/hydration-session-store
  ```

  Keep the quality launcher's production mode, service-worker blocking for its
  route mocks, native WebKit clipboard `write`, unknown-route/runtime assertions,
  source/PDF/SyncTeX checks and owner-incarnation tests. Retain the workflow's
  `playwright-quality-report` artifact, including all three result directories;
  later stages skipped after an earlier failure remain open. These use synthetic
  backend/provider responses and do not establish live latency or PWA lifecycle.
  Run `bash scripts/ci/full-stack-smoke.sh` from the repository root using that
  workflow job's isolated services/setup; do not substitute mocked quality for
  this independent gate.

### B. Establish deployment configuration and independent certification

- [ ] Read [MODAL_RENDERER_CAPABILITY.md](../../MODAL_RENDERER_CAPABILITY.md)
  and the [deployment workflow](../../../.github/workflows/deploy-modal.yml).
  Preserve its order: billing preflight, renderer preflight, migrations, rolling
  deployment. Do not invoke migrations/deployment just to test configuration.
- [ ] Before any authorized rollout, the operator must identify the actual
  immutable bare TeX image, independently verified asset SHA-256 and intended
  supported profile. The required server-owned configuration is
  `MODAL_ENGINE_VM_CERTIFIED=true`, `MODAL_ENGINE_VM_IMAGE_ID=im-...` and
  `MODAL_ENGINE_VM_ASSETS_FINGERPRINT` containing the actual lowercase 64-hex
  asset hash. These are requirements, **not supplied certified values**. Do not
  reuse the application image, infer the hash from configuration alone or set
  the flag merely to turn the workflow green.
- [ ] After authorization to use the configured cloud runtime, from `backend`
  run the existing configuration check:

  ```sh
  modal run --env main modal_app.py::renderer_preflight
  ```

  Retain candidate SHA/run identity and sanitized output with
  `configuration_ready: true`, all required checks true and no failure reasons.
  `certification_verified` must still be `false`: this preflight creates no VM
  and does not verify the image's existence/content or certify templates. It
  does not alter credentials/configuration. The independent billing preflight
  remains required; use its workflow arguments, not an invented bypass.
- [ ] Actual image certification is a **separate authorized cloud/compiler and
  security-test operation**, outside the work performed here. The existing
  operator command, from `backend`, is:

  ```sh
  python scripts/certify_modal_vm_engine.py \
    --image-id "$OPERATOR_VERIFIED_IMAGE_ID" \
    --expected-assets "$OPERATOR_VERIFIED_ASSET_SHA256"
  ```

  It requires an authenticated operator environment and local `pdftotext`.
  Supply both flags; omission selects a historical diagnostic image. Capture
  exit status/stdout/stderr externally (there is no `--output` option), actual
  matching image/assets, every case's zero exit status, PDF/text/glyph checks and
  all required isolation results. Preserve sanitized failure artifacts under
  `backend/temp/vm-certification-failure-*`. Even this script's successful report
  leaves `default_resume_flow_certified: false`; separately verify the actual
  application default Lua path and supported template/language profile, including
  output text, glyphs, links, layout, SyncTeX/geometry, cache identity and normal
  cancellation/terminal behavior. The historical cloud CJK case exited 1 despite
  producing a PDF and remains failed evidence, not a usable certification.
- [ ] Where relevant, regenerate the repository's template/owned-format evidence
  in the exact authorized renderer environment using the commands in
  [HANDOFF.md](HANDOFF.md#benchmarks-and-certification-artifacts). Its
  `verify_trusted_formats.py` proof is pdfLaTeX-specific; it does not certify Lua.
  Keep image/asset/profile/fixture identities and representative visual review
  with each result. Retain the capability gate if any required proof is absent.

### C. Resolve the local slowdown before making speed claims

- [ ] Retain the existing [baseline](render-pipeline-latency-baseline-2026-10-08.json)
  and [candidate](render-pipeline-latency-candidate-2026-10-08.json): fresh p50/p95
  is **1.008/1.188 s versus 1.644/2.095 s**; exact-cache p50/p95 is
  **0.246/0.340 s versus 0.430/0.598 s**. Their `quiet` labels do not independently establish
  controlled, comparable host load. Do not discard the slower samples or call the comparison a
  proven improvement/regression without controlling those conditions.
- [ ] Use matched immutable baseline/candidate source snapshots, the same actual
  image, compiler, managed-English fixture, isolated `*_test` database/Redis/
  private bucket and resource limits. Alternate A/B order on the same controlled
  host and measure load throughout. The existing command from `backend` is:

  ```sh
  python scripts/benchmark_render_pipeline.py --samples 30 \
    --profile managed_english --compiler lualatex \
    --source-commit "$SOURCE_COMMIT" --image-id "$IMAGE_ID" \
    --host-load "$HOST_LOAD" --output "$EVIDENCE_JSON"
  ```

  `HOST_LOAD` must be one of the script's `quiet`, `contended`, `unspecified`
  labels, supported by recorded observations. The script alternates **fresh and
  cache** within a run, not baseline and candidate implementations; arrange the
  latter as a separate controlled paired protocol. Retain at least 30 valid warm
  samples per condition, plus all failures/timeouts and cold-start observations.
  Record sample counts and p50/p95, per-phase timings, engine pass count and cache
  no-compiler proof. This eager-worker harness excludes HTTP quota admission,
  Celery transport, AI, browser paint and cold image startup; it cannot close the
  production SLO. Preserve the exclusions in the new evidence.
- [ ] Treat the 40-ms injected storage/upload experiments as mechanism tests
  only. If repeated, use their existing scripts/arguments documented in
  [latency-priority-2026-10-08.md](latency-priority-2026-10-08.md#reproduction-and-remaining-work)
  and label injected delay explicitly. Do not subtract those savings from
  overlapping whole-worker or browser percentiles.

### D. Measure the reviewed deployment's real user-visible performance

- [ ] Only after a separately authorized reviewed rollout, record exact frontend
  and backend commits, actual image/assets/compiler/profile, configured capacity,
  API/worker/data regions, network/device/browser and sample time. The public
  generic health version or deployment history alone is not runtime attestation.
- [ ] Collect guest and saved-editor scenarios separately: cold first job, warm
  fresh edit, exact-cache repeat, rapid edit/manual-click overlap, identical-
  source burst and distinct-source burst. Include desktop/mobile first paint,
  interrupted/repeated previews and correct final-source output. Keep ordinary
  quota/cooldown behavior. Predeclare the bounded run/load and sample plan;
  retain failures and timeout rates, at least 30 valid samples per warm condition,
  p50/p95 and cold samples separately. Do not silently redefine the acceptance
  network, device, fixture or supported profile after seeing results.
- [ ] Correlate user action, admission, dispatch, worker initialization, queue
  wait, source preparation, TeX passes/drain, artifact upload/manifest/publication,
  finalization, download and first paint. Use `PDF_USER_ACTION_PAINT` separately
  from `PDF_RENDER_PAINT`; preserve source/PDF identity and correctness. Follow
  [latency-instrumentation-2026-10-10.md](latency-instrumentation-2026-10-10.md):
  queue wait overlaps startup and initialization is not image-pull timing. Do not
  add overlapping spans or compare timestamps across unsynchronized clocks. Keep
  source text, credentials and personal data out of telemetry/public evidence.
- [ ] The existing one-sample public production probe, from `frontend`, is:

  ```sh
  LATEXY_PRODUCTION_AUDIT=1 LATEXY_AUDIT_COMPILE=1 \
    LATEXY_AUDIT_DIR="$EVIDENCE_DIR" node scripts/audit-production-latency.mjs
  ```

  It targets hard-coded production origins and consumes normal guest quota.
  Run only within explicit live-test authorization. Its visible nonzero canvas
  plus two animation frames is a paint proxy; one invocation is not a p95/cold/
  saved/burst acceptance harness. The saved-account audit scripts listed in
  [the production audit](production-latency-audit-2026-10-08.md#reproduction-and-evidence)
  additionally create/use ordinary account state and need their own approved
  scope. Do not run them as a supposedly read-only check.
- [ ] `frontend/scripts/benchmark-preview-browser.mjs` is **local HTTP only**,
  reports one/three functional samples and excludes production/Modal latency.
  It still selects the older “Built internal design system…” demo bullet; review
  that selector against the new first-use seed before reusing the harness.
  There is no verified one-command complete cold/warm/overlap production matrix
  in this handoff. Prepare/review that bounded procedure before executing it;
  do not repoint the local-only helper to production or fabricate percentiles.
- [ ] Close the architecture targets only with qualifying end-to-end evidence:
  fresh simple resume after committed edit **p50 <750 ms and p95 <1 second** on
  the defined warm/certified profile, cached first paint **p95 <500 ms** including
  authorization/download/render. Report cold/overlap/burst separately; the
  intermediate two-second milestone is not final acceptance. Compare to the
  retained 18.823-second guest and 57.736-second overlapping saved observations
  without pretending those diagnostic samples were controlled distributions.

### E. Verify configured-provider conversion terminal/refund acceptance

- [ ] Keep [the historical production failure and source repairs](production-latency-audit-2026-10-08.md)
  linked to [#1863](https://github.com/sanskarpan/Latexy/issues/1863): configured
  model HTTP 404, escaped eager retry and no terminal result after 183.480 s.
  `backend/test/test_converter_provider_runtime.py` covers configured endpoint/
  model, BYOK isolation, 404/timeout/invalid output, rejected ownership and
  lost/throwing terminal events with controlled dependencies. These assertions
  must remain in exact-head CI; they mock provider/refund operations and are
  not proof of live output or accounting.
- [ ] Obtain explicit authorization for the intended account, configured
  provider/model, synthetic content, bounded calls/cost and failure/recovery
  scenario. Use an already authorized ordinary QA session; do not create/copy
  credentials, change roles, edit provider configuration or expose private
  session files as a side effect of this checklist. Attest deployed source and
  configured model/origin without exposing keys.
- [ ] For the authorized **single successful-path attempt**, the existing
  command from `frontend` is:

  ```sh
  LATEXY_PRODUCTION_AUDIT=1 LATEXY_AUDIT_CONVERSION=1 \
    LATEXY_QA_CREDENTIAL_FILE="$PRIVATE_QA_CREDENTIAL_FILE" \
    LATEXY_AUDIT_DIR="$PRIVATE_EVIDENCE_DIR" \
    node scripts/audit-production-conversion.mjs
  ```

  It requires Chrome and an existing valid session in
  `${LATEXY_QA_CREDENTIAL_FILE}.state.json`; its production origins are hard-coded.
  It uploads one synthetic TXT using normal quota, then writes
  `conversion-latency.json`. Inspect the JSON, not just the exit code: caught
  errors are recorded without setting a failing shell status. Require completed
  terminal status, successful result response, `has_latex: true`, no error and
  independently reviewed usable output. `has_latex` only detects
  `\begin{document}`; it is not a quality/export proof. Retain sanitized request/
  stage timings and job correlation, not tokens or credentials.
- [ ] To inspect the **same** authorized synthetic job without another upload,
  add `LATEXY_AUDIT_EXISTING_JOB="$EXISTING_SYNTHETIC_JOB_ID"` to that command.
  It polls five times; fresh submission polls up to 60 times with two-second
  waits plus request timeouts. This is not a guaranteed two-minute deadline.
  A bounded poll ending without terminal state remains failure/incomplete
  acceptance, not permission to submit again or extend retries indefinitely.
- [ ] Separately approve and review a bounded provider-failure/recovery procedure.
  The existing live script has **no forced-error mode or refund assertion** and
  cannot close this part alone. Correlate configured model/origin, one provider
  attempt, canonical terminal state and timely client-visible recovery with
  durable quota evidence. Demonstrate exactly one `ai_assists` quota refund for
  an accepted eligible failure, none for success/rejected ownership, no duplicate
  charge/refund on recovery, and no stranded refundable receipt after lost or
  throwing terminal-event delivery. This is usage-quota accounting, not a Dodo
  payment refund. Use `converter_worker.py`, `quota_refund.py` and
  `cleanup_worker.py` as the contract; do not invent an unaudited live fault
  injection command or break shared production configuration to exercise it.
  Record the agreed terminal-time bound before running and preserve unsuccessful
  observations. Paid-provider quality remains a separately scoped acceptance
  question even when terminal/accounting behavior passes.

### F. Record the closure decision

- [ ] For each item above, attach exact-head/deployment identity, command/procedure,
  environment, date, result, evidence location and unresolved limitation. Keep
  sensitive raw logs/session files outside the repository; publish only reviewed
  synthetic/redacted evidence. Do not add overlapping test counts together.
- [ ] Distinguish **merge-gate completion**, **deployment readiness**, **renderer
  certification**, **production latency**, and **provider acceptance** in the PR.
  Mark a gate complete only from its own evidence. If the release owner elects
  to merge with a separately tracked acceptance item open, state that explicit
  decision and keep its rollout/capability restriction and issue open; never
  relabel a green CI run as production acceptance.
- [ ] Reconcile [the existing issue crosswalk](issue-tracking-links.md), epic
  [#1814](https://github.com/sanskarpan/Latexy/issues/1814), first-task acceptance
  [#1862](https://github.com/sanskarpan/Latexy/issues/1862) and conversion acceptance
  [#1863](https://github.com/sanskarpan/Latexy/issues/1863) against the new evidence
  before any closure. This checklist itself closes none of them.
