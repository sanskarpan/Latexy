# Redis failover: disposable cache foundation and authority requirements

## Delivery boundary

This implementation is an **opt-in automatic backup chain for embedding and ESCO
lookup caches only**. It does **not** keep the entire application available when
its primary Redis quota is exhausted. The job system, quotas, OAuth and other
authoritative state still use their existing primary clients. No backup is
provisioned or enabled by this change, and no production configuration changes.

A blank backup must never replace an authoritative Redis merely because it is
reachable. That would grant new quotas, lose cancellation/ownership, re-enable
single-use credentials or dispatch work twice. A successful disposable cache
request must not clear authoritative Redis health or capacity alarms.

## State inventory

| State | Current owner | Fail over independently? |
| --- | --- | --- |
| Model + input-hash embedding vector | `services/embedding_service.py` | Yes, bounded TTL and recomputation |
| ESCO version/language/query/limit lookup | `services/esco_service.py` | Yes, bounded TTL and recomputation |
| Quota counters, refund tickets/markers | `services/entitlement_service.py`, `workers/quota_refund.py` | No |
| Checkout/reconciliation locks, verification tokens | `services/payment_service.py` | No |
| OAuth state/completion tickets, team invitations | `CacheManager.pop`, OAuth routes, `team_routes.py` | No |
| Tenant resolution with invalidation | `middleware/tenant_middleware.py` | No |
| External budget / developer limits | `external_budget_service.py`, `developer_key_service.py` | No |
| Job admission, execution epochs, leases, cancellation | `workers/job_lifecycle.py` | No |
| Ordered event streams, sequences and snapshots | `workers/event_publisher.py`, `event_bus.py` | No |
| Celery deliveries/acknowledgments/results | `core/celery_app.py` | No |
| Resume-engine leases and provider budgets | `services/resume_engine/ledger.py`, `provider.py` | No |
| Collaborative document state and Pub/Sub | `services/collab_manager.py` | No |

All paths above are under `backend/app/`. The existing `REDIS_CACHE_URL` name does
not imply disposability: monetary and security state also lives there. Mutable
analytics, scraped pages, reference data and tenant caches are deliberately not
migrated by this first change.

## Configuration

`DISPOSABLE_CACHE_BACKUPS=[]` preserves the existing path and creates no new
connections. A nonempty JSON list enables the isolated chain, ordered after
`REDIS_CACHE_URL`. Up to three backups are accepted. Each item is one of:

- `{"transport":"redis","url":"rediss://USER:PASSWORD@HOST:PORT/0"}`
- `{"transport":"rest","url":"https://HOST","token":"REST_TOKEN"}`

These are schema placeholders, not credentials or usable endpoints. Supply real
values only through the deployment's approved secret mechanism; never commit
them, paste them into PRs, or use frontend/public environment variables. Secret
fields are redacted from model representations and validation error rendering.
Backup Redis credentials come from each backup URL, never the primary password.
REST requires HTTPS, an origin without path/query/userinfo, and a separate token.
Configuration changes require process restart.

Backups must be separate, authorized databases with independent capacity. The
same host cannot appear twice, including TCP and REST transports. Different DNS
aliases can still identify one database; operators must verify actual database
identity. A second database is not a replica simply because it is called backup.

`UPSTASH_REDIS_REST_URL`/`TOKEN` are not reinterpreted as TCP credentials. The
new optional REST transport uses POST command arrays and bearer header auth;
it does not put tokens, cache keys or values in URLs and does not follow
redirects. Responses are streamed with a byte limit before JSON decoding;
unexpected compression is rejected to prevent decompression bypass. Cached
embedding vectors are checked for expected dimension and finite numeric values. REST is not a substitute for the application's Celery/stream clients.

Defaults:

| Setting | Default | Purpose |
| --- | --- | --- |
| `DISPOSABLE_CACHE_TIMEOUT_SECONDS` | 1 | Per-backend total command timeout, including connection/pool wait |
| `DISPOSABLE_CACHE_QUOTA_COOLDOWN_SECONDS` | 3600 | Suppress a quota-rejected backend for an hour |
| `DISPOSABLE_CACHE_ERROR_COOLDOWN_SECONDS` | 30 | Suppress other failed backends for 30 seconds |

There are at most four backend attempts per operation: default network wait is
at most four seconds; each configured timeout is limited to five seconds. No
health PING, management request, mirroring write or background recovery probe is
added. Existing provider capacity monitoring remains separately configured for
the authoritative primary; it does not monitor backup account usage.

## Failure and recovery behavior

1. Only allowlisted content-hash embedding/ESCO keys may enter this interface.
   There is no counter, lock, GETDEL, invalidation, pipeline or arbitrary-command
   API. Values use an isolated `disposable:v1:` namespace and bounded payloads.
2. A successful GET miss ends the lookup. Do not hunt older copies, promote
   cached results between backends, or refresh TTL on a read.
