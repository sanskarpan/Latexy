# Executive summary - Latexy production audit 2026-11-27

**Scope:** every user-facing HTTP operation, WebSocket/job event, worker, integration, plan and capability in production at backend `ee1a405d`, frontend `d2cbc51a`, Modal app `ap-IB2XwK8MjL2xmeI7wOUyEZ`, DB head `0109_error_alerts`.
**Method:** source/OpenAPI inventory reconciled against live production, 16 synthetic cohort identities plus one device trial, read-only journeys, controlled entitlement flips with byte-exact restore, 35-endpoint analytics reconciliation, 75 WebSocket observations, failure/quota/tenant probes.
**Verdict:** core journeys are broadly functional, but the product is **not launch-clean**. One P0, a set of P1s across AI, auth, collaboration, recovery and analytics, and an entitlement layer that currently grants nearly everything to everyone.

## What works

| Area | Evidence |
|---|---|
| Free/Basic journeys: templates, resume CRUD, compile + PDF, ATS, import/export, share, portfolio, tracker, quotas/refunds | `audit/plans/free-basic.md`; 144 requests, all core paths PASS |
| Pro/Pro Annual/BYOK unlimited quotas; developer key lifecycle, scopes, revocation, API compile/ATS/job/PDF, cross-user 404 | `audit/plans/pro-byok-developer.md`; 140 requests |
| Team seats, owner-vs-member boundaries, seat limit, tenant isolation, cross-user document 404 | `audit/plans/student-team-trial.md` |
| Student checkout gate, trial expiry, past-due/cancelled fallback | `audit/plans/student-team-trial.md` |
| Signup/login/logout/reset/2FA, session expiry, GDPR export/deletion/legal-hold/audit trail | `audit/plans/auth-account-gdpr.md` |
| `/ws/jobs` normal path: ticket auth, 58/58 persisted events, replay, dedupe, isolation, frame limits; event-to-client p50 6.2 ms / p95 215.6 ms | `audit/events/ws-audit.md` |
| Admin analytics: 35/35 endpoints 200; daily-metrics series reconciled to SQL; read-only admin roles blocked correctly | `audit/analytics/reconciliation.md`, `audit/plans/admin.md` |
| Entitlement resolver: plan matrix and kill switch actually change effective access; exact restore verified | `audit/changes/production-changes.md` |

## What is broken

1. **P0 - BYOK credential leak/misroute (PB-D03).** OpenAI BYOK keys are sent to the platform's non-OpenAI `OPENAI_BASE_URL` because the SDK client omits `base_url`. A user's key leaves the selected provider; valid OpenAI BYOK cannot work.
2. **P1 - AI optimization fails (PB-D01).** `/optimize` and `/jobs/submit` optimization fail 2/2 with `llm_error` after retry on the platform key; direct `POST /optimize` also returned 500.
3. **P1 - Auth rate limiting is global (AAG-D01).** Every Vercel request keys as `untrusted-proxy`; the product shares 18 sign-ins/min and 5 password-reset mails/hour. Trivial DoS and launch-day lockout.
4. **P1 - Collaboration truncation (WORK-01).** Yjs history is a Redis list capped at 500 updates/24 h with no snapshot/compaction; late joiners lose document history.
5. **P1 - Job recovery (WORK-02).** Modal workers have no retries; a killed job can stay non-terminal until the hourly sweep (~70 min). The sweep's Celery revoke is a no-op.
6. **P1 - Email health (EMAIL-01).** 30-day: 107 sent, 79 delivered, 20 bounced (20%), 1 complaint, 199 delayed; the outbound ledger reports 0.
7. **P1 - Analytics definitions (AN-01/AN-02/AN-03).** Direct `/compile` charges quota but writes no compilation/event; "paid" is inferred from subscription status with 0 payments; MRR/upgrades read an empty history table while sibling dashboards report 10 paid.
8. **P1 - Entitlement/price mismatch (CAP-01).** Live export grants all 149 gateable capabilities to every plan, role and anonymous caller; Free gets BYOK/team/collab/analytics/deep ATS/API. Paid plans differ mainly by quotas and seats.
9. **P2 - Trial/past-due display (ST-D01/ST-D02).** A linked `trialing` row resolves to Free while `/subscription/current` says Pro unlimited; past-due/cancelled/team-lapse display advertises the old plan while enforcement is Free.
10. **P2 - Cancellation exactly-once (WSE-01/02, WS-01).** Mid-compile cancel emits two terminal events and can invert sequence; repeated cancel appends more; replay can overtake live events.
11. **P2 - Collab chat (WSE-04/05).** ~0.83 s/frame relay and a 20/10 s limiter that does not bound a burst at that throughput.
12. **P2 - Subscription/trial controls (TRIAL-01, RET-01).** `trial_used` is never read; no checkout trial; `historyRetention` is copy-only.
13. **P2 - Share revocation/capability leak (SEC-D01/D02).** Revoking a share leaves an already-issued 1-hour presigned PDF URL downloadable; a viewer collaborator receives the owner's live `share_token`/`share_url` and can redistribute it after removal.

