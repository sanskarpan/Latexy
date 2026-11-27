# Plans, quotas and capability catalog — reconciliation

**Scope:** plan catalog, quota policy, capability catalog, live grant matrix, entitlement UI and admin control plane.
**Mode:** read-only. No production mutation, no user creation, no checkout, no load test.
**Source:** `d2cbc51ab8c25106d073e0e0065b985fc6dc6490` (working tree at `f9e34fa6`, docs-only commits on top).
**Live backend:** `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`, 2026-11-27.

## Verdict

The **129 product-ID claim is accurate**, but it is not the number of runtime controls and it is not the number of capabilities a plan actually receives:

| Count | What it is | Source |
|---:|---|---|
| **129** | Audited product IDs `A01`–`I04`, no duplicates, no gaps | `backend/app/core/capability_catalog.json`; `docs/audits/admin-capabilities/feature-matrix.json:12` |
| **113** | Product IDs with an admin switch (gateable) | catalog; `feature-matrix.json:15` |
| **16** | Product IDs that are immutable baselines (always on) | catalog; `feature-matrix.json:16` |
| **5** | D14 child controls (`d14_latex`, `d14_table_text`, `d14_table_image`, `d14_math_text`, `d14_math_image`) | `backend/app/core/capability_subfeature_catalog.json`; `0073_d14_subfeatures.py:16` |
| **31** | Coarse legacy parent controls (`compile`, `llm_optimize`, `ai_writing`, …) | `backend/app/core/feature_registry.py:46-116` |
| **165** | Runtime registry entries = 31 + 129 + 5 | `feature_registry.py:121-137`; `feature-matrix.json:17` |
| **149** | Runtime gateable controls = 31 + 113 + 5 | `feature-matrix.json:18`; live `capability_labels` = 149 |
| **1639** | Seeded plan-feature cells = 11 plan keys × 149 gateable controls | 0069/0072/0073 seed migrations |
| **596** | Seeded role-feature cells = 4 roles × 149 gateable controls | `0072_capability_roles.py:52-57`; `0073` |

**The live matrix is all-on.** The live public catalog returned **165 capabilities, all 165 `true`, for each of 9 visible plans**, and `/config/entitlements` returned **165/165 true for an anonymous caller**. There are **zero plan-family denials, zero exact-SKU denials, and zero role denials** in the live export. Paid plans currently differ only by quota, retention copy, seats, API daily limit and the `customModels` display flag — not by capability access.

This is either an intentional all-enabled pre-launch baseline or a launch-configuration gap; no source file defines a paid capability matrix. The migration defaults are all `true` (`0069_capability_catalog.py:20-25`, `0072_capability_roles.py:52-57`, `0073_d14_subfeatures.py:21-38`), so the all-on state is the code default, not an admin edit.

---

## 1. Plan catalog

`plans.csv` contains 12 rows: 11 configured SKUs in `SUBSCRIPTION_PLANS` plus the `team_member` seat state. Prices are in **minor units (paise)** because that is how the source and live API expose them.

| Plan | Family | Price (paise) | Interval | Compiles | Optimizations | AI assists | Retention | Seats | API/day | Live |
|---|---|---:|---|---|---|---|---:|---:|---:|---|
| free | free | 0 | month | 10/day | 3/month | 25/month | 0 | 1 | 10 | visible, purchasable |
| basic | basic | 29,900 | month | 400/month | 10/month | 100/month | 30 | 1 | 100 | visible, purchasable |
| basic_annual | basic | 287,100 | year | 400/month | 10/month | 100/month | 30 | 1 | 100 | visible, purchasable |
| pro | pro | 59,900 | month | unlimited | unlimited | unlimited | 365 | 1 | 1,000 | visible, purchasable |
| pro_annual | pro | 575,000 | year | unlimited | unlimited | unlimited | 365 | 1 | 1,000 | visible, purchasable |
| byok | byok | 19,900 | month | unlimited | unlimited | unlimited | 365 | 1 | 500 | visible, purchasable |
| byok_annual | byok | 191,000 | year | unlimited | unlimited | unlimited | 365 | 1 | 500 | visible, purchasable |
| student | pro | 29,900 | month | unlimited | unlimited | unlimited | 365 | 1 | 1,000 | visible, purchasable; email verification required |
| team | team | 249,900 | month | unlimited | unlimited | unlimited | 365 | 5 | 1,000 | visible, purchasable |
| weekly | pro | 0 | week | unlimited | unlimited | unlimited | 365 | 1 | 1,000 | **omitted**; not configured |
| lifetime | pro | 0 | lifetime | unlimited | unlimited | unlimited | 365 | 1 | 1,000 | **omitted**; not configured |
| team_member | team | n/a | n/a | unlimited | unlimited | unlimited | 365 | 1 | 1,000 | seat state, not sold |

