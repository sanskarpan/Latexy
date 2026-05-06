# P3 Feature Implementation Checklist

> Deep implementation guide for all 14 P3 features. Each item maps directly to the current codebase —
> file paths, specific functions, and exact changes. Work through features in dependency order.
>
> **Branch convention:** one branch per feature (e.g. `feat/dropbox-sync`)
> **Key files to know:** see `MEMORY.md` for architecture overview.
> **Numbering:** continues from P2 (Features 35–76); P3 starts at Feature 77.
> **Last alembic migration at P3 start:** `0019_add_portfolio.py` → P3 DB migrations start at `0020`.

---

## Legend
- `[ ]` — not started
- `[x]` — done
- `[~]` — in progress
- Complexity: **S** = < 1 week | **M** = 1–3 weeks | **L** = 1–2 months | **XL** = 3+ months

---

## Build Order (recommended)

```
Quick wins first (S/M complexity, foundational):
  88 → 89 → 90 → 86 → 77

Large features (own 4–8 week sprints):
  81 → 82 → 83 → 80 → 85

XL features (dedicated multi-month projects):
  79 → 78 → 84 → 87
```

---

## Feature 77 — Dropbox / Cloud Storage Sync · P3 · L

**Goal:** Two-way sync between Latexy and a user's Dropbox account. Every resume save pushes
the `.tex` source to `Dropbox/Apps/Latexy/{resume_title}.tex`. Users can edit the file locally
and Latexy pulls changes on next open. Modeled after Feature 37 (GitHub Sync) — same shape,
different API. No compilation is synced — source only.

### 77A · Database Migration
- [x] Create `backend/alembic/versions/0020_add_dropbox_integration.py`:
  ```sql
  ALTER TABLE users
    ADD COLUMN dropbox_access_token  TEXT,
    ADD COLUMN dropbox_refresh_token TEXT,
    ADD COLUMN dropbox_user_id       TEXT;

  ALTER TABLE resumes
    ADD COLUMN dropbox_sync_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN dropbox_path          TEXT,          -- e.g. /Apps/Latexy/My Resume.tex
    ADD COLUMN dropbox_last_synced_at TIMESTAMPTZ;
  ```
  - `down_revision = '0019'`

### 77B · Backend — Models
- [x] In `backend/app/database/models.py`:
  - Add to `User`: `dropbox_access_token`, `dropbox_refresh_token`, `dropbox_user_id`
  - Add to `Resume`: `dropbox_sync_enabled`, `dropbox_path`, `dropbox_last_synced_at`

### 77C · Config
- [x] Add to `backend/app/core/config.py`:
  ```python
  DROPBOX_APP_KEY:    str = ""
  DROPBOX_APP_SECRET: str = ""
  DROPBOX_REDIRECT_URI: str = "http://localhost:8030/dropbox/callback"
  ```

### 77D · Backend — Dropbox Sync Service
- [x] Create `backend/app/services/dropbox_sync_service.py`:
  ```python
  class DropboxSyncService:
      BASE_URL = "https://api.dropboxapi.com/2"
      CONTENT_URL = "https://content.dropboxapi.com/2"

      async def refresh_token(self, refresh_token: str) -> str:
          """POST https://api.dropbox.com/oauth2/token with grant_type=refresh_token.
          Returns new access_token. Store in users.dropbox_access_token."""

      async def upload_file(self, access_token: str, path: str, content: str) -> dict:
          """POST {CONTENT_URL}/files/upload with Dropbox-API-Arg header.
          mode=overwrite, autorename=False. Returns metadata dict."""

      async def download_file(self, access_token: str, path: str) -> str:
          """POST {CONTENT_URL}/files/download. Returns file content as string."""

      async def list_folder(self, access_token: str, folder: str) -> list[dict]:
          """POST {BASE_URL}/files/list_folder. Returns entries list."""

      async def get_account_info(self, access_token: str) -> dict:
          """POST {BASE_URL}/users/get_current_account. Returns account_id, name, email."""
  ```

### 77E · Backend — OAuth Routes
- [x] Create `backend/app/api/dropbox_routes.py`:
  - `GET /dropbox/connect` → redirect to Dropbox OAuth v2 authorization URL with PKCE
  - `GET /dropbox/callback?code=...&state=...` → exchange code for access+refresh tokens via
    `https://api.dropbox.com/oauth2/token`, call `get_account_info()`, store in `users`
  - `DELETE /dropbox/disconnect` → clear `dropbox_access_token/refresh_token/dropbox_user_id`,
    set `dropbox_sync_enabled=False` on all user resumes
  - `GET /dropbox/status` → returns `{ connected: bool, dropbox_user_id, display_name }`

### 77F · Backend — Sync Endpoints
- [x] Add to `backend/app/api/dropbox_routes.py`:
  - `POST /dropbox/resumes/{resume_id}/enable` — set `dropbox_sync_enabled=True`,
    compute path as `/Apps/Latexy/{resume.title}.tex`, do initial push
  - `POST /dropbox/resumes/{resume_id}/push` — upload `resume.latex_content` to `resume.dropbox_path`
  - `POST /dropbox/resumes/{resume_id}/pull` — download from `resume.dropbox_path`,
    update `resume.latex_content`, create auto-save checkpoint
  - `POST /dropbox/resumes/{resume_id}/disable` — set `dropbox_sync_enabled=False`, clear `dropbox_path`
  - `GET /dropbox/resumes/{resume_id}/status` → `{ enabled, path, last_synced_at, remote_modified_at }`
- [x] Register router in `backend/app/api/routes.py`

### 77G · Frontend — Settings Integration
- [x] In `frontend/src/app/settings/page.tsx`:
  - "Dropbox Integration" section: connected display name or "Connect Dropbox" button
  - "Disconnect" with confirmation dialog
- [x] In `frontend/src/lib/api-client.ts`:
  - Add `dropboxStatus()`, `dropboxEnable(resumeId)`, `dropboxPush(resumeId)`,
    `dropboxPull(resumeId)`, `dropboxDisable(resumeId)` methods

### 77H · Frontend — Editor Integration
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Dropbox sync toggle in editor header (only visible if Dropbox connected)
  - "Push to Dropbox" and "Pull from Dropbox" manual buttons
  - Show `last_synced_at` timestamp tooltip on Dropbox icon
  - If pull succeeds → reload editor content from response without page refresh

### 77I · Tests
- [x] Create `backend/test/test_dropbox_sync.py` — 8 tests:
  - `DropboxSyncService.upload_file`: mocked HTTP → verifies Dropbox-API-Arg header format
  - `DropboxSyncService.download_file`: mocked → returns file content string
  - `GET /dropbox/status` unauthenticated → 401
  - `POST /dropbox/resumes/{id}/enable` without connected Dropbox → 400 `dropbox_not_connected`
  - `POST /dropbox/resumes/{id}/push` enabled → calls upload_file once with correct path
  - `POST /dropbox/resumes/{id}/pull` → updates `latex_content`, updates `dropbox_last_synced_at`
  - `DELETE /dropbox/disconnect` → all resumes `dropbox_sync_enabled=False`
  - Token refresh flow: expired token → service calls refresh_token, retries upload

---

## Feature 78 — WYSIWYG / Rich Text Editor Mode · P3 · XL

