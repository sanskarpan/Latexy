# Frontend routes and third-party integrations

Audit: Latexy production audit, branch `audit/production-2026-11-27`.
Source: code at deployed SHA `d2cbc51ab8c25106d073e0e0065b985fc6dc6490` (audit-doc HEAD `f9e34fa6` is docs-only).
Live probes: 2026-11-27 10:34-11:00 UTC, read-only. No config, user, content or provider state was changed. One exception is noted for transparency: a single `POST /api/auth/request-password-reset` for the nonexistent `audit-nonexistent@example.test` was used to detect the production email-provider guard; no account existed, so no message could be delivered. All other state-changing endpoints were avoided.
Identities: read-only admin GETs used audit identity `8b2ee54b-a2ee-4009-9eee-4cc995b3d2ad` (`audit+admin-superadmin-20261127103328@example.test`, role `admin`). No secrets are reproduced in this file.

## Counts

| Surface | Count | Notes |
|---|---:|---|
| App Router `page.tsx` routes | 44 | Matches the prompt's expected 44 |
| Admin tabs | 22 | Query-param tabs under `/admin?tab=...`; 21 admin-only, Customers also support |
| App Router `route.ts` handlers | 12 | Auth, BYOK proxy, deployment identity, dev preview, extension, referral, llms.txt |
| Metadata/static routes | 4 | `sitemap.xml`, `robots.txt`, `manifest.json`, `offline.html` |
| `frontend-routes.csv` rows | 82 | 44 pages + 22 tabs + 12 handlers + 4 metadata |
| Integration rows | 19 | 3 identity OAuth/OIDC, 5 content integrations, 4 billing/email/analytics, 5 infrastructure/data, 2 AI/reference. Status: 10 live-configured, 2 explicitly not configured, 7 enabled-but-unverified/partial |
| Protected pages | 23 | `useRequireAuth`; client gate + backend 401, no server middleware auth |
| Public pages | 17 | Marketing, auth entry, share, portfolio, legal |
| Optional-auth pages | 2 | `/try` (guest editor), `/verify-email` (token landing) |
| Role-gated pages | 2 | `/admin` (admin/support), `/admin/tenant` (admin/team owner) |

Live availability: all 44 page routes return HTTP 200; `/contact` and `/documentation` return 404. Protected pages return a 200 shell because authentication is enforced client-side by `useRequireAuth` (`frontend/src/hooks/useRequireAuth.ts:37-46`) and by backend 401/403, not by Next middleware (`frontend/src/middleware.ts:62-142` only handles tenant/portfolio host routing).

