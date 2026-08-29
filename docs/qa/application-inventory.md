# Latexy — Complete Application Inventory (QA Audit Reference)

> Generated for a production-readiness QA audit. Static analysis only — the app was **not** run. All references are `file:line` where available. This document drives the QA test matrix; completeness is prioritized over prose. Includes surfaces not reachable from the visible nav.

## Summary Counts

| Metric | Count |
|---|---|
| **Frontend routes** (`page.tsx`) | **38** (+1 root `layout.tsx`, +1 auth-unrelated `middleware.ts`) |
| **Backend endpoints** | **~297** total → **295 REST** across 36 routers + **2 WebSocket** |
| **Backend routers** (`*_routes.py`) | 36 (+ `routes.py` main/legacy aggregator) |
| **Background workers** (Celery) | 13 task modules; 5 Celery Beat periodic schedules |
| **User journeys identified** | **18** end-to-end flows |

Endpoint counts per router group: Group A (10 routers) = 88; Group B (12 routers) = 70; Group C (14 routers incl. `routes.py`) = 139 (137 REST + 2 WebSocket).

---

# FRONTEND — Next.js App Router (`frontend/src/app/`)

## 1. Routes / Pages

Auth model: **client-side, per-page** (`useSession` + `useEffect` redirect). There is **no server-side auth middleware and no central route guard**. Backend is the real enforcement point (token validated against the `session` table). See §Auth Gating Mechanism below.

| URL Path | File (rel. `frontend/src/`) | Access | Purpose |
|---|---|---|---|
| `/` | `app/page.tsx` | Public | Landing page ("Typeset" marketing specimen) |
| — | `app/layout.tsx` | N/A | Root layout: providers, `AuthSync`, `GlobalHeader`, footer, theme bootstrap |
| `/admin` | `app/admin/page.tsx` | Protected (RBAC) | Admin control plane: feature flags, entitlements matrix, users/roles; 403-probe gate (`:648-686`) |
| `/admin/tenant` | `app/admin/tenant/page.tsx` | Protected (RBAC) | Tenant admin dashboard: tenant members, roles, settings |
| `/billing` | `app/billing/page.tsx` | Protected (soft) | Subscription/billing mgmt; inline sign-in prompt (`:460`); student-verify/team-invite tokens |
| `/byok` | `app/byok/page.tsx` | Protected | BYOK API-key management; redirect `/login` (`:38-39`) |
| `/dashboard` | `app/dashboard/page.tsx` | Protected | Analytics KPIs, activity chart, recent runs; redirect `/login` (`:38-41`) |
| `/developer` | `app/developer/page.tsx` | Protected | Developer API keys & app mgmt; redirect `/login?next=/developer` (`:45`) |
| `/faq` | `app/faq/page.tsx` | Public | Marketing FAQ |
| `/forgot-password` | `app/forgot-password/page.tsx` | Public (auth) | Request password-reset email |
| `/login` | `app/login/page.tsx` | Public (auth) | Sign-in form |
| `/platform` | `app/platform/page.tsx` | Public | Marketing "Platform" page |
| `/pricing` | `app/pricing/page.tsx` | Public | Marketing pricing (checkout on `/billing`) |
| `/r/[token]` | `app/r/[token]/page.tsx` | Public (dynamic) | Shared-resume view by share token |
| `/reset-password` | `app/reset-password/page.tsx` | Public (auth) | Set new password from reset link |
| `/resources` | `app/resources/page.tsx` | Public | Marketing resources index |
| `/settings` | `app/settings/page.tsx` | Protected (gate-before-fetch) | Per-user settings & integrations (GitHub/Zotero/Mendeley/Dropbox) (`:82-90`) |
| `/signup` | `app/signup/page.tsx` | Public (auth) | Sign-up form |
| `/templates` | `app/templates/page.tsx` | Public (action-gated) | Template gallery; "use template" pushes `/login` (`:92`) |
| `/tracker` | `app/tracker/page.tsx` | Protected | Job-application tracker (kanban); redirect `/login` (`:317`) |
| `/try` | `app/try/page.tsx` | Public | Resume Studio / trial editor (Monaco + streaming); "Log in" link, no redirect (`:720`) |
| `/u/[username]` | `app/u/[username]/page.tsx` | Public (dynamic) | Public user portfolio; custom-domain rewrite target |
| `/updates` | `app/updates/page.tsx` | Public | Marketing changelog/updates |
| `/verify-email` | `app/verify-email/page.tsx` | Public (auth) | Email-verification landing |
| `/workspace` | `app/workspace/page.tsx` | Protected | Resume list/grid workspace; redirect `/login` (`:139-140`) |
| `/workspace/[resumeId]/batch-tailor` | `app/workspace/[resumeId]/batch-tailor/page.tsx` | Protected* | Batch-tailor a resume to multiple jobs (no in-page guard) |
| `/workspace/[resumeId]/career` | `app/workspace/[resumeId]/career/page.tsx` | Protected (soft) | Career-path analysis for a target role (`:110`) |
| `/workspace/[resumeId]/cover-letter` | `app/workspace/[resumeId]/cover-letter/page.tsx` | Protected | Cover-letter generator; redirect `/login` (`:66-67`) |
| `/workspace/[resumeId]/edit` | `app/workspace/[resumeId]/edit/page.tsx` | Protected (gate-before-fetch) | Resume editor (`:995`) |
| `/workspace/[resumeId]/optimize` | `app/workspace/[resumeId]/optimize/page.tsx` | Protected (gate-before-fetch) | Resume optimize flow (`:113`) |
| `/workspace/builder/[resumeId]` | `app/workspace/builder/[resumeId]/page.tsx` | Protected* | Structured resume builder (existing) (no in-page guard) |
| `/workspace/builder/new` | `app/workspace/builder/new/page.tsx` | Protected* | Structured resume builder (new) (no in-page guard) |
| `/workspace/cover-letters` | `app/workspace/cover-letters/page.tsx` | Protected | Cover-letter list; redirect `/login` (`:23-24`) |
| `/workspace/history` | `app/workspace/history/page.tsx` | Protected (soft) | Compilation/optimization history (`:55`) |
| `/workspace/merge` | `app/workspace/merge/page.tsx` | Protected | Merge/compare resumes; redirect `/login` (`:37-38`) |
| `/workspace/new` | `app/workspace/new/page.tsx` | Protected (gate-before-fetch) | Create new resume (`:99`) |
| `/workspaces` | `app/workspaces/page.tsx` | Protected | Team workspaces list |
| `/workspaces/[workspaceId]` | `app/workspaces/[workspaceId]/page.tsx` | Protected | Team workspace detail: members, roles |
| `/workspaces/[workspaceId]/recruiter` | `app/workspaces/[workspaceId]/recruiter/page.tsx` | Protected | Recruiter view within a team workspace |

\* No dedicated in-page `useSession` redirect — effectively protected via child components / API 401s. **QA flag:** verify these builder/batch-tailor pages actually block unauthenticated access.

**Dynamic routes:** `/r/[token]`, `/u/[username]`, `/workspace/[resumeId]/*`, `/workspace/builder/[resumeId]`, `/workspaces/[workspaceId]`, `/workspaces/[workspaceId]/recruiter`.

## Auth Gating Mechanism

1. **`AuthSync`** (`components/AuthSync.tsx`, mounted in `app/layout.tsx:6,67`) — reads `useSession()`; on resolution: `apiClient.setAuthToken(token)` (`:33`), `apiClient.markAuthResolved()` (`:37`), `wsClient.setToken(token)` (`:40`). No-ops while `isPending` (`:26`). Renders `null`; enforces nothing — it only bridges the token so FastAPI can validate it against the `session` table.
2. **`middleware.ts`** (`frontend/src/middleware.ts`) — **NOT auth.** Rewrites custom portfolio domains → `/u/{username}` via `GET /portfolio/resolve-domain` (`:26-72`); known domains pass through (`:34-41`). No login checks.
3. **Per-page redirect** (`useSession` + `useEffect` → `router.push('/login')`) is the dominant protected idiom. Variants: hard redirect, **soft gate** (inline sign-in panel, no redirect), **gate-before-fetch** (skip data load), **action-gated** (page public, action needs login), **RBAC** (backend 403-probe on admin page).
4. **No** `useAuthGuard`/`ProtectedRoute`/`requireAuth` helper exists — every page reimplements the check inline. **QA implication:** auth is genuinely enforced server-side; some pages have inconsistent or missing client guards.

