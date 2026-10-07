# Dodo migration audit and sandbox evidence

Review date: 7 October 2026 (Asia/Kolkata). Base: `main`,
`787b935136fcaf63709fb8adc438eb7e3b1ab1fe`. Existing uncommitted product,
resume editor, design, auth, and infrastructure changes were preserved.
Upstream advanced by 32 commits during the review. Main was fast-forwarded
after backing up all existing work; the three overlapping editor/auth files
were merged semantically to retain both upstream fixes and local enhancements.
At the user's request, the current implementation and existing local enhancements
are being preserved together in a checkpoint branch and pull request. Further
implementation and verification are paused until user approval. This report
contains no credentials or customer payment details.

## Audit and architecture

The previous payment service imported the Razorpay SDK, created provider plans,
reserved local coupons against Razorpay offers, created recurring subscriptions,
verified checkout signatures, and reconciled provider webhooks. The billing UI,
API contract, configuration, deployments, dependency locks, database identifiers,
analytics, referrals, and subscription entitlements depended on that flow.

The replacement flow is:

`Authenticated user -> billing UI -> authenticated backend -> persisted checkout intent -> Dodo hosted checkout -> signed webhook -> durable inbox -> payment/subscription ledger -> entitlements, analytics, referrals, notifications`.

The backend chooses customer identity, product, plan, amount, currency, and tax
basis. `DodoProvider` handles authenticated provider HTTP requests; the payment
service owns business state. Redirect query parameters convey navigation only.
Checkout returns refresh subscription state from the authenticated API.

The runtime Razorpay SDK, API calls, checkout widget, signature verification,
webhook endpoint, and credential configuration were removed. Historical schema
columns, migration history, and the guard against starting a second chargeable
subscription while an old Razorpay mandate exists remain deliberately traceable.
The resume parser's example company name is unrelated to payment integration.
Existing Razorpay mandates need reconciliation/cancellation at the old provider;
database migration cannot cancel a remote mandate.

## Implementation map

| Area | Files / decisions |
| --- | --- |
| Provider adapter | `backend/app/services/dodo_provider.py`: fixed test/live hosts, Bearer auth, checkout/subscription/payment/portal/refund/discount APIs, bounded timeouts, sanitized errors; no automatic checkout creation retries |
| Business state | `backend/app/services/payment_service.py`: persisted intent, signed webhook inbox, server quote checks, ownership/product matching, lifecycle, refunds, coupons, student/team behavior, legacy mandate guard |
| API | `backend/app/api/routes.py`: authenticated server identity; hosted checkout contract; `POST /billing/webhook` |
| Models / migrations | `backend/app/database/models.py`; `0059` preserves historical provider identifiers and adds payment/refund/webhook state; `0060` stores quote tax basis; `0061` tracks reserved/redeemed/released coupons against intents |
| Frontend | Billing page, subscription manager, API client: hosted checkout, backend state refresh, current-plan and scheduled-cancellation state |
| Reporting | `backend/app/services/analytics_service.py`: paid historical/Dodo gross revenue with successful partial/full refunds deducted once |
| Deployment | Environment examples, Compose, Kubernetes configuration, dependency requirements and locks |
| Local development relay | `scripts/dodo-sandbox-relay.py`: official outbound protocol, local signed route, test-mode guard, reconnect, no customer payload logging |
| Local health | `backend/app/core/worker_healthcheck.py`: checks this worker's reply, matches the Redis transport separator, runs with Python isolated mode |

Durable webhook keys are `(provider, event_id)` with a payload digest. Signatures
cover raw bytes, event ID, and timestamp; timestamps outside five minutes and
wrong-business events are rejected. Payments must match local intent ownership,
product, quantity, currency, quote, and tax basis before access is granted.
Recurring payments sometimes omit `product_cart`; authenticated subscription
lookup supplies the product and verifies ownership in that case.

