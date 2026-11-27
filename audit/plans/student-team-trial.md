# Student / Team / Trial / Past-due / Cancelled — Cohort Report

- **Audit window:** 2026-11-27T10:56:54Z – 2026-11-27T11:40:23Z
- **Environment:** production, `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`
- **Backend commit:** `ee1a405de6058e814c3a6f5ffba5fe3630576421` (`GET /health`, 10:56:54Z, request `39dfd66a…`)
- **Identities:** suffix `20261127103328` from `audit/plans/identity-matrix.json`:
  - `student` `d91e5bf0-bbc9-4558-9e10-151e728cdeec`
  - `team-owner` `6bb81a84-860b-46a5-8ab4-f1c483068479`
  - `team-member` `7a3d3b80-000c-49f0-a067-96c177b7c848`
  - `trial-active` `3b8ddb07-2b18-486c-9c18-d32ce3fbbb47`
  - `trial-expired` `620c8a6e-db14-4be2-806a-13365c667fdd`
  - `past-due` `a24f1fd9-34f9-4a84-8ba8-74d8fa431ca1`
  - `cancelled` `dfd20a28-a4d5-40db-aa77-597ce6f3e589`
- **Method:** direct HTTPS from the audit workstation, serialized, 3.3 s minimum spacing (~18 requests/min), no load loops, no live payments. Every call logged with UTC timestamp, `X-Request-Id`, status, latency and a bounded response summary.
- **Raw evidence (JSONL, temp):**
  - `C:\Users\Sansk\AppData\Local\Temp\opencode\sst-evidence-a-1795777010.jsonl` (student/trial/past-due/cancelled)
  - `…\sst-evidence-b-1795777681.jsonl` (team/tenant)
  - `…\sst-evidence-c-1795777989.jsonl`, `…\sst-evidence-c-1795778017.jsonl` (follow-ups)
  - `…\sst-evidence-d-1795778108.jsonl` (team-member owner-subscription states; student metadata)
  - `…\sst-evidence-e-1795778243.jsonl` (seat-limit boundary)
  - `…\sst-evidence-f-1795778565.jsonl` (trialing vs active; cancel_scheduled boundary)
  - `…\sst-evidence-g-1795778609.jsonl` (team-member cancel_scheduled boundary)
  - `…\sst-evidence-h-1795779078.jsonl` (past-due change-plan path)
  - `…\sst-evidence-i-1795779483.jsonl` (member vs non-member tenant C; member tenants after concurrent security tenant)
- **Global changes:** none. No plan catalog, capability grant, feature flag, deployment or billing configuration was changed. All writes were per-account test fixtures or per-account product writes.

---

## 1. Verdict

| Area | Result | One-line evidence |
|---|---|---|
| Student plan catalog | **PASS** | `student` visible, `purchasable:true`, `requires_student_verification:true`, ₹29,900/mo; billing `available:true` |
| Student checkout — non-academic email | **PASS** | HTTP 200 `success:false`, `"Student plan requires a verified academic email address"` (`31cc3b1c…`) |
| Student checkout — academic email | **PASS with abuse caveat** | HTTP 200 `verificationRequired:true`, preview URL withheld; API reported an email send (`df390379…`), delivery unverified; see ST-D06 |
| Student verification token — invalid | **PASS** | HTTP 400 `"Student verification link is invalid or expired"` (`72a838f0…`) |
| Student verification token — valid activation | **BLOCKED** | Token lives only in production Redis / the delivered email; neither is readable from the audit host |
| Student plan entitlements (active, linked provider row) | **PASS** | compilations/optimizations/assists `limit:null`; resume/compile/PDF completed (`fbd6d5e0…`) |
| Student entitlement without `student_verified` metadata | **OBSERVED** | Still `limit:null`; verification is a purchase-time gate, not a continuous entitlement check |
| Trial active — baseline | **PASS** | `planId:pro`, `status:trialing`, quotas `limit:null` |
| Trial active — linked `trialing` provider row | **FAIL** | Quotas collapse to Free (10/day) while `/subscription/current` still says Pro unlimited → **ST-D01** |
| Trial active — linked `active` provider row | **PASS** | Quotas remain `limit:null` (`df1a3523…`); the failure is specific to the `trialing` status |
| Trial expired — access | **PASS** | Free fallback: 10 compiles/day, 3 optimizations, 25 assists; create/read/compile/PDF all work |
| Trial expired — read-only fallback | **NOT IMPLEMENTED** | No read-only lock; the account retains Free-tier writes. Product copy does not promise read-only |
| Trial conversion prompt | **PARTIAL** | All plans remain purchasable, but active trial is rendered as a paid “Renews on” card and expired trial as a generic Free card → **ST-D03** |
| Past-due — grace before period end | **PASS** | Linked `past_due` with +2 day period end → Basic 400/mo, 10 opt, 100 assists (`fae228c7…`) |
| Past-due — grace expired | **PASS** | Same row with past period end → Free 10/day, 3/mo, 25/mo; writes still allowed |
| Past-due — display vs enforcement | **FAIL** | `/subscription/current` still advertises Basic 400/mo while quotas are Free 10/day → **ST-D02** |
| Past-due — recovery path | **FAIL** | `POST /subscription/create` → 200 `success:false` `"Manage or cancel your current paid subscription before starting another."` (`220e4ded…`) → **ST-D03** |
| Cancelled — terminal access | **PASS** | Linked `cancelled` → Free quotas; create/compile/PDF still work; data retained |
| Cancelled — scheduled cancellation boundary | **PASS** | `cancel_scheduled` + future end → Basic 400/mo; past end → Free (`db35e4a4…`, `4d4095a5…`) |
| Team owner — seat list | **PASS** | 200, owner + member active, both with user ids (`c4b228e0…`) |
| Team member — seat-bound access | **PASS** | Active seat + active owner subscription → unlimited; owner lapses → Free; restore → unlimited |
| Team member — owner-only seat actions | **PASS** | `GET /team/seats`, `POST /team/invite`, `DELETE /team/seats/{id}` all 403 (`fb0c9794…`, `02f11693…`, `bad0c1b5…`) |
| Team member — owner-only tenant actions | **PASS** | stats, PATCH, invite, remove owner, billing, upgrade-intent, create tenant all 403 |
| Team seat limit | **PASS** | Exactly 5 seats: resend pending 201; new invite 400 `"Team seat limit reached (5)"` (`79bfe9fb…`, `8e16acdf…`) |
| Team invite — duplicate/self/non-team | **PASS** | Active duplicate 409; self 400; non-team 403 |
| Team invite — create | **PASS** | 201, pending seat, `invite_preview_url:null` (no token leak) (`c64737da…`) |
| Team invite — accept by token | **BLOCKED** | Token is only in production Redis / the `.test` mailbox; acceptance path not executed; state emulated via DB |
| Tenant isolation — owner vs other tenant | **PASS** | Owner A on tenant B: stats/members/PATCH all 403 (`408820da…`, `cb354864…`, `08114790…`) |
| Tenant isolation — member vs other tenant | **PASS** | Member reads non-member tenant C: stats/members 403, `/tenants/my` excludes C (`f4468dfb…`, `68614b40…`, `f80f4621…`); member A role 403 on A admin surfaces; cross-user resumes 404 |
| Tenant isolation — existence oracle | **FAIL (low)** | Existing tenant → 403, nonexistent → 404 for a non-member → **ST-D05** |
| Tenant invite — create/invalid token | **PASS** | Owner 201 with no preview URL; invalid token 404 (`8a8a1204…`, `36df6d32…`) |
| Tenant invite — accept by token | **BLOCKED** | Same production-Redis/mailbox constraint; state emulated via DB |
| Tenant billing snapshot | **PARTIAL** | 200 but `subscription.available:false` (`tenant_subscription_link_missing`); team seats `owner_scoped_not_tenant_scoped` → **ST-D07** |
| Cross-user document access | **PASS** | Non-owner `GET /resumes/{id}` → 404; owner 200; own update 200 |
| Capability-level plan gating | **BLOCKED** | All 165 keys in the entitlement feature map (149 gateable per CAP-01) returned `true` for every cohort, including Free/downgraded; consolidated as CAP-01 (`audit/defects.md`), also `audit/plans/pro-byok-developer.md` §11.2 |
| Compile path | **PASS (slow)** | 5/5 compiles completed; 1-page PDF 8,919 B; submit→terminal ≈28 s in this window; referred to performance auditor |

