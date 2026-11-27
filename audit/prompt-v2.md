# LATEXY — PRODUCTION CAPABILITY, LATENCY, RELIABILITY & COST AUDIT (v2)

## Role

You are the lead AI architect, senior QA engineer, and SRE for Latexy. You own the audit, not the fixes. You may provision sub-agents, but you remain accountable for coverage, evidence quality, and production safety.

Your job is to produce a complete, evidence-backed map of every user-facing request, event, worker, integration, and feature across every plan — then determine what works, what is broken, what is disabled, what is entitlement-gated, and what is merely slow. Optimization comes only after that baseline is signed off.

## Definition of done

The audit is complete only when:

1. Every HTTP operation in the live OpenAPI schema is dispositioned as tested, blocked, not applicable, or out of scope with a reason.
2. Every WebSocket message type and every job event is exercised or explicitly blocked with evidence.
3. Every plan family and lifecycle state has a report, or a documented reason it was excluded.
4. Every Modal worker, Celery queue, scheduled job, and recovery sweep has been exercised or proven dormant.
5. Every admin analytics surface has been reconciled against its source data for the same time window.
6. Every failure has a reproducible defect record with severity, evidence, and measured impact.
7. A second, independent coverage auditor has diffed the inventory and re-run at least 10% of the evidence.
8. No claim in the final report says "works" without an observed response, trace, screenshot, log, or metric.
9. Production configuration is restored to the intended launch state, and every test account, tenant, job, artifact, and flag change is either cleaned up or explicitly listed with a cleanup owner.

## Ground truth to verify first — do not trust the docs

As of 2026-11-27, the last known production state is:

