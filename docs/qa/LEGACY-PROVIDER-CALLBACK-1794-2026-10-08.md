# Legacy provider callback ownership: #1794

Status: committed local candidate; browser verification is still in progress.
Not merged or production-accepted. Hydration #1772 remains unresolved.

## Scope and base

This leaf covers legacy `github`, `zotero`, `mendeley`, and `dropbox` connected
query callbacks in Settings. It does not replace ticketed OAuth, configure
Google Cloud credentials, or change provider/backend authorization. Evidence
below demonstrates UI ownership defects, not backend IDOR or cross-account
provider writes.

Initial implementation started from accepted main
`26e802ca3e83b11b565365f817407911080c5ff3`. After notification #1860 merged,
the six focused one-file commits were normally rebased onto main
`bdee48926ce0e2e6c9c5e2b281d2ab07c4355b98`, without rewriting any published
branch. Candidate application checkpoint:
`22e24ff2ae02ac56f28a9a6564bc383f18a6e85c`.

Two Settings conflicts retained both notification identity refs and legacy
identity refs, and placed the legacy initial-status precedence guard outside
the notification-loading branch. The resulting diff against main is
legacy-only. Existing generated Playwright report and TypeScript build-info
changes were preserved through an explicitly scoped stash and restored; they
are excluded from publication. No whole stale-primary checkout was merged.

## Repair and independent review

- Status reads receive a captured token and dispatch predicate checked after
  the API auth gate. An undispatched read cannot retarget a replacement session.
- Already-dispatched results use owner epoch, page lifetime, and per-provider
  operation revision, allowing same-owner token refresh without allowing
  owner changes or A→B→A replacements to receive old results.
- Callback query removal waits for verification to settle. Pre-dispatch auth
  loss retains retry intent; false→true readiness cannot revive an old auth
  wait or let its eventual rejection delete a newer retry.
- Only verified connected results produce success or popup messages/closure.
  Timers cannot clear a replacement owner's or newer callback's notices.
- Callback-owned success/error notices clear on owner transition without
  erasing unrelated messages. Per-provider initial status remains available
  while verification is held, but cannot overwrite a later verified result.

Independent review found and prompted repairs for the readiness-recovery
ordering race and indefinite settled-notice retention. The re-review confirmed
their regression tests exercise recovery before the old rejection settles and
owner changes without a replacement callback. Popup-specific stale-owner
browser evidence remains a required acceptance item.

## Unit and static verification

Before integrating notification main: **172 files / 1,151 tests passed**, full
frontend lint and `tsc --noEmit --incremental false` passed. This used the
worktree's older dedicated Next.js 15.5.24 installation; it is not patched
production-bundle acceptance.

Log: `/private/tmp/latexy-legacy-callback-full-final3-20261008.log`, SHA-256
`b33dd930452aeb137ce461b36c5075eba5cee3efbb2b145564f43b84cb14288a`.

After rebasing onto notification main: **174 files / 1,167 tests passed** with
`pnpm test:unit`, without changing application/test assertions to hide failures.
Log: `/private/tmp/latexy-legacy-notification-integrated-vitest-20261008.log`,
SHA-256 `db9859d38cb8caa5c43a285463d5dc7c2631873c65f8c604c566940ae7fe97fd`.

## Fresh browser baseline and evidence limitations

The root-owned isolated production server on localhost 5530 uses Node
22.23.2 and the frozen Next.js 15.5.27 installation, without user credentials.
Its source checkpoint is the clean notification candidate `bbc8722352231bcb282bee2441a77db2879bc500`.
The legacy callback block was verified byte-identical to unchanged main26e:
2,504 bytes, SHA-256
`4e70f1f65c9e88e47ac5a1ae3c6268dcf64719b6eeda4111c48c9d61e1f8058a`.

The first 16-case Chromium baseline used one worker, zero retries, strict
page-error/request checks and labeled response-body barriers. Result:
**11 failed / 5 passed**, but this is **not eleven verified application bugs**.

Four failures reached the substantive stale-owner assertions: old A success
replaces B or fresh A; old A failure surfaces in B; settled A verification
error remains after B's own status is consumed. The delayed-initial case fails
before releasing the initial response: the verified callback identity remains
hidden behind the initial loading state. That phase alone does not prove a
later initial-response overwrite.

