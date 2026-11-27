# Auth, Account & GDPR — Cohort Report

**Audit window:** 2026-11-27T10:43:28Z → 2026-11-27T11:00:30Z
**Cohorts tested:** `free` (`96c507cd-e7a2-4749-9153-96b6321742db`) + one fresh disposable email/password signup (`de17a255-09cc-45fc-bceb-b67e2fc2985c`). `admin-superadmin` (`8b2ee54b-a2ee-4009-9eee-4cc995b3d2ad`) was used only as the operator for legal-review/legal-hold actions; `admin-support` and `free` were used for role-boundary negatives.
**Backend:** `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`
**Frontend/auth:** `https://latexy.xyz` (Better Auth under `/api/auth`)
**Deployment identity:** `GET /api/deployment-identity` → 200, `commitSha=d2cbc51ab8c25106d073e0e0065b985fc6dc6490`, `source=vercel`, 2026-11-27T10:43:28Z. Matches `audit/ground-truth.md`.
**No global configuration, capability, plan, flag, or deployment change was made.** All writes were scoped to the free identity or the disposable signup; the disposable identity was the only account erased.

---

## 1. Verdict

| Area | Verdict | Evidence summary |
|---|---|---|
| Signup | **PASS** | Weak-password rejection 400; real signup 200 with user + 7-day session |
| Email verification — send contract | **PASS** | `send-verification-email` 200 `{status:true}`; invalid link token 401; delivery itself unconfirmable |
| Email verification — link click | **BLOCKED** | No readable inbox exists for `@example.test`; the endpoint returned 200 but delivery could not be verified |
| Email-verification enforcement | **PASS** | Export and deletion both 403 `identity_verification_required` while unverified |
| Login / logout | **PASS** | Correct/wrong password paths; sign-out invalidates current session; backend 401 after |
| Session expiry | **PASS** | Expired session → frontend `null`, backend 401; restored session active again |
| Password reset request + consume | **PASS** | Generic 200 request; signed reset token consumed; old password 401, new password 200; all sessions revoked |
| 2FA (TOTP) | **PASS** | Enable returns TOTP URI + 10 backup codes; active 2FA forces challenge; valid TOTP issues session |
| Passkey — availability | **PASS** | Register-options returns WebAuthn challenge, `rp.id=latexy.xyz`; unauth 401; bogus delete 401 |
| Passkey — registration | **BLOCKED** | No authenticator/WebAuthn device available in the harness |
| Google OAuth — initiation | **PASS** | 200 authorization URL to `accounts.google.com` with state + PKCE |
| Google OAuth — callback | **BLOCKED** | Requires Google account consent; not executed |
| GitHub OAuth | **DISABLED** | `POST /api/auth/sign-in/social {provider:github}` → 404 `PROVIDER_NOT_FOUND` |
| Onboarding events + consent | **PASS** | Grant → 202 capture; withdrawal → 403; duplicate `event_id` deduped; `has_onboarded=true` |
| Account export request/download | **PASS** | 202 ready + 254-char HMAC token; 200 signed bundle; negative matrix pass |
| Export expiry/rotation | **PASS** | Expired → 410 + status `expired`; reissue invalidates old token 403 |
| Deletion request/validation | **PASS** | 422 wrong phrase; 202 `legal_review/pending`; duplicate returns same request |
| Deletion dry-run | **FAIL (not implemented)** | No dry-run/preview route exists; see AAG-D02 |
| Legal review (approve/reject) | **PASS** | Approve → `approved`; reject → `rejected`; execute after reject 409 |
| Legal-hold block | **PASS** | Active hold → execute 409 `legal_hold`; request `blocked`, `legal_hold_blocked=true` |
| Release + erasure execution | **PASS** | 54 delete steps completed, 0 failed, 13 retained; login after erasure 401 |
| Erasure idempotency | **PASS** | Execute replay 200 `completed`, `attempts` remained 1 |
| Retention exceptions | **PASS with reporting gap** | Subscription, GDPR requests/events and admin audit rows survived; retained counts are always 0 (AAG-D04) |
| Admin audit trail | **PASS** | `/admin/audit` returns approved/blocked/completed rows with actor, request id, before/after |
| Role boundaries | **PASS** | support and free roles → 403 on admin GDPR; unauth → 401 |
| Auth rate limiting | **FAIL** | Single global `untrusted-proxy` bucket; see AAG-D01 |

