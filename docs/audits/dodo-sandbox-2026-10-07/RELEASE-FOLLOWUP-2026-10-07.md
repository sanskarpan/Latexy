# Dodo release follow-up — 7 October 2026

This is a checkpoint for the isolated Dodo candidate, not a production-readiness
approval. It complements [REPORT.md](REPORT.md), which retains transaction-level
sandbox evidence, and [ISSUES.md](ISSUES.md), which records issue scope and
external dependencies. No live payment, refund, webhook replay, merchant change,
production migration, or deployment was performed for this checkpoint.

## Exact source and verification state

- Candidate branch: `fix/1834-dodo-release-20261007`
- Candidate source commit: `bc9fb281471f35b1b7f3c3ab17b1803173ed0c99`
- Backend source tree: `3eae0a5125ca3541cb0c89c99935ee6ba62caba7`
  (the backend integration run below is for this exact candidate tree).
- Dodo schema chain: OAuth `0059`, engine `0060`–`0064`, Dodo `0065`–`0067`,
  single Alembic head `0067`.
- Isolated full backend suite: **4,315 passed, 5 skipped** (4,320 collected),
  with zero failures/errors and one Starlette/httpx deprecation warning in the
  completed run. The exact source was tested
  with the QA PostgreSQL database on port 5547 (`latexy_dodo_release_test`),
  Redis DB 11 and cache DB 10, the worktree backend on `PYTHONPATH`, and no
  `SKIP_INFRA_CHECK`. Dodo API and webhook credentials were blank. Pytest's
  JUnit independently reports `tests=4320`, `failures=0`, `errors=0`,
  `skipped=5` in `/private/tmp/latexy-dodo-full-final-20261008.xml` (SHA-256
  `7c2493e1809c59ce5c1a671000e993f94d70d24113c5a285650ca24b6a5f5ea8`).
  Full pytest log: `/private/tmp/latexy-dodo-full-final-20261008.log` (SHA-256
  `596839daf090a734dda51202e83f32a3f41ca9974d5fe08bd9f13f4a8c3e19e2`).
- Focused provider/billing/webhook-recovery/entitlement/subscription suites:
  **88 passed**. The separate latest-main OAuth/public-bound/telemetry/manifest
  regressions: **140 passed**; some paths overlap with the broader suites, so
  these counts must not be summed as unique tests. The final contract/harness
  follow-up (configured and unconfigured plan contracts plus publication regex
  children): **5 passed**. Ruff passed for the changed test file.
- The previous full run at the pre-follow-up checkpoint showed 15 failures:
  11 local auth-secret/TeX-image launcher failures, 3 publication-regex child
  import failures, and the stale Phase 12 billing assumption. Afterward, the
  launcher files passed 12/12 in isolation, the publication regressions passed
  with the backend root on `PYTHONPATH`, and the Phase 12 test now separately
  covers configured paid-plan visibility and unconfigured free-only behavior.
  The exact later full-suite rerun above passed. The isolated reruns explain the
  earlier harness failures; they do not establish that those failures were
  caused by product code.
- Frontend frozen-lock verification: **1,101 Vitest tests across 176 files**;
  lint and TypeScript checks passed. The production build generated all 44
  static pages and passed artifact validation using a dummy HTTPS test URL and
  test-only auth values. These checks do not certify the engine/runtime matrix.

All integration tests use a dedicated QA database and test Redis only. Fixture
configuration blanks inherited Dodo keys; no real payment credentials or
customer records are part of this test result.

### Subsequent candidate updates verified locally

- Candidate CI maintenance: both Python locks are generated with a universal
  Python 3.12 resolution. The lockfiles preserve platform markers (including
  Windows-only `colorama` and non-Windows `uvloop`); CI regeneration and custom
  provenance comments use the same `--universal` option, and the manifest
  regression keeps marker differences strict. This fixes the Ubuntu
  host-specific regeneration mismatch seen in the earlier CI attempt without
  relaxing hash/marker checks or changing requirement inputs. Focused lock
  manifest tests passed **2/2** locally; these local commits have not yet been
  re-run by GitHub Actions.
- Frontend smoke fixture maintenance: the full-stack test follows the current
  landing-page “Build my résumé” CTA to `/try?mode=visual`, checks the visual
  editor and “Update PDF preview” control, then switches to Source and checks
  Monaco. The mobile quality fixture also targets the current exact “Update PDF
  preview” accessible name instead of the retired “Recompile” label. A local
  isolated Chromium run passed **1/1** against its dedicated
  backend/frontend pair. The earlier GitHub smoke run used the old selector
  and failed because “Start compiling →” no longer exists; that is fixture
  drift, not evidence that the current smoke passes in GitHub Actions. A macOS
  WebKit attempt ended in a browser-process crash; it is not a WebKit pass and
  cross-browser acceptance remains open.
- Quota outage log privacy: the entitlement service no longer interpolates
  user IDs into quota-counter outage logs; it records the fail-open/closed
  disposition and exception type instead. The regression checks that a
  CR/LF-injected owner identifier is absent from captured logs. Its fixture
  pins the intended quota policy directly, so this privacy assertion is
  independent of paid-plan catalog availability in the QA environment.

## Material sandbox limits still open

### October 8 handoff checkpoint

The owner requested committed draft handoffs so the feature worktrees can
continue while root returns to deployed-main QA. Neither draft is merge-ready.

