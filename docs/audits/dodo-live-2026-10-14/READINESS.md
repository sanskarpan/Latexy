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
  must be selected explicitly with `MODAL_BILLING_SECRET_NAME`.
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

Linux deployment parity passed 30 tests after the initial overlay, then 31 after
the source-path repair. Final integrated parity/CI and fresh read-only production
diagnostics remain required after subsequent changes.

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
