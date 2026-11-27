# Defects — Student / Team / Trial / Past-due / Cancelled

- **Audit window:** 2026-11-27T10:56:54Z – 2026-11-27T11:40:23Z
- **Environment:** production (`https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`, backend `ee1a405d…`)
- **Identities:** `audit+student…`, `audit+team-owner…`, `audit+team-member…`, `audit+trial-active…`, `audit+trial-expired…`, `audit+past-due…`, `audit+cancelled…` (suffix `20261127103328`)
- **Cohort report:** `audit/plans/student-team-trial.md`
- **Raw evidence:** `C:\Users\Sansk\AppData\Local\Temp\opencode\sst-evidence-{a,b,c,d,e,f,g,h}-*.jsonl`
- **Status:** all defect records are open; no fixes were attempted. No global configuration was changed.

| ID | Sev | Title | Cohort |
|---|---|---|---|
| ST-D01 | **P2** (P1 if provider emits `trialing`) | Linked `trialing` subscription resolves to Free entitlements | trial-active |
| ST-D02 | **P2** | `/subscription/current` advertises stored plan quotas after an effective downgrade | trial-active, past-due, cancelled, team-member |
| ST-D03 | **P2** | Trial/past-due lifecycle lacks dedicated conversion and dunning prompts | trial-active, trial-expired, past-due, cancelled |
| ST-D04 | P3 | Team member display uses non-catalog `team_member`; owner-only errors misstate the reason | team-member |
| ST-D05 | P3 | Tenant existence oracle: 403 for an existing tenant, 404 for a nonexistent one | outsider |
| ST-D06 | P3 | Student verification accepts any address with an allowed academic suffix and ignores an existing subscription | student |
| ST-D07 | P3 | Tenant billing cannot attribute the Team plan or team seats | team-owner |
| ST-H01 | P3 | Team-member fixture bypassed the invite flow and made the matrix stale | audit tooling |
| ST-H02 | P3 | Production Redis and test mailboxes are unavailable, so token-accept paths are unverifiable | audit tooling / coverage |

---

## ST-D01 — P2 — Linked `trialing` subscription resolves to Free entitlements

**Severity:** P2 in the observed state; **P1** if Dodo emits `subscription.updated` with `status:"trialing"` in production, because a paid trial would lose Pro access and hit a 10/day cap while the UI advertises unlimited.

**Surface:** entitlement resolution for a user whose `users.subscription_id` points at a local Dodo subscription row with `subscriptions.status='trialing'`. Affects `/config/entitlements`, every quota-consuming route, and any feature decision derived from the effective plan.

**Cohort / user:** `trial-active` `3b8ddb07-2b18-486c-9c18-d32ce3fbbb47`; subscription `9c641be4-3702-4f2a-83f7-e9537036b903` (`plan_id:pro`, `status:trialing`, period end 2026-12-04).

**Repro (observed):**

1. Confirm the baseline with `users.subscription_id = NULL`: `GET /config/entitlements` → compilations/optimizations/assists `limit:null` (`3c5bd208-14a1-4f37-bc08-0896d397dd5a`, 10:57:25Z).
2. `UPDATE users SET subscription_id='9c641be4-3702-4f2a-83f7-e9537036b903'::uuid WHERE id='3b8ddb07-2b18-486c-9c18-d32ce3fbbb47'::uuid`.
3. `GET /config/entitlements` → **Free** `limit:10/day`, `3/month`, `25/month` (`133f72b3-2c71-43b0-a928-abf26ff43375`, 10:59:34Z).
4. `GET /subscription/current` → **Pro**, `status:"trialing"`, `compilations:"unlimited"`, period end 2026-12-04 (`5e5b563a-a64e-491e-9544-87a999309df4`, 10:59:38Z).
5. Control: change only the provider status to `active` while keeping the link → `limit:null` again (`df1a3523-783d-4f51-bfed-03550b7e8c12`, 11:22:53Z). Change it back to `trialing` → Free again on the next linked read. Restore `subscription_id=NULL` → unlimited (`2951c254-92de-4794-aac4-1fdae9d046a0`).

**Expected:** a subscription in a paid trial state grants the target plan's entitlements while `current_period_end > now`, exactly as `active` does. A trial must not be treated as a suspended/terminal state.

