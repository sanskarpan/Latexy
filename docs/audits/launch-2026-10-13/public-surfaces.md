# Latexy public surfaces and first-use launch audit

Date: 2026-10-13. Source baseline: `c24531e2` on main.

## Verdict and evidence boundary

Public positioning is substantially more conservative than the older audits: the homepage does not promise a sub-second end-to-end compile or guaranteed ATS/hiring results, and privacy explicitly describes provider transmission, persisted saved documents, trial signals, first-party telemetry and the absence of self-service account deletion. Do not reopen the corrected privacy or Google-sign-in issues based on older documents. Successful fresh Google login acceptance was supplied dated October 7; the older unchecked acceptance list in `docs/qa/GOOGLE-OAUTH-1830-2026-10-07.md` is superseded historical evidence.

Launch still needs a terms/support-owner reconciliation, final-head real-browser acceptance, and named accessibility/integration acceptance. Source inspection is not evidence of a working production grant, screen reader, mobile keyboard, PWA update, or support mailbox. This audit performed no external account, credential, security probe, configuration, provider, payment or production write.

Fresh final focused local check: **85 tests in nine files passed**, using an existing diagnostic Vitest 4.1.11 dependency runtime. Node host is 24.19.0, not the declared 22.x; the diagnostic runtime contains Better Auth 1.6.25 while main requests 1.7.7. These source/renderer/hook checks are therefore bounded diagnostic evidence, not a frozen-lock final-build/auth-upgrade certification. No fresh real-browser run was performed for this audit. Final aggregate checks remain required on the exact candidate in CI.

## Inventory and launch scenarios

| Surface | Inventory / implementation | Launch scenario / acceptance evidence required |
| --- | --- | --- |
| Landing and product | `/`, `/platform`, `/pricing`, `/resources`, `/faq`, `/updates`; layout and marketing components | Fresh guest visit, capability-disabled visit, light/dark, narrow viewport, keyboard CTAs, JS failure, first draft. Verify deployed metadata/OG image, same-origin canonical links and truthful plan/usage copy. |
| Discovery | `app/robots.ts`, `app/sitemap.ts`, `app/llms.txt/route.ts`, `lib/site-url.ts`, homepage SoftwareApplication and FAQ JSON-LD | Public sitemap lists reachable public destinations. Private/account/recovery routes excluded from indexing. Actual configured origin retained. Structured FAQ is identical to visible copy. No fictitious ratings/outcome promises. |
| Template gallery | `/templates`, `TemplateCard`, `TemplatePreviewModal` | Load/empty/error/retry; category/search; preview/Escape; guest template into studio; authenticated use; user switch while template/create promise pending. Current page fetches catalog client-side: not server-rendered catalog content. |
| Anonymous studio | `/try` and layout | Sample → ordinary typing → reload recovery → source/visual switching → PDF preview/export; quota exhaustion; provider unavailable; fallback older backend; import auth gate; cancel/retry; new request supersedes old; no stale PDF export. |
| Auth and recovery | `/login`, `/signup`, `/forgot-password`, `/reset-password`, `/verify-email`, `/two-factor`, `/tenant-invite`; `components/auth/*`, `lib/auth.ts` | Email signup/login/reset/verification delivery, Google cancel/complete, password mismatch/error focus, safe preserved destination, passkey/2FA fallback, expired link, sign-out then reload; transient session lookup must not evict a valid user. Fresh auth upgrade acceptance on final build still required. |
| Onboarding | `components/onboarding/OnboardingFlow.tsx`, `/workspace` | New user first visit, skip/reopen/completion across reload; catalog limits; failure/retry; A→B→A and token rotation while completion is pending; focus trap/Escape/body scroll lock. |
| Saved workspace/builder | `/workspace`, `/workspace/new`, `/workspace/builder/*`, `/workspace/[id]/*`, `/workspaces/*` | Create → edit → save/reload → PDF/output; interrupted save/conflict; exact ownership; builder fields preserved when capability revoked; import parse/review; Back/Forward; mobile focus and on-screen keyboard; no cross-account drafts/PDFs. |
| Settings/integrations | `/settings`, `/byok`, `/developer`; source API routes and `lib/provider-oauth*` | Status error/empty distinguishable; connect/cancel/complete/disconnect; stale callbacks/tickets fail closed; reconnect expired token; disabled capability retains disconnect/recovery; narrow viewport long identity/error strings. Live grants need separate authorized acceptance. |
| Public output | `/r/[token]`, `/u/[username]`; custom-domain middleware | Explicit publish/revoke; anonymous redaction pending/failure does not release original PDF; readable HTML alternative; disabled portfolio; expired share; configured-domain serving/canonical and crawl policy. No inference that public sharing is a privacy default. |
| Help, legal, support | `/privacy`, `/terms`, `/accessibility`, footer mailto links | Legal copy agrees with actual storage, trial, billing and current entity; accessible server render; correct mailbox ownership, delivery and published response commitments. Contact paths exist in source but were not tested. |
| PWA/mobile | manifest/icons/offline.html, PWA hook, production config, offline storage | Installed app launch, update/service-worker activation, offline edit/reload/reconnect, sign-out/account-switch purges, viewport/zoom/keyboard/safe-area. Mocked quality suite explicitly blocks service workers and is not PWA lifecycle acceptance. |