Quote tax basis is immutable per intent. Tax-inclusive catalog quotes match the
gross paid amount; exclusive quotes match the subtotal. Payment and lifecycle
events use provider billing dates so the same cycle does not extend twice.
Charge failures remain retryable; a fully validated late successful charge is
still recorded after terminal subscription failure/cancellation, without
reactivating access, changing closed periods, consuming a released coupon, or
qualifying referral rewards. A late capture needs explicit financial reconciliation. Unknown checkout creation retains its intent
because a timeout may occur after the provider created a session.

Refund reconciliation locks the payment ledger row, checks currency and aggregate
amount, and retains successful refund state when an older failure arrives.
Referral and notification handling stays within the existing application flow.
There was no separate provider payout/commission integration to migrate.

## Real sandbox verification

These results used the supplied test key, real Dodo sandbox products, documented
test cards, and Dodo-generated webhook signatures. No live payment was made.

| Scenario | Evidence / result |
| --- | --- |
| Catalog setup | Eight recurring sandbox products: Basic/Pro/BYOK monthly and annual, Student, Team. Authenticated product reads confirmed INR price, inclusive tax, cadence, and 20-year subscription horizon |
| Monthly India checkout | `pay_0NpAmEbPJR64QPSUIohmb`: succeeded, INR 29,900 minor units, tax 4,561. Real signed payment activated Basic after fixing omitted recurring `product_cart` reconciliation |
| Monthly US billing address | `pay_0NpApcUA2NdRzLFkK86Qw`: succeeded, INR 29,900, tax 0. Browser checkout displayed INR 299 and returned to Basic ACTIVE in the local billing UI |
| Forced recurring renewal | Set sandbox subscription `sub_0NpApcUHaGeSSDtcg7CjQ` next billing date to `2026-10-06T20:26:40.781806Z`; `pay_0NpAs3R1Ce0pDhazNccjD` succeeded, INR 29,900. Signed `subscription.renewed` and `payment.succeeded` returned HTTP 200; provider next date became `2026-11-06T20:26:40.781806Z` |
| Cancellation | Local authenticated cancellation successfully set provider `cancel_at_next_billing_date`; local state became `cancel_scheduled`, retaining paid access through the period |
| Declined payment | Documented sandbox decline card produced `pay_0NpAuDWrioz7BRJ228zNe`, status failed, `DO_NOT_HONOR`; real signed payment/subscription failure webhooks returned HTTP 200; authenticated customer state remained Free/inactive |
| Retry with compatible coupon | The failed customer started a fresh Basic checkout with a sandbox-only perpetual 10% provider coupon. `pay_0NpAw5O8d55mRdcybjcph` succeeded at INR 26,910, Basic activated, local coupon used count was 1/redeemed |
| Discounted recurring renewal | `pay_0NpAxTpLo9tnOewf17aEo` succeeded at INR 26,910 after a second forced billing date. Real signed renewal/payment events returned HTTP 200; the coupon use count remained 1 |
| Pause and resume | After final service reload, real provider pause/unpause events returned HTTP 200. Authenticated quotas changed to Free's 10 compilations/day while paused and restored Basic's 400/month when active |
| Coupon reservation release | A fresh checkout after reload persisted a linked `reserved` redemption and raised used count from 1 to 2. Cancelling that unused intent through the Free-plan action released the reservation and restored used count to 1 |
| Duplicate checkout | A second create request while an intent was pending was rejected rather than creating another charge |
| Refund attempt | Provider rejected test partial refund with HTTP 409 `INSUFFICIENT_WALLET_FUNDS`. No refund was created; real provider refund lifecycle is not verified |
| Basic annual | `pay_0NpBFToZYAPEf9Ld1BImg`: succeeded, INR 287,100 minor units, tax 43,795. Provider, local paid ledger, authenticated subscription and annual entitlement matched; end-of-period cancellation was scheduled |
| Pro monthly | `pay_0NpBHD8AuoPbvQfwR2QTp`: succeeded, INR 59,900 minor units, tax 9,137. Provider, local paid ledger and authenticated Pro access matched; provider confirmed end-of-period cancellation |

