# Dodo Payments operations

Dodo Payments is Latexy’s only active payment provider. There is no Razorpay
SDK, checkout, webhook handler, provider selector or fallback in this application.
Historical financial rows and their retained migration columns are preserved;
that preservation does not enable a legacy payment integration.

Latexy creates Dodo hosted checkout sessions from the backend. The backend
selects a configured Dodo product for the requested plan and sends a local
checkout-intent ID in signed checkout metadata. The browser only receives the
hosted checkout URL. The return URL is informational and cannot prove payment. Paid access requires
either a verified signed webhook or the authenticated owner-only recovery flow,
which independently reads and cross-checks the provider checkout, payment,
customer, product, metadata and immutable local quote. Checkout disables Dodo's default
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
stored on each intent by revision `0066`, so later configuration changes cannot
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
provided. Production/staging checkout with test credentials is rejected at startup;
provider API calls and webhook processing also reject test mode at runtime, even
when startup validation is skipped. Unconfigured `auto` billing stays unavailable.
Disabling new sales does not prevent authenticated servicing of existing live
Dodo subscriptions through cancellation or verified checkout recovery.

### Read-only production preflight

Before merging a release that triggers automatic production deployment, inspect
the existing configuration without copying secret values into a terminal or chat.
From a **clean checkout of the reviewed PR revision**, with the already-authorized
Modal CLI account selected, run from `backend/`:

```bash
modal run --env main modal_app.py::billing_preflight \
  --source-revision "$(git rev-parse HEAD)" --expected-environment main
```