## 2. Components by Area (`frontend/src/components/`)

### Layout / Chrome / Providers
| File | Purpose |
|---|---|
| `GlobalHeader.tsx` | Sticky auth-aware top nav; items gated by entitlement `feature` keys |
| `marketing/MarketingFooter.tsx` | Marketing footer |
| `marketing/MotionPrimitives.tsx` | Reusable framer-motion animation wrappers |
| `EmailVerifyBanner.tsx` | Dismissible "verify your email" banner |
| `OfflineBanner.tsx` | Offline status banner |
| `ErrorBoundary.tsx` | React error boundary fallback |
| `NotificationProvider.tsx` | Toast/notification context |
| `WebSocketProvider.tsx` | Wraps `wsClient` singleton in React context |
| `AuthSync.tsx` | Syncs Better Auth token → `apiClient`/`wsClient` |
| `TenantThemeSync.tsx` | Applies per-tenant theme/branding (white-label) |
| `WebVitalsReporter.tsx` | Reports Core Web Vitals |
| `LoadingSpinner.tsx` | Generic spinner |
| `theme/ThemeProvider.tsx` | Light/dark mode provider |
| `theme/ModeToggle.tsx` | Light/dark toggle |
| `theme/AestheticController.tsx` | Sets `data-aesthetic` (marketing vs app skin) per route |
| `icons/brand-icons.tsx` | Inline SVG brand/provider icons |

### Editor / Studio
| File | Purpose |
|---|---|
| `LaTeXEditor.tsx` | Monaco LaTeX editor + ref API + collab permissions |
| `MobileEditor.tsx` | Touch-optimized mobile editor |
| `WYSIWYGEditor.tsx` | Visual WYSIWYG resume editor |
| `TikZEditor.tsx` | Visual TikZ/diagram editor |
| `PDFPreview.tsx` | iframe PDF viewer w/ zoom + color-usage analysis |
| `LogViewer.tsx` | Scrollable compile-log w/ error highlighting |
| `CompilerSelector.tsx` | pdflatex/xelatex/lualatex engine picker |
| `CompileSettingsModal.tsx` | Compile options modal |
| `CompileErrorHistory.tsx` | Past compile-error history |
| `ErrorExplainerPanel.tsx` | AI-explains a LaTeX compile error |
| `SymbolPalette.tsx` | Insertable math/LaTeX symbol palette |
| `MacroLibraryPanel.tsx` | Manage/insert reusable LaTeX macros |
| `PackageManagerPanel.tsx` | Manage `\usepackage` dependencies |
| `LinterPanel.tsx` | LaTeX lint issues + auto-fix |
| `LaTeXSearchPanel.tsx` | Find/replace within source |
| `LaTeXDocPanel.tsx` | Inline LaTeX command docs |
| `QrCodeInserter.tsx` | Generate + insert QR code |
| `SlideViewer.tsx` | Beamer/slide deck preview |
| `SectionReorderPanel.tsx` | Drag-reorder resume sections |
| `KeyboardShortcutsPanel.tsx` | Editor shortcut cheat-sheet |
| `SaveCheckpointPopover.tsx` | Save a named version checkpoint |
| `JobQueue.tsx` | Live compile/optimize job queue (WS-driven) |
| `SnippetMarketplace.tsx` | Browse community LaTeX snippets |
| `SnippetPreviewModal.tsx` | Preview a marketplace snippet |

### ATS
| File | Purpose |
|---|---|
| `ATSScoreCard.tsx` | Full ATS score breakdown |
| `ATSScoreBadge.tsx` | Compact ATS score pill |
| `ATSTextView.tsx` | Plain-text extraction an ATS sees |
| `KeywordDensityMap.tsx` | Keyword frequency heatmap vs JD |
| `SkillsGapPanel.tsx` | Skills gap vs target role |
| `ConfidenceScorePanel.tsx` | Confidence radar for resume readiness |
| `ScoreHistoryChart.tsx` | ATS score over time |
| `ats/ATSRadarChart.tsx` | Radar of ATS category scores |
| `ats/AtsSimulatorPanel.tsx` | Simulates ATS parsing |
| `ats/DeepAnalysisPanel.tsx` | Deep AI ATS analysis |
| `ats/SemanticMatchModal.tsx` | Embedding semantic match vs JD |

### Optimize / AI Writing
| File | Purpose |
|---|---|
| `GuidedIntakePanel.tsx` | Collapsible "fine-tune the AI" intake (industry/seniority/tone/emphasize/downplay) |
| `ChangeReviewModal.tsx` | Per-change accept/reject/edit review of AI edits |
| `ChangesPanel.tsx` | Side panel of AI-proposed changes |
| `QuickTailorModal.tsx` | Quick one-shot tailor-to-JD |
| `WritingAssistantWidget.tsx` | Inline AI writing assistant |
| `BulletGeneratorWidget.tsx` | Generate achievement bullets |
| `SummaryGeneratorWidget.tsx` | Generate resume summary/objective |
| `ProofreadPanel.tsx` | AI proofreading suggestions |
| `ContactFormatterPanel.tsx` | Normalize contact-info block |
| `DateStandardizerPanel.tsx` | Standardize date formats |
| `DesignPanel.tsx` | Accent-color / design presets |
| `JobDescriptionInput.tsx` | Paste target JD |
| `CompareModal.tsx` | Side-by-side version compare |
| `DiffViewerModal.tsx` | Text-diff viewer |

### Billing / BYOK / Auth
| File | Purpose |
|---|---|
| `billing/PricingCard.tsx` | Single plan pricing card |
| `billing/SubscriptionManager.tsx` | Manage subscription (upgrade/cancel) |
| `byok/APIKeyManager.tsx` | Add/list/delete/validate BYOK keys |
| `byok/ProviderSelector.tsx` | Choose LLM provider |
| `auth/SignInForm.tsx` | Sign-in (Better Auth client) |
| `auth/SignUpForm.tsx` | Sign-up (Better Auth client) |

### Collaboration / Templates / Import / Tracker / Career / References / Export
| File | Purpose |
|---|---|
| `CollaboratorPanel.tsx` | Manage collaborators/permissions |
| `CommentsPanel.tsx` | Inline comments thread |
| `ShareResumeModal.tsx` | Share/publish resume (link + access) |
| `VersionHistoryPanel.tsx` | List + restore prior versions |
| `TemplateCard.tsx` | Template gallery card |
| `TemplatePreviewModal.tsx` | Full-preview modal for a template |
| `TemplateCustomizerPanel.tsx` | Customize template variables |
| `ImportProjectsModal.tsx` | Unified import: GitHub / URL / LinkedIn |
| `ImportFromBuilderWizard.tsx` | 4-step wizard: Kickresume/Resume.io/Novoresume/generic |
| `MultiFormatUpload.tsx` | Drag-drop upload (JSON/PDF/DOCX...) |
| `builder/BuilderPreview.tsx` | Live preview inside builder-import flow |
| `AddApplicationModal.tsx` | Add job application to tracker |
| `ApplyModal.tsx` | One-click job application (Greenhouse/Lever) |
| `CareerPathChart.tsx` | Career path visualization |
| `SalaryEstimatorPanel.tsx` | Salary estimate for role |
| `AgeAnalysisPanel.tsx` | Resume age/dating-signal analysis |
| `InterviewPrepPanel.tsx` | Interview prep questions/tips |
| `ReferencesPanel.tsx` | Manage bibliography/reference entries |
| `PublicationsPanel.tsx` | Manage academic publications |
| `GenerateReferencesModal.tsx` | AI-generate references/citations |
| `ExportDropdown.tsx` | Export-format dropdown |
| `WatermarkDownloadPopover.tsx` | Watermarked (free-tier) PDF download |