The official outbound Dodo webhook relay was used to deliver signed events to
the local backend without an inbound public tunnel. Original signed artifacts
and disposable test-account credentials remain only in ignored local temporary
files. The relay follows the official CLI wire protocol. Real signature checks
remained enabled and succeeded.

## Provider and configuration limitations

1. Dodo subscription GET reports `currency=USD` and
   `recurring_pre_tax_amount=310` for the US test subscription, although both
   actual first and renewal payment objects report INR 29,900. This conflicts
   with the documented subscription currency meaning. Actual payment objects
   are the charge evidence; do not silently reinterpret a USD subscription
   amount as INR. Plan-change/proration reconciliation needs independent
   validation of the provider resource discrepancy.
2. Sandbox refund completion is blocked by the provider wallet error. Official
   documentation says test refunds are simulated; it provides no documented
   sandbox wallet-funding remedy. Dodo support/account configuration must resolve
   this before claiming real refund lifecycle verification.
3. Weekly and Lifetime remain disabled because reviewed prices/product IDs were
   not supplied. No commercial prices were invented.
4. Basic annual and Pro monthly have separately verified transactions in addition
   to Basic monthly. Pro annual, BYOK monthly and BYOK annual reached the sandbox
   success simulator, but their full provider/ledger/access reconciliation is
   not certified in this checkpoint. The local relay had stopped during an
   interruption and was restarted; recovery for events missed while offline is
   pending. Do not repeat those payments. Team's created checkout has not been
   completed. Student remains pending an authorized academic test mailbox;
   verification was not bypassed and no unsolicited verification email was sent.
5. Test catalog/webhook IDs cannot be reused as live IDs. Existing local success
   does not establish live merchant approval or live webhook delivery.
6. Closing an unused local checkout does not invalidate a hosted Dodo URL.
   A subsequent verified charge remains traceable in the ledger with access
   closed; operations must reconcile/refund it explicitly. Provider refund
   capability and this support procedure need acceptance before production.

## Tests and deployment validation

Backend tests use a separate `latexy_test` database and Redis databases 15/14.
Test fixtures clear inherited Dodo credentials so mocked tests cannot call the
real provider. Focused adapter, billing, subscription, analytics, pricing,
referral, and entitlement suites provide negative and state-transition coverage.
Consolidated command results and additional coverage are recorded below.

- Final consolidated backend run: 122 passing tests across adapter, billing,
  subscriptions, entitlements (service/enforcement/wiring), pricing, referrals,
  analytics, worker health, and webhook recovery; exit 0 in 60.18 seconds on the
  rebuilt backend runtime (earlier source run: 103.29 seconds). This includes the final
  pause/resume, team-member status/grace-period, delayed charge traceability, and
  cancelled-checkout underquote regressions.
- Frontend: 173 Vitest files / 1,076 tests passed with two workers on the integrated latest main
  source; lint and TypeScript checks passed.
  That full suite used the development dependency graph. The additional full
  Linux Vitest run against the frozen production lock exposed two test-fixture
  environment portability issues, which were corrected; its final rerun result
  remains unconfirmed at this checkpoint. The successful frozen-lock production
  image build and HTTP/static-asset probes below are separate confirmed results.
- Additional adapter/recovery run: 22 passing tests. These include connection
  errors/timeouts, conflicting signed replays, distinct event IDs for one payment,
  missing signed fields, and simulated interruption after durable inbox commit
  followed by a fresh service/session processing redelivery.
- Ruff passed for the payment adapter/service, entitlement/analytics service,
  worker probe, local relay, financial regressions, and all three new migrations.
