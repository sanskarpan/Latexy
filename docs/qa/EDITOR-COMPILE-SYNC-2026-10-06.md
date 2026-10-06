# Editor compile cadence and source–PDF synchronization

User-requested work, 6 October 2026. LLM optimization is explicitly out of scope.

## Tracking and acceptance

| Item | Issue | Current status |
| --- | --- | --- |
| Coalesced automatic compilation and busy-buffer retention | #1809 | Root-reviewed; native and dependency-free production-bundle browser contracts passed; protected PR checks pending |
| Correct SyncTeX parsing/coordinates, modifier clicks and divider arrows | #1810 | Root-reviewed; native and dependency-free production-bundle browser contracts passed; protected PR checks pending |
| Intact keyboard input before collaboration binds | #1812 | Real-timer baseline failure retained; exact source/payload assertions passed after repair |
| Component-scoped CI | #1801 / PR #1803 | Merged to main `fc8d947b`; canonical CI, Vercel certification and Modal deployment succeeded |
| Dependency audit evidence | #1807 / PR #1811 | Integrated through PR #1803; no advisory waiver; sanitized GitHub artifact verified |

The editor candidates are not deployed yet. Publication acceptance is pending
protected PR checks. The CI/audit integration
is merged and deployed, independently of these editor changes.

## Findings and intended behavior

- The existing Monaco editor already uses a **two-second trailing debounce**;
  it does not submit once per character. Backend limits count HTTP requests,
  not letters: the default bucket is 60/minute and 1,000/hour, with a separate
  lightweight-background bucket. Removing server abuse protections is not the
  repair.
- Busy page callers remove the compile callback. An edit during a running job
  can therefore lose its pending compile. The new policy waits for **five
  seconds of quiet** and at least **ten seconds between automatic submissions**,
  coalesces to the latest buffer, retains busy edits, and acknowledges matching
  manual submissions. Disposal, document changes, readonly state and async
  settlement must not dispatch stale content.
- The old SyncTeX parser expects colon-separated coordinates/dimensions instead
  of actual native TeX comma-separated records. It also estimates page height
  from the largest text Y position. Actual PDF page heights, native box
  height/depth, source-file identity and async artifact ownership are required.
- Ordinary caret movement/PDF selection must not scroll the other pane. Explicit
  divider arrows, Ctrl/Cmd-click and PDF double-click reveal and temporarily
  highlight the corresponding location without route navigation. Repeating an
  action on the same location must work. Missing/unsupported mappings disable
  the actions honestly. Resizing and normal selection remain available.
- On macOS, Control-click can emit a context-menu event rather than a normal
  click. PDF modifier navigation must use mouse-down instead of depending only
  on `onClick`, while normal click remains selection-only.
- Before Y.js binds, the existing collaborative editor can replay stale parent
  values through `model.setValue`, resetting the caret and corrupting native
  rapid typing. The guard distinguishes pending local echoes from external
  source replacements, prunes superseded echoes, and rejects old effect closures.
- A completed replacement job can expose its SyncTeX before its PDF finishes
  downloading. Keep the visible PDF and rendered job identity paired until the
  replacement blob is adopted. `/try` also invalidates stale downloads on reset
  or owner changes and separates PDF download lifetime from source-dependent ATS
  refreshes. Ordinary typing must not restart a completed PDF download.

## Primary research

