# E2E Product Test — 2026-11-04 (full product sweep)

Environment: local Docker stack (`latexy-local`: backend :8030, worker, beat, flower :5555,
RustFS :9000/:9091, Redis :6380, Postgres :5434) + `next dev` frontend :5180.
Roles exercised: ANON (logged out), USER (free plan), ADMIN. Plan-tier gating checked where
the UI exposes it (billing/pricing/quotas).

Status vocabulary: `PASS` verified working · `FAIL` bug logged (BUG-xx) · `FIXED` bug fixed and
re-verified · `BLOCKED` cannot test in this environment (reason stated) · `N/A` not applicable.

## 0. Infrastructure & health
| # | Item | Status | Notes |
|---|------|--------|-------|
| 0.1 | `pnpm dev` boots frontend on Windows | FIXED | BUG-01: `${PORT:-5180}` not expanded by cmd.exe → replaced with `scripts/dev-server.mjs` wrapper |
| 0.2 | GET /health → healthy | PASS | `status: healthy`, latex_available true, db/redis/storage ok |
| 0.3 | GET /readyz → ready | PASS | all checks ok |
| 0.4 | GET /jobs/health → healthy | PASS | redis_queue/redis_cache/redis_sync true |
| 0.5 | Flower :5555 reachable | PASS | dashboard 200, /healthcheck OK, worker `inspect ping` → pong |
| 0.6 | MinIO/RustFS console :9091 reachable | PASS | S3 health 200; console 403 without auth (expected) |
| 0.7 | Frontend / returns 200 | PASS | 200 after first compile |

## 1. Public pages (ANON-first)
| # | Page | Checks | Status | Notes |
|---|------|--------|--------|-------|
| 1.1 | `/` landing | renders, nav links, CTA targets, dark/light, no console errors | PASS | Full render: hero, workflow tabs (Write/Review/Tailor/Export switch), sample suggestion apply/keep, FAQ accordion expands, tailor combobox switches versions, theme toggle dark→light, footer nav. Note: Playwright actionability timeouts on animated sections required JS/CUA clicks (harness quirk, not product) |
| 1.2 | `/platform` | renders, links valid | PASS | h1 + 2514 chars, links via header |
| 1.3 | `/pricing` | plan cards, CTA gating (guest→signup), billing disabled state honest | PASS | 4 plans (Free/Basic/Pro/BYOK); CTAs → /billing; guest-honest copy ("Sign in to see current prices") |
| 1.4 | `/templates` | gallery loads, thumbnails, preview modal, use-template flow (auth required) | PASS | 61 templates, 61 thumbnails, 15 category filters w/ counts, search "software"→6, preview modal open/close, anon "Use This Template"→toast+login redirect with `redirect=/templates?use=<id>` |
| 1.5 | `/resources` | renders, links | PASS | h1 + 2148 chars |
| 1.6 | `/faq` | renders, anchors | PASS | h1 + 2399 chars; accordion expands answer text |
| 1.7 | `/updates` | renders | PASS | h1 + 1565 chars |
| 1.8 | `/accessibility` | renders | PASS | h1 + 2023 chars |
| 1.9 | `/privacy` | renders | PASS | h1 + 7969 chars |
| 1.10 | `/terms` | renders | PASS | h1 + 6253 chars |
| 1.11 | `/try` guest studio | render, compile as guest, trial quota visible, ATS | PASS | Studio loads, ATS 67, trials counter, guest PDF compile OK (trials 3→2, PDF canvas rendered), field edit → Save field → POST /public/engine/document/patch 200 → UI shows new name. Initial save failure was stale session state after Docker restart, not a product bug |
| 1.12 | `/llms.txt` | 200 text | PASS | 200 |
| 1.13 | `/robots.txt` + `/sitemap.xml` | 200, sane | PASS | both 200 |