3. A recognized provider command-quota rejection opens that backend's circuit
   and immediately tries the next eligible backend for this GET or SET. Redis
   command rejections and Upstash REST JSON errors are classified explicitly.
4. A GET can move on after a transport failure. A SET timeout/disconnect, HTTP
   error, malformed reply or cancellation is uncertain: **do not replay that
   write**, including on another backend. The cache write is best effort and
   the service returns its already-computed value. Underlying redis-py retries
   are explicitly disabled; no paid model/API operation is retried by this layer.
5. Credentials/configuration errors are logged with only slot number and a
   bounded error class. HTTP library INFO logs can include the credential-free
   origin; auth headers, cache keys and values stay out of request URLs.
   They are not classified as quota exhaustion or replayed
   in the same operation. Later calls can select another eligible backend.
6. Routing remains on a working backup even when the primary cooldown expires.
   A failed endpoint is eligible again only when the active path also fails.
   Recovery admits a single real command per recovering slot per process.
   Late successes never move affinity back or clear a newer failure's cooldown.
7. Retried, explicitly rejected SETs preserve remaining TTL. An absolute expiry
   inside the serialized value prevents a returning backend serving an expired
   entry, even if server-side expiry differs slightly. No cross-backend delete
   is needed because mutable/invalidation-sensitive keys are excluded.
8. All-backend exhaustion is a cache miss or failed best-effort write, not a
   new quota allowance. Model recomputation can still cost money; this change
   does not bypass any existing entitlement/provider-budget checks.

Affinity and circuit state are process-local, reset on restart, and intentionally
not coordinated through exhausted Redis. Different processes can use different
cache endpoints without becoming independent authorities. An upstream model
alias or taxonomy response can change, so these are bounded-lifetime derived
results rather than mathematically immutable values. Any future cache
transformation change should version the namespace.

Embedding worker tasks own loop-local clients that close before each asyncio.run
loop exits; routing/cooldown metadata is shared across those tasks without sharing
sockets. Shutdown closes both Redis and HTTP clients with bounded cleanup. The cache owns its pools and does
not close or replace primary quota/queue clients. Application readiness still
reports the existing authoritative dependencies, even when cache backups work.

## Full automatic failover: concrete next implementation

### Primary authority freeze (migration 0074)

`redis_authority_control` adds a Postgres singleton with an integer generation,
the current primary identity, and a frozen phase. It is seeded at generation 0
with the primary. Application quota, dispatch and worker admission now read this
record and refuse frozen, missing or unreadable authority. The controlled
[held recovery workflow](redis-held-recovery.md) can freeze the primary after
an external stop/drain procedure, without admitting backup work.
`freeze_primary_authority` can atomically reserve the next generation with a
caller-owned UUID; a second or stale coordinator cannot reserve another. A
caller that loses the transaction response must read back the UUID before
deciding whether its freeze committed. Database failure or a missing row has no
synthetic healthy state. This first migration structurally forbids a backup as
active and refuses every generic downgrade, including before a freeze, because
a state check followed by a table drop would race a concurrent coordinator.

This is containment, not a recovery switch. Read-before-act checks cannot stop
an already-running effect or close a race with an in-flight broker call; the
external writer fence and global traffic hold remain required. The exhausted
primary cannot supply quota counters, receipts, consume-once tokens or job
leases through normal Redis reads. No code path may treat an empty backup as a
reconstructed authority. A later migration must add promotion/failback states
only after durable quota cutover, one-time consumption, job outbox, worker
fencing and state reconciliation below are implemented and validated. Failback
must allocate a new forward generation, never resurrect an old one.

### Disabled quota ledger (migration 0075)

`quota_ledger_accounts` represents each user, dimension and period as either
`unknown` or `reconciled`. A missing or unknown account rejects reservations.
The migration creates no balances. An operator must first fence every legacy
writer, obtain a consistent account snapshot, verify outstanding refund
receipts, and record the opening usage plus a nonsecret evidence reference and
SHA-256 digest. The code validates the presence and shape of this provenance;
it cannot prove the source was complete or accurate. Redis is currently over
quota, so opening usage cannot be verified through normal primary reads.

`quota_ledger_reservations` records a globally unique reservation ID, the
user/dimension/period/window/cost/limit inputs, and a SHA-256 fingerprint of
the caller's persisted intent. The fingerprint is unique per account/period;
a retry with changed inputs or another reservation ID is rejected. Allowed and
denied decisions are sticky. A PostgreSQL account row lock serializes debits,
settlement and refunds. A confirmed success can transition to `settled` once;
it cannot later refund or dispatch again. A failed reservation can refund its
exact stored cost once; a missing receipt never refunds. The caller must
commit before dispatch and use a fresh transaction to resolve an uncertain
commit by the same ID **and full immutable inputs**. The legacy API/worker paths still use Redis
and do not call this ledger. This is a disabled building block, not a live
double-write path or an assertion that existing counters have migrated.
Neither migration has an automatic downgrade because a check/drop sequence can
race a writer and destroy authoritative state.