Source of truth: `backend/app/core/config.py:467-657` (`SUBSCRIPTION_PLANS`), `:987-1013` (`PLAN_QUOTAS`), `:1048-1067` (`_sync_plan_feature_copy`). Live values: `GET /subscription/plans`, 2026-11-27T10:42:36Z, request `53de3dae-22a3-45c9-9ba3-cca82bc357ad`; 73,195 bytes; 9 plans.

### What actually differs between plans

| Differentiator | free | basic | pro | byok | team | Enforced? |
|---|---|---|---|---|---|---|
| compilations | 10/day | 400/month | unlimited | unlimited | unlimited | Yes, Redis quota (`entitlement_service.py:761-802`) |
| optimizations | 3/month | 10/month | unlimited | unlimited | unlimited | Yes |
| ai_assists | 25/month | 100/month | unlimited | unlimited | unlimited | Yes |
| retention | 0 | 30 | 365 | 365 | 365 | **No** — copy only |
| seats | 1 | 1 | 1 | 1 | 5 | Yes, `team_routes.py:222-233`; `TEAM_PLAN_MAX_SEATS=5` at `config.py:372` |
| API daily limit | 10 | 100 | 1,000 | 500 | 1,000 | Yes, `get_developer_api_daily_limit` at `config.py:950-959` |
| custom models display | no | no | no | yes | no | Display only; actual `d25` capability is true everywhere |
| priority support | no | no | yes | yes | yes | Copy only |
| **capability access** | **all 165** | **all 165** | **all 165** | **all 165** | **all 165** | **No differentiation** |

### Quotas

- `PLAN_QUOTAS` has exactly three dimensions: `compilations`, `optimizations`, `ai_assists` (`config.py:982-1013`).
- Windows are `day` and `month`; only free compiles use `day`.
- Live `GET /subscription/plans` reports `source: "configured_default"` for all 27 visible plan/dimension policies. That means **zero admin quota overrides** are active for the 9 visible plans (`quota_policy_service.py:46-56`).
- Admin overrides live in `plan_quota_overrides` and are versioned (`quota_policy_service.py:69-101`); the read path is `resolve_quota_policy` (`:107-111`).
- `historyRetention` is not part of `PLAN_QUOTAS` and is not read by any enforcement service. Grep finds it only in `config.py` and frontend display code (`PricingCard.tsx:80`, `billing/page.tsx:69`, `SubscriptionManager.tsx:300`). The durable artifact retention service has no plan lookup (`backend/app/services/render_engine/retention.py`).

---

## 2. Capability catalog and live matrix

### Catalog shape

| Category | Product IDs | Gateable | Always-on |
|---|---:|---:|---:|
| core | 39 | 31 | 8 |
| editor | 40 | 36 | 4 |
| advanced | 24 | 20 | 4 |
| career | 13 | 13 | 0 |
| integrations | 13 | 13 | 0 |
| **total** | **129** | **113** | **16** |

- Canonical definitions: `backend/app/core/capability_catalog.json`.
- Runtime registration: `backend/app/core/feature_registry.py:121-137`; subfeatures at `:130-137`.
- Operation-level gates: `backend/app/middleware/capability_router.py:29-214` (182 route policies, 27 dynamic endpoints, 246 passthrough entries).
- Generated per-capability evidence: `docs/audits/admin-capabilities/feature-matrix.json` (129 entries, 5 nested subfeatures).

### Coarse parent controls (not separate rows in `capabilities.csv`)

These 31 controls are the `parent` values referenced by product rows:

- **core:** `compile`, `llm_optimize`, `ats_score`, `ats_deep`
- **editor:** `resume_builder`, `cover_letters`, `batch_tailor`, `templates`, `exports`, `ai_writing`, `macros`, `snippets`
- **career:** `career_paths`, `interview_prep`, `application_tracker`, `one_click_apply`
- **advanced:** `byok`, `collaboration`, `team_workspaces`, `portfolio`, `developer_api`, `references`
- **integrations:** `integration_github`, `integration_dropbox`, `integration_google_drive`, `integration_zotero`, `integration_mendeley`, `ai_import_github`, `ai_import_url`, `ai_import_linkedin`
- **analytics:** `analytics`