**Actual:** `_effective_plan_for_billing_status` only returns the stored plan for provider status `active`, or `past_due`/`cancel_scheduled` with a future period end. Any other status — including `trialing` — falls through to `"free"`:

- `backend/app/services/entitlement_service.py:562-575`
  - `provider_status in suspended_statuses` → free.
  - `provider_status in {"past_due","cancel_scheduled"}` → plan if period end future else free.
  - `if provider_status != "active": return "free"`.
- The webhook path can persist `trialing`: `backend/app/services/payment_service.py:1881-1894` stores an unrecognised non-terminal status on `intent.status` and copies it to `user.subscription_status`; `:1651` links `user.subscription_id` on activation. No status map rejects `trialing`.
- The display path ignores the effective plan entirely: `backend/app/services/payment_service.py:641-662` uses `user.subscription_plan` / `get_plan_config(plan_id)`.

**Evidence:**

| Time (UTC) | State | Compilations limit | `/subscription/current` | Request id |
|---|---|---|---|---|
| 10:57:25 | unlinked | `null` | Pro / trialing / unlimited | `3c5bd208-14a1-4f37-bc08-0896d397dd5a` |
| 10:59:34 | linked, `trialing` | **10/day** | Pro / trialing / unlimited | `133f72b3-2c71-43b0-a928-abf26ff43375` |
| 10:59:38 | linked, `trialing` | — | Pro / trialing / unlimited | `5e5b563a-a64e-491e-9544-87a999309df4` |
| 11:22:53 | linked, `active` | `null` | — | `df1a3523-783d-4f51-bfed-03550b7e8c12` |
| 10:59:43 | unlinked (restored) | `null` | Pro / trialing / unlimited | `2951c254-92de-4794-aac4-1fdae9d046a0` |

Raw: `sst-evidence-a-1795777010.jsonl` (10:59Z rows), `sst-evidence-f-1795778565.jsonl` (11:22Z control).

**Impact:**

- A provider-linked trial is silently capped at Free quotas while every UI surface fed by `/subscription/current` says Pro unlimited. The quota engine will reject the 11th daily compile (the exceeded-limit path returns 402); exhaustion itself was not run to avoid spending more compile units.
- Any trial that uses a Dodo status string other than `active` — including `trialing` — is affected. The audit cohort is defined as `trialing`, and the admin status vocabulary includes it (`admin_user_service.py:1246`), so this is a supported state in the product, not a fabrication.
- The control shows the bug is not “all provider-linked plans are free”; it is the status mapping. An `active` row works.

**Proposed fix:**

1. In `_effective_plan_for_billing_status`, treat `trialing` as paid while `current_period_end > now` (same branch as `past_due` for grace), and reject only the explicit suspended statuses. Do not let an unknown provider status silently fall to Free without a metric/log.
2. Add a contract test matrix for every provider status (`active`, `trialing`, `past_due`, `cancel_scheduled`, `on_hold`, `paused`, `cancelled`, `expired`, `failed`, `refunded`) with future/past period ends, asserting both the effective plan and the quota limit.
3. Align `/subscription/current` with the effective plan (see ST-D02) so the UI cannot claim a plan the meter will not honour.
4. If Dodo never emits `trialing`, remove it from the supported admin/status vocabulary or map it to `active` at webhook ingestion; do not leave a state that the entitlement resolver treats as Free.

**Owner:** Billing / entitlement backend. **Status:** open.

---

## ST-D02 — P2 — `/subscription/current` advertises stored plan quotas after an effective downgrade

**Surface:** `GET /subscription/current` and every UI that renders its `features` (billing plan card, usage copy, upgrade prompts).

**Cohorts / users:** `past-due` `a24f1fd9-34f9-4a84-8ba8-74d8fa431ca1`; `cancelled` `dfd20a28-a4d5-40db-aa77-597ce6f3e589`; `team-member` `7a3d3b80-000c-49f0-a067-96c177b7c848` when the owner lapses; `trial-active` in the linked-`trialing` case above.

**Repro:**