Six popup cases failed in fixture setup: a visible initial status was rendered
but its body marker was not associated with the popup. These are test
instrumentation failures, not OAuth/popup regressions. Their diagnostics and
positive controls must be repaired and rerun before browser acceptance.
The settled-success transition control also needs a bounded assertion so the
old unguarded five-second timer cannot masquerade as immediate owner cleanup.

First fixture SHA-256:
`e2ec50e05e85b24f8c0bfb43b5a1cfc8addbd80568b294a908c1b954f0f7f831`.
Baseline log: `/private/tmp/latexy-legacy-callback-patched-baseline-browser-20261008.log`,
SHA-256 `c312955faecc4808157eb79f469f4d146c7a41cfc40394f8b1ef92bc1594c46d`.
Traces/screenshots: `/private/tmp/latexy-legacy-callback-patched-baseline-artifacts-20261008/`.

All session/provider responses are synthetic and bearer-derived; unknown
external traffic/writes/WebSockets fail closed. The explicit service-worker
shim excludes native PWA lifecycle proof. No live account/provider writes,
real OAuth-provider credential acceptance, or hydration closure is claimed.

## Remaining acceptance

### Corrected baseline and patched static follow-up

The popup fixture defect was an early init-script exception: the synthetic
Workbox scope called `new URL('/', 'about:blank')` before response wrappers were
installed. A safe scope for the popup's initial blank document fixes that
instrumentation without weakening body barriers, unexpected-request checks,
or actual popup-close/message assertions. The post-owner-switch notice checks
now require absence within one second, rather than allowing the old five-second
expiry timer to pass them incidentally.

The corrected frozen fixture
`e8c2961e5481899832607a34875ed7bbb21691067c0ac21ec3a1f2e74072d31c`
ran all 16 baseline cases again: **7 failed / 9 passed**, one Chromium worker,
zero retries, 1.4 minutes. Ordinary GitHub, same-owner token refresh, and
Zotero/Mendeley popup success/failure controls pass. Six substantive stale
owner/notice cases fail after their required body barriers; the seventh is the
previously documented held-initial/loading phase. In particular, releasing
A's Zotero verification closes the popup after B's status has been consumed.

Corrected baseline log:
`/private/tmp/latexy-legacy-callback-corrected-baseline-browser-20261008.log`,
SHA-256 `23202f2a38cdadcdaedb57167032f710178a857b7c304c799f25417a2bb6bcd4`.
The old 11/5 result is retained above solely as diagnostic history, not accepted
regression evidence for the six broken popup setups.

Next.js **15.5.27** patched-dependency integrated units also pass: **174 files /
1,167 tests**. The earlier 15.5.24 dependency trees were moved intact to
`/private/tmp/latexy-legacy-deps-preserved.b3a520/`; this checkout now borrows the
root-owned frozen patched installation read-only. No installation is performed
through those symlinks. Patched unit log:
`/private/tmp/latexy-legacy-notification-patched-units-20261008.log`, SHA-256
`f819c50f90cf6829c9524ffd4ae63f6371a5a8c4e774b6c58774df1900ade01a`.

The new E2E helper initially caused a TypeScript error by passing a void promise
resolver directly to `requestAnimationFrame`. It now explicitly discards the
timestamp, with no assertion change. Final no-incremental TypeScript and full
frontend lint passed. Final browser fixture SHA-256:
`7e1821b9ac20957256133d48e8ca5a824b14c642e958ba763a5ff68016a2ef81`.
The isolated patched production candidate is building on localhost 5531; its
browser result is not yet claimed. The shared scoped CI browser command now
includes this legacy spec rather than adding an always-running workflow.

- Repair popup body instrumentation and rerun unchanged-baseline positives
  and stale-owner controls with exact failure phases recorded.
- Run the rebased candidate with patched dependencies in an isolated production
  bundle, including notification/provider/editor regressions; keep zero retries.
- Add the final legacy browser suite to scoped shared CI; publish a focused
  draft linked only to #1794 until exact-head checks and review complete.
- Normal protected merge, exact Vercel production identity and Modal/main CI
  certification, then bounded deployed QA before claiming production acceptance.