**Defects:** 1×P1, 1×P2, 3×P3 — see `audit/defects/auth-account-gdpr.md`.

---

## 2. Identity and safety record

| Item | Value |
|---|---|
| Free cohort | `96c507cd-e7a2-4749-9153-96b6321742db`, `audit+free-20261127103328@example.test`, plan `free`, email verified |
| Disposable signup | `de17a255-09cc-45fc-bceb-b67e2fc2985c`, `audit+gdpr-signup-20261127103328@example.test`, created 2026-11-27T10:47:01.392Z via `POST /api/auth/sign-up/email` |
| Operator | `admin-superadmin` `8b2ee54b-a2ee-4009-9eee-4cc995b3d2ad` |
| Per-account writes | verified-email flag on the disposable account (mailbox unavailable); synthetic `subscriptions` row for retention proof; temporary stale/fresh session rows for free (deleted after use); export expiry set in DB for free (one request); all writes listed in §9 |
| Global writes | **none** |
| Irreversible actions | exactly one: erasure of the disposable signup, after request → legal review → legal-hold block → release. No free/admin identity was deleted or anonymized |
| Rate control | 20 requests/min ceiling observed; no 429 was deliberately induced (AAG-D01 already proves the shared bucket; inducing a 429 would lock out other audit traffic) |

---

## 3. Environment and availability checks

| Check | Result | Latency | Evidence |
|---|---|---|---|
| Deployment identity | 200, `d2cbc51…`, vercel | — | 2026-11-27T10:43:28Z |
| `GET /api/auth/ok` | 200 `{ok:true}` | — | 2026-11-27T10:45:08Z |
| `GET /api/auth/providers` | 200 `{google:true, github:false, oidc:null}` | — | 2026-11-27T10:45:08Z |
| `GET /api/auth/get-session` no cookie | 200 `null` | 1,409 ms cold | — |
| `POST /api/auth/two-factor/enable` no session | 401 `UNAUTHORIZED` | 266 ms | — |
| `GET /api/auth/passkey/generate-register-options` no session | 401 `UNAUTHORIZED` | 296 ms | — |
| `GET /account/gdpr/policy` no session | 401 `Authentication required` | 1,870 ms | request `89e2d375-cc43-4c1a-9dae-9db3e05ffea3` |
| `POST /account/gdpr/exports` no session | 401 | 1,636 ms | request `a2eebafa-fa24-4dcb-9a16-8760020b1f44` |
| `POST /account/gdpr/deletion` no session | 401 | 2,086 ms | request `be5f87dc-f4c9-45b8-b0e5-245455b0c752` |
| `GET /admin/gdpr/requests` no session | 401 | 2,152 ms | request `07197222-26fd-48f7-bfc1-23f8f5e4eb72` |

All six GDPR endpoints and both admin GDPR reads enforce authentication before any body/state handling.

---

## 4. Signup and email verification

### 4.1 Signup

| Step | Observed | Status | Evidence |
|---|---|---|---|
| Weak password | 400 `PASSWORD_TOO_SHORT`, no user created | PASS | 286 ms |
| Valid signup | 200; `user.emailVerified=false`, `twoFactorEnabled=false`; `__Secure-better-auth.session_token` set; body token issued | PASS | 568 ms; user `de17a255…`; `createdAt=2026-11-27T10:47:01.392Z` |
| Session immediately usable | 200 `get-session`; `expiresAt=2026-12-04T10:47:01.467Z` (7 days) | PASS | DB session `943f22c5-d052-4d2b-a869-7d434c0eaccd` |
| Self-serve account state | DB `subscription_plan=free`, `subscription_status=inactive`, `auth_provider=unknown` | Observation | `/me` 200 plan `free`; session, export, onboarding and 2FA flows all worked |