All 31 are gateable and seeded true for every plan/role; a child requires its parent as well as its own row (`feature_registry.py:173-184`; `entitlement_service.py:439-454`).

### Live export

```
GET /subscription/plans       200  73,195 bytes  2026-11-27T10:42:36Z  x-request-id 53de3dae-22a3-45c9-9ba3-cca82bc357ad
GET /config/entitlements      200   2,180 bytes  2026-11-27T10:42:38Z  x-request-id 7acf5fa6-864b-4ba2-a509-57954cd41555
GET /config/feature-flags     200  {trial_limits: true, deep_analysis_trial: true, compile_timeouts: true, task_priority: true, billing: true, upgrade_ctas: true}
```

Observed for every visible plan (`free`, `basic`, `basic_annual`, `pro`, `pro_annual`, `byok`, `byok_annual`, `student`, `team`):

- `capabilities`: **165 keys, 165 true**.
- `capability_labels`: **149 keys** (gateable only; the 16 always-on baselines have no label, see `plan_catalog_service.py:133`).
- `quotas`: the values in the table above, all `source=configured_default`.
- `purchasable`: **true for all 9**.
- `billing`: `{provider: "dodo", feature_enabled: true, mode: "enabled", available: true}`.

Anonymous `/config/entitlements` also returned **165/165 true**. Therefore the anonymous role and the free plan are fully enabled in the live database. Because `_decide` intersects the global kill switch, all 149 gateable kill switches must also be `true` for these decisions to pass. Authenticated `user`/`support`/`admin` role rows were not live-exported (admin endpoints require auth); the seed migrations set all four roles to true (`0072_capability_roles.py:52-57`), and no admin mutation evidence was found.

### Effective-decision semantics

`EntitlementService._decide` requires **all** of the following for a gateable key (`entitlement_service.py:439-454`):

1. global kill switch `true`;
2. account role row `true`;
3. plan-family row `true`;
4. exact-SKU row `true` when the SKU is not the family key;
5. every ancestor row `true`.

Consequences:

- **A family-only change is insufficient for annual/student/weekly/lifetime SKUs.** To deny a capability on Basic, an admin must set both `basic` and `basic_annual` false. To deny it on Pro-family SKUs, `pro`, `pro_annual`, `student`, `weekly` and `lifetime` must all be false. There are 11 matrix columns (`PLAN_MATRIX_KEYS` at `feature_registry.py:142`), not 5.
- A missing matrix row denies. New SKUs must be seeded explicitly; 0069 seeds all 11 current keys, 0073 adds the 5 D14 leaves.
- Parent-child enforcement is real: `feature_ancestry` walks the catalog (`feature_registry.py:173-184`), and the product catalog uses 31 coarse parents (e.g. `c05 -> compile`, `d01 -> llm_optimize`, `d25 -> byok`).

### Disable semantics

For gateable controls, disabling stops **new admissions/external actions**; it does not cancel already-admitted jobs, remove artifacts, or remove recovery/read/delete/revocation paths (`backend/app/middleware/capability_router.py:1-13`; `docs/capability-enforcement.md:8-20`). Specific live/declared exceptions:

- public share/review (`f01`/`f02`/`f03`): new share creation denied; public serving stops when the owner's publication is revoked;
- portfolio (`g12`/`g13`): new publish/domain setup denied; existing public page stops serving when publication is revoked;
- collaboration (`f05`): active frames and heartbeats are rechecked; in-flight work is not cancelled;
- BYOK (`d25`): no silent fallback to the platform key;
- developer API (`h09`): existing keys are denied at admission before job creation;
- new purchases (`i01`/`i02`): existing subscriptions, renewals, refunds and seats continue.

The 16 always-on baselines have no kill switch and no plan/role/SKU cell. They are listed in `capabilities.csv` with `default=always_on`.

---

## 3. Plan/role matrix observations and gaps

### F-PC-01 — P1 — Every gateable capability is enabled for every plan and role

**Evidence:** live export above; seed defaults `0069_capability_catalog.py:20-25`, `0072_capability_roles.py:52-57`, `0073_d14_subfeatures.py:21-38`; decision logic `entitlement_service.py:439-454`.

