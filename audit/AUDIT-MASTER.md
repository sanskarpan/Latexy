# Latexy production audit - master report

**Date:** 2026-11-27
**Audit branch:** `audit/production-2026-11-27`, based on `main` `d2cbc51ab8c25106d073e0e0065b985fc6dc6490`
**Production backend:** `ee1a405de6058e814c3a6f5ffba5fe3630576421`, Modal `ap-IB2XwK8MjL2xmeI7wOUyEZ`
**Production DB:** `neondb`, migration head `0109_error_alerts`
**Frontend:** `d2cbc51a` (docs-only ahead of the deployed runtime `ee1a405d`)
**Windows:** 2026-11-27T10:33:28Z identity provisioning; 10:41-11:50Z live probes, journeys, events, load and cleanup.

## Verdict

Core user journeys are broadly functional, but the baseline is **not launch-clean**.

- **1 P0:** BYOK OpenAI keys are routed to the platform's non-OpenAI `OPENAI_BASE_URL` instead of `api.openai.com` (credential disclosure plus broken BYOK).
- **12 P1s:** optimization fails; auth rate limiting is one global bucket; Yjs history is truncated; job recovery can take ~70 minutes; email delivery/ledger disagree; analytics paid/MRR/compile-source definitions are wrong; Free gets every gateable capability at the entitlement layer.
- **58 P2s and 32 P3s** cover trial/past-due display, cancellation exactly-once, collab chat latency, replay contracts, queue observability, retention/trial controls and dead surfaces.
- **Entitlements:** live export gives 165/165 features to Free, Pro, admin and anonymous. The resolver and matrix work (proven by a controlled flip), but the configured matrix is effectively all-on; paid plans differ mainly by quotas and seats.
- **Observability:** live OpenAPI/docs are disabled; queue health is blind to Modal spawn backlog; the daily metrics rollup is never populated; analytics cannot exclude audit traffic.

Detailed defects: [`defects.md`](defects.md) - **1 P0, 15 P1, 58 P2, 32 P3**.

## Method

1. Recomputed inventories from source at the deployed SHA and the source-generated OpenAPI (636 operations / 558 paths), then diffed against 674 registered operations / 588 paths (38 hidden).
2. Reconciled live production: `/health`, `/readyz`, `/jobs/health`, deployment identity, DB head, GitHub, provider telemetry.
3. Provisioned 16 synthetic users plus one anonymous device trial covering free, basic monthly/annual, pro monthly/annual, BYOK, student, trial active/expired, past due, cancelled, team owner/member, support/admin, developer API (`audit/plans/identity-matrix.json`; tokens redacted before merge).
4. Ran per-cohort journeys with low request rates, read-only HTTP sweeps, 75 WebSocket observations, 35 admin analytics reconciliations, failure/quota/tenant probes, and a bounded compile load test (simple/complex 1/5/10 concurrency; hard ceiling 38).
5. Executed one controlled global entitlement mutation (kill switch + free-plan matrix) and restored the exact pre-test state; every mutation is in [`changes/production-changes.md`](changes/production-changes.md).
6. Deleted every audit identity/artifact or listed it with an owner in [`cleanup.md`](cleanup.md); verification in [`cleanup-verification.md`](cleanup-verification.md).

## Coverage

| Surface | Source count | Evidence | Status |
|---|---|---|---|
| HTTP operations | 636 OpenAPI; 674 registered (38 hidden) | 212 tested, 424 blocked with reason; every op dispositioned in `inventory/http-disposition.csv`; summary `http-disposition-summary.md` | complete with named gaps |
| WebSocket paths / protocol rows | 2 / 41 | 75 live observations `events/ws-observations.csv`; report `events/ws-audit.md` | complete |
| Modal functions / schedules | 30 / 5 | `inventory/workers.csv`, `workers-events.md` | inventory complete |
| Celery queues / beat | 6 / 11 | 0 consumers; 1 orphaned beat entry | complete |
| Plans / SKUs | 5 families / 11 configured + team_member | `inventory/plans.csv`, `plans-capabilities.md` | complete |
| Capabilities | 129 product IDs; 165 registry; 149 gateable | `inventory/capabilities.csv`, live 165/165 export | complete |
| Admin analytics | 35 GET `/admin/analytics/*` + 84 surfaces | `analytics/reconciliation.md`, `inventory/analytics-surfaces.md` | complete |
| Frontend pages | 44 App Router pages, 22 admin tabs, 12 route handlers | `inventory/frontend-routes.csv` | complete |
| Integrations | 19 providers | `inventory/integrations.csv` | complete |
| Templates | 61 live / 61 source | `inventory/coverage-diff.md` | complete |
| Cohorts | 16 users + device trial | free/basic, pro/BYOK/developer, student/team/trial, auth/GDPR, admin | complete |