No email-verification row keyed to the email was observed after signup or resend; the deployed version may use a signed token rather than a stored verification row (not confirmed). This was not classified as a defect because the send contract and the enforcement gate both passed.

### 4.2 Email verification

| Step | Observed | Status | Evidence |
|---|---|---|---|
| Resend verification | 200 `{"status":true}` | PASS | 314 ms, 2026-11-27T10:47:49Z |
| Invalid verification token | 401 `INVALID_TOKEN` | PASS | `GET /api/auth/verify-email?token=invalid-token` |
| Successful link click | **not executable** — `@example.test` has no inbox | BLOCKED | No mailbox; no verification row to consume |
| Export while unverified | 403 `identity_verification_required` | PASS | request `44d62fe0-7000-4e0a-867d-f57380601b21` |
| Deletion while unverified | 403 `identity_verification_required` | PASS | request `c3779e3d-04e8-496d-b6fe-99f61b6c6750` |
| Verified-email flag set (DB) | `/me` 200; export/deletion gate opened | PASS (documented write) | `UPDATE users SET email_verified=true WHERE id='de17a255…'` |

The gate is correctly ordered before confirmation/re-authentication checks; an unverified account cannot start either data-subject workflow.

---

## 5. Login, logout and session expiry

| Step | Observed | Latency | Status |
|---|---|---|---|
| Wrong password | 401 `INVALID_EMAIL_OR_PASSWORD` | 400 ms | PASS |
| Correct password (pre-2FA) | 200 + session cookie + body token | 403–2,049 ms | PASS |
| Sign-out | 200 `{"success":true}` | 267 ms | PASS |
| `get-session` after sign-out | 200 `null` | 265 ms | PASS |
| Backend `/me` after sign-out | 401 | 2,577 ms | PASS |
| Expired session (DB set `expiresAt` in past) | frontend `null`; backend 401 | 284 ms / 2,640 ms | PASS |
| Expiry restored | 200 session | 265 ms | PASS |
| 7-day lifetime | `expiresAt - createdAt = 7d` | — | PASS |

Sign-out deletes only the current session row; older sessions created by earlier sign-ins remained, which is expected for Better Auth. Password reset revoked all sessions (§6).

---

## 6. Password reset

| Step | Observed | Latency | Status |
|---|---|---|---|
| Request reset | 200 generic `If this email exists…` | 312 ms | PASS |
| Reset token storage | `verification.identifier=reset-password:<24-char>`, `value=<user uuid>`, TTL 60 min | — | PASS (read-only DB inspection) |
| Consume reset token | 200 `{"status":true}` | 1,577 ms | PASS |
| Old session after reset | `get-session` 200 `null` | 279 ms | PASS — all sessions revoked |
| Old password | 401 | 400 ms | PASS |
| New password | 200 + new session | 403 ms | PASS |
| Invalid/replayed token | 400 `INVALID_TOKEN` | — | PASS |
| Unknown-email reset | 200 same generic `If this email exists…` message; no account disclosure | 1,015 ms | PASS |
| Unknown-email sign-in | 401 same `INVALID_EMAIL_OR_PASSWORD` as a wrong password | 371 ms | PASS |

Single-sample timings are not used to claim an enumeration side-channel; only the response shapes were compared.

The reset token row was removed from `verification` on use (DB count 0 for that identifier).

---

## 7. 2FA and passkeys

### 7.1 TOTP

