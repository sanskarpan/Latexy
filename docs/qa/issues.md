# Latexy — QA Audit Issue Register (historical snapshot)

> This file preserves the findings from the original August 2026 audit; it is not the live
> backlog. GitHub epic [#1621](https://github.com/sanskarpan/Latexy/issues/1621) and its linked
> issues are the current source of truth. Statuses below were reconciled on 2026-08-28.
>
> Environments: **prod** = latexy.xyz (Vercel) + Modal backend; **local** = dev.sh stack (backend :8030 / frontend :5180).
> Production test-account credentials must never be stored in the repository. Obtain
> short-lived QA access through the project owner or the approved secret manager, and
> rotate credentials after each audit window.

## Severity legend
- **P0 / Critical** — app unusable, major workflow fully broken, data-loss/security
- **P1 / High** — major functionality broken
- **P2 / Medium** — important, workaround exists
- **P3 / Low** — minor UI/UX

## Summary (updated as audit progresses)
| Priority | Open | Fixed | Total |
|---|---|---|---|
| P0 | 1 | 0 | 1 |
| P1 | 0 | 0 | 0 |
| P2 | 0 | 2 | 2 |
| P3 | 0 | 2 | 2 |

_ISSUE-001 recorded an external provider-credit failure and needs revalidation against the current
production secret/billing state. ISSUE-002–004 shipped in PR #1117. OBS-001 was resolved by
#1550/#1560 and the production sweep merged through PR #1572._

## Clean bill (verified NO issues)
- **Security:** no IDOR (cross-user resume/job access blocked), no auth bypass on protected endpoints, no admin privilege escalation, no weak `X-Admin-Secret` write, no plaintext BYOK key leak, public `references`/`config` endpoints leak nothing sensitive.
- **Rendering:** all 38 routes load; public routes 200 with zero console/network errors; authed pages render with correct empty states (dashboard, workspace+onboarding, billing, /try Studio [light Monaco], templates=147 items, byok).
- **Core flows (local, funded key):** compile→PDF, AI optimize (combined job → optimized_latex+ATS), ATS quick-score, tracker CRUD, BYOK CRUD, cover-letter — all work; unlimited plan → no 402.
- **Prod authed pages (paced):** /dashboard /workspace /tracker /billing /settings all 200, 0 errors. (Earlier sweep flags were 100% self-inflicted 429 rate-limit.)

---

## ISSUE-001 — AI features fail on prod (OpenAI credits exhausted)

- **Severity:** Critical
- **Priority:** P0
- **Area:** LLM optimization / AI (optimize, tailor, cover letter, deep analysis — any shared-key LLM feature)
- **Route:** `/try` (AI Optimize), plus any AI-backed endpoint; job_type `combined` / `llm`
- **Type:** Infrastructure / Configuration (external integration)
- **Status:** Needs revalidation (external provider billing/secret state)

### Description
Every LLM-backed feature that uses the platform's shared OpenAI key fails on production. Compile (no LLM) and ATS quick-score (local scoring) are unaffected.

### Steps to Reproduce
1. Log in on prod with an approved, short-lived QA account.
2. `POST /jobs/submit` with `job_type=combined` (or use /try → AI Optimize).
3. Poll `/jobs/{id}/state` → `status=failed, stage=llm_optimization`.

### Expected Behavior
LLM stage returns optimized LaTeX + changes; job completes with PDF + ATS score.

### Actual Behavior
Job fails at `llm_optimization`. Modal worker log:
```
openai.RateLimitError: Error code: 429 —
'You have no credits remaining. Add credits to continue using the API...'
type: insufficient_quota, code: credit_balance_exhausted
  at backend/app/workers/orchestrator.py:162 → _run_llm_stage:432 → openai chat.completions.create
```

### Root Cause
The OpenAI account behind the prod `OPENAI_API_KEY` (Modal secret `latexy-backend-secrets`) has zero credits. Not a code defect — the `openai` client (v2.51) correctly surfaces the provider 429.

### Dependencies
None (root issue). Blocks verification of all AI journeys on prod.

### Proposed Fix
One of: (a) add credits / rotate `OPENAI_API_KEY` to a funded key + redeploy; (b) switch default provider to a funded `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` / `GEMINI_API_KEY` (all supported via `llm_provider_service.py`); (c) rely on BYOK per-user keys. Requires user's billing access.

### Verification
Re-run `job_type=combined` with the approved QA account → job completes with optimized_latex + ATS score.

### Regression Risk
Low (config change). If switching provider, verify model/prompt compatibility.

---
## ISSUE-002 — `PUT /resumes/{id}` with non-UUID id returns 500

- **Severity:** Medium — **Priority:** P2 — **Area:** Resume CRUD — **Route:** `PUT /resumes/{resume_id}`
- **Type:** Validation / Runtime — **Status:** Deployed (PR #1117, merged 2026-08-09)
- **Dependencies:** shared root cause with ISSUE-003.
- **Fix:** `UUID()` guard added to `update_resume` (resume_routes.py). **Verified:** Yes (404). **Regression Tested:** Yes (test_qa_audit_fixes.py).

### Steps to Reproduce
`curl -X PUT http://localhost:8031/resumes/not-a-uuid -H 'Authorization: Bearer <pro>' -H 'Content-Type: application/json' -d '{"title":"x"}'` → 500 (reproduced 3/3). A random valid-format UUID correctly returns 404.

### Expected / Actual
Expected 404 (consistent with GET) or 422. Actual: **HTTP 500** `{"error":{"code":"internal_error"}}`.

### Root Cause
`update_resume` (`backend/app/api/resume_routes.py:804-818`) runs `select(Resume).where(Resume.id == resume_id, ...)` with the raw string; a non-UUID reaches Postgres → asyncpg `DataError` → unhandled 500. The GET route (`:787-790`) has a `try: UUID(...) except: 404` guard that PUT/DELETE lack.

### Proposed Fix
Add the same UUID guard to `update_resume` (and `delete_resume`, `update_resume_settings`). Regression test asserting 404 for non-UUID.

### Verification
`PUT /resumes/not-a-uuid` → 404; owned resume update still 200.

---

## ISSUE-003 — `DELETE /resumes/{id}` with non-UUID id returns 500

- **Severity:** Medium — **Priority:** P2 — **Area:** Resume CRUD — **Route:** `DELETE /resumes/{resume_id}`
- **Type:** Validation / Runtime — **Status:** Deployed (PR #1117, merged 2026-08-09)
- **Dependencies:** same root cause as ISSUE-002.
- **Fix:** `UUID()` guard added to `delete_resume` + `update_resume_settings`. **Verified:** Yes (404). **Regression Tested:** Yes.

### Steps to Reproduce
`curl -X DELETE http://localhost:8031/resumes/not-a-uuid -H 'Authorization: Bearer <pro>'` → 500 (3/3). Random valid UUID → 404; owned resume → 204.

### Expected / Actual
Expected 404/422. Actual **HTTP 500**.

### Root Cause
`delete_resume` (`:856-867`) runs `delete(Resume).where(Resume.id == resume_id, ...)` with no UUID guard → asyncpg `DataError` → 500.

### Proposed Fix / Verification
Same UUID guard; test asserts 404 for non-UUID and 204 for owned delete.

---

## ISSUE-004 — `POST /ats/recommendations` accepts out-of-range `ats_score`

- **Severity:** Low — **Priority:** P3 — **Area:** ATS — **Route:** `POST /ats/recommendations`
- **Type:** Input validation gap — **Status:** Deployed (PR #1117, merged 2026-08-09)
- **Fix:** `Field(ge=0, le=100)` on `ats_score`. **Verified:** Yes (422 out-of-range / 200 valid). **Regression Tested:** Yes.

### Steps to Reproduce
`{"ats_score":1e308,"category_scores":{}}` → 200 with `estimated_score_improvement=-6.99e+307`; `Infinity` → 200 `improvement=null`; `-500` → 200. String value correctly 422s.

### Expected / Actual
Expected: `ats_score` bounded to 0–100 → 422 (or clamped). Actual: no numeric bounds → nonsensical `estimated_score_improvement`.

### Root Cause
Request model field `ats_score` lacks `ge=0, le=100` (and no clamp before computing improvement).

### Proposed Fix / Verification
Add `Field(ge=0, le=100)` to the ats_score field (or clamp). Test asserts 422 for out-of-range.

---
<!-- New issues appended below by the audit. -->

## OBS-001 — 429 on `/api/auth/get-session` degraded to silent logged-out/blank

- **Severity:** Low — **Priority:** P3 (resilience observation) — **Area:** Auth/resilience — **Status:** Deployed
- Under rate-limiting, a 429 on the Better Auth session probe made the app treat the user as logged
  out. Issue #1550 introduced the shared `useRequireAuth` behavior and rate-limit bucket hardening;
  issue #1560 preserved the last confirmed session in `GlobalHeader` during transient failures.
  The focused fixes landed in PRs #1561 and #1571 and were integrated to production by PR #1572.
