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
- Fresh strict-warning backend run found six failures. Investigation is active;
  old backend pass counts do not certify this run.
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

- Fresh frontend suite after the security follow-ups: 155 files / 988 tests
  pass. The previous sealed production bundle passes 25 owner-scoped browser
  regressions with zero retries; a fresh security-follow-up bundle is building.
- CI exposed clean-checkout gaps: the root placeholder-only production example
  was excluded by a global `.env.*` ignore rule, and the nginx log mount lacked
  a tracked directory placeholder. Narrow ignore exceptions preserve secrets
  and actual log exclusions while publishing these safe deployment inputs.
- Python lock validation now compares every pin, marker and hash while omitting
  platform-dependent provenance comments. It still seeds existing compatible
  pins and recompiles against both direct-dependency input files.
- The template extraction job needed `fonts-noto-core`, matching its actual
  Devanagari template and the production image. Local macOS does not supply
  Poppler; the complete extraction result must come from Linux CI.
- The browser-quality fixture mocked the wrong hard-coded backend host. API
  mocks now follow paths and resource types without swallowing page navigation.
  A successful background Better Auth refresh does not mark a retained session
  pending; the persona revalidation control now exercises an actual 503/error
  followed by recovery, instead of requiring incorrect optimistic-state behavior.
- Student checkout validates invalid academic addresses normally, but must not
  send a verification email when billing is unavailable. Independent review
  caught and corrected a proposed regression of that safeguard.
- Backend database ownership remains an active strict-warning blocker. Recent
  runs reduced the failures, but an unclosed asyncpg connection remains; neither
  focused green tests nor suppressing warnings is acceptable certification.

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
- Decode extension entities in one pass and recognize whitespace before script
  and style closing brackets (five extension tests pass).
- Remove raw cache-key diagnostics and neutralize control characters at
  application loggers even when workers use plain-text handlers. Existing
  structured JSON logging remains a separate defense.
- Harden the four flagged regex sites with possessive matching / whitespace
  boundaries and add adversarial input regressions with process deadlines.
- Critical SSRF findings need evidence-based review of existing fixed-origin,
  encoded-path, redirect-disabled provider requests and the default DNS-pinned
  public-URL transport. Do not dismiss merely because an initial validation
  function exists. Remaining scan results stay visible for follow-up.

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
