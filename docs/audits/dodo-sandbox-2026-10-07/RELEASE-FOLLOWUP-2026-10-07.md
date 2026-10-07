# Dodo release follow-up — 7 October 2026

This is a checkpoint for the isolated Dodo candidate, not a production-readiness
approval. It complements [REPORT.md](REPORT.md), which retains transaction-level
sandbox evidence, and [ISSUES.md](ISSUES.md), which records issue scope and
external dependencies. No live payment, refund, webhook replay, merchant change,
production migration, or deployment was performed for this checkpoint.

## Exact source and verification state

- Candidate branch: `fix/1834-dodo-release-20261007`
- Candidate source commit: `814c671217230e295914b1b7b77bb06fc81e3338`
- Backend source tree: `c14f5a38d53a2af7162b5d0751bebcfc46498130`
  (the parent `b2a064da` was the tested code commit; `814c6712` adds only a
  documentation archive and leaves the backend tree unchanged).
- Dodo schema chain: OAuth `0059`, engine `0060`–`0064`, Dodo `0065`–`0067`,
  single Alembic head `0067`.
- Isolated full backend suite: **4,313 passed, 5 skipped** (4,318 collected),
  with no failure/error markers in the completed run. The exact source was tested
  with the QA PostgreSQL database on port 5547 (`latexy_dodo_release_test`),
  Redis DB 11 and cache DB 10, the worktree backend on `PYTHONPATH`, and no
  `SKIP_INFRA_CHECK`. Dodo API and webhook credentials were blank. The log is
  `/tmp/latexy-dodo-full-backend-20261008.log` on the test host. The pytest
  configuration suppresses its final count summary; the collected total was
  counted separately and the five skips are visible in the progress output.
  Log SHA-256: `a07f9970a4896eb98fb91a1fec3aba0819b42e6817b23e15abe55922f6683678`.
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

## Material sandbox limits still open

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
