# Accumulated remediation publication — October 6, 2026

The user requested that all accumulated task work be merged into `main` so
another worktree can start from the current implementation. This supersedes
the earlier instruction to defer commits and publication. Integration issue:
[#1750](https://github.com/sanskarpan/Latexy/issues/1750), integration PR
[#1751](https://github.com/sanskarpan/Latexy/pull/1751).

## Snapshot and safety

- Starting branch: `fix/redis-resource-lifecycle`, at `7cf484cb`.
- Starting remote main: `8ff2124aa21338d8a97ae60dbec1962af4921609`.
- Preserve the 37 existing unpublished commits and create individual-file
  commits for accumulated source, test, documentation and configuration work.
- Exclude the unrelated untracked `.github/workflows/ci-cd.yml` and `test.txt`.
- Leave the seven pre-existing October 2025 root scratch reports local and
  unchanged: `COMPREHENSIVE_ANALYSIS.md`, `FINAL_STATUS_REPORT.md`,
  `PHASE12_SUMMARY.md`, `PHASE_13_AND_BEYOND.md`, `PHASE_14_COMPLETE.md`,
  `PHASE_14_IMPLEMENTATION.md`, and `SUMMARY_FOR_USER.md`. Their literal date
  placeholders and old completion claims are not current QA evidence.
- Exclude changes to generated `frontend/playwright-report/index.html` and
  `frontend/tsconfig.tsbuildinfo`; preserve those local files without publishing
  their private/generated contents.
- Keep ignored environment files and provider credentials out of the snapshot.
  The tracked production environment file deletion is intentional; committed
  examples and secret-manager configuration remain the supported contract.
- Include referenced QA screenshots and the documented texlab evaluation spike.
- Scan the selected final-source snapshot, not credential-bearing local
  environments. The initial scan produced eight reviewed fixture/copy false
  positives, not new usable provider credentials.
- Do not force-push, bypass required checks, or overwrite another contributor's
  main-branch work. Preserve granular commits with a merge commit, not squash.

## Fresh verification and integration blockers

- Frozen JavaScript lock validation passes.
- Privacy/session-recording/marketing guards pass.
- TUI initial typecheck/build and tests pass (224 tests, 66 conditional skips);
  dependency updates require a subsequent checkpoint.
- Observability initially failed because the production example deliberately
  leaves the required immutable image tag blank. The validator now supplies
  only a command-scoped current-commit tag for Compose rendering. Full static,
  Prometheus and Alertmanager checks pass; deployment validation stays strict.
- Initial fresh strict-warning backend run found six failures; see the resolved
  follow-up checkpoint below. Old backend counts were not used as certification.
- The current registry audit found 40 advisories. Compatible dependency updates
  reduce that to one advisory in `braces@3.0.3`, which has no upstream release
  fixing [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm).
  A local pnpm patch bounds parser nesting and recursive AST walks. Installed
  dependency regressions are required before recognizing this exact version /
  advisory as mitigated; all other findings and malformed audit responses fail
  the dependency gate. Raw registry counts are not falsely described as zero.
- Frontend unit, type, lint, production and protected-branch checks remain
  required before merge. The frontend unit suite is now explicitly part of CI.

## Subsequent independent review

- Fresh frontend suite after the security follow-ups: 155 files / 989 tests
  pass. The fresh sealed production bundle passes 25 owner-scoped browser
  regressions with zero retries, plus 13 Chromium/Firefox desktop/mobile quality
  checks (two desktop-only mobile-case skips). Linux five-engine CI is separate.
- CI exposed clean-checkout gaps: the root placeholder-only production example
  was excluded by a global `.env.*` ignore rule, and the nginx log mount lacked
  a tracked directory placeholder. Narrow ignore exceptions preserve secrets
  and actual log exclusions while publishing these safe deployment inputs.
- Python lock validation now compares every pin, marker and hash while omitting
  platform-dependent provenance comments. It still seeds existing compatible
  pins and recompiles against both direct-dependency input files.
- The template extraction job needed `fonts-noto-core`, matching its actual
  Devanagari template and the production image. Local macOS does not supply
  Poppler; the complete extraction contract now passes Linux CI on `493fbb7a`.
- The browser-quality fixture mocked the wrong hard-coded backend host. API
  mocks now follow paths and resource types without swallowing page navigation.
  A successful background Better Auth refresh does not mark a retained session
  pending; the persona revalidation control now exercises an actual 503/error
  followed by recovery, instead of requiring incorrect optimistic-state behavior.
- Student checkout validates invalid academic addresses normally, but must not
  send a verification email when billing is unavailable. Independent review
  caught and corrected a proposed regression of that safeguard.
- Backend database ownership was traced to a chat test creating a pool on the
  pytest loop and then replacing it during a TestClient portal-loop lifespan.
  The framing test now uses isolated permission reads and an explicitly closed,
  non-lifespan client; dedicated database-backed ACL tests remain. Websocket
  protocol tests separately mock durable cancellation, whose DB behavior has
  its own integration coverage.
- Fresh complete, plain backend run: **4,219 passed / 5 skipped**, enforcing
  `ResourceWarning`, `RuntimeWarning`, and pytest unraisable warnings as errors.
  No diagnostic plugin or warning suppression was used for this acceptance run.
  One unrelated Starlette deprecation notice remains visible.
- The disposable browser launcher now generates Monaco assets from its own
  dependencies before both development and production startup, rather than
  copying ignored workspace assets. A fresh development copy passes the same
  13 Chromium/Firefox quality checks with two desktop-only mobile-case skips.
  Linux CI remains authoritative for the five-engine required browser context.

The source checkpoint for these local results is
`abc09b791c54c1279df27aa9c08caef22b750381`. This ledger update changes only
documentation; protected CI still must validate its final published head.

Fresh log locations (ephemeral, not repository artifacts):

- `/tmp/latexy-publication-backend-final-plain-2026-10-06.log`
- `/tmp/latexy-publication-frontend-final-monaco-2026-10-06.log`
- `/tmp/latexy-publication-security-browser-regressions-2026-10-06.log`
- `/tmp/latexy-publication-clean-dev-quality-2026-10-06.log`

## Security scan follow-ups

GitHub CodeQL reports 100 open branch alerts on the initial published head:
4 critical, 14 high and 82 medium. These are findings to validate, not proof
that all 100 are exploitable. No bulk dismissal or security-gate waiver was used.

- Fixed predictable device session identifiers with a platform CSPRNG.
- Replaced incomplete Markdown inline-code escaping with collision-safe spans,
  tested using the actual CommonMark parser, including blank paragraphs and
  many backtick runs.
- Bound the reusable render action's source read through one opened descriptor,
  including file growth and partial-read controls (six action tests pass).
- Decode extension entities in one pass and recognize whitespace / ignored
  attributes before script and style closing brackets (six extension tests pass).
- Remove raw cache-key diagnostics and neutralize control characters at
  application loggers even when workers use plain-text handlers. Existing
  structured JSON logging remains a separate defense.
- Harden the four flagged regex sites and add adversarial input regressions
  with process deadlines. Linux CI caught that possessive metric matching alone
  still rescanned rejected comma-chain suffixes; complete candidate consumption
  followed by anchored matching preserves valid-prefix behavior without those
  repeated searches. The 100k-character controls complete locally in ~0.02s.
- Critical SSRF findings need evidence-based review of existing fixed-origin,
  encoded-path, redirect-disabled provider requests and the default DNS-pinned
  public-URL transport. Do not dismiss merely because an initial validation
  function exists. Remaining scan results stay visible for follow-up.

Independent review additionally identified the reusable action's lexical-only
workspace boundary: source/output directory symlinks can escape that boundary.
This is a separate follow-up to validate and resolve, not covered by the source
descriptor race controls. No whole-action security-completion claim is made.

The GitHub Production environment now has the verified Vercel project and org
IDs and a Vercel credential supplied through the local environment without
printing or committing it. Existing Modal secrets remain in that environment.
After merge, both automatic deployment paths still require exact-SHA and live
health verification; a passing preview is not production certification.

## Acceptance boundary

Publication is not a claim that the ongoing whole-product goal is complete.
Unproven hydration hypotheses, remaining owner-race surveys, native macOS
WebKit startup, operator-controlled credentials/capacity/payment policy and
production authenticated QA remain separately tracked. A successful build or
merge is not proof of the exact deployed SHA or all live product behavior.

Record the integration PR, successful checks, merged main SHA and deployment
results here as they become available. Until then, do not claim merge or live
certification.

## Merged main checkpoint

- PR #1751 merged on October 6 at 09:20:44 UTC, with merge SHA
  `dce0bf4108fa0ab3f72b8991617bcae08afaa8e8`.
- Every required protected-branch context passed on the final PR head
  `5ee272661e0720fbf5d4ed733d1532deeb28937c`. The Linux browser run reported
  22 passed / 3 conditional skips; both full-stack smoke runs passed.
- GitHub limits rebase merging to 100 commits; this integration preserves
  1,040 commits. With explicit user approval, only the linear-history flag
  was temporarily disabled for a normal merge commit and immediately restored.
  The complete branch-protection JSON is identical before and after the merge.
  No administrator bypass, force push, squash or security-alert dismissal was
  used. False-positive review threads were individually answered with evidence.
- Local `main` and `origin/main` both advanced to the merge SHA. The merged
  source tree is identical to the tested PR head, and every excluded local file
  retained its pre-switch SHA-256 hash. New worktrees can start from this main.
- Canonical main CI run: [37442317625](https://github.com/sanskarpan/Latexy/actions/runs/37442317625).
  All jobs passed on the exact merged SHA, including full-stack smoke.
- Vercel certification run
  [37443095109](https://github.com/sanskarpan/Latexy/actions/runs/37443095109)
  passed. Direct `https://latexy.xyz/api/deployment-identity` verification
  returned HTTP 200, `Cache-Control: no-store`, and the exact merged SHA with
  `source: vercel`. The live landing and guest editor load, editor controls
  become interactive, and the guest template panel opens. These observations
  are not an authenticated feature or end-to-end compilation certification.
- Modal rollout run
  [37443095334](https://github.com/sanskarpan/Latexy/actions/runs/37443095334)
  failed while building the TeX image, before the migration function or backend
  deployment ran. Modal serialized the raw multiline warm-up script as a
  Dockerfile `RUN`; its parser rejected the shell `fi` line. The existing backend
  deployment was not replaced. The blocker is tracked in
  [#1758](https://github.com/sanskarpan/Latexy/issues/1758). Backend production
  certification remains pending; it is separate from PR previews.
- Next scoped QA follow-ups are tracked as
  [#1752](https://github.com/sanskarpan/Latexy/issues/1752) (render-action
  source/output symlink boundaries) and
  [#1753](https://github.com/sanskarpan/Latexy/issues/1753) (actual guarded HTTP
  redirects, fixed-provider URL construction, exact scraper host classification).
  They are not part of the merged source checkpoint above.

## Post-publication QA follow-up validation

- Render-action symlink containment now resolves the physical source and
  output parent, uses the validated physical paths for I/O, rejects external
  and dangling parent links before API calls, and retains safe internal links
  and atomic final-name replacement. Eight action tests pass, including linked
  workspace roots and file-as-directory failures. Concurrent ancestor-directory
  swaps still require OS-native handle-relative traversal for atomic isolation;
  the portable validation does not claim that guarantee.
- URL-import regressions now run the actual default HTTPX client, preflight,
  redirect machinery and DNS-pinning guard, mocking only DNS answers and the
  inner network send. Private-address and `file://` redirects are blocked;
  public-to-public redirects succeed and both hosts are pinned.
- Fixed-origin tests assert DOI, Zotero and GitHub path values cannot change
  the requested provider hostname. The scraper no longer misclassifies
  `wwwgreenhouse.io` by stripping arbitrary `w`/`.` prefix characters.
- Independent root run of all five affected backend suites: **204 passed**
  with all three warning-as-error flags; one existing Starlette deprecation
  notice remains. Log:
  `/tmp/latexy-post-publication-security-focused-2026-10-06.log`.
- These changes still require their own protected PR checks and merge; passing
  local tests does not place them in the published main snapshot.
- Follow-up PR: [#1757](https://github.com/sanskarpan/Latexy/pull/1757).
- The Modal blocker fix serializes the unchanged warm-up script as UTF-8
  base64, decoded into `sh` through a single physical Dockerfile command.
  Round-trip controls cover multiline text, Unicode, quotes, backslashes and
  shell metacharacters; executable controls retain non-zero failure status
  with bounded subprocess deadlines. Pinned Modal 1.5.4's offline Dockerfile
  generation was also inspected. Independent root parity/manifest suites:
  **105 passed**, strict warning flags and scoped Ruff clean. Log:
  `/tmp/latexy-modal-serialization-root-review-2026-10-06.log`.
  This is local/offline evidence, not a successful production retry.

## Follow-up merged checkpoint and second deployment blocker

- PR #1757 merged by normal protected rebase on October 6 at 09:55:02 UTC.
  Local and remote main both reached
  `3250051e47c214cc64a665ae921fe927d93c878d`; its source tree matches the
  validated PR head. All accumulated publication work is available to new
  worktrees. Required checks, strict freshness, administrator enforcement,
  conversation resolution and linear history remain enabled.
- Canonical main CI
  [37446253281](https://github.com/sanskarpan/Latexy/actions/runs/37446253281)
  passed. Exact-SHA Vercel verification
  [37446860286](https://github.com/sanskarpan/Latexy/actions/runs/37446860286)
  passed; the live deployment identity independently returned this main SHA.
- Modal rollout
  [37446860439](https://github.com/sanskarpan/Latexy/actions/runs/37446860439)
  successfully built the repaired images and applied production migrations.
  Rolling deployment then failed because the application declares seven
  scheduled functions against this workspace's limit of five. It did not
  replace backend release `v49`, tagged
  `8ff2124aa21338d8a97ae60dbec1962af4921609`. The old API still reports ready
  after the migrations. Schedule consolidation is tracked in
  [#1760](https://github.com/sanskarpan/Latexy/issues/1760); preserve every
  maintenance task, cadence and independently isolated execution. No plan
  purchase, disabled maintenance or production acceptance waiver is authorized.
- The in-app browser's template gallery fetch error is not an established
  application defect: navigating directly to the Modal API produced
  `net::ERR_BLOCKED_BY_CLIENT`, while independent HTTP catalog and CORS checks
  succeeded. Do not weaken CORS or disable client protection to mask this
  environment limitation. Authenticated and complete live UI QA remain open.
- A separate narrow dependency follow-up
  [#1759](https://github.com/sanskarpan/Latexy/issues/1759) tracks PyJWT advisory
  remediation and actual JWT boundary controls. Upstream vulnerable dependency
  behavior is not proof of a Latexy auth exploit: the migration-only application
  fallback uses a raw configured secret, HS256 only and mandatory expiry.
- The Quick Tailor close/reopen candidate was withdrawn after checking its
  actual workspace caller: closing unmounts the old modal, and the caller
  cannot replace its resume while it remains mounted. A deferred-start control
  passes for close A, open B, then resolve A. Synthetic same-instance prop
  replacement is not reported as a reachable product defect. This narrow
  control does not certify Apply or template-preview request lifetimes.
- Read-only tracing of CodeQL URL-import alert #12 found no production guard
  bypass. The API uses the default DNS-pinned client; actual private/scheme
  redirect regressions exercise that path. The injectable custom-client seam
  can omit the transport, but current non-test callers do not supply it. GitHub
  project metadata links are not fetched afterward. Keep the alert visible;
  this bounded call-site review is not a universal SSRF-completion claim.

## Next backend publication verification

- PyJWT is pinned to 2.15.1; production and development lock changes are
  restricted to its pin and hashes. The development input inherits the
  production input rather than duplicating a new direct pin.
- Independent root JWT/auth run: **18 passed** with ResourceWarning,
  RuntimeWarning and pytest unraisable warnings treated as errors. Controls
  cover empty JWKs, loader-accepted mutated PEMs, public JWK confusion, actual
  valid legacy tokens and missing/expired/wrong-key/other-algorithm rejection.
- Independent root Modal parity run: **27 passed**, with the same strict
  warning flags. Five schedule triggers retain seven maintenance tasks;
  equal-cadence triggers dispatch separate durable child calls with independent
  deadlines. Both siblings are attempted even when enqueue fails, followed by
  a sanitized failure signal. Exact per-function cadences/images/timeouts and
  executable first/second/both enqueue-failure controls are enforced. Modal's
  [invocation documentation](https://modal.com/docs/guide/function-invocation-methods)
  confirms spawned calls continue when their caller exits.
- Complete independent combined backend run: **4,238 passed / 5 skipped**,
  with all three strict warning flags and no warning suppression or diagnostic
  plugin. One existing Starlette test-client deprecation remains visible.
  Scoped Ruff and `uv pip check` pass. Log:
  `/tmp/latexy-backend-publication-full-root-2026-10-06.log`.
- Protected publication and exact-SHA backend deployment remain pending.
  Local acceptance is not proof that the new backend is deployed.

## Merged backend security checkpoint and retained-schedule investigation

- PR [#1761](https://github.com/sanskarpan/Latexy/pull/1761) merged through
  normal protected rebase at 10:26:36 UTC. Local and remote main are
  `56412bf6d3193da931960174d7e961ed7cf149d9`, with the validated source tree
  preserved. All required PR checks passed; no protection exception was needed.
- Canonical main CI
  [37449811043](https://github.com/sanskarpan/Latexy/actions/runs/37449811043)
  and exact-SHA Vercel verification
  [37450529395](https://github.com/sanskarpan/Latexy/actions/runs/37450529395)
  passed. The live deployment identity independently reports this main SHA.
  GitHub's PyJWT dependency alerts are resolved; the separately mitigated
  `braces` registry finding remains visible.
- Modal rollout
  [37450529413](https://github.com/sanskarpan/Latexy/actions/runs/37450529413)
  built the images and applied migrations, but deployment reported **six**
  scheduled functions despite **five** source declarations. The release remains
  `v49` at `8ff2124aa21338d8a97ae60dbec1962af4921609`. Issue #1760 was
  reopened; static parity success was not treated as deployment acceptance.
- Exact v49 source had four schedules, including `scheduled_health_check`.
  The new source changed that existing tag to an unscheduled runner. Pinned
  Modal 1.5.4 sends an absent schedule field while reusing an existing function
  ID. Retention of the old health schedule is the leading inference for the
  extra slot, not confirmed server behavior: function-level server metadata
  was unavailable through the inspected endpoint.
- The narrow repair uses a new unscheduled tag,
  `run_scheduled_health_check`, updates the five-minute fan-out and removes the
  old registration. All seven tasks and five trigger cadences are preserved.
  The SDK rebuilds the published tag map from current registrations, supporting
  retirement of the unreferenced old tag without changing rolling strategy.
  Independent offline SDK registration inspection confirms version 1.5.4,
  five schedules, new health tag present and old health tag absent. This does
  not certify the server's final deployed layout.
- Independent root affected parity/manifest suites: **109 passed**, all three
  strict warning flags; scoped Ruff passes. Log:
  `/tmp/latexy-retained-schedule-root-review-2026-10-06.log`.
  Protected publication and another exact-SHA live rollout remain required.
- Source review against the exact old backend does not establish complete
  feature compatibility: that revision lacks the newer APIs and macro archive
  fields. Macro-size constraints can reject old oversized writes, and quarantined
  actions appear empty to old code, although their JSON is archived without
  loss. Schema downgrade is not a safe workaround for this application rollout.
- Separate frontend issue
  [#1762](https://github.com/sanskarpan/Latexy/issues/1762) is browser-reproduced:
  an old template-create completion closes a reopened preview and navigates to
  the old result. Its caller/modal lifetime fix is not in this backend snapshot.
  The local frontend unit suite passes 990 tests; fresh browser and owner-change
  acceptance remains separate. No whole-product completion claim is made.

## Exact-main backend publication and preview-backfill failure

- PR [#1764](https://github.com/sanskarpan/Latexy/pull/1764) merged normally
  at 11:00:32 UTC. Main is `0578e606943eb201bd3c15478e14b8aca6857cc2`,
  source-identical to tested head `39aba191deb0b1b327f63347e002b15d4eeebb09`.
  Both PR CI runs and all 21 aggregated required contexts passed. Linear
  history, strict checks, administrator enforcement and conversation resolution
  remain enabled. The separate frontend QA source and unrelated local files
  were excluded.
- Canonical main CI
  [37453542668](https://github.com/sanskarpan/Latexy/actions/runs/37453542668)
  and Vercel certification
  [37454243605](https://github.com/sanskarpan/Latexy/actions/runs/37454243605)
  passed. Direct public deployment identity reports this exact SHA.
- Automatic Modal rollout
  [37454243521](https://github.com/sanskarpan/Latexy/actions/runs/37454243521)
  successfully migrated, published the rolling backend, and synchronized source
  templates. Independent Modal history shows **v50**, tagged with this exact
  SHA. The schedule-limit publication defect #1760 is resolved without dropping
  maintenance tasks, changing cadence, buying capacity or bypassing CI.
- Direct live `/health`, `/readyz` and `/jobs/health` checks pass. One synthetic
  anonymous job, `e8fe0fe0-1f50-42d3-a6fe-cb01f9e02964`, exercised submission,
  actual worker completion, result retrieval and download. The matching result
  and downloaded artifact contain one page and **15,604 bytes**, with
  `application/pdf` content type and `%PDF` magic. One fixed synthetic device
  fingerprint was used; no identity rotation, real user document, LLM or billing
  flow was exercised. This does not certify authenticated ownership recovery,
  quota metering, every compiler, or the entire product.
- The workflow nevertheless **failed** at preview backfill: **2 compiled,
  56 skipped, 3 failed**. Hindi Professional, Europecv and Polish CV RODO all
  report `fontspec`'s `cannot-use-pdftex` error. The batch generator hardcodes
  `pdflatex` regardless of source/compiler policy. This new verified defect is
  [#1765](https://github.com/sanskarpan/Latexy/issues/1765); preserve failure
  propagation while repairing engine selection. The workflow's subsequent
  health/catalog/asset steps were skipped, so their overall automated acceptance
  is not green despite the independent health and guest-PDF checks above.
- Failure log: `/tmp/latexy-main-modal-0578e606-failure-2026-10-06.log`.
  Synthetic artifact: `/tmp/latexy-production-acceptance-0578e606.scnFLh/resume.pdf`.
  Frontend preview-lifetime runtime controls and the recurring shared hydration
  defect remain separate work; no whole-goal completion claim is made.

The #1765 repair follows the same configured compiler policy as template-created
documents, including Europecv's closed English-locale preparation. It retains
two passes, the 60-second per-pass deadline, bounded diagnostics and failure
propagation. Root independently ran the four batch-generator regressions with
strict resource/runtime/unraisable warning flags: all passed. These fully mocked
tests use the existing offline infrastructure mode and do not flush Redis,
connect to a real database, invoke TeX or upload provider assets. They execute
the actual batch loop with repository Hindi, Polish and Europecv sources plus a
Latin control, verify each PDF/PNG upload and engine cleanup, and preserve failed
compilation as an error. Scoped Ruff and diff checks pass. Log:
`/tmp/latexy-template-backfill-compiler-root-2026-10-06.log`.
Actual Unicode asset compilation and a green protected-main rollout remain
required; the separate existing PNG-warning behavior is not certified by this
compiler repair.

## Subsequent isolated QA checkpoints

- Compiler-policy PR [#1766](https://github.com/sanskarpan/Latexy/pull/1766)
  merged at 11:26:26 UTC through normal protected rebase. Main is
  `1cb54c0b5d8f40b1f7773b7f2057084c166fd8d8`, source-identical to validated
  head `7a48e57880b7d98524894a5819e472a4262f11ee`. Both PR CI runs and all
  21 aggregated required contexts passed; branch protections remain enabled.
  Canonical main CI and actual asset-generation acceptance remain pending at
  this writing. The most recently verified live backend remains v50/0578e606.
- New [#1767](https://github.com/sanskarpan/Latexy/issues/1767) is independently
  reproduced in the actual batch loop with fully mocked infrastructure:
  a valid PDF plus an empty converter result or converter exception incorrectly
  reported success without a thumbnail. Root's red check reproduced both
  failures with the normal PDF/PNG control passing. The repair counts empty,
  conversion, image-save and PNG-upload failures as failed templates, retaining
  any uploaded PDF for the normal two-object retry. Existing complete pairs
  still skip regeneration. Root's final strict-warning offline suite passes
  **10 tests**, including the compiler regressions, partial-upload retry and
  complete-pair skip. Ruff and diff checks pass; no real TeX/provider/DB/Redis
  operation was used for these unit controls. Logs:
  `/tmp/latexy-template-png-false-success-root-red-2026-10-06.log` and
  `/tmp/latexy-template-png-integrity-root-final-2026-10-06.log`.
- The separate uncommitted frontend #1762 lifetime repair now has fresh isolated
  Node 22 production browser evidence: **11/11 passed with zero retries** for
  both close/reopen surfaces, stale 503/retry on both surfaces, an observed
  A→B→A session epoch and exact current-result navigation, plus ordinary
  preview/detail/use/Escape/backdrop/source/tags controls. A separate **2/2**
  production run includes deferred direct-card creation after unmount on both
  surfaces and the owner-epoch control. Both runs used port 5492, mocked APIs,
  disposable bundles and line reports; 5485 and unrelated services were retained.
  Final logs: `/tmp/latexy-template-preview-production-5492-final4.log` and
  `/tmp/latexy-template-preview-production-5492-final2.log`.
  Root review required real response/body/UI-completion barriers, reachable
  direct-card/navigation interactions and exact retry-result IDs. Passing these
  UI controls does not establish cancellation of server-created documents,
  cross-account dispatch safety while waiting for auth readiness, authenticated
  production acceptance, or a fix for the shared hydration defect.

## Completed publication checkpoint and continuing QA

- PR #1766's main `1cb54c0b5d8f40b1f7773b7f2057084c166fd8d8` passed
  canonical CI 37456414849, Vercel certification 37457109804 and the complete
  automatic Modal workflow 37457109763. Independent history reported v51 with
  that tag. All six previously missing Hindi/Europecv/Polish PDF and PNG assets
  returned 200 with the correct types. All three PDFs were rendered and visually
  inspected; this is not PDF/UA or every employer parser certification. #1765
  was closed after this acceptance, not after source review alone.
- Thumbnail-integrity PR #1768 merged to main
  `9ce682f60ebe3117c85a1610fb3463a72ac751cf`. Canonical CI 37458069402,
  automatic Modal 37458827239 and Vercel certification 37458827163 passed;
  independent live identities matched v52/9ce682f6. #1767 was closed with the
  regression and rollout boundaries recorded.
- Preview-lifetime PR #1769 merged normally to main
  `40e199abb2f0e9dae132ea435463027d14f8ebe9`, source-identical to tested head
  `96de1130661b853f256c26436e942cb08efbf3af`. All required contexts and both
  PR CI runs passed. Main CI 37459298989 and Vercel certification 37460001529
  passed, and the public deployment identity independently matched this SHA.
  Modal workflow 37460001501 **attempt 1 failed before migrations/deployment**
  because its canonical-CI lookup did not find the just-completed run. The same
  lookup subsequently returned that exact successful run; gated attempt 2
  completed every step and independently published v53/tag40e199ab. A transient
  lookup/event-timing failure is verified; GitHub's internal indexing mechanism
  is an inference. Reliability follow-up is #1775, not a waived provenance gate.
- Direct live health, readiness and worker health passed after v53 publication,
  as did all six affected Unicode asset requests. The public catalog contains
  61 rows, none missing PDF/thumbnail URLs; this does not independently fetch
  all 122 objects. Local and remote main matched, with linear history, strict
  required checks, administrator enforcement and conversation resolution enabled.
  Another worktree can start from this published checkpoint.
- The browser skill was used to inspect actual deployed public DOM. `/privacy`
  contains the conservative current-system disclosure; the four policy/domain
  guards pass independently. The current browser session still cannot fetch
  `/templates`, although the direct API returns 200 and the exact origin CORS
  header. Authenticated production flows are not certified; a safe non-admin QA
  sign-in was requested without requesting a password in chat. #1732 counsel
  review, #1731 tenant wildcard provisioning and #1683 exposed-account rotation
  were not inferred from source fixes or deployment.
- Live `/privacy` exposes a separate confirmed rendering defect: an indented
  Markdown list continuation becomes a paragraph. #1770 / PR #1774 preserve
  list semantics without changing legal wording. Root reviewed the four-line
  change and independently ran the actual React server-render regression plus
  policy/domain controls: five tests passed, as did scoped ESLint. The agent's
  non-incremental TypeScript check passed. Protected publication/live DOM
  acceptance for this follow-up remain pending at this writing.
- #1771 / PR #1773 repair the backfill's basic compiler invocation boundary:
  the old actual batch loop omitted a subprocess environment and engine guards,
  inheriting the function environment. All active DB templates are eligible,
  including admin-controlled source, so the boundary is not immutable repository
  files alone. No real secret-reading TeX or ordinary-user exploit was tested.
  Both passes now use the shared credential-filtered `engine_env()`, explicit
  flags and temporary working directory. Root's 18 strict-warning offline
  backfill/shared-environment controls pass, and the agent's actual Europecv
  compile passes in a disposable scrubbed environment. An expanded offline
  sandbox sweep had three worker-Redis-initialization failures; these are not
  counted as passing or evidence of this narrow fix's failure. PR #1773 merged
  normally to source-identical main `af81781fff0c4e58c472df7f56607ea879fb78c0`;
  canonical main CI and its exact deployment remain pending. Recorder generation
  alone does not certify the normal worker's complete read/isolation boundary.
- #1776 is a new synthetic browser-confirmed private draft boundary: an A title
  and imported source survive an in-place B session refresh and are submitted
  with B authorization. Two diagnostic controls pass on sealed pre-preview-fix
  production port 5485; current main retains the same unscoped form state. No
  real database write was made. Better Auth 1.6.25 has built-in storage messaging
  and focus/visibility refresh; sign-in need not broadcast immediately. The fix
  requires fresh-source proof, same-owner/error preservation and deferred-create
  isolation. The diagnostic assertion of bad behavior is not a passing safety
  regression and must not ship unchanged.
- #1772 now tracks the recurring React **error code** 418 (not GitHub issue
  #418). Historical zero-retry failure evidence remains unresolved; an async
  root headers/loading/provider interaction is still a hypothesis. Old temporary
  logs are unavailable, and narrowed CI success does not close this defect.
  Whole-product accessibility, native WebKit, authenticated production ownership,
  Upstash capacity instrumentation, publishing/payment/legal prerequisites and
  the broad remediation goal remain open.

### Later accepted follow-ups

- Main `af81781fff0c4e58c472df7f56607ea879fb78c0` subsequently passed canonical
  CI 37460958008, Vercel verification 37461683856 and complete Modal rollout
  37461683992. Independent history and public identity matched v54/af81781f.
  #1771 is accepted within the basic compiler-boundary scope above; existing
  asset pairs were preserved rather than deleted to force live compilation.
- Legal PR #1774 merged normally to main
  `dfc2ad4d95d3d0e185fdb3125054fd7ab3286800`, source-identical to tested head
  `1fbc8264d82cc487a78b404fa540e0fe0cf3c9e0`. All 21 required contexts passed.
  Canonical CI 37462103265, Vercel certification 37462865578 and complete Modal
  rollout 37462865681 passed. Independent identities match v55/dfc2ad4d, and
  the actual live privacy DOM exposes the full wrapped sentence as one list
  item. #1770 acceptance changes no legal wording or counsel-review status.
- Workflow-reliability PR #1777 merged normally to source-identical main
  `5f466798ba83ba91e78f7cbc8c9bf4924233a72d`, after both PR CI runs and all
  21 required contexts passed. Six bounded canonical-CI lookup attempts retain
  exact reachable-main, canonical workflow, SHA, main branch and success checks.
  Each request has a 20-second deadline and 5-second kill grace; five 5-second
  waits give approximately 175 seconds plus process overhead. API errors,
  malformed payloads and wrong/missing runs still fail closed. Root reviewed
  and independently passed 118 strict-warning executed-shell/parity/manifest
  controls, including immediate/delayed success, invalid shapes, mixed entries
  and ancestry rejection. This revision's main CI/deployment remain pending.
- The continuing #1776 owner-keyed form repair now passes root's combined
  frontend unit checkpoint: 157 files, 991 tests, plus non-incremental TypeScript.
  Fresh production draft controls initially pass four cases, but acceptance is
  being strengthened with exact navigation IDs, deferred success/rejection
  body/handler barriers and existing template-lifetime controls. It is not yet
  published or an authenticated production claim. Main publication readiness
  applies to the merged revisions above, not these uncommitted QA changes.

### Exact 5f466798 rollout and pending browser acceptance

- Canonical main CI 37463194119, Vercel verification 37463969659 and the
  complete automatic Modal workflow 37463969750 subsequently succeeded.
  Independent checks confirm public Vercel identity
  `5f466798ba83ba91e78f7cbc8c9bf4924233a72d` and Modal v56 tagged with that
  exact SHA. #1775 production acceptance is recorded. This rollout did not
  naturally reproduce delayed API visibility; the delayed/fail-closed cases
  remain executed-shell test evidence rather than a live-delay claim.
- A stronger fresh #1776 browser run passed six cases and failed one:
  same-owner refresh/reload emitted React hydration error code 418 despite
  correct draft retention/reset assertions. The page-error assertion remains
  enabled, and #1772 stays open. Response reader probes are being tightened to
  record completed JSON/text reads rather than just reader invocation.
- #1778 tracks a separately reproduced local-upload race: select A, clear it,
  select B, resolve B then A, and the old read overwrites the newer import.
  The sealed old-source run has three expected safety failures and three
  passing controls. Its desired-safety tests and generation/lifecycle repair
  are not yet accepted or published. Root source review caught a StrictMode
  effect replay regression in the pending repair before publication; the
  agent is correcting it before the combined fresh-source browser checkpoint.