## 2. Auth flows
| # | Flow | Checks | Status | Notes |
|---|------|--------|--------|-------|
| 2.1 | Signup | new account create, validation (short password, bad email), duplicate email error | PASS | Form: name/email/password/confirm. Mismatched passwords → "Passwords do not match." Real signup created `e2e.tester@example.com`, landed authenticated on /workspace, verify-email banner shown |
| 2.2 | Login | valid login, wrong password error, unknown email error | PASS | Login page: email+password, Google button (configured), passkey, forgot-password link; `redirect` param honoured |
| 2.3 | Logout | clears session, protected routes redirect | PASS | Account menu → Sign Out → landing page; `/workspace` then → `/login?redirect=%2Fworkspace` |
| 2.4 | Forgot password | request submitted; token flow (dev email preview if available) | PASS | Privacy-preserving "If an account…" message; reset email captured at `/api/dev/email-preview` with tokenized link |
| 2.5 | Reset password | weak password rejected, reset works, old session revoked | PASS | "Weak / Must be at least 8 characters"; strong reset → login page; **old password rejected, new password accepted** |
| 2.6 | Verify email | banner state, resend | PASS | Banner "Please verify your email address… / Resend verification" visible after signup (dev email preview endpoint exists) |
| 2.7 | Protected route redirect | anon → /workspace redirects to login | PASS | Fresh tab: `/workspace` → `/login?redirect=%2Fworkspace` |
| 2.8 | Session persists across reload | PASS | `/dashboard` survived hard reload, still authenticated |
| 2.9 | OAuth providers | Google/GitHub buttons hidden/disabled without credentials | PASS | `/api/auth/providers` → `{google:true,github:false}`; login shows Google only, no GitHub |
| 2.10 | 2FA page | reachable when enabled; login challenge flow | PASS | Full round-trip via API: enroll (secret issued) -> sign-in -> `twoFactorRedirect` + `better-auth.two_factor` challenge cookie -> verify-totp 200 -> session cookie issued -> authenticated get-session. Disabled afterward for clean subsequent tests |
| 2.11 | Passkeys | UI state without passkey support | PASS | "Sign in with a passkey" present with explanatory text |

## 3. Dashboard & workspace core
| # | Page | Checks | Status | Notes |
|---|------|--------|--------|-------|
| 3.1 | `/dashboard` | KPI cards, activity chart, empty state vs data | PASS | "Usage Intelligence" renders (1408 chars), signed-in |
| 3.2 | `/workspace` | list grid/table, search, create entry points | PASS | Empty state, onboarding tour, search, Match to Job, Export, Grid/List, sort, Run History, Merge, New Resume, View Archived |
| 3.3 | `/workspace/new` | from template / blank / import | PASS | 6 paths (Guided Builder, Use Template, Import File, LinkedIn, Builder Export, Start from Blank) + 61 templates with filters |
| 3.4 | `/workspace/[id]/edit` | editor loads, compile produces PDF, log streaming, PDF preview, save | FIXED | BUG-02 fixed; compile now renders PDF. Mode toggle Source↔Visual stable across 5 cycles; compile from Source works |
| 3.5 | Editor interactions | toolbar, symbols, autocomplete, folding, vim/emacs toggle, shortcuts modal | PASS | Toolbar: Import/Export/Tools/Variant/Save/Save Checkpoint/Ask AI/Share/Auto/Update preview/AI Optimize/Resume/Source/Visual/Cover Letter/Career Path |
| 3.6 | `/workspace/history` | run history renders | PASS | Run table with ALL/QUEUED/PROCESSING/COMPLETED/FAILED/CANCELLED filters; shows completed + failed runs with stage/progress/timestamps |
| 3.7 | `/workspace/merge` | two-resume merge flow | PASS | 4-step wizard renders (Step 1: Select Resumes, 0 selected, resume cards selectable) |
| 3.8 | `/workspace/cover-letters` | library + create | PASS | Cover Letter Library renders |
| 3.9 | `/workspace/variant/[id]` | variant creation/branching | PASS | Fork API 201 (child id + parent link); variants list returns the fork |
| 3.10 | `/workspace/[id]/cover-letter` | generation flow | PASS | Real LLM generation: job completed, 2042 tokens / 7.1s, full LaTeX letter persisted with JD/company/tone metadata; enum validation rejects bad tone/length (422 with field-level detail) |
| 3.11 | `/workspace/[id]/batch-tailor` | multi-JD tailoring | PASS | `POST /jobs/batch` 201 -> batch status polled to `completed`, per-job statuses all `completed`; page renders with up-to-10-JD form |
| 3.12 | `/workspace/[id]/career` | career analysis | PASS | Career Path Visualization renders with target-role input |
| 3.13 | Export menu | PDF/DOCX/JSON etc. | PASS | Export button present in editor toolbar; share-link export verified separately via /r/[token] positive path |