**Goal:** Toggle from raw LaTeX to a visual rich-text view. Users format text with a toolbar;
the platform generates LaTeX behind the scenes. Bidirectional: WYSIWYG changes update the
LaTeX source, and LaTeX edits round-trip back to the WYSIWYG state. Covers the subset of
LaTeX constructs used in resume templates — not general LaTeX WYSIWYG.

### 78A · Document Model (Frontend)
- [x] Create `frontend/src/lib/wysiwyg/document-model.ts`:
  ```typescript
  // Intermediate representation between LaTeX and WYSIWYG DOM
  export interface ResumeDoc {
    preamble: string        // raw LaTeX preamble (not editable in WYSIWYG)
    sections: Section[]
  }
  export interface Section {
    title: string
    entries: Entry[]
  }
  export interface Entry {
    type: 'job' | 'education' | 'project' | 'skill-group' | 'text'
    heading?: string        // company / institution / project name
    subheading?: string     // role / degree / tech stack
    startDate?: string
    endDate?: string
    location?: string
    bullets: string[]       // plain text, no LaTeX markup
    raw?: string            // fallback for unrecognized constructs
  }
  ```

### 78B · LaTeX → Document Model Parser
- [x] Create `frontend/src/lib/wysiwyg/latex-parser.ts`:
  - `parseResume(latex: string): ResumeDoc`
  - Recognize `\section{Title}` → new Section
  - Recognize `\resumeSubheading`, `\cventry`, `\cvevent`, `\job` macros → Entry
  - Recognize `\begin{itemize}...\end{itemize}` → bullets array
  - Strip `\textbf{}`, `\textit{}`, `\emph{}` wrappers from prose (preserve text)
  - Unknown constructs → `type: 'text'`, `raw: originalLatex`
  - Preserve preamble (everything before `\begin{document}`) verbatim

### 78C · Document Model → LaTeX Serializer
- [x] Create `frontend/src/lib/wysiwyg/latex-serializer.ts`:
  - `serializeResume(doc: ResumeDoc): string`
  - Reconstruct the same macro set that was detected at parse time (store original macro name)
  - For `raw` entries: emit verbatim
  - Produce valid LaTeX with proper `\begin{document}...\end{document}` wrapper

### 78D · WYSIWYG Editor Component
- [x] Create `frontend/src/components/WYSIWYGEditor.tsx`:
  - Props: `doc: ResumeDoc`, `onChange: (doc: ResumeDoc) => void`
  - Uses **Slate.js** (`slate`, `slate-react`) for rich-text editing
  - Toolbar: Bold, Italic, Bullet list, Add Section, Add Job Entry, Add Education Entry
  - Each Section renders as a named group with entries below
  - Each Entry renders as a form-like card: heading / subheading inputs, date range inputs,
    location input, bullets list (each bullet as an editable line, drag to reorder)
  - Unknown `raw` entries render as a locked code block with a warning icon
  - Parse errors (round-trip failures) shown as amber banner: "Some LaTeX constructs can't be
    edited visually — switch to Source mode to edit them"

### 78E · Mode Toggle + Integration
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Add `editorMode: 'source' | 'wysiwyg'` state (default `'source'`, persisted to localStorage per resume)
  - Toggle button: "Source" | "Visual" in editor header
  - On switch to Visual: call `parseResume(latexContent)` → render `<WYSIWYGEditor />`
  - On switch to Source: call `serializeResume(doc)` → update Monaco content
  - On `WYSIWYGEditor.onChange`: serialize to LaTeX → update `latexContent` state → trigger auto-save
  - Show parse warnings from `latex-parser.ts` as dismissible info toast

### 78F · Round-Trip Quality Tests
- [x] Create `frontend/src/lib/wysiwyg/__tests__/round-trip.test.ts`:
  - Jake's Resume standard subheading → parse → serialize → identical LaTeX output
  - `\section{Experience}` + 3 `\resumeSubheading` + bullets → full round trip
  - Unknown macro (`\customcommand{...}`) preserved as `raw` and re-emitted verbatim
  - Empty section (no entries) round-trips correctly
  - Date range `Jan 2020 -- Present` preserved exactly

---

## Feature 79 — Mobile App / PWA · P3 · XL

**Goal:** Phase 1: PWA (service worker, manifest, offline drafts, background sync).
Phase 2: React Native app. Monaco doesn't run on mobile — mobile uses a simplified
CodeMirror-based editor. Offline compilations are queued and synced when connectivity returns.

### 79A · PWA Manifest & Config
- [x] Create `frontend/public/manifest.json`:
  ```json
  {
    "name": "Latexy",
    "short_name": "Latexy",
    "description": "AI-powered LaTeX resume builder",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#09090b",
    "theme_color": "#6d28d9",
    "icons": [
      { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
      { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png" },
      { "src": "/icons/icon-512-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
    ]
  }
  ```
- [x] Add `<link rel="manifest" href="/manifest.json" />` to `frontend/src/app/layout.tsx`
- [x] Generate and place app icons at `frontend/public/icons/` (192×192, 512×512, maskable)

### 79B · Service Worker (Workbox)
- [x] Install `next-pwa` or `@ducanh2912/next-pwa`
- [x] In `frontend/next.config.js`: wrap config with `withPWA`:
  ```js
  const withPWA = require('next-pwa')({ dest: 'public', register: true, skipWaiting: true })
  module.exports = withPWA({ /* existing config */ })
  ```
- [x] Cache strategy in `frontend/src/sw-config.ts`:
  - **App shell** (HTML, CSS, JS): `StaleWhileRevalidate`
  - **API GET /resumes**: `NetworkFirst`, cache 5 min
  - **MinIO PDF assets**: `CacheFirst`, cache 7 days
  - **Offline fallback page**: `frontend/public/offline.html`

### 79C · Offline Draft Storage (IndexedDB)
- [x] Create `frontend/src/lib/offline-drafts.ts`:
  ```typescript
  // Uses 'idb' library for typed IndexedDB access
  export interface OfflineDraft {
    resumeId: string
    latexContent: string
    savedAt: Date
    syncStatus: 'pending' | 'synced' | 'conflict'
  }
  export async function saveDraft(draft: OfflineDraft): Promise<void>
  export async function getDraft(resumeId: string): Promise<OfflineDraft | null>
  export async function getPendingDrafts(): Promise<OfflineDraft[]>
  export async function markSynced(resumeId: string): Promise<void>
  ```
- [x] In editor `useAutoSave` hook: if `navigator.onLine === false`, save to IndexedDB instead of API
- [x] On `window.onfocus` or `online` event: flush pending drafts → `PATCH /resumes/{id}` for each

### 79D · Background Sync (Compile Queue)
- [x] Create `frontend/src/lib/compile-queue.ts`:
  ```typescript
  export interface QueuedCompile {
    id: string       // uuid
    resumeId: string
    latexContent: string
    queuedAt: Date
  }
  export async function enqueueCompile(resumeId: string, content: string): Promise<string>
  export async function flushQueue(): Promise<void>  // called on reconnect
  ```
- [x] In editor compile handler: if offline, call `enqueueCompile()` and show "Queued — will compile
  when online" toast instead of error
- [x] Register Background Sync event in service worker: `self.addEventListener('sync', ...)` to
  call `flushQueue()` when browser regains connectivity