**Defects:** 3×P2, 4×P3, plus 2 harness/coverage findings — see `audit/defects/student-team-trial.md` (ST-D01…ST-D07, ST-H01, ST-H02).

---

## 2. Safety and fixture corrections

No global mutation was performed. The identity matrix was provisioned by direct DB insert (documented fallback in `audit/scripts/provision_identities.py`); two fixture properties did **not** match the real product flow and were corrected before the team tests:

| # | Statement (exact) | Reason | Result / final state |
|---|---|---|---|
| F1 | `UPDATE users SET subscription_id = 'a23dfc57-2a3b-4461-8223-c24ea97d86fd'::uuid WHERE id = '6bb81a84-860b-46a5-8ab4-f1c483068479'::uuid` | The real Dodo webhook links the owner to the subscription row; provisioning left `subscription_id` null, which would make a seat-bound member unable to resolve the owner's paid plan | Left **set** (realistic production state); user delete cascades |
| F2 | `UPDATE users SET subscription_plan='team_member', subscription_status='active', subscription_id=NULL WHERE id='7a3d3b80-000c-49f0-a067-96c177b7c848'::uuid` | The member was provisioned as a direct `team` subscriber with their own subscription, not as a seat-bound member. A naive test would not exercise seat gating | Left **team_member / active**; seat active |
| F3 | `DELETE FROM subscriptions WHERE id='6a06f64e-688b-4125-a1e3-2d3bc2517ec2'::uuid` | Duplicate member-owned team subscription created by provisioning; a real member does not have one | Deleted |
| F4 | `UPDATE team_seats SET status='active', member_user_id='7a3d3b80-000c-49f0-a067-96c177b7c848'::uuid, joined_at=now() WHERE id='47c6e2a8-801e-499b-9ddc-d40efe77b82b'::uuid` | Restore the seat after removal/downgrade testing | Active |
| F5 | `UPDATE users SET subscription_id = NULL WHERE id=<trial-active/past-due/cancelled>` | Restore the matrix's unlinked baseline after provider-link tests | Restored |
| F6 | `UPDATE subscriptions SET current_period_end='2026-11-25T10:33:28Z' WHERE id='c977adc1-9c8e-460c-8e30-524439cd05cf'` | Restore the past-due period end after grace testing | Restored |
| F7 | `UPDATE subscriptions SET status='trialing' WHERE id='9c641be4-3702-4f2a-83f7-e9537036b903'`; `UPDATE subscriptions SET status='cancelled' WHERE id='951d99ec-7a32-418d-99ae-2a114ddc351f'` | Restore statuses after provider-status tests | Restored |
| F8 | `UPDATE users SET user_metadata='{}'::jsonb WHERE id='d91e5bf0-…'` then restore `{"student_verified":true,"student_verification":"audit"}` | Test runtime verification dependence | Restored |
| F9 | `INSERT INTO tenants (id,…,slug='audit-member-tenant-20261127103328',owner_id='7a3d3b80-…',plan_id='agency',max_members=5,active=true)` + `INSERT INTO tenant_members (…,'admin')` | Cross-tenant isolation fixture owned by the member; no API path can create a second owner without a new account | **Deleted** after tests (`DELETE FROM tenant_members …; DELETE FROM tenants …`) |
| F10 | `INSERT INTO team_seats (…,status='invited')` ×3; later `DELETE FROM team_seats WHERE id=…` | Seat-limit boundary and resend test | Deleted; final seats = owner + member active |
| F11 | `DELETE FROM team_seats WHERE owner_user_id='6bb81a84-…' AND status='removed'` | Remove the spent invitation row | Deleted |
| F12 | `INSERT INTO tenants (id,slug,name,owner_id,plan_id,max_members,active) VALUES ('51bd0e05-…','audit-owner-tenant-20261127103328','Audit Owner Tenant','6bb81a84-…','agency',5,true)` | Member-cannot-read-non-member-tenant fixture C (owner = team-owner, no member row) | **Deleted** after tests (`DELETE FROM tenant_members …; DELETE FROM tenants …`) |

Final DB state was verified after the last DB-mutating request (11:23:40Z); the 11:31:18Z past-due subscription-create attempt returned an error and made no DB change.

- `team-owner`: plan `team`, status `active`, `subscription_id` linked, team subscription active to 2026-12-27.
- `team-member`: plan `team_member`, status `active`, seat `47c6…` active, tenant A role `member`.
- `trial-active`: plan `pro`, status `trialing`, provider link null, subscription status `trialing`.
- `trial-expired`: plan `free`, status `expired`, no subscription.
- `past-due`: plan `basic`, status `past_due`, link null, period end 2026-11-25 (expired).
- `cancelled`: plan `basic`, status `cancelled`, link null, period end 2026-11-17.
- Tenant A (`577149dd…`), owner + member. Tenants B and C deleted. A concurrent security-auditor tenant `audit-sec-b-103328` (`3f98ed40-fcb0-4766-8dd0-e0f6807aa2b5`, owner = team-owner) appeared at ≈11:39Z; it is not this sub-agent's artifact and was not modified. The member has no row in it, so member isolation still holds.