| Step | Observed | Status |
|---|---|---|
| Enable (authenticated, password supplied) | 200 `{method:"totp", totpURI:"otpauth://…", backupCodes:[10]}` | PASS |
| Activation semantics | `user.twoFactorEnabled` remains `false` until the first `verify-totp`; `users.two_factor_enabled` then becomes `true`; `twoFactor` row has encrypted secret + backup codes | PASS (observed) |
| Sign-in with active 2FA | 200 `{"twoFactorRedirect":true,"twoFactorMethods":["totp"]}`; only `__Secure-better-auth.two_factor` cookie; `get-session` 200 `null` | PASS |
| TOTP verification | 200 session token + full user; `get-session` 200; `twoFactorEnabled=true` | PASS |
| Backup codes | 10 returned once; encryption configured (`storeBackupCodes:'encrypted'`); not consumed | PASS (availability only) |
| Lockout policy | 10 failures / 15 min configured; not exercised | Not tested |

No 2FA bypass was found once activation was complete. The earlier pre-activation sign-in issued a session because activation had not yet been completed — this is the documented Better Auth enable/verify sequence, not a bypass.

### 7.2 Passkey

| Step | Observed | Status |
|---|---|---|
| Register options (fresh authenticated session) | 200 `{challenge, rp:{name:Latexy,id:latexy.xyz}, user:{id,name,displayName}, pubKeyCredParams[-8,-7,-257], timeout:60000, attestation:"none", excludeCredentials:[]}` | PASS |
| Unauthenticated options | 401 | PASS |
| Delete bogus passkey | 401 `PASSKEY_NOT_FOUND` | PASS |
| Full registration / authentication | No WebAuthn authenticator in harness | BLOCKED |

Passkey is enabled and correctly origin-bound to `latexy.xyz`; full credential lifecycle could not be exercised headlessly.

---

## 8. Google / GitHub / OIDC

| Provider | Contract | Status |
|---|---|---|
| Google | `POST /api/auth/sign-in/social {provider:google,disableRedirect:true}` → 200 authorization URL at `accounts.google.com` with `state`, `code_challenge` (S256), `redirect_uri=https://latexy.xyz/api/auth/callback/google` | PASS (initiation); callback BLOCKED |
| GitHub | Same call → 404 `PROVIDER_NOT_FOUND` | DISABLED |
| Institutional OIDC | `/api/auth/providers` returns `oidc:null` | DISABLED |

The Google initiation response exposed only public OAuth parameters (host, state presence, PKCE presence); values are not reproduced here.

---

## 9. Onboarding events and consent

| Step | Observed | Latency | Status |
|---|---|---|---|
| Consent grant (anonymous, no auth) | 202 `{accepted:true,recorded:true,decision:"granted"}` | 2,371 ms | PASS |
| Complete `get-started` step | 202 `{recorded:true,completion_reconciled:true}` | 2,286 ms | PASS |
| Preferences reconciliation | `/me` → `preferences.has_onboarded=true` | 2,656 ms | PASS |
| Second step view | 202 recorded | 2,040 ms | PASS |
| Duplicate `event_id` | 202 `{recorded:false,duplicate:true}`; no second row | 2,024 ms | PASS |
| Consent withdrawal | 202 `{decision:"withdrawn"}` | 1,928 ms | PASS |
| Event after withdrawal | 403 `Analytics consent is required` | 2,092 ms | PASS |
| Admin snapshot (admin-superadmin) | 200, `suppressed:true`, all summary metrics `null`, `minimum_cohort_size:5` | 2,111 ms | PASS with AAG-D05 |
| Admin snapshot version list | `available_flow_versions:[{flow_version:"v1",events:2}]` while suppressed | — | **AAG-D05 (P3)** |

The onboarding rows are stored under the authenticated user (`usage_analytics`), and the terminal event correctly marks `has_onboarded`. Consent rows are anonymous and survive account erasure because they carry no user link.

---

## 10. Account export contract

### 10.1 Positive path (free and disposable)

