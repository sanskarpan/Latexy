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

### Reviewed draft and local-read acceptance checkpoint

- The corrected frozen owner and uploader sources passed a single fresh
  Node22 production build on isolated ports 5493/7493: **13 browser cases
  passed with zero retries**, recorded in
  `/tmp/latexy-publication-5493-final-bodyprobe2.log`. This combined snapshot
  contains both pending repairs; their PRs will retain separate source/test
  scopes. Five owner cases cover confirmed A/B/ABA changes, exact fresh-B
  navigation, deferred success/rejection and same-owner refresh/error/reload.
  Six upload cases cover both completion orders, clear-only, stale rejection,
  unmount/remount and ordinary import. Two existing template lifetime cases
  also pass. All page-error assertions remain enabled.
- JSON/text probes now record completed body reads before the two-frame
  handler barrier. Same-owner assertions also wait for completed session-body
  reads, not just intercepted request entry. Root independently reviewed the
  test log and matching source hashes, passed all 157 frontend unit files / 991
  tests, scoped ESLint, non-incremental TypeScript and diff checks. The uploader
  effect explicitly restores mounted ownership during every setup; production
  remount acceptance is not a claim of an executed development StrictMode test.
- React error code 418 did not recur in this checkpoint. Earlier fresh failure
  evidence remains valid and #1772 is not closed by an intermittent clean run.
  Neither owner nor uploader acceptance here implies authenticated live QA.

### Owner publication and continued QA

- Owner/draft PR #1779 merged normally after all 21 required contexts passed,
  clean mergeability and no unresolved review threads, to source-identical main
  `6e4de96976ecaf1efa3de8c8b39790ea534919fd`. Canonical main CI 37467253098,
  Vercel verification 37467962504 and every step of automatic Modal rollout
  37467962473 succeeded. Independent history and public identity confirm
  Modal v57 and Vercel at that exact SHA. The local main pointer is updated;
  another worktree can consume this published owner boundary.
- Uploader PR #1780 contains only its component and six-case safety file,
  individually committed. Its branch was updated normally against the new
  main, retaining strict fresh-head CI; acceptance/merge remain pending here.
- #1781 is a newly verified ordinary theme-toggle race. A delayed initial
  account preference GET reverses a newer visible toggle, despite the mocked
  preference PATCH containing the user's selected mode. Three sealed-source
  diagnostics/control cases reproduced it. The desired-safety expansion has
  three expected old-source failures and two passing controls, including ABA
  owner and multiple-toggle cases. A narrow owner/request/choice-epoch repair
  is under review; negative assertions need completed-body barriers before
  fresh-source acceptance. No real database/provider write was made.
- A separate sealed-source hydration diagnostic reproduced React code 418
  during reload, but structural churn/React stack alone does not establish
  causality. The installed Next App Router aliases both browser and server to
  its vendored React canary runtime: package React 18 paths or stale `.next`
  references do not prove a runtime mismatch. Diagnostic-only files are kept
  out of accepted PRs; a diagnostic that records errors is not a safety pass.

### Uploader publication and deployed-asset synthetic coverage

- Uploader PR #1780 was updated normally against owner-fix main and passed all
  21 current required contexts at head
  `8117003f2c81e10dad1972e0d098d4810bd2a260`. Clean mergeability and no unresolved
  threads were checked before a normal protected rebase merge. Main is
  `f647c16988a1d22455ff3b56c5e3e88d91400117`, source-identical for both uploader
  files. Main CI 37469041048, Vercel verification 37469837538 and every step of
  automatic Modal rollout 37469837522 passed. Independent identities confirm
  Vercel at that SHA and Modal v58. Local main and origin/main match; branch
  protections remain strict, linear, administrator-enforced and conversation-
  resolving. The reviewed owner and uploader repairs are now on main.