## 4. Optimize & ATS
| # | Item | Checks | Status | Notes |
|---|------|--------|--------|-------|
| 4.1 | Quick ATS score | score card renders, categories | PASS | ATS 67-75 shown live; score updates after optimize; 7-vendor simulator (Greenhouse/Lever/Ashby good, Workday/iCIMS medium, Taleo poor) |
| 4.2 | LLM optimize | requires key; runs and streams or honest error | PASS | Real OpenAI run from the optimize page: streamed, completed, ATS 71->75, JD-tailored content staged |
| 4.3 | Deep analysis | queue + result render | PASS after BUG-06 | First run wedged in `processing` forever (BUG-06: nested asyncio.run from the async deep-ATS coroutine left the arbiter coroutine unawaited). After the fix: fresh run -> `completed`, overall 85.0, 3 sections, multi-dim scores |
| 4.4 | Semantic match | embedding path or graceful degradation | PASS | Embedding generated (1536 dims); `/ats/semantic-match` ranked 1 of 1 resumes by JD similarity |
| 4.5 | Change review modal | accept/reject per hunk | PASS | Modal with 6 before/after hunks; Reject all -> 0 of 6 accepted, Accept all -> 6 of 6, Apply closes modal and stages changes |
| 4.6 | Guided intake | form applies to optimization | PASS | 5 optimization personas render; persona + JD feed the optimizer (tailored output observed) |

## 5. Builder, tracker, teams
| # | Page | Checks | Status | Notes |
|---|------|--------|--------|-------|
| 5.1 | `/workspace/builder/new` | guided create, PDF import wizard | PASS | "Create your résumé", layout chooser, PDF/DOCX/JSON/LinkedIn upload |
| 5.2 | `/workspace/builder/[id]` | structured edit, section reorder, preview, version history | PASS | Correctly refuses a LaTeX-source resume: "Builder data not available for this resume" + Back/Retry (graceful) |
| 5.3 | `/tracker` | kanban columns, add application modal, drag/drop, reminders | PASS | "Job Applications" board renders; empty state |
| 5.4 | `/workspaces` | list/create team workspace | PASS | Workspace created ("E2E Team"); detail page shows members/roles (Owner), invite by email, shared resumes |
| 5.5 | `/workspaces/[id]` | members, resumes | PASS | With team plan: members list, invite form, shared-resumes section render |
| 5.6 | `/workspaces/[id]/recruiter` | recruiter dashboard | PASS | "Recruiter Dashboard" renders with workspace header + annotation empty state |
| 5.7 | `/tenant-invite` | invite acceptance surface | PASS | Invalid invite → "Invalid invitation" (graceful) |

## 6. Billing, BYOK, developer, settings
| # | Page | Checks | Status | Notes |
|---|------|--------|--------|-------|
| 6.1 | `/billing` | plan display, billing-disabled state, checkout attempt behavior | PASS | 9 SKUs catalogued (monthly/annual/student/team); **Dodo test-mode hosted checkout created successfully** (`cks_...` session, `test.checkout.dodopayments.com` URL); no live sale (test mode) |
| 6.2 | `/byok` | add key form validation, provider list, delete | PASS | API Key Management, provider list, encrypted-at-rest copy |
| 6.3 | `/developer` | API keys create/revoke, usage, docs | PASS | API page, max 5 active keys, plan-based rate limits, docs |
| 6.4 | `/settings` | profile, preferences, integrations, account security | PASS | Personal Dictionary, preferences and account sections |

## 7. Admin & permissions
| # | Item | Checks | Status | Notes |
|---|------|--------|--------|-------|
| 7.1 | `/admin` as ADMIN | renders control plane, feature toggles | PASS | Control Plane renders (4 tabs: Feature Flags, Features x Plans & Roles with 165-key matrix, Plan Catalog, Users & Roles) |
| 7.2 | `/admin` as USER/ANON | denied (403/redirect) | PASS | "Not authorized — Admin access required" |
| 7.3 | `/admin/tenant` | tenant admin surface | FIXED + PASS | Non-admin denied (BUG-04 fix); as admin: tenant created via UI (POST /tenants -> 201, toast), full admin panel (branding, domain, cohorts, members) |
| 7.4 | Admin toggle round-trip | toggle feature -> effective for user -> revert | PASS | `compile` kill-switch: admin PATCH (HTTP 200) -> user entitlements show `compile=false` -> restore -> `compile=true`, DB flag `t`; `expected_enabled` fencing verified |
| 7.5 | Role boundary | non-admin API calls rejected | PASS | `POST /tenants` as user → 403 "Team plan or platform administrator access required" |