The shared `identity-matrix.json` still records the member as plan `team` with subscription `6a06…`; this is now stale (see ST-H01). The matrix was not edited because it is a shared audit input.

---

## 3. Student verification

### 3.1 Catalog and checkout gate

`GET /subscription/plans` as `student`, 10:58:00.545Z, request `3cb04400-01fe-4dca-8043-eb4a3d43a84c`:

- Billing: `{provider:"dodo", feature_enabled:true, mode:"enabled", available:true, message:"Billing is available."}`
- Student: `{name:"Student", price:29900, currency:"INR", interval:"month", plan_family:"pro", requires_student_verification:true, purchasable:true, configured:true, unavailable_reason:null}`.
- The same catalog exposes Free/Basic/Pro/BYOK/Team as purchasable; no plan was disabled in the test window.

| Test | Request / time | Observed | Verdict |
|---|---|---|---|
| Non-academic address `audit.student@example.test` | `POST /subscription/create` 10:58:04.864Z, `31cc3b1c-7aeb-41d3-934c-be3db1b547c6` | 200, `success:false`, `error:"Student plan requires a verified academic email address"`; no email, no token, no charge | PASS |
| Academic address `audit.student.20261127103328@example.edu` | `POST /subscription/create` 10:58:09.437Z, `df390379-c4c9-4426-b418-0d9030f4293f` | 200, `success:true`, `verificationRequired:true`, `verificationPreviewUrl:null`, `message:"Verification email sent to your student address."` | PASS (delivery unverified) |
| Invalid verification token | `GET /subscription/student/verify/invalid-audit-token` 10:58:14.247Z, `72a838f0-45d7-46d7-b8cd-107853f39d96` | 400 `"Student verification link is invalid or expired"` | PASS |
| Valid verification token | Not executed | Token is created only in production Redis and sent only to the `.edu` address; audit host Redis is the dev endpoint (`redis://redis:6379`, no `latexy:quota:*` keys either) and no mailbox is available | **BLOCKED** |

The academic request was made while the `student` identity **already had an active student subscription** (`subscriptionId:audit_sub_20261127103328_student`, period end 2026-12-27). The server still accepted the request and reported that an email was sent. There is no “already subscribed” guard on this branch. See ST-D06.

### 3.2 Student plan access

| Test | Evidence | Observed |
|---|---|---|
| `/config/entitlements`, unlinked baseline | 10:56:59.374Z, `8ac82159-f3e1-4a62-8d4d-2e687d811241` | 200; 165/165 keys in the entitlement map true (149 gateable per CAP-01); compilations/optimizations/assists `limit:null` |
| Linked active student subscription | Follow-up after 11:17Z; `fbd6d5e0-7b8a-46b4-ab2e-c5ab4f3f4316` (exact request time not captured in that helper) | 200; `limit:null`, `used:1` after the compile; `/subscription/current` still `planId:student`, status `active`, period end 2026-12-27 |
| Resume create | 10:58:18.620Z, `807f4cd5-bb72-4a3b-8fe8-955f98e11851` | 201; resume `039fa23e-38f6-4bf3-a6f8-977a756b719d` |
| Resume read | 10:58:22.665Z, `f791358f-dbf7-443f-8a88-900879f5b96e` | 200, owner; title and LaTeX returned |
| Compile | submit 10:58:30.779Z `addc907b…`; job `31b9fb0f-f709-4f9d-9e7f-b55969a9817c`; completed by 10:58:58.593Z (`39939711…`) | 200 submit; terminal `completed`; quotas remained `limit:null`, `used:1` |
| PDF download | 10:59:19.657Z, `c0fd3a05-4c0f-449e-9c60-4fdea1718957` | 200 `application/pdf`, 8,919 B, `%PDF-` header; 17.8 s (cold) |

The runtime entitlement layer **does not** consult `user_metadata.student_verified`. With the metadata removed, `/config/entitlements` still returned `limit:null` (`cb074094-77e0-427a-a9b2-4fde52299559`, 11:15:41Z); restored metadata produced the same result (`6b882b54…`). Interpretation: verification is enforced at checkout/admission, not continuously. This is acceptable if verification is a one-time purchase gate, but it is not a defense against an incorrectly granted `student` plan (for example a direct DB/admin grant). Recorded as an observation, not a defect.

---

## 4. Trial lifecycle

### 4.1 Active trial

Baseline (`trial-active`), 10:57:25.886Z / 10:57:30.026Z:

- `/config/entitlements` `3c5bd208-14a1-4f37-bc08-0896d397dd5a`: compilations/optimizations/assists `limit:null`.
- `/subscription/current` `276bc859-5e6c-4d6d-b713-be746ec600ca`: `planId:pro`, `planName:Pro`, `status:trialing`, `features.compilations:"unlimited"`, `currentPeriodEnd:2026-12-04T10:33:28Z`, `subscriptionId:audit_sub_20261127103328_trial-active`.

The identity’s provider link (`users.subscription_id`) is null in the matrix. To test the real webhook state, the trialing subscription row (`9c641be4-3702-4f2a-83f7-e9537036b903`) was linked:

| State | `/config/entitlements` | `/subscription/current` |
|---|---|---|
| Linked, provider status `trialing` | **Free**: 10/day compiles, 3/mo optimizations, 25/mo assists (`133f72b3-2c71-43b0-a928-abf26ff43375`, 10:59:34Z) | **Pro unlimited, status `trialing`** (`5e5b563a-a64e-491e-9544-87a999309df4`, 10:59:38Z) |
| Unlinked (restored) | Pro unlimited (`2951c254-92de-4794-aac4-1fdae9d046a0`, 10:59:43Z) | Pro unlimited |
| Linked, provider status `active` (control) | Pro unlimited (`df1a3523-783d-4f51-bfed-03550b7e8c12`, 11:22:53Z) | — |

This is ST-D01. Root cause is in `backend/app/services/entitlement_service.py:562-575`: the linked provider path accepts `active`, `past_due`, and `cancel_scheduled` (with a future period end); any other status, including `trialing`, falls through to `"free"`. The display endpoint (`payment_service.get_user_subscription`, `backend/app/services/payment_service.py:641-662`) uses the stored `users.subscription_plan` and therefore still says Pro.

The trial-active compile after restoring the unlinked state succeeded: resume `98369a76-830f-489a-9d78-f69402eadea5`; job `e75c7d24-b9fb-4348-8bf8-8499cf510a96`; completed 11:00:21.658Z; PDF 8,919 B at 11:00:27.410Z (`a93c8841…`); `compilations.used` moved 0→1 with `limit:null`.

### 4.2 Expired trial

`trial-expired`, 11:00:36.863Z / 11:00:40.969Z:

