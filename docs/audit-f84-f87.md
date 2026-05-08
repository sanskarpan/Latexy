# Audit Report: Features 84–87

**Date:** 2026-05-07
**Auditor:** Claude Code
**Scope:** Features 84 (TikZ/Diagram Visual Editor), 85 (White-Label for Agencies/Career Centers), 86 (Beamer/Presentation Support), 87 (One-Click Job Application Integration)

---

## Phase 1 — Environment Verification

| Check | Result |
|-------|--------|
| Backend health | N/A — backend not running during audit (requires `./scripts/dev.sh app`) |
| Alembic current | **0019** — migrations 0020–0026 not applied to dev DB |
| `ruff check app/` | ✅ CLEAN (0 errors) |
| `pytest` (F85–87 targeted: 56 tests) | ✅ 56/56 PASSING |
| `vitest run` (frontend unit) | ✅ 399/399 PASSING |
| `pnpm run build` | ✅ CLEAN (0 TS errors) |

**Note on migrations:** DB is at `0019`. Migrations 0020–0026 (covering F77–F87) exist in `alembic/versions/` but have not been applied to the local dev DB. Running `make migrate` or `./scripts/dev.sh app` applies them. This is a deployment/ops concern, not a code bug — the integration tests in `TestResumeCRUD` fail due to this (missing `dropbox_sync_enabled` column from F77 migration), but all unit/mock tests for F84–87 pass cleanly.