**Observed:** free/basic/pro/BYOK/team all receive `byok` (`d25`), `team_workspaces` (`f08`/`f09`), `collaboration` (`f01`–`f07`), all integrations (`g01`–`g13`), `analytics` (`h06`/`h07`), `developer_api` (`h08`/`h09`), `deep ATS` (`d20`), interview simulation (`e03`), package manager (`c17`), Canva/Figma (`h03`) and email PDF (`h05`).

**Impact:** paid plans are differentiated only by quotas, retention copy, seats and API daily limit. A free account can use BYOK with its own key (which also bypasses `ai_assists` charges, `ai_routes.py:153-167`), create team workspaces, connect integrations, and use the developer API. The ₹199 BYOK offer does not buy the BYOK capability that free already has (only the `customModels` display flag and a 500/day API limit); the ₹2,499 Team offer still buys 5 seats and unlimited quotas, but not exclusive workspace access. This is a product/revenue configuration gap, not a data-security breach.

**Why P1:** it makes paid entitlements and the pricing page materially wrong for every paid cohort. It is not P0 because no data is exposed across tenants and the quotas still meter platform spend.

### F-PC-02 — P1 — Billing is live and all 8 paid visible SKUs are purchasable, while launch docs say billing is held

**Evidence:** live `billing={mode:"enabled", available:true}` and all 8 paid visible plans (plus free) report `purchasable:true`; `docs/LAUNCH_CHECKLIST.md:248-249` says “Billing stays disabled; the pricing page shows only honest unavailable states and no purchasable SKU”; L13 at `:202` says live Dodo acceptance remains open. Ground truth records billing enabled, so live wins; this is a launch-state discrepancy to resolve, not a code defect.

**Impact:** a real-money checkout is exposed without recorded live-sales acceptance. No payments exist yet (ground truth: 0 payments), so no customer funds are at risk today, but the launch gate is not represented by the live config.

### F-PC-03 — P2 — Free plan advertises API access and BYOK, contradicting `SUBSCRIPTION_PLANS` copy

**Evidence:**

- `config.py:481` sets free `apiAccess: False`; free features have no `customModels`.
- Live free has `features.apiAccess=true`, `apiDailyLimit=10`, and `capabilities.d25/h08/h09=true`.
- `plan_catalog_service.py:116-119` overwrites `apiAccess` from `h09` and `customModels` from `d25`.
- `developer_routes.py:116-120` explicitly says developer API on free is intentional; the free limit is 10/day (`config.py:404`).
- BYOK has no equivalent “free is intentional” comment; `byok_routes.py` gates the `d25` leaf (and several operations also require the `byok` parent), and both are true for all plans.

**Impact:** the plan config, pricing copy and server truth disagree. Developer API on free is documented as intentional; BYOK/team/integrations on free are not. Either the copy or the matrix must change.

### F-PC-04 — P2 — `historyRetention` is advertised but not enforced

**Evidence:** `historyRetention` exists only in `SUBSCRIPTION_PLANS` (`config.py:479,495,512,528,545,561,579,597,614,635,652`) and frontend display (`PricingCard.tsx:80`, `billing/page.tsx:69`, `SubscriptionManager.tsx:300`). No backend consumer, no plan lookup in `render_engine/retention.py`, and no retention worker keyed by plan.

**Impact:** free advertises “None” (0 days) and paid advertises 30/365 days, but data is retained according to fixed artifact/PDF policies, not the plan. This is a terms/privacy-copy mismatch and a paid-feature claim with no meter.

### F-PC-05 — P2 — Trial controls are dead; there is no plan-level trial

**Evidence:**

- `User.trial_used` is read/written only by admin user services and GDPR (`admin_user_service.py:176-182,1101-1105,1167-1183`; `gdpr_service.py:981`). `entitlement_service` never reads it.
- Anonymous trial is device-fingerprint based (`trial_service.py:18-21,49-57`) and limited to 3 lifetime compiles; `TEST_USER_EMAILS` can raise it to 100.
- Admin can set `subscription_status="trialing"` for any plan (`admin_control_routes.py:90-94`; `admin_user_service.py:1238-1253`). `_effective_plan_for_billing_status` does not suspend `trialing`, so it returns the paid plan when no linked Dodo row overrides it; a linked Dodo subscription whose provider status is not `active` would fall back to free (`entitlement_service.py:562-575`).
- No checkout code sets a provider trial period (`payment_service.py` has no `trial_period`; grep found none).