- Security source checkpoint `165f6810`, backend tree `d083d8a8`: restrict the
  adapter to the exact official HTTPS origin of the active mode, without
  userinfo/ports/extra paths/query/fragment; omit untrusted webhook event types
  from failure logs. Test-only URL validation now compares parsed origins, and
  contrast utilities use a declared, locked CSS selector parser rather than
  partial escaping. Independent root checks: 31 provider/webhook cases and four
  frontend cases passed; Ruff/diff checks passed. Agent targeted ESLint/types
  also passed. A fresh CodeQL scan is required; no alert was dismissed or
  suppressed. Tracked separately in [#1846](https://github.com/sanskarpan/Latexy/issues/1846).
  The 4,315-case full run above predates these security follow-ups.
- GitHub CI `37667949642` at `4a6f8980`: backend lint/tests, frontend lint/build,
  template extraction, deployment parity and full-stack smoke all passed.
  Cross-browser quality failed in all five desktop compile/synchronization
  scenarios during fixture setup: `__latexyMonacoEditor` remained undefined.
  Review lazy editor-mode initialization before changing assertions; the cause
  is not certified from that error alone. Browser-quality and complete-current-
  source acceptance remain open. The earlier failed CI is retained as history.
- Fresh TEST-only API reads confirm a cross-resource currency inconsistency:
  the Basic monthly product and linked first/renewal payments show INR 29,900
  minor units; their subscription reports USD 310 minor units. Payments
  separately report USD 298 settlement. The provider's
  [subscription schema](https://docs.dodopayments.com/api-reference/subscriptions/get-subscriptions)
  describes subscription currency as the payment currency. Do not assume these
  fields are harmless settlement semantics or normalize currencies. Provider
  explanation is required before recurring-price/proration acceptance. No
  checkout, charge, refund, replay or provider-state change was made in this
  diagnostic; original checkout-intent database access is still required.

1. **Original intent database and event recovery:** the earlier sandbox
   transactions were exercised against a separate local Windows/Docker database
   at the old migration checkpoint. This fresh QA database has the new schema,
   but not those original checkout-intent rows. Do not replay old signed relay
   events into it: without their original intents, that would not test recovery
   and could create misleading/unmatched state. Recovery for any events missed
   by the interrupted relay must be reconciled against the original test data or
   a provider-supported replay process with matching intent history.
2. **Provider amount disagreement:** Dodo subscription reads report USD and
   recurring pre-tax values that disagree with the INR catalog and successful
   INR payment resources (for example, Basic monthly subscription `USD 310`
   versus INR 29,900 payments/catalog). Payment objects are charge evidence;
   the subscription representation remains unresolved. Do not certify plan
   changes, proration, or recurring amount reconciliation from those values.
3. **Refund lifecycle:** the sandbox partial-refund request returned HTTP 409
   `INSUFFICIENT_WALLET_FUNDS`; no refund was created. Real provider refund
   creation, webhook reconciliation, and support/operations handling remain
   unverified. Do not claim refund readiness or infer that a failed sandbox
   refund proves production refund behavior.
4. **SKU acceptance and transaction matrix:** Weekly and Lifetime remain
   disabled until approved prices and product IDs are supplied. Team checkout
   was not completed; Student verification awaits an authorized academic test
   mailbox; Pro annual and both BYOK periods do not have complete
   provider/payment/ledger/access reconciliation. Do not invent commercial
   prices or bypass student verification. Existing sandbox payments are not to
   be repeated just to fill this matrix.
5. **Legacy mandates:** historical Razorpay subscription rows do not prove that
   their chargeable mandates were cancelled at Razorpay. Reconcile each
   potentially chargeable legacy mandate with the old provider before enabling
   a new Dodo subscription for that account. A schema migration cannot cancel
   an external mandate.
6. **Merchant and production configuration:** live merchant approval, reviewed
   live products/prices/tax/cadence, live API and webhook keys, public webhook
   delivery, event coverage, and operational monitoring remain external gates.
   Test-mode IDs or events cannot satisfy them. No live-mode call was made.

## Combining with the resume-engine candidate

The Dodo branch contains the actual engine migrations `0060`–`0064` as
dependencies, but it does not contain the engine's model/API implementation.
Those migration files are not substitutes for the engine code or its
certification. The Dodo and engine candidates share a base around
`787b9351` and modify many of the same application, editor, workspace, fixture,
and test paths. A combined release should integrate the engine candidate first,
then add Dodo changes by semantic review. Preserve both sides of shared files;
do not replace one candidate's snapshot wholesale. Identical shared migration
files can remain unchanged, while route/config/model/test and especially editor
and resume-workspace changes need explicit conflict resolution and combined
verification.

## Release decision and next gates

The backend and frontend evidence above establishes a strong test-mode source
checkpoint, not a go-live decision. Keep billing in test/disabled mode until the
original sandbox intent/recovery question, provider amount discrepancy, refund
behavior, remaining enabled-SKU acceptance, legacy mandates, legal/commercial
choices, live merchant/webhook setup, and combined engine release verification
are closed with evidence. Back up production data and apply the single reviewed
migration chain only as part of an explicitly approved deployment plan.

Linked issue epics are not blanket completion claims: distinguish implemented
code from accepted plan policy, external operations, merged provenance, and
production certification. In particular, do not close all billing/engine
children merely because these isolated suites pass.
