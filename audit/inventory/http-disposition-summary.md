# HTTP disposition summary - 2026-11-27

Source schema: `audit/inventory/openapi-source.json` (558 paths / 636 operations at deployed backend SHA `ee1a405d`). The live `/openapi.json` and `/docs` are disabled (404), so the source schema is the only complete schema.

Full per-operation table: `audit/inventory/http-disposition.csv` (636 rows). `audit/inventory/http.csv` carries the same `status` and `notes`.

## Counts

| Disposition | Operations | Share |
|---|---:|---:|
| Tested live | 212 | 33.3% |
| Blocked, with reason | 424 | 66.7% |
| **Total** | **636** | **100%** |

Tested by method: GET 160, POST 38, DELETE 9, PATCH 3, PUT 1, HEAD 1.
Blocked by method: POST 242, GET 101, PATCH 35, DELETE 34, PUT 11, HEAD 1.

## What "tested" means

- GET: live request from the audit workstation with a cohort token or anonymous; status, latency, request id and body size are in `http-disposition.csv`. These were the 10:41-11:12 UTC sweep plus targeted rechecks.
- Non-GET: request actually observed in a cohort or event evidence file (`audit/plans/*`, `audit/events/ws-audit.md`, or the temp raw evidence). Request ids are carried where the evidence captured one. Some rows show both success and failure statuses (for example `/byok/api-keys` returned 500 for a rejected key and 200 for an unvalidated key).

## Blocked reasons

| Reason | Count |
|---|---:|
| Path parameter needs a domain fixture/destructive setup not provisioned | 275 |
| Mutation needs a safe domain fixture not provisioned in this pass | 101 |
| Admin mutation/global-config/destructive action not exercised | 24 |
| Requires provider callback, mailbox, authenticator or OAuth consent | 16 |
| Live payment/provider action; no charges or callbacks allowed | 8 |

Blocked is a safety disposition, not an assertion that the endpoint is broken. The most material untested surfaces are:

- **Admin writes** (81 `POST /admin/*`): plan/capability changes, GDPR execute/review, refunds, user PII reveal, key revocation. Read paths were tested with `admin-superadmin`; one controlled entitlement mutation was executed and restored (`audit/changes/production-changes.md`).
- **AI mutations** (22 `POST /ai/*`): most need a resume/job fixture and spend LLM budget; the core `/optimize`, `/ats/deep-analyze`, AI assist and optimization paths were exercised by the cohort auditors.
- **Path-parameter reads/writes**: concrete IDs from cohort fixtures were deleted during cleanup before a full per-ID sweep could run. This is the largest residual coverage gap.
- **Billing/webhooks**: no live charges were allowed. Dodo webhook behavior is inferred from the stored failed events and source, not replayed.
- **OAuth/provider callbacks**: no readable mailbox or provider consent screen.

## Operations outside the schema

The independent coverage auditor found **674 registered operations** in code versus 636 in the source schema. The 38 hidden operations are 35 admin routes plus `/livez`, `/readyz`, `/metrics`; all are registered with `include_in_schema=False`. They are inventoried in `audit/inventory/http-coverage-audit.csv` and diffed in `audit/inventory/coverage-diff.md`. `/readyz` and `/jobs/health` were tested; the hidden admin routes were not, for the same safety reasons above.

## Evidence quality

- Every tested row has a timestamped source and, for GET, a live status/latency/request id.
- Every blocked row has a reason that names the missing fixture or safety constraint.
- No row is marked "works" from source reading alone.
- `GET` rows with 401/403/422 are retained as tested negative evidence; an auth/entitlement response is not a server failure.

## Residual gap statement

The audit does **not** claim all 636 operations were exercised end-to-end. It claims every operation is dispositioned, and the untested 424 are blocked for a named, reproducible reason. Closing the 275 path-parameter rows requires stable fixtures (one resume, one job, one share, one portfolio, one tenant per cohort) kept alive for a dedicated per-ID sweep; those fixtures were intentionally deleted during this audit's cleanup.