### Analytics / Help / Search / Onboarding / UI primitives
| File | Purpose |
|---|---|
| `analytics/MetricCharts.tsx` | Dashboard KPI/metric charts |
| `help/HelpCenter.tsx` | Help center panel + `useHelpCenter` |
| `ProjectSearchModal.tsx` | Command-palette project/resume search |
| `onboarding/OnboardingFlow.tsx` | 4-step welcome onboarding modal + `useOnboarding` |
| `ui/*` | `badge, button, card, input, Panel, ProgressBar, SegmentedControl, Separator, Skeleton, Spinner, Tabs, Toggle` — token-styled primitives |

## 3. Modals, Dialogs & Multi-step Flows

**Modals/Dialogs:** `AddApplicationModal`, `ApplyModal`, `ChangeReviewModal`, `CompareModal`, `CompileSettingsModal`, `DiffViewerModal`, `GenerateReferencesModal`, `ImportProjectsModal`, `ProjectSearchModal`, `QuickTailorModal`, `ShareResumeModal`, `SnippetPreviewModal`, `TemplatePreviewModal`, `ats/SemanticMatchModal`, `OnboardingFlow` (modal overlay).
**Popovers:** `SaveCheckpointPopover`, `WatermarkDownloadPopover`. **Dropdown:** `ExportDropdown`.

**Multi-step flows:**
- **`OnboardingFlow.tsx`** (steps array `:42-236`; `useOnboarding` `:377-418`) — 4 steps, persists `latexy_onboarding_completed` to localStorage: (1) Welcome/stats, (2) How it works, (3) Key features, (4) Get started (variant by `userType`).
- **`ImportFromBuilderWizard.tsx`** (step logic `:137-197`; blocks at `:218/245/282/327`) — 4 steps → `onComplete(latexContent)`: (1) Platform selector, (2) Export instructions, (3) File upload (`apiClient.parseForPreview`), (4) Preview + convert (async job via `useFormatConversion`).
- **`GuidedIntakePanel.tsx`** — single collapsible progressive form (industry/seniority/tone/emphasize/downplay) with active-count badge.
- **`ImportProjectsModal.tsx`** — one modal, three external-source paths (GitHub / URL / LinkedIn).

## 4. Client-side Data Hooks (`frontend/src/hooks/`)

| Hook | Purpose | API / client calls |
|---|---|---|
| `useATSScoring.ts` | ATS score, JD analysis, recommendations, industry keywords, deep + semantic | `jobApiClient.scoreResume`/`.analyzeJobDescription`/`.getRecommendations`/`.getIndustryKeywords`/`.getSupportedIndustries`; `apiClient.deepAnalyzeResume`/`.semanticMatch` |
| `useAutoCompile.ts` | Toggle auto-compile | none — localStorage `latexy_auto_compile` |
| `useConfidenceScore.ts` | Debounced (15s) confidence score | `apiClient.confidenceScore(latex)` |
| `useFormatConversion.ts` | Upload → convert to LaTeX (async job) | `apiClient.uploadForConversion`; polls `/jobs/{id}/result`; wraps `useJobStream` |
| `useJobManagement.ts` | Submit jobs, list, health | `jobApiClient.submitJob`/`.listJobs`/`.getSystemHealth` |
| `useJobStatus.ts` | Wrapper over `useJobStream` + poll/cancel | `apiClient.getJobState`, `apiClient.cancelJob` |
| `useJobStream.ts` | Accumulate typed WS events → UI state; hydrate via REST | `wsClient`; `apiClient.getJobState`/`.getJobResult` |
| `useJobStream.reducer.ts` | Pure reducer (node-testable) | none |
| `useLatexLinter.ts` | Debounced client-side lint + auto-fix | none — local `@/lib/latex-linter` |
| `usePushNotifications.ts` | Browser Notification permission/state | Web Notification API; localStorage |
| `usePWAInstall.ts` | Capture `beforeinstallprompt`, expose `prompt()` | PWA install event |
| `useQuickATSScore.ts` | Debounced (10s) quick ATS score | `apiClient.quickScoreATS(latex, jd)` |
| `useSpellCheck.ts` | Spell-check + personal dictionary | `apiClient.checkSpelling(latex, lang)`; localStorage |
| `useTrialStatus.ts` | Trial usage tracking + localStorage fallback | `apiClient.getTrialStatus(fp)` + `getDeviceFingerprint` |

---

# BACKEND — FastAPI (`backend/app/api/`)

**Auth guard legend:**
- `get_current_user_required` — Better Auth session required, returns `user_id: str` (401 if absent). Sometimes aliased `get_current_user` / `_require_user`.
- `get_current_user_optional` — session optional, returns `Optional[str]`; anonymous allowed.
- `require_feature("<flag>")` — entitlement gate that **also resolves & returns the user** (so it enforces auth **and** plan). `require_feature_optional("<flag>")` gates the flag but does **not** force auth.
- `require_admin` — admin RBAC (Better Auth session with admin role).
- `require_template_admin` — header-based `X-Admin-Secret` == `settings.ADMIN_SECRET_KEY` (**not** session auth).
- `get_developer_api_key_required` — developer API-key auth with per-key scopes (public API only).
- **Public** — no auth dependency (some still per-IP rate-limited or CSRF-nonce-protected).

## Group A

### admin_routes.py — no prefix (absolute paths)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/config/feature-flags` `:56` | Public | Client-facing flat flag map (public keys only) |
| GET | `/admin/feature-flags` `:71` | require_admin | Full flag objects |
| PATCH | `/admin/feature-flags/{key}` `:90` | require_admin | Toggle a feature flag |
| GET | `/admin/entitlements` `:125` | require_admin | Full entitlement state |
| PATCH | `/admin/entitlements/kill-switch/{key}` `:134` | require_admin | Toggle global feature kill-switch |
| PATCH | `/admin/entitlements/matrix` `:156` | require_admin | Set a per-plan feature cell |
| GET | `/admin/users` `:227` | require_admin | List users (search + pagination) |
| PATCH | `/admin/users/{user_id}/role` `:255` | require_admin | Change RBAC role (last-admin guard) |

### ai_routes.py — prefix `/ai`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/ai/generate-bullets` `:258` | optional + `require_feature_optional(ai_writing)` | AI bullet generation |
| POST | `/ai/generate-summary` `:366` | optional + `require_feature_optional(ai_writing)` | AI summary variants |
| POST | `/ai/proofread` `:458` | Public + `require_feature_optional(ai_writing)` | Rule-based proofread (no LLM) |
| POST | `/ai/explain-error` `:468` | optional | Explain LaTeX error |
| POST | `/ai/rewrite` `:591` | optional + `require_feature_optional(ai_writing)` | AI rewrite of selection |
| POST | `/ai/spell-check` `:713` | optional | LanguageTool spell/grammar |
| POST | `/ai/confidence-score` `:827` | Public | Rule-based quality score |
| POST | `/ai/standardize-dates` `:964` | Public | Regex date normalization |
| POST | `/ai/salary-estimate` `:1052` | optional | LLM salary range |
| POST | `/ai/age-analysis` `:1221` | Public | Resume-age/staleness flags |
| POST | `/ai/format-contacts` `:1355` | Public | Contact-block normalization |
| POST | `/ai/translate` `:1451` | required + `require_feature(ai_writing)` | Translate resume → variant fork |
| POST | `/ai/reorder-sections` `:1597` | optional | AI section reordering |
| GET | `/ai/personas` `:1752` | Public | List optimization personas |
| POST | `/ai/generate-publications` `:1806` | optional | ORCID pubs → LaTeX bib block |