1. For `past-due`, link the provider row and let the grace period expire (or use the baseline with a past period end).
2. `GET /config/entitlements` → Free 10/day.
3. `GET /subscription/current` → `planId:"basic"`, `status:"past_due"`, `features.compilations:"400 / month"`, `currentPeriodEnd` in the past.
4. Repeat for `cancelled` (terminal) and for `team-member` while the owner subscription is `cancelled`.
5. Compare the two responses for the same request-time state.

**Expected:** the subscription contract either returns the effective plan/quotas, or exposes both the billed plan and an explicit effective/access state. A client must not be told it has 400 compiles/month when the server enforces 10/day.

**Actual:** `payment_service.get_user_subscription` uses `user.subscription_plan` and `get_plan_config(plan_id)` for `planId`, `planName` and `features` (`backend/app/services/payment_service.py:641-662`). It does not apply `_effective_plan_for_billing_status`. `/config/entitlements` does apply it (`backend/app/services/entitlement_service.py:994-1055`), so the two authoritative-looking endpoints disagree.

**Evidence:**

| Cohort | `/subscription/current` | Effective `/config/entitlements` | Request ids |
|---|---|---|---|
| past-due (grace expired) | Basic, `past_due`, 400/mo, period end 2026-11-25 | Free 10/day, 3/mo, 25/mo | `63f423c9-af06-4629-a715-b0ff856a0cb6`; `1b389c1a-d0de-459f-929b-7cd516ad7877` |
| cancelled (terminal) | Basic, `cancelled`, 400/mo, period end 2026-11-17 | Free 10/day | `4ec7d438-7346-4b8c-ad09-180bfcaa2a3a`; `f9941cc8-857b-4e22-8af7-51f5bad37d59` |
| team-member (owner cancelled) | Team, `team_member`, unlimited, no period end | Free 10/day | `56beeaa1-f355-4f55-973d-faa7adecc60a`; `d5b8b2ff-76aa-4101-9f5b-2f7cb07d5756` |
| trial-active (linked `trialing`) | Pro, `trialing`, unlimited | Free 10/day | `5e5b563a-a64e-491e-9544-87a999309df4`; `133f72b3-2c71-43b0-a928-abf26ff43375` |

The frontend consumes the stored copy directly: `SubscriptionManager.tsx:296-301` renders `subscription.features.compilations`, `optimizations`, and `historyRetention`; `:285-287` renders “Renews on” from `currentPeriodEnd`; `billing/page.tsx:413-418` derives the current plan from `currentSubscription.planId`.

**Impact:**

- A past-due or cancelled user sees “400 compilations / month” while the meter enforces 10/day. The exceeded-limit path would report `limit:10` (402); exhaustion was not run, but `/config/entitlements` already shows the 10/day limit that contradicts the plan card.
- A team member whose owner has lapsed sees “Team unlimited” with no renewal date while every feature is actually Free.
- This is a billing-integrity/trust defect, not just copy: the client cannot distinguish “paid but suspended” from “still entitled” using the endpoint named for the current subscription.
- Support and upgrade prompts are driven by the same object, so retention offers target a state the account is not in.

**Proposed fix:**

1. Make `/subscription/current` return the effective plan and quota policy, or add explicit fields: `billedPlanId`, `effectivePlanId`, `accessState` (`active|grace|free_fallback|suspended|trial`), `effectiveLimits`, `graceEndsAt`.
2. Update `SubscriptionManager` and `billing/page.tsx` to render the effective limits and a truthful status (“Past due — access ends 25 Nov”, “Trial ends 4 Dec”, “Team access paused — owner subscription lapsed”).
3. Add a contract test that asserts `/subscription/current` and `/config/entitlements` agree on the effective quota for every lifecycle state (active, trialing, past_due in grace, past_due expired, cancel_scheduled before/after, cancelled, team member with owner active/lapsed).
4. Do not remove the billed-plan fields; audit/receipts still need them. Label them explicitly.

**Owner:** Billing API + frontend billing. **Status:** open.

---

## ST-D03 — P2 — Trial and past-due lifecycle lacks dedicated conversion/dunning prompts

**Surface:** `/billing` subscription card and plan catalog; `/subscription/current` response shape; trial and dunning conversion.