## Top findings

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| FE-01 | P2 | Editor References tab cannot start Zotero or Mendeley OAuth. `ReferencesPanel` opens `GET ${API_BASE}/zotero/connect` and `GET ${API_BASE}/mendeley/connect`, but both backend routes are POST-only. Live GET returns 405. Settings works, so a workaround exists. | `frontend/src/components/ReferencesPanel.tsx:324,545`; `backend/app/api/zotero_routes.py:162`; `backend/app/api/mendeley_routes.py:112`; live `GET /zotero/connect` 405, `GET /mendeley/connect` 405 (2026-11-27) |
| FE-02 | P2 | No read-only way to prove Google Drive, GitHub repo, Dropbox, Zotero or Mendeley credentials are configured. All five capabilities are enabled and the UI offers Connect, but credentials are only checked inside the connect handler. Default callback URIs are localhost or empty, so an unset production env breaks OAuth only after the user clicks, with a 503. | `backend/app/core/config.py:211-221,659-674`; config guards `google_drive_routes.py:218-228`, `dropbox_routes.py:154-158`, `github_routes.py:155-159`, `zotero_routes.py:172-176`, `mendeley_routes.py:122-126`; live `/admin/analytics/integrations` has 0 connections and 0 events over both 30d and 365d |
| FE-03 | P2 | `/admin/tenant` has no navigation entry anywhere in the frontend. Platform admins and team-plan owners must know the URL; GlobalHeader only links `/admin`. | `frontend/src/app/admin/tenant/page.tsx:563-582`; `frontend/src/components/GlobalHeader.tsx:357-364,503-511`; repo-wide link scan finds no `href="/admin/tenant"` |
| FE-04 | P1 | Transactional email is materially degraded and unreconciled. Admin email health reports 107 sent, 79 delivered (79%), 20 bounced (20%), 1 complaint and 199 delayed in 30 days, while the outbound ledger reports 0. Password reset and verification depend on this path. Sample includes owner/test traffic and must be rechecked excluding the audit cohort. | Live `GET /admin/email/health` 2026-11-27T10:53Z; `frontend/src/lib/email.ts:102-114`; `backend/app/api/email_webhook_routes.py:23-38` |
| FE-05 | P2 | Dodo billing health is degraded: five failed webhooks, all unacknowledged, from 2026-11-20, with "Subscription/Payment did not match a local checkout intent". 0 payments in 30 days; 9 active subscriptions are audit comps. | Live `GET /admin/billing/webhooks?days=30`, `GET /admin/operations/health` 2026-11-27T10:52-10:53Z |
| FE-06 | P3 | `/workspace/cover-letters` is orphaned. No page or component links to the library; only the per-resume `/workspace/[id]/cover-letter` flow is linked from the workspace card menu. | `frontend/src/app/workspace/page.tsx:753-754`; repo-wide link scan |
| FE-07 | P3 | `HelpCenter` is dead code (never imported) and links to `/contact` and `/documentation`; both are 404 in production. | `frontend/src/components/help/HelpCenter.tsx:333,340`; live 404 `/contact`, `/documentation` |
| FE-08 | P3 | Dead client code: `getArtifactManifest` calls `/download/{job_id}/preview/manifest`, which is not in the source OpenAPI schema; it has zero call sites. `getResumeGitHubStatus` and `getResumeDropboxStatus` also have zero call sites. | `frontend/src/lib/api-client.ts:8897`; `audit/inventory/openapi-source.json` has only `/download/{job_id}/preview/{artifact_id}` and `/download/{job_id}/preview/{artifact_id}/geometry`; usage scan |
| FE-09 | P3 | GitHub sign-in is not configured while Google is. Live `/api/auth/providers` returns `github:false`; the button is hidden, so there is no error, but there is also no explanation. | Live `GET /api/auth/providers`; `frontend/src/components/auth/SignInForm.tsx:262-296` |
| FE-10 | P3 | Server-side PostHog capture is unverified. Browser PostHog is configured (consent banner renders), but no public/admin read-only endpoint exposes `POSTHOG_API_KEY`, and server capture silently no-ops without it. | `frontend/src/lib/analytics/posthog.ts:46-49,100-128`; live home page renders the consent banner; `backend/app/services/posthog_service.py:160-232` |
| FE-11 | P3 | `sitemap.xml` lists only seven marketing URLs and omits `/accessibility`, `/privacy`, `/terms`, `/login` and `/signup`. | `frontend/src/app/sitemap.ts:5-13`; live `/sitemap.xml` |
| FE-12 | P3 | No server-side auth middleware: every protected route returns a 200 HTML shell to an unauthenticated caller. Data remains protected by API 401s, but route-level HTTP checks cannot prove auth and the shell is indexable unless route-level metadata blocks it. | Live probes of all 23 protected pages returned 200; `frontend/src/middleware.ts:62-142`; `frontend/src/hooks/useRequireAuth.ts:37-46` |

## Production configuration status

