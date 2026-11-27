# Defects — Free / Basic monthly / Basic annual

Audit window: **2026-11-27T10:49:06Z → 2026-11-27T11:18:13Z** (UTC)
Environment: production (`sanskarpandey2004--latexy-backend-fastapi-app.modal.run`)
Scope: free, basic-monthly, basic-annual journeys and quota behavior.

No P0/P1 defect was confirmed for these cohorts. The records below are P2/P3.

---

## CAP-01 — All plan families and roles are granted every gateable capability; Free gets features priced as Basic

> Cross-cutting duplicate of lead register **CAP-01**; recorded here because it determines free/basic upgrade behavior.

**Severity:** P2 (entitlement/monetization mismatch; may be intended all-enabled launch state)
**Surface:** capability matrix, plan differentiation, upgrade prompts
**Cohort(s):** free, basic-monthly, basic-annual (environment-wide)
**Status:** open — needs launch-intent confirmation

### Expected

The pricing page differentiates tiers. For example `frontend/src/app/pricing/page.tsx` lists under **Basic only**: “Cover letters” and “Saved history and role-specific versions.” A Free account should therefore be denied Basic-only capabilities (or the copy should not claim exclusivity).

### Actual

`GET /admin/entitlements` (read-only, admin identity) at **2026-11-27T11:18:13Z**, request **`d672c690-6daa-4795-b829-8cab26a179b1`**, returned:

- **149/149** gateable capabilities `true` for **every** plan family: `free`, `basic`, `basic_annual`, `pro`, `pro_annual`, `byok`, `byok_annual`, `student`, `team`, `weekly`, `lifetime`.
- **149/149** `true` for **every** role: `anonymous`, `user`, `support`, `admin`.
- All global kill switches `true` (none off).

Effective snapshots agree: free `GET /config/entitlements` 200 (10:49:11Z, request `4147a612-330c-406b-ae05-2625eeab9f0b`) has `cover_letters: true`, `portfolio: true`, `developer_api: true`, `byok: true`, `team_workspaces: true`. `GET /subscription/plans` reports free `apiAccess: true`, `apiDailyLimit: 10`.

This matches the all-enabled seed in `backend/alembic/versions/0069_capability_catalog.py` (inserts `plan_features ... true` for every plan key), so it is probably the current launch configuration rather than a transient audit flip. The result is that plan differentiation is **quota-only**; feature locks never produce an upgrade prompt for these cohorts.

### Impact

- Pricing-tier value is not reflected in server authorization; Free can use capabilities advertised as Basic/Pro.
- Upgrade-prompt and paywall tests cannot distinguish plans by capability.
- If all-enabled is intentional, marketing copy is wrong. If it is not, every plan has an entitlement leak.
- Not a security or tenant-isolation issue.

### Reproduce

1. `GET /config/entitlements` with the Free session → inspect `features.cover_letters`, `portfolio`, `developer_api`.
2. `GET /admin/entitlements` with the admin session → inspect `matrix.free` / `role_matrix.anonymous` (read-only).
3. Compare with `frontend/src/app/pricing/page.tsx` tier feature lists.

### Proposed fix

Confirm launch intent with the owner. If all-enabled is intended, remove tier-exclusive claims from pricing/upgrade copy and make plan differences explicitly quota/retention-based. If not, disable the free/anonymous cells for the paid-only capabilities and rerun the plan-gated pass.

> Cross-cutting: likely overlaps the capability audit; recorded here because it determines free/basic upgrade behavior.

---

## RET-01 — History retention is displayed as None/30 days but is not enforced

> Cross-cutting duplicate of lead register **RET-01**.

**Severity:** P2 (advertised paid-plan feature not implemented; over-retention for Free)
**Surface:** billing/pricing copy, resume optimization history, ATS score history
**Cohort(s):** free, basic-monthly, basic-annual
**Status:** open

### Expected

- Free: `historyRetention: 0`; the UI renders this as **“None”** (`frontend/src/components/billing/PricingCard.tsx`, `SubscriptionManager.tsx`, `app/billing/page.tsx`).
- Basic: `historyRetention: 30`; history older than 30 days should be unavailable and purged.

### Actual

- `GET /subscription/plans` and `/subscription/current` return `historyRetention: 0` (Free) and `30` (Basic/Basic Annual).
- No backend consumer of `historyRetention` exists outside `backend/app/core/config.py` (backend-wide search). There is no plan-aware read filter and no purge job for user history.
- `GET /resumes/{id}/optimization-history` returns the 20 newest rows regardless of plan; `GET /resumes/{id}/score-history` returns all scored rows regardless of plan (`backend/app/api/resume_routes.py`).
- Fresh proof on **Free** (whose UI says “None”):
  - `POST /resumes/d0e35c34-d619-4384-a5c6-b4eb39135d3f/record-optimization` → **201** at 11:15:20Z, request `809974e7-456e-4fac-8da9-37719abc92e0`.
  - `GET .../optimization-history` → **200**, 1 row, request `77617cc1-ef5c-4b58-a3cd-43c4aa55e630`.
  - `GET .../score-history` → **200**, 1 row, request `4a4ff05a-da4e-4a79-b043-b05d9955194c`.
- Same on Basic monthly: record 201 `aed5d3e8-66f6-4cb0-a40d-6be6614e3632`; history 200 `85b23441-9a66-4667-9117-ec464e307ba3`.

### Impact

- A paid Basic promise (“30 days”) and a Free limitation (“None”) are both unbacked.
- Free accounts retain history that the UI says they do not have; this may conflict with the stated product retention behavior.
- No user-visible breakage; no data loss.

