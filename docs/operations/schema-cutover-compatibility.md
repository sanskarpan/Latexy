# Schema cutover and forward recovery

This runbook concerns the Modal backend schema and builds. It grants no approval
to deploy, change credentials, enable sales, or run a production migration.
The current production database revision and serving backend SHA remain unknown.

## Source evidence and failure modes

At `dec5ca62b6f92dd85dd879aad04f9ff38852c023` there is one Alembic head,
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

The [latest checked Modal workflow run](https://github.com/sanskarpan/Latexy/actions/runs/38787403505)
for `dec5ca62` failed renderer input validation; its migration and deploy steps
were skipped. [Canonical CI](https://github.com/sanskarpan/Latexy/actions/runs/38784170535)
and [Vercel verification](https://github.com/sanskarpan/Latexy/actions/runs/38787403545)
succeeded for that SHA. None of those results identifies the currently serving
Modal revision or database head. The [retained renderer boundary result](https://github.com/sanskarpan/Latexy/issues/1865#issuecomment-6200386555)
also records that production renderer variables were not enabled and asks for
this compatibility plan before automatic migration or deployment.

## Before approving an exact SHA

1. Keep traffic, checkout, callbacks, asynchronous billing work, render writes,
   share creation, and bulk PDF export on hold while crossing the schema
   boundary. Identify **every** currently serving API and worker image using
   deployment version and traffic evidence; record its immutable SHA. Stop or
   drain all legacy writers and readers. Preserve and replay pending webhooks
   through the approved Dodo-only service; do not drop events.
2. Use read-only, redacted diagnostics to identify the actual `alembic_version`,
   including any legacy Dodo `0061` collision, current financial pointers,
   pending intents, and unaccepted compilations. A backup and restore rehearsal
   must be available. Do not assume the latest GitHub run changed production.
3. Identify a previously built, deployable **forward-compatible** recovery SHA
   on main, distinct from the candidate SHA. Verify successful canonical CI,
   Dodo-only billing code, and accepted artifact filters on **every** public
   share/export path. Verify its image and Modal deployment availability
   separately. The automated source checks cover only two known reader queries
   and legacy billing ID references; they do not prove full reader coverage or
   image availability. `dec5ca62` passes those minimum source and CI checks,
   but image availability and production provenance are unverified.
4. Review the exact candidate SHA and recovery SHA, then set Production
   environment variables `MODAL_SCHEMA_CUTOVER_APPROVED_SHA` and
   `MODAL_RECOVERY_VERIFIED_FOR_SHA` to the candidate SHA, and
   `MODAL_FORWARD_ROLLBACK_SHA` to the distinct recovery SHA. Set the first
   only after identifying and draining the fleet; set the second only after
   verifying the recovery image and every public artifact reader. The workflow
   checks exact SHA matches, ancestry, minimum source filters, and rollback CI
   before migration. Refresh both candidate-scoped attestations for each
   release. The variables record operator assertions; the workflow cannot
   independently prove traffic drain or image availability.
5. Complete renderer input certification and read-only billing preflight. Apply
   ordinary Alembic upgrades only from the identified, compatible revision.
   Keep ingress held across migration and the rolling deploy until old instances
   and queued work are gone, new version health passes, and read-only checks
   show no newly mislabeled provider rows or unaccepted artifact exposure.
   Release ingress gradually with billing sales still disabled unless separately
   accepted.

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

Three tests create UUID-named PostgreSQL schemas, run the real `0065` or `0062`
upgrade on minimal tables, check legacy/new billing writes and downgrade
refusal, and compare old versus accepted-only compilation selection. They drop
their schemas even on assertion failure. The gate tests run with mocked GitHub
and Git commands and need no external service. CI has a dedicated verbose step
so each database test reports PASS or SKIP by name. Keep database URLs on a
disposable loopback instance.