| Surface | Observed 2026-11-27 | Status |
|---|---|---|
| Frontend deployment | `/api/deployment-identity` -> `d2cbc51ab8c25106d073e0e0065b985fc6dc6490`, source `vercel` | Live, matches checkout |
| Page routes | 44/44 returned 200; `/contact` and `/documentation` returned 404 | Live |
| Google Sign-In | `/api/auth/providers` `google:true` | Configured |
| GitHub Sign-In | `/api/auth/providers` `github:false` | Not configured |
| Institutional OIDC | `/api/auth/providers` `oidc:null` | Not configured |
| Dodo Payments | `/subscription/plans` `provider:dodo`, `mode:enabled`, `available:true`; production-like guard requires live mode; 5 failed webhooks | Live, degraded |
| Resend | Reset probe for a nonexistent address returned 200 (not the 503 no-key guard); DKIM TXT at `resend._domainkey.latexy.xyz`; DMARC `p=quarantine`; admin email health provider `resend`, Svix signature configured | Configured, degraded delivery |
| PostHog browser | Home page server-renders "Help us improve Latexy" consent banner, which only renders when a key is configured | Configured |
| PostHog server | No observable signal | Unverified |
| Modal | `/health` `deployment_target:modal`; admin operations health lists Modal and one healthy modal worker | Live |
| Neon Postgres | `/readyz` and `/health` database ok; admin operations health lists Neon Postgres | Live |
| Upstash Redis | `/health` `provider:upstash`, configured true, 1,913,497 monthly requests, request limit unset/unbounded | Live, capacity unset |
| Cloudflare R2 | `/health` storage ok; admin operations health lists Cloudflare R2 | Live |
| Vercel | Deployment identity source `vercel` | Live |
| Google Drive | Capability `g06` enabled; 0 connected accounts; 0 OAuth/sync events in 365d; credentials unverified | Enabled, unverified |
| GitHub repo sync/import | Capabilities `g01`/`g02` enabled; 0 connected accounts; 0 OAuth/sync events in 365d; credentials unverified | Enabled, unverified |
| Dropbox | Capability `g05` enabled; 0 connected accounts; 0 OAuth/sync events in 365d; credentials unverified | Enabled, unverified |
| Zotero | Capability `g07` enabled; 0 connected accounts; 0 OAuth/import events in 365d; credentials unverified | Enabled, unverified |
| Mendeley | Capability `g08` enabled; 0 connected accounts; 0 OAuth/import events in 365d; credentials unverified | Enabled, unverified |
| LLM platform keys | Public BYOK provider catalog works; 30-day AI usage totals are 0, so no live call proves the platform key | Unverified |
| ORCID | Public iD lookup route (`POST /references/fetch-orcid`) with optional capability gate; no ORCID OAuth or credentials | Available |

Notes:

- The five consumer-integration capabilities are enabled for all plans and roles in `audit/inventory/capabilities.csv` (g01, g05, g06, g07, g08), and live `/config/entitlements` returns them true. Capability enablement therefore does not prove provider credentials.
- Over 365 days, live `/admin/analytics/integrations` reports zero connected accounts, zero OAuth starts/completions and zero sync/import events for GitHub, Dropbox, Google Drive, Zotero and Mendeley. None of the five has been exercised in production, so the provider paths have no acceptance evidence.
- `AdminIntegrations` reports connected accounts and allowlisted OAuth/sync telemetry only; it has no "credentials configured" field (`frontend/src/components/admin/AdminIntegrations.tsx:73-180`, `backend/app/api/admin_integration_routes.py:28-50`).
- A connect probe was deliberately not executed: it would write Redis OAuth state and an integration telemetry event, violating the read-only brief. Provider credential presence is therefore **blocked**, not absent.

## Integration UI entry points