| Step | Observed | Latency | Evidence |
|---|---|---|---|
| Create export (verified) | 202; `request.status=ready`; `download_token` 254 chars; `expires_at=+30 min`; `download_token_header=X-GDPR-Export-Token` | 1,957–2,650 ms | disposable `c1c7ef10-acf6-4c74-96ae-1fd43295a101`; free `00ad102a…`, `fded5745…` |
| Reissue | 202; same request id; `reissued:true`; 30-min TTL reset | 2,026–2,418 ms | request `6fdd6f69-1cda-48ad-b5af-068abde33d66` |
| Download | 200; `Content-Disposition: attachment; filename="latexy-gdpr-export-<id>.json"`; `Cache-Control: no-store`; CSP `default-src 'none'; sandbox`; envelope `{manifest,data}` | 1,913–2,577 ms | request `af8d649b-093e-48cb-8961-836698a6ec1b` |
| Manifest integrity | Recomputed `sha256(canonical JSON(data)) == manifest.data_sha256` | — | digest match (free) |
| Scope | `data` keys: `profile,resumes,resume_files,cover_letters,job_applications,payments,subscriptions,usage,credentials,retention_exceptions,export_scope` | — | free bundle 10,890 bytes; 2 resumes, 0 subscriptions/payments |
| Secret exclusion | Recursive key scan found only `credentials` metadata (`byok_keys:[], developer_keys:[], note:"Secret values, hashes and encrypted material are never exported."`) | — | no password/token/hash keys in bundle |
| Credential metadata | `credentials` contains metadata only, no secret values | — | PASS |

### 10.2 Negative matrix

| Case | Observed | Status | Evidence |
|---|---|---|---|
| Missing token header | 400 `missing_export_token` | PASS | request `c72c3746-89d0-495d-9512-42821520f516` |
| Tampered token | 403 `invalid_export_token` | PASS | request `3e8c36a8-0554-43ea-9d12-a9f7b1125327` |
| Cross-user download (free session, disposable export) | 404 `Export request not found` | PASS | request `dfef0bdd-621b-46db-bc26-adc7864719a6` |
| Expired link | 410 `export_expired`; request status becomes `expired` | PASS | request `5a8e6780-bf06-408f-8d56-ca600275e94d`; get request `2712442e-3e05-4611-aca7-a1f08476c022` |
| Old token after reissue | 403 invalid | PASS | request `7dc0a075-59de-43a9-8a56-26a2060abe70` |
| New token after reissue | 200 download | PASS | request `1a325f7e-68b7-40f0-832e-30f7ccdd3945` |
| Unauthenticated create | 401 | PASS | §3 |
| Download after erasure (disposable) | Code path rejects `@privacy.invalid` accounts with 404; **not executed** because no valid token was retained after erasure | Not tested (code-level guard only) | `gdpr_service.download_export` email guard |

Export generation is synchronous (no worker queue) and takes ~2 s warm. No export job or orphan artifact was left behind; download bundles are generated on demand and not stored.

---

## 11. Account deletion, legal review, legal hold and erasure

### 11.1 Request and validation

| Step | Observed | Latency | Status |
|---|---|---|---|
| Unverified email | 403 `identity_verification_required` | 1,982 ms | PASS |
| Wrong confirmation text | 422 `confirmation_mismatch` | 1,868 ms | PASS |
| Whitespace/case-normalized confirmation | 202 accepted (`" DELETE MY ACCOUNT "`) | 2,044 ms | PASS |
| Missing reason | 202 accepted; reason optional | 2,072 ms | PASS |
| Correct request | 202; `status=legal_review`, `legal_review_status=pending`, `identity_verified=true`, `reauthenticated_at=2026-11-27T10:53:38.129Z`, `confirmed_at=2026-11-27T10:54:39.021Z`; retention exceptions returned | 2,044 ms | PASS; request `c9cba012-7804-46b2-ada4-08cb25afcefd` |
| Duplicate request | 202 same id, `created:false` | 1,879 ms | PASS |
| Stale session (created 30 min earlier) | 403 `reauth_required` | 1,863 ms | PASS |
| User reads request | 200 `legal_review` | 3,303 ms | PASS |