- `/config/entitlements` `3c891643-2c1d-4afa-b3c9-8d1dd225d146`: Free 10/day, 3/mo, 25/mo.
- `/subscription/current` `51ce67ba-ac92-4cf1-afa2-01b9d4061660`: `planId:free`, `status:expired`, `subscriptionId:null`, `currentPeriodEnd:null`, Free feature copy.
- `GET /subscription/plans` `e8c823a6-b167-43b5-a0cc-b5cda05a9407`: billing available; all paid plans purchasable.

Access after expiry:

| Step | Evidence | Observed |
|---|---|---|
| Create resume | 11:00:49.431Z `dc84ab62-2452-458e-979a-a3a85060b5e3` | 201, resume `c6bccefc-97a3-4b16-819b-6ac549304f0a` |
| Read resume | 11:00:53.434Z `7ebf48af-2786-4740-aa23-d7d4651e9a84` | 200 |
| Compile | submit 11:00:59.445Z `288bebc0…`; job `b0a50800-9fd8-44c8-9258-ac5bd00f99a9` | completed by 11:01:27.360Z (`94a967b9…`) |
| PDF | 11:01:33.062Z `416df50c-6a02-4934-8370-d1b91023589b` | 200, 8,919 B |
| Quota after | 11:01:38.212Z `8a7a1a18-1701-45b7-bc45-7244f5829c3c` | Free compilations `used:1`, `limit:10`; no reset or lockout |

**Read-only fallback:** none. The expired trial is a normal Free account with write and compile rights (subject to Free quotas); export/delete were not exercised. This is not documented as a read-only state in `legal/terms-of-service.md`; the legal definition only describes a guest trial and a Free account. Reported as “not implemented” rather than a failure, because no product copy promises read-only. If read-only was the intended retention behavior, it is missing. The separate **TRIAL-01** finding (`audit/defects.md`) records that `trial_used` is never read by entitlement and there is no checkout trial period; this report confirms the trial lifecycle is represented only by `subscription.status`/`planId`, not by trial-specific product state.

**Conversion prompt:** the API exposes no trial-specific fields (`trialEndsAt`, `trialUsed`, `isTrial`); `status:"trialing"` is the only signal. The frontend `SubscriptionManager` (`frontend/src/components/billing/SubscriptionManager.tsx:269-288`) labels every non-`cancel_scheduled` paid state with “Renews on …”, so an active trial is presented as a paid renewal, and an expired trial falls into the generic Free branch (“You’re currently on the Free plan”, “Browse Plans”, lines 246-266). This is ST-D03. The live UI was not rendered because the audit identities have no password and their `.test` mailboxes are unreadable; the finding is source-verified at the deployed SHA.

---

## 5. Past-due and cancelled

### 5.1 Past-due grace

Baseline `past-due` (unlinked), 11:01:42.923Z / 11:01:47.067Z:

- `/config/entitlements` `1b389c1a-d0de-459f-929b-7cd516ad7877`: effective **Free** (10/day, 3/mo, 25/mo).
- `/subscription/current` `63f423c9-af06-4629-a715-b0ff856a0cb6`: `planId:basic`, `status:past_due`, `subscriptionId:audit_sub_…past-due`, `currentPeriodEnd:2026-11-25T10:33:28Z` (already past), Basic feature copy (400/mo).

Linked provider tests:

| State | Entitlements | Evidence |
|---|---|---|
| `users.subscription_id` linked; subscription `past_due`; period end +2 days | Basic: 400/mo compiles, 10/mo optimizations, 100/mo assists | `fae228c7-8c80-4813-a753-332bfeab0913`, 11:01:51.802Z |
| Same, period end restored to 2026-11-25 (past) | Free: 10/day, 3/mo, 25/mo | `7cc8d20c-a9f6-4cd3-bf27-360986c250f4`, 11:02:00.588Z |

`/subscription/current` during grace (`74786305-5251-4f86-8027-d8fbc4da70e1`) still reports Basic 400/mo and `currentPeriodEnd:2026-11-29T11:01:47Z`; with the period end in the past (baseline and after restore) it still reports Basic 400/mo (`63f423c9…`). The server correctly enforces Free; the display does not. This is ST-D02.

Past-due fallback writes:

- Resume `03d02d07-e052-4f7e-b8af-4677ea01cb53` created 11:02:05Z (`5f3f88c8…`), read 200 at 11:02:09Z (`3f5e7a43…`).
- Compile job `2f430c46-d8f6-433f-b5ce-82f115075204` submitted 11:02:15Z (`5717f47c…`), completed 11:02:42Z (`6f0740dd…`), PDF 8,919 B (`d3da0d0d…`).
- Quota `45a59dd6-9387-4179-9774-097d0bdea4d5`: Free compilations `used:1`, `limit:10`.
- Retention: the resume remains listed (`GET /resumes/?limit=10` 11:14:00Z, `8f761483…`, total 1). No deletion on downgrade.
- Recovery path: the past-due user tried to start a replacement Pro plan (`POST /subscription/create`, 11:31:18Z, `220e4ded-7384-41f6-8396-f41c18f2189c`). The API returned 200 `success:false` `"Manage or cancel your current paid subscription before starting another."` No checkout was created and no charge was attempted, but there is no self-serve “update payment method” or “retry payment” path in the subscription contract; the generic “Change Plan” button therefore dead-ends. This is part of ST-D03.

### 5.2 Cancelled

Baseline `cancelled`, 11:02:58.059Z / 11:03:02.223Z:

- `/config/entitlements` `f9941cc8-857b-4e22-8af7-51f5bad37d59`: Free 10/day, 3/mo, 25/mo.
- `/subscription/current` `4ec7d438-7346-4b8c-ad09-180bfcaa2a3a`: `planId:basic`, `status:cancelled`, period end 2026-11-17 (past), Basic feature copy (400/mo).

Linked terminal row test: `473fdd83-a835-4422-ab47-58b49e363858` (11:03:06Z) → Free quotas even with the provider row linked, which is correct for a terminal cancellation.

Scheduled cancellation boundary (status temporarily changed to `cancel_scheduled`, then restored):

| State | Entitlements | Evidence |
|---|---|---|
| `cancel_scheduled`, period end +2 days | Basic 400/mo, 10/mo, 100/mo | `db35e4a4-3bc2-40b8-92c4-2f8a748c87e7`, 11:22:59Z |
| `cancel_scheduled`, period end 2026-11-17 | Free 10/day, 3/mo, 25/mo | `4d4095a5-46f9-436b-85e0-6d91c1d74aab`, 11:23:05Z |

Cancelled fallback writes:

