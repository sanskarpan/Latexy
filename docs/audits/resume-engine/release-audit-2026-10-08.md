# Resume engine continuation audit — October 8, 2026

The owner authorized continuation after reviewing the newer commits on draft
[PR #1833](https://github.com/sanskarpan/Latexy/pull/1833). This dated audit
supersedes the outstanding-status lists in the historical checkpoint and handoff;
it does not erase their failed runs or claim production acceptance.

## Source and review

Remote engine head `20ae2039141bcd3d8a795294bae53686538859bc` was fetched and
reviewed before implementation. The engine branch was rebased onto current main
`bdee48926ce0e2e6c9c5e2b281d2ab07c4355b98`, preserving upstream OAuth migration
0059 and its route/query changes. Engine migrations remain 0060–0064.

Three independent reviewers checked semantic ownership/recovery, renderer
confinement/cache/retention, and frontend preview/account behavior. Findings were
checked against concrete reproduction tests before repairs were accepted.

- [Semantic review](semantic-audit-2026-10-08.md): stale identity-map writes,
  expired import staging limits, and unkeyed private durable replay identities.
- [Renderer review](renderer-audit-2026-10-08.md): expired cache admission,
  reused-session deadlines, retained aggregate export buffers, geometry inspection
  and configured immutable certification identities.
- [Frontend review](frontend-review-2026-10-08.md): acknowledged cancellation,
  late guest field responses across account changes, and original PDF attachment
  visibility before effect cleanup.

An additional timestamp-boundary test reproduced invalid artifact retention when
creation and expiry sampled the clock separately. Both user/guest cases failed
before the fix. Creation is now sampled once and expiry derived from it. The
focused artifact suite passed 21 cases; five database finalization cases were
explicitly deselected in that pure run, not represented as passes.

## Recorded validation

- Frozen local full backend at `01a0ad7e`, backend tree
  `966d97a5aeae87dcb7ea2e85bb7ed368de8672cd`: **4,848 passed, two failed, eight
  skipped**, 1,563.64 seconds. Real isolated PostgreSQL and Redis were enabled;
  source was extracted from Git to a Linux volume, not a changing worktree.
  The two failures were unchanged eight-second child-process deadlines in
  `test_publication_regex_regressions.py` (`authors`, `bibtex`). Preserve this
  result even if a later serial rerun passes. An unchanged serial recheck at
  backend `3d556b87` still failed both eight-second child-process deadlines;
  it passed the remaining metrics case. Another unchanged recheck at final
  backend `e77df27e` had the same two failures and one pass in 55.28 seconds.
  A separate diagnostic measured the authors module import at **13.950 s**
  and its 100,000-space malformed match at **0.010 s**. This diagnoses startup
  contention for that case; it does not turn the failed process test green,
  change its deadline or establish the BibTeX case's isolated timing. A prior
  faulthandler diagnostic crashed during settings import and is not acceptance
  evidence. This frozen full run preceded the
  timestamp repair, frontend repair and subsequent provider/template changes.
- Real private RustFS/PostgreSQL/Redis integration at backend `cd6f95b8`:
  **three passed**, 150.25 seconds. Immutable write conflict checks, authenticated
  and guest preview/export/SyncTeX/geometry, candidate export rejection, exact
  cache reuse and guest ownership were exercised. The first harness invocation
  omitted `TEST_REDIS_URL` and failed infrastructure setup; the corrected run used
  its own Redis databases 13/12. Neither run touched development Redis.
- Frontend checkpoint `3d556b87`: **1,162 unit tests across 182 files**, full
  TypeScript/ESLint, complete 40-page production standalone build and its artifact
  validator, and **nine production Chromium contracts with zero retries** passed.
  Browser contracts mock API/auth/stream responses and cannot certify live model
  quality or deployment latency.
- GitHub checks at `cd6f95b8` passed backend tests/lint, frontend build/lint,
  template extraction, deployment parity, full-stack smoke, observability/privacy
  smoke and CodeQL. The previous two hashing findings cleared without suppression.
  Check acceptance must be read again for the final published head.

- Provider/worker follow-up at frozen backend tree
  `afca6ba3fe9e1c607874928a56b09d32a8599864`: **138 passed**, no failures/skips,
  341.26 seconds, real isolated PostgreSQL/Redis and enabled preflight. This
  covers native provider framing/usage/watchdogs, exact owner/key/model admission,
  durable recovery, quota regressions and native-import preparation. The first
  combined run passed 137 and failed a malformed non-UUID ownership fixture;
  the corrected fixture persists a distinct user. [Provider details](provider-integration-2026-10-08.md)
  and [worker details](worker-preparation-2026-10-08.md).
- Provider UI: full TypeScript and zero-warning ESLint passed; **eight focused
  tests across three files** passed in 15.06 seconds. The production build and
  changed browser contract must be accepted separately from the previous bundle.
- Complete frontend unit run at UI source `15540528`: **1,170 passed across 185
  files**, no failures/skips, 331.05 seconds, one worker, Linux Node 22.23.3 and
  frozen pnpm dependencies. [Counts and raw-report hash](frontend-unit-summary-2026-10-08.json).
  These include the eight focused provider cases and are not additional unique
  tests to add to the earlier 1,162-case checkpoint.

The first new production build compiled and passed its static checks, then failed
page collection because the QA command omitted the production HTTPS auth origin
required by passkeys. The corrected QA command uses an inert HTTPS `.example.test`
origin and preserves the product requirement. The failed build is retained locally;
its partial compilation is not reported as a complete build.

Counts, failed/skipped node IDs and SHA-256 hashes for full, serial, real-storage,
bookmark and provider runs are preserved in [machine-readable test evidence](local-test-summary-2026-10-08.json).
Raw JUnit captured logs remain local; the portable summary script excludes those
logs and preserves failures without committing credentials or user-like content.

These suites overlap. Their counts must not be added into a unique-test total.

## Performance evidence and harness boundaries

The direct-worker benchmark used actual TeX, Redis Lua ownership, PostgreSQL,
private immutable S3 objects, geometry and durable finalization. Each condition
has 30 measured samples, alternating fresh and exact-cache requests after excluded
warmups. HTTP admission, Celery queueing, AI, browser paint and cold image startup
are excluded. Phase intervals overlap and cannot be summed as total latency.

The default managed-English LuaLaTeX run at `01a0ad7e`, image
`latexy-engine-qa:20261007-v2` (`df9a8c1332fb`), was explicitly **contended**:

| Condition | Median | p95 | Samples |
| --- | ---: | ---: | ---: |
| Fresh managed Lua PDF | 9.566 s | 13.844 s | 30 |
| Exact-cache direct-worker reuse | 1.643 s | 2.213 s | 30 |

Fresh TeX process time had a 7.162-second median; all measured fresh renders used
two passes. Event publication and output drain were millisecond-scale. These
numbers do not satisfy the one-second fresh-PDF target or the 500-ms browser
cached-paint target. A separate pdfLaTeX baseline uses a different fixture and is
not a paired claim of improvement for default LuaLaTeX.

The subsequent managed-English run at backend `e77df27e` (tree
`afca6ba3fe9e1c607874928a56b09d32a8599864`) completed another 30 fresh/cache
pairs. All 30 fresh samples used **one pass**. Fresh p50/p95 were **10.115/20.140 s**;
cache p50/p95 were **1.979/4.439 s**. The changed preamble is one-pass, but this
more contended run does not establish a wall-time improvement. An exact within-
compiler two-pair text/link/pixel/geometry/SyncTeX comparison is separately
recorded in [bookmark evidence](managed-bookmarks-2026-10-08.md). Private v2
pdfLaTeX format parity passed; the old QA image's v1 format is not selected for v2
source. The ordinary safe path remains available.

Raw 30-pair reports: [default Lua baseline](render-pipeline-managed-lua-2026-10-08.json),
[one-pass Lua](render-pipeline-managed-lua-onepass-2026-10-08.json) and
[separate pdfLaTeX baseline](render-pipeline-pdflatex-2026-10-08.json).
The one-pass CLI initially labeled the renderer-change commit `da8892fa`; the
committed report adds exact frozen-tree provenance matching backend `e77df27e`.

The first live guest browser attempt started before the restarted QA API became
ready and failed without admission. The next attempt reached projection, field
PATCH and job admission but timed out without a PDF. Its worker hit the unchanged
time limit while importing `cache_policy.py` from the Windows bind mount, before
starting TeX. Both failures are retained in separate dated directories. The
isolated API/worker were subsequently moved to a frozen Linux source volume;
this corrects the harness transport without weakening compile limits or recording
a failed attempt as a successful render.

The first Linux-volume real job also failed before TeX: a Celery deadline
interrupted the first native `asyncpg` import. The worker now prepares imports
before prefork readiness; a new isolated worker reached readiness normally.
Separate `linux`, `linux-ready` and `linux-functional` browser reports preserve
startup/readiness failures and the admitted cold-worker failure. The benchmark
now performs API readiness checks outside the user-action timer. It cannot count
startup rejection as a successful render or bypass guest cooldowns.

The initial direct-worker storage attempt also detected that the new test database
had been pointed at an existing database-bound bucket. The immutable binding
correctly rejected it. A separate private test bucket was created for the new
database; no binding was removed or bypassed.

## Release gates

The work remains isolated on `codex/resume-engine`; all accepted source,
regressions, portable reproduction scripts and dated evidence are committed.
Operator-configured immutable Modal image/asset identity, actual default Lua
multilingual and isolation acceptance, live paid-provider quality, controlled
regional/burst/cold/action-to-paint distributions, and combined billing-release
verification remain distinct gates. Local or mocked proof must not open the broad
Modal Lua capability, promise the latency targets, deploy a production schema,
merge the draft or close the migration epic.

Final-head verification and the subsequent provider/template results will be
recorded below after their checks finish.

## Final local production and first-task checks

The corrected production build completed all **40 static pages**, full
lint/type validation, standalone tracing and the build-artifact validator.
All **nine production Chromium contracts passed with zero retries**, 75.21 seconds,
against that actual bundle. This includes the changed two-model Anthropic choice,
admission body, authoritative decisions, import, cancellation/account recovery,
structure and keyboard/mobile interaction. API/auth/streams are mocked for these
contracts. [Build/browser counts and hashes](frontend-production-summary-2026-10-08.json).

The real guest probe then saved a field through the actual API, Redis quota,
prefork worker, TeX, PostgreSQL and private S3 path. It was the prepared worker's
first real task, job `3375626e-1444-48be-b57b-4206e97da162`; logs identify
**pdfLaTeX**. Ordinary guest admission returned 200; no quota reset/bypass or
deadline extension was used. Worker finalization succeeded. Verified binary
preview reached paint, seven conservative field overlays were exposed, and
keyboard/mobile field selection passed. No browser runtime/console errors were
recorded. [Full dated probe](browser-2026-10-08-prepared-worker/preview-browser-benchmark.json).

Save-to-paint was **22,367.4 ms**, verified-blob-to-paint **647.7 ms**. This is
one uncontrolled, contended first-task functional sample, not a distribution or
an exact-cache paint sample. It verifies the native-import repair and end-to-end
behavior, not the one-second fresh or 500-ms cached-paint target. Previous failed
attempts remain committed in their separate directories.

The actual standalone runtime served `/icon.svg`, `/favicon.ico`,
`/icons/apple-touch-icon.png` and `/sw.js` with HTTP 200. The shared new brand mark
is inline SVG, so it has no external image URL to fail loading. These specific
runtime asset checks are recorded in the production summary; they are not a
claim that every unrelated remote image was exercised.

## Current source checkpoints

- `da8892fa`: owned managed-English bookmarks disabled, format ID v2, real parity
  probe and dated Lua/pdfLaTeX evidence.
- `d29beec2`: explicit bounded provider integration and regression fixtures.
- `e77df27e`: prefork/Modal native-module preparation and readiness failure checks.
- `15540528`: account-scoped provider/model UI and actual admission contracts.
- `2b5621f7`: local API readiness required before guest latency timing.

The fresh isolated API/worker use backend tree
`afca6ba3fe9e1c607874928a56b09d32a8599864`, exactly `e77df27e:backend`.
Linux UI component, hook, API client, types and changed browser-contract SHA-256
values were compared against the worktree before production verification.
Main was refetched at `bdee48926ce0e2e6c9c5e2b281d2ab07c4355b98`; it remains an
ancestor of this branch. The earlier published rebase used an explicit lease
against `20ae2039141bcd3d8a795294bae53686538859bc`; newer follow-ups are ordinary
branch commits. No concurrent remote commits were overwritten.

First-task acceptance is tracked by [#1862](https://github.com/sanskarpan/Latexy/issues/1862).
The epic and its individual acceptance issues remain open.