### 11.2 Legal review and legal hold

| Step | Observed | Latency | Status |
|---|---|---|---|
| Admin list pending deletion | 200, one item | 1,780 ms | PASS |
| Support role on admin GDPR | 403 `Admin privileges required` | 2,619 ms | PASS |
| Free role on admin GDPR | 403 `Admin privileges required` | 2,264 ms | PASS |
| Place legal hold | 201; `active:true`; masked email; actor recorded | 2,032 ms | PASS; hold `99b83561-24dd-4afb-87be-24ad3b5c2217` |
| Approve legal review | 200; `status=approved`, `legal_review_status=approved`, `legal_reviewed_at` set | 1,801 ms | PASS |
| Execute while held | 409 `legal_hold`; payload `status=blocked`, `legal_hold_blocked=true`, `failure_code=legal_hold` | 2,904 ms | PASS |
| User sees blocked request | 200 `blocked`, `legal_hold_blocked=true` | 2,024 ms | PASS |
| Release hold | 200; `active:false`, release actor/time/reason | 2,012 ms | PASS |

### 11.3 Execution

| Step | Observed | Latency | Status |
|---|---|---|---|
| Execute after release | 200 `status=completed`; `attempts=1`; 67 table results: **54 completed, 0 failed, 13 retained** | 3,659 ms | PASS |
| User profile | `users` anonymized: `email=deleted+56c280c2dfcc74427274@privacy.invalid`, `name=NULL`, `email_verified=false`, `two_factor_enabled=false`, `subscription_id=NULL`, `user_metadata=NULL`, `rows_affected=1` | — | PASS |
| Auth rows | `account=0`, `session=0`, `twoFactor=0`, `passkey=0` | — | PASS |
| Retained rows | `subscriptions=1` (synthetic `f5e7a8e2-293e-4921-afcd-62130e79110e`), `gdpr_requests=2`, `gdpr_request_events=5`, `admin_audit_log` rows retained | — | PASS |
| Retained tables reported | `payments, subscriptions, payment_refunds, admin_refund_requests, admin_approvals, billing_webhook_events, quota_ledger_accounts, quota_ledger_reservations, referral_rewards, admin_audit_log, gdpr_requests, gdpr_request_events, gdpr_legal_holds` | — | PASS |
| Idempotent execute replay | 200 `completed`; `attempts` remains 1 | 2,426 ms | PASS |
| Login after erasure | 401 `INVALID_EMAIL_OR_PASSWORD` | 1,511 ms | PASS |
| Backend `/me` after erasure | 401 | 1,674 ms | PASS |
| Hold on anonymized account | 409 `already_anonymized` | 2,154 ms | PASS |

### 11.4 Rejection path (free cohort, non-destructive)

| Step | Observed | Status |
|---|---|---|
| Free deletion request with fresh session | 202 `legal_review/pending`; request `98a1e187-57cf-47ea-bd5a-cc80b7b4d3dc` | PASS |
| Admin rejects | 200 `status=rejected`, `legal_review_status=rejected`, review note set | PASS |
| Execute rejected request | 409 `legal_review_required` | PASS |
| User cancels rejected request | 409 `not_cancellable` | PASS |
| Erasure | none performed; free account and its data remain | PASS |

### 11.5 Audit trail