## Cohort outcomes

| Cohort | Verdict | Report |
|---|---|---|
| Free, Basic monthly/annual | Core journeys PASS; quotas/refunds correct; CAP-01/RET-01/FB-03/FB-04 | `plans/free-basic.md` |
| Pro monthly/annual, BYOK, Developer API | Unlimited paths and developer key lifecycle PASS; PB-D03 (P0), PB-D01 (P1), PB-D02/D04/D05/D06 | `plans/pro-byok-developer.md` |
| Student, team, trial, past due, cancelled | Seats/tenant isolation/grace PASS; ST-D01/D02/D03 (P2), ST-D04-D07 (P3) | `plans/student-team-trial.md` |
| Auth, account, GDPR | Signup/login/reset/2FA/export/deletion/legal hold PASS; AAG-D01 (P1) rate limit, AAG-D02-D05 | `plans/auth-account-gdpr.md` |
| Admin analytics | 35/35 endpoints 200; SQL counts reconcile; 19 AN findings | `analytics/reconciliation.md`, `plans/admin.md` |
| WebSocket jobs/collab | Normal path, replay, isolation PASS; cancellation/replay/chat defects | `events/ws-audit.md` |

## Latency

Client-observed read endpoints (30 samples each, audit workstation IST/UTC+5:30; backend us-east-1):

| Endpoint | p50 | p95 | p99 | Notes |
|---|---:|---:|---:|---|
| `/health` | 1.19 s | 2.93 s | 4.10 s | ~1.2 s network/edge floor |
| `/readyz` | 1.18 s | 1.24 s | 3.35 s | floor, not app work |
| `/jobs/health` | 3.55 s | 4.56 s | 4.77 s | six empty Celery queues |
| `/me` | 1.17 s | 1.21 s | 1.21 s | floor |
| `/config/entitlements` | 1.86 s | 2.33 s | 2.73 s | one 17.65 s outlier |
| `/subscription/current` | 1.28 s | 3.45 s | 3.62 s | |
| `/resumes` | 2.33 s | 3.22 s | 23.37 s | p99 outlier |
| `/resumes/builder/templates` | 1.29 s | 1.57 s | 2.14 s | |
| `/analytics/admin/overview` | 1.41 s | 3.80 s | 4.15 s | |
| `/admin/plan-catalog` | 23.05 s (single) | - | - | 92 KB, constants |

Compile stage baseline (warm single 1-page, n=5): queue/acquisition **1.35 s**, pdflatex **9.16 s**, storage/finalize **6.80 s**, total **20.73 s** p50 / **35.61 s** p95. Under load: simple-5 **39.91 s** p50 / 62.65 s p95; simple-10 **30.18 s** p50 / 45.72 s p95; complex-1 27.76 s; complex-5 42.86 s; complex-10 42.17 s p50 / 51.88 s p95. All 38/38 completed, zero 5xx. Full detail: `latency/endpoints.csv`, `latency/compile-stages.md`, `latency/load-test.md`, `latency/cost.md`, `latency/cost-estimate.md`, `latency/lead-compile-stages.md`.

## Analytics

- 35/35 `GET /admin/analytics/*` returned 200 with the admin token; daily-metrics 30-day series matched SQL exactly.
- P1 source-truth defects: direct `/compile` writes no compilation/event; "paid" is inferred from subscription status with 0 payments; MRR/upgrades read an empty `subscription_history`.
- P2: no test-cohort exclusion, timezone windows differ by up to 13 h, template attribution is 100% NULL, the daily rollup is never populated, and the overview realtime counters are zero.
- Suppression: primary `<5` fields are suppressed correctly; reconciliation blocks republish exact suppressed counts.

## Safety and restore

- No live charges, provider callbacks or deploys.
- One controlled global pass: `d25` kill switch and free-plan `d25` matrix were flipped, observed, and restored. Final `GET /admin/entitlements` SHA-256 `b2b63b36…` is **identical** to the pre-test snapshot. See `changes/production-changes.md`.
- Audit identities use `audit+…@example.test`; sessions, keys, tenants, subscriptions, compilations and usage rows were deleted; Redis jobs expire in 24 h; R2 artifacts are listed.

## Gates

1. Inventory/reconciliation - **complete**. 636/636 dispositions; 38 hidden ops diffed.
2. Identity provisioning - **complete**.
3. Journeys/latency/events - **complete** for all cohorts; performance/reliability/security reports included.
4. Global mutation - **complete with byte-exact restore**.
5. Analytics reconciliation - **complete**.
6. Independent cross-check - **complete** (`cross-check/cross-check.md`; coverage auditor independently recomputed the surface). Five defect claims re-tested: 4 confirmed, 1 confirmed structurally with the denial state unverifiable read-only. One disposition row was wrong (pro vs admin on `/analytics/admin/overview`) and is fixed.
7. Baseline sign-off - **functional baseline signed off with exceptions; latency baseline is screening-grade, not SLO-grade**. Launch is blocked by PB-D03, PB-D01 and AAG-D01; CAP-01 requires a product decision before pricing launch.


