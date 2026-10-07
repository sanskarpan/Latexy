# Dodo Payments operations

Latexy creates Dodo hosted checkout sessions from the backend. The backend
selects a configured Dodo product for the requested plan and sends a local
checkout-intent ID in signed checkout metadata. The browser only receives the
hosted checkout URL. The return URL is informational: a signed webhook is the
only path that grants or changes paid access. Checkout disables Dodo's default
currency selector and explicitly sets `billing_currency` because plan prices and webhook validation use the fixed
catalog currency; adaptive currency support needs a separate conversion-aware
quote and reconciliation flow.

## Configure a Dodo environment

Create the products in the matching Dodo dashboard environment first. Set the
catalog price and billing interval to match Latexy's plan configuration; the
server compares the successful payment amount, in the currency's smallest
unit, against its local quote before it grants access. Core plans include tax,
so configure `price.tax_inclusive=true` and match the gross amount. A plan with
`tax_inclusive=false` instead matches the amount before tax. This choice is
stored on each intent by revision `0060`, so later configuration changes cannot
alter the original quote. Configure every plan you
intend to offer:

- Basic, Pro, and BYOK monthly and annual
- Student and Team recurring products
- Weekly recurring and Lifetime one-time products, if those SKUs are enabled

For ongoing subscriptions, Dodo's payment frequency is separate from its total
subscription lifetime. The local sandbox catalog uses monthly/yearly payment
frequency and a 20-year subscription period. Setting the subscription period to
one month would automatically terminate a monthly subscription after that time.

Copy the matching environment's API key, webhook signing key, business ID, and
product IDs into the environment variables listed in `backend/.env.example`.
Use `DODO_MODE=test` with the test key, test webhook key, business ID, and test
product IDs for local verification. Use `DODO_MODE=live` only after the live
catalog and live webhook endpoint are configured. Test and live credentials and
catalog IDs must not be mixed. The backend's default Dodo API hosts are
`https://test.dodopayments.com` and `https://live.dodopayments.com`.

For local development, configure `backend/.env` (or the root `.env` used by
your launcher). Never commit either file. Compose deployments pass the same
variables through to the backend and worker. Kubernetes reads API and webhook
keys from `latexy-secrets`; set the product IDs and amounts in the
`latexy-config` ConfigMap. `k8s/deploy.sh` reads the credentials and mode from
the invoking environment. The mode defaults to `test` if `DODO_MODE` is not
provided.

## Webhook setup

Register `POST /billing/webhook` (prepend a deployment's configured API
prefix, if any) as the Dodo webhook destination and enable the payment, subscription,
and refund events. Select the events used by the reconciliation service:

- `payment.succeeded`, `payment.failed`, `payment.cancelled`.
- `subscription.active`, `subscription.renewed`, `subscription.updated`,
  `subscription.plan_changed`, `subscription.paused`, `subscription.unpaused`,
  `subscription.past_due`, `subscription.on_hold`, `subscription.cancelled`,
  `subscription.failed`, `subscription.expired`.
- `refund.succeeded`, `refund.failed`.

Copy the endpoint's signing key into
`DODO_TEST_WEBHOOK_KEY` or `DODO_LIVE_WEBHOOK_KEY` for the selected mode. If
configured, `DODO_*_BUSINESS_ID` also restricts acceptance to that business.

Latexy verifies the Standard Webhooks signature using the raw request body,
checks timestamp freshness, and stores each `webhook-id` in a durable inbox.
Successful payments must match a local intent, plan metadata, product, currency,
and quoted amount. Subscription lifecycle events update status but do not grant
access. Webhook retries are safe to deliver; investigate entries marked failed
in `billing_webhook_events` and replay after correcting the cause.

## Migration and historical records

Alembic revision `0059` adds provider-neutral identifiers and webhook/refund
tables. It copies existing Razorpay IDs into the new columns and labels those
rows `provider='razorpay'`; the legacy database columns remain for historical
records and rollback. New checkouts and webhooks use `provider='dodo'`. Run the
normal backend migration command before deploying the new application code.

Do not delete historical Razorpay payment or subscription records. Revenue
analytics includes paid Dodo payments and historical paid/captured payment
statuses, subtracting successful partial and full refunds.

Revision `0059` does not cancel Razorpay mandates or import them into Dodo. Before
switching production webhook traffic, reconcile every migrated subscription row
with `provider='razorpay'` and a chargeable status in the Razorpay dashboard,
then cancel or otherwise settle that mandate there. Until an old row is
cancelled, Latexy blocks that account from starting a Dodo checkout or switching
to the free plan; the in-app cancellation endpoint directs the user to support
because new deployments no longer hold legacy Razorpay credentials. This
prevents a second subscription from being created while the old mandate can
still charge.

