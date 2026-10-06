# Active local QA tracker — 2026-10-04

This is the compact current-work index. Historical repros, failed attempts,
runtime job IDs, and evidence are retained in
[the remediation ledger](local-remediation-2026-08-31.md). Passing a checkpoint
does not certify subsequent edits or the deployed site.

## Scope and operating constraints

- Root reviews and coordinates three GPT-5.6 Luna/high agents; implementations
  receive independent source review and proportionate regression checks.
- Publication was deferred during the October 4 pass. On October 6 the user
  explicitly requested that all accumulated task work be committed, published
  and merged into `main` before further QA. The current integration is tracked
  in [the publication checkpoint](PUBLICATION-2026-10-06.md) and GitHub #1750.
- Preserve the dirty shared tree, credentials, and unrelated local services.
- One pytest lease at a time. Do not overlap fixture-resetting pytest with
  complete browser tests that write through real Next auth handlers.
- One isolated Node 22 production browser builder at a time. Avoid real TeX
  timing probes during heavy browser builds. Do not raise plan limits to hide
  cache/startup failures.
- Local app: frontend 5180, API 8030, PostgreSQL 5434, Redis 6380, MinIO 9000.
  App/test databases and Redis namespaces remain separate. Provider calls and
  billing are disabled for synthetic worker smoke tests.

## Latest status (older checkpoints below retain their snapshot boundaries)

The checkpoints below describe October 4 snapshots, not fresh October 6 or
production acceptance. Temporary logs from that session are no longer available
in the current environment. The October 6 publication checkpoint records fresh
checks, exclusions, failures and their disposition separately.

- Backend: 4,212 passed / 5 skipped; actual owned PDF, cancellation and exact
  JD transport-expiry recovery passed with the restarted worker.
- Frontend before the new workspace/saved-builder/compatibility-hook batch:
  153 files / 972 unit tests, full lint/types, and production build pass.
- Reviewed 5461 public quality: Chromium/Firefox/mobile Chromium **13 passed /
  2 conditional skips**; mac15-target WebKit **9 passed / 1 conditional skip**.
  Native mac26 WebKit still crashes before page creation. These are separate
  execution results, not a natively passing five-engine run.
- The 95-case focused ownership gate is not wholly green: the repeat has
  93 passes, the stale tracker locator module, and an actual editor React #418.
  Preserve runtime error assertions and investigate the shared hydration defect.
- The next reviewed batch contains workspace result-loading/cache guards,
  saved-builder owner/document isolation, and authoritative compatibility-hook
  completion. Final frozen unit/static/build/browser proof is still required.
- New read-only surveys cover tracker auxiliary panels and remaining saved
  builder/recovery edges. Verified defects are distinguished from source-only
  candidates; publication and production certification remain deferred.

## Accepted checkpoints

- [x] Strict ownership metadata parser and route/WS/PDF/batch/list checks:
  127 affected tests passed; malformed/misbound ownership fails closed.
- [x] Completed owned PDF transport-expiry recovery and immediate cancellation:
  real API/worker/PostgreSQL/MinIO smoke passed after strict parsing. No broad
  Redis flush, artifact deletion, or user-data deletion.
- [x] Standalone Hindi template: actual worker PDF compiled within the unchanged
  budget, rendered legibly, embedded fonts, zero missing-glyph/shape warnings.
  Local gallery serves the exact corrected source. No PDF/UA claim.
- [x] Backend checkpoint before output-integrity additions: 4152 passed,
  5 skipped, one Starlette deprecation warning.
- [x] Frontend checkpoint before output-integrity additions: 149 files /
  949 tests; TypeScript/scoped lint passed.
- [x] Latest focused production-browser checkpoint before editor metadata and
  output-integrity additions: 22/22 passed with zero retries, including actual
  IndexedDB transactions, owner switches, same-owner PDF refresh, cover-letter
  signature/query races, and deep ATS recovery.

## Current implementation and verification

- [x] Durable output integrity: known typed completed jobs with missing/invalid
  generated output must not yield successful empty UI. Persisted incomplete
  markers and bounded omission evidence must survive repeat serialization.
  Backend implementation and 14 focused tests pass, including real ASGI HTTP
  and unchanged DB terminal decisions. Frontend handles an explicit client
  delivery error without polling forever, fabricating completion, refunding,
  or resubmitting. Root's 47 affected frontend tests and TypeScript pass;
  complete unit suites pass at the checkpoint below. The production browser
  error/no-poll test found a real missing panel connection: both `/try` and
  the saved editor passed only submit errors, ignoring stream delivery errors.
  Root wired `deepStream.error` into both panels; fresh production recovery
  proof passes in the 31-case checkpoint below.
