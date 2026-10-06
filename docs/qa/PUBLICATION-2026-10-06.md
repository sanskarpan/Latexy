# Accumulated remediation publication — October 6, 2026

The user requested that all accumulated task work be merged into `main` so
another worktree can start from the current implementation. This supersedes
the earlier instruction to defer commits and publication. Integration issue:
[#1750](https://github.com/sanskarpan/Latexy/issues/1750).

## Snapshot and safety

- Starting branch: `fix/redis-resource-lifecycle`, at `7cf484cb`.
- Starting remote main: `8ff2124aa21338d8a97ae60dbec1962af4921609`.
- Preserve the 37 existing unpublished commits and create individual-file
  commits for accumulated source, test, documentation and configuration work.
- Exclude the unrelated untracked `.github/workflows/ci-cd.yml` and `test.txt`.
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

## Acceptance boundary

Publication is not a claim that the ongoing whole-product goal is complete.
Unproven hydration hypotheses, remaining owner-race surveys, native macOS
WebKit startup, operator-controlled credentials/capacity/payment policy and
production authenticated QA remain separately tracked. A successful build or
merge is not proof of the exact deployed SHA or all live product behavior.

Record the integration PR, successful checks, merged main SHA and deployment
results here as they become available. Until then, do not claim merge or live
certification.
