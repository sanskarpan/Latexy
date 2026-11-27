# Defects — Auth, Account & GDPR

**Audit window:** 2026-11-27T10:43:28Z → 2026-11-27T11:00:30Z
**Cohorts:** free (`96c507cd-e7a2-4749-9153-96b6321742db`), disposable signup (`de17a255-09cc-45fc-bceb-b67e2fc2985c`), admin-superadmin operator (`8b2ee54b-a2ee-4009-9eee-4cc995b3d2ad`), admin-support and free role negatives.
**Reports:** `audit/plans/auth-account-gdpr.md`
**No global configuration was changed by any test in this scope.**

| ID | Severity | Surface | Status |
|---|---|---|---|
| AAG-D01 | P1 | Auth rate limiting (all Better Auth endpoints) | Open |
| AAG-D02 | P2 | Account deletion dry-run/preview | Open — not implemented |
| AAG-D03 | P3 | GDPR erasure cleanup of `verification` rows | Open |
| AAG-D04 | P3 | GDPR retention reporting | Open |
| AAG-D05 | P3 | Onboarding analytics small-cohort suppression | Open |

---

## AAG-D01 — Auth rate limiting is one global bucket on Vercel, not per client

**Severity:** P1 (availability + trivial denial of service on core auth)
**Surface:** `POST /api/auth/sign-in/email`, `/sign-up/email`, `/request-password-reset`, `/send-verification-email`, `/sign-out`, `/two-factor/*`, `/passkey/*`, and every other Better Auth path behind `enforceAuthRateLimit`
**Cohorts affected:** all users, anonymous and paid
**Observed:** 2026-11-27T10:45–11:00Z

### Expected

The limiter keys each bucket by the caller's IP (or another client-specific key), so one client's traffic cannot consume another client's budget. The documented design says the limiter is per-IP (`lib/auth-rate-limit.ts` header comment).

### Actual

Live production buckets are keyed `untrusted-proxy|<path>` for every caller. `clientIp()` returns the literal `untrusted-proxy` whenever `X-Forwarded-For` is present and `TRUST_PROXY_HEADERS` is not `true`; Vercel always supplies `X-Forwarded-For`, and the deployed frontend does not trust proxy headers. The result is a single global fixed-window counter per auth path.

Observed live rows (read-only DB snapshot, 2026-11-27T11:00Z):

```
untrusted-proxy|/sign-in/email             count=1
untrusted-proxy|/sign-up/email             count=1
untrusted-proxy|/request-password-reset    count=2
untrusted-proxy|/send-verification-email   count=1
untrusted-proxy|/sign-out                  count=3
untrusted-proxy|/get-session               count=6
untrusted-proxy|/two-factor/verify-totp    count=1
untrusted-proxy|/passkey/...               count=1
```

The key contains no client address. Even requests from different source networks would share it.

Effective global budgets from `RATE_LIMIT_RULES`:

| Path prefix | Window | Max (global) | Consequence |
|---|---|---|---|
| `/sign-in` | 10 s | 3 | 18 sign-ins/minute for the entire product; OAuth `sign-in/social` shares it |
| `/sign-up` | 10 s | 3 | 18 signups/minute |
| `/request-password-reset` | 3600 s | 5 | 5 reset emails/hour globally |
| `/send-verification-email` | 3600 s | 5 | 5 verification emails/hour globally |
| default (includes `/sign-out`, 2FA verify, passkey) | 60 s | 20 | 21st sign-out or 2FA/passkey attempt in a minute is 429 for everyone |

### Reproduction

1. Read `auth_rate_limit` in production after ordinary auth traffic; every row key begins `untrusted-proxy|`.
2. Inspect `frontend/src/lib/auth-rate-limit.ts`:
   - `RATE_LIMIT_RULES` lines 62–78 (3/10 s sign-in, 5/h reset);
   - `clientIp()` lines 127–140 (untrusted XFF → `untrusted-proxy`);
   - `enforceAuthRateLimit()` lines 207–226 (bucket key = IP + path).
3. Send four `POST /api/auth/sign-in/email` requests from any client within 10 s → all later clients receive 429. Not executed deliberately here to avoid locking out other audit traffic; the bucket key and rule make the outcome deterministic.

### Impact