- [Overleaf compile options](https://docs.overleaf.com/getting-started/recompiling-your-project):
  auto compilation happens every few seconds. This does **not** establish a
  universal exact five- or ten-second industry standard; those are the chosen
  quiet/cadence policy for Latexy.
- [Overleaf source–PDF navigation](https://docs.overleaf.com/navigating-in-the-editor/working-with-the-pdf-viewer/moving-between-the-editor-and-pdf):
  divider arrows and PDF double-click use SyncTeX; mappings are line-level and
  can be inaccurate when source changes after compilation.
- [Upstream SyncTeX parser API](https://github.com/jlaurens/synctex/blob/main/synctex_parser.h)
  and native `synctex view/edit` provide the coordinate oracle.

## Independently retained evidence

- Root generated a real native PDF/SyncTeX pair from
  `frontend/e2e/fixtures/compile-sync/resume.tex` using local pdfTeX,
  `-no-shell-escape -halt-on-error -synctex=1`. Outputs are isolated in
  `/tmp/latexy-editor-native-oracle-20261006/`; no provider or production DB was
  contacted. Native forward lookup for source line 3 gives page 1,
  `x=169.689255`, top-origin `y=134.764618`; native reverse lookup at
  `(170,134.765)` returns source line 3. `pdfinfo` verifies this installation's
  native output is **595.276×841.89 points (A4)**. The browser test reads these
  actual dimensions. Its dependency-free CI PDF fallback is Letter, 612×792,
  with the same source-line baselines. Paper sizes must not be conflated.
- The original frozen production bundle on port 5501 failed the new two-case
  browser contract with zero retries: it submitted before the five-second quiet
  deadline and had no explicit source→PDF divider action. Retained log:
  `/tmp/latexy-editor-compile-sync-baseline-red-v2-20261006.log`. First diagnostic
  invocation failed Playwright's CJS handling of `import.meta`; that was a test
  setup error, not an application regression. The corrected invocation is the
  application evidence.
- Fresh candidate browser runs must retain unique outputs/logs, report all
  uncaught page errors and unexpected backend requests, and keep HTTP/WS
  fixtures isolated. A clean retry must never replace a failing original.
- `/tmp/latexy-editor-compile-sync-green-v1-20261006.log`: both failed; frozen
  input/animation timers disrupted the harness and the PDF locator matched two
  nested elements. `/tmp/latexy-editor-compile-sync-green-v2-20261006.log`: real
  timers still reproduce corrupted input (genuine #1812); the native PDF test
  then exposed the test's incorrect Letter-paper assumption. Those artifacts
  remain intact and are not replaced by later runs.
- `/tmp/latexy-editor-native-sync-v3-20261006.log`: genuine native geometry,
  divider actions and repeat highlights pass up to the Control-click assertion;
  Control-click fails on macOS before the mouse-down repair. Trace retained.
- `/tmp/latexy-editor-native-typing-baseline-red-v3-20261006.log`: the corrected
  fixture against the original frozen production bundle still corrupts native
  60-word keyboard input with real browser timers. The failure occurs at the
  exact source equality assertion, before cadence checks; it is not a frozen
  clock artifact. The repaired bundle preserves both source and submitted bytes.
- `/tmp/latexy-editor-compile-sync-final-v4-20261006.log`: background endpoints
  omitted from the fixture and an incorrect busy-button label caused failures.
  The file changed while later workers imported it; do not treat this run as
  four-case acceptance. Original traces remain intact.
- `/tmp/latexy-editor-compile-sync-final-v5-20261006.log`: functional editor
  assertions pass, but Playwright's blocked service-worker registration returns
  `undefined` where Workbox expects a registration. The first case additionally
  contains genuine React hydration error 418. The registration boundary helper
  now provides a truthful synthetic registration shape, not an error filter or
  application PWA repair. **The separate hydration issue #1772 remains open**;
  later clean editor runs do not prove its intermittent cause repaired.
- `/tmp/latexy-editor-compile-sync-final-v6-20261006.log`: four native-PDF
  scenarios pass with zero retries and explicit empty uncaught-error/unexpected-
  request assertions. The bundle predates the final accessible maximum/viewport
  clamp change, so this alone is not exact final-source acceptance.
- `/tmp/latexy-editor-compile-sync-final-v7-20261007.log`: the earlier isolated
  production bundle (port 5505, `.playwright-e2e-sfnmlq`) passes all **4/4**
  native-PDF scenarios with zero retries. Trace output is retained at the same
  path without `.log`. Build log:
  `/tmp/latexy-editor-production-5505-build-20261007.log`.
- `/tmp/latexy-editor-compile-sync-fallback-v1-20261007.log`: the same earlier
  production bundle passes **4/4** dependency-free Letter-PDF scenarios, zero
  retries and no ignored errors/requests. This final test also explicitly
  enlarges the panel, shrinks the viewport and verifies both the clamped width
  and updated accessible maximum. Its trace directory is retained alongside
  the log. Neither browser fixture contacts live auth, providers or production
  data. The synthetic Workbox registration does not test actual PWA lifecycle.
- `/tmp/latexy-editor-pdf-pairing-baseline-red-20261007.log`: the first delayed-
  download probe used a manual compile, which intentionally opens Logs. Its
  missing-canvas assertion is a harness error, not proof of an artifact bug.
- `/tmp/latexy-editor-pdf-pairing-baseline-red-v2-20261007.log`: the corrected
  automatic-compile probe keeps Preview selected and reproduces #1810. PDF 2
  starts downloading at 11651.649 ms and takes 12329.569 ms; SyncTeX 2 is requested
  at 11669.093 ms, before the new PDF exists. The old canvas remains visible but
  its mapped divider action disappears. Original traces and the explicit
  correction are retained in issue #1810.
- `/tmp/latexy-editor-pairing-native-final-v1-20261007.log`: the repaired,
  branding-preserving production bundle on port 5506 (`.playwright-e2e-J1tATQ`)
  passes **5/5 native-PDF cases**, zero retries and empty error/request lists.
  The fifth case holds the replacement download and verifies the previous PDF
  still uses its previous mapping until the new blob is adopted. Root compared
  publication application source byte-for-byte with this frozen bundle.
  Build log: `/tmp/latexy-editor-production-5506-build-20261007.log`.
- `/tmp/latexy-editor-pairing-fallback-final-v1-20261007.log`: the same exact
  bundle also passes **5/5 dependency-free PDF cases**, zero retries and empty
  uncaught-error/unexpected-request lists. Both final trace directories are
  retained alongside their logs. This is the CI fixture, not native TeX output.
- After the pairing repair, root full frontend units again pass **163 files /
  1,032 tests** (`/tmp/latexy-editor-pairing-full-unit-20261007.log`);
  nonincremental typechecking and scoped ESLint also pass.
- Root full frontend unit run: **163 files / 1,032 tests passed**, including
  **5 focused files / 28 tests**; final full-unit log
  `/tmp/latexy-editor-root-full-unit-v6-20261006.log` and focused log
  `/tmp/latexy-editor-root-focused-v4-20261006.log`. Nonincremental root
  typecheck passed (`/tmp/latexy-editor-root-typecheck-v6-20261006.log`), as did
  final scoped ESLint (`/tmp/latexy-editor-final-eslint-v7-20261007.log`).
- CI PR #1803 final head `679b187f` passed all selected component jobs before
  protected rebase merge. Merged main tree `fc8d947b` is byte-identical to that
  reviewed head. Main CI run `37508662846` passed all 14 jobs. Vercel certificate
  `37509481007` succeeded with both steps executed; live no-store identity reports
  main `fc8d947bedd82efe1b52577e8e23164d3d823168`. Modal run `37509481076`
  executed migrations, rolling deployment, template sync/backfill and health/
  asset checks successfully. Live health, readiness and job-service checks pass.

## Scope limitations

This pass changes desktop Monaco auto compilation and the shared desktop PDF
viewer. Mobile CodeMirror currently remains manual-compile; its stubbed source
highlighting is not claimed fixed or tested here. LLM generation/optimization
algorithms and backend rate-limit protections are unchanged. SyncTeX is compiled
line-level metadata: recompile changed source to refresh the mapping. Unsupported
coordinate-transform headers fail closed instead of guessing a location.

## Publication and regression wiring

PR [#1821](https://github.com/sanskarpan/Latexy/pull/1821) starts from merged main
`fc8d947b` and was normally rebased through GitHub onto branding main `c9700f92`,
retaining its brand assets, accepted MCP SDK 1.31.0 and sanitized dependency audit
changes. Each changed
file has its own commit; generated TypeScript build metadata and unrelated
worktrees are excluded.

The five desktop Chromium editor regressions run inside the existing
**Cross-Browser Quality** job, which is already frontend/full-stack scoped.
They use the dependency-free PDF fixture and an isolated production build,
one worker, zero retries, and retained traces in the existing quality artifact.
No unconditional job or required-check name is added. A workflow-file change
deliberately selects all scopes once; subsequent documentation-only changes
still skip this component job. Root actionlint and **83 deployment-manifest
tests** pass, including the new execution/artifact contract. Classifier and
dependency-audit regressions pass **31 tests**.

The pre-pairing PR head `5dc946f1` CI run `37513425642` passed 13 of 14 jobs,
including the editor browser regressions; only the separately tracked TUI
Ctrl+L failure (#1805) failed. That failure is retained, not waived or called
repaired. The superseded run `37513121390` concluded cancelled despite its jobs
continuing to execute: job-level `always()` prevents timely cancellation. This
separate gap is tracked in #1822; its unpublished candidate is not part of this
editor PR. The updated pairing revision still requires fresh protected checks.

## Remaining verification

- [x] Root review scheduler async A→B→A settlement, busy latest buffer, manual
  dedupe, disabled/readonly/offline state and minimum cadence.
- [x] Root review genuine native parser fixtures, per-page dimensions,
  primary-source matching, readiness and stale PDF render/fetch callbacks.
- [x] Fresh Node 22 full frontend units, nonincremental typecheck and scoped lint.
- [x] Fresh isolated production build, actual browser request-count and
  bidirectional navigation/highlight tests, with no retries/error filters.
- [x] Review focus/keyboard and resize interaction; mobile/visual editor
limitations must be stated, not silently counted as tested.
- [ ] Focused one-file commits, PR checks, protected merge and deployed QA.
