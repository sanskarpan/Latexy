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

## Provider scope

Latexy uses **Dodo Payments only**. No active Razorpay service, SDK, checkout,
webhook handler, selector/default or fallback is included. Historical financial
records and migration columns remain intact. A proposed compatibility restoration
was not published and was discarded when the owner clarified this requirement.
Only independent Dodo correctness repairs remain from that review.

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

- Production/staging test mode fails closed at both the Dodo network boundary
  and webhook entry, independently of startup-validation bypass. Existing live
  Dodo cancellation/recovery remains available when new sales are disabled.
- An unresolved hosted checkout cannot be locally discarded while its URL may
  remain payable. The Free transition requires verified provider cancellation;
  historical Free rows without actual mandate IDs do not block Dodo checkout.

The provider retry contract is documented in [Dodo's webhook reference](https://docs.dodopayments.com/developer-resources/webhooks#event-ordering).

## Migration boundary

Fresh databases migrate through 0068. The legacy Dodo 0061 bridge deliberately
still lands at its separately verified 0067 checkpoint, after which ordinary
Alembic applies 0068. It only accepts the reviewed single-head repository graph.
It does not stamp an unknown database or rewrite financial history. Downgrade
0068 refuses while webhook identity evidence exists; use an application rollback
without discarding billing evidence.

## Final Dodo-only verification checkpoint

- 229 distinct focused Dodo/rollout cases passed. Independent read-only review
  confirmed the Dodo-only scope and passed 16 isolated configuration, route and
  runtime checks; these counts overlap other suites.
- Frontend: 195 files / 1,329 tests passed, with full TypeScript, ESLint and Linux
  production build/artifact validation. Backend Ruff and whitespace checks pass.
- A newly created isolated PostgreSQL database migrated to the actual single
  head 0068. Separate 0059 → 0068 preservation proof kept original historical
  user pointers, plan/status/terms and financial rows identical, while generic
  historical IDs exactly matched retained legacy IDs. No compatibility trigger
  or removed migration was present in this final fixture.
- The complete backend run on that fresh database recorded **4,576 passed,
  22 failed, one skipped and five setup errors** under deterministic tracing.
  Nineteen failures and five setup errors lack usable pdflatex/lualatex format
  files on this host; three unchanged scraper tests fail real DNS preflight.
  There were no additional billing or migration failures. Full backend success
  still requires the supported CI environment; this is not a clean local pass.
- The earlier 0068 proof also verified that a data-bearing downgrade is refused
  atomically and an empty downgrade/upgrade remains possible. Historical bridge
  tests preserve their separately verified 0067 checkpoint.
- Local Chromium cannot start under this host's Unix-socket restriction. No
  sandbox controls were changed and no new exploit/private-file probes ran.
  Required CI includes production billing, builder, editor and account browsers.
- Initial published head `dd138524` passed full Backend Tests, Full-Stack Smoke
  and 11 other CI jobs. Its browser gate passed 66 cases and failed two billing
  fixtures (missing canonical plan IDs and an ambiguous status selector), now
  corrected. Final Dodo-only source requires its own latest-head CI. Results
  from the discarded compatibility candidate are not final acceptance evidence.

### Production preflight handoff

Exact Dodo-only head `77d7442b40d8402b905e109db7f366fe57227a0b` subsequently
passed all 14 CI jobs, Vercel, CodeQL and credential scanning. Its production
browser gate passed all 68 billing/builder/editor/Settings cases, in addition to
the quality and hydration suites. Code readiness does not establish production
configuration: a fresh read-only production plans response reported billing
unconfigured, but does not reveal dormant Dodo configuration, the schema marker,
or historical paid-account counts.

The read-only `dodo_billing_preflight.py` diagnostic and `billing_preflight`
Modal wrapper were added for an operator with existing authenticated access.
They neither enable billing nor perform a migration, deploy, provider request,
or transaction. The wrapper uses existing deployment secret bindings and emits
redacted environment/source/image identity, while the script reports static
configuration facts and aggregate database cutover checks. See the exact command
and interpretation in `docs/BILLING_DODO.md`. This follow-up source requires its
own exact-head CI; results for `77d7442b` do not certify later edits.
The final diagnostic suite passed 131 tests, including actual read-only local
PostgreSQL and disposable pre-Dodo schema/history/team-seat preservation checks.
Independent read-only review passed 85 overlapping isolated cases and found no
remaining diagnostic blocker. Existing Modal deployment/CI-visibility tests also
pass. These tests do not certify deployed source, live credentials/catalog, or
complete database constraint equivalence.

CodeQL alert 377 on the initial diagnostic head `6b73de05` identified private-data
flows into its JSON logging boundary. The follow-up separates credential presence
from public settings and validates/rebuilds an exact public output schema at both
the standalone and Modal child-output boundaries. It emits canonical public modes
and current ISO currency constants, rejecting unexpected fields and types without
echoing values. The currency registry is the complete SIX snapshot dated
17 September 2026; no payment runtime currency rules are changed. Tests include
unexpected/nested-field and malformed-type sentinel rejection. No alert
suppression or dismissal is used; the replacement head needs its own successful
CodeQL result before operator handoff.

The follow-up also adds a read-only rollout-safety step before the existing
main/Production migration and deployment boundary, without widening secret/ref
access. It accepts known safe-disabled staging while requiring startup, schema,
historical-access and existing-Dodo-servicing checks. Configured live sales are
held unless an operator separately records acceptance and explicitly sets the
documented Actions variable; this review does not set it. The pure policy cannot
turn that assertion into live provider proof or bypass its other checks.
The final preflight/policy/wrapper suite passed 384 cases, including the two real
isolated database proofs. Additional workflow shell-contract tests verify exact
opt-in and failure propagation. New frontend provider and builder capabilities,
together with new-only mutation URLs, prevent mixed old/new backend instances
from accepting unsafe payment actions or ignoring builder save preconditions.

The production report remains pending. A clean disabled/unconfigured default
can safely leave purchases unavailable, but unknown `required`, partial-key, or
production-test configuration can block the release. No new engine/model
production variables are required by this branch relative to current main.
The candidate remains draft pending exact-head CI and release review. A source
merge can use the conservative automatic guard without declaring a production
rollout successful: unknown configuration/schema/access conditions still stop
the backend deployment before migration. The script is not a substitute for
live Dodo acceptance.

The frozen combined follow-up passed 475 backend tests covering the diagnostic,
rollout policy, Modal wrapper/workflow boundaries, Dodo routes/runtime and builder
capability/concurrent saves. All 1,373 frontend unit tests across 198 files passed,
with TypeScript, full ESLint, focused Ruff and diff checks. The production build
and artifact validator passed with a bounded 2 GB Node heap after an unbounded
attempt compiled successfully but was killed during its type-check phase.
Thirteen new builder
rollout browser cases are included in the production-browser CI gate. Local
browser execution remains blocked by this executor's known Node host-network
interface limitation; those cases require the authoritative CI result.

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
4. Live Dodo merchant/catalog/webhook configuration and an approved production
   schema/rollout plan. Auto billing without configured Dodo keys remains
   unavailable; `required` mode requires them. Historical financial evidence is
   preserved without reactivating its provider. Source merge does not certify
   live Dodo configuration or transaction acceptance.
5. Deployment-specific trusted engine images/caches and real email/Drive delivery
   retain their existing acceptance limits from the builder and engine audits.

No live payment/refund, provider configuration, secret rotation, production
migration, manual deployment or admin-catalog merge was performed.