### 79E · Mobile Editor (CodeMirror)
- [x] Create `frontend/src/components/MobileEditor.tsx`:
  - Uses `@codemirror/view` + `@codemirror/lang-markdown` (lighter than Monaco, mobile-friendly)
  - LaTeX syntax highlighting via existing language configuration
  - Virtual keyboard-aware: adjust editor height when soft keyboard appears (`visualViewport` API)
  - Toolbar strip (above keyboard): Bold, Italic, `\item`, `\section`, compile button
  - No split-pane on mobile: full-screen editor with "Preview" tab to see PDF
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Detect mobile with `useMediaQuery('(max-width: 768px)')`
  - Render `<MobileEditor />` instead of `<LaTeXEditor />` on mobile
  - PDF preview tab: full-screen iframe of latest compiled PDF

### 79F · Offline UX Polish
- [x] `frontend/src/components/OfflineBanner.tsx`:
  - `useOnlineStatus()` hook (subscribes to `online`/`offline` events)
  - Banner: "You're offline — edits are saved locally and will sync when you reconnect"
  - Pending draft count badge in workspace header
- [x] `frontend/public/offline.html`: simple branded offline page with Latexy logo and message

### 79G · PWA Install Prompt
- [x] Create `frontend/src/hooks/usePWAInstall.ts`:
  - Captures `beforeinstallprompt` event
  - Returns `{ canInstall: boolean, prompt: () => void }`
- [x] In workspace header: "Add to Home Screen" button (hidden if not `canInstall`)

---

## Feature 80 — Career Path Visualization + Skills Gap Analysis · P3 · XL

**Goal:** Given a user's resume + a target senior role, generate a career path visualization
showing the trajectory from current state to target. Identify skills to develop over 2–3 years.
Uses a curated career graph knowledge base + LLM for personalized gap analysis.

### 80A · Database Migration
- [x] Create `backend/alembic/versions/0021_add_career_paths.py`:
  ```sql
  CREATE TABLE career_roles (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title        TEXT NOT NULL,
    level        TEXT NOT NULL,             -- 'junior' | 'mid' | 'senior' | 'staff' | 'principal' | 'director' | 'vp' | 'c-suite'
    industry     TEXT NOT NULL,             -- 'software_engineering' | 'data_science' | 'product' | 'finance' | etc.
    required_skills TEXT[] NOT NULL DEFAULT '{}',
    typical_yoe_min INT,
    typical_yoe_max INT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
  );

  CREATE TABLE career_transitions (
    from_role_id UUID REFERENCES career_roles(id) ON DELETE CASCADE,
    to_role_id   UUID REFERENCES career_roles(id) ON DELETE CASCADE,
    avg_years    NUMERIC(3,1),              -- average years to transition
    difficulty   TEXT,                      -- 'easy' | 'moderate' | 'hard'
    PRIMARY KEY (from_role_id, to_role_id)
  );

  CREATE TABLE career_analyses (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    resume_id      UUID NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    target_role_id UUID REFERENCES career_roles(id),
    target_role_freetext TEXT,             -- if no matching career_role found
    current_skills TEXT[] NOT NULL DEFAULT '{}',
    gap_skills     TEXT[] NOT NULL DEFAULT '{}',
    timeline_months INT,
    llm_analysis   TEXT,                   -- full LLM response in markdown
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  CREATE INDEX ON career_analyses(user_id, resume_id);
  ```
  - `down_revision = '0020'`

### 80B · Backend — Models
- [x] In `backend/app/database/models.py`:
  - Add `CareerRole`, `CareerTransition`, `CareerAnalysis` models with SQLAlchemy mappings

### 80C · Backend — Career Graph Seed Data
- [x] Create `backend/app/data/career_graph_seed.py`:
  - Seed 80+ common career roles across: Software Engineering, Data Science, Product Management,
    Finance/Quant, Consulting, Marketing
  - Seed transitions: e.g., SWE II → Senior SWE (avg 2.5 yrs, moderate), Senior SWE → Staff SWE (avg 3 yrs, hard)
  - Load via `POST /admin/career-graph/seed` endpoint (admin only)

### 80D · Backend — Analysis Service
- [x] Create `backend/app/services/career_path_service.py`:
  ```python
  class CareerPathService:
      async def detect_current_role(self, latex_content: str) -> str:
          """LLM call: extract current job title and infer career level from resume."""

      async def match_career_role(self, title: str, db: AsyncSession) -> CareerRole | None:
          """Fuzzy-match detected title against career_roles table (trigram similarity)."""

      async def find_path(
          self, from_role_id: str, to_role_id: str, db: AsyncSession
      ) -> list[CareerRole]:
          """BFS over career_transitions graph. Returns ordered list of roles in path."""

      async def analyze_gap(
          self,
          current_skills: list[str],
          target_role: CareerRole,
          latex_content: str,
          db: AsyncSession
      ) -> CareerAnalysis:
          """LLM call: compare user skills vs target required_skills.
          Returns gap_skills, timeline_months, and full markdown analysis."""
  ```

### 80E · Backend — API Endpoints
- [x] Create `backend/app/api/career_routes.py` with prefix `/career`:
  - `POST /career/analyze` — body: `{ resume_id, target_role_title: str }` →
    run full analysis (detect current role, find path, gap analysis), return `CareerAnalysis`
  - `GET /career/analyses/{resume_id}` — list past analyses for resume
  - `GET /career/roles?q=<search>` — search career_roles for autocomplete
  - `GET /career/analysis/{analysis_id}` — retrieve full analysis with path data
- [x] Register router in `backend/app/api/routes.py`

### 80F · Frontend — Career Path Page
- [x] Create `frontend/src/app/workspace/[resumeId]/career/page.tsx`:
  - Target role search input with autocomplete from `GET /career/roles?q=`
  - "Analyze Career Path" button → calls `POST /career/analyze`
  - Loading state with progress steps: "Parsing resume... Analyzing skills... Building path..."
- [x] Create `frontend/src/components/CareerPathChart.tsx`:
  - Uses **D3.js** (`d3-dag` or `@visx/network`) to render career transition graph
  - Nodes: role titles with level badges; current role (purple), path nodes (gray), target role (green)
  - Edges: labeled with avg years to transition
  - Highlight the recommended path from current → target
  - Click a node → show required skills for that role
- [x] Create `frontend/src/components/SkillsGapPanel.tsx`:
  - Two columns: "Skills You Have" (green chips) vs "Skills to Develop" (amber chips)
  - Timeline estimate: "Estimated path: ~N years with consistent growth"
  - Full LLM analysis text rendered as markdown below

### 80G · Tests
- [x] Create `backend/test/test_career_paths.py` — 19 tests (6 planned, extended):
  - `match_career_role`: "Software Engineer II" → matches seeded SWE Mid role
  - `find_path`: SWE Mid → Staff SWE returns ordered path of 2 intermediate roles
  - `POST /career/analyze` with valid resume_id → returns analysis with gap_skills
  - `GET /career/roles?q=data` → returns roles matching "data science"
  - Analysis for unrecognized target role → uses `target_role_freetext`, still returns LLM analysis
  - Past analyses listed in reverse chronological order

---

## Feature 81 — Resume Benchmarking / Anonymous Percentile · P3 · L

**Goal:** "Your resume scores in the top 23% of Software Engineering resumes on Latexy."
Anonymous aggregation of ATS scores across all resumes in the same industry bucket.
Only meaningful once sufficient volume exists (>1,000 scored resumes per industry).