### analytics_routes.py — prefix `/analytics`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/analytics/track` `:134` | optional | Track generic event |
| GET | `/analytics/me` `:176` | required + `require_feature(analytics)` | My analytics |
| GET | `/analytics/me/timeseries` `:218` | required | My timeseries |
| GET | `/analytics/user/{user_id}` `:257` | require_admin | Analytics for a user |
| GET | `/analytics/system` `:289` | require_admin | System-wide analytics |
| GET | `/analytics/conversion-funnel` `:311` | require_admin | Conversion funnel |
| POST | `/analytics/track/compilation` `:333` | optional | Track compile event |
| POST | `/analytics/track/optimization` `:374` | optional | Track optimize event |
| POST | `/analytics/track/page-view` `:415` | optional | Track page-view |
| POST | `/analytics/track/feature-usage` `:455` | optional | Track feature usage |
| GET | `/analytics/dashboard` `:495` | require_admin | Combined dashboard |

### application_routes.py — prefix `/apply`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/apply/detect` `:200` | required | Detect job platform from URL |
| POST | `/apply/greenhouse/preview` `:228` | required | Fetch Greenhouse job details |
| POST | `/apply/lever/preview` `:259` | required | Fetch Lever posting details |
| POST | `/apply/greenhouse` `:291` | required + `require_feature(one_click_apply)` | Submit Greenhouse application |
| POST | `/apply/lever` `:402` | required + `require_feature(one_click_apply)` | Submit Lever application |
| GET | `/apply/submissions` `:511` | required | List submission history |
| GET | `/apply/submissions/{submission_id}` `:531` | required | Single submission detail |

### ats_routes.py — prefix `/ats`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/ats/score` `:172` | optional + `require_feature_optional(ats_score)` | ATS score (sync/async), rate-limited |
| POST | `/ats/analyze-job-description` `:294` | optional | Analyze JD for ATS insights |
| POST | `/ats/recommendations` `:393` | Public | Generate improvement recommendations |
| GET | `/ats/industry-keywords/{industry}` `:502` | Public | Keywords for an industry |
| GET | `/ats/supported-industries` `:527` | Public | List industries |
| GET | `/ats/industry-profiles` `:549` | Public | List calibration profiles |
| POST | `/ats/quick-score` `:575` | Public + `require_feature_optional(ats_score)` | Lightweight quick-score |
| POST | `/ats/deep-analyze` `:687` | optional + `require_feature_optional(ats_deep)` | LLM deep section analysis (anon trial) |
| POST | `/ats/semantic-match` `:841` | required + `require_feature(ats_deep)` | Rank resumes by JD similarity |
| GET | `/ats/simulate/profiles` `:1055` | Public | List ATS system profiles |
| POST | `/ats/simulate` `:1066` | optional | Simulate ATS parse |
| POST | `/ats/keyword-density` `:1194` | optional | JD keyword-density map |
| GET | `/ats/benchmark` `:1295` | required | Percentile rank vs cohort |

### byok_routes.py — prefix `/byok`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/byok/api-keys` `:135` | required + `require_feature(byok)` | Add provider API key |
| GET | `/byok/api-keys` `:163` | required | List keys |
| DELETE | `/byok/api-keys/{key_id}` `:183` | required | Delete key |
| GET | `/byok/providers` `:206` | Public | Supported providers + capabilities |
| POST | `/byok/validate` `:223` | required | Validate a key |
| POST | `/byok/test/{provider}` `:247` | required + `require_feature(byok)` | Test connection |
| GET | `/byok/usage-stats` `:269` | required | Provider usage stats |
| POST | `/byok/generate` `:296` | required + `require_feature(byok)` | Generate content via provider |
| GET | `/byok/system/health` `:358` | require_admin | Multi-provider system health |
| POST | `/byok/load-providers` `:398` | required + `require_feature(byok)` | Load user providers into service |
| GET | `/byok/models/{provider}` `:427` | Public | Models for a provider |
| GET | `/byok/capabilities/{provider}` `:452` | Public | Capabilities for a provider |

### career_routes.py — `/career` + admin_router `/admin`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/career/analyze` `:118` | required + `require_feature(career_paths)` | Career-path + skills-gap analysis |
| GET | `/career/analyses/{resume_id}` `:202` | required | List past analyses |
| GET | `/career/analysis/{analysis_id}` `:226` | required | Single analysis |
| GET | `/career/roles` `:254` | Public | Role autocomplete |
| POST | `/admin/career-graph/seed` `:280` | require_admin | Seed career graph |

### comment_routes.py — prefix `/resumes/{resume_id}/comments`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `.../comments` `:124` | required + `require_feature(collaboration)` | Add comment |
| GET | `.../comments` `:157` | required | List comments |
| PATCH | `.../comments/{comment_id}` `:187` | required | Edit (author only) |
| DELETE | `.../comments/{comment_id}` `:217` | required | Delete (author only) |
| PATCH | `.../comments/{comment_id}/resolve` `:241` | required | Toggle resolved |

### cover_letter_routes.py — prefix `/cover-letters`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/cover-letters/` `:203` | required | List (paginated/search) |
| GET | `/cover-letters/stats` `:253` | required | Count |
| POST | `/cover-letters/generate` `:266` | required + `require_feature(cover_letters)` | Generate via AI (async job) |
| GET | `/cover-letters/{id}` `:363` | required | Get one |
| PUT | `/cover-letters/{id}` `:374` | required | Update LaTeX |
| DELETE | `/cover-letters/{id}` `:389` | required | Delete |
| GET | `/cover-letters/resume/{resume_id}` `:401` | required | List for a resume |

### developer_routes.py — prefix `/developer`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/developer/keys` `:77` | required | List developer keys |
| GET | `/developer/usage` `:90` | required | Usage + daily limit |
| POST | `/developer/keys` `:104` | required + `require_feature(developer_api)` | Create key (max 5) |
| PATCH | `/developer/keys/{key_id}` `:151` | required | Rename key |
| DELETE | `/developer/keys/{key_id}` `:174` | required | Revoke key |

## Group B

### dropbox_routes.py — prefix `/dropbox`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/dropbox/connect` `:125` | required + `require_feature(integration_dropbox)` | Dropbox OAuth redirect |
| GET | `/dropbox/callback` `:157` | Public (Redis CSRF nonce) | OAuth token exchange |
| GET | `/dropbox/status` `:241` | required | Connection status |
| DELETE | `/dropbox/disconnect` `:261` | required | Clear tokens |
| POST | `/dropbox/resumes/{id}/enable` `:288` | required | Enable sync + initial push |
| POST | `/dropbox/resumes/{id}/disable` `:337` | required | Disable sync |
| POST | `/dropbox/resumes/{id}/push` `:357` | required | Upload LaTeX |
| POST | `/dropbox/resumes/{id}/pull` `:404` | required | Download LaTeX |
| GET | `/dropbox/resumes/{id}/status` `:447` | required | Per-resume sync status |

### export_routes.py — prefix `/export`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/export/formats` `:72` | Public | List export formats |
| GET | `/export/{id}/canva` `:115` | required (owner) | Export as Canva JSON |
| GET | `/export/{id}/figma` `:148` | required (owner) | Export as Figma JSON |
| GET | `/export/{id}/{fmt}` `:187` | required + `require_feature(exports)` (owner) | Export in format (tex/md/txt/html/json/yaml/xml/docx) |
| POST | `/export/content/{fmt}` `:232` | Public | Export raw LaTeX content |

### format_routes.py — prefix `/formats`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/formats/supported` `:80` | Public | List supported formats |
| POST | `/formats/detect` `:101` | Public | Detect uploaded file format |
| GET | `/formats/info/{format_name}` `:150` | Public | Format info |
| POST | `/formats/validate` `:184` | Public | Validate file format |
| POST | `/formats/parse` `:287` | Public | Parse file → preview (no LLM) |
| POST | `/formats/upload` `:406` | optional (LaTeX public; others require auth + `ai_assists` quota) | Upload resume; queue LLM conversion |

