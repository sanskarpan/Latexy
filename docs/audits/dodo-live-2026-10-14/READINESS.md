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
- The owner signed in to the Latexy merchant dashboard. Its verification page
  reports verification complete and live payments active. This confirms merchant
  status, not a completed application payment or entitlement.
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

The full CI run on `b172fff6886d1b3629090eedfde8b5a337cf05f9` passed, including
backend PostgreSQL tests, full-stack smoke, isolated real compile/preview,
cross-browser quality, security analysis and the Vercel preview. Main then
advanced through #1886 and #1882; these were integrated without conflicts and
the final combined head requires its own CI.

## Recovery and isolated migration rehearsal

With the owner-signed-in Neon session, a manual production snapshot was created
at **2026-10-14 10:58:18 UTC**, with expiry shown as **never**. The snapshot was
restored through Neon's multi-step recovery into a separate validation branch;
production remained the default branch and no application connections were
switched. The validation branch is `codex-dodo-validation-20261014`. Endpoint,
role, credentials, account identifiers and table counts remain private.

The restored copy passed the read-only diagnostic at revision `0059`. An explicit
rehearsal helper allowed only its literal, independently observed clone endpoint,
rejected the normalized production endpoint and query routing overrides, required
the reviewed source fingerprint and zero billing/access holds, and then ran the
ordinary Alembic upgrade against the clone. On source
`b172fff6886d1b3629090eedfde8b5a337cf05f9`, candidate migration image
`im-54PEANIGv3SWAzZzYdBCGd`, it reached `0073_d14_subfeatures` with a complete
read-only post-check and equal before/after row counts for users, subscriptions,
team seats and resumes. Row-count equality does not establish byte-for-byte row
identity. No production migration or financial-history rewrite was performed.

Redis failover and the existing second Redis instance are being handled by a
separate owner-authorized agent. This work does not reconfigure those resources
or treat the backup instance as an isolated acceptance database.

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

## Operator application isolation

A later diagnostic showed that running an operator on the serving Modal App
also warmed its minimum API container, which ran ordinary application startup.
The read-only diagnostic function itself remained read-only, but the enclosing
App was not an isolated operator boundary. Source `8c1ecd99066be0a4aae3c2952a07b50535fbb649`
moves billing/renderer preflights, migrations and template sync to a separate
`latexy-backend-operations` App. The API and workers retain their original App,
bindings and warm-container settings. Production deployment explicitly selects
`modal_app.py::app`; unique operator commands retain their existing function
selectors.

Both diagnostics were repeated with native Python 3.12 and pinned Modal 1.5.4.
Only the four operator functions were created; the serving web function and its
startup/admin bootstrap did not run. The retained billing decision now binds
this source and image `im-VI3aHDZLsEgjYVsdz5K9v2`, again reporting safe disabled
rollout and unverified live acceptance. The renderer configuration diagnostic
returned `configuration_ready=true`, all configuration checks true, and
`certification_verified=false`. It used the independently checked bare image
only for this configuration invocation; no production certification flags were
set. All 142 local deployment/wrapper/renderer configuration tests passed again.
Independent source and Modal CLI review found no operator-selector regression.

The previous integrated head `021dbdf2337556d04c24ba4227cfffab207dc2fc` passed
all PR checks. This last operator isolation change requires CI on its own final
head before merge. Production migrations, serving deployment and paid
fulfillment acceptance remain pending.

## Actual bridge acceptance and fresh application validation

On source `2c1061129ba3f22431ca78e69817dd9a43954823`, a separate credential-free
operator function exercised the actual Lua renderer bridge against the pinned
bare image. [The sanitized execution report](../resume-engine/modal-bridge-acceptance-2026-10-14.json)
binds source-file byte hashes, image/assets, fixtures, requested limits and
observed results. The pass coordinator ran LuaLaTeX, BibTeX, LuaLaTeX and
LuaLaTeX in the same VM/session with the original deadline. Its 101-page PDF was
258,345 bytes, and PDF/SyncTeX/geometry hashes and resolved references/citation
were checked. Cancellation, a bounded wait and a natural absolute deadline each
reached an observed terminal sandbox state. Expired-session reuse was rejected;
cleanup was confirmed. This is bridge acceptance, not owner-flow certification,
a broad template/language profile or a performance SLO.

A fresh empty database was separately created within the validation branch and
migrated normally to `0073_d14_subfeatures` using an expiring, restricted QA role.
Actual reads against the restored copy's users/subscriptions/resumes tables
were denied with SQLSTATE 42501. Its dedicated Modal acceptance environment uses
only generated QA credentials, private temporary object storage and a distinct
TLS-protected temporary Redis service with a one-hour bound. It does not use the
owner's backup Redis instance or bind production credentials to the application.

The workspace's scheduled-function limit prevented a second complete App
deployment. The temporary acceptance assembly therefore registers the exact
source API and unscheduled worker callables with their source images/resources,
while omitting periodic invocations. It is confined to the acceptance environment
and does not change production scheduling or certify periodic recovery behavior.

The first application readiness check then exposed `InvalidCatalogNameError`:
the former regex-based async database URL conversion deleted a leading
`channel_binding` query delimiter and treated the remaining `&ssl=require` as
part of the database name. A private reproduction confirmed both the changed
database path and lost TLS query. Structural URL conversion now preserves
credentials and query boundaries, translates SSL options without changing
their requested mode, and rejects conflicting options. Production was not
changed to mask the defect. Full application/browser acceptance remains pending
a healthy deployment with this repair.