### 81A · Backend — Anonymized Aggregation Service
- [x] Create `backend/app/services/benchmarking_service.py`:
  ```python
  class BenchmarkingService:
      CACHE_TTL_SECONDS = 3600   # Recompute hourly

      async def compute_percentile(
          self,
          ats_score: float,
          industry: str,
          db: AsyncSession,
          redis: Redis,
      ) -> BenchmarkResult:
          """
          BenchmarkResult:
            percentile: float         # 0–100, e.g. 77.3
            sample_size: int          # how many resumes in cohort
            cohort_median: float
            cohort_p25: float
            cohort_p75: float
            industry: str
            sufficient_data: bool     # False if sample_size < 100

          Query: SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY ats_score),
                        percentile_cont(0.25) ..., percentile_cont(0.75) ...,
                        COUNT(*), percent_rank() OVER (ORDER BY ats_score)
                 FROM optimization_history
                 JOIN resumes ON resumes.id = optimization_history.resume_id
                 WHERE resumes.metadata->>'detected_industry' = :industry
                   AND optimization_history.ats_score IS NOT NULL
          Cache result in Redis by industry key.
          """
  ```

### 81B · Backend — Endpoint
- [x] Add `GET /ats/benchmark?ats_score=<float>&industry=<str>` to `backend/app/api/ats_routes.py`:
  - Returns `BenchmarkResult` from `BenchmarkingService.compute_percentile()`
  - If `sufficient_data=False`: return result with `percentile=null`, message:
    `"Not enough data yet for [industry] benchmarking"`
  - Rate-limit: 10 calls per user per hour (Redis token bucket)

### 81C · Frontend — Percentile Badge
- [x] In `frontend/src/components/ATSScoreCard.tsx` (equivalent ATS results component):
  - After ATS score is shown, add "Benchmark" row:
    - If `sufficient_data=true`: "Top **N%** of [Industry] resumes on Latexy"
      with a mini bar chart showing distribution: p25 | p50 | p75 markers and user's score dot
    - If `sufficient_data=false`: "Benchmarking available once more [Industry] users join"
  - Call `GET /ats/benchmark` lazily on ATS panel open (not on every compile)
- [x] In `frontend/src/lib/api-client.ts`:
  - Add `getBenchmark(atsScore: number, industry?: string): Promise<BenchmarkResult>`

### 81D · Privacy Considerations
- [x] In `backend/app/api/ats_routes.py` benchmark endpoint:
  - Never return individual resume data — only aggregated statistics
  - Minimum cohort size of 50 before returning any data (`sufficient_data=false` if below threshold)
  - No user_id or resume_id in response — only aggregate percentile and distribution stats

### 81E · Tests
- [x] Create `backend/test/test_benchmarking.py` — 5 tests:
  - Score at p50 → percentile ≈ 50
  - Score above all others → percentile = 100
  - Sample size < 50 → `sufficient_data=False`, `percentile=None`
  - Unknown industry → returns generic cohort or `sufficient_data=False`
  - Result is Redis-cached: second call returns same result without DB query

---

## Feature 82 — LaTeX Snippet Marketplace · P3 · L

**Goal:** Community-shared LaTeX snippets — two-column skills tables, publication list templates,
timeline experience formats, boxed summary sections. Users browse, preview, install, and
contribute snippets directly from the editor sidebar.

### 82A · Database Migration
- [ ] Create `backend/alembic/versions/0022_add_snippets.py`:
  ```sql
  CREATE TABLE snippets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    author_id       UUID REFERENCES users(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    content         TEXT NOT NULL,                -- the LaTeX snippet source
    category        TEXT NOT NULL,                -- 'header' | 'experience' | 'skills' | 'education' | 'misc'
    tags            TEXT[] NOT NULL DEFAULT '{}',
    is_official     BOOLEAN NOT NULL DEFAULT FALSE,  -- Latexy-curated snippets
    installs_count  INT NOT NULL DEFAULT 0,
    upvotes_count   INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  );

  CREATE TABLE snippet_installs (
    snippet_id  UUID NOT NULL REFERENCES snippets(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    installed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (snippet_id, user_id)
  );

  CREATE TABLE snippet_upvotes (
    snippet_id  UUID NOT NULL REFERENCES snippets(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (snippet_id, user_id)
  );

  CREATE INDEX ON snippets(category);
  CREATE INDEX ON snippets(installs_count DESC);
  ```
  - `down_revision = '0021'`

### 82B · Backend — Models
- [ ] In `backend/app/database/models.py`:
  - Add `Snippet`, `SnippetInstall`, `SnippetUpvote` models

### 82C · Backend — Snippet Routes
- [ ] Create `backend/app/api/snippet_routes.py` with prefix `/snippets`:
  - Pydantic schemas:
    ```python
    class SnippetCreate(BaseModel):
        title: str = Field(..., min_length=3, max_length=100)
        description: str = Field(..., min_length=10, max_length=500)
        content: str = Field(..., min_length=10, max_length=10_000)
        category: Literal['header','experience','skills','education','misc']
        tags: list[str] = Field(default=[], max_length=10)

    class SnippetResponse(BaseModel):
        id: str
        title: str
        description: str
        content: str
        category: str
        tags: list[str]
        is_official: bool
        installs_count: int
        upvotes_count: int
        author_name: str | None
        created_at: datetime
        installed_by_me: bool     # true if current user has installed
        upvoted_by_me: bool
    ```
  - `GET /snippets?category=<str>&q=<search>&sort=popular|newest` — public list, paginated
  - `GET /snippets/{snippet_id}` — single snippet detail
  - `POST /snippets` — create (authenticated); content is screened for `\write18`,
    `\input{/etc`, `\immediate\write` to prevent shell injection in snippets
  - `PATCH /snippets/{snippet_id}` — update (author only)
  - `DELETE /snippets/{snippet_id}` — delete (author only)
  - `POST /snippets/{snippet_id}/install` — record install, increment `installs_count`
  - `DELETE /snippets/{snippet_id}/install` — uninstall
  - `POST /snippets/{snippet_id}/upvote` — toggle upvote (idempotent)
- [ ] Register router in `backend/app/api/routes.py`

### 82D · Backend — Official Snippet Seed
- [ ] Create `backend/app/data/official_snippets.py`:
  - At least 10 official snippets marked `is_official=True`:
    - Two-column skills table with `tabular`
    - Timeline experience section with `tikz` or `tcolorbox`
    - Boxed professional summary with `mdframed`
    - Publication list with `bibitem` entries
    - Awards / Honors formatted table
    - Multi-column interests / hobbies section

### 82E · Frontend — Marketplace Browser
- [ ] Create `frontend/src/components/SnippetMarketplace.tsx`:
  - Props: `onInsert: (content: string) => void`
  - Category tab strip: All / Header / Experience / Skills / Education / Misc
  - Sort dropdown: Most Popular | Newest | Official First
  - Search input: filters `title`, `description`, `tags`
  - Snippet cards: title, description, install count, upvote count, official badge, "Preview" + "Install" buttons
- [ ] Create `frontend/src/components/SnippetPreviewModal.tsx`:
  - Shows syntax-highlighted source with Monaco (read-only)
  - "Insert at Cursor" button → calls `onInsert(snippet.content)`
  - Shows rendered output description (static text, not compiled)
- [ ] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Add "Snippets" tab to editor sidebar
  - `onInsert` → `editorRef.current?.insertAtCursor(content)`

