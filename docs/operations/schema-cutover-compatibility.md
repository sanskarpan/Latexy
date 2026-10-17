# Schema cutover and forward recovery

This runbook concerns the Modal backend schema and builds. It grants no approval
to deploy, change credentials, enable sales, or run a production migration.
Prior read-only database and deployment-pointer observations exist, but they
do not establish compatibility across the full serving fleet. Reverify the
cutover evidence for the exact release before approving migration or recovery.

## Source evidence and failure modes

At the checked main revision `e9d6f1c2b71722e30efe861703e648ed744c3327` there is one Alembic head,
`0075_durable_quota_ledger`. The mainline path is `0061` → `0062` → `0063` →
`0064` → `0065` → `0066` → `0067` → `0068` → `0069_capability_catalog` →
`0070_plan_catalog` → `0071_plan_quotas` → `0072_capability_roles` →
`0073_d14_subfeatures` → `0074_redis_authority_freeze` →
`0075_durable_quota_ledger`. An older unpublished Dodo `0061` schema can
collide with mainline `0061`; use the existing bridge validation, never stamp
an ambiguous revision.

* `0065` adds `provider DEFAULT 'dodo'` to payments and subscriptions and
  backfills the rows present in that transaction. The historical
  `c21bcc20:backend/app/services/payment_service.py` writes only Razorpay ID
  fields. An old writer after migration can create `provider='dodo'` with a
  null generic ID. The one-time backfill cannot repair that later row.
* `0062` adds `artifact_accepted`, default true for existing compilations. The
  historical `c21bcc20:backend/app/api/resume_routes.py` share creation and
  bulk PDF queries select the newest completed compilation without acceptance
  filtering. A later unaccepted candidate can therefore win on an old build.
  The historical SHA is source evidence, **not** an attested serving SHA.
* `0065` rejects downgrade when provider-neutral rows or later evidence exist.
  Downgrading `0062` drops the acceptance state. Treat both as forward recovery
  boundaries, not routine schema rollback targets.

The read-only billing preflight now counts rows whose retained Razorpay ID
conflicts with the provider label or generic ID. A nonzero aggregate blocks
rollout and omits the identifiers from its report. It can detect a completed
mixed-version write, but its snapshot cannot prove that old writers have
stopped; the traffic drain and commit-scoped recovery attestation remain required.
The Modal workflow repeats this read-only preflight after migration and before
the rolling deploy, while ingress must remain held. A failed recheck leaves the
schema advanced and blocks the deploy; follow the forward-recovery procedure.
Investigate suspect rows against independent provider evidence. Do not change
their provider label automatically.