- At launch, normal sign-in volume above 18/min (3 concurrent users retrying) exhausts the global budget; everyone receives 429 until the 10-second window rolls.
- An unauthenticated attacker can deliberately exhaust sign-in, sign-up, reset, sign-out, 2FA and passkey budgets with a handful of requests. Sign-out being globally limited at 20/min is a session-hygiene denial of service.
- Password reset and verification email delivery are capped at 5/hour for the entire user base, which will block legitimate account recovery.

### Proposed fix

- On Vercel, enable a trusted-proxy mode and key on the proxy-written client IP (e.g. `x-real-ip` or the Vercel-provided forwarded header), never on a client-supplied first XFF hop. Verify with two source IPs that the bucket key differs.
- Add an independent per-account bucket for authenticated endpoints (`sign-out`, 2FA verify, passkey management) so a single IP/NAT cannot lock out unrelated accounts.
- Keep the atomic Postgres counter; only change the key derivation. Add a regression test that two distinct client IPs do not share a counter.
- Consider raising the reset/verification email budget per account while retaining a per-IP abuse cap.

### Evidence

`audit/plans/auth-account-gdpr.md` §3, §5, §14; DB `auth_rate_limit` snapshot 2026-11-27T11:00Z; source `frontend/src/lib/auth-rate-limit.ts`.

---

## AAG-D02 — No account-deletion dry-run or preview contract

**Severity:** P2 (data-subject safety / compliance capability gap; no data loss)
**Surface:** `POST /account/gdpr/deletion`, `GET /account/gdpr/policy`
**Cohorts affected:** every account
**Observed:** 2026-11-27T10:53–10:58Z

### Expected

The audit brief requires a deletion dry-run: a non-mutating preview of what would be erased, what would be retained, and ideally per-table counts, before the typed confirmation creates a legal-review request.

### Actual

No dry-run/preview path exists. The source OpenAPI at the deployed SHA and `backend/app/api/account_gdpr_routes.py` expose only:

- `GET /account/gdpr/policy` — static policy metadata (TTL, confirmation phrase, retention categories);
- `POST /account/gdpr/deletion` — immediately creates a `gdpr_requests` row in `legal_review/pending` and an `admin_approvals` row.

There is no `?dry_run=true`, no `POST /account/gdpr/deletion/preview`, and no row counts. The request response includes the static `retention_exceptions` list (categories/tables/reasons) but no indication of how many rows of each class the caller actually has.

### Reproduction

1. Enumerate `audit/inventory/openapi-source.json` → only `/account/gdpr/{policy,requests,exports,deletion}` paths; no deletion preview.
2. Inspect `account_gdpr_routes.py` lines 49–160: `request_deletion` is the only deletion route and calls `gdpr_service.request_deletion`, which inserts the request and approval.
3. Call `POST /account/gdpr/deletion` with the correct phrase on a disposable account → 202 `legal_review`; a DB row is created immediately. There is no precursor that returns row counts.

### Impact

- A data subject cannot see the scope of an erasure before confirming; the only preview is a static category list.
- Support/legal cannot answer “how many resumes/payments/audit rows will be retained?” without a manual DB query.
- The audit had to use policy inspection + request + legal hold + blocked execution as the non-destructive proxy; that is more invasive than a dry-run should be.

### Proposed fix

- Add `POST /account/gdpr/deletion/preview` (or a `dry_run` flag on the existing route) requiring the same verified email and fresh session. Return per-table counts for erase/retain classes and the retention reasons, with no mutation and no approval row.
- Keep the existing typed-confirmation request as the mutating step; rate-limit and audit the preview separately.
- Add a contract test asserting the preview is non-mutating (`gdpr_requests` count unchanged).

### Evidence

`audit/plans/auth-account-gdpr.md` §11.6; `backend/app/api/account_gdpr_routes.py`; `audit/inventory/openapi-source.json` path list.

---

## AAG-D03 — Erasure leaves token-keyed `verification` rows containing the subject UUID

**Severity:** P3 (residual identifier/auth-challenge material; no login bypass observed)
**Surface:** `gdpr_service.execute_deletion`, step `auth_verification`
**Cohorts affected:** erased accounts that used 2FA, passkeys, or an unconsumed password reset
**Observed:** 2026-11-27T10:55:01Z, after the disposable erasure completed

### Expected

After a completed erasure, rows that carry the subject's UUID or authentication challenge material should be removed, not merely left to expire. The erasure report claims `auth_verification` completed with `rows_affected` for verification rows.

### Actual

`DELETION_STEPS` contains:

