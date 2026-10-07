# Historical publication appendix — October 6–7, 2026

Archived from PR #1804, head `144b37cb`, authored documentation-only appendix.
These entries preserve historical observations and pending states, not current
issue/PR/deployment status. Current acceptance is recorded in
[OPEN-PR-REVIEW-2026-10-07.md](OPEN-PR-REVIEW-2026-10-07.md), issue-specific
records, and subsequent GitHub checks. This archive does not close #1801 or
#1802. Their remaining acceptance gates are separate from the CI implementation
already merged on main. No stale implementation files accompany this archive.


### Protected publication and follow-up verification

- All #1788 dictionary head checks passed, with no unresolved review threads,
  but normal protected rebase returned `This branch can't be rebased` because
  of inherited historical merge commits. Replacement #1791 starts from main
  d54e0f63 and cherry-picks only the fourteen selected one-file commits. Root
  verified its **entire committed tree** matches the previously tested head.
  Fresh required checks remain mandatory; no force push or protection bypass
  was used. #1788 is retained until the replacement is accepted.
- #1787 is published separately as #1792 with four one-file commits and no
  frontend or unrelated artifacts. Root independently accepted scoped Ruff
  and the complete strict isolated backend suite: **4,273 passed / 5 skipped**
  out of **4,278 collected**, with no failures or errors. Artifact
  `/tmp/latexy-1787-backend-full-root.log`; the existing Starlette HTTPX
  deprecation is recorded, not suppressed as a new safety waiver. Shared
  metadata policy retains the existing 4,096 escaped-JSON-byte / depth-five
  limits and redaction list. Iterative depth measurement and serialization
  recursion handling also protect tiny deeply nested inputs. Actual FastAPI
  admission tests verify invalid inputs return 422 before fake DB writes.
- Root review caught a first-read regression in the notification candidate:
  B's failed initial GET could expose A's old preferences. The candidate now
  hides controls until B's successful read and exposes a truthful error/Retry;
  same-owner known preferences remain visible during refresh failure. API
  notification GET/PUT calls use explicit owner/token dispatch contexts.
  Existing OAuth controls are retained; the obsolete lexical effect marker
  was replaced with the actual call, mounted lifetime is exercised, and real
  notification auth-gate tests cover allow/stale-owner/stale-token paths.
- Notification candidate unit verification passed **158 files / 1,012 tests**,
  full Node 22 ESLint and nonincremental TypeScript. A proposed unmount test
  initially used full-document navigation, which destroys the pending fetch
  realm; root rejected that fixture. The corrected control uses rendered
  client-side account-menu navigation and verifies the old response body was
  consumed after remount. It passes on the sealed baseline (a positive
  lifetime control, not another verified old-source defect). A fresh isolated
  40-case integrated production-build run is pending; no acceptance is inferred
  from implementation alone.
- Dependabot #153 still reports the upstream `braces` version with no available
  patched version. The committed patch, lockfile hash and installed regression
  remain consistent. Actual `next-pwa -> fast-glob -> micromatch -> braces`,
  Tailwind and ESLint resolution reaches the patched root package. The plain
  ignored frontend virtual-store directory is an orphan, not an active
  vulnerable consumer. No install, symlink rewrite or alert dismissal occurred.
- Hydration #1772 remains open. The unpublished server-signature diagnostic
  passed **one Playwright test containing ten auth-timing arms**, with explicit
  empty page-error and unknown-route assertions. This is a clean bounded
  observation, not ten independent tests or a root-cause fix. The prior delayed
  page-chunk probe never demonstrated authenticated header consumption while
  the page chunk was still held, so it did not exercise the suspected race.
  Preserved reload failures and operator-only acceptance gaps remain in scope.
- #1793 now tracks two root-verified onboarding defects. The current and sealed
  hook source hashes match. With expected B session and bearer-derived `/me`
  body markers consumed, an ordinary incomplete B account displays the tour;
  a completed B account without local cache incorrectly keeps the tour open.
  Separately A actually completes/skips (captured synthetic A preference PATCH),
  then an incomplete B reload inherits A's global completion and misses its
  tour. Artifact
  `/tmp/latexy-onboarding-owner-isolation-diagnostic-2026-10-06-final3.log`:
  **one positive passed / two desired-safety assertions failed**, with empty
  page-error and unknown-route gates. Initial insufficient CORS body markers
  and a preseeded completed-account control were strengthened before acceptance.
  Account-scoped cache/replay and owner/lifetime/reconciliation safeguards are
  planned; no production account writes or speculative hydration fix occurred.