- Latest-main deployment manifest checks: 85 passed in 16.91 seconds, including
  the non-root font-cache and workspace standalone runner regressions. The lock-version parser
  now handles platform markers and file reads use UTF-8 on Windows.
- Production Compose configuration parsed successfully with placeholder values
  and no deployment; required production variables remain enforced.
- The reusable local sandbox relay passed raw-body/header forwarding, transport
  failure, and live-mode guard checks and connected to the real official relay.
- Development database is migrated through `0061`; tests use the same migration
  head in their independent database.
- Credential scan of changed/new non-ignored paths found zero matches for the
  active API/webhook keys or disposable account passwords/tokens. Root/backend/
  frontend environment files and temporary verification files are ignored.

Team member access now follows the active seat owner's linked team subscription
status and grace period. Pausing a team suspends access without permanently
revoking its seats, allowing recovery on resume. Both paid recurring sandbox
accounts were scheduled for cancellation after the renewal experiments.

The Windows production build compiled and type-checked all 44 static routes,
then failed copying pnpm workspace symlinks into standalone output (`EPERM`).
This is an artifact-build failure and is not reported as a successful build.
The Linux build exposed a Monaco AMD-import resolution error and a Better Auth
two-factor response union in `SecuritySettings`. The exact bare-import alias to
the ESM editor API and guarded response handling fixed those failures.

The final `frontend/Dockerfile.prod` image was built from the frozen root
workspace lockfile (`vite@8.0.16`, `esbuild@0.28.1`), generated all 44 static
pages, and passed standalone artifact validation. Starting that image caught
the monorepo runner-path defect: its entrypoint is `frontend/server.js` and its
static/public files must also live under `frontend/`. The corrected image
`latexy-validation-20261007` built and started successfully. Home and billing
returned HTTP 200 HTML, a referenced CSS asset returned HTTP 200 (72,454 bytes),
and `sw.js` returned HTTP 200 (24,608 bytes). The disposable probe container was
removed and the image retained; the normal frontend on port 5180 was restarted.

The backend development image was rebuilt using the hash-verified dependency
lock and recreated for API, worker, beat, and Flower. Installed-package probes
confirm that Razorpay is absent from both API and worker. Dodo remains in test
mode, the database is at `0061`, and readiness/health checks pass for database,
Redis, cache, and private object storage.

On this Windows Docker bind mount, source changes did not reliably trigger
development reloads. The frontend was restarted to load the corrected billing
controls; the final backend recreate loads the current payment/entitlement code
and enables local WatchFiles polling. Tests import current source in fresh
processes, so passing tests alone cannot establish that an old running service
has picked up changes.

## Additional local application checks

The running API, billing page, and S3 health endpoint returned HTTP 200, and the
worker passed its targeted health probe. The corrected private S3 bucket
initializer exited 0. A real anonymous `pdflatex` job
`94b0e270-4a99-4865-a618-e45667f84be2` completed through API/Celery/Redis and
returned a valid 13,766-byte PDF.
After the dependency/image rebuild, authenticated job
`b76ad22a-f4fe-49f2-8fd7-97b947f3b1d0` also completed through the actual worker
and returned a valid 15,206-byte PDF over the owner-authorized download route.

The Hindi/LuaLaTeX fixture is **not verified** on this local runtime. The first
attempt exposed a missing writable Lua font cache for the non-root system user;
both backend Dockerfiles now provision an owned cache under the permitted TeX
runtime tree, and the local overrides mount the corresponding writable paths.
The next real job passed that cache initialization but failed inside
`luaotfload-multiscript.lua` while loading Unicode data on the installed
LuaHBTeX 1.18 / TeX Live 2025 development build. A compatible, sandboxed Lua
runtime and its complete font/template matrix still need acceptance, consistent
with the open resume-engine render certification work. This limitation does not
establish a payment failure, and neither this report nor the local health check
claims that every engine or project feature is certified.
The rebuilt runtime repeated the same Lua font-loader failure in actual job
`90b9d44a-8a36-470a-bbf0-41ea5298721c`; its compilation log was checked through
the authenticated API. Sandbox file-access restrictions were retained.

