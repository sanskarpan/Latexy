# Held Redis recovery qualification

`MODAL_REDIS_SECRET_NAME` selects one named Modal secret at build/deployment
time. Unset or empty selects the existing `latexy-redis`. This is a static
binding for recovery qualification, not an automatic failover chain.

An alternate label is allowed **only while deployment traffic is held**.
Source import, API startup and the canonical workflow reject an alternate label
with traffic released, even with a matching release approval SHA. Ordinary
HTTP, WebSockets, worker invocations and scheduled work remain blocked by the
existing hold. Startup skips admin role bootstrap while held.

## Qualification boundary

Supply the alternate binding through a new dedicated secret. Preserve the
original secret and primary database. The selected secret must override every
Redis setting inherited from the opaque backend/billing secrets: native queue
and cache URLs, password, Celery broker/result URLs, disposable-cache configuration
and any provider capacity identity/management settings. Verify that both native
URLs identify the intended database and use TLS; a successful PING alone does
not prove database identity, ordinary command capacity or restored state.
Do not put native credentials in GitHub variables, source, public reports or
frontend configuration. Only the nonsecret secret label belongs in the variable.

Images capture the selected label; a final inline secret pins it and the hold
after all opaque secrets. The selected Redis secret overrides the API billing
overlay too. Health publishes a domain-separated SHA-256 of the validated label.
The workflow checks that fingerprint alongside the serving SHA before release
and after deployment. This checks **selector continuity only**: it neither hashes
nor authenticates mutable secret contents and does not certify recovered Redis
authority. An operator must separately preserve and verify the secret binding.

The workflow still requires canonical main CI, compatible recovery images,
schema-cutover approval, a fresh externally verified drain, and the stopped old
App before migrations. A held deployment can apply approved migrations and run
explicit template synchronization; it is not a read-only operation. Health and
template probes cannot establish product E2E acceptance or permit release.

The migration and primary-freeze functions also require a signed operation
proof minted by the protected Production workflow immediately after the stopped
App check. The proof is bound to one action, exact source SHA, `main`, the
observed old App ID, selected Redis label fingerprint, and (for freeze) the
canonical freeze UUID. It expires after 120 seconds. A separate
`latexy-recovery-ops-20261027` Modal secret carries the 256-bit HMAC verifier
key only into those two functions; the matching GitHub Production secret is
used only by their workflow steps. The proof is masked and passed directly to
the operation. This prevents an ordinary unsigned direct invocation. It does
not prevent a privileged operator who can read the signer key or administer
Modal/GitHub from authorizing an operation, and a valid proof can be replayed
until expiry. Freeze UUID idempotency bounds that replay; Alembic upgrades must
remain repeatable. The proof attests a recent drain query and does not remove
the race between that query and the operation.

## No snapshot recovery

An empty backup contains no evidence about old quota counters, refund receipts,
queued deliveries, locks or consume-once tokens. Missing usage is unknown.
Database terminal job rows and zero running Modal inputs do not reconstruct that
state. Preserve the primary, forbid replay of uncertain work and keep alternate
authority product admission closed. Do not seed zero balances or mark a drain
complete based on reachability or aggregate database counts.

The conservative recovery choice keeps **all work admission closed**, including
unlimited plans, unmetered legacy tasks, cleanup/reconciliation and refunds. It
does not grant fresh allowances to new accounts. The canonical held-cutover
workflow rechecks the stopped old App after migration, then commits a one-way
primary freeze in `redis_authority_control` using a canonical operation UUID.
An uncertain response is resolved by a fresh read of that same UUID, generation
and reason. A different coordinator or changed identity cannot claim success.
The primary remains the named, frozen authority; the spare is not promoted.

Quota admission and refunds read this durable control before using Redis;
snapshots report unknown usage (`used: null`) when authority is frozen or
unreadable. Dispatch, Celery publication/execution, worker/beat startup, legacy
worker admission and receipt cleanup have the same backstop. An unheld API
cannot start after a freeze. Modal's global hold additionally prevents all job
and scheduler entrypoints, including families that lack job lifecycle records.

These fresh checks are **not an atomic fence around running work**. A broker call
or provider effect that passed its check can race a later freeze. Therefore the
old API, every worker/scheduler and all other writers must first be stopped or
quiesced; uncertain deliveries/effects remain quarantined and are never replayed.
The App-state verifier alone does not prove that settlement or preserve a lost
collaboration update stream. Preserve the primary and private recovery evidence.
Keep the global hold and job admission closed after backup qualification.

Before opening product traffic, implement and independently validate the coherent
authority, quota, receipt and job recovery described in
[the failover architecture](redis-failover.md) and
[the quota cutover inventory](redis-quota-cutover-plan.md), or recover the original
authority's verified state and capacity. This staging selector deliberately has
no approval flag that bypasses those requirements. Changing the selector back
after alternate qualification fails the held candidate fingerprint check.