- Dictionary #1791 merged normally at **ed4eaf25** after all fresh required
  checks and no unresolved threads. Root verified the entire merged tree is
  identical to the tested clean replacement and closed superseded #1788 without
  deleting its historical branch. Security #1789, variant #1790 and backend
  #1792 were updated with normal GitHub CLI rebase; their scoped source trees
  still match the accepted snapshots. Rollout acceptance remains separate.
- #1794 tracks the root-verified legacy integration callback race. The exact
  current/sealed legacy block hashes match. Before A's release, B's bearer
  status body and visible `BobGitHub` are applied with no success notice; after
  consuming A's legacy body, `AliceLegacyGitHub` and stale success replace B.
  Same-owner success and actionable verification-failure controls pass. The
  final fixture is unannotated (no `test.fail` swallowing setup failures):
  **two controls passed / one desired-safety assertion failed**, one worker and
  zero retries, in
  `/tmp/latexy-settings-legacy-callback-5485-unannotated-final.log`. Synthetic
  service-worker registration is a stated dependency boundary, not PWA proof.
- Fresh notification integration finished **39/40**, not an accepted green run:
  `/tmp/latexy-publication-1786-fresh-40-node22-final2.log`. The initial-read
  error/Retry behavior reached its expected state, but its enabled page-error
  gate caught React **#418 on Settings**, extending #1772's route evidence.
  Two earlier 38-pass runs remain recorded; same-owner test refreshes initially
  reused an identical session payload and did not trigger a new read. Fixtures
  were corrected with real synthetic token rotation and a precise alert locator;
  application hashes stayed unchanged. No page-error suppression or clean-rerun
  substitution is authorized. The notification candidate may be committed for
  isolation but is not accepted for protected merge/deployed certification yet.
- #1795 tracks a new active dependency finding that now blocks fail-closed CI
  before ESLint/unit execution: Next resolves vulnerable `sharp 0.35.4`, and
  registry advisory `GHSA-wq5f-xc86-pv6w` requires **0.35.5** with librsvg 2.63.2.
  Upstream: https://github.com/advisories/GHSA-wq5f-xc86-pv6w . Root reproduced
  the audit, preserving the separate tested braces mitigation. A narrowly scoped
  override/lock update is being tested in an isolated publication checkout;
  unintended Turbo/latest and unrelated semver rebinding from regeneration were
  restored. Shared QA dependencies remain untouched. Runtime-specific exposure
  is not a claim of measured production exploitation or compromise.

### Deployed dictionary acceptance and security patch review

- Exact-main **ed4eaf25** canonical CI 37484587860 passed. Modal automatic
  rollout 37485572775 executed migrations, rolling deployment, catalog/preview
  synchronization and backend/catalog health checks successfully (not merely a
  stale-deployment skip). Modal v60 carries the full revision tag. Vercel
  certification 37485572830 successfully verified the canonical alias.
- Root tested the deployed dictionary frontend against `https://latexy.xyz`:
  **6/6 passed**, one worker, zero retries, with enabled page-error assertions.
  Exact Vercel identity remained ed4 before and after. Cases include owner B,
  ownerless legacy, retained account switches, consumed stale ABA bodies,
  ordinary add/remove and scoped offline failures. Log:
  `/tmp/latexy-dictionary-live-ed4-20261006.log`. Auth/preference responses and
  service-worker registration were deliberately synthetic, with fail-closed
  ancillary routes; this is not certification of real-account database writes,
  providers or PWA integration. Acceptance is recorded on #1783.
- Security patch #1797 contains four selected one-file commits from main ed4:
  override, narrowly scoped lock update, installed Sharp runtime regression,
  and CI invocation. Root independently ran the actual regression against both
  binaries: the old 0.35.4 version assertion fails while its three compatibility
  controls pass; all four pass on 0.35.5. The test checks Next's actual loaded
  Sharp instance, librsvg minimum version, raster resize and benign SVG render.
  Frozen installation and the existing installed braces regression pass;
  dependency audit reports **zero unresolved** advisories. No suppression or
  protection bypass was added. Production acceptance remains pending.