- [ ] Editor metadata/download ownership: parent-title success/failure,
  academic reports, connection/plan display, and delayed share/download fallback
  use live mounted owner/resume/generation guards. Two same-document account
  switch browser regressions passed in the complete sealed production run; source review,
  TypeScript, scoped lint, and 11 existing focused tests pass. A dedicated
  deferred native-share fallback browser proof is not yet present.
- [x] Output-integrity backend checkpoint: **4166 passed,
  5 skipped, 1 Starlette deprecation warning**, 123.67s;
  `/tmp/latexy-backend-full-output-integrity-2026-10-04.log`.
- [x] Output-integrity frontend unit checkpoint:
  **150 files / 957 tests passed**;
  `/tmp/latexy-frontend-full-output-integrity-2026-10-04.log`.
- [x] Typed-admission/event/cache backend checkpoint: **4181 passed,
  5 skipped, 1 warning**, 188.68s;
  `/tmp/latexy-backend-full-typed-event-cache-2026-10-04.log`.
  This predates the subsequent terminal-epoch/canonical-result fixes below.
- [x] Restarted current-code local worker smoke: completed fixture
  `b88c71c4-597a-45c6-9083-44e360bb6f19` matches the durable 14,105-byte PDF,
  transport-expiry recovery/anonymous denial pass, and cancelled fixture
  `f7897fc9-6977-4897-a1f6-fa8b2cb43dd7` has both records cancelled. Log:
  `/tmp/latexy-owned-recovery-output-integrity-2026-10-04.log`.
- [ ] Complete zero-retry production browser checkpoint: **575 scenarios /
  58 files**, **568 passed, 2 failed, 5 skipped**, 16.5m. Failures are the
  recurring cover-letter React hydration `#418` and the newly verified missing
  deep-analysis error-panel connection. Neither is waived. Four backend-opt-in
  cases and one mobile-only public-quality case skip in this desktop mocked
  run; these are not live/mobile acceptance.
  `/tmp/latexy-browser-complete-output-integrity-2026-10-04.log`.
  This sealed bundle predates the newly verified provider-pull fix and upcoming
  typed-commit/cache changes. Source implementation may proceed in the shared
  checkout without altering its isolated application copy; another final-source
  gate is required after those changes freeze.
- [ ] Mixed CJK/RTL/Indic cold-cache support: an actual confined 45-second
  Docker probe originally timed out initializing LuaTeX-ja before the body.
  The reviewed cache-warmed image now produces the diagnostic PDF in **9.96s**
  without relaxing runtime limits, but unwrapped Latin/email/bullets inside
  explicit non-Latin spans produce missing-glyph warnings. This is not visual
  acceptance. The explicit-English-span control produces a one-page,
  **31,475-byte PDF in 15.45s**, zero missing-glyph/shape warnings, and root's
  rendered inspection shows legible Latin/CJK/RTL/Hindi, bullets, and Indic
  bold/slanted shapes. Artifacts: `/tmp/latexy-mixed-wrapped-acceptance.2Nm0B2/`.
  This is a confined engine control, not a restarted actual-worker or Modal claim.
  Bare Latin inside RTL spans is outside the documented direction-switching
  contract; the missing generated-output instruction for mixed Hindi remains
  a separate translation-product gap.
- [ ] Production Modal font/cache parity: packages are present, but the verified
  local build-time cache warm contract is now shared in Modal source, with static
  parity checks; the actual Modal image has not been built/deployed. No production
  runtime claim or deployment is made.

## New surveys awaiting behavioral verification

- [ ] Editor mutation ownership beyond the accepted PDF/metadata boundary:
  source review identifies unguarded deferred compile/AI/deep-analysis job IDs,
  auto-fit content application, save snapshots, provider pull/toggle/push,
  parent diffs, variant navigation, suggestion decisions, and reconnect queue
  flushing. Old job IDs/baselines are not all invalidated on account/resume
  changes. Highest-impact content-mutation candidates are assigned fully mocked
  red browser repros reusing the current isolated production server, without
  starting another builder or editing the application snapshot.
  **Verified GitHub pull repro:** the deferred account-A response overwrites
  Monaco after same-document A→B switch. One browser test genuinely fails, with
  artifact directory
  `/tmp/latexy-editor-mutation-ownership-2026-10-04/`.
  Both GitHub and Dropbox deferred pulls genuinely failed against the sealed
  pre-fix bundle. Guarded mutation implementation passes static/unit checks; it is not yet
  accepted by a fresh browser run.
- [x] Typed finalization admission: the arbiter previously did not require
  discriminator-specific generated output before committing success. Normal
  deep ATS/cover-letter workers supply validated output, so this is a producer
  integrity boundary, not evidence of a public exploit. Real DB regressions
  for missing/malformed typed output and unchanged output rows now pass in the
  focused backend run and the complete 4,185-test checkpoint below.