### 82F · Tests
- [ ] Create `backend/test/test_snippets.py` — 8 tests:
  - `GET /snippets` returns paginated list with `installed_by_me` correctly set
  - `POST /snippets` with `\write18{rm -rf /}` in content → 422 security rejection
  - `POST /snippets` authenticated → `installs_count=0`, `is_official=False`
  - `POST /snippets/{id}/install` → `installs_count` increments, `installed_by_me=True` in list
  - Double-install is idempotent (no error, count not double-incremented)
  - `POST /snippets/{id}/upvote` → toggles (on then off)
  - `DELETE /snippets/{id}` by non-author → 403
  - `GET /snippets?q=skills` → returns only snippets matching search term

---

## Feature 83 — Keyboard Macro System · P3 · L

**Goal:** Record a sequence of editor actions (keystrokes, insertions, replacements) and replay them
as a named macro bound to a keyboard shortcut. Useful for repetitive formatting tasks.
Monaco doesn't natively support macro recording — requires custom implementation.

### 83A · Database Migration (Cloud Sync)
- [x] Create `backend/alembic/versions/0023_add_user_macros.py`:
  ```sql
  CREATE TABLE user_macros (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    shortcut    TEXT,               -- e.g. "ctrl+shift+1"
    actions     JSONB NOT NULL,     -- serialized action sequence
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  CREATE INDEX ON user_macros(user_id);
  ```
  - `down_revision = '0022'`

### 83B · Macro Action Types
- [x] Create `frontend/src/lib/macros/macro-types.ts`:
  ```typescript
  export type MacroAction =
    | { type: 'insert'; text: string }
    | { type: 'move'; direction: 'up' | 'down' | 'left' | 'right'; count: number }
    | { type: 'select'; startLine: number; startCol: number; endLine: number; endCol: number }
    | { type: 'delete'; direction: 'forward' | 'backward'; count: number }
    | { type: 'replace'; search: string; replacement: string; all: boolean }
    | { type: 'command'; monacoCommand: string }  // e.g. 'editor.action.commentLine'

  export interface Macro {
    id: string
    name: string
    description?: string
    shortcut?: string
    actions: MacroAction[]
  }
  ```

### 83C · Macro Recorder Engine
- [x] Create `frontend/src/lib/macros/macro-recorder.ts`:
  ```typescript
  export class MacroRecorder {
    private recording = false
    private actions: MacroAction[] = []

    startRecording(editor: monaco.editor.IStandaloneCodeEditor): void
    stopRecording(): MacroAction[]

    // Hooks into Monaco events during recording:
    // - editor.onDidChangeModelContent: captures insertions/deletions
    // - editor.onDidChangeCursorPosition: captures cursor moves
    // - editor.onDidChangeCursorSelection: captures selections
  }
  ```

### 83D · Macro Player Engine
- [x] Create `frontend/src/lib/macros/macro-player.ts`:
  ```typescript
  export class MacroPlayer {
    async play(
      macro: Macro,
      editor: monaco.editor.IStandaloneCodeEditor
    ): Promise<void>
    // Executes each MacroAction sequentially:
    // - 'insert': editor.executeEdits('macro', [{ range: cursor, text }])
    // - 'move': editor.setPosition(...)
    // - 'replace': find all in model, executeEdits for each
    // - 'command': editor.getAction(id)?.run()
  }
  ```

### 83E · Backend — Macro Sync Endpoints
- [x] Create `backend/app/api/macro_routes.py` with prefix `/macros`:
  - `GET /macros` — list current user's macros
  - `POST /macros` — create macro (name, description, shortcut, actions JSONB)
  - `GET /macros/{macro_id}` — fetch full macro with actions
  - `PATCH /macros/{macro_id}` — update name / description / shortcut
  - `DELETE /macros/{macro_id}` — delete
- [x] Register router in `backend/app/api/routes.py`
- [x] Add `getMacros`, `createMacro`, `getMacro`, `updateMacro`, `deleteMacro` to `frontend/src/lib/api-client.ts`

### 83F · Frontend — Macro Library Panel
- [x] Create `frontend/src/components/MacroLibraryPanel.tsx`:
  - Record/Stop button with recording indicator (pulsing red dot)
  - Macro list: name, shortcut badge, description, Play / Delete buttons
  - Empty state when no macros saved
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Add "Macros" tab to editor sidebar (Keyboard icon)
  - Add `'macros'` to `RightTab` union type
  - Expose `getEditor()` on `LaTeXEditorRef` for MacroRecorder/Player access

### 83G · Tests
- [x] Create `backend/test/test_macros.py` — 5 tests:
  - Unauthenticated → 401
  - Create macro → 201 with id and actions
  - List macros → returns created macro
  - Update macro name → 200 with new name
  - Delete macro → 204, subsequent GET → 404

---

## Feature 84 — TikZ / Diagram Visual Editor · P3 · XL

**Goal:** Drag-and-drop visual editor for TikZ diagrams (timeline, skill bars, flowcharts, and
network diagrams) that generates valid TikZ code. Target: academic CVs and technical resumes.
Output is inserted as LaTeX at cursor position. No new DB schema needed.

### 84A · TikZ Code Generator
- [ ] Create `frontend/src/lib/tikz/tikz-generator.ts`:
  ```typescript
  export type DiagramType = 'timeline' | 'skill-bars' | 'flowchart' | 'network'

  export interface TimelineEntry { year: string; label: string; description: string }
  export interface SkillBar { skill: string; level: number }  // level 0–10
  export interface FlowNode { id: string; label: string; x: number; y: number; shape: 'rect'|'diamond'|'circle' }
  export interface FlowEdge { from: string; to: string; label?: string }

  export function generateTimeline(entries: TimelineEntry[]): string  // → TikZ code
  export function generateSkillBars(skills: SkillBar[]): string
  export function generateFlowchart(nodes: FlowNode[], edges: FlowEdge[]): string
  ```
  - Each generator outputs self-contained TikZ code wrapped in `\begin{tikzpicture}...\end{tikzpicture}`
  - Include required `\usetikzlibrary{...}` directives as comments at the top

### 84B · Timeline Generator
- [ ] `generateTimeline` produces:
  ```latex
  % Requires: \usepackage{tikz} \usetikzlibrary{positioning}
  \begin{tikzpicture}[every node/.style={font=\small}]
    \draw[thick, ->] (0,0) -- (0,-8);   % vertical spine
    % For each entry at y offset:
    \draw (-0.15, -N) -- (0.15, -N);    % tick mark
    \node[right] at (0.3, -N) {\textbf{YEAR} — LABEL};
    \node[right, text width=5cm] at (0.3, -N-0.4) {DESCRIPTION};
  \end{tikzpicture}
  ```

### 84C · Skill Bars Generator
- [ ] `generateSkillBars` produces:
  ```latex
  % Requires: \usepackage{tikz}
  \begin{tikzpicture}
    % For each skill at y offset:
    \node[left] at (0, -N) {SKILL};
    \fill[gray!30] (0, -N-0.15) rectangle (5, -N+0.15);      % background
    \fill[violet!70] (0, -N-0.15) rectangle (LEVEL/2, -N+0.15); % fill bar
  \end{tikzpicture}
  ```