- Full frontend lint and **158 files / 1,004 unit tests** passed again on verified
  **Node 22.23.2**, using the mise runtime explicitly. Logs:
  `/tmp/latexy-1795-root-actual-node22-lint.log` and
  `/tmp/latexy-1795-root-actual-node22-unit.log`. The Homebrew `node@22` symlink
  actually points to Node 23.1.0; earlier `1795-root-node22` filenames therefore
  do not establish Node 22 execution and were superseded, not silently renamed.
- Root onboarding review rejected acceptance of the first seven green runtime
  cases: old callbacks captured the latest owner ref but retained old cache keys
  and token; readiness was not render-owner stamped; a rotated initial-read
  token could strand reconciliation; request revisions could strand the action
  lock. Expanded actual-hook regressions and repair are in progress. Existing
  positive tests alone do not prove these interleavings safe.
- Hydration investigation is authorized for one bounded, instrumented ignored
  production copy of the sealed baseline. It must demonstrate actual session
  snapshot application between root and Settings commits, preserve all errors,
  and distinguish that order from a post-Settings-commit control. No speculative
  application-wide auth wrapper or broad-run replacement is accepted.

### Protected security merge and onboarding isolation

- #1797 merged normally as **c3990ba2404a23b92fd3524f754e1cc20b6dcc1b**
  after every feature-head check passed, including duplicate required contexts,
  with CLEAN merge state and no unresolved review threads. Root verified the
  entire merged tree matches feature head eb34f938. Local main and origin/main
  were advanced without touching the dirty shared QA checkout. Main canonical
  CI **37489121790** and automatic rollout certification are still pending.
  Vercel already reports c399 identity; a real public icon optimization returned
  HTTP 200, WebP 64×64, with identity unchanged afterwards. That functional
  endpoint check does not introspect Vercel's managed native binary.
- Existing PRs were normally rebased onto c399: security #1789 head
  **4c970a17**, variant #1790 **26278055**, backend #1792 **dd0fd443**.
  Root confirmed the patched main is an ancestor of all three and each scoped
  accepted source tree is unchanged. Fresh CI remains mandatory; queued checks
  are not failures and do not justify weakening branch protection.
- Onboarding review added live confirmation/token admission for retained
  same-owner callbacks, a real attempted third action while a newer write is
  pending, and a ready-state token-refresh control. A self-triggering readiness
  effect dependency was removed after root identified duplicate B reads on
  real state rerender. The actual-hook harness now has **13 passing cases**.
  These added review controls were not run against a saved intermediate source
  snapshot, so no pre-fix red execution is claimed for those candidate defects.
- Root independently accepted full Node 22 unit execution at the reviewed
  shared snapshot: **160 files / 1,039 tests**, including the separate pending
  twelve-case legacy provider API-context candidate, plus scoped zero-warning
  lint. Logs: `/tmp/latexy-onboarding-reviewed-root-node22-unit.log` and
  `/tmp/latexy-onboarding-reviewed-root-node22-lint.log`. Six onboarding source
  and unit files were committed individually through **8b352569** for isolation.
  Fresh browser acceptance and protected publication are still pending; these
  local commits do not mark #1793 resolved. Settings legacy-block ownership was
  then handed to a single writer, preserving the committed onboarding changes.

### Security deployment accepted; account-security merge pending rollout

- Security patch c399 passed canonical main CI **37489121790**. Exact-main
  Vercel certification **37490812677** and Modal rollout **37490812520** passed;
  all migration, rolling-deploy, template/preview, backend health and catalog
  asset steps executed successfully. Root independently verified Modal **v61**
  with the full c399 tag, public Vercel identity c399, and `/readyz` reporting
  database, Redis and Redis cache healthy. #1795 has a deployed-acceptance comment.
- Account-security #1789 then merged normally as
  **317b9b3d0b1cf05cb4a007dbf179129993d67ba5**, with all 34 reported feature-head
  checks successful, CLEAN merge state and no unresolved review threads. The
  entire merged tree matches accepted head **4c970a17**. Local main/origin/main
  now point to 317b; exact-main CI **37491413204**, rollout and the eight-case
  deployed frontend acceptance remain pending. No protection bypass was used.
