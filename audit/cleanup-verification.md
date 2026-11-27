# Cleanup verification - production audit 2026-11-27

Suffix: `20261127103328`. Scripts: `audit/scripts/verify_cleanup.py` (read-only counts), `audit/scripts/cleanup_identities.py` (deletes sessions, subscriptions, developer keys, SET NULL artifacts, tenant data, device trial, then users).

## Pre-cleanup state

`audit/cleanup-before.json` (2026-11-27T11:47Z):

| Item | Count |
|---|---:|
| Users by audit email | 16 |
| Users by matrix ID | 16 |
| Sessions | 16 |
| Subscriptions | 11 |
| Developer API keys | 13 |
| Team seats owned | 2 |
| Tenant members | 2 |
| Compilations | 72 |
| Optimizations | 8 |
| Usage analytics | 28 |
| GDPR requests | 4 |
| Tenants owned | 1 |
| Device trials | 1 |
| Migration head | `0109_error_alerts` |

One team-owner tenant remained at cleanup time; the security auditor had already deleted tenant B. The cleanup script also deletes any tenant owned by an audit user, so a late-created tenant cannot escape. The 55 compilations include the performance load (simple-1/5, complex-1/5/10) and cohort/reliability jobs. All are owner-scoped and are deleted explicitly or by cascade.

## Deletion order

1. `tenant_members`, `team_seats`, `tenant_domain_events`, `tenants` for all tenants owned by audit users (not just matrix IDs).
2. `developer_api_keys`, sessions, subscriptions.
3. `compilations`, `optimizations`, `usage_analytics`, `gdpr_requests` - these FKs are `SET NULL`, so they would survive as orphans if not deleted explicitly.
4. `device_trials` by the audit fingerprint.
5. `users` by matrix ID.

## Post-cleanup state

`audit/cleanup-after.json` (2026-11-27T12:05Z) shows all counts 0, migration head `0109_error_alerts`, database `neondb`, and zero `audit+%` users. Six GDPR request rows remain by database trigger: the disposable signup's export/deletion, the free identity's expired/ready exports and rejected deletion, and the security export `e6a5b566…`. Four now have `user_id=NULL`; the disposable signup retains its anonymized subject UUID by design. They are legal audit evidence, not residue to delete.

## Redis / object storage

Compile jobs live in Redis Streams with a 24-hour TTL; the nine WebSocket-audit jobs and performance jobs are not deleted by the Postgres cleanup. They expire naturally. R2 render artifacts are listed by the performance/security reports; they are not deleted because the audit has no bucket credentials and deleting shared artifacts was out of scope. No artifact was made public by the audit.