For that SHA, [canonical CI](https://github.com/sanskarpan/Latexy/actions/runs/38864530611)
and [exact-SHA Vercel verification](https://github.com/sanskarpan/Latexy/actions/runs/38867427620)
passed. The [Modal workflow](https://github.com/sanskarpan/Latexy/actions/runs/38867427592)
stopped at renderer input validation; billing preflight, cutover approval,
migration and deploy were skipped. Those workflow results alone do not establish
the full serving fleet or cutover-time schema state. The [bounded renderer boundary result](https://github.com/sanskarpan/Latexy/issues/1865#issuecomment-6200386555)
binds an immutable image and asset marker to an earlier source revision. Its
11 recorded source-file hashes match the current Windows checkout bytes, but
the complete backend tree differs and production rollout was not certified.

## Before approving an exact SHA

1. Keep traffic, checkout, callbacks, asynchronous billing work, render writes,
   share creation, and bulk PDF export on hold while crossing the schema
   boundary. Identify **every** currently serving API and worker image using
   deployment version and traffic evidence; record its immutable SHA. Complete
   the separately authorized drain/recovery procedure for all legacy writers
   and readers. That procedure must establish how queued and in-flight business
   work is settled or preserved and how pending webhooks are replayed through
   the approved Dodo-only service; do not drop events. The deployment workflow
   does not measure or infer settled work from a Modal App state or task count.
2. Use read-only, redacted diagnostics to identify the actual `alembic_version`,
   including any legacy Dodo `0061` collision, current financial pointers,
   pending intents, and unaccepted compilations. A backup and restore rehearsal
   must be available. Do not assume the latest GitHub run changed production.
3. Identify a previously built, deployable **forward-compatible** recovery SHA
   on main, distinct from the candidate SHA. Verify successful canonical CI,
   Dodo-only billing code, and accepted artifact filters on **every** public
   share/export path. Verify its image and Modal deployment availability
   separately. The automated source checks cover two known share/export queries,
   the public API PDF fallback and legacy billing ID references; they do not
   prove full reader coverage or image availability. The current minimum source
   checks reject `dec5ca62`
   and `11890a1d` (#1901), whose public PDF reader can fall back to live Redis
   for pending, committing or expired durable jobs. Source checks accept the
   #1903 fix at `359806d2` and #1904 at `4182705d`, but this does not
   establish a distinct deployable recovery image, drained fleet or cutover-time
   database compatibility. Do not nominate a recovery SHA from source checks alone.
4. Review the exact candidate SHA and recovery SHA, then set Production
   environment variables `MODAL_SCHEMA_CUTOVER_APPROVED_SHA` and
   `MODAL_RECOVERY_VERIFIED_FOR_SHA` to the candidate SHA, and
   `MODAL_FORWARD_ROLLBACK_SHA` to the distinct recovery SHA. Set the first
   only after reviewing the migration decision; set the second only after
   verifying the recovery image and every public artifact reader. The workflow
   checks exact SHA matches, ancestry, minimum source filters, and rollback CI.
   Those source and operator checks do not establish a runtime drain or settled
   business work. After the separately authorized procedure has completed,
   update these Production environment variables:

   - `MODAL_DRAIN_PROCEDURE_APPROVED_FOR_SHA`: exact candidate SHA covered by
     the external procedure.
   - `MODAL_DRAIN_PROCEDURE_APP_ID`: the old App ID recorded by that procedure.
   - `MODAL_DRAIN_PROCEDURE_COMPLETED_AT`: its UTC completion timestamp.
   - `MODAL_DRAIN_PROCEDURE_EVIDENCE_REFERENCE`: a reference to the external
     procedure record.

   This is a trusted operator-pointer gate, not verified external drain
   evidence. The code checks only candidate-SHA equality, App ID format and
   equality, a completion timestamp no more than 300 seconds old, and that the
   reference string is nonempty. It does not fetch, authenticate, or inspect
   the referenced record; an arbitrary nonempty reference and recent timestamp
   satisfy those fields if the current App ID/state checks also pass. An
   authorized operator must independently verify the external drain/recovery
   procedure and production change freeze before setting these variables and
   allowing migration. The workflow itself does not verify queued or in-flight
   work. Immediately before Alembic it resolves the App name through Modal's
   non-creating SDK lookup, reads the current App list state, and resolves the
   name again. The current App ID must still equal the supplied old App ID and
   its state must be `stopped`.
   Missing, mismatched, stale, live, recreated, ambiguous, or unavailable
   state blocks migration. Modal 1.5.4's App-list JSON has an `app_id` and a
   human-readable `description`, but no stable App-name field; the check binds
   by App ID and never treats `description` as identity.

   The automatic `workflow_run` path uses the same gate and therefore fails
   closed if pointer fields are absent or the timestamp is stale. The gate does
   not establish that the referenced procedure happened. After completing and
   independently verifying the separately authorized procedure, use manual
   dispatch if the automatic run already failed. The
   workflow's concurrency group serializes only GitHub deployment runs; it
   cannot lock out a Modal deploy or other operator. There is a small
   check-to-migration race because Modal state and the database migration are
   not one atomic operation. Keep an externally enforced production change
   freeze in place until migration and deployment finish. Without that freeze,
   do not migrate. Refresh all candidate-scoped markers for each release; the
   recovery variables remain operator assertions and do not prove image
   availability.
5. Complete renderer input certification and read-only billing preflight. Apply
   ordinary Alembic upgrades only from the identified, compatible revision.
   Keep ingress held across migration and the rolling deploy until the external
   procedure's work-settlement criteria are met, new version health passes, and
   read-only checks show no newly mislabeled provider rows or unaccepted
   artifact exposure.
   Release ingress gradually with billing sales still disabled unless separately
   accepted.

## Hold the replacement before releasing product traffic

The deployment workflow never stops the previous App. The initial held-cutover
phase requires trusted operator-supplied pointer fields and performs read-only
App identity/state queries immediately before migration. Those pointer fields
do not authenticate the referenced procedure; an arbitrary nonempty reference
with a fresh timestamp can pass their format checks. Modal's `stopped` state
means the App is stopped at the observation time; it is not evidence of
graceful completion of requests, queued workers, or in-flight business jobs.
The external procedure must own those checks and preserve/replay work as
needed. The workflow's pointer fields do not independently verify the external
procedure's contents.

The two Modal lookups and App-list query detect a name-to-ID change during the
check, but cannot make the state check and database migration atomic. An
out-of-band redeployment can race after the final lookup. Keep a production
change freeze active from external drain through migration and deployment;
the GitHub concurrency group does not control other Modal clients. Missing
pointer fields, an App that is live or recreated, or an unavailable
API query blocks migration. A replacement deployment exposes its endpoint after
startup, so it must remain held until the release gates pass. FastAPI startup
also tolerates some Redis failures, and startup completion cannot substitute
for readiness checks.

Use the deployment workflow's two explicit phases:

1. Create and validate the fresh post-freeze recovery point. Retain the existing
   restore-rehearsal evidence. Complete the separately authorized external
   drain/recovery procedure, retain its evidence, and update the four
   `MODAL_DRAIN_PROCEDURE_*` variables. The workflow does not run the procedure
   or claim its work-settlement facts. Bind the reviewed renderer inputs, exact
   candidate cutover attestations and distinct recovery SHA. Keep new sales
   disabled and live acceptance unset.
2. Dispatch the exact candidate with `traffic_mode=held` (the default). Automatic
   deployments also use held mode. The image-bound
   `MODAL_DEPLOYMENT_TRAFFIC_HOLD=true` makes the API reject product HTTP
   requests with 503 and accepts then immediately closes WebSocket handshakes
   with application close code 1013. Only the documented read-only
   health and public template probes remain available. A narrowly anonymous
   `GET /config/entitlements?include_quotas=false` probe is also allowed, with
   that exact query and no Authorization, Cookie or X-API-Key headers. Other
   entitlement requests remain held. Worker entry points
   reject new work before business initialization, and scheduled fan-out is
   disabled. Runtime worker guards also protect against retained schedule
   metadata. Operator migrations, preflights and catalog synchronization remain
   explicit operations during this phase.
   The selected value is also appended as the final inline secret to both
   function secret lists before registration. It overrides stale hold values
   in base, storage, Redis or billing secrets; API and worker functions cannot
   choose different modes through those bundles.
3. Let the held workflow finish migration, the repeated financial preflight,
   deployment identity verification, catalog work and health checks. Verify the
   actual schema head and safe-disabled purchase state separately. Public
   presentation verification honors B05: OFF requires an empty catalog and
   skips public asset verification; ON requires every source-owned template
   exactly once and verifies its assets, while allowing custom entries. It
   never enables the feature to pass deployment. Hidden public assets are not
   certified by that check; explicit operator synchronization still runs.
   Check the
   `X-Latexy-Deployment-Hold: true` marker on fresh health responses and 503
   denials on product paths. This is an application admission hold; the public
   network endpoint still exists. The marker is not drain evidence and does
   not cancel previously admitted work. The workflow's read-only Modal
   identity/state and trusted operator-pointer gate runs immediately before
   migration. It does not authenticate external evidence or prove work drained.
   The existing outer CORS/verified-tenant layer can resolve domains and
   populate infrastructure caches before the hold; startup, health probes and
   explicit operator catalog work also access backing services. This hold
   prevents product handler admission and worker execution, not every possible
   infrastructure write. CORS preflight success does not permit a held product
   request to execute.
4. Only after that evidence passes, set Production variable
   `MODAL_TRAFFIC_RELEASE_APPROVED_SHA` to the same exact candidate and manually
   dispatch `traffic_mode=release`. Release requires the candidate's existing
   held deployment identity and fresh held/healthy probe responses before
   redeploying that exact source with the hold disabled. It does not repeat the
   old-App drain gate or database migration: those belong only to the initial
   held cutover, and the held candidate is now the current serving App. Verify
   the false marker and perform bounded normal product checks after release.
5. Retain the release-approval SHA after success. An automatic CI rerun for that
   approved SHA skips another held deployment, so it cannot silently re-hold
   the released application. A different source SHA still needs fresh cutover
   and recovery attestations. A manual held deployment remains available for an
   explicitly reviewed containment action.

If release fails, contain the exact identified App and preserve the advanced
schema. Do not reactivate a legacy writer or unfiltered artifact reader. Keep
sales disabled throughout this procedure; traffic release does not authorize
live billing acceptance or payment transactions.

If failure occurs before migration, restore traffic only to the verified old
fleet after its prior conditions are checked. If failure occurs after migration,
retain the advanced schema and switch to the verified forward-compatible
recovery build; never roll back to an unfiltered artifact reader or legacy
Razorpay writer. Reconcile suspect financial rows against independent provider
evidence under an approved operator procedure. Do not relabel them by prefix or
run the `0065` backfill again. Quarantine unaccepted candidates from public
sharing until verified acceptance is restored.

## Disposable reproductions

CI provides a disposable loopback PostgreSQL service and runs the focused tests:

```sh
cd backend
TEST_POSTGRES_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/latexy_test \
TEST_POSTGRES_ALLOW_SCHEMA_CREATE=1 SKIP_INFRA_CHECK=1 \
pytest -vv -ra test/test_schema_rollout_compatibility.py test/test_modal_schema_cutover_gate.py
```

Five tests create UUID-named PostgreSQL schemas, run the real `0065` or `0062`
upgrade on minimal tables, check legacy/new billing writes, null and mismatched
identifier pairs, the redacted identity-mismatch count and downgrade refusal, and compare old versus
accepted-only compilation selection. They drop
their schemas even on assertion failure. The gate tests run with mocked GitHub
and Git commands and need no external service. CI has a dedicated verbose step
so each database test reports PASS or SKIP by name. Keep database URLs on a
disposable loopback instance.