### github_routes.py — prefix `/github`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/github/connect` `:73` | required + `require_feature(integration_github)` | GitHub OAuth redirect |
| GET | `/github/callback` `:104` | Public (Redis CSRF) | OAuth token exchange |
| GET | `/github/status` `:182` | required | Connection status |
| DELETE | `/github/disconnect` `:198` | required | Clear token |
| POST | `/github/resumes/{id}/enable` `:220` | required | Enable sync, create repo |
| POST | `/github/resumes/{id}/disable` `:271` | required | Disable sync |
| POST | `/github/resumes/{id}/push` `:296` | required | Push LaTeX |
| POST | `/github/resumes/{id}/pull` `:356` | required | Pull LaTeX |
| POST | `/github/import-projects` `:408` | `require_feature(ai_import_github)` | Enqueue async project import |
| GET | `/github/import-projects/{job_id}` `:461` | `require_feature(ai_import_github)` | Import job result |
| GET | `/github/resumes/{id}/status` `:484` | required | Per-resume sync status |

### interview_routes.py — `/interview-prep` + `resume_interview_router` `/resumes`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/interview-prep/generate` `:84` | required + `require_feature(interview_prep)` | Start question generation (201) |
| GET | `/interview-prep/{prep_id}` `:153` | required | Get one prep session |
| DELETE | `/interview-prep/{prep_id}` `:178` | required | Delete prep session |
| GET | `/resumes/{resume_id}/interview-prep` `:208` | required | List prep sessions for resume |

### job_routes.py — prefix `/jobs`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/jobs/submit` `:323` | optional (anon device-trial; auth plan-quota) | Submit job (compile/optimize/combined/ats) |
| POST | `/jobs/compile-watermarked` `:557` | optional (same metering) | Compile with watermark |
| POST | `/jobs/batch` `:647` | required + `require_feature(batch_tailor)` (owner) | Batch-tailor across JDs (201) |
| GET | `/jobs/batch/{batch_id}` `:778` | required (owner) | Batch status |
| GET | `/jobs/{job_id}/state` `:835` | optional (owner if owned) | Job state snapshot |
| GET | `/jobs/{job_id}/result` `:865` | optional (owner) | Final result |
| GET | `/jobs/{job_id}/stream` `:948` | optional (owner) | Replay Redis Stream events |
| DELETE | `/jobs/{job_id}` `:1007` | optional (owner) | Request cancellation |
| GET | `/jobs/` `:1079` | optional (empty if anon) | List recent jobs |
| GET | `/jobs/health` `:1122` | Public | Job system health |
| POST | `/jobs/system/cleanup` `:1139` | require_admin | Trigger cleanup task |

### macro_routes.py — prefix `/macros` (all required)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/macros` `:67` | required | List macros |
| POST | `/macros` `:80` | required + `require_feature(macros)` | Create macro |
| PATCH | `/macros/{id}` `:104` | required (owner) | Update macro |
| DELETE | `/macros/{id}` `:124` | required (owner) | Delete macro |

### mendeley_routes.py — prefix `/mendeley`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/mendeley/connect` `:58` | required + `require_feature(integration_mendeley)` | OAuth redirect |
| GET | `/mendeley/callback` `:89` | Public (Redis CSRF) | OAuth token exchange |
| GET | `/mendeley/status` `:163` | required | Connection status |
| DELETE | `/mendeley/disconnect` `:181` | required | Clear token |
| POST | `/mendeley/import` `:265` | required (owner) | Import BibTeX into resume |

### optimize_routes.py — prefix `/optimize`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/optimize/segment-changes` `:100` | optional | Diff original→optimized as hunks |
| POST | `/optimize/apply-changes` `:123` | optional | Reconstruct from accepted hunks |

### portfolio_routes.py — prefix `/portfolio`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/portfolio/setup` `:114` | required + `require_feature(portfolio)` | Configure public portfolio |
| GET | `/portfolio/check-username` `:162` | Public | Username availability |
| POST | `/portfolio/verify-domain` `:181` | required | Verify custom-domain CNAME |
| GET | `/portfolio/resolve-domain` `:240` | Public (used by FE middleware) | Domain → username |
| GET | `/portfolio/{username}` `:262` | Public | Public profile + public resumes |

### public_api_routes.py — prefix `/api/v1` (all developer-API-key, scoped)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/compile` `:143` | dev-key `compile` scope; `compilations` quota | Queue compile job |
| POST | `/api/v1/optimize` `:183` | dev-key `optimize` scope; `optimizations` quota | Queue optimize job |
| POST | `/api/v1/ats/score` `:218` | dev-key `ats` scope | Deterministic ATS score (sync) |
| GET | `/api/v1/jobs/{job_id}` `:243` | dev-key (owner) | Poll job |
| GET | `/api/v1/jobs/{job_id}/pdf` `:273` | dev-key `export` scope (owner) | Download PDF |

### reference_routes.py — prefix `/references`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/references/fetch` `:126` | `require_feature_optional(references)` (effectively public) | Fetch BibTeX for DOI/arXiv (max 20) |
| POST | `/references/fetch-orcid` `:240` | `require_feature_optional(references)` (effectively public) | Fetch ORCID publications |
| POST | `/references/detect` `:339` | Public | Extract DOI/arXiv IDs from text |

## Group C