- [x] Cover-letter final-event ordering: `llm.complete` previously preceded
  durable arbiter acceptance. A valid generated document may be exposed as
  complete before a cancellation/lease/fencing rejection. Worker regressions
  now cover rejection after valid generation and preserve the documented legacy
  non-admitted worker path. Accepted ordering is DB commit → result publication
  → final content → terminal event. Root review caught and corrected an overly
  broad guard that would suppress valid running LLM stage completion events;
  a real-Redis regression preserves them. Tentative token streaming is distinct from accepted
  final content; no claim is made that all streaming should be removed.
- [x] Terminal-event epoch and canonical replay: genuine real DB/Redis red
  regressions reproduced a same-token stale epoch consuming the completed-event
  capability and a losing result replacing Redis after `ALREADY_COMPLETED`.
  The fixes preserve the exact ownerless recovery exception and matching
  canonical replay. Nine new focused tests and affected suites pass; root
  source review and the complete 4,185-test checkpoint pass.
- [x] Offline reconnect ownership: real fake-IndexedDB regressions initially
  failed **4/5** against the unowned global compile queue. Owner-scoped query,
  enqueue, count, and atomic acknowledgement now pass. Legacy unowned rows are
  preserved/quarantined, never assigned to the next account or sent automatically.
  Reconnect stops later submissions/UI mutations on identity change; accepted
  requests acknowledge only their captured owner. Draft acknowledgement uses
  a transaction/revision comparison so newer offline edits cannot be deleted by
  an old save response. **18 focused storage tests passed**, TypeScript and
  scoped lint pass. Actual production-browser reconnect and flap/retry/CAS
  controls pass in the 31-case checkpoint below.
- [x] Editor job/save ownership: reviewed provider, compile, AI, auto-compile,
  auto-fit, deep-analysis, explicit-save, and autosave guards; account-transition
  renders hide old stream IDs before effects reset state. Root review caught
  the completed-PDF re-fetch risk introduced by resetting the dedupe ref and
  required an immediate render guard plus regression. Focused production proof
  passes against reviewed production source on port 5457 (31-case checkpoint).
- [ ] Additional survey candidates, not verified defects yet: workspace list/
  activity/translation response ownership; tracker overlapping load and stale
  optimistic rollback; builder autosave server ordering/reattach; Quick Tailor,
  Apply, and template modal reuse. Deferred browser repros are assigned before
  runtime changes. Existing server-authoritative persistence/load recovery
  protections must not be removed or duplicated blindly.

## Still separate / not waived

- Whole-product keyboard/accessibility and manual screen-reader matrix.
- Recurring cover-letter hydration `#418`: the complete run reproduced it;
  a fresh non-minified diagnostic is assigned. Passing retries or narrowed
  runs do not explain it or certify a fix.
- Operator-dependent Upstash capacity, trusted npm publishing, production QA
  account/email delivery, secret rotation/validation, payment/KYC/commercial
  policy, and explicitly unsupported PDF/UA requirements.
- Eventual publication and exact deployed-SHA testing, only after the local pass
  and the user's deferred publication decision.

## Reviewed checkpoint — October 4, 10:15 IST

- [x] Complete backend canonical-result/terminal-epoch gate: **4,185 passed,
  5 skipped, 1 warning**, 292.46s. Log:
  `/tmp/latexy-backend-full-canonical-epoch-2026-10-04.log`.
- [x] Complete frontend unit gate after offline queue/revision acknowledgement:
  **152 files, 969 tests passed**. Log:
  `/tmp/latexy-frontend-full-offline-owned-editor-accepted-2026-10-04.log`.
- [x] Sealed production-browser recovery/reconnect acceptance: **5/5 passed**
  (three output recovery cases, two owner-scoped queue/migration cases).
  Log: `/tmp/latexy-recovery-reconnect-prod-2026-10-04.log`.
- [x] Restarted actual local worker with canonical-result/epoch source and the
  cache-warmed TeX image; authenticated durable-PDF recovery, transport expiry,
  anonymous denial, and cancellation smoke passed. Log:
  `/tmp/latexy-owned-recovery-canonical-cache-2026-10-04.log`.
- [ ] Editor deep-analysis start: actual production interaction exposed a React
  click event passed as the optional industry argument, causing circular JSON.
  Root added an explicit argument-free click wrapper. Fresh production proof
  is required; port 5455 is sealed before this change.
- [ ] Tracker delayed-delete rollback now restores only the removed card rather
  than overwriting newer board mutations. Three development-browser cases pass;
  account-switch/Undo guards are under independent review. Development acceptance
  is not production acceptance.
- [ ] Rapid reconnect duplicate submission: source candidate assigned a real
  IndexedDB/deferred HTTP reproduction. Pending-write/sign-out ordering is
  unconfirmed; no purge-epoch change is accepted without native ordering proof.