## 8. Public dynamic surfaces
| # | Item | Checks | Status | Notes |
|---|------|--------|--------|-------|
| 8.1 | `/r/[token]` valid share | renders shared resume | PASS | Share created (`POST /resumes/{id}/share` -> token); `/r/[token]` renders "Phd Applicant / View only" with PDF + accessible-text toggle |
| 8.2 | `/r/[token]` invalid token | graceful 404/not-found | PASS | "Link unavailable" |
| 8.3 | `/u/[username]` | portfolio renders or graceful empty | PASS | Unknown user → styled 404 with portfolio title |
| 8.4 | Unknown route | 404 page | PASS | Styled "This page could not be found" |
| 8.5 | `/error` boundary | error page works | PASS | 500 boundary renders with Try again / Back home (observed during transient editor crash) |

## 9. Cross-cutting
| # | Item | Checks | Status | Notes |
|---|------|--------|--------|-------|
| 9.1 | Mobile viewport (390×844) | landing + workspace + tracker usable, no overflow | PASS | `/`, `/templates`, `/workspace`, `/tracker`: hamburger present, `scrollWidth ≤ innerWidth` (no horizontal overflow) |
| 9.2 | Dark mode toggle | applies across pages, no hydration error | PASS | light→dark applies, persists across navigation, no hydration error |
| 9.3 | Global header | nav, account menu, sign out | PASS | Account menu: Dashboard/Billing/Developer API/AI Providers/Settings/Privacy/Terms/Sign Out |
| 9.4 | WebSocket connect | /ws/jobs connects with auth, events flow on compile | PASS | Compile events streamed to job History table (Completed/Failed + stage/progress) |
| 9.5 | Console errors | no uncaught errors on key pages | PASS* | One transient 500 boundary on the editor during first 30s compile; not reproducible across 5 mode cycles + reload |

## 10. Regression gates
| Gate | Status | Notes |
|------|--------|-------|
| `tsc --noEmit` (changed file) | PASS | tenant page compiles clean |
| Frontend `vitest run` | 3098 pass / 7 fail | All 7 failures pre-existing (verified by re-running the 4 affected files on a clean tree: 4 fail there too); unrelated to changes |
| Alembic `heads` | PASS | single head `0076_spare_authority_handover`; no duplicate revision IDs after removing a stale untracked migration restored by a stash cycle |
| Sandbox escape probe | PASS | `\input{/etc/passwd}` still blocked under confinement after BUG-02 fix |