## GitHub issue reconciliation

Six completed issues were closed with merged-main evidence in comments:

- #1335, #1337, #1342, #1731: [PR #1751](https://github.com/sanskarpan/Latexy/pull/1751),
  merge `dce0bf4108fa0ab3f72b8991617bcae08afaa8e8`.
- #1806: focused [PR #1808](https://github.com/sanskarpan/Latexy/pull/1808),
  integrated through [PR #1803](https://github.com/sanskarpan/Latexy/pull/1803),
  main `fc8d947bedd82efe1b52577e8e23164d3d823168`.
- #1807: focused [PR #1811](https://github.com/sanskarpan/Latexy/pull/1811),
  integrated through PR #1803 at the same main commit, with actual dependency
  audit artifact and deployment evidence in its comment.

All 47 open issues were reviewed individually in [ISSUES.md](ISSUES.md),
including GitHub bodies/comments and linked-PR state. A final refresh added the
confirmed GitHub OAuth owner-dispatch issue #1829. The snapshot also included #1828,
#1826, and #1822. Local payment/design/editor changes are uncommitted and are not
merged evidence for closing remote issues. Weekly/Lifetime pricing, PDF
accessibility certification, CI/deployment certification, resume engine epics,
and product gaps remain open wherever the required implementation or external
verification is outstanding.

## Required configuration and production cutover

Local `.env` and `backend/.env` contain the supplied test credentials and are
ignored by Git. No API key is placed in frontend code or committed files.
Set `DODO_MODE=test`, `DODO_TEST_API_KEY`, `DODO_TEST_WEBHOOK_KEY`,
`DODO_TEST_BUSINESS_ID`, and the enabled `DODO_TEST_PRODUCT_*` variables.
Local coupon mappings additionally require compatible provider discount codes.
See `backend/.env.example` and `docs/BILLING_DODO.md` for the complete names.

For production:

1. Resolve the provider refund/resource discrepancies and finish the outstanding
   transaction/lifecycle matrix for enabled SKUs.
2. Create independent live products, matching currency, amount, inclusive tax,
   cadence, subscription horizon, and supported discount configuration.
3. Configure an HTTPS live `POST /billing/webhook` endpoint, obtain its signing
   key, and enable relevant payment/subscription/refund events.
4. Set `DODO_MODE=live`, `DODO_LIVE_API_KEY`, `DODO_LIVE_WEBHOOK_KEY`,
   `DODO_LIVE_BUSINESS_ID`, and reviewed `DODO_LIVE_PRODUCT_*` values. Use
   `BILLING_MODE=required`, correct public frontend/CORS URLs, and normal
   production database/storage/auth/email secrets.
5. Back up the database, apply migrations through `0061`, reconcile all old
   chargeable Razorpay mandates, and deploy matching backend/worker/frontend
   versions. A rollback must not resume old charges without reconciliation.
6. Independently verify live delivery, payment state, access, cancellation, and
   refund monitoring before enabling broad paid traffic.

## Official references

- [Checkout sessions](https://docs.dodopayments.com/developer-resources/checkout-session)
- [Subscription behavior](https://docs.dodopayments.com/features/subscription)
- [Webhook signing](https://docs.dodopayments.com/developer-resources/webhooks)
- [Sandbox testing and renewal simulation](https://docs.dodopayments.com/miscellaneous/testing-process)
- [Test versus live mode](https://docs.dodopayments.com/miscellaneous/test-mode-vs-live-mode)
- [Discount by code](https://docs.dodopayments.com/api-reference/discounts/get-discount-by-code)
- [Official local relay implementation](https://github.com/dodopayments/dodopayments-cli/blob/main/src/commands/webhook/listen.ts)