- [ ] Hydration remains open: **48/50 passed, 2 failed**, zero retries, against
  the same production bundle. Error snapshots still show the deterministic
  loading spinner, not Monaco/PDF settings. DOM streaming history is retained in
  `/tmp/latexy-hydration-dom-50-2026-10-04/`. A blocking-metadata user-agent
  control is diagnostic only; no application workaround or error suppression.
- [ ] Hindi/Marathi translation prompt now requests explicit English switches
  for preserved Latin runs. **28 focused backend tests passed, 1 skipped**;
  complete-suite rerun is in progress. Source text is not automatically rewritten.

Publication remains deferred. These checkpoints apply to their tested local
snapshots, not later changes, all product surfaces, or the deployed site.

### Next coordinated local acceptance

- Backend translation-guidance gate completed: **4,187 passed, 5 skipped**;
  4,192 collected, zero test failures, one existing Starlette warning. Logs:
  `/tmp/latexy-backend-full-devanagari-guidance-2026-10-04.log` and
  `/tmp/latexy-backend-collection-devanagari-guidance-2026-10-04.log`.
- Frontend complete unit rerun: **153 files / 972 tests passed**, including
  transient reconnect reservations and updated narrow tracker rollback contract.
  Log: `/tmp/latexy-frontend-full-tracker-reconnect-2026-10-04.log`.
- Reconnect compile and draft duplicate submissions are genuinely reproduced
  against sealed pre-fix production source. Synchronous per-item transient
  reservations now span overlapping effects and release after acknowledgement
  or failure. They do not provide durable/cross-tab/exactly-once delivery.
  A failed-compile retry control and native IndexedDB newer-revision CAS browser
  proof pass against the earlier bundle. Fresh dedupe acceptance is pending.
- Tracker same-card/other-card failed PATCH rollback and deleted-card resurrection
  are genuine red browser regressions. Narrow rollback now checks owner, per-card
  mutation token, presence, and attempted status inside the state updater.
  Deferred delete/Undo ownership guards are included. Fresh production proof is
  pending on the one coordinated port-5457 build.
- Blocking-metadata user-agent control also reproduces hydration **2/50 failures**;
  metadata streaming alone does not explain the defect. Instrumented React
  delivery probes pass 40/40 and 100/100, but alter timing and are **diagnostic,
  not application acceptance or evidence of a fix**. No app workaround accepted.
- Backend source-contract candidates assigned behavioral verification: scoring/
  JD/deep ATS completions advertising nonexistent PDFs; async scoring/JD durable
  terminal recovery; async hook result-shape mismatch (no active consumer found).
  Do not relabel source traces as exercised endpoint/worker counterexamples.
- Workspace deferred list/stats and translation navigation ownership are assigned
  mocked browser repros. API auth-ready sequencing remains unproven; no broad
  API-layer mutation is accepted merely from the source observation.

### Fresh production ownership acceptance — port 5457

- [x] **31/31 passed**, zero retries, against the reviewed production bundle:
  editor provider/job/save/metadata ownership, completed-PDF identity isolation,
  deep-analysis click/job start, unavailable/failed/successful output recovery,
  offline owner/migration/flap/retry/newer-revision preservation, and tracker
  deferred delete/Undo/status rollback/resurrection controls. Log:
  `/tmp/latexy-reviewed-ownership-prod-2026-10-04.log`; artifacts/output:
  `/tmp/latexy-reviewed-ownership-prod-2026-10-04/`.
- [x] Whole frontend lint and TypeScript gates passed before this build, logs:
  `/tmp/latexy-frontend-lint-tracker-reconnect-2026-10-04.log` and
  `/tmp/latexy-frontend-types-tracker-reconnect-2026-10-04.log`.
- [ ] Workspace list/stats and late translation navigation now have genuine
  A→B browser counterexamples, not source-only candidates. A's delayed list
  replaced B's resumes/score, and A's translation navigated B to A's variant.
  Root approved scoped ownership/request-generation guards and positive controls.
  Logs/artifacts: `/tmp/latexy-workspace-ownership-list-red-2026-10-04-r4/`
  and `/tmp/latexy-workspace-ownership-translation-red-2026-10-04/`.
- [ ] Non-PDF ATS scoring/JD/deep completion payloads now explicitly contain
  `pdf_job_id: None`. Three genuine worker-call red assertions preceded the fix;
  **138 affected tests pass**. These tests mock the publisher, so this is worker
  payload proof, not real Redis terminal publication/deployed-runtime proof.
  Log: `/tmp/latexy-ats-nonpdf-contract-2026-10-04.log`. Next full backend gate
  and durable async ATS expiry repros remain pending.
- [ ] Hydration diagnostic direct chunk delivery reproduced **1/50 failures**;
  host-fiber capture identifies the root `main` and a `$` comment candidate while
  the loading spinner remains. Richer diagnostic 50/50 passes do not close the
  intermittent defect. Artifacts: `/tmp/latexy-hydration-fiber-local-50-2026-10-04/`.