```python
DeletionStep(
    "auth_verification",
    "verification",
    "delete",
    "DELETE FROM verification WHERE identifier = (SELECT email FROM users WHERE id = CAST(:uid AS uuid))",
    ...
)
```

Better Auth stores non-email verification records as `identifier = '2fa-<challenge>'`, `identifier = '2fa-attempts-<challenge>'`, and `identifier = 'reset-password:<token>'`, with `value = <user uuid>`. None matches `identifier = email`, so they survive erasure until TTL.

Observed after `request c9cba012-7804-46b2-ada4-08cb25afcefd` completed:

- 2 × `2fa-…` rows, `value=de17a255-…`, expire 11:02:35Z / 11:03:23Z;
- 2 × `2fa-attempts-…` rows (same challenge, counter value);
- 1 × passkey registration challenge row (`identifier` opaque, value JSON), expire 10:58:38Z.

An unused password-reset token (`reset-password:<token>`, `value=<user uuid>`, TTL 60 min) would likewise survive; the token used in this run had already been consumed, so that variant is code-level, not observed live.

### Reproduction

1. Create a disposable account, enable 2FA (enable + verify), start a passkey registration, and request a password reset but do not consume it.
2. Request and execute erasure.
3. Query `SELECT identifier, value, "expiresAt" FROM verification WHERE value='<user uuid>'` → `2fa-*`, `2fa-attempts-*`, and `reset-password:*` rows remain.
4. Query `users`, `account`, `session`, `twoFactor`, `passkey` → all auth rows gone; only the transient `verification` rows remain.

### Impact

- A subject UUID and authentication challenge material remain in the database after the erasure report says the credential rows were cleared, for up to ~1 hour.
- No session/account/password/2FA secret remains, so no login or 2FA bypass was demonstrated. The risk is residual-identifier retention and audit inaccuracy, not immediate account takeover.
- A future feature that trusts a surviving challenge row could turn this into a larger issue.

### Proposed fix

- Delete `verification` rows by `value = :uid` as well as by the old email identifier, or add a `user_id` column and scope on it.
- Include `identifier LIKE '2fa-%'`, `2fa-attempts-%`, `reset-password:%`, and passkey challenge rows when `value` matches.
- Add a post-erasure sweep/assertion that no `verification` row references the user UUID.
- Re-run the erasure test with an unconsumed reset token and a live passkey challenge.

### Evidence

`backend/app/services/gdpr_service.py` `auth_verification` step; DB `verification` rows after 2026-11-27T10:55:01Z; `audit/plans/auth-account-gdpr.md` §11.3, §13.2.

---

## AAG-D04 — Retention report always says `rows_affected: 0`, even when rows are retained

**Severity:** P3 (reporting accuracy / audit usefulness; deletion behavior is correct)
**Surface:** `POST /admin/gdpr/requests/{id}/execute` response `table_results`
**Cohorts affected:** every erased account with retained billing/audit rows
**Observed:** 2026-11-27T10:55:01Z

### Expected

For a `retain` result, the report should quantify what survived (row count per table), or explicitly say `not_counted`, so an operator or data subject can verify the retention exception.

### Actual

`execute_deletion` appends every `RetentionStep` with a hardcoded `rows_affected: 0`:

```python
for retained in RETENTION_STEPS:
    results.append({
        "table": retained.table,
        "step": f"retain_{retained.table}",
        "action": "retain",
        "status": "retained",
        "rows_affected": 0,
        "reason": retained.reason,
        "category": retained.category,
    })
```

Live erasure response: 13 retained entries, all `rows_affected: 0`. Independent DB verification showed the rows did survive:

- `subscriptions = 1` (`f5e7a8e2-293e-4921-afcd-62130e79110e`),
- `gdpr_requests = 2`,
- `gdpr_request_events = 5`,
- 3 `admin_audit_log` rows, and the `admin_approvals` row.

The report is therefore not literally false (`rows_affected` by the deletion action is 0), but it is ambiguous and does not quantify retention.

### Reproduction

1. Before erasure, insert/confirm at least one retained row for the subject (the audit used a synthetic subscription).
2. Execute erasure.
3. Inspect `table_results`: retained entries all have `rows_affected: 0`.
4. Query the retained tables by user id: the rows exist.

### Impact

- Operators and data subjects cannot verify that the financial/audit exception actually retained the expected records.
- A regression that accidentally deletes retained rows would not be visible in the report.
- Compliance evidence is weaker than it appears.

### Proposed fix