## Confirmed defects and ownership

### PUB-01 — P1: Terms contradict actual trial/quota/storage behavior and retain a legal placeholder

Owner: product/legal/billing owner, with engineering verifying exact effective behavior. Source: identical `legal/terms-of-service.md` and `frontend/public/legal/terms-of-service.md`; served via server component `components/marketing/LegalDoc.tsx`.

- Lines 50–51 say trial usage resets every 24 hours and converting to a paid plan removes all usage limits. `backend/app/core/config.py` explicitly describes the anonymous device trial as three lifetime uses (around line 884); enforced `PLAN_QUOTAS` retains Basic compilation/optimization limits. The Terms' own Basic plan also says 400/10 at lines 37–39.
- Line 86 says résumé content is processed for optimization but not stored permanently. Saved `Resume` records and the corrected privacy policy's retention section intentionally persist saved work while the account remains active/until deletion. The ambiguous Terms sentence misleads about that designed persistence.
- Line 155 still exposes `[Company Address]`. Line 174 lists `https://latexy.com`, whereas the actual canonical marketing/identity domain is `https://latexy.xyz`.
- Fixed INR monthly prices currently match static defaults, so **no current price mismatch is asserted**. However the Terms omit annual/student/team/operator-configured SKUs, assert monthly-only billing, and pin old model families. Reconcile contracts with the effective catalog and merchant-of-record/refund process before a paid public launch; do not fabricate a legal entity, SLA, refund promise or retention deadline in a mechanical patch.

Completion: legal owner approves replacement terms, both copies remain identical, final served page is verified, effective date/notification/consent requirements are considered. This audit does not authorize rewriting or accepting legal terms.

### PUB-02 — P2: Private/account recovery indexing policy is incomplete

Owner: frontend/SEO. Baseline `frontend/src/app/robots.ts:9–20` disallows `/workspace/` and `/admin/` but misses their exact roots; `/workspaces`, `/byok`, `/tracker`, `/developer`, `/forgot-password`, `/two-factor`, `/tenant-invite` are absent. No app/recovery `robots: noindex` metadata or response header exists in baseline; only the developer email-preview API has X-Robots-Tag.

Impact: unwanted crawling/indexed application shells or invitation/recovery URLs. This is a crawl-policy defect, **not evidence of authentication bypass or leaked user documents**. Robots exclusions cannot guarantee deindexing; crawlers must receive the noindex response directive. Do not block real OAuth API operation or add noindex to intentionally public portfolio/share pages as a side effect.

Narrow source repair is implemented: central exact-root/descendant classification, app/auth X-Robots-Tag on actual middleware response paths, aligned robots coverage, public preservation tests. The original `/r/` robots exclusion is preserved; no new noindex is applied to `/r/*` or `/u/*`. Public custom-domain portfolio rewrites also preserve public indexing, while verified tenant app routes receive the directive. Final live/CI verification remains open; no production deployment is included.

### PUB-03 — P2: Sitemap advertises an authentication-only developer page

Owner: frontend/SEO. Baseline `sitemap.ts:12` includes `/developer`; `app/developer/page.tsx:35` immediately uses `useRequireAuth()`, whose confirmed-empty session redirects to `/login?redirect=/developer`. `llms.txt:16` advertises this as developer tools without an account caveat.

Impact: search/agent discovery directs people to an auth shell as though it were public documentation. Implemented narrow source repair: omit auth-only `/developer` from public sitemap, retain human-facing advanced-tool guidance but label account requirement in llms.txt. Public marketing links may still deliberately lead to the authenticated portal.

### PUB-04 — P2: README first setup command references a nonexistent tracked file

Owner: developer experience/docs. `README.md:28` says `cp .env.example .env`; root only tracks `.env.production.example`, while app-specific templates are `backend/.env.example`, `frontend/.env.example` and `frontend/.env.production.example`. A clean clone fails at its first setup command.

Completion: choose and test the supported development setup, including matching backend/frontend auth/database/ports and renderer defaults. Do not tell new users to use production configuration as a dev workaround. The README repair is tracked separately from the indexing change.