| Surface | Observed | Status |
|---|---|---|
| `GET /admin/audit?target_id=<deletion request>` | 200; rows for `gdpr.deletion.approved`, `gdpr.deletion.blocked`, `gdpr.deletion.completed`, each with actor id/email, request id, before/after, IP, timestamp | PASS |
| `GET /admin/audit?action=gdpr.deletion.completed` | 200, one row, `total:1` | PASS |
| `GET /admin/gdpr/requests?request_type=deletion&status=completed` | 200, completed request with full per-table report | PASS (9,594 ms — see §12) |
| `GET /admin/gdpr/legal-holds?active_only=false` | 200; our hold shown released; masked email now `de…@privacy.invalid` | PASS |
| `gdpr_request_events` | 5 append-only transitions: `requested → legal_approved → blocked_by_legal_hold → started → completed` | PASS |
| `admin_approvals` | `executed` for disposable; `rejected` for free | PASS |
| User-facing event timeline | `/account/gdpr/requests/{id}` returns status/review/table results but **not** the event timeline | Observation (not filed as a defect) |

### 11.6 Deletion dry-run

No dry-run or preview route exists in the source OpenAPI at the deployed SHA (`audit/inventory/openapi-source.json`) or in `account_gdpr_routes.py`. `GET /account/gdpr/policy` returns static retention categories and TTLs; `POST /account/gdpr/deletion` immediately creates a `legal_review` request. The closest non-destructive evidence used before erasure was: inspect policy → create request → legal review → place hold → attempt execution (blocked) → release → execute. This is filed as **AAG-D02 (P2)**.

---

## 12. Latency observations

Single-sample / small-n observations only; the performance auditor owns statistical latency work.

| Surface | Observed | Notes |
|---|---|---|
| Better Auth warm reads (`get-session`, sign-out, passkey options, 2FA verify) | 261–306 ms | Vercel edge/function warm |
| Better Auth sign-in | 403–2,049 ms | 403–443 ms warm after first; 1.5–2.0 s cold |
| Better Auth signup | 568 ms | |
| Password reset request | 312 ms | |
| Password reset consume | 1,577 ms | |
| GDPR policy / list | 2,233–2,834 ms | Modal backend baseline |
| Export create/download | 1,913–2,650 ms | synchronous generation |
| Deletion request | 2,044–2,208 ms | |
| Deletion execute | 3,659 ms | 67 table steps |
| Admin GDPR completed list | **9,594 ms** | single item with 67-entry `table_results`; likely cold start + large payload; flagged to performance auditor, not filed as a latency defect here |
| Admin audit query | 2,164 ms | |

---

## 13. Artifacts, writes and cleanup

### 13.1 Per-account writes (all intentional, all listed)

| Timestamp (UTC) | Account | Write | Status |
|---|---|---|---|
| 10:47:01 | disposable | User + account + session created via signup | erased at 10:55:01 |
| 10:47:49 | disposable | Password reset token created and consumed | token deleted on use |
| 10:50:43–10:53:40 | disposable | 3 consent events + 2 onboarding events | onboarding rows erased with account; consent rows remain anonymous |
| 10:51:59–10:53:23 | disposable | 2FA secret/backup codes; passkey challenge; TOTP challenge rows | auth rows deleted by erasure; transient `verification` rows remain (AAG-D03) |
| 10:50:25–10:54:39 | disposable | Export request + deletion request + admin approval | export retained; deletion retained |
| 10:54:50–10:54:58 | disposable | Legal hold placed and released | released, `active=false` |
| 10:58:31 | free | Temporary fresh session row for reauth test | deleted at 10:58:37 |
| 10:57:26–10:58:36 | free | Two export requests; one DB expiry edit; one deletion request + admin rejection | retained as audit evidence; no data erased |

No global config, capability, plan catalog, feature flag, deployment, or payment state was modified. No live charge or invoice was created.

### 13.2 Surviving artifacts (for cleanup / analytics exclusion)