### 84D · Visual Editor Canvas
- [ ] Create `frontend/src/components/TikZEditor.tsx`:
  - Tabs: "Timeline" | "Skill Bars" | "Flowchart" | "Network"
  - **Timeline tab**: ordered list of entries (year, label, description). Add/remove/drag-to-reorder.
  - **Skill bars tab**: list of (skill name, level slider 1–10). Add/remove.
  - **Flowchart tab**: simplified node palette (rectangle, diamond, circle). Click to add, drag to position,
    click two nodes to connect with arrow, label edges.
    (Uses **@xyflow/react** / React Flow for the canvas)
  - **Network tab**: same as flowchart but bidirectional edges and circular layout
  - Live TikZ code preview (syntax-highlighted, read-only Monaco instance) updates on every change
  - "Insert into Document" button → `editorRef.current?.insertAtCursor(tikzCode)`
  - "Copy TikZ" button

### 84E · Compile Preview
- [ ] Add "Preview Diagram" button in `TikZEditor`:
  - Wraps generated TikZ in minimal `\documentclass{standalone}` document
  - Posts to `POST /compile` with the standalone LaTeX source
  - Shows compiled PNG/PDF thumbnail inline in the editor panel

### 84F · Integration
- [ ] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Add "TikZ" tab to editor sidebar
  - Render `<TikZEditor onInsert={(code) => editorRef.current?.insertAtCursor(code)} />`
- [ ] In editor `LaTeXEditor.tsx`:
  - Ensure `insertAtCursor` properly handles multi-line TikZ blocks (inserts with newlines before/after)

### 84G · Generator Unit Tests
- [ ] Create `frontend/src/lib/tikz/__tests__/tikz-generator.test.ts`:
  - `generateTimeline([...])` output contains `\begin{tikzpicture}` and `\end{tikzpicture}`
  - Timeline with 3 entries has 3 `\node[right]` occurrences
  - `generateSkillBars([{skill:'Python', level:8}])` → bar fill width is proportional to level
  - `generateFlowchart` with diamond node → output contains `diamond` shape keyword

---

## Feature 85 — White-Label for Agencies / Career Centers · P3 · XL

**Goal:** Full multi-tenancy: university career centers and recruiting agencies deploy Latexy
under their own brand with custom domain, logo, colors, and per-tenant user management.
Requires a parallel tenant-aware routing layer and per-tenant billing.

### 85A · Database Migration
- [ ] Create `backend/alembic/versions/0024_add_tenants.py`:
  ```sql
  CREATE TABLE tenants (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug             TEXT NOT NULL UNIQUE,           -- subdomain: slug.latexy.io
    custom_domain    TEXT UNIQUE,                    -- resume.mycollege.edu (nullable)
    name             TEXT NOT NULL,
    logo_url         TEXT,
    primary_color    CHAR(7),                        -- "#6d28d9" hex
    owner_id         UUID NOT NULL REFERENCES users(id),
    plan_id          TEXT NOT NULL DEFAULT 'agency', -- maps to Razorpay plan
    max_members      INT NOT NULL DEFAULT 50,
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
  );

  CREATE TABLE tenant_members (
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role         TEXT NOT NULL DEFAULT 'member',     -- 'admin' | 'member'
    joined_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
  );

  ALTER TABLE users ADD COLUMN default_tenant_id UUID REFERENCES tenants(id) ON DELETE SET NULL;
  ```
  - `down_revision = '0023'`

### 85B · Backend — Models
- [ ] In `backend/app/database/models.py`:
  - Add `Tenant`, `TenantMember` models
  - Add `default_tenant_id` to `User`

### 85C · Backend — Tenant Resolution Middleware
- [ ] Create `backend/app/middleware/tenant_middleware.py`:
  ```python
  class TenantMiddleware(BaseHTTPMiddleware):
      """Resolves current tenant from Host header or X-Tenant-Slug header.
      Attaches tenant_id to request.state for use in route handlers."""
      async def dispatch(self, request: Request, call_next):
          host = request.headers.get("host", "")
          # Check if custom_domain matches
          # Check if subdomain slug matches (slug.latexy.io)
          # Set request.state.tenant_id (or None for main latexy.io)
  ```
- [ ] Register middleware in `backend/app/main.py`

### 85D · Backend — Tenant Admin Routes
- [ ] Create `backend/app/api/tenant_routes.py` with prefix `/tenants`:
  - `POST /tenants` — create tenant (owner_id = current user)
  - `GET /tenants/my` — list tenants where current user is owner or admin
  - `PATCH /tenants/{tenant_id}` — update branding (logo_url, primary_color, name)
  - `POST /tenants/{tenant_id}/members/invite` — invite user by email
  - `DELETE /tenants/{tenant_id}/members/{user_id}` — remove member
  - `GET /tenants/{tenant_id}/members` — list members
  - `POST /tenants/{tenant_id}/domain/verify` — initiate DNS TXT record verification
  - `GET /tenants/{tenant_id}/stats` — member count, total resumes, avg ATS score
- [ ] Register router in `backend/app/api/routes.py`

### 85E · Frontend — Tenant Admin Dashboard
- [ ] Create `frontend/src/app/admin/tenant/page.tsx`:
  - Branding editor: logo upload, primary color picker (updates CSS custom properties live)
  - Member management: invite by email, list members with roles, remove members
  - Domain settings: input custom domain, show DNS TXT verification instructions
  - Stats cards: members, resumes shared, compilations this month

### 85F · Frontend — Tenant Theme Injection
- [ ] Create `frontend/src/lib/tenant-theme.ts`:
  ```typescript
  export function applyTenantTheme(tenant: TenantBranding): void {
    document.documentElement.style.setProperty('--color-primary', tenant.primary_color)
    // Replace logo element src
  }
  ```
- [ ] In `frontend/src/app/layout.tsx`:
  - On mount: `GET /tenants/current-context` (resolved by middleware from Host header) →
    if tenant found, call `applyTenantTheme()`
  - Show tenant logo in nav if tenant is set

### 85G · Tests
- [ ] Create `backend/test/test_tenants.py` — 8 tests:
  - Create tenant → slug is unique; duplicate slug → 409
  - Tenant middleware resolves tenant from `Host: myslug.latexy.io` header
  - Non-owner cannot `PATCH /tenants/{id}`
  - Invite member → `TenantMember` row created
  - Remove member → row deleted
  - `GET /tenants/{id}/stats` returns correct member count
  - Custom domain stored and retrievable
  - `primary_color: "not-a-hex"` → 422 validation error

---

## Feature 86 — Presentation / Beamer Support · P3 · L

**Goal:** Extend Latexy beyond resumes to LaTeX Beamer presentations. Academic users who use
Latexy for CVs can also create conference presentations. Requires Beamer-specific templates, a
slide-based PDF viewer, and a document type system.

### 86A · Database Migration
- [ ] Create `backend/alembic/versions/0025_add_document_type.py`:
  ```sql
  ALTER TABLE resumes
    ADD COLUMN document_type TEXT NOT NULL DEFAULT 'resume';
  -- Values: 'resume' | 'presentation' | 'academic_cv'

  CREATE INDEX ON resumes(user_id, document_type);
  ```
  - `down_revision = '0024'`

### 86B · Backend — Model Update
- [ ] In `backend/app/database/models.py`:
  - Add `document_type: Mapped[str]` to `Resume` model (default `'resume'`)

### 86C · Backend — Slide Count Extraction
- [ ] In `backend/app/workers/latex_worker.py`:
  - After successful Beamer compilation, extract slide count from pdflatex log:
    `Output written on output.pdf (N pages, ...)` — already extracted as `page_count`
  - Include `slide_count: int` (= `page_count` for presentations) in compile result
  - Beamer documents are detected by `\documentclass{beamer}` in source