### routes.py — main/legacy aggregator (no prefix); mounts all sub-routers
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/me` `:234` | required | Authed user id/email/plan |
| GET | `/config/entitlements` `:247` | optional | Effective feature allow-map + quota snapshot |
| GET | `/health` `:267` | Public | Health (LaTeX/DB/Redis) |
| GET | `/livez` `:313` | Public (hidden) | Liveness probe |
| GET | `/readyz` `:319` | Public (hidden) | Readiness probe (503 if down) |
| GET | `/metrics` `:349` | Public (hidden) | Prometheus scrape |
| POST | `/compile` `:367` | required | Compile LaTeX→PDF (plan quota) |
| GET | `/download/{job_id}` `:455` | optional (owner) | Download PDF |
| GET | `/download/{job_id}/synctex` `:501` | optional (owner) | SyncTeX data |
| GET | `/logs/{job_id}` `:547` | optional (owner) | Compile logs |
| POST | `/optimize` `:581` | required + `require_feature(llm_optimize)` | LLM optimization (quota) |
| POST | `/optimize-and-compile` `:646` | required + `require_feature(llm_optimize)` | Optimize + compile in one step |
| GET | `/public/trial-status` `:731` | optional | Trial status for device fp |
| POST | `/public/track-usage` `:757` | Public | Track anon usage |
| POST | `/public/compile` `:791` | optional (rejects authed) | Anonymous compile (device trial) |
| GET | `/subscription/plans` `:933` | Public | List plans + billing status |
| POST | `/subscription/create` `:952` | optional (401 if none) | Create subscription |
| GET | `/subscription/student/verify/{token}` `:999` | Public | Activate student plan |
| POST | `/billing/validate-coupon` `:1011` | optional | Validate coupon |
| GET | `/subscription/current` `:1036` | optional (401 if none) | Current subscription |
| POST | `/subscription/cancel` `:1068` | optional (401 if none) | Cancel subscription |
| POST | `/billing/webhook` `:1099` | Public (Razorpay HMAC) | Razorpay webhook |
| GET | `/share/{share_token}` `:1218` | Public | Shared-resume metadata + presigned PDF URL |

### resume_routes.py — prefix `/resumes` (all `required` except builder/templates)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/resumes/builder/templates` `:367` | Public | List builder templates |
| POST | `/resumes/builder/seed-upload` `:386` | required | Parse upload → builder content |
| POST | `/resumes/builder` `:421` | required + `require_feature(resume_builder)` | Create builder-backed resume |
| GET | `/resumes/stats` `:454` | required | Resume stats |
| POST | `/resumes/` `:499` | required | Create resume |
| GET | `/resumes/` `:542` | required | List resumes |
| GET | `/resumes/search` `:625` | required | Full-text search |
| GET | `/resumes/error-history` `:686` | required | Grouped compile-error history |
| GET | `/resumes/{id}/builder` `:719` | required | Get builder payload |
| PATCH | `/resumes/{id}/builder` `:734` | required | Update builder content |
| GET | `/resumes/{id}` `:777` | required | Get resume |
| PUT | `/resumes/{id}` `:804` | required | Update resume |
| DELETE | `/resumes/{id}` `:856` | required | Delete resume |
| PATCH | `/resumes/{id}/settings` `:872` | required | Update compile settings |
| PATCH | `/resumes/{id}/tags` `:939` | required | Replace tags |
| PATCH | `/resumes/{id}/pin` `:954` | required | Pin |
| PATCH | `/resumes/{id}/unpin` `:970` | required | Unpin |
| PATCH | `/resumes/{id}/archive` `:986` | required | Archive |
| PATCH | `/resumes/{id}/unarchive` `:1000` | required | Unarchive |
| POST | `/resumes/{id}/fork` `:1027` | required | Create variant/fork |
| POST | `/resumes/{id}/quick-tailor` `:1110` | required (quota) | Fork + tailored optimize job |
| GET | `/resumes/{id}/academic-cv-report` `:1178` | required | Detect academic CV |
| POST | `/resumes/{id}/academic-cv-convert` `:1193` | required (quota) | Convert academic CV → industry |
| GET | `/resumes/{id}/variants` `:1306` | required | List child variants |
| GET | `/resumes/{id}/diff-with-parent` `:1331` | required | Diff variant vs parent |
| POST | `/resumes/{id}/record-optimization` `:1389` | required | Save optimization record |
| GET | `/resumes/{id}/optimization-history` `:1421` | required | Recent optimizations |
| GET | `/resumes/{id}/score-history` `:1455` | required | ATS score history |
| POST | `/resumes/{id}/restore-optimization/{opt_id}` `:1486` | required | Restore optimized version |
| POST | `/resumes/{id}/checkpoints` `:1563` | required | Create manual checkpoint |
| GET | `/resumes/{id}/checkpoints` `:1608` | required | List checkpoints |
| GET | `/resumes/{id}/checkpoints/{cid}/content` `:1646` | required | Full LaTeX of checkpoint |
| DELETE | `/resumes/{id}/checkpoints/{cid}` `:1674` | required | Delete checkpoint |
| POST | `/resumes/{id}/share` `:1719` | required | Create/return share token |
| DELETE | `/resumes/{id}/share` `:1825` | required | Revoke share token |
| GET | `/resumes/{id}/analytics` `:1864` | required | Resume view analytics |
| GET | `/resumes/export/bulk` `:1988` | required | Download all resumes as ZIP |
| POST | `/resumes/{id}/collaborators` `:2139` | required | Invite collaborator by email |
| GET | `/resumes/{id}/collaborators` `:2199` | required | List collaborators |
| PATCH | `/resumes/{id}/collaborators/{cuid}` `:2234` | required | Change collaborator role |
| DELETE | `/resumes/{id}/collaborators/{cuid}` `:2292` | required | Remove collaborator |
| POST | `/resumes/{id}/generate-references` `:2424` | required | Generate LaTeX reference page |
| POST | `/resumes/merge` `:2539` | required | Merge 2–4 resumes |
| POST | `/resumes/{id}/generate-portfolio` `:2637` | required | Generate static HTML portfolio |

### scraper_routes.py — no prefix
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/scrape-job-description` `:77` | optional (per-IP 10/min) | Scrape a job-posting URL |

### settings_routes.py — prefix `/settings`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/settings/notifications` `:28` | required | Get email notification prefs |
| PUT | `/settings/notifications` `:46` | required | Update prefs |

### snippet_routes.py — `/snippets` + admin_router `/admin`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/snippets` `:149` | optional | List/search snippets |
| GET | `/snippets/{id}` `:181` | optional | Get snippet |
| POST | `/snippets` `:194` | required + `require_feature(snippets)` | Create snippet |
| PATCH | `/snippets/{id}` `:221` | required (author) | Update own snippet |
| DELETE | `/snippets/{id}` `:243` | required (author) | Delete own snippet |
| POST | `/snippets/{id}/install` `:259` | required | Install snippet |
| DELETE | `/snippets/{id}/install` `:283` | required | Uninstall snippet |
| POST | `/snippets/{id}/upvote` `:307` | required | Toggle upvote |
| POST | `/admin/snippets/seed` `:338` | require_admin | Upsert official snippets |

### sources_routes.py — prefix `/sources`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/sources/import-url` `:62` | `require_feature(ai_import_url)` | Import projects from public URL (SSRF-guarded + LLM) |
| POST | `/sources/import-linkedin` `:142` | `require_feature(ai_import_linkedin)` | Import from LinkedIn export/resume file |

### team_routes.py — prefix `/team`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/team/seats` `:77` | required (+ team owner) | List seats |
| POST | `/team/invite` `:91` | required (+ team owner) | Invite teammate |
| GET | `/team/join/{token}` `:172` | required (email match) | Accept/activate seat |
| DELETE | `/team/seats/{seat_id}` `:213` | required (+ team owner) | Remove seat |

### telemetry_routes.py — prefix `/telemetry`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/telemetry/frontend` `:63` | optional (404 if disabled) | Ingest web-vitals/business events |

### template_routes.py — prefix `/templates`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/templates/categories` `:174` | Public | Categories + counts |
| GET | `/templates/` `:193` | Public | List active templates |
| HEAD | `/templates/{id}/thumbnail` `:221` | Public | Thumbnail existence |
| GET | `/templates/{id}/thumbnail` `:239` | Public | Serve PNG thumbnail (MinIO) |
| HEAD | `/templates/{id}/pdf` `:257` | Public | PDF existence |
| GET | `/templates/{id}/pdf` `:275` | Public | Serve compiled PDF (MinIO) |
| GET | `/templates/{id}` `:293` | Public | Full detail (incl. latex) |
| POST | `/templates/{id}/use` `:303` | required + `require_feature(templates)` | Create resume from template |
| POST | `/templates` `:335` | require_template_admin (header secret) | Create template |
| PUT | `/templates/{id}` `:358` | require_template_admin | Replace template |
| PATCH | `/templates/{id}/activate` `:384` | require_template_admin | Activate |
| PATCH | `/templates/{id}/deactivate` `:401` | require_template_admin | Deactivate |
| DELETE | `/templates/{id}` `:418` | require_template_admin | Delete template |

### tenant_routes.py — prefix `/tenants`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/tenants/current-context` `:157` | Public (Host header) | Resolved tenant branding for host |
| POST | `/tenants` `:164` | required | Create tenant (caller=owner) |
| GET | `/tenants/my` `:212` | required | Tenants I own/belong to |
| PATCH | `/tenants/{id}` `:240` | required (+ owner/admin) | Update branding |
| GET | `/tenants/{id}/members` `:278` | required (+ member) | List members |
| POST | `/tenants/{id}/members/invite` `:319` | required (+ owner/admin) | Invite member |
| DELETE | `/tenants/{id}/members/{uid}` `:375` | required (+ owner/admin) | Remove member |
| GET | `/tenants/{id}/stats` `:408` | required (+ owner/admin) | Tenant stats |
| POST | `/tenants/{id}/domain/verify` `:450` | required (+ owner/admin) | DNS TXT verification |

### tracker_routes.py — prefix `/tracker` (all required)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/tracker/applications` `:118` | required + `require_feature(application_tracker)` | Create application |
| GET | `/tracker/applications` `:165` | required | List (grouped/flat) |
| GET | `/tracker/stats` `:197` | required | Funnel stats |
| GET | `/tracker/applications/{id}` `:246` | required | Get one |
| PUT | `/tracker/applications/{id}` `:263` | required | Update |
| DELETE | `/tracker/applications/{id}` `:312` | required | Delete |
| PATCH | `/tracker/applications/{id}/status` `:330` | required | Update status |