| Artifact | ID / value | Disposition |
|---|---|---|
| Anonymized disposable user | `de17a255-09cc-45fc-bceb-b67e2fc2985c` → `deleted+56c280c2dfcc74427274@privacy.invalid` | Retained by design (erasure anonymizes, does not hard-delete the users row) |
| Disposable export request | `c1c7ef10-acf6-4c74-96ae-1fd43295a101` (status `ready`, expires 11:20Z) | Expires; retains no downloadable data for anonymized account |
| Disposable deletion request | `c9cba012-7804-46b2-ada4-08cb25afcefd` (`completed`) | Retained by security-audit exception |
| Disposable admin approval | `79ec3123-446a-43b9-a20c-6002718fa00a` (`executed`) | Retained by audit exception |
| Disposable legal hold | `99b83561-24dd-4afb-87be-24ad3b5c2217` (released) | Retained as evidence |
| Disposable 2FA/passkey challenge rows | 5 `verification` rows, value/user id; expire 10:58–11:03 | Natural TTL; see AAG-D03 |
| Synthetic subscription | `f5e7a8e2-293e-4921-afcd-62130e79110e` on anonymized user | Retained by financial exception (retention proof) |
| Free export requests | `00ad102a-80cb-46e8-ad62-cfb62e2ad024` (`expired`), `fded5745-a5cc-4ac7-b592-ab54c1c5d554` (`ready`, expires 11:27Z) | Retained as evidence |
| Free rejected deletion | `98a1e187-57cf-47ea-bd5a-cc80b7b4d3dc` (`rejected`) | Retained as evidence |
| Free admin approval | rejected row for `98a1e187…` | Retained as evidence |
| Onboarding consent rows | `74c7c9ea-8463-4c7b-85b2-52c90f8f84cc`, `bd697b6e-0b6a-418f-ad0d-278e312df42f`, `9222b4ac-6d5f-450e-8b88-18762f9d8f13` | Anonymous; no user link |
| Google OAuth state row | `auth-state:…`, created 11:00:14Z, expires 11:10Z | Transient PKCE/state record from initiation; no token |
| Auth rate-limit rows | keys beginning `untrusted-proxy` + path | Operational counters, 24 h retention |
| Temporary free session rows | `audit_stale_reauth_…`, `audit_fresh_reauth_…` | Deleted during test |

**Pre-existing, not created by this run:** a `blocked` deletion request `7aec7bff-b733-4f37-ad03-f56cdfb92795` from 2026-11-26 with `user_id=NULL` is still in the table. It is left untouched and should be dispositioned by the cleanup auditor.

---

## 14. Limitations / blocked

1. **Email verification success link** — `@example.test` has no readable inbox, and delivery to the reserved `.test` TLD cannot be confirmed. Send contract, invalid-token behavior, and the `email_verified` gate were exercised; a successful click was not. No attempt was made to forge a signed verification token.
2. **Passkey registration/authentication** — no WebAuthn authenticator in the harness. Options generation and authorization were verified.
3. **Google OAuth callback** — requires a real Google account consent; only initiation was exercised. GitHub was correctly disabled.
4. **Backup-code and 2FA lockout paths** — backup codes were issued but not consumed; lockout threshold was not tripped to avoid locking the disposable account before deletion.
5. **Deletion dry-run** — no route exists (AAG-D02); the request/review/hold sequence was used as the non-destructive precursor.
6. **Latency** — one to a few samples per endpoint; not enough for p50/p95 claims. The 9.6 s admin list is a single observation.
7. **429** — not deliberately induced; the shared-bucket defect is proven from the live `auth_rate_limit` keys plus source, without exhausting the bucket other agents share.

---

## 15. Defect references

| ID | Severity | Summary |
|---|---|---|
| AAG-D01 | P1 | Auth rate limiting collapses all clients into one `untrusted-proxy` bucket on Vercel → global 18 sign-ins/min, 5 resets/hour |
| AAG-D02 | P2 | No account-deletion dry-run/preview contract |
| AAG-D03 | P3 | Erasure leaves token-keyed `verification` rows containing the subject UUID for up to ~1 h |
| AAG-D04 | P3 | Retention report always reports `rows_affected: 0`, so surviving rows are not quantified |
| AAG-D05 | P3 | Onboarding admin suppression leaks `available_flow_versions.events` below the 5-account minimum | 
