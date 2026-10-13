# Launch Checklist

Last source audit: **2026-10-13**. Baseline: [`c24531e2722bbe36d40fffb38684cecfe2682790`](https://github.com/sanskarpan/Latexy/commit/c24531e2722bbe36d40fffb38684cecfe2682790).

This is a release decision ledger, not a claim that every feature works or that the
absence of findings proves the absence of bugs. Read it with the individual
[feature-control matrix](audits/launch-2026-10-13/feature-controls.md) and
[public-surface audit](audits/launch-2026-10-13/public-surfaces.md). Keep those dated
reports as baseline evidence; update this checklist when repairs and acceptance
are independently verified. Do not turn a code merge into a production pass.

## 1. Decision, scope and ownership

**Public launch: HOLD. Limited unpaid beta: conditional, not signed off.**
The repository has substantial passing automated coverage. Deployment, provider,
capacity, security-operations and full product-path evidence still have open gates.
A small beta requires matching deployed contracts, working core flows, safe billing
state, account-remediation verification and sufficient monitored capacity. A paid
launch additionally requires live Dodo acceptance. Deferred features must be
explicitly outside the offered beta, without advertising unsupported guarantees.

### Status vocabulary

| Status | Meaning |
|---|---|
| `SOURCE` | Implementation/wiring inspected; no successful execution implied. |
| `LOCAL` | Named isolated tests passed at the stated revision/environment. |
| `CI` | Exact-revision canonical check passed; mocked, isolated and real-provider scopes remain distinct. |
| `LIVE` | Dated acceptance of the exact deployed flow and intended environment is retained. |
| `GAP` | Confirmed defect, absent test, or incomplete acceptance; distinguish which. |
| `OPERATOR` | Needs an authorized environment/account/configuration action or private evidence. |
| `DECISION` | Product, legal, cost, audience or service-level choice; engineering must not invent it. |
| `DEFERRED` | Explicitly excluded from the release scope, with limitations and follow-up owner. |

An unchecked box remains open even when another column has `SOURCE`, `LOCAL` or
`CI` evidence. A skipped job is not a test pass. A failing attempt followed by a
fix needs a new exact-head run, not a green retry used to erase the failure.

Owner classes below are responsibilities to assign to named people before launch:
**ENG** product/backend/frontend engineering; **QA** acceptance reviewer;
**OPS** deployment, monitoring and incident operator; **SEC** identity/security
operator; **BILL** merchant/catalog owner; **LEGAL** business/legal/privacy owner;
**PRODUCT** release scope, messaging and service-level owner. Account roles and
resource access roles are different from these task owners.

### Required release record

- [ ] PRODUCT names the release owner, intended audience, offered languages/templates,
  enabled capabilities/SKUs/integrations, support hours and excluded features.
- [ ] Every gate has a named assignee, decision deadline and issue/PR or evidence link.
- [ ] Record source SHA, migration head, frontend deployment identity, backend serving
  revision, worker/runtime image identity and approved renderer asset fingerprint.
- [ ] QA signs exact-source tests plus actual deployed happy/error/recovery paths.
- [ ] OPS records rollback/containment procedure, incident contact, capacity margin,
  recovery objectives and observation window before widening traffic.
- [ ] Keep private operational reports access-controlled. Never attach tokens, account
  passwords, connection strings, customer documents, raw environment dumps or logs
  containing user data to this checklist or a public issue.

## 2. Launch blockers and work split

Priority is release risk, not proof of a current production outage.

| ID | Priority / state | Required outcome | Owner / kind | Tracking/evidence |
|---|---|---|---|---|
| L01 | P0 / OPERATOR | Certify the actual candidate Modal renderer and default application flow; bind approved image/assets to deployment inputs. Passing input syntax is not certification. | OPS + QA + SEC; authorized environment work | [#1865](https://github.com/sanskarpan/Latexy/issues/1865), [capability contract](MODAL_RENDERER_CAPABILITY.md) |
| L02 | P0 / OPERATOR | Complete current-source read-only billing preflight, schema/access servicing checks and safe-disabled acceptance before migrations/deploy. | OPS + BILL; operator diagnosis | [#1866](https://github.com/sanskarpan/Latexy/issues/1866), [Dodo runbook](BILLING_DODO.md) |
| L03 | P0 / OPERATOR | Verify matching frontend/backend capability and mutation contracts on the serving deployment; fail-closed controls must not leave advertised core flows unavailable. | OPS + ENG + QA; rollout acceptance | [deploy workflow](../.github/workflows/deploy-modal.yml), [feature controls](audits/launch-2026-10-13/feature-controls.md) |
| L04 | P0 / OPERATOR | Verify historical exposed-account remediation with private rotation/disablement evidence; repository sanitization alone is insufficient. | SEC; no credentials in evidence | [#1683](https://github.com/sanskarpan/Latexy/issues/1683) |
| L05 | P0 / OPERATOR | Establish current Redis database binding, command headroom, authoritative monitoring and an approved exhaustion response before new traffic. Health/PING does not establish monthly capacity. | OPS + PRODUCT; paid changes need separate approval | [#1628](https://github.com/sanskarpan/Latexy/issues/1628), [capacity runbook](observability/runbooks.md#redis-provider-request-capacity) |
| L06 | P1 / GAP | Compose B07 structured interchange with H01 for all new JSON export admissions; retain ordinary owned source/PDF recovery. Repair and regression review in progress, not deployed. | ENG; code + tests | [route policy](../backend/app/middleware/capability_router.py), feature matrix B07 |
| L07 | P1 / GAP | Hide/recheck E03 simulation and F10/F11 tenant new actions after denial/revocation; preserve admitted results and permitted recovery. Repair and regressions in progress. | ENG; code + tests | Feature matrix E03/F10/F11 |
| L08 | P1 / GAP | Fail closed before destructive restore when the safety backup/recreation fails; treat SQL restore errors as failure. Local fake-command repair is not a restore drill. | ENG + OPS; code + isolated recovery exercise | [restore script](../scripts/backup/restore-database.sh) |
| L09 | P1 / OPERATOR | Run real saved-owner create/edit/save/reload/conflict/preview/export flow against final integrated source; cover rapid replacement, reconnect and account changes. | QA + ENG; isolated E2E then deployed acceptance | [#1819](https://github.com/sanskarpan/Latexy/issues/1819) |
| L10 | P1 / OPERATOR | Verify bounded conversion success/failure, reconnect, cancellation and exactly-once refund on deployed runtime. | QA + OPS; synthetic data, approved provider budget | [#1863](https://github.com/sanskarpan/Latexy/issues/1863), [#1818](https://github.com/sanskarpan/Latexy/issues/1818) |
| L11 | P1 / DECISION | Approve end-to-visible-PDF budgets, then measure cold/warm/cache/overlap/burst distributions and resolve unexplained regressions. | PRODUCT + ENG + QA | [#1820](https://github.com/sanskarpan/Latexy/issues/1820), [SLOs](observability/slos.md) |
| L12 | P1 / DECISION | Reconcile Terms with trial, quotas, saved-document retention, entity/contact and actual billing offer; verify support/privacy mailbox operation. Do not fabricate legal facts. | LEGAL + BILL + PRODUCT | [public audit PUB-01](audits/launch-2026-10-13/public-surfaces.md), [Terms source](../legal/terms-of-service.md) |
| L13 | P1 paid launch / OPERATOR | Accept live Dodo merchant/products/tax/currency/recurrence, signed lifecycle events, payment/recovery/refund and servicing. Unaccepted products remain unavailable. | BILL + QA + OPS; separately approved transactions | [Dodo operations](BILLING_DODO.md), [#1866](https://github.com/sanskarpan/Latexy/issues/1866) |
| L14 | P2 / GAP | Correct private-route indexing, auth-only sitemap entry, setup instructions, page metadata and reduced-motion gaps; verify actual production responses. | ENG + QA; source/test/browser work | [public audit](audits/launch-2026-10-13/public-surfaces.md) |
| L15 | DEFERRED | Hindi logical PDF text extraction is not certified in affected readers. Do not promise universal ATS/text-layer/language correctness. | ENG + PRODUCT; explicitly scoped follow-up | [#1820](https://github.com/sanskarpan/Latexy/issues/1820) |

No missing provider configuration is solved by setting an acceptance boolean,
loosening authorization, mapping unknown legacy grants to allow, disabling a
required test, or opening new live purchases. A current passing health endpoint
is useful availability evidence, not evidence for L01–L15 completion.

## 3. Evidence baseline and coverage limits

Completed baseline checks (scope is deliberately bounded):

- [x] Source inventory reconciled: all 129 product IDs represented exactly once.
- [x] Canonical baseline CI and frontend identity certification verified below.
- [x] Local source/privacy/claim guards and 21 dependency-free classifier cases passed.
- [x] Current audit ran 1,121 isolated policy cases and 582 rollout/capacity unit cases.
  Three real-PostgreSQL acceptance cases across those groups remain blocked by
  the unavailable disposable database; their repository tests were not removed.
- [x] Restore regression demonstrated eight baseline failures; nine fake-command
  tests pass after the local repair, with independent review. The repair is not
  in this documentation-only change and is not deployed or a real restore drill.

Local UI/indexing and admission repairs are being reviewed separately. References
to their new tests describe work in progress until a repair PR/source SHA is linked.


- Baseline main [CI 38185842538](https://github.com/sanskarpan/Latexy/actions/runs/38185842538)
  passed all 15 selected jobs, including backend tests/lint, frontend units/build,
  deployment parity, isolated real compile/preview, cross-browser quality,
  full-stack smoke, extension, TUI, CV action, template extraction and observability.
- [Vercel certification 38187046072](https://github.com/sanskarpan/Latexy/actions/runs/38187046072)
  passed for that source. [Backend rollout 38187046075](https://github.com/sanskarpan/Latexy/actions/runs/38187046075)
  stopped at renderer input validation before billing preflight/migrations/deploy.
  These are dated results, not a statement about future heads or manual changes.
- The source inventory contains **129 product IDs**: 113 gateable and 16 immutable
  baselines; 31 coarse parents make 160 registry entries / 144 switches. All 129
  product entries are listed in the companion matrix. Product controls are not
  the separate six operational flags.
- Inventory at this source: 345 backend test modules, 262 frontend unit files,
  103 browser `.spec.ts` files. File counts do not measure assertions, coverage,
  test selection, provider readiness or successful user journeys.
- The quality project uses Chromium, Firefox, WebKit and emulated Pixel/iPhone
  viewports. Its HTTP fixtures and blocked service workers do not establish real
  device, external provider, production database or installed-PWA acceptance.
- The real isolated compile gate exercises actual local API/broker/worker/TeX/
  private storage/browser bytes. It does not attest a Modal VM or live billing.
- The required editor/Settings browser command selects eight specs; the quality,
  admin-plan, full-stack, hydration and real-preview configs select additional
  suites. Every other browser spec needs deliberate selection or an explicit
  evidence gap. Never infer that `pnpm test:quality` runs all 103 files.
- Current audit policy tests and environment limitations are recorded in the
  companion reports. Final repaired source requires fresh aggregate checks.

## 4. Every feature, role and plan

Use [feature-controls.md](audits/launch-2026-10-13/feature-controls.md) as the
individual feature ledger. The inventory is defined in
[capability_catalog.json](../backend/app/core/capability_catalog.json),
[feature_registry.py](../backend/app/core/feature_registry.py) and the checked-in
[generated admission matrix](audits/admin-capabilities/feature-matrix.json).
Static source references identify where to test; they do not close the following
per-feature scenarios.

### Control-plane acceptance (repeat for each applicable gateable ID)

- [ ] Inventory ID, label, parent, UI entry points, backend operations, audience,
  applicable account/resource roles and the exact test cases are recorded.
- [ ] Global OFF hides new-action controls and denies direct HTTP/WS/protocol
  admission before DB mutation, quota reservation, dispatch or paid-provider work.
- [ ] Global ON restores allowed work only when role, plan family, exact SKU and
  every ancestor also allow it. Child ON must not override parent OFF.
- [ ] Anonymous/user/support/admin matrices are tested independently. Admin and
  support do not bypass product policy. Non-admins cannot change control-plane data.
- [ ] Account role is not document/team/tenant ACL. Test actual owner/member/reviewer
  access semantics where defined; do not invent a universal application `reader` role.
- [ ] Cover free/basic/pro/BYOK/team families and applicable monthly/annual/student/
  weekly/lifetime SKUs; SKU denial narrows its family. Confirm actual quota and
  subscription lifecycle, not just plan labels or displayed badges.
- [ ] Missing/unknown/failed policy denies optional new work. Session loading,
  logout, A→B→A, token refresh and stale requests cannot leak another owner's grant.
- [ ] OFF after render blocks a retained handler, shortcut, modal, scheduled
  callback, retry or background work. Test frontend refresh/expiry and server's
  authoritative reread rather than relying on a page reload.
- [ ] Current client grants expire/revalidate on focus/visibility/explicit change;
  explicit invalidation denies stale grants while recovering. Confirm 30-second
  refresh + 8-second request timeout source behavior in final browser acceptance.
- [ ] Concurrent admin changes enforce expected-state conflict handling; ambiguous
  network outcomes reconcile from authoritative state without blind replay.
- [ ] Already-admitted work can finish, publish its owned artifact, cancel, recover
  and refund exactly once. A new retry/provider request is a new admission.
- [ ] Existing owned reads/downloads, source recovery, disconnect/removal/leave and
  account security remain available where the documented recovery policy permits.
- [ ] Public portfolio/share permission is rechecked at publication/serving; test
  existing presigned URL expiry separately, because toggle changes cannot revoke
  bytes already delivered or a still-valid external storage URL.

### Non-toggleable safety baselines

The 16 immutable product baselines cover public help, account authentication,
security/accessibility/consent, existing async results/PDF/source/offline recovery,
first-party clients/self-hosting and administrative recovery. Verify their precise
registry entries. Do not add switches that can lock users out of security,
authentication or their permitted existing data. An always-available CLI/MCP/action
still obeys the server's operation-specific admissions and ordinary authorization.

## 5. Product journey acceptance

Each row needs: happy path, empty state, validation error, provider/server error,
retry, cancel/Back/Close, refresh, repeated action and account transition. Retain
sanitized browser traces with source/image identity. Use synthetic user content.

| Journey | Required scenarios beyond the happy path | Owner / evidence anchor |
|---|---|---|
| Landing → guest Studio | Template/sample, typing/manual compile, quota exhausted, disabled feature, import auth gate, reload draft, source fallback, download exact current PDF | QA; `try/page.tsx`, real-preview + quality specs |
| Signup/login/onboarding | Email delivery/expiry, Google cancel/callback, session renewal, onboarding skip/resume, safe redirect, logout/reload, reset/verify, MFA/passkey recovery | QA + OPS; auth/onboarding/Settings specs; historic Google acceptance is not all-provider acceptance |
| Workspace CRUD | Empty/list/search/filter, create/duplicate/archive/delete, stale response, same-account return, tab conflict, keyboard navigation | QA; workspace/new/ownership specs |
| Saved source editor | Load/save/reload, empty source, lint/error logs, compiler settings, theme/shortcuts/find, autosave conflict, owner switch | QA; editor ownership/capability/core full-stack specs |
| Guided/rich-text builder | All fields, import review, validation, ordering/visibility/variants, attachment to source identity, template/compiler change, delayed save/cancel | QA; builder/import/variant specs + real saved-owner gate |
| PDF interaction | Preview/download same final bytes, last verified PDF during new job, page/zoom/reflow, text selection/copy/find, keyboard/screen reader, SyncTeX/geometry and semantic overlay | QA; exact-PDF/compile-sync tests; Hindi limitations explicit |
| Optimization/AI | Configured model/provider, BYOK selection, rejected model, timeout/429, bounded retry, quota/cancel/refund, factual provenance, candidate accept/reject without stale overwrite | ENG + QA; lifecycle/durable-ledger tests + approved provider acceptance |
| Imports/exports | Supported TXT/MD/TEX/PDF/DOCX/JSON profiles, size/encoding/corrupt/encrypted rejection, review before overwrite, PDF/DOCX/TEX/JSON output and quota/gates | QA; format/export/PDF import tests; no external uploads without approval |
| Templates/locales | Every offered seeded template compiles/extracts; saved compiler retained, font/profile compatibility, long content/wrap, non-Latin and RTL scope | QA; template contract + actual intended renderer matrix |
| Career tools | ATS quick/deep, JD comparison, proofreader/assistant, cover letters, batch tailoring, career/interview/simulation and tracker workflows with OFF/ON | QA; individual catalog IDs and feature specs |
| Sharing/collaboration | Public opt-in/revoke/expiry, anonymous redaction failure, team membership/roles, comments/suggestions, concurrent source/CAS and disconnected client | QA + SEC; shared-access/owner races; approved ordinary accounts only |
| Portfolio/tenant | Publish/unpublish, slug/domain/branding, invitations/cohorts, tenant isolation, removing/recovering settings after toggle denial | QA + OPS; F10/F11 repairs + real DNS/TLS acceptance |
| Settings/BYOK | Encrypted key CRUD without echo, validate/revoke, no unintended platform fallback, provider callbacks/tickets owner binding, preferences persistence | QA + SEC; BYOK/provider/Settings suites |
| Developer/TUI/MCP/action/extension | Existing key owner policy, scopes/limits/errors, supported package install/version, headless CLI, explicit extension import/autofill, retries/idempotence | ENG + QA; package jobs; npm publisher status separate |
| Offline/PWA/mobile | Install/update/old worker, offline source/PDF, reconnect, owner switch/signout purge, screen keyboard, rotation, safe area and zoom | QA; PWA/offline specs, actual devices separately |

## 6. Compilation, latency and cost

- [ ] Cover pdfLaTeX/XeLaTeX/LuaLaTeX only where supported by the approved renderer;
  compiler/image/font/trusted-format/options all participate in cache identity.
- [ ] Bind immutable accepted PDF, SyncTeX and geometry to source revision/hash;
  output may not become current after supersession, cancellation or owner change.
- [ ] Test one running/one replaceable pending preview, manual/automatic overlap,
  interrupted stream, reconnect and terminal recovery without duplicate billing.
- [ ] Validate multi-pass/auxiliary convergence, warnings, missing glyphs, invalid PDF,
  timeout, output cap, renderer exit and cleanup in approved functional fixtures.
- [ ] Independently authorized renderer boundary certification is retained separately;
  ordinary compile permission or a configuration tuple never substitutes for it.
- [ ] Instrument action → API preparation/admission → dispatch → queue wait → worker
  initialization → source preparation → TeX passes → output validation → concurrent
  artifact uploads → acceptance/publication → download → browser first paint.
- [ ] Use one clock domain per duration or explicit correlation; do not double-count
  overlapping stages, assume queue zero, or call download completion first paint.
- [ ] Separate synthetic instrumentation overhead from user-perceived latency. Keep
  real rendered artifact identity/hash; never refetch and label it original capture.
- [ ] Benchmark same source/template/compiler/settings/image, fixed resource profile,
  cache state and concurrency for old/new comparisons. Report raw samples, sample
  size, p50/p95/max, failure rate, warmup policy and confidence/limitations.
- [ ] Measure cold process/VM, warm uncached, exact cache hit, saved owner and guest,
  ordinary/heavy documents, burst/overlap and cancellation. Include first job.
- [ ] Retain the dated 18.823s guest / 57.736s overlapping saved-editor production
  baseline and unresolved local regression in #1820; do not replace it with
  direct-TeX time or a mocked browser timing.
- [ ] PRODUCT approves end-to-PDF latency targets; existing API p95 <2s and service
  SLOs are distinct. Tune pool/region/concurrency only after measured bottlenecks
  and a bounded cost/capacity decision, not by guessing production settings.
- [ ] Confirm no duplicate provider charges, render jobs or uploads from retries;
  metered accepted failure receives one refund, uncertain owned work is not refunded.

## 7. Dodo-only billing and commercial readiness

Dodo is the only active provider. Historical ledger preservation is not a legacy
provider fallback. Use [BILLING_DODO.md](BILLING_DODO.md), not a fabricated live setup.

- [ ] Safe-disabled mode passes startup, complete read-only schema/aggregate checks,
  recognized lineage, historical access cutover and existing-Dodo servicing needs.
- [ ] Existing live/pending subscriptions/intents remain serviceable with new sales
  disabled. Cancellation/recovery are authenticated and owner-bound.
- [ ] Live merchant, offered product IDs, amount/currency/tax-inclusive quote,
  recurrence/duration and exact SKU grants match the immutable local quote.
- [ ] Checkout return URL never grants paid access by itself. Signed webhook and
  authenticated provider reconciliation verify customer/product/intent identity.
- [ ] Cover duplicate/reordered/retried webhooks, immutable event identity, signature
  age/body errors, inbox crash recovery and parallel coupon reservation.
- [ ] Test upgrade/downgrade/renewal/past-due/cancel/expire and one-time lifetime
  separately. Family/SKU capability and quota snapshots remain correct.
- [ ] Verify refund/partial refund/failed refund/duplicate refund handling and access
  effect under separately approved sandbox/live transactions and spending bounds.
- [ ] Production rejects test-mode keys; test/live modes cannot mix. Missing keys do
  not justify enabling test billing or asserting live acceptance.
- [ ] BILL approves receipts/invoices/tax/refund/support/cancellation disclosures and
  merchant-of-record wording; LEGAL verifies contract/public copy consistency.
- [ ] Only accepted SKUs appear purchasable; disabled purchases show a clear state
  without broken buttons. Returning customers retain appropriate servicing.

## 8. Security, privacy, auth and data ownership

This checklist contains outcomes, not credentials or exploit instructions.

- [ ] Reconfirm historical exposed-account remediation privately; disable/rotate and
  invalidate affected sessions as authorized, retain nonsecret attestation.
- [ ] Email/OAuth/MFA/passkey/reset/recovery use actual intended domains/callbacks,
  session/cookie policy and owner binding; account changes invalidate stale work.
- [ ] Exercise ordinary cross-owner and role-denied reads/writes across resumes,
  versions, jobs, artifacts, comments, teams, tenants, exports and public links.
- [ ] Source/CAS/builder detachment, generation/owner fencing and concurrent saves
  retain user content; no stale callback overwrites another document or owner.
- [ ] Public sharing is opt-in, redaction is fail-closed and original private objects
  remain private. Validate intended URL expiry and deletion/retention behavior.
- [ ] Logs, traces, telemetry and error reports omit source, prompts, personal fields,
  provider keys and credential-derived reversible/unkeyed identifiers.
- [ ] No session-recording SDK on document surfaces; consent/accessibility and
  security controls remain reachable when optional features are disabled.
- [ ] Current dependency audit/CodeQL/privacy gates pass without suppression or
  unsafe version overrides; pending dependency PRs are evaluated, not bulk-merged.
- [ ] Upload/archive/parser limits and trusted source URL import boundaries have
  reviewed tests. Run any adversarial isolation probes only within separately
  authorized scope; no existing restriction is overridden by this checklist.
- [ ] LEGAL validates Terms, privacy, retention/deletion/export process, subprocessors,
  data residency statements, support/privacy contacts and incident obligations.
- [ ] Verify actual deletion/export requests and backup-retention handling according
  to published process; never promise nonexistent self-service deletion.

## 9. Operations, migrations, rollback and resilience

- [ ] One recognized Alembic head; upgrade representative prior supported revisions
  on disposable databases; preserve financial history, ownership and grants.
- [ ] Test downgrade refusal where data loss is unsafe. Rollback need not mean a
  destructive schema downgrade; retain compatible code/image rollback plan.
- [ ] Freeze exact tested source, then input validation → billing preflight → renderer
  preflight → migrations → backend deploy → health/catalog verification in order.
- [ ] Check automatic frontend delivery independently. With backend held, optional
  UI must give clear unavailable states, preserve recovery, and not assume a
  successful matching backend deploy because Vercel is green.
- [ ] Verify current Redis queue/cache bindings without exposing URLs or credentials;
  authoritative monthly capacity, error rate and burn alerts have an owner.
- [ ] Investigate command load from HTTP admission, job polling, streaming events,
  maintenance and cold-start PINGs. Application counters are partial; batching
  network requests does not prove reduced provider billable commands.
- [ ] Pre-agree exhaustion response and spend approvals. Do not run MONITOR on user
  traffic or rotate databases casually: in-flight jobs/tickets/counters can be lost.
- [ ] Capture DB backups/PITR plus object-store consistency, encryption/access,
  retention, destination and success alerts. Local gzip integrity is not restoration.
- [ ] Exercise restore into an isolated target, verify representative rows/artifact
  identities, RPO/RTO and application startup, then clean up authorized test data.
- [ ] Restore tooling refuses destructive continuation if safety backup/compression
  or recreation fails and detects SQL statement failures. Actual restore remains
  a separately approved operational action, not part of routine tests.
- [ ] Test worker crash/restart/duplicate dispatch/lease expiry, storage failure,
  Redis loss, DB pool saturation, mail queue recovery and external-provider outage.
- [ ] Verify scheduled cleanup/retention never removes active owned artifacts and
  retry/dedupe permits bounded recovery without unbounded background work.
- [ ] SLOs, alert delivery/on-call acknowledgement, useful dashboards and incident
  runbooks work in the actual deployed topology. A checked-in dashboard is not live.
- [ ] Dependency work uses pinned/reproducible lock generation, patch integrity,
  clean install, minimum supported Node/Python, scoped review and exact-head CI.
  Next's vendored renderer patch must survive upgrades with paired causal proof.

## 10. Accessibility, mobile, SEO and GEO

- [ ] Keyboard-only core journey, semantic names/headings, focus return/traps,
  validation announcements, contrast, high-contrast and 200–400% zoom accepted.
- [ ] Named screen-reader/browser combinations tested (not inferred from ARIA or
  automated scan); PDF textual accessibility limitations disclosed separately.
- [ ] Reduced-motion preference covers JavaScript transforms and CSS animations;
  no essential workflow relies on animation or pointer-only dragging.
- [ ] Actual narrow device keyboard/rotation/touch, PDF toolbar, dialogs and long
  names/errors accepted. Browser emulation alone is not real-device evidence.
- [ ] Public canonical URLs, per-page titles/descriptions/OG assets and robots/sitemap
  agree with intended domain and public/private route ownership.
- [ ] Private/app/auth/recovery pages return appropriate noindex directives. Robots
  disallow is not access control and can prevent crawling a later noindex; verify
  existing index removal independently rather than promise immediate deindexing.
- [ ] Sitemap contains reachable public destinations, not login-only tools. Public
  portfolio/share discoverability follows explicit product/user publication policy.
- [ ] Structured data matches visible factual content; no invented ratings, catalog
  totals, prices, legal entity or ATS/employment outcomes.
- [ ] GEO/agent-readable pages and llms.txt accurately describe scope, citations,
  account requirements and supported integrations. No promise of search/AI ranking.
- [ ] Reconcile public release notes, FAQ, Terms and privacy; historical no-training,
  performance or unlimited-plan statements need current substantiation.
- [ ] Validate redirects/404s, crawl/rendered HTML, social preview images and target
  Search Console ownership/indexing through existing authorized operator access.

## 11. Verification commands and safe evidence collection

Run from a clean checkout of the final source with the documented local isolated
stack and supported Node 22 / pnpm 10 / Python environment. See
[local-dev.md](local-dev.md), [CI policy](CI.md) and the workflow's exact commands.
Never point these tests at production. The repository's test fixtures may clean
reserved test databases, so the `_test` database and dedicated Redis DBs are
mandatory. Do not copy a production `.env` into a test checkout.

```bash
# Static privacy/claim guards, no providers
bash scripts/ci/no-session-recording.sh
bash scripts/ci/no-plaintext-credentials.sh
bash scripts/ci/no-unsubstantiated-marketing-claims.sh
node --test scripts/ci/classify-changes.test.mjs

# Frozen dependencies and frontend contract
pnpm install --frozen-lockfile
pnpm --dir frontend verify:next-hydration
pnpm --dir frontend test:unit
pnpm --dir frontend exec tsc --noEmit --incremental false
pnpm --dir frontend lint
pnpm --dir frontend build

# Backend with documented isolated PostgreSQL/Redis services
make test-backend
# Select no-infrastructure suites only when their fixtures do not need services.
# Never set SKIP_INFRA_CHECK to manufacture a full integration pass.

# Existing production-bundle browser contracts (synthetic API fixtures)
cd frontend
pnpm exec playwright test --config=playwright.capabilities.config.ts --workers=1 --retries=0
pnpm test:quality --retries=0
# Also run the exact editor/Settings/hydration/real-preview/full-stack commands
# selected by .github/workflows/ci.yml, then the feature-specific specs changed.
```

- [ ] Save terminal pass/fail/skip counts, command, source SHA, dependency/runtime
  versions, fixture provenance, browser projects and artifact digest.
- [ ] Preserve original failure and regression red→green proof; classify environment
  limits explicitly. Borrowed dependencies and mocked providers are limited evidence.
- [ ] No empty fixture matrix, all-skipped run or diagnostic retry can satisfy a gate.
- [ ] Before merge, inspect the current main delta and rerun impacted checks; before
  release, verify actual serving identities and feature/provider behavior again.

## 12. Sign-off template

| Item | Named owner | Date / source and runtime | Evidence | Decision |
|---|---|---|---|---|
| Scope / deferred capabilities / language limits | Unassigned | Pending | Pending | HOLD |
| All offered feature controls + roles/plans | Unassigned | Pending | Per-ID matrix | HOLD |
| Core guest and saved-owner journeys | Unassigned | Pending | Pending | HOLD |
| Renderer / migrations / deployment parity | Unassigned | Pending | L01–L03 | HOLD |
| Identity remediation / privacy / Terms | Unassigned | Pending | L04/L12 | HOLD |
| Capacity / recovery / alerts / support | Unassigned | Pending | L05/L08 | HOLD |
| Paid billing (only for paid release) | Unassigned | Pending | L13 | HOLD |
| Performance / accessibility / mobile / discovery | Unassigned | Pending | L09–L11/L14 | HOLD |

Release approval must name what was actually accepted, the remaining risks and
any limited beta audience. This checklist itself does not approve a deployment,
financial transaction, credential change or production data operation.