## Checkout uncertainty

Dodo checkout creation is not automatically retried after a network timeout.
The local intent is retained as `checkout_unknown` because Dodo may have
created a session despite a lost response. A later signed webhook can reconcile
the intent using its metadata. Resolve an abandoned unknown intent only after
checking the Dodo dashboard; do not create a second checkout while the intent is
pending or unknown.

## Coupons and access state

Revision `0061` associates new coupon reservations with their checkout intent.
Confirmed payments redeem reservations. Definitive checkout or subscription
failure releases an unused reservation; an unknown provider result retains it
for reconciliation. A failed individual charge can be retried without consuming
another local coupon use.

Recurring local percentage promotions require a matching Dodo percentage
discount in basis points, unlimited subscription cycles, compatible product
restrictions, and supported eligibility/currency settings. The backend rejects
incompatible provider codes before checkout. A provider discount with an expiry
or finite cycles cannot safely match a local quote that assumes a perpetual
discount. Keep local campaign expiry separate from an indefinite provider
discount, and independently verify discount preservation when changing plans.

Paid plan identifiers remain available for billing history while the entitlement
resolver suspends access for paused/on-hold subscriptions and ends past-due
access when the provider grace period expires. Recovery requires an already-paid
matching subscription; an unpaid lifecycle event cannot activate paid access.

## Local sandbox evidence

See [the October 2026 audit](audits/dodo-sandbox-2026-10-07/REPORT.md) for actual
checkout, signed webhook, decline, renewal, and cancellation evidence, plus
provider refund/resource discrepancies and remaining production gates.

### Restart the verified Windows setup

The current local checkout is `C:\Users\Sansk\Projects\Latexy`. The isolated
Compose project is `latexy-local`; its Windows overrides and interpolation file
are in `%LOCALAPPDATA%\Temp\Latexy-Docker-Local`. They retain the existing database,
Redis, and S3 volumes. The S3 service uses RustFS with the existing MinIO-compatible
endpoint. Application URLs are `http://localhost:5180` and
`http://localhost:8030`; Flower is on port 5555, S3 on 9000, and its console on
9091. PostgreSQL and Redis host ports are 5434 and 6380.

From this checkout, restart application processes with PowerShell:

```powershell
$env:PATH = 'C:\Program Files\Docker\Docker\resources\bin;' + $env:PATH
$localConfig = "$env:LOCALAPPDATA/Temp/Latexy-Docker-Local"
docker compose --project-name latexy-local --project-directory "$PWD" `
  --env-file "$localConfig/compose.env" `
  -f "$localConfig/docker-compose.local.yml" `
  -f "$localConfig/docker-compose.override.yml" `
  up -d --no-deps backend worker beat frontend flower
```

The underlying `postgres`, `redis`, and `minio` services must be running first;
start them with the same Compose options when necessary, then run `minio-init`.
Its corrected command checks the private bucket and exits successfully when it
already exists. Keep the explicit project name and project directory: they
identify the existing stack and source mount.

For local sandbox webhook delivery, the test dashboard webhook targets Dodo's
official outbound relay at `https://wsserver.dodopayments.tech/`. Run:

```powershell
& backend/.venv/Scripts/python.exe scripts/dodo-sandbox-relay.py
```

The script reads ignored root/backend environment files, requires test mode,
connects outbound with the test API key, preserves Standard Webhooks signature
headers, and forwards to local `/billing/webhook`. It reconnects after transport
failure and logs HTTP results without customer payloads or credentials. It does
not replace backend signature verification. Install the normal backend Python
dependencies in the local virtual environment if they are missing. Run one relay
per sandbox business; use a separate terminal and keep it running during payments.
This relay is a development tool; production uses its own HTTPS webhook endpoint.

## Verification checklist

1. Confirm the backend reports billing available in test mode and the expected
   test plans are listed.
2. Start a checkout for each plan type and verify it redirects to Dodo's test
   checkout page.
3. Complete a test payment and confirm one payment row, one processed webhook
   row, and the expected entitlement.
4. Retry the same webhook and confirm it is recorded as a duplicate without
   extending the entitlement twice.
5. Verify failed payments do not grant access; verify cancellation, renewal,
   refund, team-seat, student-verification, and coupon behavior before enabling
   the corresponding plans in production.
6. Repeat the test with the live catalog only after the live credentials and
   webhook endpoint have been independently configured.

Provider references: [Checkout Sessions](https://docs.dodopayments.com/developer-resources/checkout-session),
[Webhook events](https://docs.dodopayments.com/developer-resources/webhooks/intents/webhook-events-guide),
[Webhook security](https://docs.dodopayments.com/developer-resources/webhooks), and
[test versus live mode](https://docs.dodopayments.com/miscellaneous/test-mode-vs-live-mode).