| UI surface | Providers | Action | Source |
|---|---|---|---|
| `/login`, `/signup` | Google, GitHub, OIDC | Social sign-in, provider discovery via `/api/auth/providers` | `frontend/src/components/auth/SignInForm.tsx:102-116,262-296`; `SignUpForm.tsx:213` |
| `/settings` | GitHub, Zotero, Mendeley, Dropbox, Google Drive | Connect / disconnect / status; OAuth completion landing | `frontend/src/app/settings/page.tsx:1514-1912` |
| `/workspace/[id]/edit` | GitHub, Dropbox | Per-resume enable/push/pull; GitHub project import; References tab | `frontend/src/app/workspace/[resumeId]/edit/page.tsx:2496-2632,4944,5306` |
| `/workspace`, `/workspace/builder/[id]`, `/workspace/variant/[id]` | Google Drive | PDF export to Drive via `ExportDropdown` | `frontend/src/components/ExportDropdown.tsx:32,209-219`; `workspace/page.tsx:804` |
| `/workspace/[id]/optimize` | Zotero, Mendeley | Publications/reference import panel | `workspace/[resumeId]/optimize/page.tsx:1140`; `frontend/src/components/ReferencesPanel.tsx:1091-1103` |
| `/try` | GitHub | Public project import modal for the guest editor | `frontend/src/app/try/page.tsx:52,1622`; `ImportProjectsModal.tsx:117-158` |
| `/billing` | Dodo | Checkout, coupon, student verification, team seats | `frontend/src/app/billing/page.tsx:202-676` |
| `/developer` | Latexy API keys | Key lifecycle and examples | `frontend/src/app/developer/page.tsx:56-166` |
| Admin > Product | GitHub, Dropbox, Google Drive, Zotero, Mendeley | Adoption, OAuth conversion, sync health | `frontend/src/components/admin/AdminIntegrations.tsx` |
| Admin > Email Health | Resend / Svix | Delivery, bounce, complaint, delay events | `frontend/src/components/admin/AdminEmailHealth.tsx` |
| Admin > Analytics / Quality / Replays | PostHog | Link-outs to dashboards, replays and saved insights | `AdminQualityTriage.tsx`, `AdminReplayBrowser.tsx`, `AdminPostHogInsights.tsx` |

## Missing routes and dead entries

| Entry | Type | Status | Evidence |
|---|---|---|---|
| `/contact` | Missing page | 404 live; linked from dead HelpCenter | `frontend/src/components/help/HelpCenter.tsx:333`; live 404 |
| `/documentation` | Missing page | 404 live; linked from dead HelpCenter | `frontend/src/components/help/HelpCenter.tsx:340`; live 404 |
| `GET /zotero/connect` | Wrong method | 405 live; ReferencesPanel uses it | `ReferencesPanel.tsx:324`; `backend/app/api/zotero_routes.py:162` |
| `GET /mendeley/connect` | Wrong method | 405 live; ReferencesPanel uses it | `ReferencesPanel.tsx:545`; `backend/app/api/mendeley_routes.py:112` |
| `/download/{job_id}/preview/manifest` | Missing backend route | Not in OpenAPI; client method unused | `frontend/src/lib/api-client.ts:8897`; `audit/inventory/openapi-source.json` |
| `/admin/tenant` | Orphan route | No inbound link | `frontend/src/app/admin/tenant/page.tsx`; link scan |
| `/workspace/cover-letters` | Orphan route | No inbound link | `frontend/src/app/workspace/cover-letters/page.tsx`; link scan |
| `getResumeGitHubStatus`, `getResumeDropboxStatus` | Unused client methods | Zero call sites | `frontend/src/lib/api-client.ts`; usage scan |
| `HelpCenter` | Unmounted component | Never imported | `frontend/src/components/help/HelpCenter.tsx`; usage scan |

## Config gaps and risks