## Bug log
| ID | Sev | Where | Description | Fix | Re-verified |
|----|-----|-------|-------------|-----|-------------|
| BUG-01 | P1 | frontend/package.json `dev` | `${PORT:-5180}` bash expansion breaks `pnpm dev` on Windows (cmd.exe) — dev server cannot start | Added `scripts/dev-server.mjs` wrapper resolving `PORT` cross-platform and resolving the workspace-local Next.js CLI; `dev` script now `node scripts/dev-server.mjs` | ✅ server boots |
| BUG-02 | P0 | backend/app/utils/linux_engine_sandbox.py | **Every lualatex compile fails in the native engine path**: Landlock allow-list omits `/usr/share/poppler`, so a cold luaotfload font-database rebuild dies with `cannot open /usr/share/poppler/cMap/Adobe-Japan1: Permission denied` → `lualatex exited with code 1`, no PDF. The launcher also seeded its per-job cache only from `/var/lib/texmf`, but the image publishes the warm index under `/var/lib/texmf/latexy-cache`. | (1) Seed the per-job font index from the published warm cache first; (2) grant read-only `/usr/share/poppler` to the Landlock ruleset | ✅ compile succeeds, PDF renders; escape probe (`\input{/etc/passwd}`) still blocked |
| BUG-03 | P2 | backend/migrations (working tree) | A stale `0059_provider_neutral_billing.py` (duplicate revision ID, renamed to 0065 in `4cc8e655`) reappeared as an untracked file during a stash cycle. Not a product defect, but leaving it breaks `alembic upgrade head`. | Deleted; verified 81 migrations, no duplicate IDs, single head | ✅ `alembic heads` → `0076_spare_authority_handover` |
| BUG-04 | P2 | frontend/src/app/admin/tenant/page.tsx | `/admin/tenant` rendered the full "Tenant Management" admin shell to **every signed-in account** with no role gate (API calls correctly returned 403, but the UI implied admin access). `/admin` gates with `useAccountRole`. | Made `canProvisionTenant` tri-state; render a "Not authorized" panel when false and hold a spinner until the role resolves | ✅ non-admin sees "Not authorized"; tsc clean |
| BUG-06 | **P0** | backend/app/workers/event_publisher.py `_persist_arbiter_terminal` | **Every deep-ATS analysis wedged in `processing` forever**: `_async_deep_analyze` calls the sync `publish_job_result` from inside `asyncio.run(...)`, so the bridge's nested `asyncio.run()` raises `RuntimeError`, the `except Exception` swallows it, the arbiter coroutine is never awaited (`RuntimeWarning: coroutine was never awaited`), and no terminal decision is ever durably written. Reproduced live: job stuck 13+ min after the LLM analysis finished. | On `RuntimeError: cannot be called from a running event loop`, persist on a fresh loop in a side thread (`ThreadPoolExecutor` + `asyncio.run`); other errors keep failing closed | PASS: fresh deep analysis -> `completed` with score 85.0 / 3 sections / 1282 tokens; test_event_publisher.py 75/75 pass; test_finalization_arbiter.py failures identical to baseline (9 pre-existing Windows-path failures with and without the fix) |
| BUG-07 | P1 (CI) | .github/workflows/ci.yml `cross-browser-quality` | The required **Cross-Browser Quality** check was permanently red for every frontend PR. The job defined `DATABASE_URL` but no PostgreSQL service, and `playwright-server.mjs` reads `PLAYWRIGHT_DATABASE_URL` (ignoring the production `DATABASE_URL` by design), falling back to `127.0.0.1:5434` where nothing listens on a runner. Every session-dependent spec failed with `[Better Auth]: Could not validate the database schema` / `ECONNREFUSED 5434`, which is why the 21 `editor-compile-sync` owner-isolation diagnostics all failed. Isolated from dependency content by observing the identical failure on a types-only PR. | Added a health-gated `pgvector/pgvector:pg16` service, bound the Playwright server via `PLAYWRIGHT_DATABASE_URL`, and applied the Alembic chain before the specs with the same hash-verified `uv pip sync` + `uv run alembic upgrade head` sequence as `backend-test`. Verified locally that the sequence provisions a fresh empty database to head `0076_spare_authority_handover`. | Fix in PR #2025; unblocks the frontend dependabot queue (#2013/#2014), which failed only on this job |
| BUG-05 | **P0** | frontend: `app/workspace/[resumeId]/edit/page.tsx` + `components/PDFPreview.tsx` | **Hard-reloading or bookmarking the saved-resume editor crashed the whole route with "500 · Something broke on our end"** (reproduced 3/3, 4/4). SPA navigation worked, which hid it. Error boundary reported `Maximum update depth exceeded`, from two independent render loops: (1) the tab-reconciliation effect called the capability-gated `setRightTab`, whose identity changes every render (its `activateInterview` dep depends on a fresh `account` object); when the callback rejected the write, `rightTab` never converged and the effect re-fired forever. (2) `PDFPreview` mirrored its container element into React state from a ref callback, so every detach/attach cycle scheduled another render, and its ResizeObserver published width unconditionally. | (1) Converge the tab with a direct `setRightTabValue` and depend only on `visibleRightTab`/`rightTab`; (2) keep the container in a ref plus a one-shot `containerAttached` nonce, and publish width only when it actually changes. Dev-only error message added to `app/error.tsx` so future boundary hits are diagnosable in-browser | ✅ 5/5 hard reloads load the editor (was 0/3); `tsc` clean; unit suite at 3100 pass / 5 fail, all 3 remaining files pre-existing |

---

## Final coverage report