**Cohorts:** `trial-active`, `trial-expired`, `past-due`, `cancelled`.

**Repro / observed:**

- Active trial: `GET /subscription/current` returns `planId:"pro"`, `status:"trialing"`, `currentPeriodEnd:2026-12-04`, unlimited features, and **no** trial-specific field (`trialEndsAt`, `isTrial`, `trialUsed`, `daysRemaining`). The user cannot tell from the contract that 2026-12-04 is a trial end rather than a renewal.
- Expired trial: `GET /subscription/current` returns `planId:"free"`, `status:"expired"`, no period end, Free features. There is no “trial ended” marker.
- Past-due: `status:"past_due"` with a past period end and Basic feature copy; billing is available and every plan is purchasable (`47e984fc-dfe2-4d7b-b665-0f9a1e10a097`), but there is no dedicated payment-update CTA or dunning message in the subscription contract.
- Past-due recovery attempt: `POST /subscription/create` `{planId:"pro"}` at 11:31:18Z (`220e4ded-7384-41f6-8396-f41c18f2189c`) returned 200 `success:false`, `error:"Manage or cancel your current paid subscription before starting another."` No checkout and no charge. The generic “Change Plan” button therefore dead-ends for a past-due user; there is no self-serve update-payment or retry-payment path.
- Cancelled: same, with `status:"cancelled"` and Basic copy.
- UI source: `SubscriptionManager.tsx:269-288` shows the raw status badge and “Renews on …” for any non-`cancel_scheduled` state; `:246-266` treats a Free plan as a generic free account with “Browse Plans”. `billing/page.tsx` has no trial countdown or dunning/payment-update component.

**Expected:** the billing surface distinguishes a trial from a paid renewal, tells the user when a trial ends, and gives a state-specific next action: “Trial ends in N days — choose a plan”, “Your trial ended — pick a plan”, “Payment failed — update payment method”. The audit brief explicitly asks for trial gating, conversion prompts, and past-due/cancelled retention behavior.

**Actual:** only the internal status string and a generic “Change Plan” button. An active trial is rendered as a paid renewal (wrong date semantics); an expired trial is indistinguishable from a long-term Free account; a past-due account has no payment-recovery CTA beyond re-entering the plan catalog, and that path is refused by `POST /subscription/create` while the past-due subscription is live. The UI was not live-rendered (see ST-H02), so this is source-verified at the deployed SHA and supported by the API response shape.

**Evidence:**

| State | API evidence | UI source | Gap |
|---|---|---|---|
| trialing | `276bc859-5e6c-4d6d-b713-be746ec600ca` (10:57:30Z) | `SubscriptionManager.tsx:269-288` | “Renews on” = trial end; no countdown |
| expired | `51ce67ba-ac92-4cf1-afa2-01b9d4061660` (11:00:40Z) | `SubscriptionManager.tsx:246-266` | generic Free card; no trial-ended message |
| past_due | `63f423c9-af06-4629-a715-b0ff856a0cb6` (11:01:47Z) | `SubscriptionManager.tsx:269-288` | no update-payment/dunning CTA |
| past_due change plan | `POST /subscription/create` `220e4ded-7384-41f6-8396-f41c18f2189c` (11:31:18Z) → 200 `success:false` “Manage or cancel…” | `billing/page.tsx` “Change Plan” | CTA dead-ends; no retry-payment path |
| cancelled | `4ec7d438-7346-4b8c-ad09-180bfcaa2a3a` (11:03:02Z) | same | no reactivation/retention prompt |
| catalog | past-due `47e984fc…`, cancelled `7688e69f…` | `billing/page.tsx` | all plans purchasable, so the conversion path exists but is generic |

**Impact:**

- Trial users may believe the trial auto-renews or that they are already paying, instead of knowing access ends. That is a conversion and trust problem at the exact moment the audit brief asks to measure.
- An expired trial looks like a normal Free account, so the user gets no explanation for lost Pro features and no targeted offer.
- Past-due users are not told how to recover; the only path is to browse plans. `PAID_SUBSCRIPTION_STATUSES` includes `past_due` (`backend/app/services/payment_service.py:52`), so `create_subscription` returns “Manage or cancel …” at `:445-450` instead of opening a checkout. The user is stuck between “Change Plan” and “cancel your current plan”.

