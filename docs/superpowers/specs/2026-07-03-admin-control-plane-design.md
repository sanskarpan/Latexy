# Admin Control Plane + Auth Completion — Design

**Goal:** A gated admin dashboard where an admin toggles features globally (kill-switch) and per pricing plan (feature × plan matrix), with hard backend + frontend enforcement — plus completion of the missing auth flows.

**Architecture (approved: Approach A):** A code-defined **feature registry** (catalog) + DB **state** tables, served through one `EntitlementService.has_feature(user, key)` seam that reuses the existing feature-flag DB→Redis→short-cache propagation (reaches FastAPI *and* Celery workers). RBAC via a real `role` column on `users`.

**Decisions locked with the user:**
- Scope = Admin Control Plane **+** Auth Completion (two sub-projects).
- Real RBAC role column (not just `ADMIN_EMAIL`).
- Toggle model = global kill-switch **AND** per-plan matrix.
- Enforcement = hard (backend 403/402 **and** frontend hide).
- Matrix depth = feature access on/off per plan (no numeric quota metering).
- Launch default = **everything enabled for all plans** (pricing gated).
- Email verification = **soft** (built, not blocking); password reset built provider-agnostic.

---

## Sub-project 1 — Admin Control Plane

### 1.1 Feature registry (code) — `backend/app/core/feature_registry.py`
A static list of toggleable product features. NOT the 6 existing operational flags (`trial_limits`, `deep_analysis_trial`, `compile_timeouts`, `task_priority`, `billing`, `upgrade_ctas`) — those stay as-is.

```python
@dataclass(frozen=True)
class FeatureDef:
    key: str            # stable id, e.g. "cover_letters"
    label: str          # "Cover Letters"
    category: str       # "core" | "editor" | "career" | "advanced" | "integrations" | "analytics"
    description: str
    gateable: bool = True   # if False, never blocked (e.g. core compile) — still shown in dashboard as always-on

FEATURE_REGISTRY: list[FeatureDef] = [ ... ~26 entries ... ]
```
Registry keys (initial catalog):
- core: `compile` (gateable=False), `llm_optimize`, `ats_score`, `ats_deep`
- editor: `resume_builder`, `cover_letters`, `batch_tailor`, `templates`, `exports`, `ai_writing`, `macros`, `snippets`
- career: `career_paths`, `interview_prep`, `application_tracker`, `one_click_apply`
- advanced: `byok`, `collaboration`, `team_workspaces`, `portfolio`, `developer_api`, `references`
- integrations: `integration_github`, `integration_dropbox`, `integration_zotero`, `integration_mendeley`
- analytics: `analytics`

Helpers: `get_feature(key)`, `all_feature_keys()`, `gateable_keys()`, `PLAN_FAMILIES = ["free","basic","pro","byok","team"]`.

### 1.2 Data model
**RBAC** — add to `User` (`models.py`): `role: str = Column(String(20), default="user", nullable=False)` — values `user | support | admin`. (Per-resource roles like `WorkspaceMember.role` are unrelated.)

**Global kill-switch** — reuse existing `feature_flags` table. One row per registry feature, key = the feature key (namespaced to avoid clashing with the 6 operational flags — feature rows are those whose key ∈ registry). `enabled=True` default.

**Per-plan matrix** — new table `plan_features`:
```
plan_features(
  plan_family  VARCHAR(20)  not null,   # free|basic|pro|byok|team
  feature_key  VARCHAR(100) not null,
  enabled      BOOLEAN      not null default true,
  updated_at   TIMESTAMP,
  PRIMARY KEY (plan_family, feature_key)
)
```
Model `PlanFeature` in `models.py`.

**Migration** (single new revision, down_revision = current head `0034`): add `users.role`, create `plan_features`. Data seed in migration: for every (family × gateable feature) insert `enabled=true` (launch default = all on); insert a `feature_flags` kill-switch row (enabled=true) for each gateable feature if absent. Boot reconcile (in `main.py` lifespan or a startup hook): set `role='admin'` for users whose email ∈ `ADMIN_EMAILS`.

> conftest `required_columns` must be updated to include `("users","role")` so the test-DB schema check passes.

### 1.3 EntitlementService — `backend/app/services/entitlement_service.py`
Mirrors `feature_flag_service` patterns. Source of truth = DB; fast propagation = Redis JSON blob `latexy:entitlements` = `{ "kill": {key:bool}, "matrix": {family:{key:bool}} }`; in-process TTL cache (60s) for the async path; workers read Redis (near-immediate).

API:
- `async has_feature(key, *, user, db) -> bool` — resolution order:
  1. If `key` not gateable (or unknown) → **True**.
  2. If `user.role in ("admin","support")` → **True** (admin bypass; support sees everything).
  3. Global kill-switch off → **False**.
  4. `family = resolve_plan_family(user.subscription_plan)` (anonymous/None → `"free"`).
  5. matrix[family][key] (default True) → return it.
  - **Fail-open** on infra error (return True) — consistent with existing flag service; logged.
