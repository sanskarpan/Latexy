# Live Dodo preparation — 14 October 2026

## Scope and current evidence

Baseline main: `d22998e0f45d55fd0a675e4cc622ab603c612d23` (migration head
`0073_d14_subfeatures`). The owner authorized preparing live production payments
using a server-only live key supplied in the original checkout's ignored root
environment file. No credentials, customer identifiers or provider product IDs
are included in this report.

- The live API key authenticated against the official live API with HTTP 200.
  Its local alias was normalized to `DODO_LIVE_API_KEY`; local test mode was
  retained while production readiness is assessed.
- Eight live recurring products were created and then independently re-read.
  Amount, INR currency, tax-inclusive pricing, recurrence, no trial, no discount
  and disabled purchasing-power-parity match the application defaults. Repeating
  the provisioning read found the existing managed products, without duplicates.
- Dodo's live checkout preview returned HTTP 200 and the expected gross INR amount
  for every product. A preview does not charge a card or prove paid fulfillment.
- The production webhook is registered for the 16 payment/subscription/refund
  events documented in the billing runbook. It remains **disabled** until the
  receiving deployment is ready. Its live signing key was saved only in ignored
  local configuration and the dedicated Modal secret.
- `latexy-live-billing` was created in Modal `main` with the mode-separated live
  credentials/product mappings and **`BILLING_MODE=disabled`**. The existing opaque
  backend, storage and Redis secrets were not replaced. The new optional binding
  is selected by the non-secret repository variable
  `MODAL_BILLING_SECRET_NAME=latexy-live-billing`; this takes effect only in source
  containing the new workflow binding. Renderer/live-acceptance flags remain unset.
- Weekly and Lifetime were not provisioned. Real academic-mailbox Student checkout
  remains pending under the owner's earlier instruction; catalog preparation and
  preview are not Student verification acceptance.

| SKU | Gross INR | Recurrence |
|---|---:|---|
| Basic | 299 | Monthly |
| Basic Annual | 2,871 | Annual |
| Pro | 599 | Monthly |
| Pro Annual | 5,750 | Annual |
| BYOK | 199 | Monthly |
| BYOK Annual | 1,910 | Annual |
| Student | 299 | Monthly |
| Team | 2,499 | Monthly |

## Renderer and deployment checks

A new bare renderer image was inspected independently of application images:
`im-mF0rpCXgH2MBjw3TKMYXEf`, asset fingerprint
`db98401df2e8c2d2b5a158ef96dcca6be5cfc36f2fc8451c693cb4018bf6c4a9`.
It contains its version marker and no backend source or application credentials.

The pinned SDK 1.5.4 Linux certification passed the exact image/asset comparison,
fontspec, all three private-file access denials, and Latin/Hindi/CJK PDF text and
glyph checks in a bounded credential-free VM. A separate synthetic builder-to-VM
probe used the current API image and production Modal renderer selection. It
generated a 90,126-byte PDF, verified text/glyphs, recorder and bounded SyncTeX,
and confirmed the repository-managed preamble. This proves the generated-source
renderer path; it explicitly does **not** certify the database-backed owner,
broker, storage, billing or browser pipeline.

Actual cloud diagnostics found and prompted repairs for:

1. Operator artifacts under `backend/temp` were included in image snapshots;
   a changing diagnostic log aborted a build. Temporary files, virtual
   environments and pytest caches are now excluded from source images.
2. Modal autoloads the module under `/root`, while the trusted source is baked at
   `/backend`. Remote trusted-asset reads now select the baked source directory.
3. An optional secret binding selected only in the local build environment changes
   the dependency count when the remote module imports. The validated binding
   name must be snapshotted into every application image for consistent imports.

The latest main changes from #1885 (`7cb1c8b7`) were integrated without conflicts.
Linux deployment parity passed all 31 tests after the source-path and binding
repairs, and all 31 again after the independent review narrowed live credential
bindings to the API, billing preflight and API-configuration renderer preflight.
Unrelated workers, schedulers and migrations retain their original bindings.
Ruff and whitespace checks passed. Full PR CI remains required on the final head.

The repaired read-only billing preflight executed on reviewed source
`cae711323ce928d935e1615e1fe7b27d196bc7e2`, candidate migration image
`im-cFrimampsDvyo8zpPzmEXe`, in actual Modal `main`. Its source-files fingerprint
was `07edc8e81e039dca52eccc9ee08392efacaba3b36ec95bfbdb567276b9aae1a0`.
It confirmed production classification, strict billing configuration validity,
live-mode key/product configuration and disabled new purchases. It returned
`diagnostic_error`, with `database.failure_stage=connect`; no schema revision or
historical-account counts were established. This is a connection-stage finding,
not permission to migrate or an assertion of the underlying cause.

A separate fresh task using the existing base, storage and Redis bindings made
only bounded connectivity reads. Cache and Celery broker PINGs passed. Job-state
Redis returned a Redis error; a PostgreSQL connection attempt timed out. These
results do not certify Redis capacity, existing job recovery or database safety.

The next private comparison found the same Neon connection could complete a
read-only repeatable-read transaction without the diagnostic's injected startup
GUCs, while the startup-options attempt timed out even with a 15-second bound.
The latest job-state PING passed; the earlier Redis error is not a proven quota
or credential fault. The diagnostic now preserves URL TLS/routing options and
uses SQLAlchemy's read-only transaction setting, an explicit read-only check and
transaction-local statement/lock timeouts. It still rolls back and never commits.
See [Neon's startup-parameter guidance](https://neon.com/docs/connect/connection-errors#unsupported-startup-parameter)
and [SQLAlchemy's read-only support](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#setting-read-only-deferrable).

On source `eaa31fc27f11be1f2537a3abc34b3dba8e7d41a8`, the repaired diagnostic
completed schema and aggregate reads against recognized production revision
`0059`. Its actual rollout invocation then exited successfully with
`safe_to_rollout=true`, `sales_state=safe_disabled`, no rollout reasons and live
acceptance unverified. [The exact public-safe workflow decision](rollout-preflight.json)
retains the source/image/environment/fingerprint; detailed configuration and
aggregate counts remain private. This permits the billing portion of a disabled
rollout, not live sales or bypass of independent release checks.

Local Linux verification: 490 billing-preflight tests passed; two PostgreSQL
integration tests were deliberately deselected because no local disposable DB
was running. Separately, all 142 deployment/wrapper/renderer-configuration tests
passed. Full CI must run the actual PostgreSQL cases. Initial CI identified stale
static fixture expectations after the binding split; those expectations were
updated to model the actual API bindings and image environment.

## Production holds

During this review the public serving backend still advertised the older
unconfigured Razorpay billing contract. `/health` returned a degraded state with
Redis unavailable, and `/readyz` returned HTTP 503. Those are direct observations,
not a diagnosis of Redis credentials, quota or provider capacity.

New live purchases remain disabled. Do not enable the endpoint, sales mode or
`DODO_LIVE_BILLING_ACCEPTED` merely because the key, products, image or previews
passed. Complete the current-source read-only schema/access diagnostic, resolve
its demonstrated blockers and production Redis readiness, follow the reviewed
migration/deployment sequence, then verify serving identity and owned recovery.
Live payment, webhook delivery, entitlement, cancellation and refund acceptance
require an explicitly authorized transaction and remain separate from previews.