This invokes candidate source in an ephemeral diagnostic container using the
same existing secret bindings and migration image as deployment. It does **not**
deploy the candidate, apply migrations, change settings, or contact Dodo. It
does not establish that the candidate image is already serving production.
The JSON report identifies the application, actual and expected Modal environment,
diagnostic image ID, caller-reported source revision, source-file fingerprint,
and expected repository migration head. The actual environment and image ID
come from [Modal's reserved runtime metadata](https://modal.com/docs/guide/environment_variables).
An environment mismatch refuses the database diagnostic. The wrapper also blocks
acceptance when Modal `main` is classified as development/test by the application's
`ENVIRONMENT` setting; production billing guards require production/staging.

The standalone `python scripts/dodo_billing_preflight.py` entry point is also
available for an environment whose configuration is already supplied. A local
environment report alone is not evidence about the deployed Modal secret bundle.
Both entry points print only redacted configuration facts, public catalog
expectations, database revision/schema classification, and aggregate cutover
counts. Database queries run in an explicitly read-only transaction with bounded
timeouts and rollback. Connection strings, credentials, product/customer IDs,
individual users and exception details are never included. Catalog checks concern
local configuration only; the live merchant catalog still needs separate acceptance.
Billing-only startup validity and checkout availability are reported separately;
the diagnostic does not revalidate unrelated authentication/storage credentials.
Both output boundaries rebuild an exact public schema: unexpected keys, nested
identifiers, invalid types and arbitrary messages are rejected without echoing
them. Credentials and product IDs are reduced to presence booleans before public
configuration handling. Public modes and currency codes are emitted as canonical
constants. Currency validation uses the complete 178-code current ISO 4217 snapshot
published by [SIX on 17 September 2026](https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml).
An unknown/new currency needs diagnostic review or a reviewed registry update;
this does not change the application's supported currencies or verify Dodo's catalog.

Exit 0 means the script's static readiness checks pass. Exit 1 is a readable
report requiring review, including ordinary pre-migration or disabled/unconfigured
billing states; it is not an instruction to enable billing or migrate. Exit 2
means diagnostics were incomplete and only a fixed error code is emitted. Share
the redacted JSON report, not environment files or secret values. A candidate
with `auto` billing and no active-mode keys can start with paid purchases disabled;
`required` billing without both active keys, partial keys in `auto`, or configured
test-mode billing in production fails startup deliberately. The deployment
workflow validates settings during its migration step before replacing the API.
Unresolved historical paid-account counts require a deliberate access cutover
decision; financial-row preservation alone does not establish ongoing access.

### Automatic rollout guard and later live activation

The existing main-only, `Production`-environment deployment workflow now runs
the same diagnostic with `--purpose rollout` **before** `migrate` and rolling
deployment. It uses the existing credential bindings; PR CI does not gain
production credentials. A failed check stops later deployment steps.
Public workflow logs contain only execution identity and fixed rollout decisions;
the detailed configuration and aggregate counts remain in the operator-only
default report rather than being copied into deployment logs.

Incomplete database diagnostics always block rollout (script exit 2). The
operator report may include `database.failure_stage`; public rollout output uses
the corresponding fixed `rollout_database_<stage>_failed` reason. Stages are:

- `configuration`: database URL configuration could not be interpreted.
- `engine`: the local database engine could not be constructed.
- `connect`: acquiring or entering the connection failed.
- `read_only_setup`: transaction setup or its read-only verification failed.
- `schema_metadata`: reading the allowlisted schema columns failed.
- `schema_revision`: reading or classifying the Alembic revision failed.
- `aggregate_counts`: computing the aggregate access counts failed.
- `cleanup`: rollback, connection exit or engine disposal failed; this takes
  precedence if cleanup also fails after an earlier diagnostic failure.

These codes identify the operation that failed, not its root cause. They never
contain exception text, connection details, SQL, credential values or customer
identifiers. A valid incomplete report does not imply malformed public output.
Read-only enforcement, timeouts and all rollout holds remain unchanged; do not
infer a pooler, credential or production-schema fault from a stage alone.

The rollout policy is deliberately separate from live-sales readiness:

- Strict billing startup rules, production/staging classification and Modal
  targeting must pass, even when startup validation is otherwise bypassed.
- The schema must be a recognized mainline upgrade path or the current head.
  Conflicting legacy 0061, partial/mismatched schemas, unknown revisions and
  incomplete diagnostics stop the rollout. A known pre-migration revision may
  proceed to the following ordinary migration step.
- Historical paid-user, live-mandate and inherited-team access counts must be
  zero. The guard cannot authorize removal or migration of those entitlements.
- Existing live/pending Dodo intents require live API and webhook configuration
  for servicing, even when new sales are disabled.
- `BILLING_MODE=disabled`, or `auto` with no active-mode keys, can pass as
  `safe_disabled`. This allows staged source rollout without opening purchases.
- Configured live sales remain on hold by default. The repository Actions variable
  `DODO_LIVE_BILLING_ACCEPTED` must be exactly `true` to release only that hold.
  Absent, empty or other values mean false. No variable is created or set by this
  change. The override cannot bypass startup, environment, schema, historical
  access, existing-Dodo servicing or local catalog checks.

The acceptance variable is an operator assertion, **not evidence by itself**.
Before an authorized operator sets it, record acceptance of the live merchant,
mode-separated credentials and webhook destination; every offered product's
amount/currency/tax/recurrence contract; verified payment and lifecycle delivery;
and the documented refund, currency and supported-plan-change boundaries. Use
only separately authorized transactions and mailboxes. Keep unaccepted optional
SKUs unavailable. Record the reviewed schema/backup and account-cutover plan.
Revisit this acceptance when the merchant, modes or catalog contract changes.
The diagnostic never performs these actions or declares live payments verified.

If this guard blocks backend rollout while a newer frontend is published, the
frontend refuses payment mutations unless the server advertises Dodo explicitly.
Its mutation URLs are Dodo-specific, so a request routed to an old instance fails
without falling back to old provider behavior. Guided-builder editing likewise
requires a versioned capability and new-only request paths; existing history and
manual source access remain available. These protections do not claim a blocked
backend release was successfully deployed.

## Webhook setup

Register `POST /billing/webhook` (or the explicit `/billing/dodo/webhook` alias) (prepend a deployment's configured API
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
Revision `0068` records the immutable provider resource ID for each new inbox
entry. Signed retries may carry an updated resource snapshot; they must still
match the original event type, resource ID and event timestamp. Processed events
remain idempotent. Historical entries without saved identity retain exact-body
matching, so investigate changed-body retries for those rows rather than
rewriting their evidence.

Successful payments must match a local intent, plan metadata, product, currency,
and quoted amount. Subscription lifecycle events update status but do not grant
access. Webhook retries are safe to deliver; investigate entries marked failed
in `billing_webhook_events` and replay after correcting the cause.

## Migration and historical records

Alembic revision `0065` adds provider-neutral identifiers and webhook/refund
tables. It copies existing Razorpay IDs into the new columns and labels those
rows `provider='razorpay'`; the legacy database columns remain for historical
records and rollback. New checkouts and webhooks use `provider='dodo'`.
A historical live mandate ID blocks accidental duplicate enrollment pending
operator reconciliation; a migrated Free row with no mandate ID does not block
Dodo checkout. The application never calls a legacy provider to resolve it.

**Revision 0061 has two historical meanings.** The pre-renumbering Dodo branch
used `0059`–`0061` for billing, while the coordinated mainline uses `0059` for
OAuth verification and `0060`–`0064` for the resume engine. A database whose
`alembic_version` is the old Dodo `0061` must not run ordinary `alembic upgrade
head`: Alembic would interpret that marker as the engine's render-manifest
migration and could try to re-add billing columns and tables later. Back up the
database and use `backend/scripts/bridge_legacy_dodo_0061.py` only after the
schema review. It requires the selected database name explicitly, accepts only
development/test with `DODO_MODE=test`, verifies the complete legacy billing
schema and financial identifiers, applies OAuth and engine migrations
`0059`–`0064` in one transaction, preserves financial and user-entitlement
fingerprints, and advances to the verified checkpoint `0067`. The current repository has one
head at `0068`; after the bridge transaction completes, run the ordinary
`alembic upgrade head` on that same verified database to add webhook identity.
The bridge refuses other repository heads until separately reviewed. It refuses partial/unknown
schemas and repeat runs. Example for a disposable clone:

```powershell
python backend/scripts/bridge_legacy_dodo_0061.py `
  --expected-database latexy_dodo_bridge_20261008 --dry-run
```

Only after the disposable clone passes the dry run and review, apply with:

```powershell
python backend/scripts/bridge_legacy_dodo_0061.py `
  --expected-database latexy_dodo_bridge_20261008 --apply
```

For the exact local database named `latexy`, the additional
`--allow-primary-local-database` flag is required. Stop the API, workers, and
beat before applying to that local database. The bridge does not perform a
provider API call. A mismatch must be investigated with a database copy; do not
stamp `0067`, drop columns, or rerun billing migrations to work around it.
Production/staging cutover still needs a separately reviewed backup, stop-write,
and migration plan.

Billing revisions `0065`–`0068` fail closed on downgrade when provider-neutral
payment/subscription/webhook/refund records, saved tax quotes, or linked/reserved
coupon redemptions would be lost. Treat a billing release rollback as an
application-code rollback that leaves the database at its current billing head; restoring a
pre-billing database requires a verified backup and reconciliation of every
payment accepted after that backup. Do not use `alembic downgrade` as the normal
release rollback procedure.

Do not delete historical Razorpay payment or subscription records. Revenue
analytics includes paid Dodo payments and historical paid/captured payment
statuses, subtracting successful partial and full refunds.

Revision `0065` preserves history; it neither creates nor transfers mandates.
If a historical subscription row contains an actual unresolved mandate ID,
Latexy blocks a second checkout and directs the owner to support for reconciliation.
Rows without a mandate ID do not block Dodo. This read-only check does not enable
legacy checkout, cancellation, webhook processing or any legacy provider API call.
Do not erase financial evidence to bypass that guard.

## Checkout uncertainty

Dodo checkout creation is not automatically retried after a network timeout.
The local intent is retained as `checkout_unknown` because Dodo may have
created a session despite a lost response. A later signed webhook can reconcile
the intent using its metadata. Resolve an abandoned unknown intent only after
checking the Dodo dashboard; do not create a second checkout while the intent is
pending or unknown.

## Coupons and access state

Revision `0067` associates new coupon reservations with their checkout intent.
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
access when the provider grace period expires. Scheduled cancellations end access at the paid
period boundary even when the final cancellation webhook is delayed or missing,
including access inherited through a team seat. Recovery requires an already-paid
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