## What is slow

- **Client-observed floor ~1.2 s** even for `/readyz`, `/health`, `/me`; `/jobs/health` p50 3.6 s / p95 4.6 s; `/config/entitlements` p50 1.86 s / p95 2.33 s (one 17.65 s); `/resumes` p99 23.4 s; `/analytics/admin/overview` p95 3.8 s; `/admin/plan-catalog` 23.05 s for 92 KB; `/developer/usage` 2.5-3.3 s.
- **Compile:** warm single 1-page submit-to-terminal **20.7 s p50 / 35.6 s p95** (pdflatex 9.2 s, storage/finalize 6.8 s, acquisition 1.4 s). Simple-5 concurrent **39.9 s p50 / 62.7 s p95**; simple-10 30.2 s / 45.7 s; complex-10 42.2 s / 51.9 s. All 38/38 completed, zero 5xx. See `audit/latency/` and `audit/optimization-backlog.md`.
- WS reconnect pays ~2.18 s ticket + ~1.02 s connect before replay.

## What is blocked

- Valid third-party BYOK key: successful BYOK generation/custom-model routing not observed.
- OAuth/provider callbacks (Google/GitHub/Drive/Dropbox/Zotero/Mendeley), email verification links and invitation acceptance: no readable mailbox, authenticator or provider console.
- Live payments/refunds/webhooks: no charges allowed.
- >500-event WS replay: blocked by a verbose-compile stall at 10%.
- 38 registered operations hidden from OpenAPI; 424/636 operations blocked for named fixture/safety reasons (all dispositioned in `inventory/http-disposition.csv`).
- PostHog server parity: no personal API key; production HTML has no PostHog key.

## Top 10 actions before launch

1. **Fix BYOK routing (PB-D03):** set `base_url` explicitly per provider in every client; add a test asserting the outbound host for platform vs BYOK keys.
2. **Fix optimization (PB-D01):** reproduce the `llm_error`, classify provider errors, retry only transient classes, refund once.
3. **Decide and enforce the entitlement matrix (CAP-01/02/03):** define which capabilities Free/Basic/Pro/BYOK should have, gate BYOK key management, and rename or invert the kill-switch semantics.
4. **Fix auth rate limiting (AAG-D01):** trust the Vercel proxy correctly or key by a trusted client identifier; add a per-IP and per-account limit test.
5. **Harden job/cancel lifecycle (WORK-02, WSE-01/02, WS-01):** worker-level retry/timeout, idempotent cancel, single terminal publisher, ordered replay.
6. **Add Yjs snapshots/compaction (WORK-01)** and cap room history by bytes, not only update count.
7. **Repair analytics source truth (AN-01/02/03, AS-02/03):** write compilation/event rows for direct compiles, define paid from settled payments, and add test-cohort exclusion.
8. **Fix trial/past-due display and entitlement (ST-D01/02):** one effective-plan resolver for quotas and copy; add `trialing` to the linked-status path.
9. **Restore email deliverability and ledger parity (EMAIL-01):** fix domain/auth/suppression, reconcile provider events, alert on bounce/delay.
10. **Take the latency wins:** cache entitlements, serve the constant plan catalog, cache Modal-aware job health, repair the daily rollup, cut the 6.8 s storage/finalize window, and confirm/raise the LATEX CPU allocation before tuning containers.
11. **Make share revocation real (SEC-D01/D02):** stop publishing long-lived presigned PDF URLs or delete/replace the object on revoke; strip `share_token`/`share_url` from collaborator responses and rotate on removal.