**Proposed fix:**

1. Add trial fields to `UserSubscriptionResponse`: `isTrial`, `trialEndsAt`, `trialDaysRemaining`, `trialUsed`. Populate from the subscription row/user state.
2. Render a trial banner/countdown with a state-specific CTA; render a trial-ended state with the previous plan name and a “Choose a plan” action.
3. Add a past-due banner with “Update payment method” (provider-hosted update URL or support contact) and a grace-end date; do not only offer “Change Plan”.
4. Add a cancelled state with “Reactivate/reactivate by choosing a plan” and a retention offer if product approves one.
5. Add frontend tests for each state and a backend contract test that the required lifecycle fields are present.

**Owner:** Product/billing frontend; billing API for the fields. **Status:** open. **UI render:** BLOCKED (ST-H02).

---

## ST-D04 — P3 — Team member display uses non-catalog `team_member`; owner-only errors misstate the reason

**Surface:** `GET /subscription/current` for a seat-bound member; `GET /team/seats`, `POST /team/invite`, `DELETE /team/seats/{id}` error copy; `/billing` team panel gating.

**Cohort / user:** `team-member` `7a3d3b80-000c-49f0-a067-96c177b7c848`.

**Observed:**

- `/subscription/current` → `planId:"team_member"`, `planName:"Team"`, `status:"active"`, `subscriptionId:null`, `currentPeriodEnd:null`, unlimited Team feature copy (`f869dd90-965b-4f15-814b-663bd25bcefa`, 11:08:12Z).
- `GET /subscription/plans` has no `team_member` SKU (only `team`); a client that looks up the current plan id in the catalog fails.
- The frontend’s team-seat panel is gated on `currentSubscription?.planId === 'team'` (`frontend/src/app/billing/page.tsx:481,1030`), so a real member never sees the team context; `SubscriptionManager` renders “No renewal date” because `currentPeriodEnd` is null.
- Owner-only team routes return **403 “Team plan required”** to an active member (`fb0c9794…`, `02f11693…`, `bad0c1b5…`), even though the member does have a team seat. The check is `subscription_plan != "team"` (`backend/app/api/team_routes.py:153-168`), which is an owner check, not a plan check.

**Expected:** the member’s display plan should be a recognized Team/member representation (or a member-specific view), with the seat owner and renewal/period shown honestly. An owner-only denial should say “Only the team owner can manage seats”, not “Team plan required”.

**Actual:** non-catalog internal plan id, null billing fields, hidden team panel, and misleading error copy. Enforcement itself is correct: every owner-only action returned 403 and member entitlements correctly resolved through the seat.

**Evidence:** `sst-evidence-b-1795777681.jsonl` rows at 11:08:12Z–11:08:24Z; `sst-evidence-c-1795778017.jsonl` final member subscription. Source: `team_routes.py:153-168`, `billing/page.tsx:481,1030`, `SubscriptionManager.tsx:284-288`.

**Impact:** a paying team member cannot see their team/seats context or a renewal date, and support receives a misleading “Team plan required” message for a user who is on a team. Low severity (no access error, no data exposure) but directly in the team cohort’s core UX.

**Proposed fix:**

1. Return `planId:"team"` for `team_member` (or add `planId:"team_member"` to the catalog and client types) plus `seatBound:true`, `seatOwnerId`/`seatOwnerEmail`, and the owner’s period end if the member is allowed to see it.
2. Gate the team panel on `planId === 'team' || seatBound === true`.
3. Change `_require_team_owner`’s 403 to “Only the team owner can manage seats” (and keep “Team plan required” for a caller with no team family/seat).
4. Add tests for member display and member/owner error copy.

**Owner:** Team billing + frontend. **Status:** open.

---

## ST-D05 — P3 — Tenant existence oracle: 403 for an existing tenant, 404 for a nonexistent one

**Surface:** tenant-scoped reads for a caller who is neither owner nor member: `GET /tenants/{id}/stats`, `GET /tenants/{id}/members`, and the shared `_require_tenant_owner_or_admin` helper.

**Cohorts / users:** `student` outsider `d91e5bf0-bbc9-4558-9e10-151e728cdeec`.