### 86D · Backend — Beamer Templates
- [ ] In `backend/app/database/seed_templates.py` (or equivalent template loader):
  - Add 5 Beamer presentation templates:
    - `beamer_madrid` — Madrid theme, conference talk format
    - `beamer_metropolis` — Metropolis theme (modern, minimal)
    - `beamer_warsaw` — Warsaw theme, academic seminar
    - `beamer_research` — Research group lab presentation
    - `beamer_pitch` — Startup / product pitch deck style
  - Each template: full Beamer document with sample frames, title slide, TOC, section structure
  - `document_type = 'presentation'`, `is_template = True`

### 86E · Frontend — Slide Viewer
- [ ] Create `frontend/src/components/SlideViewer.tsx`:
  - Props: `pdfUrl: string`, `slideCount: number`
  - Renders PDF via `react-pdf` (PDF.js) in single-page mode (one slide at a time)
  - Navigation: Previous / Next slide buttons, keyboard arrow keys
  - Slide counter: "Slide 3 / 12"
  - Thumbnail strip: horizontal scrollable strip of all slides (rendered at low resolution)
    clicking a thumbnail jumps to that slide
  - Fullscreen presentation mode button → browser Fullscreen API

### 86F · Frontend — Document Type Awareness
- [ ] In workspace page: when creating a new document, show type selector:
  "Resume" | "Presentation" | "Academic CV"
- [ ] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - If `resume.document_type === 'presentation'`: show `<SlideViewer>` instead of `<PDFPreview>`
  - If presentation: hide ATS score features, hide optimization panel, show slide count in status bar
  - Slide count badge in editor status bar for presentations

### 86G · Tests
- [ ] Create `backend/test/test_beamer.py` — 4 tests:
  - `document_type: 'presentation'` stored and returned in GET
  - Compile result for Beamer source includes `page_count > 0`
  - Filter `GET /resumes/?document_type=presentation` returns only presentations
  - Beamer template seeds: 5 templates with `document_type='presentation'` exist after seed

---

## Feature 87 — One-Click Job Application Integration · P3 · XL

**Goal:** After optimizing a resume, apply directly to jobs on Greenhouse and Lever from within
Latexy. LinkedIn Easy Apply is restricted to LinkedIn's own clients — use Greenhouse / Lever
public APIs for direct integration. Auto-updates job tracker on successful application.

### 87A · Database Migration
- [ ] Create `backend/alembic/versions/0026_add_application_submissions.py`:
  ```sql
  CREATE TABLE application_submissions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    resume_id        UUID REFERENCES resumes(id) ON DELETE SET NULL,
    job_tracker_id   UUID REFERENCES job_applications(id) ON DELETE SET NULL,
    platform         TEXT NOT NULL,     -- 'greenhouse' | 'lever' | 'manual'
    platform_job_id  TEXT,
    application_url  TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'submitted' | 'failed'
    submitted_at     TIMESTAMPTZ,
    error_message    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  CREATE INDEX ON application_submissions(user_id);
  ```
  - `down_revision = '0025'`

### 87B · Backend — Platform Integration Services
- [ ] Create `backend/app/services/greenhouse_service.py`:
  ```python
  class GreenhouseService:
      # Uses Greenhouse Job Board API (public, no auth required for reading)
      # Uses Greenhouse Application API (requires job-specific tokens embedded in apply links)
      BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}"

      async def get_job_details(self, company: str, job_id: str) -> dict:
          """GET job details: title, company, description, apply_url, custom_fields."""

      async def submit_application(
          self,
          company: str,
          job_id: str,
          applicant: ApplicantData,  # name, email, phone, resume_pdf_bytes, cover_letter_text
      ) -> dict:
          """POST to Greenhouse job board application endpoint with multipart form data.
          Returns { id, status }."""
  ```
- [ ] Create `backend/app/services/lever_service.py`:
  ```python
  class LeverService:
      BASE_URL = "https://api.lever.co/v0/postings/{company}/{posting_id}"

      async def get_posting(self, company: str, posting_id: str) -> dict: ...
      async def apply(
          self, company: str, posting_id: str, applicant: ApplicantData
      ) -> dict: ...
  ```

### 87C · Backend — Application Routes
- [ ] Create `backend/app/api/application_routes.py` with prefix `/apply`:
  - `POST /apply/greenhouse` — body: `{ job_url, resume_id, cover_letter_text? }` →
    parse company/job_id from URL, fetch PDF from MinIO, submit via `GreenhouseService`,
    create `ApplicationSubmission`, optionally create/update `JobApplication` tracker entry
  - `POST /apply/lever` — same flow for Lever
  - `GET /apply/submissions` — list user's submission history with status
  - `GET /apply/submissions/{submission_id}` — single submission detail
- [ ] Register router in `backend/app/api/routes.py`

### 87D · Frontend — Apply Modal
- [ ] Create `frontend/src/components/ApplyModal.tsx`:
  - Props: `resumeId: string`, `jobUrl?: string`
  - Step 1: Paste job URL → auto-detect platform (Greenhouse: `boards.greenhouse.io`,
    Lever: `jobs.lever.co`)
  - Step 2: Show detected job: company, role title, location (from API fetch)
  - Step 3: Review resume to submit (dropdown to select resume variant)
  - Step 4: Optional cover letter textarea
  - "Submit Application" button → calls `POST /apply/{platform}`
  - Success: "Application submitted! Added to your job tracker." with link to tracker
  - Error: show error message, offer "Open in browser" fallback

### 87E · Frontend — Quick Apply from Workspace
- [ ] In workspace resume card actions: "Quick Apply" button
  - Opens `<ApplyModal resumeId={id} />`
- [ ] In `frontend/src/lib/api-client.ts`:
  - `applyGreenhouse(jobUrl, resumeId, coverLetter?)`, `applyLever(...)`, `getSubmissions()`

### 87F · Tests
- [ ] Create `backend/test/test_apply.py` — 6 tests:
  - `GreenhouseService.get_job_details` with mocked HTTP → parses company/title correctly
  - `POST /apply/greenhouse` with invalid job URL → 422
  - `POST /apply/greenhouse` with unknown company → 404 from upstream → returns 502 with message
  - Successful submission → `ApplicationSubmission.status = 'submitted'`, `submitted_at` set
  - Failed submission → `status = 'failed'`, `error_message` populated
  - `GET /apply/submissions` returns only current user's submissions

---

## Feature 88 — Compile Error History · P3 · S

**Goal:** Track which compilation errors a user has encountered and fixed over time.
Build a personal "error log" helping users recognize recurring mistakes. Uses existing
`compilations` table — no new schema required.

### 88A · Backend — Error Aggregation Service
- [ ] Create `backend/app/services/error_history_service.py`:
  ```python
  class ErrorHistoryService:
      async def get_error_history(
          self, user_id: str, db: AsyncSession, limit: int = 50
      ) -> list[ErrorHistorySummary]:
          """
          Query compilations table for rows where status='failed'.
          Parse error_log: extract ! Error lines using existing regex from latex_worker.
          Group by error_type (first word after ! in pdflatex output).
          Return:
            ErrorHistorySummary:
              error_type: str        # e.g. "Undefined control sequence"
              count: int             # how many times seen
              last_seen: datetime
              last_resume_id: str
              last_resume_title: str
              example_line: str      # the specific erroneous line (first occurrence)
              resolved: bool         # true if a successful compile followed this error
          """
  ```