## Baseline sign-off

The evidence supports signing off the **functional baseline with the P0/P1 exceptions above**. Optimization should start only after items 1-3 are fixed, because caching or tuning would otherwise hide the defects. The audit artifacts are committed on `audit/production-2026-11-27`; cleanup is tracked in `audit/cleanup.md`.


## Front-end page audit (follow-up)

All **44 App Router pages** were loaded in production at desktop and mobile widths with anonymous/free/pro/admin/team roles. Reports and screenshots are in `audit/frontend/`; 18 page-level defects are in `defects-frontend.md` and GitHub #2324-#2335, #2339, #2342-#2345, #2347.

- **P1:** Optimize can sit on a blank "Checking feature availability" spinner for 25s+; imported/legacy LaTeX resumes dead-end across edit, builder and variant; compiled share links could not render their PDF because the R2 artifact URL was blocked by CORS — **fixed 2026-11-27** with a bucket CORS rule; PDF + public review comment verified (regression checks pending).
- **P2:** Consent banner covers auth/pricing/admin controls; admin capability matrix is 21,101px/930 toggles; pricing hides prices; dashboard says 3.5s compile vs 20.7s measured; builder/auth controls are unlabeled; share says "Link unavailable" after compile; cover-letter generation hangs at "Generating…" for 45s.
- **P3:** missing H1/small text, onboarding modal, PDF URL wrapping, tracker labels.

The builder happy path works: create (201) → fill fields → preview PDF → download; PDF import completes end-to-end (~6s upload, ~16s adapt, 12.8s to editor after create). The failures are latency, feedback and artifact delivery (share CORS), not the core edit model.

## Architecture

`audit/architecture/latency-advisor.md` is the measured plan; `audit/architecture/latency-advisor-opus.md` is the **actual Claude Opus 5.5** review (Anthropic API). Opus reorders the work: instrument first (cgroup CPU, cold/warm, per-stage spans), then ship explicit `MODAL_LATEX_CPU=1.0`/memory plus container font warm-up, then finalize stage A (parallel geometry/pdftotext, persistent loop/pool, no redundant HEADs) before any high-risk transaction rewrite, then warm pool + admission, then the client-perceived path (cache short-circuit, presigned URL + R2 CORS, preview semantics). Target: warm p50 <=12s, warm p95 <=18s, 5-concurrent p50 <=25s, finalize <=2s. Tracked in #2337, with #2309/#2310 as specific defects.

## Issue tracking

**51 GitHub issues** were filed (#2295-#2345, #2347, plus the complete index #2341), covering every defect ID in `audit/defects.md` and `audit/frontend/defects-frontend.md`, with proposed fixes and acceptance criteria. The index is the authoritative map.

## Evidence index

- `audit/AUDIT-MASTER.md` - scope, method, coverage, gates
- `audit/defects.md` - 106-row consolidated register (1 P0, 15 P1, 58 P2, 32 P3)
- `audit/inventory/` - seven inventories + coverage diff + HTTP dispositions
- `audit/plans/` - cohort reports
- `audit/latency/` - endpoint and compile-stage measurements
- `audit/events/` - WebSocket protocol, replay, latency
- `audit/analytics/reconciliation.md` - dashboard-vs-DB reconciliation
- `audit/changes/production-changes.md` - every mutation and restore
- `audit/cleanup.md` - every test identity/artifact and deletion state
- `audit/optimization-backlog.md` - ranked latency/cost work
