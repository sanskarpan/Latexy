# Settings provider account contexts — #1828 / #1829

Base: exact main `d80757cdbb2710633e942de878f61d7e78aa7f63`.
Final application source/production build checkpoint:
`c8b875f2c454c2d8038daac562b8157c6dc57a93`.

## Bounded repairs

- #1828: capture owner, token, monotonic identity generation, component
  lifecycle and per-provider operation revision for disconnect actions and
  Drive status retries. Reject obsolete intent before API dispatch; ignore
  stale success/error/finally updates. Drive retry/disconnect share an atomic
  in-component lock. Account/token changes reset transient busy indicators.
- #1829: capture context for GitHub completion and its subsequent status read.
  Preserve one-use completion through StrictMode cleanup/setup, reject queued
  intent on unmount/ABA/token change, and do not reinterpret a started ticket
  as an intent for a replacement account. A genuinely new ticket still works.
- Independent review caught stranded GitHub connecting state on token rotation
  and retained-session error. Three new tests failed against the first
  checkpoint; the final repair resets this UI, waits for confirmed auth and
  includes `sessionError` in callback-effect dependencies for recovery.

No provider credentials, backend owner checks, grants, user documents, engine
or billing feature branches changed. Initial provider reads and other-provider
callback intent are not claimed universally context-safe. Notification PUT
races remain tracked separately in #1786.

## Evidence

All browser sessions were disposable synthetic fixtures: actual Next app,
React component, Better Auth session refresh and ApiClient; provider endpoints
were explicitly mocked with bearer-bound identities and unexpected traffic
failed closed. Stale-response assertions wait for actual body consumption,
not merely `route.fulfill` or response headers. No human cookies/accounts,
live provider, payment or production write was used.

- Identical three new unit files on unchanged main: **29 failed / 12 passed**.
  These execute the actual component with a custom indexed-hook harness and
  real ApiClient dispatch controls; they are not a real React renderer.
- Final Node 22 frozen-lock graph: **1,106 unit tests passed**, 170 files.
- Targeted ESLint/type checking and final production build passed (40 static
  pages). Deployment manifest contracts: **92 passed / 0 skipped**.
- Original six-case exact-main browser run: **3 failed / 3 passed**. The stale
  Drive retry/disconnect/ABA assertions reproduced incorrect connection state;
  three ordinary/callback controls passed. Root later found non-exact Connect
  locators could also match Disconnect; baseline failure snapshots show the
  actual stale-state failures, but a new exact-locator baseline rerun is not
  claimed.
- Final six-case candidate browser run with exact button names: **6 passed**,
  one Chromium worker, zero retries, fatal page errors, auth-error list empty.
- CI adds this spec to the existing production editor test invocation, sharing
  one production build rather than adding a second workflow/build.

## Acceptance failure retained, not suppressed

The first combined eleven-case browser run was **3 failed / 8 passed**.
Two were Connect-vs-Disconnect locator false positives and are corrected.
The delayed PDF/SyncTeX replacement editor case completed its behavior checks
but failed the strict page-error assertion on genuine React hydration error
#418. The editor and auth-client wrapper were unchanged by this branch. This
is not a matched baseline causal proof; no attribution to the new Settings
changes or general hydration resolution is claimed. #1772 remains open, with
the log/trace evidence recorded in its GitHub comment. The filename containing
`green` below is historical and does **not** mean that combined run passed.

Independent trace review places the error during route startup: session
fixture fulfillment completed around trace time 46,521.7 ms, followed by #418
around 46,535.9 ms. The first Compile click was around 47,437.8 ms. Thus the
delayed replacement is the test reporting the error, not its demonstrated
trigger. The stack is minified and identifies no mismatched DOM node. A
same-bundle controlled auth-response timing comparison is a next diagnostic,
not proof that the auth store caused this failure.

Follow-up same-bundle experiment: the targeted delayed-replacement test ran
once with zero session-response delay and once with a 500 ms delay. Both
passed with zero retries and fatal page-error assertions; neither reproduced
#418. Initial server HTML was identical (26,629 characters, SHA-256
`a4e2faf07a041207c8f958fee3c59753537bd768a0dbe879d3219871f9e5e7ee`).
Traces and attached diagnostic JSON are retained in
`/private/tmp/latexy-hydration-auth-delay-zero-20261008` and
`/private/tmp/latexy-hydration-auth-delay-500-20261008`. This non-reproduction
does not establish/refute the timing hypothesis and does not erase the earlier
failure or close #1772. The opt-in test-only delay leaves default fixture
behavior and acceptance assertions intact; no application fix was made.

| Local evidence | SHA-256 |
| --- | --- |
| `/private/tmp/latexy-settings-fresh-main-red-20261008.log` | `cb57767a2c1bf0d2749e11f8f70da1f2c7648e52b8885c7bde0d5342a8415c7b` |
| `/private/tmp/latexy-settings-release-all-unit-20261008.log` | `95964be0b5ee14d6c2d5e9489825aa1f2ea557dd952333e3f90875ebe1a1f674` |
| `/private/tmp/latexy-settings-oauth-review-red-20261008.log` | `211ab23d319b40da9992021d523cf657719a5d791dd32aad682ecd9fcd25154c` |
| `/private/tmp/latexy-settings-final-browser-green-20261008.log` | `50fa01e04c303f82dfdc646ec2542e3f48799bc052757d3bcf6a0b6e3929d14a` |
| `/private/tmp/latexy-settings-owner-browser-exact-20261008.log` | `24bca79e9b964d8230270084d528a547d157b6f06aad0765869956c137b4149d` |

Traces/screenshots are retained in corresponding `/private/tmp` output
directories. The two original disposable servers were shut down through their
owned launchers; their temporary build trees were cleaned, not evidence/source.

## Release and next QA

Keep this checkpoint as a draft until the broader fatal hydration acceptance
has been investigated and normal CI/review gates are satisfied. Vercel's
required preview status on concurrent PR #1851 failed due build quota; no
protection bypass or paid upgrade was attempted. The live frontend still
reported main `d80757cd`; backend database/Redis/storage/LaTeX/job-health
checks were healthy. No new fix was claimed deployed.

Subsequent release update: the separate provider-retention PR #1853 obtained a
successful preview and protected CI, merged normally, and closed #1852. The
live frontend subsequently reported its exact main merge SHA
`9c88f40a816b7255082c5f34bae3408494f31ee8`. PR #1851 was updated to that base
without force-pushing; its required preview and this draft's preview still
reported the rate-limit failure when rechecked. One successful production
deployment does not waive either per-head failed check. Main CI and backend
deployment completion still require independent verification.

Next: diagnose #1772 from the fresh editor trace with an immutable matched
baseline; repair #1786 notification action ownership separately; complete
all-provider client dispatch survey and wider authenticated QA. Engine #1833
and Dodo #1834 remain separate pushed draft handoffs, not release claims.