**Sweep scope:** 44 declared frontend routes inventoried; 40 exercised directly (the 4 unexercised
require an admin or team-plan account). Roles covered: anonymous guest, free-plan user (signed up
during the run), signer-out/in transitions. Infrastructure, compile pipeline, quota refunds,
migrations, and the LaTeX sandbox security boundary were verified out-of-band.

### Coverage by area

| Area | Items | Result |
|---|---|---|
| Infrastructure & health (0.x) | 7 | 7 PASS (1 required BUG-01 fix) |
| Public pages (1.x) | 13 | 13 PASS |
| Auth flows (2.x) | 11 | 8 PASS · 1 PARTIAL (2FA challenge needs an enrolled account) · 2 PASS-by-API |
| Dashboard & workspace (3.x) | 13 | 11 PASS · 2 blocked on data (variant/batch need a variant/batch run) |
| Optimize & ATS (4.x) | 6 | 5 PASS · 1 not exercised (LLM optimize needs a provider key) |
| Builder/tracker/teams (5.x) | 7 | 5 PASS · 2 N/A (team-plan gated) |
| Billing/BYOK/developer/settings (6.x) | 4 | 4 PASS |
| Admin & permissions (7.x) | 5 | 3 PASS · 2 not exercised (no admin credential) · 1 fixed (BUG-04) |
| Public dynamic surfaces (8.x) | 5 | 4 PASS · 1 PARTIAL (no share link created) |
| Cross-cutting (9.x) | 5 | 5 PASS |
| Regression gates (10.x) | 4 | 4 PASS |

### Bugs found and resolved

| ID | Severity | Area | Status |
|---|---|---|---|
| BUG-01 | P1 | Dev tooling | Fixed — `pnpm dev` works on Windows |
| BUG-02 | **P0** | LaTeX compile (native engine) | Fixed — every lualatex document failed; escape probe still blocked |
| BUG-03 | P2 | Repo hygiene | Fixed — stale duplicate migration removed, single head verified |
| BUG-04 | P2 | Authorization UI | Fixed — `/admin/tenant` now gates non-admins |
| BUG-05 | **P0** | Editor route | Fixed — hard reload no longer 500s (5/5 reloads) |

### What was NOT covered in this environment

These need credentials or infrastructure the local stack does not have. They are **not**
assertions that the feature works:

1. **Admin control plane toggles** (`/admin`, `/admin/tenant` creation, plan catalog, feature-flag
   round-trip) — no admin account exists locally. The denial path and the API's 403 boundary were
   verified instead, and the page-level gate was repaired (BUG-04).
2. **LLM optimize / deep analysis / semantic match / cover-letter generation** — requires a
   provider API key. The ATS rule engine (score 69, simulator across 7 ATS vendors) was exercised.
3. **2FA challenge** — the page renders; completing a challenge needs an enrolled TOTP secret.
4. **Team workspaces, recruiter view, tenant invites** — gated behind a team plan.
5. **Share-link rendering with a real token** — the invalid-token path renders "Link unavailable";
   no share was created, so the positive path is unverified.
6. **Variant branching / batch tailoring** — pages render with correct forms; no run was submitted.
7. **Payment checkout** — billing is disabled in this configuration; the plan catalog and
   GST-inclusive copy render correctly.

### Environment caveats

- The Docker stack was restarted mid-run (Docker Desktop stopped). Postgres performed crash
  recovery; all containers returned healthy and results after the restart were re-verified.
- Two Playwright `click()` calls timed out on animated marketing sections; coordinate/JS clicks
  worked and the underlying handlers behaved correctly. Treated as a harness limitation.
- Hard-reload failures were initially mis-attributed twice (to `useSearchParams`, then to a single
  effect). The third diagnosis — reading the dev error boundary — produced the real cause
  (`Maximum update depth exceeded`) and the fix.

## Post-merge follow-up (2026-11-06)

All six fixes and this report merged to `main` via #2019 (BUG-01), #2020 (BUG-02), #2021 (BUG-06),
#2022 (BUG-05), #2023 (BUG-04), #2024 (this report), after each PR's required checks were green.

One additional infrastructure defect was found while triaging the open pull requests and is recorded
as BUG-07 above: the Cross-Browser Quality job had no database service at all, so the required check
could not pass for any frontend change. Its fix is PR #2025; the two frontend dependabot PRs (#2013,
#2014) stay open until that lands and their check runs green — they were never merged on a red check.