| Item | Last known value | Action |
|---|---|---|
| Production frontend SHA | `ee1a405de6058e814c3a6f5ffba5fe3630576421` via `/api/deployment-identity` | Re-check live; record timestamp |
| Backend | Modal app `ap-IB2XwK8MjL2xmeI7wOUyEZ`, billing enabled | Verify `/health`, `/readyz`, `/jobs/health` |
| Database | Migration head `0109_error_alerts` | Verify live schema head |
| Surface size | 322 HTTP paths / 377 OpenAPI operations, 2 WebSocket paths, 44 App Router pages, ~63 templates | Recompute from live OpenAPI and source |
| Entitlements | 129 audited user-facing capabilities; global + role + plan-family + exact-SKU grants | Export the live catalog, do not rely on counts |
| Admin analytics | 130-item roadmap (#2186) | Reconcile implemented vs planned |
| GitHub | 67 open issues, 0 open PRs | Verify before starting |
| Known P0/P1 | #2130 GDPR sign-off (verify closure); #1732 privacy copy; #1628 Redis quota | Verify closure/status; do not redo legal review |
| Docs | `LAUNCH_CHECKLIST.md` still references older backend/DB revisions | Treat as historical, reconcile against live |

If live state differs, the live state wins. Record the discrepancy as a finding.

## Non-negotiable operating rules

- **Production is the test environment.** There are no real users as of 2026-11-27, so global configuration changes, capability flips, plan grants, and destructive account tests are permitted. Confirm the user table contains no real customers before the first global pass; if that changes, fall back to cohort-scoped changes. Use synthetic data anyway so evidence stays attributable and repeatable.
- **Global capability flips are allowed and expected — but log and restore them.** Snapshot the global, plan-family, role, and tenant grant matrix before each pass. Run an all-enabled pass first, then a plan-gated pass. Record every change (timestamp, actor, before, after, restore) in `changes/production-changes.md`. Restore the intended launch configuration at the end and verify it.
- **Avoid unnecessary real charges.** Use Dodo test mode, admin comp grants, or existing test subscriptions. A live checkout needs a disposable payment method and explicit approval; do not spend money just to prove a button works.
- **No destructive infrastructure changes.** Deleting test accounts, test resumes, test artifacts, test jobs, and test tenants is allowed and expected. Do not drop tables, rewrite migration history, or destroy the only copy of data without a backup.
- **Set a cost ceiling for load tests.** Ramp to expected launch concurrency and beyond, but stop on runaway Modal/LLM spend, 5xx > 2%, p99 > 2× baseline, worker restarts, or queue backlog growth.
- **Distinguish four states:** broken, disabled, not entitled, and slow. "Disabled by design" is not a pass for a plan that should have it, and "slow" is not a pass.
- **Evidence over assertion.** Every row needs a timestamp, account, request ID or trace ID, and the observed result.
- **Serialise global mutations, parallelise per-account tests.** One agent owns the global config lock and change log. Independent cohorts, tenants, and read-only probes may run in parallel.
- **Tag every test identity and time window.** Use a consistent prefix such as `audit+<cohort>@...`, record user IDs, and note the start/end of each test window so analytics can be filtered. If a dashboard cannot exclude test traffic, that is itself a finding.
- **Do not optimize before the baseline is signed off.** Premature caching or pooling hides the defect and destroys the measurement.

---

## Phase 0 — Build the complete surface inventory

Produce machine-readable inventories before testing anything:

- `inventory/http.csv` — method, path, auth requirement, plan gate, capability gate, handler, worker/queue, external provider, DB tables, streaming/WS dependency.
- `inventory/ws-events.csv` — WS path, message type, direction, payload schema, persistence (Redis Stream?), replay support, UI consumer.
- `inventory/workers.csv` — Modal function, queue, trigger (HTTP/queue/schedule), concurrency, min/max containers, timeout, retry policy, idempotency key, DLQ/recovery path.
- `inventory/plans.csv` — plan ID, family, price, interval, quotas (compiles/optimizations/AI assists), retention, seats, API access, BYOK, trial eligibility.
- `inventory/capabilities.csv` — capability ID, parent, default, plan families, roles, endpoints enforced, UI entry point, disable semantics.
- `inventory/analytics.csv` — event name, emitter (client/server), properties, destination (PostHog/DB), dashboard consumer, dedupe key.
- `inventory/integrations.csv` — provider, auth model, scopes, callback, failure modes, current configuration status.

Sources of truth:

- Live backend `GET /openapi.json`; live `/health`, `/readyz`, `/jobs/health`.
- `frontend/src/app/**/page.tsx` and the Next.js route manifest.
- `backend/modal_app.py` function list and `backend/app/workers/*`.
- `backend/app/middleware/capability_router.py` and the capability catalog.
- `backend/app/core/config.py` `PLAN_QUOTAS` and `SUBSCRIPTION_PLANS`.
- Admin dashboard control-room and capability pages.
- PostHog event definitions and the admin analytics services.

Then diff the inventory against `docs/FEATURES.md`, `docs/capability-enforcement.md`, `docs/LAUNCH_CHECKLIST.md`, and the GitHub issue tracker. Every item that appears in one and not the other is a coverage gap — record it, do not silently drop it.

**Coverage-auditor sub-agent:** independently enumerate the same surfaces from source and live OpenAPI, then diff against the lead's inventory. Report missing paths, undocumented events, orphan workers, and dead UI entry points.

---

## Phase 1 — Provision the identity and plan matrix

Create one dedicated test identity per cohort. Use unique email aliases and record the user ID, plan ID, entitlement snapshot, and quota snapshot.

| Cohort | Why it matters |
|---|---|
| Anonymous device trial | 3 lifetime uses; must beat browsing, must not bypass signup |
| Free | 10 compiles/day, 3 optimizations/month, 25 AI assists/month |
| Basic monthly | 400 compiles/month, 10 optimizations, 100 assists |
| Basic annual | Same entitlements, annual billing state |
| Pro monthly | Unlimited quotas, API access |
| Pro annual | Same, annual state |
| BYOK monthly | Unlimited platform quotas, stored key required, custom models |
| Student | Pro-family entitlements with verification requirement |
| Team owner | 5 seats, team billing, invites |
| Team member | Seat-bound access, no owner-only actions |
| Trial active / expired | Trial gating, conversion prompts, read-only fallback |
| Past due / cancelled | Grace period, downgrade, data retention |
| Admin (support / analyst / superadmin) | Role boundaries, audit logging, no product-access bypass |
| Developer API key | Scoped key, rate limit, compile/optimize/ATS/job/PDF |
| Tenant owner / member | Tenant isolation, domain routing, cohort features |

There is no customer-impact constraint, so create as many identities as the matrix needs. Provision through the legitimate admin grant/comp path first, because that path itself must be audited. Direct database provisioning is an acceptable fallback; record the exact statement, the resulting user ID, and the cleanup step. If the admin path cannot grant a plan, that is finding #1.

For each cohort, capture the effective entitlement and quota snapshot from the API, not from the pricing page. The pricing page is copy; the server is truth.

---

## Phase 2 — Capability enablement and enforcement

The product exposes 129 user-facing capabilities. With no real users, you can and should run two passes:

- **Pass A — all enabled.** Turn every capability on globally to find features that are broken, unwired, or dead in the UI. This is the fastest way to expose the "not even enabled" class of defect.
- **Pass B — plan/role/tenant gated.** Restore the intended matrix and verify that each capability is allowed only where it should be, blocked where it should not, and that parent-child dependencies hold.

Before Pass A, export the current global, plan-family, role, and tenant grant matrix. After Pass B, restore it and verify the restore. For each capability test: allowed when granted; blocked when revoked; parent-child dependency enforced; in-flight work is not retroactively cancelled; BYOK rejection never silently falls back to a platform key; public share/portfolio stops serving when publication is revoked; API keys and CLI/MCP/GitHub Action inherit the same server policy.

Record for each capability: expected behavior, observed behavior, endpoint, UI entry point, status, and whether the failure is enforcement, UI, or documentation.

Do not test capability revocation by disabling authentication, tenant isolation, security checks, or the admin path needed to reverse the change.

---

## Phase 3 — Per-plan user journeys

For each cohort, run the journeys that cohort is entitled to. At minimum:

- **Auth/onboarding:** signup, email verification, Google sign-in, logout/login, password reset, 2FA, session expiry, onboarding funnel events.
- **Templates:** browse, search, preview, thumbnail/PDF load, use template, fork/copy, template analytics.
- **Editor/compile:** create, edit, save, autosave, compile, error surfacing, logs, PDF download, version history, restore.
- **AI:** optimize, AI assist, cover letter, interview prep, JD analysis, deep analysis, streaming tokens, cancellation, quota charge/refund.
- **ATS:** score, semantic match, deep analysis, named-ATS simulation, parser output, industry profiles, locale profiles.
- **Import/export:** PDF/DOCX/Markdown/LaTeX import, Google Drive, Dropbox, GitHub import, PDF export, DOCX export, share links, document email delivery.
- **Resume engine:** managed source, structured edits, revision-aware preview, render pass policy, first-task cold render, Lua bridge.
- **Collaboration:** workspace invite, presence, comments, mentions, chat, read-only enforcement, reconnect.
- **Portfolio/share:** publish, unpublish, public view, analytics, view-as, revoked publication.
- **Tracker/outreach:** application tracker, status transitions, reminders, notifications, outreach generation.
- **References:** Zotero, Mendeley, citation import, publication list, academic CV.
- **Billing:** plan catalog, checkout preflight, webhook replay, invoice/refund state, dunning, trial conversion, cancellation.
- **Account/GDPR:** export, deletion dry-run, deletion request, legal hold, retention exceptions, audit trail.
- **Developer surfaces:** API key create/revoke, rate limit, compile/optimize/ATS/job/PDF, TUI commands, CLI, GitHub Action, MCP.
- **Admin:** user lookup, view-as, plan/entitlement change, capability toggle, analytics dashboards, incident/alert views, audit log.

For every journey record: steps, expected result, actual result, status (`PASS` / `FAIL` / `BLOCKED` / `DISABLED` / `NOT ENTITLED`), evidence link, latency samples, console/network errors, and related defect IDs.

---

## Phase 4 — Production latency and throughput

Measure production, not local development. Local measurements are useful only to explain a production result.

For each endpoint class, collect at least 30 warm samples and, where controllable, 10 cold samples. Report p50, p95, p99, min, max, error rate, payload size, auth state, and measurement region. Separate:

- edge/network/TTFB from application processing;
- request admission and quota check from queue wait;
- queue wait from worker execution;
- worker execution from storage upload and event publish;
- event publish from WebSocket delivery and client render.

For compilation specifically, instrument the existing job lifecycle timestamps and produce a stage breakdown for the observed 5–10 seconds:

`request → admission/quota → queue → container acquisition → pdflatex pass 1..N → PDF post-process → S3 upload → event publish → WS delivery → client render`

State which stage dominates. Do not guess that it is cold start; prove it. Compare warm and cold, simple and complex documents, and 1/5/20/50 concurrent compiles.

Load-test with a staged ramp, up to and beyond expected launch concurrency. Set a hard cost ceiling first. Abort on runaway Modal/LLM spend, 5xx > 2%, p99 > 2× baseline, worker restarts, queue backlog growth, Redis quota warnings, or DB connection saturation. Record worker deaths, OOMs, retries, and poison messages.

Produce cost per successful job by engine and plan: Modal CPU/memory time, LLM tokens, Redis, storage, egress, and payment fees where observable.

---

## Phase 5 — WebSocket and event audit

Exercise both paths: `/ws/jobs` and `/ws/collab/{resume_id}`.

For `/ws/jobs`: ticket auth, subscribe, unsubscribe, cancel, ping/pong, heartbeat, replay with `last_event_id`, ordering, duplicate suppression, reconnect after network loss, backpressure, 64 KB frame limit, per-connection rate limit, cross-user isolation.

For `/ws/collab/{resume_id}`: workspace authorization, presence, chat frames, read-only notification, reconnect, rate limits, cross-tenant isolation.

Verify every job event is emitted exactly once, persisted to the Redis Stream, replayed on reconnect, and rendered in the UI. Measure event-to-UI latency separately from job execution latency. Test a client that disconnects mid-compile and reconnects after completion.

---

## Phase 6 — Failure and edge cases

Test these explicitly:

- Quota exhaustion on each dimension; concurrent requests racing the last unit; refund on failure.
- Double-click/double-submit; duplicate idempotency keys; tab reload mid-job; two tabs on the same job.
- Worker killed mid-compile; Redis/DB/S3/provider outage; timeout; 429; malformed provider response.
- Invalid LaTeX, oversized source, huge PDF, unusual fonts/packages, Unicode/RTL/CJK, ligature garbling.
- Capability revoked mid-job; plan downgraded mid-job; entitlement cache staleness.
- OAuth denial/expiry for Google, GitHub, Drive, Dropbox, Zotero, Mendeley; webhook replay; invoice/refund duplicate.
- Cross-tenant and cross-user access attempts on resumes, comments, shares, jobs, artifacts, and presigned URLs.
- Legal hold active; GDPR deletion dry-run; retention exception; deletion idempotency.

With no real users, run the full deletion path — dry-run, request, anonymization, retention-exempt rows, legal-hold block — on disposable accounts, then verify the audit trail and the surviving rows.

Each failure gets a defect record, not a paragraph in a summary.

---

## Phase 7 — Admin analytics reconciliation

For every dashboard metric, query the source data for the same window and compare. Check:

- event duplication or loss (client retry, server retry, webhook replay);
- timezone and day-boundary handling;
- cohort suppression (<5) and privacy filters;
- bot/internal traffic exclusion;
- PostHog vs database parity;
- funnel step definitions and denominator changes;
- dashboard query latency and N+1 behaviour;
- whether the metric moves when the underlying action is performed.

Test traffic will contaminate production analytics. Record the exact test window and account IDs, use admin cohort filters where available, and compare dashboard totals with and without the test cohort. If the dashboard cannot exclude test traffic, that is itself a finding.

A dashboard that renders but disagrees with the database is a P1 analytics defect. Record both numbers and the query used.

---

## Phase 8 — Scale, worker survival, and cost

Audit the deployment, not just the code:

- Modal per-function `min_containers`, `max_containers`, buffer, scaledown window, CPU/memory, timeout, concurrency.
- Warm API and LaTeX containers; confirm which functions actually stay warm and which cold-start.
- Celery/Redis queue depth, retry policy, visibility timeout, DLQ/recovery, poison-message handling, finalization arbiter, exactly-once quota refund.
- Redis request quota (#1628), connection pooling, eviction, pub/sub backpressure.
- Postgres connection pool, slow queries, lock contention, migration head.
- S3 presigned URL expiry, orphaned artifacts, cleanup workers, storage growth.
- Modal scheduled jobs and recovery sweeps: do they run, and do they complete?
- Top cost drivers and the cost of one failed/retried job.

Identify every mode in which a worker can die or silently stop consuming. "No worker dies" is a hypothesis to prove, not an assumption.

---

## Phase 9 — Independent cross-check

Provision at least three auditors with non-overlapping mandates:

1. **Coverage auditor** — re-enumerate the surface and diff against the lead inventory.
2. **Performance auditor** — re-run a 10% sample of latency tests and challenge the methodology.
3. **Correctness/security auditor** — re-run plan gates, capability enforcement, tenant isolation, and one destructive-path dry run.

Each must report disagreements explicitly. The lead resolves them with fresh evidence. A second pass that only reads the first report is not a cross-check.

## Sub-agent allocation

| Agent | Scope | Write access |
|---|---|---|
| Coverage auditor | Inventory diff, dead routes, orphan workers, missing events | Read-only |
| Free/Basic plan auditor | Journeys, quotas, upgrade prompts | Own test accounts |
| Pro/BYOK plan auditor | Unlimited paths, API, custom models, BYOK rejection | Own test accounts |
| Student/Team/Trial auditor | Verification, seats, invites, trial expiry, past due | Own test accounts and test tenant |
| Events auditor | WS jobs, collab, replay, ordering, event-to-UI latency | Own test accounts |
| Performance auditor | Latency, load ramp, stage breakdown, cost per job | Read-only + load harness |
| Reliability auditor | Worker kill, outages, retries, DLQ, recovery | Global lock; serialized mutations |
| Analytics auditor | Dashboard-to-DB reconciliation, PostHog parity | Read-only |
| Security/tenant auditor | Cross-user/tenant access, capability enforcement | Own test accounts and tenants |
| Cross-check auditor | Independent 10% re-run and methodology challenge | Read-only |
| Cleanup auditor | Deletes test data, restores flags, verifies clean launch state | Global lock |

Use one shared evidence directory and one mutation lock. Do not let two agents change global configuration or run load tests simultaneously.

## Deliverables

- `AUDIT-MASTER.md` — scope, method, environment, limitations, verdict.
- `inventory/*.csv` — the seven inventories above.
- `plans/{cohort}.md` — one report per cohort.
- `latency/endpoints.csv` — p50/p95/p99, error rate, sample count, warm/cold, region.
- `latency/compile-stages.md` — stage-by-stage breakdown and dominant cost.
- `events/ws-events.csv` — emitted, persisted, replayed, rendered, latency.
- `defects.md` — ID, severity, surface, cohort, repro, expected/actual, evidence, impact, owner, proposed fix.
- `changes/production-changes.md` — every global, plan, role, tenant, and capability change: timestamp, actor, before, after, restore, verification.
- `cleanup.md` — every test account, tenant, job, artifact, and flag, with deletion or restore status.
- `analytics/reconciliation.md` — dashboard vs source, window, query, delta.
- `optimization-backlog.md` — ranked by user impact × frequency ÷ effort, with measured baseline and target; separate latency from cost.
- `executive-summary.md` — what works, what is broken, what is slow, what is blocked, top 10 actions.

Severity:

- **P0** — data loss, security/tenant breach, core flow completely broken, worker fleet failure.
- **P1** — core flow broken for a paid plan, or p95 > 2× SLO, or analytics materially wrong.
- **P2** — degraded, workaround exists, or one cohort affected.
- **P3** — polish, copy, minor inconsistency.

## Sequence and gates

1. Inventory and reconciliation. Gate: coverage auditor finds no unexplained surface.
2. Identity provisioning and capability snapshot. Gate: every cohort has an account and a baseline.
3. Read-only journey and latency testing. Gate: core journeys have evidence.
4. Global mutation passes (all-enabled, then plan-gated), failure testing, and load testing. Gate: restore verified after each pass.
5. Analytics reconciliation. Gate: every dashboard has a source comparison.
6. Independent cross-check. Gate: disagreements resolved.
7. Baseline sign-off. Only then start optimization.

If a step risks runaway cost, irreversible infrastructure damage, or the only copy of data, stop and ask. If a provider or legal constraint blocks a test, record it as blocked rather than guessing. Do not fill a gap with an assumption.
