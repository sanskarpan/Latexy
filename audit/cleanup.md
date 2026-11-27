# Cleanup register — production audit 2026-11-27

Suffix: `20261127103328`. Identity matrix: `audit/plans/identity-matrix.json`.
Cleanup script: `audit/scripts/cleanup_identities.py` (deletes sessions, subscriptions, tenant/members, team seats, developer keys, device trial, then users).

## Identities to delete

All 16 user identities and 1 anonymous device trial created by `provision_identities.py`. The auth auditor's disposable signup was anonymized and its GDPR rows are retained by design.

## Test artifacts to delete with identities

| Source | Artifacts | Status |
|---|---|---|
| Pro/BYOK/developer report | resumes, compilations, jobs, PDFs, portfolio/share, developer keys (revoked), BYOK fixture key (deleted), 2 failed optimizations | delete via user cascade; job/PDF rows may need explicit cleanup |
| Free/Basic report | 6 resumes, 2 history rows, 4 jobs/PDFs, 1 tracker item, 2 optimize/AI-assist calls; import/share/portfolio artifacts were already deleted by the agent | delete via user cascade; listed in `audit/plans/free-basic.md` |
| Student/Team/Trial report | resumes/jobs/PDFs, one student verification email, temporary tenant + membership, 3 invited seats, one residual invite, one removed seat. DB fixtures F2-F11 were restored or deleted by the agent; final seats = owner + member. | delete via user cascade; verify no `audit-member-tenant-*` rows |
| Admin analytics probe | 1 resume, direct compile, 1 async job, activity/usage rows | delete via admin identity cascade |
| Auth/GDPR | disposable signup anonymized; export/deletion/approval rows retained (legal evidence) | keep; list in final cleanup |
| Lead latency probes | 270 read requests (no writes) | none |
| Lead entitlement probes | 3 deep-analysis jobs, 1 failed optimize | delete/leave as evidence then purge |
| Events auditor | 9 terminal compile jobs and their Redis Streams; all test resumes and collaborator rows already deleted | jobs TTL 24 h; purge streams if clean-state audit requires |
| Security/tenant auditor | pro/free resumes, comments, tracker item/reminder, share, portfolio `auditsec-103328`, GDPR export `e6a5b566…` (ready until 12:05Z), tenant B and cohort (deleted by the agent), developer key (revoked), compilation/finalization rows with `resume_id=NULL`, R2 PDF `render-artifacts/v1/5ea2c0d1…/pdf/c429…pdf` | agent cleaned portfolio/share/tenant/per-user overrides; remaining user-owned rows cascade with the identity; R2 object listed as retained |
| Performance auditor | warm/concurrent compile jobs and PDF artifacts; 40-compile ceiling | delete via user cascade; R2 objects listed in `audit/latency/cost.md` |
| Reliability auditor | quota-exhaustion fixtures, duplicate/cancel jobs, malformed LaTeX jobs; free quota counter reset; `compile` revoked then granted to basic-annual; plan changed free then basic_annual; stuck job `f1d55ffa…` left basic-annual at 10/400 because its unit was never refunded | delete via user cascade; the stuck unit is on an audit identity, not a customer; per-user feature/plan changes disappear with the identities (final state verified in report) |
| Performance/reliability/security/WS agents | compiles/jobs/resumes/tenants created after this file was written | append before final cleanup |

## Global configuration

- Phase 4 controlled entitlement test: `d25` kill switch was briefly set false and restored true; free-plan `d25` matrix was briefly set false and restored true. Final `GET /admin/entitlements` is byte-identical to the pre-test snapshot (`audit/changes/production-changes.md`).
- No plan catalog, pricing, role, flag, or deploy change remains.

## Deferred

- Final cleanup runs after all agents finish and evidence is captured.
- Verify: zero `audit+%@example.test` users, zero audit sessions, zero audit dev keys, zero audit tenants; DB head unchanged.


## Execution result - 2026-11-27T12:05Z

`cleanup_identities.py` deleted, in one transaction:

- 16 users, 16 sessions, 11 subscriptions, 13 developer keys
- 1 tenant, 2 tenant members, 2 team seats
- 72 compilations, 8 optimizations, 28 usage rows, 1 device trial

`cleanup-after.json` confirms all zero; no `audit+%` user remains; DB head is still `0109_error_alerts`. Six `gdpr_requests` rows remain by database trigger (legal retention): the disposable signup's export/deletion, the free identity's expired/ready exports and rejected deletion, and the security export. Four have `user_id=NULL`; the disposable signup keeps its anonymized subject UUID. They are listed in `cleanup-verification.md`.

Redis compile streams and R2 PDF artifacts are not deleted by the Postgres cleanup; their 24 h/TTL and object list are recorded in the parent reports. No global config, plan, role, flag or deploy change remains.

## Front-end interaction cleanup - 2026-11-27T16:20-17:00Z

| Pass | Identities | Rows deleted | Remaining |
|---|---|---|---|
| interact5 (PDF import attempt) | 1 free user | jobs/resume via user cascade, session | 0 |
| interact6 (PDF import PASS) | 1 free user | 1 compilation, 1 resume, session, user | 0 |
| interact7 (share/review) | 1 pro user + synthetic subscription | 1 compilation, 1 job finalization, 1 resume, 1 subscription, session, user | 0 |
| ATS attempt (interact3) | 3 users (free/admin/team) + tenant/workspace | tenant members, tenant, workspace members, workspace, dependent rows, sessions, users | 0 |
| Admin/team attempt (interact4) | 2 users + tenant/workspace | tenant/workspace rows, 2 subscriptions, sessions, users | 0 |

- All audit/interaction users matching `interact%` and `audit.fe.%`: **0**.
- DB head remains `0109_error_alerts`.
- The interact7 render artifact in R2 has no DB reference and is eligible for the existing `render-artifacts/v1` orphan sweep (retention prefix, 1 h grace).
- No live payment, global flag, plan catalog or entitlement change was made by these passes; the only plan row was the synthetic pro subscription deleted with interact7.