## Front-end page audit (follow-up wave)

All **44 App Router pages** were loaded in production at 1440x900 and 390x844 with anonymous/free/pro/admin/team roles. Evidence: `audit/frontend/AUDIT.md`, `page-inventory.csv`, 44 `report.json` files, desktop/mobile screenshots and the builder journey.

**14 front-end defects** are tracked in `audit/frontend/defects-frontend.md` and GitHub #2324-#2335, #2339, #2342. The critical ones:
- **FE-01 P1:** Optimize page can sit on a blank "Checking feature availability" spinner for 25s+ with no error.
- **FE-02 P1:** Imported/legacy LaTeX resumes have no coherent edit path (edit read-only, builder 404, variant 409, optimize spinner).
- **FE-03 P2:** Consent banner overlays sign-in, pricing and admin controls.
- **FE-04 P2:** Admin capability matrix is a 21,101px page with 930 toggles.
- **FE-05 P2:** Pricing page hides all prices while billing shows them.
- **FE-06 P2:** Dashboard says 3.5s compile latency vs the measured 20.7s, and 100% success despite failures.
- **FE-07 P2:** Builder/auth controls have no accessible names.
- **FE-08 P2:** Share page shows a generic "Link unavailable" after a successful compile.
- **FE-13 P2:** Cover-letter generation stays at "Generating…" for 45s with no logs/error.
- **FE-14 P2:** Guided-builder creation can sit at "Creating your résumé…" for ~30s.

The page-load and visual coverage is complete; full interaction coverage remains partial (template use, PDF/LinkedIn import, ATS simulator, tracker CRUD, team invite, billing checkout, admin mutations).

## Architecture review

`audit/architecture/latency-advisor.md` is the independent architecture plan. It identifies the two serialized finalization pipelines (fresh NullPool DB engines, serialized advisory locks, R2 HEAD checks, two pdftotext subprocesses) as the first code win, explicit LATEX CPU/memory as the first architecture win, and warm pool + admission control as a pair. Target: warm p50 <=12 s, 5-concurrent p50 <=25 s, finalize <=2 s. GitHub #2337 tracks the program; #2309/#2310 are the specific defects.

## Limitations

- Provider consoles (Dodo/Resend/PostHog/Drive/Dropbox/Zotero/Mendeley) were not all available; configuration is inferred from live telemetry, stored events and env presence.
- No valid third-party BYOK key was available, so successful BYOK generation/custom-model routing is blocked, not passed.
- Live OpenAPI/docs are disabled; all schema work uses source at the deployed SHA.
- 424/636 operations are blocked for named fixture/safety reasons; the 275 path-parameter rows need stable fixtures for a future per-ID sweep.
- The audit cohort contaminates production analytics; no dashboard can exclude it (AN-08/AS-01).
- Compile load is bounded (38 jobs); no destructive worker-kill or provider-outage test.
- Event-to-UI paint was not measured; event-to-client delivery was.
- The cross-check found `/resumes` is a 307 chain; the recorded 2,326 ms p50 is two calls, canonical `/resumes/` p50 is 1,508 ms. `/analytics/admin/overview` is cache-bimodal (hit 1,196 ms, miss 3,454-3,830 ms); the recorded p50 is a hit and p95 a miss.
- Warm/cold labels are unsupported: all latency samples are transport-cold and no cold-start sample is isolated. n=30 is a screening baseline, not an SLO sign-off; p95/p99 tails are not independently confirmed.
- The cross-check could not re-run the exact owner-A-vs-tenant-B isolation because tenant B was deleted; the 403-vs-404 oracle was re-confirmed with a non-member outsider.

## Deliverables

- [`executive-summary.md`](executive-summary.md)
- [`defects.md`](defects.md)
- [`inventory/`](inventory/) - seven inventories, coverage diff, HTTP disposition summary
- [`plans/`](plans/) - cohort reports
- [`latency/`](latency/) - endpoints, compile stages, load, cost
- [`events/`](events/) - WebSocket observations and report
- [`analytics/reconciliation.md`](analytics/reconciliation.md)
- [`changes/production-changes.md`](changes/production-changes.md)
- [`cleanup.md`](cleanup.md), [`cleanup-verification.md`](cleanup-verification.md)
- [`optimization-backlog.md`](optimization-backlog.md)
- [`cross-check/`](cross-check/)
- [`frontend/`](frontend/) - 44-page audit, screenshots, journeys, 14 defects
- [`architecture/latency-advisor.md`](architecture/latency-advisor.md)
- GitHub issue index #2341
