# Open PR review and production acceptance — 2026-10-07

Survey baseline: main `c8cdbf933461723729e72dfc0fef097b25fc00bd`. Latest reviewed
main: `95537f70bc896bbaa68ab608cfe5fd49282ec248`. Three read-only
review agents surveyed all 14 open PRs (12 non-draft, two drafts). No draft
branch, billing account, credentials, or production payments were modified.
This is a point-in-time tracker, not a claim that every project issue is fixed.

## Production OAuth acceptance

- [x] Approved existing Google web client retains localhost callback and adds
  `https://latexy.xyz/api/auth/callback/google`.
- [x] External app published with only OpenID, email, and profile scopes;
  canonical homepage/privacy/terms and authorized domain configured.
- [x] Existing credentials installed as sensitive production configuration;
  no credentials committed, client recreated, or account-link safety weakened.
- [x] [PR #1835](https://github.com/sanskarpan/Latexy/pull/1835) merged normally:
  verification state storage widened from VARCHAR(255) to TEXT, with real
  PostgreSQL upgrade and safe-downgrade regressions. The ordinary native
  Better Auth state was 290 characters; the original admission failed with
  SQLSTATE 22001. Long destinations also remain supported without truncation.
- [x] Canonical CI [37603450953](https://github.com/sanskarpan/Latexy/actions/runs/37603450953),
  actual automatic Modal migration/rolling deployment
  [37604617887](https://github.com/sanskarpan/Latexy/actions/runs/37604617887),
  and exact-main Vercel certification
  [37604617901](https://github.com/sanskarpan/Latexy/actions/runs/37604617901)
  succeeded for this exact baseline. Backend readiness is healthy.
- [x] Search Console verified canonical URL-prefix ownership using the deployed
  homepage HTML tag. Keep the tag; no DNS change was needed.
- [x] Real production browser sign-in passed account selection, basic
  name/profile/email consent, callback, authenticated Resume Library, and
  workspace reload. This was not a mocked provider or synthetic session.
- [ ] Complete ordinary UI logout/re-login acceptance. Mobile navigation lacks
  account controls and Sign Out: newly verified
  [issue #1836](https://github.com/sanskarpan/Latexy/issues/1836).
- [ ] Retry Google's branding verification after its stated 24-hour ownership
  propagation wait. Ownership verification is complete, branding is not.
- [ ] Keep [#1830](https://github.com/sanskarpan/Latexy/issues/1830) open until
  outstanding acceptance is documented; no blanket closure from setup alone.

## Non-draft PR disposition

Old green checks alone do not certify a refreshed integration branch. Keep
required protections, review the current diff, and run fresh applicable checks.

| PR | Disposition and next step | Issue linkage |
| --- | --- | --- |
| [#1792](https://github.com/sanskarpan/Latexy/pull/1792) | **Merged** after normal rebase onto the baseline and fresh checks. Main `91d1f683` has the exact reviewed Git tree. Independent focused tests: 31 passed; unrelated draft route work was not imported. | #1787 automatically closed on merge. |
| [#1827](https://github.com/sanskarpan/Latexy/pull/1827) | Closed as superseded by merged [#1837](https://github.com/sanskarpan/Latexy/pull/1837). Seven intended paths selectively transplanted; stale stacked changes excluded. Source branch retained. | #1800 automatically closed by #1837. |
| [#1824](https://github.com/sanskarpan/Latexy/pull/1824) | **Merged** after fresh rebase and protected checks. Fourteen job conditions use `!cancelled()` while preserving scope classification and fail-closed behavior. Integrated supersession timing remains an operational observation to capture. | #1822 automatically closed on merge. |
| [#1804](https://github.com/sanskarpan/Latexy/pull/1804) | Historical QA evidence on an already-merged feature base. Retarget/rebuild as documentation only if still useful; distinguish dated observations from current state. | Do not close partial #1801 from a documentation checkpoint. |
| [#1763](https://github.com/sanskarpan/Latexy/pull/1763) | 33-package Python group has failing backend/Ruff checks; refresh and resolve dependency-specific failures. | No issue closer. |
| [#1756](https://github.com/sanskarpan/Latexy/pull/1756) | 56-package JS group has failing lint/build/browser/Vercel checks; do not batch-merge on old evidence. | No issue closer. |
| [#1743](https://github.com/sanskarpan/Latexy/pull/1743) | **Merged** after normal rebase onto `95537f70` and all fresh checks. Four immutable setup-uv pins updated; scoped cancellation conditions preserved. | No related issue; no invented closer. |
| [#1705](https://github.com/sanskarpan/Latexy/pull/1705) | upload-artifact action update conflicts with current main; refresh serially with CI workflow updates. | No issue closer. |
| [#1704](https://github.com/sanskarpan/Latexy/pull/1704) | setup-python deployment action update conflicts with current main; refresh and verify manifest/runtime contract. | No issue closer. |
| [#1520](https://github.com/sanskarpan/Latexy/pull/1520) | setuptools pin update needs current dependency/test validation; coordinate shared requirements file with billing draft. | No issue closer. |
| [#1519](https://github.com/sanskarpan/Latexy/pull/1519) | Ruff lower-bound update needs refreshed installation/lint checks. | No issue closer. |
| [#1518](https://github.com/sanskarpan/Latexy/pull/1518) | OpenAI major upgrade is not endorsed by this review; validate SDK/client/runtime compatibility separately, including HTTPX2 change. No LLM implementation requested here. | No issue closer. |

## Draft integration gates

### [#1833 — semantic resume/PDF engine](https://github.com/sanskarpan/Latexy/pull/1833)

- [ ] Rebase onto current main and repair migration lineage. Its `0060` migration
  depends on `0058`; current main adds `0059`, otherwise there are two heads.
- [ ] Coordinate globally unique revision identifiers with billing draft.
- [ ] Obtain frozen backend/frontend CI evidence on the final head. Current
  review saw no such checks and a failing CodeQL umbrella despite successful
  language analyses. Recorded suite: 4,543 passed, 49 failed, seven skipped,
  explicitly non-attested and before final head.
- [ ] Run the unexecuted original-PDF backend suite and verify import/retention.
- [ ] Verify performance targets with suitable end-to-end distributions; saved
  samples (~29.3 seconds action-to-paint and 1.60 seconds artifact-to-paint) do
  not certify the advertised one-second/500-ms targets.

No direct changed-path overlap with the five newest main files was found for
this draft. That does not remove the database lineage or acceptance gates.

### [#1834 — billing and accumulated enhancements](https://github.com/sanskarpan/Latexy/pull/1834)

- [ ] Resolve hard revision collision: its billing `0059`/parent `0058` duplicates
  main's OAuth storage revision. Resequence downstream `0060`/`0061` against
  main and the engine draft before applying migrations.
- [ ] Preserve main's runtime OAuth discovery, callback recovery, removal of
  build-time OAuth flags, and homepage ownership tag in overlapping files.
- [ ] Keep the recoverable snapshot but split focused billing work from editor,
  marketing, design, and infrastructure changes (194 files in this checkpoint).
- [ ] Resolve failing Backend Lint (uvloop lock marker), Backend Tests (plan
  availability contract), Cross-Browser Quality (mobile Recompile visibility),
  and CodeQL; rerun the frozen production-dependency unit suite.
- [ ] Finish Pro annual/BYOK provider-ledger-access reconciliation, Team/Student
  acceptance, currency discrepancy, refund verification, live catalog/webhooks,
  and legacy Razorpay mandate reconciliation before release.
- [ ] Decide recurring-refund entitlement policy and test it. Source ends
  Lifetime access for refund but leaves recurring entitlement unchanged;
  correctness depends on intended product policy, not an assumed requirement.

Do not automatically close the draft's 47-item inventory. Partial local work,
operational gates, and already-merged independent fixes have different status.
Live merchant/cutover operations remain separate from read-only PR review.

## Publication follow-up

The trial PR merged at `91d1f683c6656e8a04f6e977593532af2f02000d` after CI
[37606343779](https://github.com/sanskarpan/Latexy/actions/runs/37606343779)
succeeded. Reviewed PR head `722c4c06` and merged main share Git tree
`a683f0d6ef89861a0d77dfa5820cd964b4b5e0ae`. Its canonical main CI
[37607772764](https://github.com/sanskarpan/Latexy/actions/runs/37607772764)
and automatic Modal rollout [37608781142](https://github.com/sanskarpan/Latexy/actions/runs/37608781142)
and Vercel certification [37608781112](https://github.com/sanskarpan/Latexy/actions/runs/37608781112)
succeeded. Invalid oversized fingerprint and metadata requests return 422 in
production. An initial 30-second metadata POST timeout remains an unexplained
performance observation; two subsequent invalid POST probes passed and do not
erase it. OAuth acceptance above refers specifically to the earlier `c8cdbf9`
deployment.

#1824 merged at `bbb2b49faf8216b304161e2d097311c277125d4b`; canonical CI
[37612421654](https://github.com/sanskarpan/Latexy/actions/runs/37612421654),
Modal [37613602992](https://github.com/sanskarpan/Latexy/actions/runs/37613602992),
and Vercel [37613602991](https://github.com/sanskarpan/Latexy/actions/runs/37613602991)
succeeded. No old green check was substituted for the refreshed head.

#1837 merged at `95537f70bc896bbaa68ab608cfe5fd49282ec248`, whose Git tree
matches accepted head `ad7a34b3`. Root's full backend run: 4,298 passed, five
skipped, one existing unsuppressed deprecation warning. A later direct JSON-safe
unit regression and explanatory comments were accepted in focused tests; after
rebasing onto `bbb2b49`, 143 focused/manifest tests passed. Validation errors no
longer echo request `input` or `ctx`, including private nested metadata. Canonical
CI [37614920023](https://github.com/sanskarpan/Latexy/actions/runs/37614920023),
Modal [37615807415](https://github.com/sanskarpan/Latexy/actions/runs/37615807415),
and Vercel certification [37615807430](https://github.com/sanskarpan/Latexy/actions/runs/37615807430)
succeeded. Canonical identity reports `95537f70`. Four invalid live probes
(nested NaN metadata; nan/inf/-inf compilation time) returned 422 without input,
ctx or synthetic private markers, taking 5,013 / 5,096 / 4,101 / 2,929 ms.

#1743 merged at `12e54dbf655b3fb4c8491a22e1d3691ed3021f9e` after fresh CI
[37619510856](https://github.com/sanskarpan/Latexy/actions/runs/37619510856)
and all applicable protections passed. Its automatic main rollout is pending
at this writing. #1705 and #1704 need immutable SHA replacements instead of
their submitted mutable tags; root separately passed 92 manifest tests on each
prepared candidate. Neither is approved for deployment by stale checks alone.

## Mobile account navigation — #1836

The production 627px menu lacked account controls and Sign Out. The focused fix
reuses existing session resolution, role/feature gates and shared sign-out cleanup;
it adds scrollable account navigation and Escape focus restoration, without new
auth endpoints. The shared hard-navigation sign-out now opts out of Better Auth's
redundant pre-unload session signal; it still awaits the real logout POST and
retains private-data cleanup and a fresh session read in the new document.

- Root Node 22 TypeScript and focused ESLint passed on the corrected frozen test.
- Root zero-retry Chromium, Firefox and mobile Chromium run: nine passed (59.3s).
- Root updated-header unit acceptance: 1,057 tests across 166 files passed after
  adding the SDK-supported sign-out signal option; TypeScript also passed.
- Earlier failures are preserved: cold route/session timing, a test-only fixture
  closure ReferenceError (fixed), and six macOS WebKit launch SIGSEGV failures.
  The macOS launch failures are not passing tests or permission to waive WebKit.
- First Linux CI [37619025359](https://github.com/sanskarpan/Latexy/actions/runs/37619025359):
  35 quality cases passed, two authenticated WebKit cases failed on strict
  page-error assertions, including retries. All visible logout/navigation
  assertions passed, but that is not permission to ignore the errors. Traces
  place the access-control error after logout and before root navigation
  completes, not at the test's later explicit reload. Successful captured auth
  requests are same-origin 200 responses; traces do not identify the exact
  interrupted request. The SDK option is a mitigation pending fresh Linux
  evidence, not a proven root-cause claim or CORS/security bypass.
- Linux desktop/mobile WebKit and current-head protected CI remain required
  before merge. Real production UI logout/re-login remains pending deployment.

## Integration checklist

- [ ] Root-review prepared focused diffs and independent regressions.
- [ ] Keep one file per commit and use focused PRs with truthful issue closers.
- [x] Refresh and merge #1792, #1824 and focused #1837 in dependency order.
- [ ] Refresh workflow dependency PRs serially to preserve scope classification.
- [ ] Merge only after current protected checks/reviews; no admin/force bypass.
- [ ] Verify actual canonical deployment and relevant live behavior after merge.
- [ ] Preserve unrelated dirty worktrees, drafts, failures, and external gates.

This tracker supplements existing QA records; it does not supersede unresolved
hydration/owner-isolation, deployment-policy #1802, external credential/legal/
accessibility gates, or the broader all-priorities QA goal.