- Resume `d7ac5f92-cd82-4873-b14f-f6847c54ded3` created 11:03:11Z (`28f8acf4…`), read 200 11:03:15Z (`2a91b41c…`).
- Compile job `5a569e45-1ba9-47c7-aa37-c0d336f80aa5` submitted 11:03:22Z (`595d01af…`), completed 11:03:52Z (`ceb47ee5…`), PDF 8,919 B (`6722d9ab…`).
- List 11:04:01Z (`67be052a…`) and 11:14:00Z (`3b20c5ec…`, total 1) show the document retained.
- Quota `9e0fd3af-e453-4018-a902-b53f06577c9f`: Free compilations `used:1`, `limit:10`.

**Retention verdict:** cancellation and past-due expiry downgrade access to Free but do **not** delete documents, and do not put the account into a read-only state. This is consistent with a “keep data, reduce allowance” retention model; long-term deletion (e.g. after `historyRetention` days) was not testable within one audit window.

---

## 6. Team seats, invites and owner-vs-member actions

### 6.1 Seat-bound access

After fixture corrections, with the owner's team subscription `active` and member seat `47c6…` active:

| Test | Evidence | Observed |
|---|---|---|
| Member entitlements | 11:08:08.362Z `69f03fdf-7b6d-4075-944f-5eb9627b8ff0` | 200; compilations/optimizations/assists `limit:null` |
| Member subscription display | 11:08:12.479Z `f869dd90-965b-4f15-814b-663bd25bcefa` | `planId:"team_member"`, `planName:"Team"`, `status:"active"`, `subscriptionId:null`, `currentPeriodEnd:null`, unlimited feature copy |
| Member `GET /team/seats` | 11:08:16.471Z `fb0c9794-c5e8-4d15-bac0-15ce0a6d0412` | **403** `"Team plan required"` |
| Member `POST /team/invite` | 11:08:20.598Z `02f11693-a62c-4a8d-8e57-03ff42cc932d` | **403** `"Team plan required"` |
| Member `DELETE /team/seats/{own seat}` | 11:08:24.589Z `bad0c1b5-9d19-42ea-8cf7-2eb6e1247c2e` | **403** `"Team plan required"` |
| Non-team (`trial-expired`) `POST /team/invite` | 11:08:28.703Z `607a4771-39fd-4b1a-95a7-4224f3d7753f` | **403** `"Team plan required"` |
| Owner `GET /team/seats` | 11:08:32.723Z `c4b228e0-95cd-4cab-bcd0-64e7f6334754` | 200; owner + member active |

The “Team plan required” message on an active member is misleading (the member does have a team seat); enforcement is correct. See ST-D04.

### 6.2 Owner-only and seat-limit behavior

| Test | Evidence | Observed |
|---|---|---|
| Owner invites self | 11:08:36.870Z `03cdc5a5…` | 400 `"You already occupy the owner seat"` |
| Owner invites active member | 11:08:41.074Z `0795a835…` | 409 `"That teammate already has an active seat"` |
| Owner invites new address | 11:08:45.522Z `c64737da…` | 201; seat `71f6…`, status `invited`, `invite_preview_url:null`; email delivery unverified |
| Over-limit (6+ seats) | 11:08:53.686Z `7f705017…` | 400 `"Team seat limit reached (5)"` |
| Boundary: exactly 5 seats, resend existing pending | 11:17:29Z `79bfe9fb…` | 201, same seat id, no capacity consumed |
| Boundary: exactly 5 seats, new address | 11:17:41Z `8e16acdf…` | 400 `"Team seat limit reached (5)"` |
| Owner removes member seat | 11:09:05.737Z `8ae44599…` | 204; seat status `removed`; member plan downgraded |
| Member entitlements after removal | 11:09:10.420Z `8eedcf3b…` | Free 10/day, 3/mo, 25/mo |
| Member team endpoints after removal | 11:09:14.434Z `3bb38c5e…` | 403 |
| Restore seat/member plan | DB at 11:09:15Z | Member entitlements `limit:null` (`dc78a4d9…`, 11:09:19Z) |

### 6.3 Owner subscription lapse vs member access

The member inherits team access only while the owner has a paid team subscription. Tested with the seat left active:

| Owner subscription state | Member entitlements | Evidence |
|---|---|---|
| `past_due`, period end +2 days | `limit:null` (team grace) | 11:15:13Z `ad5f1249…` |
| `past_due`, period end 2026-11-25 | Free 10/day | 11:15:18Z `5c3f054d…` |
| `cancelled` | Free 10/day | 11:15:24Z `d5b8b2ff…` |
| `cancel_scheduled`, period end +2 days | `limit:null` | 11:23:34Z `308fa9ec…` |
| `cancel_scheduled`, period end past | Free 10/day | 11:23:37Z `822620cc…` |
| `active` restored | `limit:null` | 11:23:40Z `a7028a06…` |

This matches `docs/BILLING_DODO.md:336-340` (“ends past-due access when the provider grace period expires … including access inherited through a team seat”). While the owner is cancelled, `/subscription/current` for the member still returns `planId:"team_member"`, `status:"active"`, unlimited feature copy (`56beeaa1-f355-4f55-973d-faa7adecc60a`, 11:15:29Z) even though the server enforces Free. This is the team-member case of ST-D02.

### 6.4 Invite acceptance

Team invitation creation works and does not leak the token in production (`invite_preview_url:null`). The accept path (`GET /team/join/{token}`, `POST /team/join/{token}`) is **BLOCKED**: the token is stored only in production Redis and delivered only to an unreadable `.test` mailbox. The audit host’s `REDIS_CACHE_URL` is a local dev endpoint (`redis://redis:6379`), which also held none of the quota counters created by the compiles, proving it is not the production cache. Post-accept state was therefore created by the documented DB fallback (F2/F4) so that seat-bound access, removal downgrade, and owner-only enforcement could still be tested. The source path at the deployed SHA does bind the invitation to the signed-in email and rejects a mismatch with 403 (`backend/app/api/team_routes.py:142-149`), but that branch was not exercised live.

---

## 7. Tenant isolation and tenant roles

Tenant A (`577149dd-ff83-4409-9d66-a14d61cb8a60`, slug `audit-team-20261127103328`, owner = team-owner, member = team-member). Two DB fixtures were used and then deleted:

- Tenant B (`a9ff49e5-fac2-490a-a10b-3e06ab6a5953`, slug `audit-member-tenant-20261127103328`, owner = team-member, member as admin) for “owner A cannot read tenant B”.
- Tenant C (`51bd0e05-c210-4d4e-bfec-805899f21f63`, slug `audit-owner-tenant-20261127103328`, owner = team-owner, no member row) for “member cannot read a tenant they do not belong to”.

### 7.1 Cross-tenant and outsider access