- [x] Additional production offline/PWA gate: **16/16 passed**, including mobile
  installation/editor controls, real service-worker cache/fallback privacy,
  cold offline PDF reader, IndexedDB validation/eviction races, logout and account
  switch. Log: `/tmp/latexy-reviewed-offline-pwa-prod-2026-10-04.log`.
  Editor offline PDF ownership controls separately pass **3/3** at
  `/tmp/latexy-reviewed-pwa-prod-2026-10-04.log`.
- [x] ATS scoring durable-recovery concern withdrawn as a false positive:
  real Postgres/Redis proof confirms the existing generic publisher arbiter
  bridge completes the durable row and authorized recovery survives Redis loss.
  Ambiguous scoring dispatch preserves its reservation. No duplicate terminal
  persistence added. Log: `/tmp/latexy-ats-recovery-loss-2026-10-04.log`.
- [ ] JD-analysis durable recovery was genuinely missing in the old path:
  real Redis-loss replay returns state/result 404 with no finalization row.
  The new route/lifecycle/bounded typed recovery and ambiguous dispatch pass
  focused tests. Root required and reviewed additional failure, retry, and
  publication-rejection handling; **146 affected tests pass**. Complete backend
  acceptance is pending. Log: `/tmp/latexy-ats-jd-terminal-2026-10-04.log`.

No claim is made that all defects or all product surfaces are resolved.

## Frozen workspace/JD checkpoint and next open edge

- [x] Complete backend snapshot before the JD long-field correction:
  **4,197 passed, 5 skipped, 1 warning**, 434.56s. Log:
  `/tmp/latexy-backend-full-ats-jd-durable-2026-10-04.log`.
- [x] Complete frontend units after workspace ownership guards:
  **153 files / 972 tests passed**. Log:
  `/tmp/latexy-frontend-full-workspace-owned-accepted-2026-10-04.log`.
  The first attempt failed one obsolete source assertion referring to raw
  `resumes`; it now asserts owner-gated outage behavior without waiving retry.
- [x] Fresh production workspace behavior: **5/5 passed**, zero retries, on
  port 5459. Covers deferred list/stats, account-switch translation, same-owner
  success, modal close/reopen stale success and stale failure. Log:
  `/tmp/latexy-workspace-ownership-prod-2026-10-04.log`.
- [ ] Complete zero-retry browser gate: **607 scenarios / 64 files** finished
  **601 passed, 1 failed, 5 skipped**, 17.0m. The failure is React `#418` on
  Optimize; no assertion was suppressed. This checkpoint ran
  against the sealed port-5459 application. Log:
  `/tmp/latexy-browser-complete-workspace-jd-2026-10-04.log`.
  No concurrent pytest or shared-test-database mutations are allowed.
- [ ] Root pure-helper counterexample: a valid JD requirement of 5,010
  characters was reduced to 2,048 while `recovery_complete=True` and typed
  completeness reported no missing fields. A narrow flat-list preservation/
  explicit oversized-output fix is assigned; the green backend snapshot above
  does not certify this newly verified edge. No generic payload limits are raised.
- [ ] Real running worker needs a coordinated restart after JD lifecycle changes
  and additional actual-Celery JD smoke. Existing PDF/cancellation smoke applies
  to its earlier canonical-result/epoch source, not the latest JD worker code.

### Review while the complete browser gate holds the database lease

- [ ] The uninstrumented complete browser gate also reproduced React `#418`
  on `/workspace/[resumeId]/optimize` (`ats-quick-score.spec.ts:607`). This is
  evidence of a shared-root hydration problem, not just the cover-letter route.
  The assertion remains unchanged; the failed artifact is retained under the
  complete-gate output directory above.
- [ ] A 100-repeat, fully mocked cover-letter diagnostic captured one failure
  with both initial seed loading data and router cache loading data present.
  The missing-loading-data hypothesis is therefore falsified for that failure.
  The `$` comment candidate under `main` remains unexplained; streaming/cursor
  timing is a hypothesis, not a proven cause. Diagnostic artifacts:
  `/tmp/latexy-hydration-router-2026-10-04.yA7SR0/`.
- [ ] JD exact-preserving list/closed-metrics correction is implemented and
  root source-reviewed. Pure helper and Ruff checks pass; runtime regressions
  and the next complete backend gate remain pending the browser database lease.
  Valid long requirements must remain exact; malformed or oversized fields must
  retain an explicit incomplete marker across repeated serialization.
- [x] Dedicated delayed native-share failure/fallback ownership proof:
  **3/3 passed**, zero retries, against reviewed port 5459. Real browser download
  and anchor-click assertions preserve same-owner failure fallback and suppress
  both user-cancellation and post-account-switch fallback. Log:
  `/tmp/latexy-native-share-owned-2026-10-04.log`. Scoped ESLint/TypeScript pass.
  These three new scenarios are separate from the already-collected 607 sweep.