- Count retained rows per table in the same execution transaction and report the number, or use `rows_affected: null` with `count_status: "not_counted"` instead of `0`.
- Add a contract test that a synthetic subscription produces `subscriptions: 1` in the retained report.
- Keep the reason/category fields; add `subject_count` or `retained_rows`.

### Evidence

`backend/app/services/gdpr_service.py` retention-result loop; execute response request id `9017fae3-f159-418d-b0b0-f2bcd72f4ecd`; DB counts after erasure; `audit/plans/auth-account-gdpr.md` §11.3.

---

## AAG-D05 — Onboarding small-cohort suppression leaks event counts in `available_flow_versions`

**Severity:** P3 (admin-only privacy-filter inconsistency)
**Surface:** `GET /admin/analytics/onboarding`
**Cohorts affected:** any flow version with fewer than 5 accounts
**Observed:** 2026-11-27T10:50:56Z

### Expected

When a cohort is below the documented minimum (`minimum_cohort_size: 5`), the endpoint suppresses cohort-derived numbers, including any count that can reveal activity from a 1–4 account cohort.

### Actual

The response correctly returned:

```json
"summary": { "suppressed": true, "suppressed_cell": ..., "accounts": null, ... },
"minimum_cohort_size": 5,
```

but also returned:

```json
"available_flow_versions": [{ "flow_version": "v1", "events": 2 }]
```

With a one-account test cohort, `events: 2` reveals that at least one account produced two events even though the summary is suppressed. The leak is admin-only, but it defeats the stated suppression rule for the version selector.

### Reproduction

1. Create/collect fewer than 5 accounts with onboarding events for a flow version (the audit used one disposable account with two events).
2. Call `GET /admin/analytics/onboarding?days=1` as admin.
3. Observe `summary.suppressed=true` and `available_flow_versions[].events=2`.

### Impact

- A small-cohort activity count is visible to admins despite the suppression contract.
- No end-user or cross-tenant exposure; low severity.
- If the version list is later exposed beyond admin, the leak becomes larger.

### Proposed fix

- Apply the same `<5` suppression to `available_flow_versions[].events` (return the version label only, or `events: null`/`"suppressed"`).
- Add a test asserting no numeric event count is returned when the account cohort is below the minimum.

### Evidence

Admin snapshot request `e3f45479-3c6f-4946-8010-a53d7ccf7812`; `audit/plans/auth-account-gdpr.md` §9.

---

## Not filed as defects (observations for the lead)

| Observation | Detail | Why not filed |
|---|---|---|
| Admin GDPR completed-list latency | `GET /admin/gdpr/requests?status=completed` took 9,594 ms on a single item with 67 `table_results` (request `8c9518c1-56fe-44a1-b790-b64285fffe16`). Other admin GDPR reads were 1.7–2.2 s. | Single sample, likely cold start + large payload; performance auditor owns latency methodology/SLO comparison |
| No user-facing GDPR event timeline | `/account/gdpr/requests/{id}` returns status/review/table results but not the five `gdpr_request_events` transitions that admins can read via `/admin/audit`. | Admin audit trail exists; product requirement for a user-facing timeline is not established |
| Consent records are unauthenticated | `POST /analytics/consent` accepts any `anonymous_id`; an actor who knows another visitor's id can grant/withdraw consent for it. `anonymous_id` is opaque and client-generated. | Analytics-integrity residual risk, not an account/GDPR access-control failure; no PII in the record |
| Self-serve free account is `subscription_status=inactive` | DB after signup: `subscription_plan=free`, `subscription_status=inactive`; `/me` and the tested account flows behaved as free. | No functional failure observed in this scope; billing auditor owns status semantics |
| Prior orphan deletion request | `7aec7bff-b733-4f37-ad03-f56cdfb92795`, status `blocked`, `user_id=NULL`, created 2026-11-26T01:18Z. Not created by this run. | Pre-existing cleanup item; left untouched |
| Email-verification success click | Could not be exercised because `@example.test` has no inbox. Send contract, invalid-token 401, and `email_verified` enforcement all passed. | Test-environment limitation, not a product failure |

---

## Cross-references

- Cohort report: `audit/plans/auth-account-gdpr.md`
- Identity matrix: `audit/plans/identity-matrix.json`
- Ground truth: `audit/ground-truth.md`
- Production changes: none from this scope; `audit/changes/production-changes.md` remains authoritative for the identity provisioning entry