**Impact:** the prompt’s “Trial active / expired” cohort cannot be produced through the public checkout. `trial/extend` and `trial/eligibility` do not affect product access; only a plan/status override does. `plans.csv` therefore records `trial_eligible=admin_only` for every plan.

### F-PC-06 — P2 — 13 gateable product capabilities have no server-side admission gate

These are gateable in the catalog and admin UI but have no HTTP policy, dynamic payload gate or service gate in the generated matrix (client-only controls):

`a06` onboarding tour/replay, `c02` completions/navigation, `c03` find and replace, `c04` keyboard modes/shortcuts, `c06` automatic compilation, `c10` SyncTeX, `c11` PDF inspection, `c15` LaTeX lint, `c17` package manager, `c18` symbols/QR/TikZ, `c19` design/template customisation, `c24` compile error history, `e13` browser extension.

**Impact:** disabling them hides the UI control, but there is no server admission to deny. For several (c03/c04/c10/c11/c15/c18/c19/c24) the effect is purely local, so UI hiding is the only possible control. For c17/c06/e13, the underlying server actions are gated by other capabilities (`c05`, `e12`), but the named control itself is not enforce-able. The launch checklist explicitly says “hiding a control only in the UI does not satisfy the gate” (`LAUNCH_CHECKLIST.md:232-234`), so this needs a product decision: document them as UI-only or add a server check.

### F-PC-07 — P3 — 11 gateable product capabilities have no recorded UI entry in the generated matrix

`d05` batch tailoring, `g02` GitHub project import, `g03` portfolio URL import, `g09` bibliography lookup, `g13` portfolio custom domain, `h01` multi-format export, `h02` SVG/JPEG export, `h03` Canva/Figma, `h05` email PDF, `h07` shared-resume analytics, `h09` public developer API.

This is a **matrix coverage gap**, not proof of dead UI. Spot-check: `d05` is not in the generated `clientControls`, but the frontend route policy maps `/workspace/[^/]+/batch-tailor` to `d05` (`frontend/src/lib/capability-ui-policy.ts:67`). Other entries are invoked indirectly (export dropdown, import flow, analytics page). `h09` is intentionally protocol-only. A coverage auditor should not infer a missing feature from this list without checking the route policy and component tree.

### F-PC-08 — P2 — Exact-SKU matrix is a footgun

`_decide` requires both the family and the exact SKU row to be true (`entitlement_service.py:451-454`). The admin UI writes one cell at a time (`admin_routes.py:260-326`). An operator who disables `basic` but forgets `basic_annual` leaves annual Basic fully entitled; disabling `pro` but not `student`, `weekly` and `lifetime` leaves those Pro-family SKUs entitled. The live all-on state hides this. Any gating change must update all 5 family keys and 11 SKU keys as applicable.

### F-PC-09 — P3 — Docs counts are stale by five controls

`docs/LAUNCH_CHECKLIST.md:363-365` says “129 product IDs: 113 gateable and 16 immutable baselines; 31 coarse parents make 160 registry entries / 144 switches.” Actual runtime registry is **165 entries / 149 switches** after the five D14 leaves (`0073_d14_subfeatures.py`). `feature-matrix.json:17-18` already has the correct 165/149. The 129 product claim itself is correct; the 160/144 total is not.

### F-PC-10 — P3 — All 16 always-on product IDs have no capability seed row

`A01`–`A05`, `A07`, `A08`, `C08`, `C09`, `C25`, `C26`, `H10`–`H13` and `I04` are non-gateable. They are absent from the `0069`/`0072` seed key lists by design, so they have no `feature_flags`, `plan_features` or `role_features` row. They still appear in the registry and in the live `capabilities` map as `true`. This is correct for “always on”, but it means there is no per-ID audit row and no admin visibility beyond the registry response. The five C/I examples (`C08`, `C09`, `C25`, `C26`, `I04`) are the easiest to mistake for missing product IDs because they sit inside otherwise contiguous gateable ranges.

### F-PC-11 — P3 — Live `capabilities` has 165 keys but only 149 labels

`plan_catalog_service.py:133` labels only gateable entries. The pricing page renders `Object.entries(plan.capabilities).filter(enabled && label)` (`PricingCard.tsx:93-99`), so it lists **149 capabilities for every plan** and silently omits the 16 baselines. Combined with F-PC-01, the free pricing card shows the same 149-item “Included capabilities” list as Team. This is both a UX problem and a paid-value disclosure problem.