- [ ] Actual-worker JD smoke is now an explicit `--include-jd` option in
  `scripts/ci/local-owned-job-smoke.py`. It verifies the exact long requirement,
  durable ownership/type/output, transport-expiry recovery, anonymous denial,
  absence of a PDF artifact, and no transport recreation. Ruff/compile checks
  pass; actual execution awaits the coordinated worker restart.

### Post-sweep corrections and runtime acceptance

- [x] JD exact-preserving serializer and real recovery/readmission controls:
  **56 focused + 102 related tests passed**. Logs:
  `/tmp/latexy-jd-serializer-retry-2026-10-04.log` and
  `/tmp/latexy-jd-finalization-related-2026-10-04.log`.
- [x] Complete backend rerun after these JD additions:
  **4,212 passed, 5 skipped, 1 warning**, 160.49s. Log:
  `/tmp/latexy-backend-full-jd-exact-recovery-2026-10-04.log`.
- [ ] Tracker board-load ownership is now a verified browser defect: releasing
  A's delayed board response after B loads replaces B's cards with A's cards.
  Root approved a scoped owner/version fix. The proposed drag rollback case is
  still unproven and was removed from the accepted repro, not silently fixed.
  RED evidence: `/tmp/latexy-tracker-load-ownership-2026-10-04-final/`.
- [ ] Deferred editor share-link creation is now a verified browser defect:
  A's completed response changes B's editor to **Manage share link**. Root added
  modal-lifetime/owner guards and keyed owner/document boundaries at both callers.
  Same-owner success and the stale-failure control passed the pre-fix build;
  fresh corrected production proof is pending. RED/control logs:
  `/tmp/latexy-share-link-owner-controls-2026-10-04.log`.
- [ ] Exact local app launcher 70878 was verified and gracefully stopped;
  backend, worker/beat and frontend ports were checked closed. Infrastructure
  and isolated browser servers were retained. New disabled-provider app startup
  log: `/tmp/latexy-local-app-jd-exact-recovery-2026-10-04.log`.
- [x] Restarted actual-worker smoke including exact JD recovery passed:
  PDF job `b20e3ea0-1fb4-4f3f-8e85-3d0a6252b7ad` is **14,105 bytes** and matches
  durable database/storage metadata; cancellation job
  `3b91ac0b-c305-4321-83e3-7eb701789518` remains cancelled without an artifact.
  JD job `181a9518-e287-4e18-9c00-39989efb2dd6` preserves its long requirement
  exactly in the durable row and after transport-key deletion. Anonymous denial,
  completed-state recovery, non-PDF download rejection and no Redis transport
  recreation all pass. Log:
  `/tmp/latexy-owned-jd-exact-recovery-smoke-2026-10-04.log`.
- [ ] Modal retry/backoff/startup/timeout differences remain source-only
  candidates: eager Celery application retries immediately, unlike broker
  countdown, and function startup can fail before task admission/publication.
  No Modal invocation, deployed counterexample or production parity acceptance
  occurred. These observations do not negate the actual local Celery proof.
- [ ] Root review caught a one-render-only weakness in the initial tracker
  board guard. Accepted-data owner/generation stamps are required to keep the
  previous board hidden until a correct-owner response is accepted. A passing
  focused test alone does not waive this review finding; correction precedes
  the next frozen production build.
- [x] The four backend-opt-in cases skipped in the mocked desktop sweep pass
  against the restarted local API: health, real frontend/core-route smoke, and
  two unauthenticated search contracts. **4/4 passed**, zero retries. Log:
  `/tmp/latexy-live-backend-optin-2026-10-04.log`.
- [ ] Five-project public quality matrix: **13 passed, 10 failed, 2 skipped**,
  2.0m, against sealed 5459. Chromium/Firefox/mobile Chromium execute; every
  WebKit failure is a bundled-engine segmentation fault before page creation,
  independently reproduced with `about:blank`. This is an environment failure,
  not product acceptance or an app runtime defect. A fresh isolated WebKit
  download is being checked without replacing the existing browser cache.
  Logs: `/tmp/latexy-five-engine-quality-2026-10-04.log` and
  `/tmp/latexy-webkit-blank-control-2026-10-04.log`.
- [ ] New-builder create ownership is verified RED: releasing A's deferred
  create response after B mounts navigates B to A's created draft. Keyed
  owner-scoped private form state and lifetime guards are implemented, with
  same-owner creation and transient-refresh draft-preservation controls.
  Root review required StrictMode-safe mounting and preservation of retained
  session drafts during temporary verification failures. Fresh proof is pending.
