# Authoritative quota cutover inventory

This is a review plan, not an activation procedure. Migration 0074 now supplies
the primary-frozen admission backstop described in
[held recovery](redis-held-recovery.md); it does not promote a backup. Migration
0075's balance ledger remains dormant. The application still uses Redis meters
when primary authority is active, and
current-period balances cannot be read from the exhausted primary through
normal commands. A missing balance is unknown, never zero.

## Plan allowance paths

`entitlement_service.consume_quota`, `enforce_quota`, and `refund_quota` own the
Redis Lua debit and compensating refund. `quota_snapshot` reads the same Redis
counters. All three plan dimensions need durable, refundable reservations:

| Dimension | Direct admission paths | Refund path |
| --- | --- | --- |
| `compilations` | `api/job_routes.py` (`latex_compilation`, `auto_fit`), `api/routes.py`, `api/public_api_routes.py` compile | API exception handlers, `workers/latex_worker.py`, `workers/cleanup_worker.py` |
| `optimizations` | `api/job_routes.py` (`llm_optimization`, `combined`, batch), `api/routes.py`, `api/resume_routes.py`, `api/cover_letter_routes.py`, `api/public_api_routes.py` optimize | API exception handlers, `workers/llm_worker.py`, `workers/orchestrator.py`, `workers/cover_letter_worker.py`, `workers/cleanup_worker.py` |
| `ai_assists` | `api/ai_routes.py` shared helper (also interview/outreach), `api/career_routes.py`, `api/ats_routes.py`, `api/format_routes.py`, `api/github_routes.py`, `api/sources_routes.py` | API exception handlers, `workers/ats_worker.py`, `workers/converter_worker.py`, `workers/github_import_worker.py`, `workers/cleanup_worker.py` |

The worker seam is `workers/quota_refund.py`. It currently trusts a serialized
cost and a job-scoped Redis marker. `workers/cleanup_worker.py` scans pending
Redis receipts and combines them with lifecycle state; its orphan/recovery
branches must move to a durable pending-reservation query and terminal proof.
`clear_quota_refund_receipt` must call the dormant durable `settled` transition
in the same transaction as job success so a successful job cannot later be
refunded. Refunds must use the stored cost, not
the worker payload. BYOK paths that skip platform plan quota retain that policy.

For background work, allocate one stable reservation ID before charging,
persist it beside the `JobFinalization`/outbox identity, then serialize that ID
with the job. Every retry and every API/worker/cleanup compensation reads the
same ID. In `api/job_routes.py`, two `_consume_job_quota` calls around lines
821 and 872 omit the already allocated `job_id`; correct those in the complete
switch. A new HTTP request currently creates a new job ID, so client retries
also need a persisted idempotency key mapped to the existing job and immutable
request fingerprint. Synchronous AI routes need the same persisted request
intent before an ambiguous external call; payload hashes alone would collapse
legitimate repeated requests.

## Other Redis meters

| Meter | Current writer and callsites | Durable shape and outcome |
| --- | --- | --- |
| Developer API daily requests | `services/developer_key_service.py:consume_rate_limit`, called by `api/public_api_routes.py:_authorize` before plan allowance; `touch_usage` separately commits `request_count`. `get_usage_history` reads Redis. | A per-user UTC day attempt counter with stable attempt IDs. Current Redis increments even denied requests, so record denied attempts as attempts while keeping them denied on retry. Commit the meter, plan reservation, key usage metadata and job intent together. Read history from the new authority. |
| Client and global outbound budgets | `services/external_budget_service.py:enforce_external_budget`; `api/github_routes.py` GitHub import, `api/sources_routes.py` URL and LinkedIn imports, `api/reference_routes.py` fetch/verify/ORCID/DOI subcalls. | One compound weighted reservation debits client and global rows in the same PostgreSQL transaction, locking in a fixed order. These are consumption counters without current refund semantics. Reference endpoints can charge twice in one request, so each sub-operation gets a distinct stable ID. Persist the first-use expiry for the existing rolling TTL behavior. |
| Anonymous device trial | `services/trial_service.py` uses PostgreSQL `DeviceTrial` transactions. | Preserve its existing separate policy; do not initialize it from Redis. |
| Resume optimization stage budgets | `services/resume_engine/ledger.py` and `budgets.py` use PostgreSQL run/stage rows. | Preserve their existing stage identities and reconcile external provider outcomes; do not fold them into a per-user quota counter. |

Migration 0075's `quota_ledger_accounts` key is a user/dimension/UTC period.
It cannot represent an IP-derived client plus global scope or a first-use TTL.
Extend the schema for those meters before using this ledger at runtime. Do not
reinterpret its `user_id` column as a scope or create a fabricated user.

## Atomic migration and authority boundary

1. Add a durable mode with `legacy`, `fencing`, `reconciling`, and `durable`
   transitions under a monotonically increasing generation. Migrations 0074/75
   do not yet provide this mode. Every new API, Modal worker and cleanup writer
   must consult it at the authoritative write boundary. Old binaries do not
   understand it; stop/fence them during a coordinated rollout before cutover.
2. Freeze legacy admission and drain or classify uncertain dispatch and provider
   effects. Obtain a consistent snapshot of every active account/window,
   developer attempt counter, external client/global window, and outstanding
   refund receipt. Record provenance and verify it independently. With primary
   reads currently rejected by quota, this step is blocked. Keep missing or
   unverifiable current-period balances closed.
3. Reconcile old receipts to one stable reservation identity and terminal job
   outcome. Migration 0075 now supports `allowed`, `denied`, `settled`, and
   `refunded` states, but no runtime path uses them. Bind each reservation to
   the job/outbox or synchronous request intent and its immutable fingerprint.
   An uncertain commit is read back by that same ID and all immutable inputs
   in a fresh transaction. Commit settlement with durable success, so it
   cannot later refund; a failed action cannot refund twice.
4. In one PostgreSQL admission transaction, decide policy, lock all relevant
   rows, spend plan allowance and any developer/external budgets, and persist
   the job/outbox or synchronous intent. Commit before dispatching work. A
   missing policy, unknown balance, database error, mixed-version worker or
   unclassified prior external effect blocks admission. No independent Redis
   dual-write can be treated as the authority decision.
5. Enable `durable` only after reconciliation, all callsites and workers are
   switched, and real PostgreSQL/mixed-fleet failure tests pass. A later backup
   Redis promotion must separately fence job leases, cancellation, one-time
   tokens, event order and old workers. Failback uses a new generation.

New UTC periods may begin at zero only after proving legacy writes have ended
for that account and window. A calendar rollover by itself does not repair an
unknown previous period with outstanding refund or job effects.