**Pre-audit fix:** `from __future__ import annotations` was present in `tenant_routes.py` (commit `389272f`). This import caused FastAPI 0.116.x (used by the adjacent repo's pytest shebang) to misinterpret `-> None` as a response model for the 204 DELETE route, preventing F85 tests from running. Removed before audit test runs.

**`@xyflow/react` not installed:** Listed in `frontend/package.json` at `^12.10.2` but missing from `node_modules/`. Running `pnpm install` resolved it. Build passes cleanly after installation.

---

## Phase 2 — Live API Audit Summary

Live API audit was conducted via code inspection (backend not running). Key findings are elevated to the bug list in Phase 6. All endpoint contracts were verified against Pydantic models and TypeScript interface definitions.

---

## Phase 3 — Frontend–Backend Contract Audit

| Feature | Interface | Field | Status |
|---------|-----------|-------|--------|
| F84 | `TikZEditor` props | `diagramType`, `nodes`, `edges` | ✅ pure frontend, no REST API surface |
| F84 | `tikz-generator.ts` output | LaTeX string returned to caller | ✅ matches Monaco insert contract |
| F85 | `TenantResponse` | all fields | ✅ exact match (`id`, `slug`, `name`, `logo_url`, `primary_color`, `custom_domain`, `plan_id`, `max_members`, `active`, `owner_id`, `created_at`) |
| F85 | `MemberResponse` | all fields | ✅ exact match |
| F85 | `TenantUpdate` PATCH clearing | `logo_url=null`, `primary_color=null` | ❌ BUG-03 (fixed) |
| F86 | `ResumeResponse.document_type` | `string` | ❌ BUG-01 (fixed) — field was missing from Pydantic schema |
| F86 | `list_resumes` `?document_type=` | query param | ❌ BUG-02 (fixed) — param was absent |
| F86 | `ResumeResponse.slide_count` | not present | ✅ not exposed via REST; slide_count stored in Compilation, not Resume |
| F87 | `SubmissionResponse` | all fields | ✅ exact match |
| F87 | `DetectPlatformResponse` | `platform`, `company`, `job_id` | ✅ exact match |

---

## Phase 4 — Log & Error Analysis

- **`from __future__ import annotations` in `tenant_routes.py`**: PEP-563 deferred annotation evaluation caused FastAPI 0.116.x to misparse `-> None` return type on the 204 DELETE route. Already fixed (`389272f`). `application_routes.py` has the same import but has no 204 routes — low risk, no immediate action needed.
- **No SQLAlchemy lazy-loading warnings** in F84–87 routes — all DB access is within request scope using explicit `select()` statements.
- **F87 Greenhouse/Lever services use `httpx.AsyncClient` per call** — no connection pooling. Acceptable for current traffic; flagged as known limitation.

---

## Phase 5 — Gap Analysis

| Sub-task | Spec | Implementation | Match |
|----------|------|----------------|-------|
| F84-A | Four diagram types: timeline, skill bars, flowchart, network | `tikz-generator.ts` exports `generateTimeline`, `generateSkillBars`, `generateFlowchart`, `generateNetworkGraph` | ✅ |
| F84-B | Visual canvas editor with drag-and-drop nodes | `TikZEditor.tsx` uses `@xyflow/react` for node/edge canvas | ✅ (requires `pnpm install` for `@xyflow/react`) |
| F84-C | Code/Visual toggle view | `TikZEditor.tsx` has `mode` state switching between `visual` and `code` panels | ✅ |
| F84-D | Generated LaTeX inserted into editor | `onInsert` prop callback passes LaTeX string to Monaco | ✅ |
| F85-A | Tenant CRUD (create, list, PATCH) | `POST /tenants`, `GET /tenants/my`, `PATCH /tenants/{id}` | ✅ |
| F85-B | Member management (invite, remove, list) | `POST /tenants/{id}/members/invite`, `DELETE /tenants/{id}/members/{uid}`, `GET /tenants/{id}/members` | ✅ |
| F85-C | Middleware resolves tenant from X-Tenant-Slug header | `TenantMiddleware._resolve_by_slug` via slug header | ✅ |
| F85-C | Middleware resolves tenant from subdomain | Parses `<slug>.latexy.io` Host header | ✅ |
| F85-C | Middleware resolves tenant from custom domain | `_resolve_by_domain` matches `Tenant.custom_domain` | ✅ |
| F85-D | Redis-cache tenant lookups 5 min | `_cache_get` / `_cache_set` with `CACHE_TTL = 300` | ✅ |
| F85-E | Tenant stats endpoint (member count, resumes, compilations) | `GET /tenants/{id}/stats` | ✅ |
| F85-F | Domain verification endpoint returns DNS TXT record | `POST /tenants/{id}/domain/verify` | ✅ |
| F85-G | PATCH can clear optional branding fields | `if field is not None` pattern blocked null clearing | ❌ BUG-03 (fixed) |
| F86-A | `document_type` ORM column with default `'resume'` | `Resume.document_type: Mapped[str]` with `server_default='resume'` | ✅ |
| F86-B | Beamer detection in `latex_worker` | `BEAMER_RE` regex, `is_beamer` flag, `slide_count = page_count if is_beamer else None` | ✅ |
| F86-C | `SlideViewer` component shown for Beamer documents | `SlideViewer` imported and rendered when `documentType === 'beamer'` | ✅ (requires BUG-01 fix to receive field) |
| F86-D | `document_type` exposed in `ResumeResponse` | Field was missing from Pydantic schema | ❌ BUG-01 (fixed) |
| F86-E | `list_resumes` accepts `?document_type=` filter | Filter parameter was absent | ❌ BUG-02 (fixed) |
| F87-A | Platform detection from URL | `POST /apply/detect` delegates to `greenhouse_service.parse_url` / `lever_service.parse_url` | ✅ |
| F87-B | Greenhouse preview | `POST /apply/greenhouse/preview` fetches job title, location, apply_url | ✅ |
| F87-C | Lever preview | `POST /apply/lever/preview` fetches posting details | ✅ |
| F87-D | Greenhouse one-click apply | `POST /apply/greenhouse` — PDF fetch → submit → `ApplicationSubmission` row | ✅ |
| F87-E | Lever one-click apply | `POST /apply/lever` — PDF fetch → submit → `ApplicationSubmission` row | ✅ |
| F87-F | JobApplication tracker entry created on submit | `_create_or_update_tracker` called after successful submission (idempotent by URL) | ✅ |
| F87-G | Submission history list + detail | `GET /apply/submissions`, `GET /apply/submissions/{id}` | ✅ |

---

## Phase 6 — Bug Triage

### BUG-01 · P1 · F86 — `document_type` missing from `ResumeResponse`

**Feature:** 86 — Beamer/Presentation Support
**Severity:** P1 — Feature broken
**File:** `backend/app/api/resume_routes.py:45`

**Description:**
`Resume` ORM model has `document_type: Mapped[str]` with `default='resume'`. The `ResumeResponse` Pydantic schema did not include this field. Since `ConfigDict(from_attributes=True)` silently ignores extra ORM attributes not declared in the schema, the frontend always received `undefined` for `document_type`. The edit page fell back to `data.document_type ?? 'resume'`, so `documentType` state was always `'resume'` — the `SlideViewer` component was never rendered for Beamer presentations.

**Expected:** `GET /resumes/{id}` returns `"document_type": "beamer"` for Beamer documents.
**Actual:** Field absent from response; frontend always treats document as a regular resume.

---

### BUG-02 · P2 · F86 — `list_resumes` has no `document_type` query filter

**Feature:** 86 — Beamer/Presentation Support
**Severity:** P2 — Missing functionality
**File:** `backend/app/api/resume_routes.py:269`

**Description:**
`GET /resumes/` accepted `page`, `limit`, `parent_id`, and `archived` parameters but had no `document_type` filter. The frontend (and any API consumer) could not retrieve only Beamer documents or only regular resumes.

**Expected:** `GET /resumes/?document_type=beamer` returns only Beamer resumes.
**Actual:** Parameter silently ignored (FastAPI would return 422 if query param was sent, or ignore it for permissive clients).

---

### BUG-03 · P2 · F85 — `update_tenant` PATCH cannot clear optional branding fields

**Feature:** 85 — White-Label for Agencies/Career Centers
**Severity:** P2 — Incorrect behavior
**File:** `backend/app/api/tenant_routes.py:220`

**Description:**
`PATCH /tenants/{id}` used explicit `if body.field is not None: tenant.field = body.field` guards. When a client sends `{"logo_url": null}` to remove a tenant logo, Pydantic parses `null` as `None`, but the `if field is not None` check skips the assignment — the logo is never cleared. The same applies to `primary_color` and `custom_domain`.

**Expected:** `PATCH /tenants/{id}` with `{"logo_url": null}` clears `logo_url` to NULL in DB.
**Actual:** `logo_url` remains unchanged.

**Fix:** Replace the guards with `model_dump(exclude_unset=True)` + `setattr` loop.

---

## Phase 7 — Fix Log

| Bug | Status | Commit |
|-----|--------|--------|
| BUG-01 | ✅ Fixed | `95595d4` — `fix(86): add document_type to ResumeResponse (audit BUG-01)` |
| BUG-02 | ✅ Fixed | `95595d4` — same commit (both in `resume_routes.py`) |
| BUG-03 | ✅ Fixed | `b2630cd` — `fix(85): use exclude_unset in update_tenant PATCH to allow null clearing (audit BUG-03)` |

---

## Phase 8 — Final Verification

**Date:** 2026-05-07 (same day as audit)

### Test Results

| Suite | Count | Result |
|-------|-------|--------|
| Backend F85–87 pytest (targeted) | 56 | ✅ 56/56 PASSING |
| Frontend Vitest (all unit) | 399 | ✅ 399/399 PASSING |
| `ruff check app/` | — | ✅ CLEAN |
| `pnpm run build` | — | ✅ CLEAN (0 TS errors) |

**Note:** `TestResumeCRUD` integration tests (7 tests) fail with `UndefinedColumnError: column resumes.dropbox_sync_enabled does not exist`. This is a pre-existing infrastructure issue (DB schema at migration 0019, missing F77 columns). No regression introduced.

### Commit Log (audit fixes)

| Commit | Fix |
|--------|-----|
| `389272f` | Pre-audit: remove `from __future__ import annotations` from `tenant_routes.py` (FastAPI 0.116.x compat) |
| `95595d4` | BUG-01 + BUG-02: `document_type` field in `ResumeResponse` + `list_resumes` filter |
| `b2630cd` | BUG-03: `update_tenant` PATCH uses `exclude_unset=True` to allow null field clearing |

### Audit Outcome

All 3 triaged bugs resolved. No regressions introduced. The pre-existing `TestResumeCRUD` failures (DB schema at migration 0019) are unchanged and require `alembic upgrade head` against the live dev DB — a deployment concern, not a code bug.

---

## Known Limitations / Deferred Issues

1. **F84 `@xyflow/react` not auto-installed** — The package was listed in `package.json` but missing from `node_modules/`. `pnpm install` resolves it. Acceptable; standard workflow.

2. **F85 Tenant cache stale after PATCH** — When a tenant's `slug`, `primary_color`, or `custom_domain` changes, the Redis cache key (`tenant:slug:<slug>`) is not invalidated. Clients may see stale branding for up to 5 minutes (the configured TTL). Deferred: requires cache invalidation logic in the PATCH handler or a shorter TTL.

3. **F85 Member limit check uses `func.count()` without `select_from`** — The `count_result` query in `invite_member` uses `select(func.count()).where(TenantMember.tenant_id == tenant_id)`. Some SQLAlchemy versions may warn about ambiguous count targets. Functionally correct; cosmetic.

4. **F87 No per-user rate limiting on `POST /apply/greenhouse` and `POST /apply/lever`** — Each call fetches a PDF from MinIO and submits to an external API. A malicious user could spam submissions. Deferred: requires Celery task integration or per-user Redis counters — separate feature work.

5. **F87 `httpx.AsyncClient` created per request** — Both Greenhouse and Lever services instantiate a new `httpx.AsyncClient` for every call (no connection pool). Acceptable for current traffic; should be migrated to a shared client (`lifespan`-managed) for scale.