- [ ] Hydration source interpretation correction: the spinner captured below
  the outer `$` marker is the page's initial client-loading view, **not** the
  root `loading.tsx` fallback. The unconsumed Suspense marker is verified; exact
  trigger is unresolved. Root diff confirms the sealed 5455 root layout matches
  current layout source, including async headers and providers. Instrumented
  200/200 passing runs neither close the defect nor establish a timing cause.

### Integrated owner-surface freeze — port 5461

- [x] Frozen frontend units **153 files / 972 tests passed**; complete ESLint
  and nonincremental TypeScript checks also pass. Logs:
  `/tmp/latexy-frontend-full-owned-surface-freeze-2026-10-04.log`,
  `/tmp/latexy-frontend-lint-owned-surface-freeze-2026-10-04.log`, and
  `/tmp/latexy-frontend-types-owned-surface-freeze-2026-10-04.log`.
- [x] One integrated production build includes reviewed share-link, tracker
  loading, and new-builder identity boundaries. Log:
  `/tmp/latexy-production-owned-surface-server-2026-10-04.log`.
  **620 scenarios / 68 files** were collected before further survey tests;
  collection is not execution. Build completed and the server is ready; focused
  zero-retry acceptance is running, not yet accepted as a whole.
- [x] Tracker review corrections are implemented: stable accepted-data identity
  stamps, owner-keyed reset, owner-visible stale count, and monotonic status
  mutation tokens across account cycles. Four production-source controls are
  ready; the pre-fix bundle has three genuine REDs and a same-owner positive.
- [ ] Fresh native-platform WebKit still crashes on `about:blank`; the macOS
  crash report identifies WKWebView `_cornerConfiguration`/AppKit frames, not
  application JS. An isolated official mac15-target WebKit build on this host
  successfully opens `about:blank`. This compatibility control is not native
  mac26 acceptance; app quality checks under that target remain pending. Cache
  `/tmp/latexy-webkit-mac15.IIpiTR`; probe log:
  `/tmp/latexy-webkit-mac15-blank-control-2026-10-04.log`.
- [x] Unused diagnostic server 5455 was exact-target validated and stopped;
  temporary server copy was cleaned by its normal shutdown. Original source,
  the live app, old 5459 test server and all `/tmp` failure evidence remain.

### Integrated review follow-ups

- [ ] Port-5461 focused ownership/share/builder/tracker regression run is in
  progress. The new-builder owner-switch case initially fails before releasing
  the deferred create because its template text selector matches both the
  selection card and preview heading. This is a verified test-selector defect,
  not evidence that the application ownership fix failed. Preserve that run;
  narrow the locator and repeat the complete focused gate without retries.
  Log: `/tmp/latexy-owned-surfaces-integrated-2026-10-04.log`.
- [ ] Compatibility-hook recovery survey: `useJobStatus.refresh` can announce
  completion from `/state` rather than authoritative `/result`, then dedupe the
  subsequent stream callback. Source evidence is concrete; active consumers and
  behavior remain under review. Root rejected source-string assertions as
  behavioral RED proof and requested actual hook/callback regressions before
  implementation. The `useATSScoring` hook currently has no importing product
  page; do not describe this as a demonstrated live ATS screen defect.
- [ ] Saved-builder autosave/reattach and tracker drag/result-modal surveys
  continue in parallel against the prior sealed server. No unverified candidate
  or passing same-owner control authorizes changing persistence semantics.

### Expanded surface / compatibility evidence

- [ ] Workspace activity-result ownership is verified RED: A's late result
  `finally` clears B's still-pending loading indicator. A same-owner deferred
  result control passes. A scoped identity/request fix is approved; acceptance
  awaits independent source review and a new sealed build. Evidence:
  `/tmp/latexy-workspace-job-result-ownership-red-2026-10-04/`.
- [ ] Saved-builder ownership is verified RED: A's delayed autosave changes B's
  builder to detached, and A's delayed reattach removes B's detached state.
  A same-owner autosave control passes. Owner/document lifetime guards are
  approved; no server persistence ordering redesign is inferred from these
  client callback failures. Evidence: `frontend/test-results/builder-saved-owner-race-*`.