- `sync_has_feature(key, plan_family) -> bool` — worker path via Redis blob (no admin/user context; workers act on a job's plan family).
- `get_state(db)` → `{registry, kill_switches, matrix}` for the admin API.
- `set_kill_switch(key, enabled, db)`, `set_matrix_cell(family, key, enabled, db)` → write DB, rebuild Redis blob, clear cache.
- `effective_features(user, db) -> dict[str,bool]` → the per-feature allow map for the current user (drives frontend gating).

### 1.4 Enforcement seam
Backend dependency factory — `backend/app/middleware/entitlements.py`:
```python
def require_feature(key: str):
    async def _dep(user = Depends(get_current_user_required), db = Depends(get_db)):
        if not await entitlement_service.has_feature(key, user=user, db=db):
            raise HTTPException(403, detail=error_body("feature_disabled", f"The '{key}' feature is not available on your plan."))
        return user
    return _dep
```
Wire into the **primary entry route** of each gateable feature (not every endpoint) — e.g. `cover_letter_routes` create, `byok_routes` add-key, `career_routes` analyze, `interview_routes`, `application_routes` apply, `developer_routes`, integration connect routes, `ats_routes` deep-analyze, export create, etc. Anonymous-allowed features (compile/optimize/ats trial) keep their trial gating; `require_feature` applies to the authenticated entry only.

Worker path: where a worker performs a gateable action tied to a plan, call `sync_has_feature` (optional; primary enforcement is at the API boundary).

### 1.5 RBAC guard — `auth_middleware.py`
- `require_admin` upgraded: allow if `user.role == "admin"` **OR** email ∈ `ADMIN_EMAILS` (backward compat; the email-matched user is also reconciled to role=admin at boot).
- New `require_role(*roles)` factory.
- `ADMIN_EMAIL` → also accept a comma-list `ADMIN_EMAILS` (keep `ADMIN_EMAIL` working).

### 1.6 Admin + config API — extend `admin_routes.py`
- `GET  /admin/entitlements` (admin) → `{registry, kill_switches, matrix, plan_families}`.
- `PATCH /admin/entitlements/kill-switch/{key}` (admin) `{enabled}`.
- `PATCH /admin/entitlements/matrix` (admin) `{plan_family, feature_key, enabled}`.
- `GET  /admin/users` (admin) → paginated users w/ role, plan, email.
- `PATCH /admin/users/{id}/role` (admin) `{role}` (cannot demote the last admin / self-lock guard).
- `GET  /config/entitlements` (auth optional) → `effective_features(current_user)` for frontend gating (anonymous → free-family map).

All admin routes reuse existing envelope + `require_admin`.

### 1.7 Frontend
- `frontend/src/contexts/EntitlementsContext.tsx` + `useEntitlements()` — fetch `/config/entitlements` on session; `can(featureKey): boolean`. Defaults: while loading, treat as allowed to avoid flof hiding (or show skeleton).
- Gate UI: hide/disable nav items and feature entry points via `can(key)` (extend `GlobalHeader` nav filter pattern already used for `flags.billing`). Disabled feature pages show a graceful "not available on your plan" state.
- **Admin dashboard** — extend `frontend/src/app/admin/page.tsx` into tabs:
  1. **Feature Flags** (existing 6 operational flags) — keep.
  2. **Features × Plans matrix** — a grid: rows = registry features (grouped by category), columns = plan families, cells = toggles; plus a per-feature global kill-switch column. Optimistic update, toast, error rollback. Clean, dense, readable UI.
  3. **Users & Roles** — searchable user list with role dropdown (user/support/admin), plan display.
  - Gate `/admin` client-side on `session.user.role === "admin"` (in addition to backend 403).

### 1.8 Testing (backend + frontend)
- Backend: registry integrity; `has_feature` resolution matrix (kill-switch off, plan off, admin bypass, anon→free, fail-open); `require_feature` returns 403 when disabled and passes when enabled; admin API auth (non-admin 403) + mutations propagate to Redis; role endpoints incl. last-admin guard; migration column presence.
- Frontend: `useEntitlements` gating; admin matrix editor renders + toggles call API; role guard hides `/admin` for non-admins; typecheck + lint clean.

---

## Sub-project 2 — Auth Completion

### 2.1 Logout
Add a user menu (avatar dropdown) in `GlobalHeader` with **Sign out** → `authClient.signOut()` → redirect `/`. (Function exists; just wire UI.)

### 2.2 Auth-endpoint rate limiting
Better Auth runs on the Next server (outside FastAPI limiter). Enable Better Auth's built-in `rateLimit` in `frontend/src/lib/auth.ts` (window + max on `/sign-in`, `/sign-up`, reset). Storage: Better Auth memory/DB store.

### 2.3 Password reset (provider-agnostic)
- Backend/email: an email-sender abstraction already exists (`email_service`, gated by `EMAIL_ENABLED`). Better Auth handles reset on the Next side — configure `emailAndPassword.sendResetPassword` to call a mail function (Resend when `RESEND_API_KEY` set; otherwise log a dev link + no-op). Pages: `/forgot-password`, `/reset-password`. "Forgot password?" link on `SignInForm`.

### 2.4 Soft email verification
- Configure `emailVerification.sendVerificationEmail` (same mail abstraction). Keep `requireEmailVerification: false`. Add a dismissible "verify your email" banner for unverified users; `/verify-email` handler page. No blocking.

### 2.5 Testing
- Auth flows: reset/verify handlers invoked (mock mail), rate-limit config present, logout wired. Frontend pages render + form validation.

---

## Build order
1. **W1 DB layer** (one agent owns `models.py` + one migration + conftest column): `role`, `plan_features`, seed, boot reconcile.
2. **W2 Backend core**: `feature_registry`, `entitlement_service`, `require_feature`, RBAC guard upgrade.
3. **W3 Backend API + wiring + tests** (parallel: API/wiring | tests).
4. **W4 Frontend** (parallel: entitlement gating | admin dashboard | auth completion).
5. **W5 Adversarial audit** (parallel dimensions) → fix → full suite + ruff + typecheck green.

## Non-goals (this program)
Numeric quota metering; billing enablement; OAuth app provisioning; storage/secret rotation (separate go-live track). OAuth buttons: hide-when-unconfigured is a small include in W4 if trivial, else deferred.