### F-PC-12 — P3 — `weekly` and `lifetime` exist but are unsellable and unpriced

`config.py:623-656` defines both with `price: 0`, `configuration_required: true`. `is_b57_sku_configured` requires a Dodo product ID and a positive amount (`config.py:931-942`); `plan_catalog_service.py:98-105` omits unconfigured B57 SKUs from the public catalog. Live confirms only 9 plans, not 11. No live price or checkout exists for either. If marketing/roadmap references weekly or lifetime, the offer is not available.

---

## 4. Orphan / missing capability audit

| Check | Result | Evidence |
|---|---|---|
| Catalog IDs duplicated or missing | **None.** 129 IDs, A01–A09, B01–B14, C01–C26, D01–D26, E01–E13, F01–F11, G01–G13, H01–H13, I01–I04 | `capability_catalog.json` |
| Router capability keys not in registry | **0** | 87 distinct keys referenced by `ROUTE_CAPABILITIES`, all in `FEATURE_REGISTRY` |
| Registry keys not in catalog | **31** coarse parents, intentional | `feature_registry.py:46-116` |
| Gateable product capabilities with no HTTP/dynamic/service gate | **13** | F-PC-06 list |
| Gateable product capabilities with no direct UI control | **11** | F-PC-07 list |
| Always-on product capabilities with no switch | **16** | `capabilities.csv` `default=always_on` |
| Product IDs absent from seed migrations | **16** (all always-on baselines: `a01`–`a05`, `a07`, `a08`, `c08`, `c09`, `c25`, `c26`, `h10`–`h13`, `i04`) | `0069`/`0072` key lists |
| Live plan/SKU/role denials | **0** | 9 plans × 165 true; anonymous 165 true |
| Admin quota overrides | **0** of 27 visible policies | live `source=configured_default` |
| Unconfigured SKUs | **2** (`weekly`, `lifetime`) | live catalog omits both |
| Seat-only SKU | **1** (`team_member`) | `entitlement_service.py:515-516,593-625` |
| Dead trial controls | **2** (`trial/eligibility`, `trial/extend` do not affect access) | F-PC-05 |
| Copy-only plan feature | **1** (`historyRetention`) | F-PC-04 |

### Capability subfeatures

The five D14 leaves are real, separately switchable controls and are included in `capabilities.csv` with `parent=d14`:

| ID | Parent | Endpoint | UI |
|---|---|---|---|
| `d14_latex` | `d14` | `POST /ai/generate-latex` | `frontend/src/components/LatexGeneratorPanel.tsx` |
| `d14_table_text` | `d14` | `POST /ai/generate-table` | same |
| `d14_table_image` | `d14` | `POST /ai/generate-table-image` | same |
| `d14_math_text` | `d14` | `POST /ai/generate-math` | same |
| `d14_math_image` | `d14` | `POST /ai/generate-math-image` | same |

The parent `d14` is an ancestor check on all five and has no route of its own; `capabilities.csv` lists the five leaf endpoints on the parent row for traceability.

---

## 5. Entitlement UI and admin control plane

### Frontend

- `EntitlementsContext` fetches `/config/entitlements` with an 8-second timeout and a 30-second refresh; unknown/error states deny (`frontend/src/contexts/EntitlementsContext.tsx:19-21,60-118`).
- `CapabilityGate` and `useEntitlements().can()` fail closed; `CapabilityRouteBoundary` blocks routes (`frontend/src/components/CapabilityGate.tsx:7-12`; `CapabilityRouteBoundary.tsx:7-46`).
- The entitlement map is identity-scoped and invalidated on account switch (`EntitlementsContext.tsx:45-51,107-111`). No stale-allow window was found.
- **Because the server returns all 165 true, every gate in this UI is open on every plan today.**
- Pricing page: `PricingCard.tsx:75-99` renders the quota rows and the 149 labeled capabilities for every plan; `billing/page.tsx:64-78` renders the same comparison.

### Admin control plane

19 admin operations govern these surfaces:

