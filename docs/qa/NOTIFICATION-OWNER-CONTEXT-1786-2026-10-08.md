# Notification preference ownership: #1786

Status: locally verified focused candidate; not merged or production-accepted.

## Publication scope

This leaf starts from Settings PR #1854, exact parent
`f76e9f08b70c37d167559e51709b54e2e3a45d84`. It must retain that PR's
provider-action/GitHub callback fixes. The canonical main revision at the start
of this pass is `9c88f40a816b7255082c5f34bae3408494f31ee8`.

The older `qa/1786-notification-integration` checkpoint `c2649383` contains
notification source/test work but is not a merge candidate as a whole. It also
contains unpublished #1793 onboarding and #1794 legacy callback work, overlaps
current Settings/API changes, and predates newer main work. Only the focused
notification hunks and tests are being ported and revalidated here. #1783,
#1784, #1785, and #1787 already have merged repairs; they are not new leaves.

## Fresh unchanged-parent reproduction

An isolated production bundle of unchanged parent `f76e9f08` ran on localhost
5522, built with Node 22.23.2 and the existing frozen dependency installation.
No user `.env` was copied into the disposable runtime. Synthetic session and
HTTP bodies were used in new browser contexts; provider/backend traffic not
explicitly mocked failed closed. No real account/provider write was made.

The browser fixture ports the earlier tracked notification controls and adds
two held-B-save cases. Owners derive from the actual synthetic bearer header;
the held response is consumed by application JSON/text/clone readers before
asserting state. These are ordinary retained-page Better Auth refreshes, not
direct mutation of React internals.

One Chromium run, one worker, zero retries, strict page-error assertions:

- Same-owner save success and failure controls: **2 passed**.
- Delayed A success after B's consumed GET and visible identity: **failed**;
  A's result changes B's switch from false to true.
- Delayed A failure after B's consumed GET and visible identity: **failed**;
  the old rollback changes B's switch from false to true.
- A→B→A before the first A PUT completes: **failed**; the old operation
  overwrites the fresh A snapshot.
- Both added held-B-save cases: **failed before B can save**; after B's GET
  and visible BobGitHub identity, the toggle remains disabled by A's pending
  save. They have not yet reached the later stale-finally assertions in this
  baseline and are not evidence of those later branches on their own.

Total: **5 failed, 2 passed**. This is UI state isolation evidence, not backend
IDOR or proof of cross-account server writes.

Evidence log: `/private/tmp/latexy-notification-red-browser-20261008.log`, SHA-256
`c6c1d41593dab6cce80d88a8e1ef313341b39b0a89a6573aebac5e0faf2e5458`.
Traces/screenshots are under
`/private/tmp/latexy-notification-red-browser-20261008/`.

## Candidate repair and verification

The candidate ports the notification-only repair, retaining the parent's
provider changes. Notification owner epochs reject ABA, revisions protect
newer edits and Saved timers, and mounted lifetime invalidates completions.
GET/PUT receive captured bearer contexts checked after the API auth wait.
New saves require confirmed auth and a synchronous in-flight lock. An
already-dispatched same-owner save may complete across token refresh; a
refresh GET must not erase its optimistic draft.

The first integrated candidate browser run was **22 passed, 1 failed**. The
same-owner refresh failure retained the correct preference, but its error
paragraph had no alert role and the loaded-controls branch exposed no Retry
action. This was not an owner-isolation regression or a reason to weaken the
test. The candidate now announces that error and provides a retry while
preserving the loaded preferences. The unit file also required indexed array
access rather than `.at()` to respect the existing TypeScript library target.

The final application production bundle is source checkpoint
`8b5c4f50` (later unit/doc/base-merge changes do not change application sources).
On localhost 5523, the exact three-file CI command ran one Chromium worker,
zero retries, with strict page-error checks: **23 passed** (5 editor, 6 provider
action, 12 notification). Both held-B-save cases now proceed through A body
consumption while B is saving, keep B disabled without stale Saved/error
notices, and enable B only after its own response. Initial/read retry,
same-owner success/failure and token-refresh draft, unmount, and ABA controls
also pass. This run does not reproduce or close #1772.

Final browser log:
`/private/tmp/latexy-notification-integrated-final-browser-20261008.log`, SHA-256
`531bf089b05da49e0139fca1f3f4677975297edde113a3ee4bc4c9169bf79a4f`.
The original 22/1 log is retained separately, SHA-256
`79cbfef0fb3b852d97ea3a45d073bcd618ea9a1d67a35618eaae14f7f55cc21d`.

New focused API tests before implementation: **4 failed, 3 passed**; after
repair their ordinary captured-token and already-dispatched refresh controls
remain green. Dependency-aware mocked-hook tests cover owner/ABA/unmount,
old-finally versus B saving, stale Saved timer versus newer save, duplicate
initiation/auth-error gates and actual same-owner GET-error/retry recovery.
They are not a substitute for React browser scheduling.

Root's full frontend unit run after parent refresh: **172 files, 1,122 tests
passed**. TypeScript (`--noEmit --incremental false`) and targeted ESLint pass.
Deployment-manifest tests: **92 passed**; CI classifier: **21 passed**. The new
notification browser suite joins the existing shared production build, not
a new all-change workflow.

The parent #1854 has been normally updated onto main, head `e6f82436`, and
merged into this leaf without conflicts. Only provider backend/tests/report
files changed in that refresh; `git diff` confirms no frontend or CI change
from the locally verified candidate. Exact published-head CI and deployed
acceptance remain required.

## Acceptance remaining

- Publish a focused dependent PR linked to #1786, refresh against its final
  parent/main, and retain green required checks before a normal merge.
- Verify the resulting production revision and synthetic browser behavior
  before claiming deployed acceptance or closing the issue.

The separate React hydration issue #1772 remains unresolved. Passing this
leaf's Settings cases does not establish editor or application-wide hydration
acceptance. Preview failures are acceptable to the user operationally, but
the required Vercel merge check has not been removed or bypassed.