- Root additionally checked whole-tree rebase diffs for #1789/#1790/#1792:
  only the four accepted Sharp patch files changed relative to their previous
  heads. This avoids relying on a mistakenly narrow security-component path;
  the actual PR module is `frontend/src/components/auth/SecuritySettings.tsx`.
  Variant/backend PRs are being normally rebased again after main advanced.
- The first prepared seven-case onboarding fixture was rejected on review:
  an init script cleared completion keys on every reload, masking the original
  A-to-B defect; held-request release lacked admission synchronization; token
  refresh assertions used header counts rather than consumed/applied sessions.
  Body-clone instrumentation, persistent storage, explicit held-body barriers,
  current-step/rotated-PATCH controls and faithful registration stubbing are
  being corrected. It has not been browser-accepted or published.
- The instrumented hydration build compiled but produced no runnable standalone
  artifact. Root found real `pg` metadata exists in the repository virtual
  store; the temporary nested copy's relative pnpm links instead resolved into
  the wrong frontend directory. One corrected, repository-root ignored copy
  with an absolute dependency symlink is authorized. The earlier failed build
  logs remain preserved; neither missing project dependencies nor a hydration
  cause/fix is inferred from that diagnostic setup failure.

### Live account-security verification preserves another hydration failure

- Main **317b** canonical CI **37491413204** passed. Exact-main Vercel
  certification **37492254794** and Modal rollout **37492254418** completed
  successfully, including all rollout steps. Root independently observed
  matching frontend identity and Modal **v62 / full 317b tag**.
- Live synthetic account-security acceptance is **7/8**, not certified green:
  `/tmp/latexy-security-live-317b-20261006.log`, one worker, zero retries,
  Node 22. The same-owner refresh case passed its passkey-owner and both private
  draft-value assertions, but the retained page-error gate caught React
  **#418, args[]=HTML**. All other seven cases passed, including stale MFA,
  retained owner switch, ABA and unmount. Identity stayed 317b before/after.
  Failure screenshot/context are preserved under
  `frontend/.playwright-e2e-80onxm/account-test-results/settings-passkey-owner-iso-25840-across-a-same-owner-refresh/`.
  #1772 and #1785 now record this separate live failure. It is not masked by
  clean local runs, deployment-workflow success or successful functional checks.
- A new isolated live diagnostic is authorized for only that original case,
  three repetitions, with full stack/timing and actual body-consumption probes.
  It must use a different output directory, preserve this initial failure,
  keep the page-error gate and abort if the deployment identity changes. Real
  auth/backend/provider requests remain forbidden by fail-closed synthetic
  routing. No production account/database mutation is certified.
- Corrected local hydration instrumentation recorded **one test with four
  arms**, not four independent accepted tests. Stored results show both intended
  session/Settings orders, complete auth/notification body reads, and zero
  page/browser/unknown-route errors; expected console resource/503 noise remains
  visible. Its original final assertion only checked result count. Stronger
  assertion source was subsequently type-checked, not rerun. The runtime bundle
  was auto-removed by the launcher, and its visible-main signature omitted full
  streaming context. These bounded observations neither resolve #1772 nor
  justify a global auth-wrapper change.
- Root independently ran full unit coverage for an intermediate legacy repair:
  **161 files / 1,057 tests** in
  `/tmp/latexy-legacy-reviewed-root-node22-full-unit.log`. Review then identified
  same-owner newer-operation/notice-timer gaps; further repair remains pending.
  A fake Strict Mode test without mounted cleanup/setup was corrected after
  genuine pre-fix reproduction. No legacy source is published or accepted for
  fresh browser verification yet.

### Bounded live repetitions and concurrent main update

- The isolated same-owner account-security diagnostic completed three repetitions
  against unchanged deployed **317b**, one worker and zero retries, with zero
  page errors. Actual body reads, script timing and checkpoints were recorded
  in `/tmp/latexy-security-live-317b-diagnostic-run.log` and the separate
  `.playwright-e2e-security-live-317b-20261006/` output. Expected blocked telemetry
  console errors remain visible. The original failed screenshot/context were
  hash-checked and preserved. Three clean repetitions do not supersede the
  earlier eight-case **7/8** acceptance failure or close #1772.