### 88B · Backend — Endpoint
- [ ] Add `GET /resumes/error-history?limit=50` to `backend/app/api/resume_routes.py`:
  - Returns list of `ErrorHistorySummary` from `ErrorHistoryService.get_error_history()`
  - Grouped and sorted by `count DESC, last_seen DESC`

### 88C · Frontend — Error History Panel
- [ ] Create `frontend/src/components/CompileErrorHistory.tsx`:
  - Triggered from editor by "Error History" button in Log Viewer panel header
  - Displays table: Error Type | Times Encountered | Last Seen | Status (Resolved / Recurring)
  - Click a row → expand details with `example_line` and link to the resume it occurred in
  - "Most common mistake" banner for error_type with highest count
  - Empty state: "No compile errors yet — great work!"
- [ ] In `frontend/src/lib/api-client.ts`:
  - Add `getErrorHistory(): Promise<ErrorHistorySummary[]>`

### 88D · Tests
- [ ] Create `backend/test/test_error_history.py` — 4 tests:
  - User with 3 failed compilations → `get_error_history` returns 3 grouped entries
  - Same error in multiple compilations → `count > 1` in summary
  - Error followed by successful compile → `resolved: true`
  - Empty history (no failed compilations) → returns empty list, not 404

---

## Feature 89 — Print Preview Mode · P3 · S

**Goal:** Preview how the resume looks when printed on a black-and-white printer.
Applies a grayscale CSS filter to the PDF canvas — purely display-side, original PDF unmodified.
Zero backend changes.

### 89A · Frontend — Toggle Button
- [ ] In `frontend/src/components/PDFPreview.tsx` (or equivalent PDF viewer component):
  - Add `printPreviewMode: boolean` state (default `false`)
  - "B&W Print Preview" button in PDF viewer toolbar (printer icon)
  - When `printPreviewMode=true`:
    - Apply `filter: grayscale(1) contrast(1.05)` to the PDF canvas/iframe wrapper
    - Show amber banner: "Print Preview — showing how this looks on a B&W printer"
  - Toggle off restores full color

### 89B · Color Dependency Warnings
- [ ] In print preview mode, run a lightweight analysis of the LaTeX source:
  - Check for `\textcolor`, `\color`, `\colorbox`, `\definecolor` usage
  - If found: show warning list under the preview: "Color-dependent elements detected —
    these may become invisible or lose meaning in grayscale print:"
  - List each detected color usage with the line number (link to editor line)

### 89C · Integration
- [ ] Add `printPreviewMode` prop to `LaTeXEditor.tsx` if needed to pass line warnings back
- [ ] Persist print preview mode preference to `localStorage` per user

---

## Feature 90 — Export to Canva / Figma · P3 · M

**Goal:** Export resume content as structured JSON to Canva (via Content Import API) or
Figma (via plugin API), allowing users to create a visually designed resume version.
Complements the ATS-safe LaTeX version with a design-focused output.

### 90A · Backend — Canva-Compatible Export Format
- [ ] Add `GET /resumes/{resume_id}/export/canva` to `backend/app/api/export_routes.py`:
  ```python
  class CanvaResumeExport(BaseModel):
      # Canva Content Import API format
      type: str = "DESIGN"
      elements: list[CanvaElement]

  class CanvaElement(BaseModel):
      type: str    # "TEXT" | "HEADING" | "DIVIDER"
      text: str
      style: dict  # bold, italic, fontSize

  # Implementation:
  # 1. Extract resume JSON via DocumentExportService.to_json() (already implemented)
  # 2. Map sections → Canva element array:
  #    - section titles → HEADING elements
  #    - company/role → TEXT bold
  #    - date range → TEXT small
  #    - bullets → TEXT bulleted
  # 3. Return as Canva-compatible JSON
  ```

### 90B · Backend — Figma-Compatible Export Format
- [ ] Add `GET /resumes/{resume_id}/export/figma` to `backend/app/api/export_routes.py`:
  - Returns structured JSON mapping resume sections to Figma text nodes:
    ```python
    class FigmaResumeExport(BaseModel):
        sections: list[FigmaSection]

    class FigmaSection(BaseModel):
        title: str
        entries: list[FigmaEntry]

    class FigmaEntry(BaseModel):
        heading: str
        subheading: str
        date: str
        bullets: list[str]
    ```
  - This JSON is consumed by a Figma plugin (separate artifact) that populates a resume frame

### 90C · Frontend — Export Buttons
- [ ] In `frontend/src/components/ExportDropdown.tsx` (or wherever export options are shown):
  - Add "Export to Canva" option: calls `GET /resumes/{id}/export/canva`,
    then opens Canva import URL with the JSON payload
  - Add "Export to Figma" option: calls `GET /resumes/{id}/export/figma`,
    downloads `resume-figma.json` for use in Figma plugin
  - Both options show tooltip: "Opens [Canva/Figma] with your resume content pre-filled"
- [ ] In `frontend/src/lib/api-client.ts`:
  - Add `exportCanva(resumeId: string): Promise<CanvaResumeExport>`
  - Add `exportFigma(resumeId: string): Promise<Blob>` (returns downloadable JSON)

### 90D · Figma Plugin (Separate Artifact)
- [ ] Create `frontend/figma-plugin/` directory:
  - `manifest.json`: Figma plugin manifest with `networkAccess: ["latexy.io"]`
  - `code.ts`: plugin entry that reads the JSON and populates a Figma resume template frame
  - `ui.html`: simple plugin UI: "Fetch from Latexy" button, API key input
  - This plugin is published to the Figma Community separately

### 90E · Tests
- [ ] Create `backend/test/test_export_canva_figma.py` — 4 tests:
  - `GET /resumes/{id}/export/canva` returns JSON with `elements` array non-empty
  - Section headers appear as `type: "HEADING"` elements
  - `GET /resumes/{id}/export/figma` returns JSON with `sections` array
  - Non-owner trying to export another user's resume → 403

---

## Cross-Feature Notes

### Alembic Migration Chain for P3
```
0019_add_portfolio.py           ← last P2 migration (F67/F68)
  └── 0020_add_dropbox_integration.py       (F77)
        └── 0021_add_career_paths.py         (F80)
              └── 0022_add_snippets.py       (F82)
                    └── 0023_add_user_macros.py  (F83)
                          └── 0024_add_tenants.py   (F85)
                                └── 0025_add_document_type.py  (F86)
                                      └── 0026_add_application_submissions.py  (F87)
```
Features with no DB migrations: F78 (WYSIWYG), F79 (PWA), F81 (benchmarking uses existing tables),
F84 (TikZ — frontend only), F88 (error history — queries existing compilations), F89 (print preview — frontend only), F90 (Canva/Figma export).

### Recommended Dependency Order
- F88 and F89 are completely independent — build first as warm-up
- F77 (Dropbox) mirrors F37 (GitHub) — reuse service patterns
- F82 (Snippets) before F83 (Macros) — both add sidebar tabs, establish sidebar extension pattern
- F85 (White-Label) requires careful multi-tenant testing — build last among L features
- F78 (WYSIWYG) and F84 (TikZ) are the highest-risk XL features — prototype parser/generator before committing to full UI