| Surface | Operations |
|---|---|
| Capability state | `GET /admin/entitlements`; `PATCH /admin/entitlements/kill-switch/{key}`; `PATCH /admin/entitlements/matrix`; `PATCH /admin/entitlements/roles` (`admin_routes.py:203-395`) |
| Bulk entitlements | `POST /admin/entitlements/bulk` (`admin_approval_routes.py:453`) |
| Plan catalog | `GET /admin/plan-catalog`; `PATCH /admin/plan-catalog/{sku}`; `PATCH /admin/plan-catalog/{sku}/quotas/{dimension}` (`plan_catalog_routes.py:34-102`) |
| Feature flags | `GET /admin/feature-flags`; `PATCH /admin/feature-flags/{key}` (`admin_routes.py:104-123`) |
| Per-user plan/feature/trial/quota | `POST /admin/users/{id}/plan`; `features/grant`; `features/revoke`; `trial/extend`; `trial/eligibility`; `trial/reset`; `quota/reset` (`admin_control_routes.py:430-554`) |
| User lookup / role | `GET /admin/users`; `PATCH /admin/users/{id}/role` (`admin_routes.py:592-641`) |

The public `/config/feature-flags` route (`admin_routes.py:81`) exposes the six operational flags without admin auth; it is not an admin mutation surface. There is no public global/role matrix endpoint, but the public `/subscription/plans` catalog does expose each plan’s effective capability booleans (all 165 true today).

`GET /admin/entitlements` and `GET /admin/plan-catalog` both returned **401 Authentication required** to this read-only audit (requests `521d94b4-63a0-46bc-8751-7a9df2a53268` and `db484576-0129-4ffe-adc3-6634534d047b` at 2026-11-27T10:52Z). No admin token was used.

The six **operational** flags are separate from the capability catalog (`feature_flag_service.py:33`): `trial_limits`, `deep_analysis_trial`, `compile_timeouts`, `task_priority`, `billing`, `upgrade_ctas`. All six are `true` live. They do not grant or deny the 129/165 controls.

---

## 6. Reconciliation of the “129 user-facing capabilities” claim

**Accurate as a product-ID claim; misleading as a control/switch count.**

- 129 is exactly the product inventory (`A01`–`I04`), no duplicates, no gaps.
- 113 of those are gateable; 16 are immutable baselines.
- Five D14 subfeatures are separately user-facing controls and are not part of the 129; they are part of the 149 runtime switches.
- 31 coarse parent controls are also separately switchable and are not part of the 129.
- The live API exposes 165 capability keys and 149 labels, not 129.
- The docs’ “160 registry entries / 144 switches” is stale; actual is 165/149.
- The live matrix grants all of them to all plans and roles. The claim “129 audited capabilities” therefore does not imply 129 differentiated plan entitlements; today it implies 129 product IDs all available everywhere.

---

## 7. Blocked / not verified

| Item | Status | Reason |
|---|---|---|
| Live OpenAPI export | Blocked | `/openapi.json`, `/api/openapi.json`, `/docs`, `/api/docs` return 404; used `audit/inventory/openapi-source.json` at the deployed backend SHA |
| Live authenticated role matrix | Not verified | `/admin/entitlements` requires admin auth; no credential was used. Anonymous role is live-verified; `user`/`support`/`admin` are inferred from the all-true seed |
| Live DB row counts | Blocked | Local `backend/.env` `DATABASE_URL` host `db.qmnsqkssbozhqlqzhsn.supabase.co` is NXDOMAIN; the Supabase pooler returns “tenant/user … not found”. The local credential is stale relative to production. Live API export was used instead |
| Exact `weekly`/`lifetime` rows | Not exported | Both are omitted from the public catalog because Dodo product/amount are unset; seed migrations seed all 11 keys true |
| Plan-level trial | Not present | No checkout trial period; admin-only `trialing` status. See F-PC-05 |
| Retention enforcement | Not found | Copy-only field; no backend consumer. See F-PC-04 |
| Cold-start anomaly | Observation only | First `/subscription/plans` request returned 404; an immediate retry returned 200/73 KB. Not counted as a plan defect; may be a Modal cold-start/routing race worth a separate reliability probe |

No production mutation, account creation, checkout, load test, or capability flip was performed. No test accounts or flags were created, so there is nothing to clean up in `cleanup.md`.

---

## 8. Recommendations (no changes made)