### workspace_routes.py — prefix `/workspaces` (all required + owner/member checks)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/workspaces` `:155` | required + `require_feature(team_workspaces)` | Create workspace |
| GET | `/workspaces` `:183` | required | List my workspaces |
| GET | `/workspaces/{id}` `:225` | required (+ member) | Detail + members |
| PATCH | `/workspaces/{id}` `:270` | required (+ owner) | Rename |
| DELETE | `/workspaces/{id}` `:286` | required (+ owner) | Delete |
| POST | `/workspaces/{id}/members/invite` `:299` | required (+ owner) | Invite member |
| DELETE | `/workspaces/{id}/members/{uid}` `:365` | required (+ owner) | Remove member |
| PATCH | `/workspaces/{id}/members/{uid}/role` `:393` | required (+ owner) | Change role |
| POST | `/workspaces/{id}/resumes/{rid}` `:437` | required (+ owner) | Share resume into workspace |
| DELETE | `/workspaces/{id}/resumes/{rid}` `:481` | required (+ owner) | Remove resume |
| GET | `/workspaces/{id}/resumes` `:506` | required (+ member) | List workspace resumes |
| POST | `/workspaces/{id}/resumes/{rid}/notes` `:560` | required (+ owner) | Create recruiter note |
| GET | `/workspaces/{id}/resumes/{rid}/notes` `:592` | required (+ member) | List recruiter notes |
| PATCH | `/workspaces/{id}/resumes/{rid}/notes/{nid}` `:619` | required (+ member, author) | Edit note |
| DELETE | `/workspaces/{id}/resumes/{rid}/notes/{nid}` `:657` | required (+ member, author/owner) | Delete note |

### ws_routes.py — no prefix (WebSocket, auth via `?token=`)
| Method | Path | Auth | Purpose |
|---|---|---|---|
| WEBSOCKET | `/ws/jobs` `:61` | Optional `?token=` (per-job ownership) | Real-time job event stream (subscribe/cancel/ping) |
| WEBSOCKET | `/ws/collab/{resume_id}` `:298` | Required `?token=` (owner or collaborator) | Y.js CRDT live collaboration socket |