### PUB-05 — P2 follow-up: Public release log retains an unsupported no-training commitment

Owner: privacy/product copy. `frontend/src/data/changelog.ts:20`, served by `/updates`, says a published no-training data commitment shipped. Corrected privacy describes selected AI provider processing and each provider's own terms, but does not publish a no-training guarantee. This is a mismatch among public surfaces, **not evidence that Latexy or a provider actually trains on user documents**.

Completion: owner supplies the specific truthful commitment/provenance or removes/qualifies the changelog claim. The conservative corrected privacy policy should remain the source of current processing disclosures.

### PUB-06 — P2 follow-up: Updates motion ignores reduced-motion setting

Owner: frontend/accessibility. `components/marketing/MotionPrimitives.tsx` drives opacity/y transitions and ScrollDepth transforms through Framer Motion without `useReducedMotion` or a MotionConfig. `app/updates/page.tsx` consumes these primitives. The CSS reduced-motion floor in `design-tokens.css:136` only overrides CSS animation/transition duration and cannot suppress JS-generated transform sequences; GlobalHeader explicitly handles this distinction with `useReducedMotion`.

Source confirms missing preference handling. Actual discomfort, frame timing and browser reflow are not claimed. Completion: respect the OS setting, preserve visible content without JS/observer initialization, and verify reduced-motion page behavior in a real browser. This is outside the narrow indexing patch.

### PUB-07 — P3 follow-up: Public Templates/Updates lack dedicated metadata

Owner: frontend/SEO. The sitemap lists `/templates` and `/updates`, but their pages have no page-specific title/description/canonical/OpenGraph URL. They inherit generic root metadata; templates is a client component with no metadata-export wrapper.

Completion: add server layouts/metadata with unique supported copy and canonical URLs, execute metadata tests and verify final HTML. Missing schema ratings/FAQ rich-result eligibility is not a defect; do not invent ratings, reviews, prices or required Google appearance guarantees.

## Source-confirmed strengths, not generalized passes

- Root layout sets language from negotiated UI locale, one main landmark and keyboard skip target; high-contrast pre-paint theme cookie/OS support exists. Auth form labels, autocomplete, reveal buttons, mismatch/error live regions and error focus are implemented.
- `GlobalHeader` accounts for reduced motion, closes menus on route change, handles Escape/focus restoration, roving account-menu keys and mobile cyclic focus. `OnboardingFlow` implements focus trapping, body scroll lock and reduced motion. These are positive source observations, not screen-reader certification.
- `useRequireAuth`, `AccountContentBoundary`, and local account-incarnation handling distinguish transient session failure from an authoritative sign-out and reset private React state on real owner changes. Existing controlled tests execute real hook/page callback logic; they are stronger than regex checks but not real service acceptance.
- `CapabilityRouteBoundary` preserves an already-open unsaved builder draft under hidden+inert on capability revocation, offers local JSON recovery and source/editor navigation. A different identity cannot receive the retained subtree.
- Homepage/software and visible FAQ JSON-LD describe only actual product capabilities; FAQ/llms text explicitly disclaims employer-ATS reproduction/hiring prediction. `siteUrl()` avoids advertising localhost and preserves configured HTTPS origin.
- Runtime provider endpoint exposes booleans/public OIDC info only, with no-store. Basic Google identity and separate Google Drive scope/config are separated. Settings transparently warns that GitHub private sync requests broad repository read/write access; public-project import requests no private-repo scope. Integration cards preserve connected-state disconnect/recovery when new connect capability is disabled.
- Privacy and Terms top-level/served Markdown copies are byte-identical. Legal renderer is server-side and its wrapped-list regression passed. No claim of WCAG certification or guaranteed PDF/UA appears in the accessibility statement.

## Executed checks

Command from frontend using the diagnostic dependency runtime:

`node_modules/.bin/vitest run --config vitest.config.ts src/__tests__/marketing-origin.test.ts src/__tests__/canonical-public-domain.test.ts src/__tests__/accessibility-statement.test.ts src/__tests__/legal-markdown-renderer.test.ts src/__tests__/landing-compile-claims.test.ts src/__tests__/onboarding-runtime.test.ts src/__tests__/oauth-completion-claims.test.ts`

Initial result: seven files, 32 tests passed, 801 ms Vitest duration. After the indexing patch, the same selection plus `search-indexing.test.ts` and `middleware-routing.test.ts` passed **85 tests in nine files**, 855 ms Vitest duration. Changed-file ESLint, focused strict TypeScript compilation of `search-indexing.ts`, and `git diff --check` passed. The first new middleware test run found its synthetic NextRequest omitted the actual Host header; fixing the fixture to include Host yielded the final pass without changing product host routing. Tests establish controlled configured-origin/schema behavior, conservative claim strings, legal renderer behavior, onboarding lifecycle and bounded document-lifetime OAuth intent deduplication. They do not establish live model output, real OAuth callback, mail delivery, network latency, billing or accessibility conformance.