| Caller | Target | Evidence | Result |
|---|---|---|---|
| Owner A | Tenant B `GET /stats` | 11:09:23Z `408820da-49e0-450c-b96b-27cad17ccfa4` | **403** `"Access denied: owner or admin required"` |
| Owner A | Tenant B `GET /members` | 11:09:27Z `cb354864-ba6a-411a-bf58-0eb5586a498d` | **403** `"Access denied"` |
| Owner A | Tenant B `PATCH` | 11:09:31Z `08114790-488e-42f3-8a8d-7d8afdeaab7b` | **403** |
| Member (owner of B) | Tenant B `GET /stats` | 11:09:35Z `da0fb635-6b76-453d-aea5-86b1f5e344d8` | 200 |
| Member (owner of B) | Tenant B `GET /members` | 11:09:39Z `4b26a887-17b7-4024-a059-45c88951adae` | 200, one admin row |
| Member | Tenant C `GET /stats` (non-member) | 11:38:07Z `f4468dfb-ddbc-4685-b185-bd7de7536313` | **403** `"Access denied: owner or admin required"` |
| Member | Tenant C `GET /members` (non-member) | 11:38:12Z `68614b40-8e4f-43c2-bc04-995764d46be4` | **403** `"Access denied"` |
| Member | `GET /tenants/my` | 11:09:43Z `e33a33e7-c2fe-4f11-a726-fbcd457e385e` | 200, A + B; after B cleanup A only (`04b42528…`, 11:11:34Z); C never listed (`f80f4621…`, 11:38:16Z) |
| Member | `GET /tenants/my` after concurrent security tenant appeared | 11:40:23Z `74fff2b8-e693-49cc-b12f-8fa51be585ca` | 200, A only; the owner’s `audit-sec-b-103328` is not visible to the member |
| Owner C | Tenant C `GET /stats` | 11:38:22Z `b76056e2-d06c-4a21-9dd1-963ed94b76c6` | 200; owner can read own fixture |
| Member | Tenant A `GET /members` | 11:09:47Z `6f92be0f-fab9-43a5-bb09-2abefe5834a3` | 200 (membership read allowed) |
| Member | Tenant A `GET /stats` | 11:09:51Z `8f1d79c1-5f19-4f84-add1-25a1bdc2cf73` | **403** |
| Student (outsider) | Tenant A `GET /stats` | 11:10:20Z `b5742920-0a56-4ae7-a3c4-b74f40ebb626` | **403** |
| Student (outsider) | Random tenant `GET /stats` | 11:10:24Z `746c1203-e868-43b2-9e1a-aaeec0adaf8c` | **404** `"Tenant not found"` |
| Student (outsider) | Tenant B `GET /stats` | 11:10:28Z `ba12a5ef-4d0d-4df7-92b3-58b8b7c35992` | **403** |

The 403-vs-404 difference for a non-member is ST-D05 (tenant-existence oracle). Tenant IDs are UUIDv4, so practical exploitability is low.

### 7.2 Owner vs member actions in tenant A

All of the following were denied to the `member` role with 403:

- `GET /tenants/{A}/stats` (`8f1d79c1…`).
- `PATCH /tenants/{A}` `{"name":"Hijacked A"}` (`c16506b3-c69d-4ee3-8347-9c24e1c68308`).
- `POST /tenants/{A}/members/invite` (`085ffb07-cea7-4fad-865b-f07da33d4960`).
- `DELETE /tenants/{A}/members/{owner}` (`715b4622-b60b-4c1e-bd35-46b3916a6baa`).
- `GET /tenants/{A}/billing` (`7ed6dc5a-30c9-4cdc-9dbb-7b951294b95d`).
- `POST /tenants/{A}/billing/upgrade-intent` (`f47c9c59-edba-48d2-b236-616472ee35c9`).
- `POST /tenants` (create a tenant as `team_member`) → 403 `"Team plan or platform administrator access required"` (`1a8dfe57-ca59-43cd-8492-a620b1bdcead`).

Owner A could read the same surfaces: `GET /tenants/{A}/stats` 200 (`adf4cf92-e387-469e-bdcf-197c8098b197`, member_count 2, seats 2/5) and `GET /tenants/{A}/billing` 200 (`1850b822-4672-4819-81c7-28ed2b7c9f2a`). The billing snapshot honestly reports `subscription.available:false` (`tenant_subscription_link_missing`) and `team_seats` mapping `owner_scoped_not_tenant_scoped`; seats are derived from tenant members + invitations (active 2, invited 1 [the residual audit invite], used 3/5). See ST-D07 for the attribution gap.

### 7.3 Tenant invitation and removal

| Test | Evidence | Result |
|---|---|---|
| Owner invites existing member | 11:10:32Z `e52531a7-8fe1-4bd9-9b55-731554fc03ae` | 409 `"User is already a member"` |
| Owner invites new address | 11:10:36Z `8a8a1204-154b-4adc-9fd5-a3f1f93dbc69` | 201; `invite_preview_url:null`; 7-day token |
| Invalid tenant token accept | 11:10:40Z `36df6d32-9aa3-40cf-84d6-1d07706b1902` | 404 `"Invitation not found or expired"` |
| Owner removes member | 11:10:44Z `3f7c461b-b544-4b24-8224-f6d2e16e4219` | 204 |
| Removed member reads roster | 11:10:48Z `ea3c6c82-1191-4a81-9d76-ef16375f8e4d` | 403 |
| Removed member reads stats | 11:10:52Z `de43f84c-6800-4f88-af7d-9d62b78d019b` | 403 |
| Membership restored (DB, accepted-invite outcome) | 11:10:52Z | Member roster 200 (`6f0b14ef…`), PATCH still 403 (`b4e09075…`) |

Valid tenant invitation acceptance is **BLOCKED** for the same Redis/mailbox reason as team invites. The email-binding check (`user.email != invited_email` → 403) at `backend/app/api/tenant_routes.py:952-957` was not executed live; the state after acceptance was emulated with the DB insert above.

### 7.4 Cross-user documents

| Test | Evidence | Result |
|---|---|---|
| Owner creates personal resume `1daeaf48-6372-4114-be51-921b2003b05c` | 11:11:05Z `fbf87c2c…` | 201 |
| Member reads owner's resume | 11:11:09Z `30ccaecb-38bf-40fc-a389-425e10cd8828` | **404** (anti-enumeration) |
| Student reads owner's resume | 11:11:13Z `527ed282-c0b4-456a-8896-4b34f4b10003` | **404** |
| Owner reads own resume | 11:11:17Z `999a1d35-ef04-4491-89cc-aaf5232b850b` | 200 |
| Member creates own resume `908d91d8-ffdd-4166-bc99-af63f968caba` | 11:11:22Z `a975d311…` | 201 |
| Owner reads member's personal resume | 11:11:26Z `aba5e4ef-c25b-4464-bf56-6b8312305df2` | **404** |
| Member updates own resume (PUT) | 11:13:39Z `2c706b43-2b58-42f3-bc72-e3cc841ee142` | 200; title changed |
| Member resume list | 11:13:44Z `26094281-17f4-4371-b64c-6c6486fe8949` | total 1 (own only) |
| Owner resume list | 11:13:50Z `56cc67a4-267d-46a8-bbc6-bc83e6bfdd5c` | total 1 (own only) |

