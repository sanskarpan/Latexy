# Notification preference ownership: #1786

Status: focused candidate in progress; not merged or production-accepted.

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

## Acceptance remaining

- Review ported GET/PUT dispatch contexts and owner epoch, request/edit
  revision, mounted lifetime, success/error/finally/Saved timer guards.
- Preserve same-owner token-refresh drafts and already-dispatched ordinary
  completions, while rejecting pre-dispatch token retargeting.
- Fail closed while a new owner's preferences are unavailable, with a usable
  retry and no exposure of the previous owner's controls.
- Run all browser controls against the exact candidate production bundle,
  including a live B save while A's response is consumed; run focused and
  full frontend units, types/lint, CI-selection/deployment contracts.
- Publish a focused dependent PR linked to #1786, refresh against its final
  parent/main, and retain green required checks before a normal merge.
- Verify the resulting production revision and synthetic browser behavior
  before claiming deployed acceptance or closing the issue.

The separate React hydration issue #1772 remains unresolved. Passing this
leaf's Settings cases does not establish editor or application-wide hydration
acceptance. Preview failures are acceptable to the user operationally, but
the required Vercel merge check has not been removed or bypassed.