**Repro (observed):**

1. `GET /tenants/577149dd-ff83-4409-9d66-a14d61cb8a60/stats` as `student` (existing tenant, no membership) → **403** `"Access denied: owner or admin required"` (`b5742920-0a56-4ae7-a3c4-b74f40ebb626`, 11:10:20Z).
2. `GET /tenants/bfe29bf9-c197-4c4b-815e-5a69894b4694/stats` as `student` (random UUID) → **404** `"Tenant not found"` (`746c1203-e868-43b2-9e1a-aaeec0adaf8c`, 11:10:24Z).
3. `GET /tenants/a9ff49e5-fac2-490a-a10b-3e06ab6a5953/stats` as `student` (second existing tenant) → **403** (`ba12a5ef-4d0d-4df7-92b3-58b8b7c35992`, 11:10:28Z).
4. `GET /tenants/51bd0e05-c210-4d4e-bfec-805899f21f63/stats` as `team-member` (existing tenant, no membership; separate fixture C) → **403** (`f4468dfb-ddbc-4685-b185-bd7de7536313`, 11:38:07Z); `/members` → **403** (`68614b40-8e4f-43c2-bc04-995764d46be4`, 11:38:12Z).

**Expected:** a non-member should not be able to distinguish “tenant exists but you cannot see it” from “tenant does not exist”. Return 404 for both, or the same 403 after a uniform authorization path.

**Actual:** `_require_tenant_owner_or_admin` loads the tenant first and returns 404 only when absent, then 403 when present but unauthorized (`backend/app/api/tenant_routes.py:415-434`). `list_members` repeats the pattern (`:791-812`). The status code is an existence oracle.

**Impact:** an authenticated user can confirm whether a guessed tenant UUID exists. Tenant IDs are UUIDv4 (122 random bits), so practical enumeration is negligible; the impact is information disclosure plus inconsistent API semantics. Included for completeness because the audit brief asks for tenant isolation, not because it is exploitable.

**Proposed fix:** for any caller that fails membership/ownership, return 404 with the same body as a missing tenant (anti-enumeration), or always 403 after a membership lookup that does not disclose existence. Apply it centrally in `_require_tenant_owner_or_admin`, `list_members`, and any tenant-scoped route that resolves the row before authorization. Add a negative test with existing + random IDs.

**Owner:** Tenant backend. **Status:** open.

---

## ST-D06 — P3 — Student verification accepts any address with an allowed academic suffix and ignores an existing subscription

**Surface:** `POST /subscription/create` with `planId:"student"`; `payment_service._request_student_verification`; `GET /subscription/student/verify/{token}`.

**Cohort / user:** `student` `d91e5bf0-bbc9-4558-9e10-151e728cdeec` (already active on the Student plan).

**Repro (observed):**

1. With an active Student subscription (`subscriptionId:audit_sub_…student`, period end 2026-12-27), call `POST /subscription/create` with `studentEmail:"audit.student.20261127103328@example.edu"`.
2. Observe HTTP 200, `success:true`, `verificationRequired:true`, `verificationPreviewUrl:null`, `message:"Verification email sent to your student address."` (`df390379-c4c9-4426-b418-0d9030f4293f`, 10:58:09Z).
3. Control with a non-academic address: HTTP 200, `success:false`, `"Student plan requires a verified academic email address"` (`31cc3b1c…`, 10:58:04Z).
4. No check of an existing paid subscription occurs on this branch: `create_subscription` handles `student` at `payment_service.py:432-437` **before** `_get_live_subscription` at `:445`. Only an invalid suffix or a missing `studentEmail` is rejected.
5. The token is bound to the purchaser's `user_id` and `customer_email` (`payment_service.py:141-157`); the recipient of the academic address is not proven to own the account. Anyone who can call the authenticated endpoint can make Latexy send a verification email to any `.edu`/`.ac.in`/`.edu.in` address.

**Expected:** verification should prove the signed-in user controls the academic address; a user who already has an active paid plan should not enter the verification flow; repeated requests should be rate-limited per account and per recipient.

