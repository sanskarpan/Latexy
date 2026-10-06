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
  is applying production migrations before deployment. Backend production
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