### zotero_routes.py — prefix `/zotero`
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/zotero/connect` `:139` | required + `require_feature(integration_zotero)` | Start OAuth 1.0a, redirect |
| GET | `/zotero/callback` `:209` | Public (Redis reqsecret state) | Exchange verifier, store token |
| GET | `/zotero/status` `:276` | required | Connection status |
| DELETE | `/zotero/disconnect` `:295` | required | Clear token |
| GET | `/zotero/collections` `:314` | required | List collections |
| POST | `/zotero/import` `:365` | required | Import BibTeX into resume |
| DELETE | `/zotero/bibtex/{resume_id}` `:469` | required | Remove stored BibTeX |

## 7. Background Workers (Celery — `backend/app/workers/`)

Config: `backend/app/core/celery_app.py` — task routes by module → queue; priority queues (max 9); dead-letter handling.

| Worker module | Celery task(s) | Queue | Trigger |
|---|---|---|---|
| `latex_worker.py` | `compile_latex_task` (`:369`) | `latex` | `/compile`, `/jobs/submit`, `/jobs/compile-watermarked`, public API compile, orchestrator |
| `llm_worker.py` | `optimize_resume_task` (`:29`) | `llm` | `/optimize`, `/jobs/submit` (optimize), quick-tailor |
| `orchestrator.py` | `optimize_and_compile_task` (`:83`) | `combined` | `/optimize-and-compile`, `/jobs/submit` (combined) |
| `ats_worker.py` | `score_resume_ats_task` (`:32`), `analyze_job_description_ats_task` (`:183`), `deep_analyze_ats_task` (`:647`), `embed_resume_task` (`:748`) | `ats` | `/ats/score` (async), JD analyze, `/ats/deep-analyze`, embeddings for semantic match |
| `cover_letter_worker.py` | `generate_cover_letter_task` (`:92`) | `llm` | `/cover-letters/generate` |
| `interview_prep_worker.py` | `generate_interview_prep_task` (`:63`) | `llm` | `/interview-prep/generate` |
| `converter_worker.py` | `convert_document_task` (`:26`) | `llm` | `/formats/upload` (non-LaTeX), builder seed-upload conversion |
| `github_import_worker.py` | `import_github_projects_task` (`:41`) | `llm` | `/github/import-projects` |
| `auto_save_worker.py` | `record_auto_save_checkpoint` (`:21`) | `cleanup` | Editor auto-save (submitted from resume edit paths) |
| `email_worker.py` | `send_job_completion_email`, `send_job_failure_email`, `send_share_viewed_email`, `send_weekly_digest`, `send_weekly_digest_to_all` | `email` | Completion; Redis-deduplicated terminal failure; analytics-debounced share view; **weekly digest Mon 09:00 UTC** (Celery Beat and Modal cron) |
| `cleanup_worker.py` | `cleanup_temp_files_task` (`:33`), `cleanup_expired_jobs_task` (`:398`), `health_check_task` (`:640`) | `cleanup` | **Beat: every 30m / every 1h / every 5m**; also `/jobs/system/cleanup` (admin) |
| `event_publisher.py` | (not a task) | — | Sync Redis publish helpers used by all workers (`publish_event`, `publish_job_result`, `is_cancelled`) |
| `storage_guard.py` | (not a task) | — | Compilation-DB bookkeeping helpers |

**Celery Beat schedule** (`celery_app.py:105-130`): `cleanup-expired-jobs` (3600s), `cleanup-temp-files` (1800s), `health-check` (300s), `weekly-digest-monday-9am` (crontab Mon 09:00), `sample-queue-depths` (20s, observability).

## 8. External Integrations

| Integration | Service file | SDK/transport | Used by |
|---|---|---|---|
| **OpenAI** | `llm_provider_service.py`, `llm_service.py`, `embedding_service.py`, `career_path_service.py` | `openai` SDK / httpx | Optimize, AI writing, embeddings (semantic match), career analysis |
| **Anthropic** | `llm_provider_service.py` | `anthropic` SDK | BYOK / multi-provider LLM |
| **Gemini / OpenRouter** | `llm_provider_service.py` | httpx/requests | BYOK / multi-provider LLM |
| **Razorpay** | `payment_service.py` | `razorpay` SDK | Subscriptions, `/billing/webhook` (HMAC) |
| **MinIO / S3** | `storage_service.py` | `boto3` | PDF/thumbnail/template object storage, presigned URLs |
| **Email** | `email_service.py` | `resend` (default) or SMTP (`smtplib`) via httpx | Job completion/failure, shared-resume views, weekly digest, verification |
| **GitHub** | `github_sync_service.py`, `github_projects_service.py` | httpx (OAuth) | Resume repo sync, project import |
| **Dropbox** | `dropbox_sync_service.py` | httpx (OAuth) | Resume file sync |
| **Zotero / Mendeley** | `reference_service.py`, `publications_service.py` | httpx (OAuth 1.0a / 2.0) | Bibliography import |
| **Greenhouse / Lever** | `greenhouse_service.py`, `lever_service.py` | httpx | One-click apply |
| **Job scraper** | `job_scraper_service.py` | httpx/requests | `/scrape-job-description`, `/apply/*/preview` |
| **URL / LinkedIn import** | `url_projects_service.py`, `linkedin_import_service.py` | httpx (SSRF-guarded) | `/sources/import-*` |
| **ORCID / Crossref / arXiv** | `reference_service.py`, `publications_service.py` | httpx | DOI/arXiv/ORCID reference fetch |
| **Encryption** | `encryption_service.py` | Fernet + PBKDF2HMAC | BYOK key + OAuth token at-rest encryption |

---

# CROSS-CUTTING

## 9. Auth Flow, Quota Enforcement, RBAC

**Auth flow (Better Auth → session table → backend validation):**
1. User signs in via Better Auth (frontend `lib/auth.ts` / `auth-client.ts`) → token stored in `session` table.
2. `AuthSync` (`components/AuthSync.tsx`) pushes the token into `apiClient.setAuthToken()` and `wsClient.setToken()`.
3. FastAPI `middleware/auth_middleware.py` validates the bearer token by querying the `session` table; legacy HS256 JWT accepted as fallback.
4. Dependencies `get_current_user_required` / `_optional` resolve `user_id`; WebSockets validate `?token=` the same way.

**Plan / quota enforcement points:**
- **Feature gating:** `middleware/entitlements.py` — `require_feature(key)` (`:37`) and `require_feature_optional(key)` (`:48`) call `entitlement_service.has_feature(key, user)`. `require_feature` also resolves+returns the user (dual auth+plan gate).
- **Numeric quotas:** `services/entitlement_service.py` — `consume_quota` (`:388`), `enforce_quota` (`:477`, raises standard error envelope on denial), `refund_quota` (`:460`). Dimensions include `compilations`, `optimizations`, `ai_assists`. Enforced on `/compile`, `/optimize`, `/jobs/submit`, quick-tailor, academic-cv-convert, public API compile/optimize, `/formats/upload`.
- **Anonymous device-trial:** `services/trial_service.py` — 3 free uses per device fp + cooldown; enforced on `/public/compile`, `/jobs/submit` (anon), `/ats/deep-analyze` (anon, `DEEP_ANALYSIS_TRIAL_LIMIT=2`).
- **Rate limiting:** `middleware/rate_limiting.py` + per-endpoint per-IP Redis limits (scraper 10/min, ATS quick-score, benchmark 10/user/hr).
- **Compile timeout by plan:** `config.py` — free 30s / basic 120s / pro 240s / byok 240s.
- **Developer API:** per-key scopes + daily meter (`developer_key_service.consume_rate_limit`) layered on plan quota.
- **Entitlements propagation:** single Redis JSON blob `latexy:entitlements` (cache → Redis → DB rebuild); admin edits push to Redis.

**Admin RBAC (two distinct models):**
- **Session-based `require_admin`** — RBAC role on the Better Auth user; used across admin/analytics/career-seed/snippet-seed/byok-health/jobs-cleanup. Role changes via `PATCH /admin/users/{id}/role` (last-admin guard). Frontend `/admin` uses a 403-probe.
- **Header-secret `require_template_admin`** — `X-Admin-Secret` == `ADMIN_SECRET_KEY`; used only for template write endpoints (**not** session auth). **QA flag:** verify this secret is set and not a weak default in prod.
- **Per-resource RBAC** — tenants, workspaces, teams, resume collaborators use owner/admin/member ownership checks rather than global admin.

**Plans:** free (3 uses), basic, pro, byok, student, team (max 5 seats). Razorpay plan IDs per tier in `config.py:227-234`.

## 10. Key User Journeys (18)

| # | Journey | Entry → Steps → Exit |
|---|---|---|
| 1 | **Signup → onboarding → dashboard** | `/signup` (SignUpForm) → `/verify-email` → `OnboardingFlow` (4 steps) → `/dashboard` (KPIs) |
| 2 | **Anonymous trial compile** | `/try` (Monaco) → `POST /public/compile` (device trial, `useTrialStatus`) → WS `/ws/jobs` stream → PDF preview → "Log in" prompt at limit |
| 3 | **Create resume → edit → compile → PDF** | `/workspace/new` or `/workspace` → `POST /resumes/` → `/workspace/[id]/edit` (LaTeXEditor) → `POST /compile` / `/jobs/submit` → `latex_worker` → `/download/{job_id}` PDF |
| 4 | **AI optimize → review → ATS** | `/workspace/[id]/optimize` → `GuidedIntakePanel` → `POST /optimize` (`require_feature(llm_optimize)`) → `llm_worker` → `ChangeReviewModal` (`/optimize/segment-changes` + `/apply-changes`) → `POST /ats/score` |
| 5 | **Deep ATS + semantic match** | ATS panels → `POST /ats/deep-analyze` (`ats_worker`) → `POST /ats/semantic-match` (embeddings) → score history |
| 6 | **Quick tailor to JD** | `QuickTailorModal` → `POST /resumes/{id}/quick-tailor` (fork + optimize job, quota) |
| 7 | **Batch tailor** | `/workspace/[id]/batch-tailor` → `POST /jobs/batch` (`require_feature(batch_tailor)`) → poll `/jobs/batch/{id}` |
| 8 | **Templates → resume** | `/templates` (public gallery) → `TemplatePreviewModal` → login → `POST /templates/{id}/use` (`require_feature(templates)`) |
| 9 | **Guided builder** | `/workspace/builder/new` → `POST /resumes/builder/seed-upload` → `PATCH /resumes/{id}/builder` → `POST /resumes/builder` → compile |
| 10 | **Import external projects** | `ImportProjectsModal` → GitHub (`/github/import-projects` → `github_import_worker`) / URL (`/sources/import-url`) / LinkedIn (`/sources/import-linkedin`) |
| 11 | **Import from builder platform** | `ImportFromBuilderWizard` (4 steps) → `/formats/parse` → `/formats/upload` → `converter_worker` → LaTeX |
| 12 | **Cover letter** | `/workspace/[id]/cover-letter` → `POST /cover-letters/generate` (`cover_letter_worker`) → `/workspace/cover-letters` list |
| 13 | **Job tracker CRUD** | `/tracker` (kanban) → `AddApplicationModal` → `POST /tracker/applications` (`require_feature(application_tracker)`) → status transitions → `/tracker/stats` |
| 14 | **One-click apply** | `ApplyModal` → `/apply/detect` → `/apply/{greenhouse|lever}/preview` → `POST /apply/{platform}` (`require_feature(one_click_apply)`) → `/apply/submissions` |
| 15 | **BYOK key add** | `/byok` (`APIKeyManager`+`ProviderSelector`) → `POST /byok/api-keys` (`require_feature(byok)`, Fernet-encrypted) → `POST /byok/validate` → `/byok/generate` |
| 16 | **Billing / subscription** | `/pricing` → `/billing` (`SubscriptionManager`) → `POST /subscription/create` (Razorpay) → `/billing/webhook` (HMAC) → `/subscription/current` |
| 17 | **Admin control plane** | `/admin` (403-probe) → feature flags (`PATCH /admin/feature-flags/{key}`), entitlements matrix/kill-switch, users/roles |
| 18 | **Tenant white-label** | `/admin/tenant` → `POST /tenants` → `PATCH /tenants/{id}` (branding) → `TenantThemeSync` applies theme by Host → `/tenants/{id}/domain/verify` |

**Additional supporting journeys** (secondary): resume sharing (`/resumes/{id}/share` → `/r/[token]`), public portfolio (`/generate-portfolio` → `/u/[username]`), team workspaces + recruiter notes (`/workspaces/*`), live collaboration (`/ws/collab/{resume_id}` CRDT + comments), version history/checkpoints, references/publications (Zotero/Mendeley/ORCID), interview prep, career-path analysis, developer public API (`/api/v1/*`), cloud sync (GitHub/Dropbox).

---

## QA-Relevant Flags Surfaced During Inventory

- **Missing client guards:** `/workspace/builder/new`, `/workspace/builder/[resumeId]`, `/workspace/[resumeId]/batch-tailor` have no in-page `useSession` redirect — rely on API 401. Verify they don't leak UI/data pre-auth.
- **OAuth callbacks are public**, protected only by a Redis CSRF nonce/state: `/github/callback`, `/dropbox/callback`, `/mendeley/callback`, `/zotero/callback`. Test nonce validation + replay.
- **`require_template_admin` uses a shared header secret** (`X-Admin-Secret`), not session RBAC — confirm the secret is strong and set in prod.
- **`require_feature_optional("references")`** does NOT authenticate — `/references/fetch` and `/references/fetch-orcid` are effectively public (abuse control = 20-concurrency semaphore only).
- **`/public/compile` explicitly rejects authenticated callers** (they must use `/compile`) — test the auth/anon boundary.
- **Two interview-prep routers** (`/interview-prep` + resume-scoped `/resumes/{id}/interview-prep`) — confirm both are registered in `routes.py`.
- **Job download/state/result use `optional` auth + Redis-meta ownership** — verify anonymous users cannot access others' jobs by guessing IDs.