- A separate **11-case, zero-retry production-frontend synthetic run** passed
  against actual `https://latexy.xyz` assets, with that same SHA before and
  after. Five owner/session and six upload-order/lifetime cases kept page-error
  assertions enabled and empty. The disposable fixture blocks unmatched API,
  external and non-GET traffic, while explicit synthetic auth/API fixtures
  satisfy the tested flows. No real resume/auth/provider/database write occurred.
  Root reviewed `/tmp/latexy-production-owner-upload-qa-stub-f647c169.log`.
- Initial live synthetic cases had correct functional assertions but failed
  their page-error gates because Playwright's `serviceWorkers: block` replaces
  `register()` with an async function returning undefined. Root independently
  confirmed this in installed Playwright source and the live Workbox chunk's
  subsequent `registration.waiting` access. A faithful registration dependency
  mock exists only in the disposable test fixture; the error was not filtered
  or waived. This does **not** certify real PWA installation/update/offline
  lifecycle, real authentication or database integration, or the actual API
  origin/CORS path. Public gallery fetch coverage is a separate pending check.
- The next theme acceptance snapshot also corrects the existing owner test's
  entitlement endpoint to `/config/entitlements` and mocks tenant resolution,
  avoiding misleading ancillary HTTP failures. This test-only improvement
  changes no owner assertion or application behavior. The theme source and
  completed-body six-case safety fixture remain pending fresh-source proof.

### Theme repair fresh-source acceptance

- The completed-body fixture now has six desired-safety cases. Sealed old
  source failed three race assertions and passed three controls. The repair
  guards preference application by owner epoch, request generation, local
  choice generation and mounted lifetime. Owner epochs distinguish A→B→A;
  synchronous choice invalidation prevents a delayed GET from undoing a toggle.
- A freshly built Node 22 production snapshot passed all **20 cases**, Chromium,
  one worker and zero retries: five owner/draft, six uploader, six theme, two
  template lifetime and one high-contrast reload control. Root independently
  read `/tmp/latexy-publication-5493-combined.log` and matched the reviewed
  source/fixture hashes. Page-error assertions were retained without waivers.
  Theme negative assertions wait for actual response body consumption and two
  animation frames; the ABA control also requires the fresh A theme to apply.
- Exact final files passed scoped ESLint, full nonincremental TypeScript and
  all **157 unit-test files / 991 tests**. Only application theme code, its
  six-case safety fixture, the ancillary owner-test route correction and this
  publication record are selected for publication, each separately committed.
  Diagnostic-only hydration output and unrelated user/generated files are
  excluded. #1772 remains open: one clean run does not establish its cause.
- This acceptance uses synthetic sessions/API responses and does not certify
  real authenticated database writes, a development StrictMode execution or
  real service-worker lifecycle. Protected PR and rollout acceptance follow
  separately; passing local tests alone is not deployed acceptance.
- A separate anonymous browser read passed on stable f647c169 production:
  61 live template cards, search narrowing to Postdoc, live detail and PDF
  preview. Browser catalog/categories/detail returned 200 with the actual
  frontend origin allowed by CORS; the allowlisted PDF endpoint redirected to
  its exact signed R2 object, which returned 200. Root reviewed the disposable
  read-only harness and `/tmp/latexy-production-public-gallery-f647-clean.log`.
  No page errors occurred. Telemetry writes were blocked intentionally; aborted
  prefetch requests were recorded, not asserted away. The earlier public-gallery
  fetch ambiguity is resolved for these reads, not for authenticated writes,
  every public object or real PWA lifecycle.

### Theme publication and next confirmed owner-boundary findings

- Theme PR #1782 passed all 21 required current-head contexts at
  `faeaf456d70fc38d8554826818cf7fb99584eb27`, clean mergeability and no unresolved
  threads. Normal protected rebase merge produced main
  `d54e0f6352afedb50ae6cde079971fd4410d415b`; root compared all four selected
  files with the tested head and found no differences. Local main is updated.
  Main CI 37472086418 and automatic deployment acceptance remain in progress
  at this checkpoint; no production theme acceptance is claimed yet.