1. **Provider callback defaults are unsafe.** `GOOGLE_DRIVE_REDIRECT_URI`, `GITHUB_OAUTH_REDIRECT_URI` and `DROPBOX_REDIRECT_URI` default to `http://localhost:8030/...`; `ZOTERO_REDIRECT_URI` and `MENDELEY_REDIRECT_URI` default to empty (`backend/app/core/config.py:211-221,659-674`). `FRONTEND_URL` defaults to `http://localhost:5180` (`config.py:229`). Nothing validates these at boot, and the capability catalog marks all five enabled. If production omitted any value, Connect fails with 503 or redirects to localhost.
2. **No config status surface.** The admin UI can see adoption and sync health but not whether the five provider credential pairs are present. A provider with zero connections is indistinguishable from an unconfigured provider.
3. **Integration popup base URL is build-time.** ReferencesPanel uses `NEXT_PUBLIC_API_URL` directly for `window.open`. If a deployment sets that to a relative prefix (`/api`, as documented for one topology), the popup hits the Next app, not the FastAPI host. This is masked in production only if the env is an absolute URL.
4. **GitHub identity and GitHub repo sync are separate configurations.** GitHub sign-in is disabled in Vercel while backend GitHub repo sync may be configured in Modal. A historical audit also flagged one GitHub OAuth app being shared by sign-in and repo sync with different callback URLs; if GitHub sign-in is enabled later, confirm the callback registration. Source: `docs/audit-artifacts/audit2_result.json:29`.
5. **Resend domain is set up but delivery is unhealthy.** DKIM and DMARC exist, and the API key is present, yet the 30-day window shows 20% bounce, 1 complaint and 199 delayed events against 107 sent. The outbound ledger records 0, so admin cannot reconcile provider events to sends.
6. **Dodo has unresolved webhook state.** Five failed events remain unacknowledged for seven days, with no local checkout link. Billing availability is live, but webhook health is degraded.
7. **PostHog split-brain risk.** Browser capture is configured; server capture is unverified. Admin dashboards that link to PostHog can look healthy while server-side business events are absent.
8. **Upstash capacity limit is unset** while 1.9M monthly requests are recorded. This is the #1628 risk: no enforceable ceiling and no pre-exhaustion alarm from the public health payload.
9. **No `NEXT_PUBLIC_POSTHOG_PROJECT_ID` / insight ID verification.** Admin Quality and Replays are link-out-only. If project or insight IDs are blank, operators get draft links, not data.
10. **Sitemap/SEO omission.** Legal and accessibility pages are indexable but not listed in `sitemap.xml`.
11. **Capability UI-entry inventory is incomplete.** `audit/inventory/capabilities.csv` lists only `/settings` for g06, g07 and g08, but Google Drive export is also in `ExportDropdown`, and Zotero/Mendeley connect is also exposed (broken) in `ReferencesPanel`. The catalog understates the integration UI surface.

## Admin tab map

All 22 tabs live under `/admin?tab=<id>` and are described row-by-row in `frontend-routes.csv`. Access:

- `admin`: 21 tabs.
- `admin` or `support`: `customers` only. Support users do not see Analytics, Billing, Privacy, Flags, Matrix, Plans or Audit.
- Default tab is `matrix` for admins and `customers` for support (`frontend/src/app/admin/page.tsx:951`).
- `/admin/tenant` is a separate route, not a tab, and has no nav entry.

## Coverage and blockers

Covered:

- Every `page.tsx` in `frontend/src/app/**` (44), every admin tab (22), every `route.ts` handler (12), metadata routes (4).
- Client auth guards, capability route gates, OAuth start/complete/disconnect/status calls, integration UI entry points, callback landing behavior.
- Live route availability, provider booleans, plan/billing availability, admin integration telemetry, admin email health, Dodo webhook health.

Blocked:

- Google Drive, GitHub repo, Dropbox, Zotero and Mendeley credential presence: requires an authenticated connect probe or provider console/Modal secret access. Connect probes would write Redis OAuth state and telemetry and were not run under the read-only rule.
- Exact production redirect URI values for those five providers: not exposed by any public/admin GET.
- Server-side PostHog key and LLM platform keys: no read-only status endpoint.
- Provider-side app review/scopes (Google Drive consent screen, Dropbox app permissions, Zotero/Mendeley app registration): no console access in this scope.
- Real OAuth consent/denial/refresh tests: blocked by read-only rule and absence of disposable external provider accounts.