- [ ] Compatibility-target WebKit app-quality run: **7 passed, 2 failed,
  1 skipped**, zero retries. Both failures occur at the keyboard skip-link check.
  An independent plain-HTML control reproduces Tab skipping links; Option-Tab
  focuses a link. On the actual app, Option-Tab focuses the skip link and Enter
  focuses the main content. This follows
  [Apple's documented Safari keyboard policy](https://support.apple.com/en-gb/guide/safari/cpsh003/mac).
  The test now uses Option-Tab only for macOS WebKit, preserving real keyboard
  focus and reduced-motion assertions. Fresh matrix acceptance is pending;
  native mac26 engine startup remains a separate unresolved coverage gap.
  Logs: `/tmp/latexy-webkit-mac15-quality-2026-10-04.log`,
  `/tmp/latexy-webkit-mac15-keyboard-control-2026-10-04.log`, and
  `/tmp/latexy-webkit-mac15-skip-link-control-2026-10-04.log`.
- [x] Application inventory recounted from the current local OpenAPI schema:
  **322 HTTP paths / 377 operations, 44 frontend pages, 44 router modules**.
  Corrected obsolete claims that no shared auth guard or builder/batch auth
  guards exist. These counts are inventory evidence, not journey acceptance.
- [ ] Integrated ownership run initially reports **93 passed, 2 failed** in
  2.8 minutes. Both failures are test locators: duplicate builder template text
  and the tracker assertion including Next's empty global route announcer.
  They were narrowed without relaxing the ownership invariants. The complete
  **95-case** focused run is repeating with zero retries against unchanged 5461
  application source; no overall green claim until its actual completion.
  Log: `/tmp/latexy-owned-surfaces-integrated-final-2026-10-04.log`.
  Actual repeat outcome: **93 passed, 2 failed**, 2.6 minutes. All three builder
  controls now pass. Tracker loaded its old test module before the locator edit
  finished, and the editor share-page no-error assertion independently reproduces
  React **#418**. Do not call this repeat an accepted green gate or filter that
  hydration error; the shared defect now demonstrably affects another route.
- [x] Compatibility-target WebKit repeat after the keyboard test correction:
  **9 passed, 1 desktop/mobile-conditional skip**, zero retries, 1.0 minute.
  Public route/runtime, named controls/structure, keyboard skip/reduced motion,
  visual evidence and mobile Studio controls pass against sealed 5461. Native
  mac26 startup is still unresolved; this result is explicitly mac15-target
  compatibility coverage, not native-host or deployed-site certification.
  Log: `/tmp/latexy-webkit-mac15-quality-final-2026-10-04.log`.
- [x] Chromium/Firefox/mobile Chromium quality repeat against the same 5461
  bundle: **13 passed, 2 desktop/mobile-conditional skips**, zero retries,
  1.4 minutes. Log: `/tmp/latexy-nonwebkit-quality-final-2026-10-04.log`.
- [ ] Root review corrections for the next bundle: workspace result setters
  need guards inside deferred React updaters; saved-builder autosave must rearm
  after auth recovery and clear busy state during transient verification errors.
  These were corrected before a new build, rather than accepted solely from
  static checks. Regression/source review and fresh runtime proof remain pending.

### Next frozen batch — port 5471

- [x] Root complete unit rerun: **154 files / 984 tests passed**, 13.09s;
  full ESLint also passes. Logs:
  `/tmp/latexy-frontend-full-result-builder-hook-2026-10-04.log` and
  `/tmp/latexy-frontend-lint-result-builder-hook-2026-10-04.log`.
- [ ] Root TypeScript run captured an auxiliary-panel diagnostic typo while
  agents authored new tests (`requestStarted()` called a promise). Current
  source correctly calls its resolver `started()`. The sealed build copy was
  corrected only in that test fixture; all three reviewed application files
  remain identical to the frozen checkout. A fresh type gate is still required;
  do not relabel the failed log as passing.
  Log: `/tmp/latexy-frontend-types-result-builder-hook-2026-10-04.log`.
- [x] Fresh complete nonincremental TypeScript check passes after the test-only
  correction. Log:
  `/tmp/latexy-frontend-types-result-builder-hook-final-2026-10-04.log`.
- [x] One production build completed on 5471 with reviewed workspace result,
  saved-builder and compatibility-hook source. No second builder is running.
  Log: `/tmp/latexy-production-result-builder-hook-server-2026-10-04.log`.
- [ ] Expanded zero-retry focused browser gate is now running on sealed 5471,
  including the new workspace result/cache and saved-builder controls. Log:
  `/tmp/latexy-result-builder-hook-prod-2026-10-04.log`.
- [x] Hook-specific behavioral simulator: **12 tests pass**, including
  authoritative completion, same-job terminal races, identity/ABA, queued
  progress, unmount/timer cleanup and an old timeout firing before passive
  cleanup. This invokes the real hook with simulated hook primitives, not a
  claim of actual mounted-React/browser integration.
- [ ] Auxiliary tracker owner-leak candidate is withdrawn: three old-server
  owner-switch cases pass because parent auth pending unmounts the panel.
  The corrected same-owner positive has not yet been rerun. Separate draft
  persistence tests are now authored; a UX expectation is not a verified bug.
- [ ] Added test-only saved-builder document/ABA, seed-upload ownership and
  tracker draft-refresh controls. Browser execution is paused during the heavy
  build. The earlier **633 scenarios / 71 files** collection predates these
  additions; collection remains distinct from execution.
- [ ] A minimal hydration fixture is authorized only in a separate temporary
  directory, with no application changes, dependency upgrades, error filtering
  or second build. Its authoring/review precedes any controlled experiment.