- #1783 is a **verified P1 personal-dictionary isolation defect**, not merely
  a source candidate. Two ordinary same-origin A-load → B-session/reload runs
  showed A's word in B's dictionary and an authenticated B preference PATCH
  containing it. B's own word visibly loaded, establishing application of B's
  dictionary response. The desired-safety assertion failed; ordinary add/remove
  passed, with no page errors. Root confirmed both relevant sealed source
  hashes match current main and read
  `/tmp/latexy-dictionary-owner-5485-red.log`. All auth/API bodies were synthetic;
  no real private data, credential or database write was used. Account-scoped
  cache and guarded synchronization are now authorized for repair.
- The linked-variant deferred-error candidate is also behaviorally confirmed:
  B's variant title loaded, then A's delayed failure created an A-specific toast.
  Ordinary deferred save passed and the tested ABA stale-success control passed;
  no stale-success corruption or backend authorization breach is inferred.
  Root matched sealed/current source hashes and read
  `/tmp/latexy-linked-variant-owner-race-rejection-5485-v5.log`. A focused issue
  and owner/lifetime callback repair are being tracked separately.
- Remaining survey candidates: Settings interactive preference/integration
  writes, retained passkey/security state, and unscoped onboarding completion.
  Passkey diagnostics show a stale A row but need a stronger observable B
  identity-application barrier before acceptance. These are not all confirmed
  bugs. New Resume, guided-builder owner and builder-document flows already
  have explicit source guards and behavioral coverage; do not regress them.
- Theme rollout is now accepted: main CI 37472086418, Vercel verification
  37472964248 and every step of automatic Modal rollout 37472964115 succeeded.
  Independent public identity is exact d54e0f63 and Modal history is v59 tagged
  that full SHA. Root ran the six theme cases on actual deployed frontend assets:
  **6 passed, zero retries**, with enabled/empty page-error gates and exact
  identity before/after. Artifact `/tmp/latexy-production-theme-d54e0f63.log`.
  The fail-closed synthetic API/auth fixture and explicit service-worker
  registration dependency mock remain the stated acceptance boundary.
- Linked-variant stale-error repair is tracked in #1784. Stronger passkey proof
  is accepted as **P1 #1785**: B's bearer-authenticated GitHub status request and
  visible `BobGitHub` precede A's fully consumed passkey response. The stale A
  row remains and B never reloads its list. Ordinary list passed; desired-safety
  case failed without page errors. Root matched sealed/current component hashes
  and reviewed `/tmp/latexy-settings-passkey-owner-race-5485-final-confirmed-red.log`.
  Broader actual MFA secret exposure or backend authorization failure is not
  asserted. Owner-private security state resets and async guards are under review.
- Root review caught additional implementation regressions before acceptance:
  stale copied dictionary display/entry state, unmounted dictionary sync,
  auth-ready dispatch retargeting, and a variant owner-epoch spinner masking
  load errors. Repairs require positive controls for these alongside old-source
  race failures. No new dictionary, variant or security repair is accepted or
  published merely because it has been implemented by an agent.

### Dictionary, variant and security repair verification checkpoint

- Root reviewed the scoped implementations and API dispatch boundary, then
  ran scoped ESLint, full nonincremental TypeScript and the complete unit suite:
  **158 files / 1,004 tests passed**. Artifact
  `/tmp/latexy-1783-1785-root-unit-final.log`. The obsolete linked-variant
  source-text assertion was updated to check the actual stronger mounted,
  owner, epoch, resume and generation guard; newer-edit assertions remain.
- #1783 now scopes cache keys and synchronization to account identity, retains
  ownerless legacy words for anonymous reads only, and rejects stale owner/token
  dispatch after the auth-ready wait. Local edits/removals during synchronization
  and stale-dispatch retry have focused runtime coverage. Dictionary load/PATCH
  failures expose a generic unsynchronized-local-state notice, not private terms.
  Historical server-side words of unknown provenance are not automatically
  deleted or attributed to an account.