### Reproduce

1. Create/choose a resume for Free and Basic.
2. `POST /resumes/{id}/record-optimization` with any valid original/optimized LaTeX and `ats_score`.
3. `GET /resumes/{id}/optimization-history` and `/score-history` for both cohorts.
4. Compare with `/subscription/current.features.historyRetention`.

### Proposed fix

Either enforce per-plan retention in the read path (`created_at >= now - retention_days`) plus a scheduled purge, or remove `historyRetention` from plan/UI copy if it is not a product commitment. Add a regression test that Free cannot read history beyond its configured retention and that Basic cannot read older than 30 days.

---

## FB-03 — “Use template” resumes lose `selected_template_id`; downstream template attribution is null

**Severity:** P3 (analytics undercount, no user-facing failure)
**Surface:** template gallery → resume → compile/export analytics
**Cohort(s):** free, basic-monthly, basic-annual
**Status:** open

### Expected

A resume created through `POST /templates/{template_id}/use` should retain the catalog template identity so later compile/export events can be attributed to that template.

### Actual

The endpoint returns 200 and creates the resume, but the saved row has:

- `selected_template_id: null`
- `content_source: "manual_latex"`
- `builder_status: "detached"`

Observed for all three cohorts:

| Cohort | Use request | Resume readback | `selected_template_id` |
|---|---|---|---|
| free | `2c3b55e7-2079-4b70-8f2f-4bd1b97e46dc` (10:53:11Z) | `29bf3ac1-f5a5-4cc5-a06a-ba971f727944` | `null` |
| basic-monthly | `7ecad5b6-ce99-4862-8b24-412874fd5959` (10:53:30Z) | `a06ca085-9834-493b-895a-1960fbcb7ae2` | `null` |
| basic-annual | `48e8637a-1f26-433d-a807-f20c9d0bafce` (10:53:48Z) | `c896ffca-1aca-457c-a99f-7da4c8c1ed5b` | `null` |

`use_template` in `backend/app/api/template_routes.py` constructs `Resume(...)` without `selected_template_id`; it only records a `template_use` analytics row keyed `template-use:{resume_id}`. Later, both `backend/app/api/job_routes.py` (`_resolve_compile_template_id`) and `backend/app/api/export_routes.py` read `resume.selected_template_id` to attach the template id to compile/export events. Those events therefore carry `template_id: null`.

### Impact

Admin template performance can count gallery uses but cannot attribute subsequent compiles or exports to the template for gallery-originated resumes. The user-facing template flow is unaffected.

### Reproduce

1. `POST /templates/{id}/use` with an authenticated identity.
2. `GET /resumes/{resume_id}` → observe `selected_template_id: null`.
3. Submit a compile job with `metadata.resume_id` and inspect the resulting template analytics event (or source path above).

### Proposed fix

Set `selected_template_id=t.id` when creating the resume in `use_template` (and preserve it through variants/forks if intended), or persist an explicit resume→template mapping that compile/export analytics can read.

---

## FB-04 — Single 17.65 s entitlement snapshot on basic-monthly

**Severity:** P3 (single-sample latency anomaly; no error, not reproduced)
**Surface:** `GET /config/entitlements` (page bootstrap/quota meter)
**Cohort:** basic-monthly
**Status:** open — needs trace

### Expected

Entitlement/quota snapshot should complete in the same range as the other cohorts (~1.8–2.0 s client-observed in this window). `docs/observability/slos.md` lists a p95 under 2.0 s target for API requests.

### Actual

`GET /config/entitlements` at **2026-11-27T10:49:36Z**, request **`315d56d2-91d1-4620-92bd-b07fe2975e9b`**, took **17,654.8 ms** and returned 200 with correct data.

Across 26 snapshots in this window: median 1,874.8 ms, p95 1,987.3 ms, max 17,654.8 ms. The next basic-monthly snapshot at 10:56:03Z (`8187cd81-71c6-49c4-b673-1852823a2795`) was 1,836.9 ms, and later calls stayed 1.8–1.9 s. No 5xx and no quota error.

### Impact

A page that blocks on the entitlement snapshot could stall ~18 s for an affected request. With one sample, this may be a cold Modal container, DB pool wait, or Redis authority check; it is not proven to recur.

### Reproduce / investigate

Replay `GET /config/entitlements` against a cold basic-monthly session while capturing Modal trace IDs and DB pool metrics; compare the `_quota_authority_active`/DB snapshot path in `backend/app/services/entitlement_service.py` and the request log for `315d56d2-...`.

### Proposed fix

Trace the request end-to-end (edge → Modal → DB/Redis). If cold start, set appropriate `min_containers` or warm the entitlement path; if DB pool, review pool sizing/lock waits. Do not mask it with a cache until the baseline is captured.

---

## Coverage gaps (not defects)

- **402 quota exhaustion not exercised** for any cohort: deliberately avoided exhausting Free’s 3 optimizations / 10 daily compiles and Basic’s 400/10/100. Limit values, windows, successful charges, and the compile-failure refund were verified; the 402 response shape is read from `entitlement_service.enforce_quota` only.
- **UI not exercised:** in-app browser unavailable (`browser.not_attached`). Template and resume-edit source signatures were inspected instead.
- **30-day retention boundary** cannot be observed with fresh data; RET-01 relies on plan copy plus read-path/code inspection and fresh record/read calls.
- **Optimize/AI-assist failure refund** not triggered; only the compile failure refund path is empirically verified. Code shows refund calls on `optimize_routes`/`ai_routes` error paths.