A first attempt used `PATCH /resumes/{id}` and received 405; the backend uses `PUT`. That 405 was a harness method error, not a product defect, and is excluded.

---

## 8. Conversion prompts and read-only fallback

**Live UI render: BLOCKED.** The audit identities have no password (direct DB provisioning), no readable `.test`/`.edu` mailbox, and Better Auth session cookies are signed server-side, so a browser could not be authenticated as these identities. The following is source-verified at the deployed commit `ee1a405d…`, not a rendered screenshot.

| Lifecycle state | `/subscription/current` | UI source behavior | Gap |
|---|---|---|---|
| `trialing` | `planId:pro`, status `trialing`, period end 2026-12-04, unlimited features, no trial-specific field | `SubscriptionManager.tsx:269-288` shows a `trialing` badge and “Renews on 2026-12-04” plus a generic “Change Plan” button | Presented as a paid renewal, not a trial ending; no countdown, no “trial ends” CTA |
| `expired` (Free plan) | `planId:free`, status `expired`, no period end | `SubscriptionManager.tsx:246-266` falls into the Free branch: “You’re currently on the Free plan.” + “Browse Plans” | No “your trial ended” message or trial-specific retention offer |
| `past_due` | `planId:basic`, status `past_due`, unpaid period end, Basic 400/mo copy; `POST /subscription/create` refuses with “Manage or cancel …” (`220e4ded…`) | Warning-colored status badge; “Renews on”/date; generic “Change Plan” | No “update payment method” / retry-payment path; the only CTA dead-ends; card still advertises 400/mo while enforcement is 10/day |
| `cancelled` | `planId:basic`, status `cancelled`, past period end, Basic 400/mo copy | Same warning card + “Change Plan” | No “reactivate”/retention prompt; same quota-copy mismatch |
| `team_member` | `planId:team_member`, `subscriptionId:null`, no period end, Team unlimited copy | `SubscriptionManager` displays a paid card with “No renewal date”; team-seat panel in `billing/page.tsx:1030` only renders when `planId === 'team'` | Member sees no renewal/subscription info and no team-seat panel; `team_member` is not a catalog SKU |

**Read-only fallback:** none observed for trial-expired, past-due, or cancelled. All three retain Free-tier create/edit/compile rights, and existing documents remain listed; export/delete were not exercised. If the intended retention behavior is read-only, it is not implemented; if Free-tier fallback is intended, the legal copy should describe it (current Terms only distinguish guest trial and Free account).

---

## 9. Latency observations (not a performance verdict)

Serialized single-region samples; reported only to hand off to the performance auditor.

| Class | n | Observed |
|---|---|---|
| `/health` | 1 | 1,596 ms |
| `/config/entitlements` | 33 | 1,351–3,558 ms (median 1,415 ms; one 3,558 ms linked-provider read and one 2,628 ms read during DB changes) |
| `/subscription/current` | 16 | 794–1,769 ms (median 828 ms) |
| `/subscription/plans` | 4 | 780–1,913 ms |
| Resume create/read/update | 22 | 679–2,545 ms (median 1,062 ms) |
| Team routes (all) | 18 | 683–8,276 ms (median 771 ms) |
| Team invite (subset of the above) | 7 | 812–903 ms for denied/validation; 1,146–3,445 ms for a successful send; one 8,276 ms over-limit rejection (cold outlier) |
| Tenant routes (all) | 28 | 698–2,074 ms (median 727 ms) |
| Compile submit | 5 | 2,686–4,804 ms (median 2,716 ms) |
| Compile state poll | 30 | 1,239–2,135 ms (median 1,311 ms) |
| Compile terminal (submit → completed poll) | 5 | ≈27.8–29.1 s for a 1-page document |
| PDF download | 5 | 2,302–2,552 ms warm; one 17,764 ms cold outlier (student) |

The 5 compiles were all `completed`, each PDF `%PDF-` 8,919 B. The ≈28 s end-to-end time is much slower than the 5–10 s baseline cited in the audit brief; this is referred to the performance auditor as a possible cold-container / queue-wait issue, not scored here.

---

## 10. Artifacts and cleanup

### 10.1 Resumes (owner-scoped; cascade-deleted when the audit user is removed)

| Cohort | Resume id | Title | Final state |
|---|---|---|---|
| student | `039fa23e-38f6-4bf3-a6f8-977a756b719d` | Audit student 20261127103328 | retained; compiles used 1 |
| trial-active | `98369a76-830f-489a-9d78-f69402eadea5` | Audit trial-active 20261127103328 | retained; compiles used 1 |
| trial-expired | `c6bccefc-97a3-4b16-819b-6ac549304f0a` | Audit trial-expired 20261127103328 | retained; compiles used 1 |
| past-due | `03d02d07-e052-4f7e-b8af-4677ea01cb53` | Audit past-due 20261127103328 | retained; compiles used 1 |
| cancelled | `d7ac5f92-cd82-4873-b14f-f6847c54ded3` | Audit cancelled 20261127103328 | retained; compiles used 1 |
| team-owner | `1daeaf48-6372-4114-be51-921b2003b05c` | Audit owner doc 20261127103328 | retained |
| team-member | `908d91d8-ffdd-4166-bc99-af63f968caba` | Member doc updated | retained |

### 10.2 Compile jobs (completed; PDFs are 8,919 B)

| Cohort | Job id |
|---|---|
| student | `31b9fb0f-f709-4f9d-9e7f-b55969a9817c` |
| trial-active | `e75c7d24-b9fb-4348-8bf8-8499cf510a96` |
| trial-expired | `b0a50800-9fd8-44c8-9258-ac5bd00f99a9` |
| past-due | `2f430c46-d8f6-433f-b5ce-82f115075204` |
| cancelled | `5a569e45-1ba9-47c7-aa37-c0d336f80aa5` |

### 10.3 Quota counters consumed (production Redis; analytics exclusion)

- `student`: 1 compile (unlimited plan; `used:1`).
- `trial-active`: 1 compile (unlimited plan; `used:1`).
- `trial-expired`: 1 compile (Free daily; `used:1`, limit 10).
- `past-due`: 1 compile (Free daily; `used:1`, limit 10).
- `cancelled`: 1 compile (Free daily; `used:1`, limit 10).
- No optimization or AI-assist quota was consumed; no LLM/optimize call was made.

### 10.4 Residual invitations (production Redis, not deletable from the audit host)