- Main independently advanced to **275a9d28** through the logo PR #1796 while
  this diagnostic ran. A normal protected merge of #1792 was rejected because
  its reviewed head was now behind; no protection was bypassed. Root normally
  rebased #1792 to **9569331e** and #1790 to **67be1e26**, then verified each
  whole-tree old/new diff contains only the 31 files introduced by #1796.
  Their scoped repairs are unchanged. Fresh required checks must finish before
  either can merge; local main now tracks this new remote main.
- Legacy same-owner operation/notice revisions, onboarding browser acceptance,
  non-finite metadata error handling, and owner-race CI coverage remain under
  review. No unaccepted repair is represented as deployed or fully certified.

### Variant rollout, corrected fixtures, and new scope-aware CI request

- #1790 merged normally at **9262746642ef843ea8c4fa40cfa6269c41a95244**,
  with all 34 fresh checks successful and no unresolved review threads. The
  merged tree exactly matched reviewed head **67be1e26**. Canonical main CI
  **37496276781**, Vercel certification **37497507836**, and full Modal rollout
  **37497507787** succeeded. Live synthetic variant acceptance was **9/10**:
  `/tmp/latexy-variant-live926-20261006.log`. Functional owner/draft assertions
  passed; transient-session recovery caught another React #418. Identity stayed
  926 before/after. Its separate screenshot/context/trace remain preserved;
  neither workflow success nor functional correctness closes hydration QA.
- The first integrated production-source run at **5501** was **5/47**, not an
  accepted app regression report. Forty failures were missing Workbox fixture
  registrations with `serviceWorkers:block`; earlier reviewed ignored copies
  supplied that synthetic boundary, but shipped source fixtures did not. Two
  onboarding fixture assertions also failed: the `/me` count assumed one
  consumer rather than Header/Theme/Onboarding, and step copy assumed three
  steps rather than four. Original output is preserved in
  `/tmp/latexy-reviewed-candidate-main275a-5501-e2e.log` and its separate directory.
- Root corrected onboarding acceptance to hold all three initial-owner `/me`
  requests, keep their stale values distinct from the fresh owner epoch, require
  each held response's unique body-read marker, and assert the real second-step
  title/progress. The intermediate run was **6/7** with only incorrect step copy;
  the final corrected run was also **6/7**, this time solely genuine #418 after
  A completion and B reload. All seven functional controls passed. Final log:
  `/tmp/latexy-reviewed-candidate-main275a-onboarding-final.log`; failed trace
  shows B session response followed by #418 before B `/me`, but no application
  component frame or proven cause. No clean rerun replaces that failure.
- Prepared #1799's source fixture helper and zero-retry three-engine owner job
  as six individual local commits **f85a4af0**, **783390ae**, **ce8bedc2**,
  **0521f377**, **b7c32074**, **3488b83c**. Actual execution was Chromium **24/24**,
  Firefox **23/24** (#418), WebKit **0/24** (host engine launch segmentation
  faults before app execution), not 72 accepted cases. Evidence:
  `/tmp/latexy-owner-ci-three-engine-5501.log`. The new job is not published;
  error gates remain unchanged and real service-worker lifecycle is not covered.
- Legacy provider repair passed root's final **161 files / 1,061 unit tests**,
  scoped lint and nonincremental TypeScript. It was saved as five one-file local
  commits **9bf6d9d0**, **8b2fb73f**, **2d978535**, **7fa2ad63**, **8283d33a**;
  corrected onboarding fixture is **72c978b9**. Provider operation revisions and
  published-notice revisions are separate; same-owner pending token refresh
  preserves notice expiry, actual Strict Mode cleanup/setup restarts verification,
  and HTTP 200 `connected:false` is no longer treated as verified success.
  Agent pre-fix reds existed only in tool stdout, not saved red log artifacts;
  root does not claim independent retained red evidence for those additions.
  Fresh production/browser acceptance of the legacy repair remains pending.
- #1800 tracks verified non-finite metadata admission and unsafe validation
  diagnostics. Root independently reproduced actual ASGI routing against strict
  fake persistence, then reviewed the shared policy/error-envelope repair. Full
  strict backend execution exited zero: **4,287 collected / five skips**; focused
  modules **31 passed**, ruff passed. Logs:
  `/tmp/latexy-nonfinite-root-full-backend-20261006.log`,
  `/tmp/latexy-nonfinite-root-collection-final.log`,
  `/tmp/latexy-nonfinite-root-focused-final.log`. Four local one-file commits:
  **90d24a5c**, **7193ba9d**, **f304e6e4**, **e649b036**; publication waits for #1792.
  No real production DB/provider writes occurred.
