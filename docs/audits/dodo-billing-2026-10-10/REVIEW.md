# Dodo billing completion review — 10 October 2026

## Scope

This continues PR #1834 from `db97a68283d02d35d65be334ed0f2792faf700a3`.
The branch already includes guided-builder, marketing, deployment and LuaLaTeX
changes; they are not newly introduced billing changes. Main's OAuth ownership,
onboarding and dependency fixes are retained, including main through
`c21bcc20f7060b09269375f1b1f8f0b4f8229bae` (Settings callback ownership). Engine migrations 0060–0064 are
semantically identical to PR #1833's schema, but this branch does not include
that PR's new rendering runtime. The admin catalog draft uses distinct revision
IDs on another branch from 0059 and will need an explicitly reviewed merge head.

## Completed correctness repairs

- Checkout admission rechecks legacy/live intents under a locked account after
  the Redis lease, preventing two serially admitted payable sessions. A checkout
  response or timeout cannot overwrite a paid/terminal webhook received first.
- Verified payments arriving after newer active lifecycle events can establish
  paid access without rolling back newer suspension, terminal status or dates.
  Explicit customer/owner metadata mismatches are rejected.
- Lifecycle status follows the current provider payload, including delayed
  event types. Cancellation cannot restore suspended access or overwrite a
  terminal event/newer account subscription. Scheduled cancellation stops paid
  features and quotas at the paid term boundary, including inherited team seats.
- Revision 0068 saves immutable webhook resource identity. A changed signed
  retry must retain resource ID, event type and event timestamp. Historical
  hash-only rows still fail closed on changed bodies. Duplicate processing and
  older failed attempts cannot overwrite completed event state.
- Recovery verifies one-time Lifetime payments without inventing a recurring
  subscription, and accepts nullable provider tax as zero while preserving exact
  currency/amount/product/owner checks. This does not enable an unconfigured SKU.
- Billing requests and response publication are bound to the initiating account.
  Pending-checkout recovery remains reachable after a return, an early lifecycle
  event, or reopening `/billing`. Retry state survives query changes; stale
  checkout tabs close; cancellation refreshes the card; return queries survive
  login; concurrent checkout actions are disabled.

The provider retry contract is documented in [Dodo's webhook reference](https://docs.dodopayments.com/developer-resources/webhooks#event-ordering).

## Migration boundary

Fresh databases migrate through 0068. The legacy Dodo 0061 bridge deliberately
still lands at its separately verified 0067 checkpoint, after which ordinary
Alembic applies 0068. It only accepts the reviewed single-head repository graph.
It does not stamp an unknown database or rewrite financial history. Downgrade
0068 refuses while webhook identity evidence exists; use an application rollback
without discarding billing evidence.

## Verification checkpoint

- 203 distinct focused billing/entitlement cases passed, including 23 explicit
  interleaving/cancellation cases. The 197-case run and later 23-case run overlap.
- 42 entitlement/migration/bridge checks passed; this count overlaps other suites.
- Real isolated PostgreSQL: fresh upgrade through 0068 passed; a data-bearing
  downgrade was refused atomically with its marker/identity intact; an empty
  downgrade to 0067 and upgrade to 0068 passed.
- Integrated frontend unit checkpoint: 195 files / 1,326 tests passed. Full TypeScript,
  ESLint and Linux production build/artifact validation passed. Backend Ruff and
  whitespace checks passed.
- Local browser tests did not reach application assertions: the isolated build
  lacked Google Fonts DNS access; a reuse of the successful production build
  reached the server but Chromium was denied its Unix socket. No sandbox
  controls were changed. Billing browser cases are now in the normal required
  production-browser CI job alongside builder/editor/account coverage.
- The complete local backend run recorded 4,542 passed, 24 failed, one skipped
  and five setup errors. Nineteen failures and the five setup errors lack usable
  pdflatex/lualatex format files in this host; three unchanged scraper tests fail
  their real DNS preflight; two tracing tests inherited the host's 1% sampler.
  A final 427-case billing/entitlement/migration/builder/deployment selection,
  including those two tracing tests under deterministic always-on sampling,
  passed after main integration. These are environment-limited results, not a
  clean complete backend pass. No new exploit/private-file probes were performed.
- Latest published-head CI remains a separate full-backend and browser gate.
  Check its completed results on the PR before treating the branch as merge-ready.

## Still requires provider or deployment acceptance

These are not certified by synthetic tests or a merge:

1. Genuine terminal delivery of the previously requested sandbox refund and its
   observed ledger/access effects. The prior audit's pending status is historical,
   not a fresh provider observation from this review.
2. Provider USD subscription/line-item representation versus INR charged totals.
   Provider-side plan changes/prorations remain unsupported: a renewal carrying
   the original checkout plan tag after a plan change fails closed. Do not use
   provider-side plan changes until quote/metadata history is explicitly designed
   and accepted; no generic currency or metadata bypass was introduced.
3. Student checkout with an authorized academic mailbox; unconfigured optional
   SKUs remain unavailable. No Student or optional SKU was activated here.
4. Live merchant/catalog/webhook configuration, legacy Razorpay mandate
   reconciliation and an approved production schema/cutover plan. Auto billing
   without configured Dodo keys remains unavailable; `required` mode requires
   those credentials. Merging source is not a live billing cutover verification.
5. Deployment-specific trusted engine images/caches and real email/Drive delivery
   retain their existing acceptance limits from the builder and engine audits.

No live payment/refund, provider configuration, secret rotation, production
migration, manual deployment or admin-catalog merge was performed.