1. **Decide and encode the intended launch matrix.** If the recommended beta scope is the intent, the gate-off list in `LAUNCH_CHECKLIST.md:217-230` is the only in-repo candidate: `b06`, `e09/e10/e12/e13`, `g01`–`g13`, `h08/h09`, `e03`, `d20`, `c17`, `h03`, `h05`, `f08`–`f11`, `i01`–`i04`. Today all are on.
2. **If paid differentiation is intended,** gate at minimum `d25` (BYOK) to `byok`/`byok_annual`, `f08`/`f09` (team workspaces) to `team`, and the integrations/collaboration/analytics groups to their paid families. Remember both the family and exact-SKU cells (11 matrix columns).
3. **Fix the free copy/API mismatch.** Either set `features.apiAccess/customModels` copy to match the live capability-driven values, or gate `h09`/`d25` so the copy is true. Developer API on free is explicitly intentional (`developer_routes.py:116-120`); BYOK on free is not documented.
4. **Enforce or remove `historyRetention`.** A pricing field with no meter is a terms/privacy claim; add a retention worker keyed by plan or remove the field from the catalog.
5. **Wire or remove trial controls.** `trial/extend`/`trial/eligibility` mutate metadata that entitlement never reads. Either make `trial_used` part of the free/anonymous decision or delete the dead admin controls.
6. **Give the 13 client-only controls an explicit disposition.** Document them as UI-only, or add a server-side check where a server action exists (`c06`, `c17`, `e13`). Do not claim they are server-gated.
7. **Add a plan-differentiation regression test.** A test that asserts at least one paid capability differs from free would have caught F-PC-01; today a 165/165 all-true matrix passes every cross-product test.
8. **Update the docs counts** from 160/144 to 165/149 and clarify that 129 is product IDs, not switches or plan entitlements.
9. **Reconcile billing state** with the launch checklist: live Dodo is enabled and all 8 paid visible SKUs are purchasable, while the checklist says billing is held. Record the owner decision either way.

---

## Appendix — source references

| Area | Reference |
|---|---|
| Plan copy/prices/features | `backend/app/core/config.py:467-657` |
| Enforced quotas | `backend/app/core/config.py:982-1013` |
| Quota copy sync | `backend/app/core/config.py:1048-1067` |
| Family/SKU aliases | `backend/app/core/config.py:884-910` |
| API daily limits | `backend/app/core/config.py:950-959` |
| Team seat cap | `backend/app/core/config.py:372`; `backend/app/api/team_routes.py:222-233` |
| Registry / matrix keys | `backend/app/core/feature_registry.py:38-43,121-184` |
| Product catalog (129) | `backend/app/core/capability_catalog.json` |
| D14 subfeatures (5) | `backend/app/core/capability_subfeature_catalog.json`; `0073_d14_subfeatures.py:16-38` |
| Seed defaults | `backend/alembic/versions/0069_capability_catalog.py:16-25`; `0072_capability_roles.py:11,52-57` |
| Effective decision | `backend/app/services/entitlement_service.py:402-457` |
| Quota meter | `backend/app/services/entitlement_service.py:761-802` |
| Plan catalog API projection | `backend/app/services/plan_catalog_service.py:79-153` |
| Quota override policy | `backend/app/services/quota_policy_service.py:41-111` |
| Route capability map | `backend/app/middleware/capability_router.py:29-214` |
| Payload/dynamic gates | `backend/app/middleware/capability_router.py:479-582` |
| Admin entitlement routes | `backend/app/api/admin_routes.py:203-395` |
| Admin plan catalog routes | `backend/app/api/plan_catalog_routes.py:34-102` |
| Admin per-user controls | `backend/app/api/admin_control_routes.py:430-554` |
| Frontend entitlement context | `frontend/src/contexts/EntitlementsContext.tsx` |
| Pricing capability list | `frontend/src/components/billing/PricingCard.tsx:75-99` |
| Launch gate list / stale counts | `docs/LAUNCH_CHECKLIST.md:217-234,248-249,363-365` |
| Generated per-capability matrix | `docs/audits/admin-capabilities/feature-matrix.json:12-20` |

**Live evidence requests:** `GET /subscription/plans` (`53de3dae-22a3-45c9-9ba3-cca82bc357ad`), `GET /config/entitlements` (`7acf5fa6-864b-4ba2-a509-57954cd41555`), `GET /config/feature-flags` (200), `GET /admin/entitlements` 401 (`521d94b4-63a0-46bc-8751-7a9df2a53268`), `GET /admin/plan-catalog` 401 (`db484576-0129-4ffe-adc3-6634534d047b`), all on 2026-11-27 (10:42–10:52 UTC).