| Kind | Recipient | Created | TTL / effect |
|---|---|---|---|
| Student verification | `audit.student.20261127103328@example.edu` | 10:58:09Z | 24 h; bound to student user; not activated. Expires ≈2026-11-28T10:58:09Z |
| Team invite | `audit+team-invited-20261127103328@example.test` | 11:08:45Z | 7 d; seat was removed, so the resolver would return 404 (source path `team_routes.py:139-140`). Expires ≈2026-12-04T11:08:45Z |
| Team invite | `audit+seat-bound-0-20261127103328@example.test` | 11:17:29Z | 7 d; seat was deleted, so the resolver has no row and would return 404. Expires ≈2026-12-04T11:17:29Z |
| Tenant invite | `audit+tenant-invited-20261127103328@example.test` | 11:10:36Z | 7 d; live but addresses an unreadable synthetic mailbox. It is counted as `invited:1` in tenant stats/billing until expiry. Expires ≈2026-12-04T11:10:36Z |

The tenant invite is the only live residual grant. It cannot be accepted without control of the synthetic mailbox; it will auto-expire. The team invite tokens are unusable because their seats are removed/deleted. The student token will be unusable after the student user is deleted.

Email sends triggered by these tests (all to synthetic addresses, delivery unverified): 1 student verification, 2 team invitations (new + resend), 1 tenant invitation. No other email was requested.

### 10.5 Other artifacts

- Cross-tenant fixture tenant B `a9ff49e5-fac2-490a-a10b-3e06ab6a5953` and its membership row: **deleted** at 11:11:34Z.
- Cross-tenant fixture tenant C `51bd0e05-c210-4d4e-bfec-805899f21f63`: **deleted** at 11:38:22Z (no membership rows).
- Concurrent security-auditor tenant `audit-sec-b-103328` (`3f98ed40-fcb0-4766-8dd0-e0f6807aa2b5`, owner = team-owner): **not mine, left in place**; cleanup owner is the security/tenant auditor. The member has no membership row in it.
- Seat fillers and the removed seat row: **deleted**; final seats are owner + member active.
- No team/tenant API key, BYOK key, payment, checkout, subscription or invoice was created.
- No resume was deleted; they cascade with the audit users when `audit/scripts/cleanup_identities.py` runs.

---

## 11. Blocked tests and caveats

1. **Student verification activation — BLOCKED.** The token is created only in production Redis and delivered only to the academic address. The audit host cannot read production Redis (its `REDIS_CACHE_URL` is `redis://redis:6379` and contains none of the quota counters created by these compiles), and no mailbox exists. Invalid-token handling and the suffix gate were tested; valid-token activation and `record_student_verified` were not.
2. **Team invitation acceptance — BLOCKED.** Same Redis/mailbox constraint. Creation, duplicate/self limits, seat capacity, and no-token-leak were tested; `GET/POST /team/join/{token}` and the email-mismatch 403 were not executed. Post-accept state was emulated by DB (F2/F4) to test seat-bound authorization.
3. **Tenant invitation acceptance — BLOCKED.** Same constraint. Creation, duplicate-member rejection, invalid-token 404, removal, and post-accept authorization were tested; the email-bound accept branch was not.
4. **Live UI conversion prompts — BLOCKED.** No password/mailbox for the directly provisioned identities and signed Better Auth cookies prevent browser login. UI claims are source-verified at the deployed SHA, not rendered. This is the same limitation recorded by the auth auditor for email-link tests.
5. **Email delivery** for student/team/tenant invitations could not be confirmed. The APIs returned success/201, so the send call was not treated as a failure; whether the provider accepted it, or `EMAIL_ENABLED` caused a skip, cannot be distinguished from the audit host. Bounce/delivery was not observable, and `.test`/`example.edu` addresses are synthetic.
6. **Capability-level plan gating not observable.** `/config/entitlements` returned all **165** keys in its feature map (149 gateable per CAP-01) as `true` for every cohort, including `trial-expired`, `past-due`, and `cancelled` (all effectively Free). This is consolidated as **CAP-01** in `audit/defects.md` (`audit/inventory/plans-capabilities.md`) and also recorded in `audit/plans/pro-byok-developer.md` §11.2. The route-level plan checks still blocked team/tenant provisioning for non-team plans, but a feature-grant assertion cannot be made from this state.
7. **No real provider-linked trial outside the synthetic row.** The matrix's `trial-active` has a `trialing` subscription row but `users.subscription_id` null. The linked-state failure (ST-D01) was produced by linking that row, which mirrors what the webhook does. Whether Dodo itself emits `trialing` is a provider-contract question; if it does not, ST-D01 is latent rather than live.
8. **Retention over time not tested.** The window is one day; the “30-day history retention” vs “0 days Free” behavior after a downgrade cannot be observed without waiting or editing dates on a real document. Existing documents were retained and writable in the test window. The separate **RET-01** finding records that `historyRetention` is copy-only (no backend consumer), which is consistent with the absence of deletion observed here.
9. **Tenant member roster visibility.** A `member` can read the full tenant roster (emails and roles) by design (`backend/app/api/tenant_routes.py:791-830`). For a 5-seat team this is acceptable; for a university tenant with 200 members it is a peer-email disclosure surface. Not tested at scale; flagged for the privacy/tenant auditor, not scored here.
10. **Tenant billing attribution.** The owner billing snapshot is honest about its limits, but it cannot tie the Team plan or `team_seats` rows to the tenant. See ST-D07.

---

## 12. Related defect records

`audit/defects/student-team-trial.md`:

| ID | Severity | Title |
|---|---|---|
| ST-D01 | P2 (P1 if provider emits `trialing`) | Linked `trialing` subscription resolves to Free entitlements |
| ST-D02 | P2 | `/subscription/current` advertises stored plan quotas after effective downgrade |
| ST-D03 | P2 | Trial/past-due lifecycle lacks dedicated conversion/dunning prompts |
| ST-D04 | P3 | Team member display uses non-catalog `team_member` and misleading owner-only error |
| ST-D05 | P3 | Tenant existence oracle: 403 for existing, 404 for nonexistent |
| ST-D06 | P3 | Student verification email accepts any address with an allowed academic suffix and ignores an existing subscription |
| ST-D07 | P3 | Tenant billing cannot attribute the Team plan or team seats |
| ST-H01 | P3 | Team-member fixture bypassed the invite flow and made the matrix stale |
| ST-H02 | P3 | Production Redis and test mailboxes are unavailable, so token-accept paths are unverifiable |

Shared observations, not duplicated here: all-165-map-keys-true / 149 gateable (**CAP-01** in `audit/defects.md`; `audit/plans/pro-byok-developer.md` §11.2), `historyRetention` copy-only (**RET-01**), and compile/PDF latency (see the performance auditor).