- User explicitly requested folder-specific CI. Root confirmed canonical CI
  has no scope filters and commonly duplicates push/PR jobs; 33/34 check entries
  are not 33 different workflow definitions. #1801 is being implemented in
  separate clean worktree `/tmp/latexy-ci-scoping-VEjbTi`, excluding the unaccepted
  owner job. Planned policy keeps global guards and required names, classifies
  accurate NUL-safe PR/push ranges, conservatively covers shared/unknown changes,
  and avoids redundant feature push plus PR suites. The local untracked
  `.github/workflows/ci-cd.yml` is user-owned and **not** an active GitHub workflow.
- External #1798 then advanced main to **c1b0122d**, reverting its unrelated TUI
  guard change. A preceding #1792 run had genuinely failed Ctrl+L empty prompt;
  root did not waive/retry it into acceptance. #1792 was normally rebased onto
  this new main at **72bf3018**, with fresh checks required again. Scope branch
  was safely fast-forwarded to c1b while preserving its unrelated working edits.

### Component-scoped CI publication and deployment reconciliation

- #1801 is implemented in PR **#1803**, head
  **c2ccbc5c435ed952711074be399728dd650a7d21**, from main c1b. Five selected
  one-file commits contain the classifier, its tests, structured manifest
  contract tests, canonical workflow, and CI policy document. Root independently
  ran actual Node 22: **20/20** classifier cases; static manifest tests:
  **82/82**. Node syntax, Ruff, actionlint **1.7.7**, and diff checks passed.
  Logs: `/tmp/latexy-ci-scope-root-final-node22-20261006.log` and
  `/tmp/latexy-ci-scope-root-final-manifests-20261006.log`.
- This is job-level selection, not workflow path suppression. Required display
  names and read-only/fork-safe permissions remain unchanged. Every PR retains
  classifier tests and privacy guards; docs-only changes skip expensive suites.
  Main pushes still validate selected components; manual dispatch selects every
  scope. Feature pushes no longer duplicate PR CI. Unknown/unsafe paths,
  workflow changes, failed classification, ambiguous ranges, submodules, and
  executable files in prose trees fail closed. Backend contracts/runtime and
  shared JS dependencies expand relevant cross-component coverage without
  automatically scheduling unrelated unit families.
- Classifier-job failure explicitly fails the unconditional privacy guard.
  Full-stack smoke allows skipped backend unit tests only when backend scope is
  explicitly false and the frontend build succeeded. Component skips are not
  claims that tests ran. External CodeQL, GitGuardian, and Vercel app checks are
  not controlled by this workflow. #1799's unaccepted owner browser job is
  excluded. Actual GitHub scope/required-check behavior still needs acceptance;
  a useful documentation-only follow-up will exercise the new PR workflow.
- #1802 independently tracks a genuine deployment-policy mismatch. Main c1b's
  Vercel status is **success / "Skipped - Not affected"** (TUI-only source
  change), but exact-main certification **37498391872** failed after 30 polls.
  Live frontend identity still reports **92627466**. Modal **37498391973**
  successfully executed all migration, rollout, template, and health steps for
  c1b. This is not evidence of a failed frontend build and not acceptance that
  c1b is actually served by Vercel. Evidence:
  `/tmp/latexy-c1b-vercel-failed-logs.zip`, job **112388737991**, and the live
  `/api/deployment-identity` read. No project setting, production override, or
  manual redeploy was used to suppress the mismatch.
- #1792 head **72bf3018** has one genuinely failing required TUI check despite
  another parallel job passing: the real PTY empty-prompt Ctrl+L test received
  literal `l`. Same failure existed before the external #1798 revert. Logs:
  `/tmp/latexy-pr1792-tui-job-112388083998.log` and prior
  `/tmp/latexy-pr1792-old-tui-job-112381699954.log`. Root has not waived or
  rerun it into acceptance. A separate isolated TUI reproduction/repair audit
  is in progress; a precise React-ordering cause is not yet independently proven.