**Actual:** suffix-only validation plus an email dispatch. No ownership proof beyond clicking the link; no existing-subscription short-circuit; no visible rate limit on this endpoint (not stress-tested, so “none observed” rather than “none exists”). The token is bound to the purchaser, so a recipient who clicks it would activate a plan on the purchaser's account, not their own.

**Impact:** authenticated email-abuse/spam vector against academic addresses, duplicate verification mail to an existing subscriber, and a confusing flow where the recipient may not be the beneficiary. No account takeover or charge was observed.

**Proposed fix:**

1. Require the student email to be added and verified on the account (or send a confirmation to the account email as well) before accepting it as an eligibility signal.
2. Short-circuit if the account already has an active/trialing paid subscription (`get_live_subscription` before the student branch) and return “You already have a paid plan.”
3. Add a per-account + per-recipient rate limit and a resend cooldown; reuse the existing auth/email limiter instead of a new one.
4. Bind the verification token to both the purchaser and the academic address and show the account identity on the verification page.
5. Add tests for existing-subscriber, repeated request, non-academic, and mismatched-owner cases.

**Owner:** Billing/student verification + abuse prevention. **Status:** open.

---

## ST-D07 — P3 — Tenant billing cannot attribute the Team plan or team seats

**Surface:** `GET /tenants/{tenant_id}/billing` for the team-owner tenant.

**Cohort / user:** `team-owner` `6bb81a84-860b-46a5-8ab4-f1c483068479`, tenant `577149dd-ff83-4409-9d66-a14d61cb8a60`.

**Observed (11:14:21Z, `1850b822-4672-4819-81c7-28ed2b7c9f2a`):**

```json
{
  "plan": {"plan_id": "agency", "max_seats": 5, "tenant_status": "active"},
  "seats": {"active": 2, "invited": 1, "used": 3, "max": 5, "basis": "active_and_invited"},
  "subscription": {
    "available": false,
    "status": null,
    "reason": "tenant_subscription_link_missing",
    "detail": "Subscriptions are user-scoped and the tenants table has no subscription identifier, so renewal and paid status cannot be attributed safely."
  },
  "mapping": {
    "team_seats": {
      "status": "unavailable",
      "reason": "owner_scoped_not_tenant_scoped",
      "detail": "Team seats are keyed by the team owner and carry no tenant identifier, so they cannot be attributed to this tenant without guessing."
    }
  }
}
```

The `invited:1` is the residual audit tenant invitation (see `audit/plans/student-team-trial.md` §10.4), not a team seat. The owner’s actual Team subscription is active (`/subscription/current`, `currentPeriodEnd:2026-12-27`), but the tenant billing view cannot show it.

**Expected:** a tenant owner who pays for the Team plan should see the plan, renewal/status and actual team-seat utilization, or a clear owner-scoped link (“Team billing is managed by <owner>”).

**Actual:** the view is honest but incomplete: `subscription.available:false`, `team_seats` unavailable, and seats derived from tenant membership + invitations rather than the owner’s `team_seats`. This is not a false claim, so severity is P3.

**Impact:** the tenant owner cannot reconcile the Team plan they pay for from the tenant page; support must cross-reference the personal billing page. The seat utilization shown (2 active + 1 invited) is not the team-seat utilization (2 active). For a real agency tenant where tenant members and team seats differ, the numbers would diverge.

**Proposed fix:**

1. Add a tenant-to-owner-subscription reference (or resolve it through `tenant.owner_id -> users.subscription_id`) and show the Team plan status/renewal to the tenant owner.
2. When the tenant owner is also the team owner, map `team_seats.owner_user_id` to the tenant for seat utilization (with the same owner check).
3. If the product intentionally keeps team billing owner-scoped, label it explicitly and link to the owner’s billing page; remove the unavailable warning as a “bug” signal.
4. Add a test with a tenant where tenant-member count and team-seat count differ.

**Owner:** Tenant billing / product. **Status:** open.

---

## ST-H01 — P3 — Team-member fixture bypassed the invite flow and made the matrix stale

**Surface:** audit provisioning / `audit/plans/identity-matrix.json`, not a production user path.