Repository configuration: `playwright.quality.config.ts` enumerates desktop Chromium/Firefox/WebKit and mobile Chromium/WebKit, production bundle and synthetic HTTP contracts with service workers blocked. `.github/workflows/ci.yml` installs all engines and runs public quality, then explicit builder/editor/billing/Settings/onboarding owner tests with zero retries and traces, followed by isolated hydration proof. The public accessibility check is a custom visible-control/document-structure audit, **not axe or a full WCAG engine**. No axe dependency/test was found.

Historical browser evidence: `docs/audits/resume-builder-2026-10-08/ACCEPTANCE.md` records real local synthetic-account builder save/reload/PDF/download and 390×844 mobile inspection; screenshots are retained. `docs/audits/marketing-first-use-2026-10-06/validation.json` records desktop content/theme/visual-editing checks but explicitly says the requested mobile override was not applied. `docs/audits/resume-engine/isolated-verification-2026-10-11.md` records CI synthetic cross-browser and isolated-container progress, including failures and later corrections. These artifacts are dated and not final-main or deployed-build blanket acceptance. Final-head CI and deployment identity must be verified before closing launch gates.

## Remaining launch gates and accountable owners

1. **Product/legal/support:** approve Terms reconciliation, entity/contact details, applicable notices/consent; verify support/privacy/legal/billing mailboxes actually owned and deliver; confirm the published two-business-day accessibility acknowledgment process. Reading mailto source does not close this gate.
2. **Frontend/QA:** final-head frozen-lock Node22 build/lint/types/units plus the actual named Chromium/Firefox/WebKit/mobile matrices, no hidden skips/failures; deploy-identity check before production acceptance. Repeat keyboard, zoom/reflow, on-screen keyboard and interrupted/repeated navigation with screenshot evidence.
3. **Accessibility:** named NVDA+Firefox/Chrome, VoiceOver+Safari/iOS and TalkBack+Chrome matrix; error announcements, field focus, modal dismissal, editor/PDF selection, text alternatives, reduced motion and contrast. PDF tagging/reading-order limitations stay publicly disclosed; HTML alternatives do not prove PDF/UA.
4. **Auth/email/integrations:** final Better Auth 1.7.7 Google cancel/complete/re-login, email signup/reset/verification delivery, passkey/2FA interruption; separate authorized Google Drive drive.file export/update/retry, GitHub public-import/private-sync conflict, Dropbox, Zotero, Mendeley and institutional OIDC. Mock ticket/ownership passes do not prove provider consent/configuration/token refresh.
5. **PWA/mobile:** actual service-worker activation/update/offline account-transition behavior and installed-app launch; quality mocks deliberately prevent service-worker takeover and cannot close it.
6. **SEO/GEO:** final live HTML and robots/sitemap/llms/OG assets on configured canonical origin; reachable public destinations; private noindex response checks. Search Console propagation or indexing completion requires its own actual observation, not a metadata test. Public share/portfolio discoverability policy remains an explicit product decision.
7. **Engine/performance:** real deployed PDF and actual configured-provider acceptance and measured action-to-usable-output remain separate engine-owner gates. Do not promote component/TeX/synthetic timing into end-to-end user latency claims.

## Narrow source repair file inventory

- `frontend/src/lib/search-indexing.ts`: 16 explicit account/application roots and exact-root/descendant predicate; crawler-only disclaimer.
- `frontend/src/middleware.ts`: X-Robots-Tag on canonical/configured app responses, verified tenant responses and resolver failure pass-through; public custom-domain portfolio rewrites are unchanged. Existing API matcher, auth endpoints, locale headers and tenant cookies are preserved.
- `frontend/src/app/robots.ts`: align private crawl exclusions with roots; preserve existing API/share exclusions and public allow.
- `frontend/src/app/sitemap.ts`: remove auth-only `/developer`, retaining existing public marketing destinations.
- `frontend/src/app/llms.txt/route.ts`: label developer portal account-only with real purpose, preserve configured URLs and conservative interpretation.
- `frontend/src/__tests__/search-indexing.test.ts`: 50 executable cases including every root/descendant policy, actual NextResponse headers, public/auth-API preservation, custom-domain rewrite, tenant cookie preservation, resolver outage, sitemap and llms configured origin.

Robots disallow remains a crawl hint and may prevent compliant crawlers from reading a later noindex response. This patch does not promise removal of an already indexed URL; Search Console/direct live observation is required for that outcome. Authorization and confidentiality do not depend on these crawler directives.