- #1784 adds guarded load/save callbacks and preserves same-owner token-refresh
  and transient-error drafts. A load-failure Retry control protects against the
  owner-epoch loading gate hiding errors indefinitely. This does not claim a
  global queued-mutation dispatch repair for unrelated API calls.
- #1785 now has stronger MFA evidence in addition to the passkey proof: with B
  visibly applied, releasing and consuming A's synthetic enable response on the
  sealed old build displayed one A setup URI and one A backup-code element.
  The desired-safety assertion failed; ordinary synthetic setup passed. Root
  independently read
  `/tmp/latexy-settings-passkey-owner-isolation-5485-mfa-owner-red-final.log`
  and its body-reader positive control. This is simulated UI exposure, not a
  finding that real credentials or server authorization were compromised.
- New dictionary, variant and security fixtures fail closed for unmatched API,
  external and non-GET traffic. A fresh isolated Node 22 production snapshot is
  being tested on 5495/7495 with one worker and zero retries; acceptance and
  focused protected publication follow separately. No fresh browser or deployed
  acceptance is claimed at this checkpoint. Hydration #1772 remains open.

### Fresh browser acceptance and additional verified gaps

- Root independently read the fresh production logs and reviewed pre/post
  application and fixture hashes. Earlier regressions passed **20/20** in
  `/tmp/latexy-publication-5495-combined-final.log`. Its selection filter
  accidentally excluded the added suites; this is retained as a 20-case run,
  not described as a 46-case combined execution. A separately built isolated
  snapshot with unchanged application hashes then passed all **26/26** added
  cases in `/tmp/latexy-publication-5495-new26.log`: ten variant races, one
  existing occurrence-safe visibility control, seven dictionary controls and
  eight security controls. Both runs used one worker and zero retries.
- The 24 new dictionary/security/variant cases retain enabled page-error
  assertions; the two older ordinary dictionary/visibility controls do not
  have that gate. The older dictionary fixture's unmocked referral handler
  logged an unused local backend-port refusal. This is recorded, not dismissed
  as a successful real-backend check. All new fixtures fail closed. The final
  security fixture additionally checks same-owner private draft preservation
  and visible B identity before releasing the deferred A MFA response.
- Root repeated the strengthened two-case security old-build proof: the
  same-owner private draft control passed and the stale synthetic URI/code
  safety assertion failed. Artifact
  `/tmp/latexy-security-final-bodybarrier-red.log`. No real secret was used.
- Complete Node 22 unit validation also passed **158 files / 1,004 tests**
  (`/tmp/latexy-1783-1785-root-node22-unit-final.log`), and full frontend lint
  passed. A new, separately owned notification diagnostic introduced one
  nullable-header TypeScript error; it is being corrected before a fresh type
  gate. It is not a pre-existing application error or part of these repairs.
- #1786 is now a verified Settings notification-save UI race. With B bearer
  identity, B notification body and B false switch applied, A's delayed PUT
  success or error changes B's switch to true. Ordinary success/error controls
  pass. Root matched the unchanged Settings source to the sealed baseline and
  reviewed `/tmp/latexy-settings-preferences-owner-race-5485-final.log` plus
  its page-error-gated and ABA follow-ups. No real preference writes occurred.
- #1787 is an offline-confirmed public trial metadata policy gap. The real
  model, route and service accepted 5 KiB, excessive nesting and synthetic
  credential-like keys unchanged into a fake analytics row; existing analytics
  rejects those oversized/deep shapes and redacts sensitive keys. Root reviewed
  four passing evidence controls and `/tmp/latexy-public-trial-input-bounds.log`.
  This demonstrates validation/privacy inconsistency and potential storage
  amplification, not a measured production attack. A shared bounded policy is
  authorized for repair; no actual DB, Redis, provider or network was accessed.
- Protected publication and exact-main live acceptance of #1783–#1785 remain
  pending. Latest independently read production identity is still d54e0f63;
  backend health/readiness are healthy. Operator Redis capacity monitoring is
  still unconfigured and is not certified by ordinary connectivity health.

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