**Observed:** `provision_identities.py` created `team-member` with `subscription_plan:'team'` and its own `subscriptions` row (`6a06f64e-688b-4125-a1e3-2d3bc2517ec2`), while also inserting an active `team_seats` row. It also left `users.subscription_id` null for both owner and member. A real invited member signs up on Free, accepts a seat, and is moved to `team_member` by `join_team_seat` (`backend/app/api/team_routes.py:340-345`). Consequences:

- The baseline `/subscription/current` for the member showed `planId:"team"` with its own subscription id, not a seat-bound plan.
- A naive `GET /team/seats` test would satisfy `_require_team_owner`'s `subscription_plan != "team"` check (the member was stored as `team`), so the endpoint would return 200 and mask the owner-only boundary. This was not executed before the correction, but follows directly from the check at `backend/app/api/team_routes.py:153-168`.
- If the member were corrected to `team_member` without also linking the owner, `_effective_team_member_plan` would find no linked owner subscription and member entitlements would collapse to Free. F1 (owner link) is therefore required for a faithful fixture.

This sub-agent corrected the state (`team_member`, active seat, owner linked, duplicate subscription deleted) before testing; the final DB state and exact statements are in `audit/plans/student-team-trial.md` §2. The shared matrix still lists `plan:"team"` and the deleted subscription id, so it is stale for the next consumer.

**Impact:** audit tooling only. It can produce false PASS/FAIL results for team-seat authorization and seat-bound entitlements. No production impact.

**Proposed fix:**

1. Provision `team-member` as Free with no subscription, then either (a) drive the real invite + accept flow and capture the token from a reachable test Redis/mailbox, or (b) insert the seat as `active` + `users.subscription_plan='team_member'` and set `users.subscription_id` for the owner to the owner’s subscription row.
2. Add a provisioning self-check: member `GET /team/seats` must be 403; member `/config/entitlements` must be seat-derived (unlimited while owner active; Free after owner cancellation); owner `/team/seats` must be 200.
3. Update the matrix (or a companion fixture-state file) after the correction so `subscription_id`/`plan` are not stale. Do not overwrite a shared matrix while other auditors are reading it without recording the change.

**Owner:** audit tooling (`audit/scripts/provision_identities.py`). **Status:** open.

---

## ST-H02 — P3 — Production Redis and test mailboxes are unavailable, so token-accept paths are unverifiable

**Surface:** audit environment / evidence coverage; not a production defect.

**Observed:**

- The audit host’s `.env` `REDIS_CACHE_URL` and `REDIS_URL` both resolve to `redis://redis:6379` (local dev endpoint). It contains none of the `latexy:quota:compilations:*` counters created by the five production compiles, proving it is not the cache the backend writes to.
- `student_plan_verify:*`, `team_invite:*`, and `tenant_invite:*` are written only to the production cache. A scan of the local endpoint after the student verification request returned 0 `student_plan_verify:*` keys; the same endpoint also held none of the production quota counters.
- The synthetic recipients are `@example.test` and `@example.edu`; there is no mailbox and no email-to-HTTP delivery mechanism.
- Better Auth session cookies are signed server-side; the directly provisioned identities have no password, so the billing UI cannot be logged into for a live render.

**Impact:** the following paths are **BLOCKED**, not passing:

- Valid student verification token activation (`GET /subscription/student/verify/{token}`).
- Team invitation preview/accept (`GET/POST /team/join/{token}`) and the email-mismatch 403.
- Tenant invitation accept (`POST /tenants/invitations/{token}/accept`) and the email-mismatch 403.
- Live rendering of trial/past-due conversion prompts.

Downstream authorization was tested by emulating the post-accept state with exact DB statements (recorded in the cohort report), and invalid-token paths were tested live. The 7-day/24-hour invitation tokens that could not be deleted are listed in the cohort report §10.4; the only live one is the tenant invite to an unreadable synthetic mailbox.

**Proposed fix (audit tooling):** provision a test-only Redis reachable from the audit host, or a short-lived admin/read-only token store endpoint that can return a test invitation/verification token for an audit identity; provision a catch-all test mailbox or an email sink; alternatively, allow a signed test-login for audit identities on the production frontend. Do not add a production API that reveals live invitation tokens to ordinary users.

**Owner:** audit tooling / ops. **Status:** open (coverage limitation).