The current tests exercise concurrent compare-and-swap coordinators, exhausted
primary freeze, stale generation, lost freeze response readback, database
failure, unknown quota balances, near-limit admission, duplicate reservations,
changed-intent replay, settlement/refund idempotency, uncertain-commit readback
and downgrade protection against SQLite. The PR's disposable PostgreSQL CI
service runs concurrent debit, settlement and refund tests. Mixed API/Modal
workers, backup transport and partition injection are still required before
any activation.

The user-level goal of automatic whole-application continuity is **not accepted
by this patch**. Choose and verify one authority model before implementing it:

### A. Provider-managed coherent authority

Use one logical Redis service whose managed failover preserves the required
consistency, command support, acknowledged writes and capacity contract. Verify
that provider quota exhaustion does not affect every replica under the same
logical account/database limit. Replication on its own is not independent quota
capacity. Ordinary asynchronous Redis replication is not a proof of zero-loss
promotion. Do not infer zero-loss guarantees from a successful PING or WAIT.

### B. Durable authority plus replaceable Redis transport/cache

1. Move quota consumption, reservations/refunds, external spend budgets and
   one-time token consumption into transactional durable storage, with unique
   idempotency IDs and compare-and-set semantics. Migrate existing outstanding
   balances and receipts; never initialize a new epoch at zero.
2. Add a durable routing record containing active backend ID and monotonically
   increasing epoch. A coordinator must acquire and commit the new epoch before
   admission resumes. Every API, Modal/Celery worker, cleanup process and
   reconnected client must enforce it. A cached process-local active index is
   not sufficient.
3. Make lifecycle ownership, lease expiry, cancellation/fencing tombstones and
   finalization consult that durable epoch. Reject old workers after cutover.
   Existing DB JobFinalization protects terminal output, but current admission
   and execution leases still depend on Redis.
4. Add a transactional job outbox/inbox with durable delivery and completion
   identifiers. Reconcile queued, reserved, acknowledged and uncertain work
   before replay. Provider calls with unknown outcomes must remain unresolved
   until reconciled or require explicit intervention; never spend twice merely
   because Redis lost the response.
5. Persist or safely reconstruct event ordering/replay offsets and collaboration
   updates. Consumers must tolerate reconnect without treating a reset sequence
   as new authority. Define terminal reconnect behavior when no durable replay
   is available.
6. Cut over at a consistent snapshot/outbox boundary; preserve absolute TTLs,
   consume-once state and invalidation versions. Fence the old epoch before
   writing to the new backend. Rollback is another forward epoch transition,
   never returning to unfenced old state.

### Required acceptance, currently outstanding

- No quota reset, over-admission or double refund under concurrent cutovers.
- No old worker commits after fencing; canceled jobs remain canceled.
- No duplicate provider spend, dispatch or finalization after accepted writes
  lose their responses, including compensation during quota exhaustion.
- No OAuth/invitation credential consumed twice across split networks/restarts.
- Multi-process primary/backup disagreements cannot create two authorities.
- Backup quota exhaustion and failed rollback retain the same safety guarantees.
- Verified queue transport compatibility, recovery point/time objectives,
  monitoring of every failure domain and a tested operational cutover runbook.
- Fault injection for partitions, stale workers, clock skew, interrupted
  migration and backup loss, beyond mocked unit tests.

Until those pass, keep authoritative admission fail-closed and preserve existing
`quota_unavailable` / dependency-unavailable responses. An early capacity alert
should trigger operator remediation and controlled admission containment,
not an automatic blind URL switch. A new admission gate would need to consult
authoritative, fresh state without falsely treating missing management metrics
as exhaustion; it is not included here.

## Validation and official references

`backend/test/test_disposable_cache.py` covers multi-backup quota transitions,
sticky affinity, cooldown/single-flight recovery, concurrent late success,
uncertain writes, backup failure, TTL, bounded timeouts, shutdown, malformed
configuration, REST semantics, credential-safe messages and protected state.
Tests use mocks and dummy endpoints; no live provider credentials are needed.
`test_disposable_cache_integration.py` additionally accepts two explicit,
isolated local Redis URLs through `TEST_DISPOSABLE_REDIS_PRIMARY_URL` and
`TEST_DISPOSABLE_REDIS_BACKUP_URL`. It verifies real TCP round trips, TTL and
backup writes with an injected primary quota rejection, never flushing a DB.
This is transport/in-process failover coverage, not live provider-quota testing.

Official documentation checked 2026-10-13:

- [Upstash request-limit error](https://upstash.com/docs/redis/troubleshooting/max_requests_limit): monthly command exhaustion rejects requests.
- [Upstash REST API](https://upstash.com/docs/redis/features/restapi): separate HTTP transport, command arrays, JSON errors and bearer auth. Blocking queue/stream command variants are unsupported.
- [Redis replication guarantees](https://redis.io/docs/latest/operate/oss_and_stack/management/replication/): asynchronous replication and acknowledged-write loss must be considered before promotion.
