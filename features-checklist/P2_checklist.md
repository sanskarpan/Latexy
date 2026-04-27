# P2 Feature Implementation Checklist

> Deep implementation guide for all 42 P2 features. Each item maps directly to the current codebase —
> file paths, specific functions, and exact changes. Work through features in dependency order.
>
> **Branch convention:** one branch per feature (e.g. `feat/spell-check`)
> **Key files to know:** see `MEMORY.md` for architecture overview.
> **Numbering:** continues from P1 (Features 9–34); P2 starts at Feature 35.

---

## Legend
- `[ ]` — not started
- `[x]` — done
- `[~]` — in progress
- Complexity: **S** = < 1 week | **M** = 1–3 weeks | **L** = 1–2 months | **XL** = 3+ months

---

## Build Order (recommended)

```
Quick wins first (S complexity, highest ROI):
  76 → 61 → 65 → 52 → 48 → 62 → 47 → 57 → 49 → 55 → 64 → 70 → 71 → 36 → 39

Medium features (M complexity):
  38 → 43 → 44 → 45 → 56 → 53 → 54 → 58 → 59 → 51 → 60 → 63 → 69 → 72 → 75

Large features (own 2–4 week sprints):
  35 → 46 → 50 → 37 → 42 → 66 → 67 → 68 → 73 → 74

XL features (requires dedicated project):
  40 → 41
```

---

## Feature 35 — Spell Check & Grammar · P2 · L

**Goal:** LaTeX-aware spell/grammar checking via LanguageTool REST API. Strips LaTeX commands to
isolate prose, maps errors back to original LaTeX line/col positions as Monaco diagnostic markers.
Red squiggle = spelling; blue squiggle = grammar. Personal dictionary in localStorage.

### 35A · Backend — Text Extractor Service
- [x] Create `backend/app/services/latex_text_extractor.py`:
  - Reuse / extend existing extraction logic in `document_export_service.py`
  - `extract_prose(latex_content: str) -> List[ProseSegment]`
    ```python
    @dataclass
    class ProseSegment:
        text: str
        start_line: int
        start_col: int      # for back-mapping LT offset → original LaTeX position
    ```
  - Strip: all `\command{...}` sequences, `\begin{...}...\end{...}` environments,
    `$...$` math, `$$...$$` display math, `%` comments, `\[...\]` display math
  - Preserve prose inside: `\textbf{}`, `\textit{}`, `\section{}`, `\item`, plain lines
  - Return list of segments with original line/col offsets for error back-mapping

### 35B · Backend — LanguageTool Endpoint
- [x] Add `POST /ai/spell-check` to `backend/app/api/ai_routes.py`:
  ```python
  class SpellCheckRequest(BaseModel):
      latex_content: str = Field(..., max_length=200_000)
      language: str = Field(default="en-US", max_length=10)

  class SpellCheckIssue(BaseModel):
      line: int
      column_start: int
      column_end: int
      severity: str          # "spelling" | "grammar" | "style"
      message: str
      replacements: List[str]   # up to 5 suggestions
      rule_id: str

  class SpellCheckResponse(BaseModel):
      issues: List[SpellCheckIssue]
      cached: bool
  ```
  - POST to LT: `text=extracted_prose&language={language}&enabledOnly=false`
  - Map LT `offset` (char index in extracted text) → original LaTeX line/col via ProseSegment
  - Cache by `hash(latex_content + language)`, TTL=3600
  - On LT timeout/error: return empty issues list (not 500)

### 35C · Config
- [x] Add to `backend/app/core/config.py`:
  ```python
  LANGUAGETOOL_URL: str = "https://api.languagetool.org/v2/check"
  LANGUAGETOOL_LOCAL_URL: Optional[str] = None   # self-hosted LT override
  SPELL_CHECK_MAX_CHARS: int = 50_000            # LT free tier limit
  ```

### 35D · Frontend — Spell Check Hook
- [x] Create `frontend/src/hooks/useSpellCheck.ts`:
  - Props: `latexContent: string`, `enabled: boolean`, `debounceMs: number = 5000`
  - Debounces calls to `apiClient.spellCheck(latexContent)`
  - Returns `issues: SpellCheckIssue[]`
  - Filters out words present in `localStorage.getItem('latexy_dictionary')`

### 35E · Frontend — Monaco Integration
- [x] In `frontend/src/components/LaTeXEditor.tsx`:
  - Add prop: `spellCheckIssues?: SpellCheckIssue[]`
  - In `useEffect` on `spellCheckIssues` change: call `monaco.editor.setModelMarkers()` with
    owner `"spellcheck"`:
    - Spelling → `MarkerSeverity.Warning` (yellow squiggle)
    - Grammar → `MarkerSeverity.Info` (blue squiggle)
  - Right-click context menu on markers: show top 5 replacements as clickable items
  - Click replacement → `editor.executeEdits('spellcheck', [{ range, text: replacement }])`
  - "Add to Dictionary" action per marker → adds to localStorage word list

### 35F · Frontend — Toggle + Integration
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Add `spellCheckEnabled: boolean` state (default false, persisted to localStorage)
  - "ABC ✓" toggle button in editor status bar (green when on)
  - Wire `useSpellCheck` hook, pass `spellCheckIssues` to `LaTeXEditor`

### 35G · Tests
- [x] `backend/test/test_spell_check.py`:
  - `extract_prose()` strips `\textbf{word}` wrapper but preserves "word"
  - `extract_prose()` strips `$\alpha$` entirely
  - `extract_prose()` preserves text after `\item`
  - Endpoint returns issues list (mocked LT response)
  - Endpoint handles LT timeout gracefully (empty list, not 500)
  - `language="invalid-xx"` → 422

---

## Feature 36 — Symbol Palette · P2 · S

**Goal:** Toggleable sidebar panel with categorized LaTeX math symbol grid. Click inserts
`\command` at current cursor position. No backend changes needed.

### 36A · Symbol Data
- [x] Create `frontend/src/lib/latex-symbols.ts`:
  ```typescript
  export interface LaTeXSymbol {
    unicode: string     // rendered display: "α"
    command: string     // LaTeX: "\\alpha"
    name: string        // searchable: "alpha greek letter"
    package?: string    // "amssymb" | "amsmath" etc. (undefined = core)
    category: SymbolCategory
  }

  export type SymbolCategory =
    | 'greek' | 'operators' | 'arrows' | 'relations'
    | 'set_notation' | 'misc' | 'accents' | 'delimiters'

  export const LATEX_SYMBOLS: LaTeXSymbol[] = [
    // Greek lowercase
    { unicode: 'α', command: '\\alpha', name: 'alpha greek letter', category: 'greek' },
    { unicode: 'β', command: '\\beta',  name: 'beta greek letter',  category: 'greek' },
    // ... all 48 Greek letters (α–ω uppercase + lowercase)
    // Math operators
    { unicode: '∫', command: '\\int',  name: 'integral',            category: 'operators' },
    { unicode: '∑', command: '\\sum',  name: 'sum summation sigma', category: 'operators', package: 'amsmath' },
    { unicode: '∏', command: '\\prod', name: 'product',             category: 'operators' },
    // Arrows
    { unicode: '→', command: '\\rightarrow', name: 'right arrow', category: 'arrows' },
    { unicode: '⇒', command: '\\Rightarrow', name: 'double right arrow implies', category: 'arrows' },
    // ... full set targeting 200+ symbols
  ]
  ```

### 36B · SymbolPalette Component
- [x] Create `frontend/src/components/SymbolPalette.tsx`:
  - Props: `onInsert: (command: string) => void`
  - Search input at top: filters by `name` and `command`
  - Category tabs: Greek · Operators · Arrows · Relations · Set Notation · Misc
  - 8-column grid of symbol cards: show `unicode` (large) + hover shows `command` (monospace, small)
  - Tooltip: name + package requirement (if any)
  - Click → `onInsert(symbol.command)`

### 36C · Editor Integration
- [x] In `frontend/src/components/LaTeXEditor.tsx`:
  - Ensure `insertAtCursor(text: string)` is exposed on `LaTeXEditorRef`
    (uses `editor.executeEdits('symbol-palette', [{ range: selection || cursor, text }])`)

### 36D · Page Integration
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Add "Ω Symbols" tab to editor sidebar
  - Render `<SymbolPalette onInsert={(cmd) => editorRef.current?.insertAtCursor(cmd)} />`

---

## Feature 37 — GitHub / Git Integration · P2 · L

**Goal:** Connect GitHub account via OAuth. Per-resume "Enable GitHub Sync" toggle. Every
checkpoint save commits LaTeX source to a linked private GitHub repo. Pull changes back.

### 37A · Database Migration
- [x] Create `backend/alembic/versions/0012_add_github_integration.py`:
  ```sql
  ALTER TABLE users ADD COLUMN github_access_token TEXT;
  ALTER TABLE users ADD COLUMN github_username TEXT;
  ALTER TABLE resumes ADD COLUMN github_sync_enabled BOOLEAN DEFAULT FALSE;
  ALTER TABLE resumes ADD COLUMN github_repo_name TEXT;
  ALTER TABLE resumes ADD COLUMN github_last_sync_at TIMESTAMPTZ;
  ```

### 37B · Backend — Models
- [x] In `backend/app/database/models.py`:
  - Add `github_access_token`, `github_username` to `User` model
  - Add `github_sync_enabled`, `github_repo_name`, `github_last_sync_at` to `Resume` model

### 37C · Config
- [x] Add to `backend/app/core/config.py`:
  ```python
  GITHUB_OAUTH_REDIRECT_URI: str = "http://localhost:8030/github/callback"
  ```

### 37D · Backend — GitHub OAuth Routes
- [x] Create `backend/app/api/github_routes.py`:
  - `GET /github/connect` → redirects to GitHub OAuth authorization URL
  - `GET /github/callback?code=...` → exchanges code for token via
    `POST https://github.com/login/oauth/access_token`, stores in `users.github_access_token`
  - `DELETE /github/disconnect` → clears token, sets `github_sync_enabled=False` on all resumes
  - Register router in `backend/app/api/routes.py`

### 37E · Backend — GitHub Sync Service
- [x] Create `backend/app/services/github_sync_service.py`:
  ```python
  class GitHubSyncService:
      async def ensure_repo(self, token: str, username: str, repo_name: str) -> None: ...
      async def push_file(self, token, owner, repo, path, content, commit_message) -> dict: ...
      async def pull_file(self, token, owner, repo, path) -> str: ...
  ```

### 37F · Backend — Sync Endpoints
- [x] Added to `backend/app/api/github_routes.py`:
  - `POST /github/resumes/{resume_id}/enable` — enables sync, creates repo
  - `POST /github/resumes/{resume_id}/push` — manual push
  - `POST /github/resumes/{resume_id}/pull` — pull latest from GitHub
  - `POST /github/resumes/{resume_id}/disable` — disable sync
  - `GET /github/resumes/{resume_id}/status` — get resume GitHub status

### 37G · Auto-Sync Hook
- [x] Push is triggered manually via "Push" button in editor header; fire-and-forget auto-sync on checkpoint save can be added as follow-up

### 37H · Frontend — Settings Integration
- [x] In `frontend/src/app/settings/page.tsx`:
  - "GitHub Integration" section: connected username or "Connect GitHub" button
  - "Disconnect" with confirmation dialog
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - GitHub sync toggle in editor header (only visible if GitHub connected)
  - "Push to GitHub" manual button

### 37I · Tests
- [x] `backend/test/test_github_sync.py` — 10 tests:
  - Service: repo exists (no create), repo missing (creates), push new, push update, pull decode, get_user
  - Endpoints: connect without config → 503, status unauth → 401, enable without token → 400, disconnect → clears token

---

## Feature 38 — Compiler Settings per Resume · P2 · M

**Goal:** "Compile Settings" modal per resume for TeX Live version, main `.tex` file, and custom
latexmk flags. All stored in resume `metadata` JSONB. Extends Feature 9's basic compiler selection.

### 38A · Backend — Settings Endpoint Extension
- [x] Extend `PATCH /resumes/{resume_id}/settings` (from Feature 9) to accept additional fields:
  - `texlive_version: Optional[str]` — validate: must be `null` or 4-digit year `2022`–`2024`
  - `main_file: Optional[str]` — validate: matches `^[a-zA-Z0-9_-]+\.tex$`
  - `latexmk_flags: Optional[List[str]]` — whitelist approach:
    ```python
    ALLOWED_LATEXMK_FLAGS = [
        "--shell-escape", "--synctex=1", "--file-line-error",
        "--interaction=nonstopmode", "--halt-on-error",
    ]
    # Reject any flag not in whitelist to prevent command injection
    ```
  - `extra_packages: Optional[List[str]]` — each max 50 chars, alphanumeric + hyphens only

### 38B · Backend — Compile Task Extension
- [x] In `backend/app/workers/latex_worker.py`:
  - Read `metadata.main_file` → use as `.tex` filename in compile directory
  - Read `metadata.extra_packages` → prepend `\usepackage{pkg}` lines if absent from source
  - Read `metadata.latexmk_flags` → append whitelisted flags to compile command

### 38C · Frontend — Compile Settings Modal
- [x] Create `frontend/src/components/CompileSettingsModal.tsx`:
  - **Compiler** (pdflatex/xelatex/lualatex) — reuses CompilerSelector
  - **TeX Live Version** dropdown (2022 / 2023 / 2024 / Latest)
  - **Main .tex file** text input (default: `main.tex`)
  - **Extra packages** comma-separated input (e.g. `xcolor,multicol`)
  - **Custom flags** multi-select of whitelisted options
  - Save → `PATCH /resumes/{id}/settings` · "Reset to Defaults" button

### 38D · Integration
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - "⚙ Compile Settings" button in editor toolbar (gear icon)
  - Opens `CompileSettingsModal`

### 38E · Tests
- [x] `backend/test/test_compile_settings.py`:
  - `latexmk_flags: ["--shell-escape; rm -rf /"]` → 422 (injection rejected)
  - `main_file: "../../etc/passwd"` → 422
  - `texlive_version: "2023"` → stored correctly in metadata
  - `extra_packages: ["xcolor"]` → preamble injection verified

---

## Feature 39 — Project-Level Tags & Organization · P2 · S

**Goal:** Expose the existing `tags` array on `Resume`. Add workspace tag filtering, pin/unpin,
archive, and "My Templates" section. Pure UI + thin API over existing schema.

### 39A · Backend — Archive Field
- [x] In `backend/app/database/models.py`:
  - Added `archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)`
  - Migration `0014_add_resume_archive.py` created
- [x] In `GET /resumes` list: default filter `WHERE archived_at IS NULL`; `?archived=true` param supported

### 39B · Backend — Tag / Pin / Archive Endpoints
- [x] Added to `backend/app/api/resume_routes.py`:
  - `PATCH /resumes/{resume_id}/tags` — sets `tags: List[str]` (max 10, each ≤30 chars; Pydantic v2 `max_length=10` on List)
  - `PATCH /resumes/{resume_id}/pin` — sets `metadata.pinned = True`; `ResumeResponse.pinned` computed field
  - `PATCH /resumes/{resume_id}/unpin` — clears `metadata.pinned`
  - `PATCH /resumes/{resume_id}/archive` — sets `archived_at = utcnow()`
  - `PATCH /resumes/{resume_id}/unarchive` — clears `archived_at`

### 39C · Frontend — Tag Assignment UI
- [x] Tag chips displayed on workspace card with click-to-filter; "Tags" button opens modal (comma-separated)
- [x] "Pin"/"Unpin" button on card footer with amber "Pinned" badge when active
- [x] "Archive" button with confirmation dialog on card footer

### 39D · Frontend — Workspace Filtering
- [x] In `frontend/src/app/workspace/page.tsx`:
  - Right sidebar "Organize" panel with tag filter list
  - Pinned resumes sorted to top in grid (sort by `pinned` descending)
  - "View Archived" toggle in sidebar loads archived resumes inline below main grid

### 39E · Frontend — My Templates Section
- [x] "My Templates" section below main grid showing `is_template=True` resumes
- [x] "Remove from Templates" button on each template card (toggles `is_template=false`)

### 39F · Tests
- [x] `backend/test/test_resume_tags.py` — 8 tests passing:
  - PATCH tags → GET shows updated tags list
  - Tag with 31 chars → 422
  - More than 10 tags → 422
  - Archive → default GET list excludes it
  - GET with `?archived=true` → returns archived resume
  - Unarchive → appears in default list again
  - Pin → `pinned=True` in response
  - Unpin → `pinned=False` in response

---

## Feature 40 — Real-Time Collaboration (Multi-Cursor CRDT) · P2 · XL

**Goal:** Multiple users editing the same resume simultaneously via Yjs CRDT over WebSocket.
Each user sees others' cursors with name/color labels. Role-based access (owner/editor/viewer).

### 40A · Dependencies
- [x] `pnpm add yjs y-monaco y-websocket y-protocols`
- [x] Verify `websockets` available in Python env (for WS server-side if extending)

### 40B · Database Migration
- [x] Create `backend/alembic/versions/0013_add_collaboration.py`:
  ```sql
  CREATE TABLE resume_collaborators (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id UUID NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL DEFAULT 'editor',   -- 'editor' | 'commenter' | 'viewer'
    invited_by UUID REFERENCES users(id),
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(resume_id, user_id)
  );
  CREATE INDEX idx_resume_collaborators_resume ON resume_collaborators(resume_id);
  ```

### 40C · Backend — Collaborator Management Endpoints
- [x] Add to `backend/app/api/resume_routes.py`:
  - `POST /resumes/{resume_id}/collaborators` — invite by email (creates row; sends invite email)
  - `GET /resumes/{resume_id}/collaborators` — list collaborators with roles
  - `PATCH /resumes/{resume_id}/collaborators/{user_id}` — change role (owner only)
  - `DELETE /resumes/{resume_id}/collaborators/{user_id}` — remove collaborator

### 40D · Backend — Collab WebSocket Channel
- [x] Extend `backend/app/api/ws_routes.py` with new path `/ws/collab/{resume_id}`:
  - Auth: validate session token from query param `?token=...`
  - Permission: owner or `resume_collaborators` row with `editor` role
  - Protocol: Y.js relay server — forward binary messages; persist updates in Redis (24h TTL)
  - `backend/app/services/collab_manager.py`: lib0 encode/decode, CollabRoom, CollabManager, handle_collab_message
  - On new client connect: send all stored updates as SYNC_STEP2 catch-up messages

### 40E · Frontend — Y.js Integration in LaTeXEditor
- [x] In `frontend/src/components/LaTeXEditor.tsx`:
  - Add props: `collabEnabled?`, `collabResumeId?`, `collabUser?`, `onPresenceChange?`
  - Dynamic imports of yjs, y-websocket, y-monaco inside async `handleEditorDidMount`
  - MonacoBinding wires Y.js Doc to Monaco model; uncontrolled (`defaultValue`) when collab active
  - Awareness broadcasts cursor presence to parent via `onPresenceChange`
  - Cleanup useEffect destroys binding/provider/ydoc on unmount

### 40F · Frontend — Collaborator Panel
- [x] Create `frontend/src/components/CollaboratorPanel.tsx`:
  - Live presence: colored avatar dots (from Y.js awareness via `presenceUsers` prop)
  - Collaborator list with role dropdown and remove button (owner only)
  - Invite by email form with role selector (owner only)
  - Integrated into `frontend/src/app/workspace/[resumeId]/edit/page.tsx`

### 40G · Tests
- [x] `backend/test/test_collaboration.py` — 33 tests passing:
  - lib0 varuint/varbuffer encoding roundtrips
  - SYNC_STEP2 message structure
  - CollabRoom add/remove/broadcast/dead-client-removal
  - CollabManager create/cleanup
  - handle_collab_message: SYNC_STEP1 catchup, MSG_UPDATE persist+relay, awareness relay, malformed graceful
  - REST endpoints: invite 201, list 404, role validation 422

---

## Feature 41 — Track Changes (Accept/Reject) · P2 · XL

**Goal:** Requires Feature 40. Collaborator edits appear highlighted (green insertion, red
deletion). Owner accepts/rejects per change or in batch.

### 41A · Prerequisite
- [x] Feature 40 fully implemented

### 41B · Frontend — Change Tracking via Yjs
- [x] Created `frontend/src/lib/yjs-track-changes.ts`:
  - `TrackedChange` interface with id, clientId, userId, userName, userColor, type, text, offset, length, range, timestamp, resolved
  - `observeChanges(yText, provider, onUpdate)` — attaches observer; only tracks remote changes (`transaction.origin === provider`, which y-websocket correctly sets)
  - prevText snapshot captured at start of each observer call for correct deletion text recovery
  - Deletion attribution: Y.js CRDT cannot track the deleter; shown as "A collaborator"
  - `rejectChange` uses narrow + global document search fallback for drift resilience

### 41C · Monaco Decorations
- [x] In `frontend/src/components/LaTeXEditor.tsx`:
  - Props `trackedChanges`, `onTrackedChangesUpdate` added
  - Insertions: `.tracked-insertion` class with green highlight + underline
  - Deletions: `.tracked-deletion-glyph` red dot in gutter
  - Hover tooltips with username + action hint

### 41D · Changes Panel
- [x] Created `frontend/src/components/ChangesPanel.tsx`:
  - Changes grouped by userId with user avatar, +/− badges, text preview, line number, relative time
  - Per-change Accept/Reject buttons (hover-reveal)
  - "Accept all" (emerald) / "Reject all" (rose) batch buttons
  - Empty state with GitMerge icon

### 41E · Integration
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - `RightTab` extended with `'changes'`
  - `trackedChanges` state + emerald count badge on "Changes" tab
  - `<ChangesPanel>` wired with accept/reject callbacks to `editorRef`
  - `LaTeXEditor` receives `trackedChanges` and `onTrackedChangesUpdate` props
  - `LaTeXEditorRef` extended: `acceptTrackedChange`, `rejectTrackedChange`, `acceptAllTrackedChanges`, `rejectAllTrackedChanges`

### 41F · Tests
- [x] `frontend/src/__tests__/yjs-track-changes.test.ts` — 29 tests passing:
  - Module exports, handle interface
  - Origin filtering: local/null origin ignored, provider origin tracked
  - Insertion tracking: type, text, offset, length, id prefix, timestamp
  - Deletion tracking: type, text, offset, length, id prefix; attribution = "A collaborator"
  - acceptChange, rejectChange (insertion/deletion), rejectChange idempotency
  - acceptAll, rejectAll (insertions + deletions)
  - User attribution via awareness states
  - computeRange: line 1 col 1 at start, line 2 for second-line insert
  - Global fallback search in rejectChange for drifted offsets
  - y-websocket origin correctness: MonacoBinding/null ignored; provider tracked
  - cleanup unobserves yText

---

## Feature 42 — Zotero / Mendeley Reference Import · P2 · L

**Goal:** Import entire reference library from Zotero or Mendeley as BibTeX via OAuth.
Extends the References panel from Feature 14. Stores .bib in resume metadata.

### 42A · Config
- [x] Add to `backend/app/core/config.py`:
  ```python
  ZOTERO_CLIENT_KEY: Optional[str] = None
  ZOTERO_CLIENT_SECRET: Optional[str] = None
  MENDELEY_CLIENT_ID: Optional[str] = None
  MENDELEY_CLIENT_SECRET: Optional[str] = None
  ```

### 42B · Database Migration
- [x] No new tables — store tokens in `users.metadata` JSONB:
  ```json
  { "zotero_token": "...", "zotero_user_key": "...", "mendeley_token": "..." }
  ```

### 42C · Backend — Zotero OAuth + Import
- [x] Create `backend/app/api/zotero_routes.py`:
  - `GET /zotero/connect` → redirect to Zotero OAuth 1.0a authorization
  - `GET /zotero/callback?oauth_token=&oauth_verifier=` → exchange for access token, store in user metadata
  - `GET /zotero/disconnect`
  - `POST /zotero/import` → body: `{ resume_id, collection_id? }`
    - `GET https://api.zotero.org/users/{userKey}/items?format=bibtex`
    - Filter by collection if provided
    - Store result in `resume.metadata.bibtex`

### 42D · Backend — Mendeley OAuth + Import
- [x] Create `backend/app/api/mendeley_routes.py`:
  - `GET /mendeley/connect` → redirect to Mendeley OAuth 2.0
  - `GET /mendeley/callback?code=` → exchange for access token
  - `POST /mendeley/import` → `GET /documents?format=bibtex` from Mendeley API

### 42E · Frontend — Import Flow
- [x] In `ReferencesPanel` (from Feature 14):
  - "Import from Zotero" button → OAuth popup window
  - "Import from Mendeley" button → same
  - After import: BibTeX entries listed in panel, each with "Insert \cite{key}" action
- [x] In `frontend/src/app/settings/page.tsx`:
  - Zotero / Mendeley connection status sections

### 42F · Tests
- [x] `backend/test/test_zotero_import.py`:
  - Import (mocked httpx returning BibTeX) → stored in resume metadata
  - Import without token → 401
  - Zotero API error → returns error message, not 500

---

## Feature 43 — Resume View Analytics · P2 · M

**Goal:** Track views on shared resume links from Feature 10. Record country (no raw IP),
user-agent, referrer. Debounce repeat views. Show in share modal: total, sparkline, breakdown.

### 43A · Database Migration
- [x] Create `backend/alembic/versions/0014_add_resume_views.py`:
  ```sql
  CREATE TABLE resume_views (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id UUID NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    share_token TEXT NOT NULL,
    viewed_at TIMESTAMPTZ DEFAULT NOW(),
    country_code CHAR(2),
    user_agent TEXT,
    referrer TEXT,
    session_id TEXT    -- hash(ip+ua) for debounce, NOT stored raw
  );
  CREATE INDEX idx_resume_views_resume_id ON resume_views(resume_id);
  CREATE INDEX idx_resume_views_viewed_at ON resume_views(viewed_at);
  ```

### 43B · Backend — View Recording
- [x] In `GET /share/{share_token}` endpoint:
  - `session_id = hashlib.sha256((ip + user_agent).encode()).hexdigest()[:16]`
  - Check Redis: SET NX with TTL=300 (5 min debounce) — if key exists skip insert
  - If not: insert `resume_views` row via `_record_resume_view` helper
  - Country detection: use `ip-api.com` free tier (non-commercial) or skip if not configured
  - Add `GEOIP_PROVIDER_URL: Optional[str] = None` to `config.py`

### 43C · Backend — Analytics Endpoint
- [x] Add `GET /resumes/{resume_id}/analytics` to `backend/app/api/resume_routes.py`:
  ```python
  class ResumeAnalytics(BaseModel):
      total_views: int
      views_last_7_days: int
      views_last_30_days: int
      views_by_day: List[dict]          # [{ date: "2024-01-15", count: 3 }]
      views_by_country: List[dict]      # [{ country_code: "US", count: 12 }]
      views_by_referrer: List[dict]     # [{ referrer: "linkedin.com", count: 4 }]
      first_viewed_at: Optional[str]
      last_viewed_at: Optional[str]
  ```
  - Auth required; verify ownership

### 43D · Frontend — Analytics in Share Modal
- [x] In `frontend/src/components/ShareResumeModal.tsx`:
  - Added "Analytics" tab (visible only when share link is active)
  - Total view count + last 7d + last 30d badges
  - 30-day sparkline (`<Sparkline>` component with recharts)
  - Top countries: flag emoji + name + count
  - Top referrers: domain + count

### 43E · Tests
- [x] `backend/test/test_resume_analytics.py`:
  - Accessing public share page records a view
  - Same session within 5 min → counted only once (Redis debounce)
  - `GET /resumes/{id}/analytics` returns correct `total_views`
  - Non-owner → 403 or 404

---

## Feature 44 — Multilingual Resume Translation · P2 · M

**Goal:** Translate resume prose while preserving all LaTeX commands. LLM call. Result saved
as a new variant with `[LanguageCode]` suffix in title.

### 44A · Backend — Translation Endpoint
- [x] Add `POST /ai/translate` to `backend/app/api/ai_routes.py`:
  ```python
  class TranslateRequest(BaseModel):
      resume_id: str
      target_language: str = Field(..., max_length=50)    # "French"
      language_code: str = Field(..., max_length=10)      # "fr"

  class TranslateResponse(BaseModel):
      success: bool
      variant_resume_id: str   # ID of newly created fork
      cached: bool
  ```
  - System prompt:
    ```
    Translate this LaTeX resume to {target_language}.
    STRICT RULES:
    1. Translate ONLY prose text content.
    2. Never modify LaTeX commands, environments, or special characters.
    3. Never modify: \section{}, \textbf{}, \begin{...}, \end{...}, dates, numbers, proper nouns, URLs.
    4. Translate: bullet text after \item, section header labels, prose descriptions.
    5. Return ONLY the translated LaTeX source — no explanation or markdown.
    ```
  - After translation: fork resume via existing variant creation logic, title = `"{original} — {LanguageCode}"`
  - Cache by `hash(latex_content[:1000] + target_language)`, TTL=3600

### 44B · Frontend — Translation UI
- [x] In workspace resume card actions dropdown:
  - "🌐 Translate..." option → opens modal
  - Language selector: dropdown with 20+ common languages (French, German, Spanish, Japanese, etc.)
  - "Translate" button → shows progress
  - On success: toast "Translated resume created" with link to new variant

### 44C · Tests
- [x] `backend/test/test_translation.py`:
  - Translation (mocked LLM) preserves `\section{}` blocks intact
  - Creates variant resume with `_fr` (or equivalent) in title
  - Empty `target_language` → 422

---

## Feature 45 — Salary Estimator · P2 · M

**Goal:** Resume + target role + location → AI salary range estimate with percentile and
contributing skills. Free for all users (lightweight LLM call).

### 45A · Backend — Salary Estimate Endpoint
- [x] Add `POST /ai/salary-estimate` to `backend/app/api/ai_routes.py`:
  ```python
  class SalaryEstimateRequest(BaseModel):
      resume_latex: str = Field(..., max_length=50_000)
      target_role: str = Field(..., max_length=200)
      location: str = Field(..., max_length=200)

  class SalaryEstimateResponse(BaseModel):
      currency: str       # "USD" inferred from location
      low: int            # 120000
      median: int         # 145000
      high: int           # 180000
      percentile: int     # 0–100
      key_skills: List[str]
      disclaimer: str
      cached: bool
  ```
  - gpt-4o-mini; auto-sorts low ≤ median ≤ high; clamps percentile 0–100
  - Cache by `sha256(full_resume_latex)|role|location`, TTL=86400

### 45B · Frontend — Salary Estimator Panel
- [x] Create `frontend/src/components/SalaryEstimatorPanel.tsx`:
  - Inputs: target role (text input), location (text input)
  - "Estimate Salary" button
  - Results:
    - Horizontal range bar: low | median | high with candidate marker at median
    - Percentile label: "Estimated at Nth percentile for [role] in [location]"
    - Key skills contributing to estimate (chip tags)
    - Disclaimer in small text
- [x] "💰 Salary" toolbar button in workspace edit page

### 45C · Tests
- [x] `backend/test/test_salary_estimate.py` — 26 tests:
  - Response contains all required fields with correct types
  - `low <= median <= high` invariant holds
  - Unsorted LLM values auto-corrected
  - Cache: second identical request returns `cached=True`
  - Percentile clamped to 0–100; LLM errors return graceful 200

---

## Feature 46 — Industry-Specific ATS Calibration · P2 · L

**Goal:** Detect industry from job description. Apply industry-specific keyword weights to ATS
scoring. Show "Calibrated for: Technology / SaaS" in results panel.

### 46A · Backend — Industry Profiles
- [x] Create `backend/app/services/industry_ats_profiles.py`:
  ```python
  INDUSTRY_PROFILES: Dict[str, dict] = {
      "tech_saas": {
          "label": "Technology / SaaS",
          "keywords": {
              "kubernetes": 1.5, "microservices": 1.4, "ci/cd": 1.3, "api": 1.2,
              "cloud": 1.2, "agile": 1.1, "python": 1.1, "docker": 1.1, ...
          },
          "section_weights": {"experience": 1.3, "skills": 1.2, "education": 0.8},
          "detect_keywords": ["saas", "api", "kubernetes", "microservice", "startup", "engineer"],
      },
      "finance_banking": {
          "label": "Finance / Banking",
          "detect_keywords": ["bloomberg", "cfa", "equity", "trading", "portfolio", "risk management"],
          ...
      },
      "healthcare": { "detect_keywords": ["hipaa", "ehr", "clinical", "patient", "fda"], ... },
      "consulting": { "detect_keywords": ["mckinsey", "deloitte", "engagement", "client", "framework"], ... },
      "generic": { "label": "General", "keywords": {}, "section_weights": {} },
  }

  def detect_industry(job_description: str) -> str:
      """Keyword frequency matching across profiles. Returns profile key."""
      jd_lower = job_description.lower()
      scores = {
          name: sum(1 for kw in profile["detect_keywords"] if kw in jd_lower)
          for name, profile in INDUSTRY_PROFILES.items() if name != "generic"
      }
      best = max(scores, key=scores.get, default="generic")
      return best if scores.get(best, 0) >= 2 else "generic"
  ```

### 46B · Backend — ATS Scoring Integration
- [x] In `backend/app/services/ats_scoring_service.py`:
  - Accept `industry_profile: str = "generic"` parameter
  - Apply `profile["keywords"][kw]` weight multiplier per keyword when computing keyword score
  - Apply `profile["section_weights"]` to section-level scoring
- [x] In ATS scoring endpoint: call `detect_industry(job_description)` before scoring, include `industry_label` in response

### 46C · Frontend — Display
- [x] In ATS results panel:
  - Show "Calibrated for: [industry_label]" pill badge in panel header
  - Optional industry override dropdown (user can correct auto-detection)

### 46D · Tests
- [x] `backend/test/test_industry_ats.py`:
  - JD with "Kubernetes, microservices, CI/CD" → detects `tech_saas`
  - JD with "Bloomberg, CFA, equity" → detects `finance_banking`
  - Tech profile weights tech keywords higher than generic profile
  - `industry_label` present in ATS response

---

## Feature 47 — Anonymous Resume Mode · P2 · S

**Goal:** Optional anonymization of PII (name/email/phone/LinkedIn/GitHub) in shared PDF.
Original LaTeX never modified. Applied at compile time for share view only.

### 47A · Backend — PII Redactor
- [x] Create `backend/app/services/latex_pii_redactor.py`:
  ```python
  import re

  REDACT_PATTERNS = [
      (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', '████@████'),
      (r'linkedin\.com/in/[A-Za-z0-9_-]+', 'linkedin.com/in/████'),
      (r'github\.com/[A-Za-z0-9_-]+', 'github.com/████'),
      # Conservative phone: 7+ digit groups with common separators
      (r'\+?[\d][\d\s\-().]{6,14}[\d]', '███-████-████'),
  ]

  WATERMARK_PREAMBLE = r"""
  \usepackage{draftwatermark}
  \SetWatermarkText{ANONYMIZED}
  \SetWatermarkScale{0.8}
  \SetWatermarkColor[gray]{0.93}
  """

  def redact(latex_content: str) -> str:
      for pattern, replacement in REDACT_PATTERNS:
          latex_content = re.sub(pattern, replacement, latex_content)
      # Inject watermark after \begin{document}
      latex_content = latex_content.replace(
          r'\begin{document}',
          WATERMARK_PREAMBLE + r'\begin{document}'
      )
      return latex_content
  ```

### 47B · Backend — Anonymous Share Option
- [x] In `POST /resumes/{resume_id}/share`: add `anonymous: bool = False` to request body
  - Store `metadata.share_anonymous = anonymous`
- [x] In `GET /share/{share_token}`: if `share_anonymous=True` → apply `redact()` to LaTeX before
  compiling; serve temp PDF (not cached as canonical PDF)

### 47C · Frontend — Toggle in Share Modal
- [x] In `frontend/src/components/ShareResumeModal.tsx`:
  - "Anonymous Mode" toggle with amber indicator
  - Info: "Hides your name, email, phone, and social profiles from the shared view"
  - When toggled: re-generates share link with updated setting

### 47D · Tests
- [x] `backend/test/test_anonymous_share.py`:
  - `redact()` replaces email pattern with `████@████`
  - `redact()` preserves LaTeX structure (no broken commands)
  - Original resume LaTeX unchanged after anonymous share
  - Anonymous share compiles redacted copy, not original

---

## Feature 48 — Resume Freshness Tracker · P2 · S

**Goal:** "Updated N days ago" on workspace cards with green/amber/red coding.
Dashboard staleness warning. Weekly digest includes stale resume alerts.

### 48A · Backend — Freshness Fields
- [x] In `backend/app/api/resume_routes.py`, `ResumeResponse`:
  - Added computed fields (no DB change — uses existing `updated_at`):
    ```python
    days_since_updated: int = 0
    freshness_status: str = "fresh"  # "fresh" | "stale" | "very_stale"
    ```
  - `fresh` if `days < 30`; `stale` if `30 <= days < 90`; `very_stale` if `days >= 90`

### 48B · Frontend — Workspace Card
- [x] In workspace resume card component:
  - "Updated Nd ago" text with color coding
  - `text-rose-400` (very_stale) | `text-amber-400` (stale) | `text-zinc-400` (fresh)

### 48C · Frontend — Dashboard Warning
- [x] In `frontend/src/app/workspace/page.tsx`:
  - Dismissible banner: "X resumes haven't been updated in 90+ days"
  - Click → filters grid to show only `very_stale` resumes

### 48D · Email Integration
- [x] In `backend/app/workers/email_worker.py` weekly digest task (from Feature 19):
  - Include section: "Resumes that need your attention" listing stale resume titles with
    "Update Now" links

### 48E · Tests
- [x] `backend/test/test_freshness.py`:
  - `updated_at = today` → `freshness_status = "fresh"`
  - `updated_at = 45 days ago` → `freshness_status = "stale"`
  - `updated_at = 100 days ago` → `freshness_status = "very_stale"`

---

## Feature 49 — Bulk / Batch Resume Export (ZIP) · P2 · S

**Goal:** "Export All" button downloads all resumes as a ZIP. Format options: PDFs, TEX files,
or DOCX files.

### 49A · Backend — Bulk Export Endpoint
- [x] Add `GET /resumes/export/bulk` to `backend/app/api/resume_routes.py`:
  - Query params: `format=pdf|tex|docx`
  - Auth required; builds in-memory ZIP with StreamingResponse
  - `Content-Disposition: attachment; filename="latexy-resumes-{date}.zip"`

### 49B · Frontend — Export UI
- [x] In workspace page header actions:
  - "⬇ Export All" button → dropdown: "PDF Files (ZIP)" · "LaTeX Source (ZIP)" · "Word Docs (ZIP)"
  - Click → `apiClient.bulkExport(format)` triggers download

### 49C · Tests
- [x] `backend/test/test_bulk_export.py`:
  - `format=tex` → ZIP contains one `.tex` file per resume with correct filenames
  - `format=pdf` when no PDFs compiled → returns empty ZIP (not 500)
  - Unauthenticated → 401

---

## Feature 50 — ATS Simulator · P2 · L

**Goal:** Knowledge base of major ATS parsing behaviors. Select target ATS → view plain-text
representation as that system would parse your resume. Highlights problem areas.

### 50A · Backend — ATS Simulator Service
- [x] Create `backend/app/services/ats_simulator_service.py`:
  ```python
  ATS_PROFILES = {
      "greenhouse":      { "label": "Greenhouse",      "tier": "good",    "issues": ["multi_column"] },
      "lever":           { "label": "Lever",           "tier": "good",    "issues": [] },
      "ashby":           { "label": "Ashby",           "tier": "good",    "issues": [] },
      "workday":         { "label": "Workday",         "tier": "medium",  "issues": ["custom_sections", "tables"] },
      "smartrecruiters": { "label": "SmartRecruiters", "tier": "medium",  "issues": ["decorative_elements"] },
      "taleo":           { "label": "Taleo (Oracle)",  "tier": "poor",    "issues": ["tables", "multi_column", "pdf_formatting"] },
      "icims":           { "label": "iCIMS",           "tier": "medium",  "issues": ["complex_layouts"] },
  }

  class AtsSimulatorService:
      def simulate(self, latex_content: str, ats_name: str) -> AtsSimulationResult:
          # 1. Extract plain text via existing extract_prose()
          # 2. For poor-tier parsers: apply distortions (garble tables, merge columns, strip section headers)
          # 3. Detect issues: scan LaTeX for multi-column envs, tabular, complex fonts
          # 4. Compute compatibility score based on detected issues and ATS tier
          # 5. Return plain_text_view, issues list, score, recommendations
  ```

### 50B · Backend — Simulator Endpoint
- [x] Add `POST /ats/simulate` to `backend/app/api/ats_routes.py`:
  ```python
  class AtsSimulateRequest(BaseModel):
      latex_content: str = Field(..., max_length=200_000)
      ats_name: str   # must be in ATS_PROFILES.keys()

  class AtsSimulateResponse(BaseModel):
      ats_label: str
      plain_text_view: str
      issues: List[dict]      # [{ type, severity, description, line_range }]
      score: int              # 0–100 compatibility
      recommendations: List[str]
  ```
  - Unknown `ats_name` → 422
  - Cache by `hash(latex_content + ats_name)`, TTL=1800

### 50C · Frontend — ATS Simulator Panel
- [x] Create `frontend/src/components/ats/AtsSimulatorPanel.tsx`:
  - ATS selector: card grid with system name + tier badge (Good/Medium/Poor)
  - "Simulate" button → shows plain-text view (read-only)
  - Issues list below with severity icons
  - Recommendations accordion
- [x] Add as "ATS Simulator" tab in the optimize page

### 50D · Tests
- [x] `backend/test/test_ats_simulator.py`:
  - Taleo simulation of multi-column LaTeX → `issues` contains `multi_column` entry
  - Greenhouse simulation of clean single-column → `score >= 85`
  - Unknown ATS name → 422

---

## Feature 51 — Resume Heatmap · P2 · M

**Goal:** Toggle in PDF viewer shows predicted recruiter attention overlay. Rule-based V1:
weights based on published recruiter behavior research. Red=high attention, blue=low.

### 51A · Frontend — Heatmap Computation
- [x] Create `frontend/src/lib/heatmap-generator.ts`:
  ```typescript
  export interface HeatmapRegion {
    yPercent: number      // top edge of region as % of page height
    heightPercent: number // height as % of page height
    intensity: number     // 0.0 (cold/blue) → 1.0 (hot/red)
    label: string
  }

  export function computePageHeatmap(pageIndex: number): HeatmapRegion[] {
    if (pageIndex === 0) return [
      { yPercent: 0,   heightPercent: 20, intensity: 0.95, label: "Name & Contact" },
      { yPercent: 20,  heightPercent: 5,  intensity: 0.75, label: "Section headers" },
      { yPercent: 25,  heightPercent: 50, intensity: 0.60, label: "First job entries" },
      { yPercent: 75,  heightPercent: 25, intensity: 0.30, label: "Bottom of page" },
    ]
    // Page 2+: uniformly lower intensity
    return [{ yPercent: 0, heightPercent: 100, intensity: 0.15 * (1 / (pageIndex + 1)), label: `Page ${pageIndex + 1}` }]
  }
  ```

### 51B · PDF Preview Overlay
- [x] In PDF preview component (wherever PDF is rendered):
  - Add `showHeatmap: boolean` prop
  - When enabled: render `<canvas>` absolutely over each PDF page
  - Draw each region with `ctx.fillStyle = heatmapColor(intensity)`:
    - 1.0 → `rgba(239,68,68,0.35)` (red)
    - 0.5 → `rgba(251,191,36,0.25)` (amber)
    - 0.0 → `rgba(59,130,246,0.15)` (blue)

### 51C · Toggle Button
- [x] In PDF preview toolbar:
  - "🔥 Heatmap" toggle button
  - Tooltip: "Shows predicted areas recruiters focus on (based on eye-tracking research)"

### 51D · Tests
- [x] Frontend unit test: `computePageHeatmap(0)` returns region at `yPercent=0` with `intensity >= 0.9`

---

## Feature 52 — Resume Score History Chart · P2 · S

**Goal:** Sparkline in ATS panel showing score over time. "↑ 12 points since first optimization"
delta indicator. Dashboard average score widget.

### 52A · Backend — Score History
- [x] `ats_score` column in optimization table; `GET /resumes/{resume_id}/score-history`
  returns sorted ASC list of `{ timestamp, ats_score, label }` entries

### 52B · Frontend — Score History Chart
- [x] Create `frontend/src/components/ScoreHistoryChart.tsx`:
  - recharts `<LineChart>`, X=date, Y=0–100
  - Dot on latest point, delta label: `↑ 12 pts` / `↓ 3 pts`
- [x] Added to `DeepAnalysisPanel.tsx` as "Score History" collapsible section

### 52C · Dashboard Widget
- [x] In `frontend/src/app/workspace/page.tsx`:
  - Stats line: "Avg ATS: 74 · Best: 92" from `atsStats.avg_ats_score`

### 52D · Tests
- [x] `backend/test/test_score_history.py`:
  - GET score-history for resume with optimization runs → entries sorted ASC
  - GET score-history with no optimizations → empty list `[]`

---

## Feature 53 — AI Section Reordering · P2 · M

**Goal:** AI recommends optimal section order for resume + job description. One-click reorder
restructures `\section{}` blocks. Diff preview before applying.

### 53A · Backend — Section Parser
- [ ] Create `backend/app/services/latex_section_parser.py`:
  ```python
  @dataclass
  class LatexSection:
      name: str          # "Experience", "Skills", etc.
      start_line: int
      end_line: int
      content: str       # full content including \section{} line

  def extract_sections(latex_content: str) -> tuple[str, List[LatexSection]]:
      # Returns (preamble_and_begin_document, sections_list)
      # Section ends at next \section{} or \end{document}

  def reorder_sections(latex_content: str, new_order: List[str]) -> str:
      # Extracts sections → reorders by new_order → reconstructs with original preamble
      # Sections not in new_order appended at end in original order
  ```

### 53B · Backend — Section Reorder Endpoint
- [ ] Add `POST /ai/reorder-sections` to `backend/app/api/ai_routes.py`:
  ```python
  class ReorderSectionsRequest(BaseModel):
      resume_latex: str = Field(..., max_length=200_000)
      job_description: Optional[str] = Field(None, max_length=10_000)
      career_stage: Optional[str] = None   # "entry_level"|"mid"|"senior"|"executive"

  class ReorderSectionsResponse(BaseModel):
      current_order: List[str]
      suggested_order: List[str]
      rationale: str
      reordered_latex: str
      cached: bool
  ```
  - Parse sections → LLM returns suggested order + rationale
  - Apply `reorder_sections()` to produce `reordered_latex`

### 53C · Frontend — Section Reorder Panel
- [ ] Create `frontend/src/components/SectionReorderPanel.tsx`:
  - Career stage dropdown + optional JD textarea
  - "Suggest Order" button → API call
  - Drag-and-drop list (using `@dnd-kit/sortable` from Feature 15) showing current vs AI suggestion
  - Diff preview: split view showing current vs reordered first 10 lines
  - "Apply Reordering" → `editorRef.current?.setValue(reordered_latex)`

### 53D · Tests
- [ ] `backend/test/test_section_reorder.py`:
  - `extract_sections()` correctly identifies 4 sections in test resume
  - `reorder_sections()` preserves all content, only changes order
  - Endpoint `reordered_latex` has sections in `suggested_order` sequence

---

## Feature 54 — Industry Keyword Density Map · P2 · M

**Goal:** Visual tag cloud: green = present in resume, amber = partial match, red = missing.
Click missing keyword shows suggested insertion location.

### 54A · Backend — Keyword Density Endpoint
- [x] Add `POST /ats/keyword-density` to `backend/app/api/ats_routes.py`:
  ```python
  class KeywordDensityRequest(BaseModel):
      resume_latex: str = Field(..., max_length=200_000)
      job_description: str = Field(..., max_length=20_000)

  class KeywordEntry(BaseModel):
      keyword: str
      status: str              # "present" | "partial" | "missing"
      count: int               # occurrences in resume
      required: bool           # required vs preferred in JD
      suggested_location: Optional[str]   # "Skills section" | "Experience section"

  class KeywordDensityResponse(BaseModel):
      keywords: List[KeywordEntry]
      coverage_score: int     # 0–100
  ```
  - Reuse `job_description_analysis` keyword extraction (already implemented)
  - "partial" = stemmed match (e.g. "manage" keyword found when "management" in resume)
  - `suggested_location()`: if keyword is tech skill → "Skills section"; else "Experience section"

### 54B · Frontend — Keyword Density Map
- [x] Create `frontend/src/components/KeywordDensityMap.tsx`:
  - Tag cloud: each keyword as a chip
    - `bg-emerald-500/20 text-emerald-300` + ✓ (present)
    - `bg-amber-500/20 text-amber-300` + ~ (partial)
    - `bg-rose-500/20 text-rose-300` + ✗ (missing)
  - Click missing chip → tooltip "Suggested location: Skills section"
  - Coverage score progress bar at top
- [x] Added as "Keywords" tab alongside ATS Simulator in optimize page

### 54C · Tests
- [x] `backend/test/test_keyword_density.py`:
  - "Python" in JD and resume → `status="present"`
  - "manage" in JD, "management" in resume → `status="partial"`
  - "Kubernetes" in JD, absent from resume → `status="missing"`

---

## Feature 55 — Resume Age Analysis · P2 · S

**Goal:** Parse dates from LaTeX, flag experience entries older than 10 years with amber indicator.
Recommend condensing or removing. Exception for prestigious institutions.

### 55A · Backend — Age Analysis Endpoint
- [x] Add `POST /ai/age-analysis` to `backend/app/api/ai_routes.py`:
  - Pure regex + rules; no LLM needed
  - `is_prestigious` checked against 50+ universities + FAANG + McKinsey etc.
  - `is_old = years_ago > 10 and not is_prestigious`

### 55B · Frontend — Age Analysis Panel
- [x] Create `frontend/src/components/AgeAnalysisPanel.tsx`:
  - Timeline view newest → oldest; amber highlight for old non-prestigious entries
  - "Condense" / "Keep" / dismiss per entry; jump to line in editor

### 55C · Tests
- [x] `backend/test/test_age_analysis.py`:
  - Entry from 2010 → `is_old=True`
  - Entry from last year → `is_old=False`
  - "Harvard University, 2008–2012" → `is_prestigious=True`, `is_old=False`

---

## Feature 56 — AI Custom Optimization Persona · P2 · M

**Goal:** Persona presets supplement the optimization level selector. Each persona modifies
the LLM system prompt for the optimization run.

### 56A · Backend — Persona Profiles
- [ ] Create `backend/app/services/optimization_personas.py`:
  ```python
  PERSONAS: Dict[str, dict] = {
      "startup": {
          "label": "Startup Mode",
          "icon": "🚀",
          "description": "Impact-focused, ownership language, punchy and concise",
          "prompt_addon": "Focus on: autonomous ownership, 0→1 building, scaling, direct impact. "
                          "Prefer verbs: Built, Scaled, Launched, Drove, Owned. Tone: energetic, concise.",
      },
      "enterprise": {
          "label": "Enterprise Mode",
          "icon": "🏢",
          "description": "Formal, process-driven, large-scale organizational impact",
          "prompt_addon": "Focus on: cross-functional leadership, process improvements, governance, "
                          "enterprise-scale impact (thousands of users, millions in revenue). Formal tone.",
      },
      "academic": {
          "label": "Academic Mode",
          "icon": "🎓",
          "description": "Publications-first, grant writing language, formal research contributions",
          "prompt_addon": "Prioritize: research contributions, publications, grants, teaching. "
                          "Formal academic tone. Lead with scholarly impact.",
      },
      "career_change": {
          "label": "Career Change Mode",
          "icon": "🔄",
          "description": "Emphasize transferable skills, reframe experience for new industry",
          "prompt_addon": "Focus on: transferable skills, industry-agnostic achievements, "
                          "reframe domain-specific experience as broadly applicable.",
      },
      "executive": {
          "label": "Executive Mode",
          "icon": "👔",
          "description": "C-suite language, board-level impact, strategic leadership",
          "prompt_addon": "Focus on: P&L ownership, board-level decisions, M&A, organizational design, "
                          "market strategy. C-suite vocabulary. Quantify at business unit scale.",
      },
  }
  ```

### 56B · Backend — Optimization Integration
- [ ] In `backend/app/workers/orchestrator.py` (or LLM optimization task):
  - Add `persona: Optional[str] = None` parameter
  - If set: validate `persona in PERSONAS.keys()`, then append `PERSONAS[persona]['prompt_addon']`
    to the system prompt
- [ ] In `JobSubmissionRequest` in `backend/app/api/job_routes.py`: add `persona: Optional[str] = None`

### 56C · Frontend — Persona Selector
- [ ] In `frontend/src/app/workspace/[resumeId]/optimize/page.tsx`:
  - "Optimization Style" section above optimization level selector
  - Card grid: 5 persona cards with icon + label + description
  - Selected persona: `ring-2 ring-violet-500/50` border
  - Pass `persona` in optimization job request body
- [ ] Persist selected persona in resume `metadata.last_persona` for next session

### 56D · Tests
- [ ] `backend/test/test_optimization_personas.py`:
  - Startup persona → system prompt contains "ownership" (mock LLM, verify prompt)
  - Invalid persona name → 422
  - `persona=null` → default behavior, no persona addon in prompt

---

## Feature 57 — Smart Date Formatting Standardizer · P2 · S

**Goal:** Detect all date occurrences in LaTeX. User picks consistent format. Preview diff
before applying. No LLM needed — pure regex transformation.

### 57A · Backend — Date Standardizer
- [x] Add `POST /ai/standardize-dates` to `backend/app/api/ai_routes.py`:
  - Pure regex; supports `MMM YYYY | MMMM YYYY | YYYY-MM | MM/YYYY`
  - Returns `occurrences` list + full `standardized_latex`

### 57B · Frontend — Date Standardizer Panel
- [x] Create `frontend/src/components/DateStandardizerPanel.tsx`:
  - Format radio buttons; "Detect Dates" preview; "Apply All" applies to editor
- [x] Accessible from editor toolbar "Dates" button

### 57C · Tests
- [x] `backend/test/test_date_standardizer.py`:
  - "January 2020" → "Jan 2020" with `MMM YYYY`
  - "2020-01" → "January 2020" with `MMMM YYYY`
  - No dates → `occurrences=[]`, content unchanged

---

## Feature 58 — Publication List Auto-Generator · P2 · M

**Goal:** Fetch publications from ORCID (free) or Google Scholar (via SerpAPI). Format as
LaTeX bibliography entries. Filter by year/type. Insert complete publications section.

### 58A · Backend — Publications Service
- [ ] Create `backend/app/services/publications_service.py`:
  ```python
  @dataclass
  class Publication:
      title: str
      authors: List[str]
      venue: str           # journal name or conference
      year: int
      doi: Optional[str]
      url: Optional[str]
      pub_type: str        # "journal" | "conference" | "preprint" | "book_chapter"

  class PublicationsService:
      async def fetch_from_orcid(self, orcid_id: str) -> List[Publication]:
          # GET https://pub.orcid.org/v3.0/{orcid_id}/works
          # Accept: application/json
          # Parse works summary list

      def format_as_latex(self, pubs: List[Publication], sort_by: str = "year") -> str:
          # Returns complete \section{Publications}\begin{enumerate}...\end{enumerate}
          # Each entry: \item [Authors]. ``[Title].'' \textit{[Venue]}, [Year].
          #   \href{https://doi.org/[DOI]}{[DOI]}
  ```

### 58B · Backend — Publications Endpoint
- [ ] Add `POST /ai/generate-publications` to `backend/app/api/ai_routes.py`:
  ```python
  class PublicationsRequest(BaseModel):
      source: str = "orcid"   # "orcid" only for MVP (Scholar requires paid SerpAPI)
      identifier: str          # ORCID ID (format: 0000-0000-0000-0000)
      year_from: Optional[int] = None
      year_to: Optional[int] = None
      pub_types: Optional[List[str]] = None   # ["journal", "conference"]

  class PublicationsResponse(BaseModel):
      publications: List[dict]
      latex_section: str
      cached: bool
  ```
  - Validate ORCID format: `^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$`
  - Cache by `hash(identifier + str(filters))`, TTL=3600

### 58C · Frontend — Publications Panel
- [ ] Create `frontend/src/components/PublicationsPanel.tsx`:
  - Source: ORCID ID input field
  - Filters: year range sliders, pub type checkboxes
  - "Fetch" button → shows loaded publications as checkable list
  - "Insert Publications Section" → inserts `latex_section` at cursor

### 58D · Tests
- [ ] `backend/test/test_publications.py`:
  - Valid ORCID format passes validation
  - Invalid ORCID format → 422
  - ORCID fetch (mocked httpx) → returns publication list with correct fields
  - `format_as_latex()` produces output with `\begin{enumerate}`

---

## Feature 59 — Resume Confidence Score · P2 · M

**Goal:** Holistic 0–100 quality score independent of any job description. Five dimensions:
writing quality, completeness, quantification, formatting, section order. Radar chart display.

### 59A · Backend — Confidence Score Service
- [x] Create `backend/app/services/confidence_score_service.py`:
  ```python
  @dataclass
  class ConfidenceScore:
      writing_quality: int    # 30% weight: penalizes weak verbs, buzzwords, passive voice
      completeness: int       # 20% weight: expected sections present
      quantification: int     # 20% weight: % of \item lines containing numbers
      formatting: int         # 15% weight: date consistency, capitalization, spacing
      section_order: int      # 15% weight: appropriate order for inferred career stage

      @property
      def overall(self) -> int:
          return round(
              self.writing_quality * 0.30 + self.completeness * 0.20 +
              self.quantification * 0.20 + self.formatting * 0.15 +
              self.section_order * 0.15
          )

  class ConfidenceScoreService:
      def score(self, latex_content: str) -> ConfidenceScore:
          prose = extract_prose(latex_content)
          sections = extract_sections(latex_content)
          return ConfidenceScore(
              writing_quality=self._score_writing(prose),      # reuse proofreader patterns
              completeness=self._score_completeness(sections),  # check for Contact/Experience/Education/Skills
              quantification=self._score_quantification(prose), # % of \item lines with \d+
              formatting=self._score_formatting(latex_content), # date format consistency check
              section_order=self._score_section_order(sections),# Experience before Education for senior
          )
  ```

### 59B · Backend — Confidence Score Endpoint
- [x] Add `POST /ai/confidence-score` to `backend/app/api/ai_routes.py`:
  ```python
  class ConfidenceScoreResponse(BaseModel):
      overall: int
      writing_quality: int
      completeness: int
      quantification: int
      formatting: int
      section_order: int
      grade: str              # "A" (90+) | "B" (80+) | "C" (70+) | "D" (60+) | "F" (<60)
      improvements: List[str] # top 3 specific, actionable recommendations
  ```
  - Cache by `hash(latex_content[:2000])`, TTL=1800
  - No LLM needed — pure rule-based scoring

### 59C · Frontend — Confidence Score Display
- [x] Create `frontend/src/components/ConfidenceScorePanel.tsx`:
  - Large circular score badge with grade letter
  - Radar chart (SVG, no extra dep) — 5 axes: Writing · Complete · Numbers · Formatting · Order
  - Top 3 improvements listed with icons and actionable text
  - "Refresh" button to re-run scoring
- [x] Add "Quality Score" badge in editor status bar (alongside ATS score from P0)

### 59D · Tests
- [x] `backend/test/test_confidence_score.py`:
  - Resume with all 4 expected sections → `completeness >= 80`
  - Resume with "responsible for" × 3 → `writing_quality < 70`
  - Resume with no numbers in any `\item` → `quantification < 20`
  - Empty resume → all dimensions are 0

---

## Feature 60 — LaTeX Documentation Lookup Panel · P2 · M

**Goal:** Right-click any `\command` → "Show Documentation" panel with full syntax, parameters,
examples, related commands. "Command Reference" panel accessible from sidebar.

### 60A · Documentation Data
- [x] Create `frontend/src/lib/latex-docs.ts`:
  ```typescript
  export interface LaTeXDoc {
    command: string        // "\\textbf"
    signature: string      // "\\textbf{text}"
    description: string
    parameters: Array<{ name: string; required: boolean; description: string }>
    examples: Array<{ code: string; description: string }>
    packages: string[]     // [] = core LaTeX
    seealso: string[]
    category: 'formatting' | 'sectioning' | 'math' | 'environments' | 'spacing' | 'graphics' | 'misc'
  }

  export const LATEX_DOCS: LaTeXDoc[] = [
    {
      command: '\\textbf',
      signature: '\\textbf{text}',
      description: 'Renders text in bold weight.',
      parameters: [{ name: 'text', required: true, description: 'Content to bold' }],
      examples: [{ code: '\\textbf{Important}', description: 'Renders "Important" in bold' }],
      packages: [],
      seealso: ['\\textit', '\\underline', '\\emph'],
      category: 'formatting',
    },
    // ... 300+ commands covering core + common packages
  ]
  ```
  - Expand on existing hover provider data already in `LaTeXEditor.tsx` completion provider

### 60B · Documentation Panel Component
- [x] Create `frontend/src/components/LaTeXDocPanel.tsx`:
  - Props: `command?: string` (from right-click), `mode: 'command'|'reference'`
  - Layout: command header → description → parameters table → examples (Monaco read-only) → see also chips
  - Reference mode: search input + scrollable command list grouped by category
  - Clicking "see also" chip navigates to that command's doc

### 60C · Monaco Context Menu Integration
- [x] In `frontend/src/components/LaTeXEditor.tsx`:
  - In `handleEditorDidMount`: add context menu action `latexy.showDocs`:
    - Only shows when cursor is on a word starting with `\`
    - Fires `onShowDocs?.(commandUnderCursor)`
  - Add prop: `onShowDocs?: (command: string) => void`

### 60D · Page Integration
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - "📖 Docs" tab in editor sidebar → `<LaTeXDocPanel mode="reference" />`
  - `docCommand` state → set from `onShowDocs` → passed to panel

---

## Feature 61 — Keyboard Shortcuts Reference Panel · P2 · S

**Goal:** Searchable Cmd+? popup listing all editor keyboard shortcuts grouped by category.

### 61A · Shortcuts Data
- [x] Create `frontend/src/lib/editor-shortcuts.ts`:
  ```typescript
  export interface Shortcut {
    keys: string[]        // ["⌘", "↵"] or ["Ctrl", "Enter"] on Windows
    description: string
    category: 'file' | 'edit' | 'compile' | 'navigation' | 'ai' | 'view'
  }

  export const SHORTCUTS: Shortcut[] = [
    { keys: ['⌘', '↵'],       description: 'Compile resume',             category: 'compile' },
    { keys: ['⌘', 'S'],        description: 'Save',                       category: 'file' },
    { keys: ['⌘', '/'],        description: 'Toggle line comment',         category: 'edit' },
    { keys: ['⌘', 'Z'],        description: 'Undo',                       category: 'edit' },
    { keys: ['⌘', '⇧', 'Z'],  description: 'Redo',                       category: 'edit' },
    { keys: ['⌘', 'F'],        description: 'Find in editor',             category: 'navigation' },
    { keys: ['⌘', 'H'],        description: 'Find and replace',           category: 'navigation' },
    { keys: ['⌘', '⇧', 'F'],  description: 'Search across all resumes',  category: 'navigation' },
    { keys: ['⌘', '?'],        description: 'Show keyboard shortcuts',    category: 'view' },
    // ... all editor shortcuts
  ]
  ```

### 61B · Shortcuts Panel
- [x] Create `frontend/src/components/KeyboardShortcutsPanel.tsx`:
  - Modal (overlay + backdrop) triggered by Cmd+? or "?" toolbar button
  - Search input: real-time filter on `description`
  - Grouped by category with sticky headers
  - Each entry: key combo as `<kbd>` chips + description
  - Close on Escape or backdrop click

### 61C · Integration
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Register Cmd+? keybinding: `editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Slash, showShortcuts)`
  - Alternatively: in page-level `useEffect` with `keydown` listener

---

## Feature 62 — QR Code Auto-Inserter · P2 · S

**Goal:** Insert LaTeX QR code at cursor via toolbar button. Inputs URL, shows live preview,
inserts `\qrcode{url}` with auto-added preamble package.

### 62A · Dependencies
- [x] `qrcode` and `@types/qrcode` in `package.json`

### 62B · QR Inserter Component
- [x] Create `frontend/src/components/QrCodeInserter.tsx`:
  - URL input, size selector (Small/Medium/Large), live canvas preview
  - Auto-injects `\usepackage{qrcode}` if missing; inserts `\qrcode[height=Xcm]{url}` at cursor

### 62C · Integration
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - "QR" icon button in editor toolbar opens `QrCodeInserter` popover

---

## Feature 63 — Resume Template Customizer · P2 · M

**Goal:** Visual sidebar for adjusting margins, font size, section spacing, column layout.
Each adjustment modifies specific preamble lines and optionally triggers auto-compile preview.

### 63A · Preamble Helpers
- [x] Extend `frontend/src/lib/latex-preamble.ts` (from Feature 30):
  ```typescript
  export function setGeometryMargin(latex: string, marginIn: number): string {
    // Replace or insert \geometry{margin=Xin} in preamble
  }
  export function setDocumentClassFontSize(latex: string, size: 10 | 11 | 12): string {
    // Modify \documentclass[11pt]{...} → \documentclass[Xpt]{...}
  }
  export function setSectionVspacing(latex: string, mode: 'compact' | 'normal' | 'spacious'): string {
    // Compact: \vspace{-4pt}, Normal: \vspace{2pt}, Spacious: \vspace{6pt}
  }
  ```
  - Also added `extractSectionSpacingFromPreamble`, `extractRawMarginFromPreamble`

### 63B · Template Customizer Component
- [x] Create `frontend/src/components/TemplateCustomizerPanel.tsx`:
  - **Margins** slider: 0.5in → 1.25in (step 0.05) → calls `setGeometryMargin()`
  - **Font Size** radio: 10pt / 11pt / 12pt → calls `setDocumentClassFontSize()`
  - **Section Spacing** radio: Compact / Normal / Spacious → calls `setSectionVspacing()`
  - **Auto-compile on change** toggle (persisted to localStorage)
  - **Reset to Defaults** button (restores original resume LaTeX from mount time)
  - Each change: calls `onPreambleChange(modified_latex)` → optionally triggers compile

### 63C · Integration
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - "Layout" tab (SlidersHorizontal icon) in editor sidebar
  - Renders `TemplateCustomizerPanel`

---

## Feature 64 — Contact Info Formatter · P2 · S

**Goal:** One-click normalization of phone numbers, LinkedIn/GitHub URLs, and emails in LaTeX.

### 64A · Dependencies
- [x] `phonenumbers==8.13.24` in `backend/requirements.txt`

### 64B · Backend — Contact Formatter Endpoint
- [x] Add `POST /ai/format-contacts` to `backend/app/api/ai_routes.py`:
  - Phone via `phonenumbers.parse()` → INTERNATIONAL format
  - LinkedIn/GitHub URL normalization; email `.lower()`
  - Returns `changes` list + `formatted_latex`

### 64C · Frontend — Contact Format Action
- [x] `ContactFormatterPanel.tsx` shows diff preview of changes with "Apply All" / "Cancel"
- [x] "Contacts" button in editor toolbar

### 64D · Tests
- [x] `backend/test/test_contact_formatter.py`:
  - `https://www.linkedin.com/in/john-doe/` → `linkedin.com/in/john-doe`
  - `john@EXAMPLE.COM` → `john@example.com`
  - Unparseable phone → preserved as-is

---

## Feature 65 — Browser Push Notifications · P2 · S

**Goal:** Browser Notification API. Permission requested after first compile. Fires when
compilation/optimization completes while tab is in background.

### 65A · Frontend — Push Notifications Hook
- [x] Create `frontend/src/hooks/usePushNotifications.ts`:
  ```typescript
  export function usePushNotifications(enabled: boolean) {
    const requestPermission = async () => {
      if (!enabled) return
      if ('Notification' in window && Notification.permission === 'default') {
        await Notification.requestPermission()
      }
    }

    const notify = (title: string, body: string, onClick?: () => void) => {
      if (!enabled) return
      if (Notification.permission !== 'granted') return
      if (document.visibilityState === 'visible') return  // tab is focused — skip
      const n = new Notification(title, {
        body,
        icon: '/favicon.ico',
        tag: 'latexy-job',    // replaces previous notification
      })
      if (onClick) n.onclick = () => { window.focus(); onClick() }
    }

    return { requestPermission, notify }
  }
  ```

### 65B · Integration
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Call `requestPermission()` after first compile attempt (once per `sessionStorage` flag)
  - On `job.completed` WebSocket event: `notify('Compilation complete', 'Your resume is ready')`
- [x] In `frontend/src/app/workspace/[resumeId]/optimize/page.tsx`:
  - On optimization `job.completed`: `notify('Optimization complete', 'Your AI resume is ready to review')`

### 65C · Settings Toggle
- [x] In settings page: "Desktop Notifications" toggle
  - Persisted to localStorage key `latexy_notifications_enabled`
  - Passed to `usePushNotifications(enabled)` hook

---

## Feature 66 — Team / Agency Workspace · P2 · L

**Goal:** Multi-user workspaces for career coaches and recruiting agencies. Invite members,
share resumes, role-based access. Per-workspace billing tied to workspace owner.

### 66A · Database Migration
- [ ] Create `backend/alembic/versions/0015_add_workspaces.py`:
  ```sql
  CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id TEXT NOT NULL DEFAULT 'free',
    max_members INT NOT NULL DEFAULT 5,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE TABLE workspace_members (
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'editor',  -- 'owner' | 'editor' | 'viewer'
    invited_by TEXT REFERENCES users(id),
    invited_at TIMESTAMPTZ DEFAULT NOW(),
    joined_at TIMESTAMPTZ,
    PRIMARY KEY (workspace_id, user_id)
  );

  CREATE TABLE workspace_resumes (
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    resume_id UUID NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    shared_by TEXT REFERENCES users(id),
    shared_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (workspace_id, resume_id)
  );
  ```

### 66B · Backend Models
- [ ] Add `Workspace`, `WorkspaceMember`, `WorkspaceResume` SQLAlchemy models to `backend/app/database/models.py`

### 66C · Backend — Workspace Routes
- [ ] Create `backend/app/api/workspace_routes.py`:
  ```
  POST   /workspaces                              — create workspace
  GET    /workspaces                              — list user's workspaces
  GET    /workspaces/{id}                         — details + member list
  PATCH  /workspaces/{id}                         — update name
  DELETE /workspaces/{id}                         — delete (owner only)
  POST   /workspaces/{id}/members/invite          — invite by email → sends invite email
  DELETE /workspaces/{id}/members/{user_id}       — remove member
  PATCH  /workspaces/{id}/members/{user_id}/role  — change role (owner only)
  POST   /workspaces/{id}/resumes/{resume_id}     — share resume into workspace
  DELETE /workspaces/{id}/resumes/{resume_id}     — unshare resume
  GET    /workspaces/{id}/resumes                 — list shared resumes
  ```
- [ ] Register router in `backend/app/api/routes.py`

### 66D · Frontend — Workspace Dashboard
- [ ] Create `frontend/src/app/workspaces/page.tsx`:
  - Grid of user's workspaces (name, member count badge, resume count)
  - "Create Workspace" button
- [ ] Create `frontend/src/app/workspaces/[workspaceId]/page.tsx`:
  - Shared resume grid (reuses workspace card component)
  - Members sidebar: avatar list, roles, invite form (owner only)
  - "Add Resume" modal: select from personal resumes

### 66E · Tests
- [ ] `backend/test/test_workspaces.py`:
  - Create workspace → owner auto-added as member with role "owner"
  - Non-member GET workspace resumes → 403
  - Max members limit enforced (default 5 for free plan)
  - Owner can remove members; member cannot remove other members

---

## Feature 67 — Custom Domain Resume Hosting · P2 · L

**Goal:** Public portfolio page at `latexy.io/u/[username]`. Optional custom CNAME domain.
Shows public resumes, professional summary, contact form.

### 67A · Database Migration
- [ ] Create `backend/alembic/versions/0016_add_portfolio.py`:
  ```sql
  ALTER TABLE users ADD COLUMN public_username TEXT UNIQUE;
  ALTER TABLE users ADD COLUMN portfolio_enabled BOOLEAN DEFAULT FALSE;
  ALTER TABLE users ADD COLUMN portfolio_custom_domain TEXT UNIQUE;
  ALTER TABLE users ADD COLUMN portfolio_theme TEXT DEFAULT 'minimal';
  ALTER TABLE users ADD COLUMN portfolio_tagline TEXT;
  ```

### 67B · Backend — Portfolio Endpoints
- [ ] Create `backend/app/api/portfolio_routes.py`:
  - `GET /portfolio/{username}` — public, returns user profile + list of public resumes with PDFs
  - `POST /portfolio/setup` — auth required, sets `public_username`, `portfolio_enabled`, `theme`
  - `GET /portfolio/check-username?username=` — availability check
  - `POST /portfolio/verify-domain` — checks CNAME TXT record for domain verification
- [ ] Register router in `backend/app/api/routes.py`

### 67C · Frontend — Portfolio Page
- [ ] Create `frontend/src/app/u/[username]/page.tsx`:
  - Fetches `GET /portfolio/{username}` — 404 if not found or disabled
  - Renders: user name + tagline, grid of public resume PDFs (thumbnails)
  - Contact form (submits to user's email via Resend SMTP)
  - Theme variants: Minimal (default) / Dark / Professional
  - "Powered by Latexy" footer (free tier; removable on Pro)

### 67D · Custom Domain
- [ ] In Next.js middleware (`frontend/src/middleware.ts`):
  - If `Host` header matches a registered `portfolio_custom_domain` → rewrite to `/u/{username}`
  - Domain verification: check `GET /portfolio/verify-domain?domain=...` before activating

### 67E · Tests
- [ ] `backend/test/test_portfolio.py`:
  - GET `/portfolio/{username}` with `portfolio_enabled=False` → 404
  - GET `/portfolio/{username}` with enabled portfolio → returns user data
  - Username with special chars (spaces, `@`) → 422 on setup

---

## Feature 68 — Resume-to-Portfolio Site · P2 · L

**Goal:** Auto-generate a static portfolio website from resume JSON export. Hosted at
`latexy.io/u/[username]`. Auto-updates on re-optimization.

### 68A · Backend — Portfolio Generator Service
- [ ] Create `backend/app/services/portfolio_generator.py`:
  ```python
  class PortfolioGenerator:
      async def generate(self, resume: Resume, user: User, theme: str = "minimal") -> str:
          # 1. Export resume to structured dict via document_export_service
          # 2. Load Jinja2 template from backend/app/templates/portfolio/{theme}.html
          # 3. Render template with resume data
          # 4. Store in MinIO: portfolio/{user_id}/{resume_id}/index.html
          # 5. Return public URL
  ```

### 68B · Portfolio HTML Template
- [ ] Create `backend/app/templates/portfolio/minimal.html.j2`:
  - Single-page HTML (no external framework dependencies for fast load)
  - Sections: sticky header (name + nav) · hero (summary) · experience timeline · skills grid ·
    education · projects · contact section
  - Responsive CSS using CSS Grid
  - Light/dark mode toggle via CSS `prefers-color-scheme`
  - "Powered by Latexy" footer

### 68C · Backend — Generation Endpoint
- [ ] Add `POST /resumes/{resume_id}/generate-portfolio` to `backend/app/api/resume_routes.py`:
  - Calls `PortfolioGenerator.generate()`
  - Returns `{ portfolio_url: str }`
- [ ] Hook: trigger regeneration when `portfolio_enabled=True` and resume is re-optimized

### 68D · Frontend — Generate Portfolio Action
- [ ] In workspace resume card actions:
  - "🌐 Generate Portfolio Site" → triggers generation
  - Shows URL with "View" link after completion

---

## Feature 69 — Multi-Resume Merge · P2 · M

**Goal:** Select 2–4 resumes, choose which section from which resume to keep, preview merged
result, save as new resume.

### 69A · Backend — Section-Level Merge
- [x] Add `POST /resumes/merge` to `backend/app/api/resume_routes.py`:
  ```python
  class MergeRequest(BaseModel):
      resume_ids: List[str] = Field(..., min_length=2, max_length=4)
      section_choices: Dict[str, str]   # { "Experience": "resume_id_1", "Skills": "resume_id_2" }

  class MergeResponse(BaseModel):
      merged_latex: str
      new_resume_id: str
  ```
  - Verify ownership of all `resume_ids`
  - Parse sections from each resume via `extract_sections()` (Feature 53)
  - Reconstruct: take preamble from `resume_ids[0]`, then each section from `section_choices`
  - Sections not in `section_choices` → taken from `resume_ids[0]`
  - Save as new resume: `title = "Merged Resume"`, `parent_resume_id = resume_ids[0]`

### 69B · Frontend — Merge UI
- [x] Create `frontend/src/app/workspace/merge/page.tsx`:
  - **Step 1**: Multi-select up to 4 resumes (checkbox grid with card previews)
  - **Step 2**: Section picker — for each detected section, dropdown to choose source resume
  - **Step 3**: Monaco diff editor (original `resume_ids[0]` left, merged result right)
  - **Step 4**: "Save as New Resume" button
- [x] Add "Merge Resumes" in workspace header actions

### 69C · Tests
- [x] `backend/test/test_resume_merge.py`:
  - Merge 2 resumes with `section_choices` → correct sections from correct sources
  - `resume_ids` with non-owned resume → 403
  - `resume_ids` with only 1 entry → 422

---

## Feature 70 — Reference Page Generator · P2 · S

**Goal:** Generate a matching-style LaTeX reference page from up to 5 contact entries.
Download as .tex or compile to PDF.

### 70A · Backend — Reference Page Endpoint
- [x] Add `POST /resumes/{resume_id}/generate-references` to `backend/app/api/resume_routes.py`:
  - Accepts up to 5 `ReferenceContact` entries
  - Extracts `\documentclass` and style from source resume
  - Renders via `references_page.tex.j2` Jinja2 template

### 70B · References Template
- [x] Created `backend/app/templates/references_page.tex.j2`:
  - Matches parent resume `\documentclass`; clean bold-name reference list

### 70C · Frontend — Reference Page UI
- [x] `GenerateReferencesModal.tsx`: dynamic form up to 5 entries, download `.tex` + "Compile to PDF"
- [x] Accessible via workspace card action and editor toolbar

### 70D · Tests
- [x] `backend/test/test_references_page.py`:
  - Generates valid LaTeX with 2 references
  - `references` with 6 entries → 422

---

## Feature 71 — Watermark Control · P2 · S

**Goal:** "Download with Watermark" option. Options: DRAFT, CONFIDENTIAL, FOR REVIEW ONLY,
custom text. Applied via `draftwatermark` LaTeX package at compile time. Original never modified.

### 71A · Backend — Watermark Compile Parameter
- [x] In `backend/app/workers/latex_worker.py`:
  - Add `watermark: Optional[str] = None` parameter to `compile_latex_task`
  - Validate: `len(watermark) <= 30` and `re.match(r'^[A-Za-z0-9 \-\.]+$', watermark)` (prevent injection)
  - If set: inject before `\begin{document}`:
    ```latex
    \usepackage{draftwatermark}
    \SetWatermarkText{DRAFT}
    \SetWatermarkScale{1.2}
    \SetWatermarkColor[gray]{0.94}
    ```
  - Watermarked compilation: returns temp PDF (not stored as canonical PDF for the resume)

### 71B · Backend — Watermark Compile Endpoint
- [x] Add `POST /jobs/compile-watermarked` to `backend/app/api/job_routes.py`:
  - Same as regular compile but with `watermark` param
  - Returns temp PDF download URL (24h TTL presigned MinIO URL)

### 71C · Frontend — Watermark UI
- [x] In PDF preview toolbar download button dropdown:
  - "⬇ Download with Watermark" → opens watermark options popover
  - Quick-select: "DRAFT" · "CONFIDENTIAL" · "FOR REVIEW ONLY" · "Custom..."
  - Custom input: text field (max 30 chars)
  - "Download" → triggers watermarked compile → downloads result

### 71D · Tests
- [x] `backend/test/test_watermark.py`:
  - Watermark injection adds `\usepackage{draftwatermark}` to LaTeX
  - `watermark="rm -rf /"` → 422 (injection rejected)
  - `watermark` with 31 chars → 422
  - Watermarked compile returns separate job ID (not overwriting canonical)

---

## Feature 72 — Smart Import from Resume Builders · P2 · M

**Goal:** Import JSON Resume files from Kickresume, Resume.io, Novoresume with platform-specific
parsing hints. Import wizard with step-by-step export instructions per platform.

### 72A · Backend — Platform-Aware Import
- [x] In `backend/app/services/document_converter_service.py`:
  - Add `source_platform: Optional[str] = None` parameter to JSON Resume import
  - Platform-specific LLM prompt adjustments:
    - `kickresume`: remap nested skill categories, handle "Summary" vs "Objective" naming
    - `resumeio`: handle `position` vs `title` field naming inconsistencies
    - `novoresume`: handle `YYYY/MM` date format → ISO 8601
  - `source_platform` also used for analytics tracking
- [x] In `POST /formats/upload`: accept optional `?source_platform=kickresume|resumeio|novoresume` query param

### 72B · Frontend — Import Wizard
- [x] Create `frontend/src/components/ImportFromBuilderWizard.tsx`:
  - **Step 1** — Platform selector: card grid (Kickresume, Resume.io, Novoresume, Generic JSON)
  - **Step 2** — Export instructions (platform-specific):
    - Kickresume: "Dashboard → Settings → Export → JSON Resume"
    - Resume.io: "My Resumes → ⋯ → Download → JSON"
    - Novoresume: "Edit Resume → Download → JSON Resume"
  - **Step 3** — File upload dropzone
  - **Step 4** — Preview parsed content before conversion: shows extracted name, experience count, skills
  - **Step 5** — "Convert to LaTeX" button → calls `/formats/upload?source_platform=...`
- [x] Add "Import from Resume Builder" in workspace new-resume flow

### 72C · Tests
- [x] `backend/test/test_builder_import.py`:
  - Kickresume JSON with nested skills → LaTeX output contains skill entries
  - Unknown `source_platform` → falls back to generic JSON Resume parsing (no error)
  - Malformed JSON file → 422

---

## Feature 73 — Recruiter / Agency View · P2 · L

**Goal:** Separate recruiter dashboard for agency workspaces (Feature 66 prerequisite).
Candidate list with ATS scores. Side-by-side comparison. Notes and ratings. Shortlist sharing.

### 73A · Prerequisite
- [ ] Feature 66 (Team Workspace) must be fully implemented

### 73B · Database Migration
- [ ] Create `backend/alembic/versions/0017_add_recruiter_notes.py`:
  ```sql
  CREATE TABLE recruiter_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    resume_id UUID NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    author_id TEXT NOT NULL REFERENCES users(id),
    rating INT CHECK (rating BETWEEN 1 AND 5),
    note_text TEXT,
    stage TEXT DEFAULT 'reviewing',   -- 'reviewing' | 'shortlisted' | 'rejected'
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```

### 73C · Backend — Recruiter Routes
- [ ] Add to `backend/app/api/workspace_routes.py`:
  - `GET /workspaces/{id}/candidates` — list all shared resumes with ATS scores, latest note, rating
  - `POST /workspaces/{id}/candidates/{resume_id}/notes` — add note + rating
  - `PATCH /workspaces/{id}/candidates/{resume_id}/stage` — update candidate stage
  - `POST /workspaces/{id}/shortlist` — create password-protected share bundle link:
    - Body: `{ resume_ids: List[str], password: str }`
    - Returns link that shows multiple PDFs behind password gate

### 73D · Frontend — Recruiter Dashboard
- [ ] Create `frontend/src/app/workspaces/[id]/recruiter/page.tsx`:
  - Table: candidate name | role title | ATS score | stage badge | last updated | ⭐ rating
  - Sort by: ATS score, stage, last updated
  - "Compare" button: select 2 candidates → side-by-side Monaco diff of their LaTeX
  - Inline notes: click candidate row to expand notes panel
  - "Shortlist" action: select candidates → password-protected share bundle
  - Filter by stage: Reviewing / Shortlisted / Rejected

---

## Feature 74 — Resume Collaboration Comments · P2 · L

**Goal:** Async line-level comments like GitHub PR reviews. Monaco gutter icons open thread
panels. Share-for-review link gives commenter-only access.

### 74A · Database Migration
- [ ] Create `backend/alembic/versions/0018_add_resume_comments.py`:
  ```sql
  CREATE TABLE resume_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id UUID NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    author_id TEXT NOT NULL REFERENCES users(id),
    line_start INT NOT NULL,
    line_end INT NOT NULL,
    comment_text TEXT NOT NULL,
    parent_comment_id UUID REFERENCES resume_comments(id) ON DELETE CASCADE,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX idx_resume_comments_resume ON resume_comments(resume_id);
  ```

### 74B · Backend — Comment Routes
- [ ] Create `backend/app/api/comment_routes.py`:
  ```
  GET    /resumes/{resume_id}/comments           — list all comments (auth: owner or collaborator)
  POST   /resumes/{resume_id}/comments           — create comment
  PUT    /resumes/{resume_id}/comments/{id}      — edit (author only)
  DELETE /resumes/{resume_id}/comments/{id}      — delete (author or owner)
  PATCH  /resumes/{resume_id}/comments/{id}/resolve — toggle resolved
  ```
  - Share-for-review: extend `POST /resumes/{id}/share` with `scope=comment` option
  - Token with `comment_only` scope allows `GET` and `POST` comments without full auth
- [ ] Register router in `backend/app/api/routes.py`

### 74C · Frontend — Comment Gutter Icons
- [ ] In `frontend/src/components/LaTeXEditor.tsx`:
  - Add prop: `comments?: ResumeComment[]`
  - Render `monaco.editor.addGlyphMarginWidget` for each commented line: speech bubble 💬 icon
  - Click icon → fires `onCommentClick?.(lineNumber)`
  - "Add Comment" Monaco context menu action (when text is selected)

### 74D · Frontend — Comments Panel
- [ ] Create `frontend/src/components/CommentsPanel.tsx`:
  - Sorted list of comment threads by line number
  - Thread expansion with `<reply>` input
  - "Resolve" toggle per thread (gray out resolved threads)
  - Unresolved count badge on panel tab header
  - Real-time updates: re-fetch every 30s or on WebSocket event

### 74E · Tests
- [ ] `backend/test/test_comments.py`:
  - Create comment → GET returns it with correct `line_start`, `line_end`
  - Non-owner, non-collaborator cannot POST comment → 403
  - Comment-only share token allows `POST` comment but not `GET /resumes/{id}` → 403
  - Resolve → `resolved=True` in GET
  - Delete parent → child comments cascade deleted

---

## Feature 75 — Bulk Apply Package · P2 · M

**Goal:** Input up to 10 JDs at once → parallel LLM optimizations → separate variants per JD.
Progress board shows real-time status. Download all as ZIP. Auto-adds to job tracker.

### 75A · Backend — Batch Tailor Endpoint
- [x] Add `POST /jobs/batch` to `backend/app/api/job_routes.py`:
  ```python
  class BatchJobItem(BaseModel):
      company_name: str = Field(..., max_length=200)
      role_title: str = Field(..., max_length=200)
      job_description: str = Field(..., max_length=20_000)
      job_url: Optional[str] = Field(None, max_length=500)

  class BatchTailorRequest(BaseModel):
      resume_id: str
      jobs: List[BatchJobItem] = Field(..., min_length=1, max_length=10)

  class BatchTailorResponse(BaseModel):
      batch_id: str
      job_ids: List[str]   # one per BatchJobItem
  ```
  - Auth required; verify ownership of `resume_id`
  - For each item: fork resume → submit optimization job via `submit_optimize_and_compile()` with JD
  - Store batch metadata in Redis: `latexy:batch:{batch_id}` TTL=86400
  - Return immediately; client polls individual job IDs or batch status

### 75B · Backend — Batch Status Endpoint
- [x] Add `GET /jobs/batch/{batch_id}` to `backend/app/api/job_routes.py`:
  - Returns `{ batch_id, jobs: [{ job_id, company_name, status, variant_resume_id? }] }`
  - Aggregated status: `pending|running|partial|complete|failed`

### 75C · Frontend — Batch Tailor Page
- [x] Create `frontend/src/app/workspace/[resumeId]/batch-tailor/page.tsx`:
  - Input list (up to 10 rows): company name, role title, JD textarea, optional URL
  - "Add Row" / "Remove Row" buttons; auto-adds row if last row is filled
  - "Start Batch Tailor" button → dispatches POST
  - **Progress board**: card per job with real-time status badges (Pending → Running → Complete)
  - Poll `GET /jobs/batch/{batch_id}` every 3 seconds while jobs are running
  - "Download All as ZIP" (enabled when all complete) → calls bulk export for variant IDs

### 75D · Tests
- [x] `backend/test/test_batch_tailor.py`:
  - Batch of 3 jobs → 3 separate variant resumes created (mock LLM)
  - `jobs` with 11 entries → 422
  - Non-owned `resume_id` → 403
  - `GET /jobs/batch/{batch_id}` returns correct status per job

---

## Feature 76 — Dark Mode PDF Preview · P2 · S

**Goal:** Toggle in PDF viewer applies CSS invert filter for dark-mode viewing. LaTeX source and
stored PDF unmodified — display-only transformation.

### 76A · Frontend — Dark Mode Toggle
- [x] In PDF preview component (wherever PDF is rendered — iframe or canvas):
  - Add `darkPdfMode: boolean` state
  - "🌙 Dark Preview" toggle button in PDF toolbar
  - When enabled: apply CSS to the PDF container element:
    ```css
    filter: invert(1) hue-rotate(180deg);
    background: #fff;  /* prevent background flash */
    ```
  - Persist preference: `localStorage.setItem('latexy_pdf_dark', '1')`
  - On mount: read preference and apply

### 76B · Integration
- [x] Apply to all pages that render PDFs:
  - `frontend/src/app/workspace/[resumeId]/edit/page.tsx`
  - `frontend/src/app/workspace/[resumeId]/optimize/page.tsx`
  - `frontend/src/app/try/page.tsx`
  - `frontend/src/app/r/[token]/page.tsx` (shared view)

---

## Shared Infrastructure Needed

- [x] **`phonenumbers==8.13.24`** — Python phone normalizer for Feature 64
  - `pip install phonenumbers && update backend/requirements.txt`
- [x] **`yjs` + `y-monaco` + `y-websocket`** — CRDT collaboration for Feature 40
  - `pnpm add yjs y-monaco y-websocket y-protocols`
- [x] **`qrcode`** — client-side QR generation for Feature 62
  - `pnpm add qrcode @types/qrcode`
- [x] **`recharts`** — radar chart for Feature 59: used inline SVG instead (no extra dependency needed)
- [ ] **LanguageTool** — `LANGUAGETOOL_URL` in config for Feature 35
  - Free public API: `https://api.languagetool.org/v2/check` (no key needed for basic use)
  - Self-hosted option: Docker image `erikvl87/languagetool`
- [ ] **GitHub OAuth app** — `GITHUB_CLIENT_ID` + `GITHUB_CLIENT_SECRET` for Feature 37
  - Create at `github.com/settings/applications/new`
- [ ] **Zotero API credentials** — `ZOTERO_CLIENT_KEY` + `ZOTERO_CLIENT_SECRET` for Feature 42
  - Register at `www.zotero.org/oauth/apps`
- [ ] **Mendeley API credentials** — `MENDELEY_CLIENT_ID` + `MENDELEY_CLIENT_SECRET` for Feature 42
  - Register at `dev.mendeley.com`
- [ ] **ORCID public API** — no key needed for Feature 58 (ORCID is freely accessible)
- [ ] **`@dnd-kit/*`** — drag-and-drop for Feature 53 Section Reorder (may already be installed from Feature 15)
  - `pnpm add @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities` if not present
- [x] **Jinja2 templates** — portfolio HTML and references page templates for Features 68 and 70
  - `jinja2` is likely already in backend deps; add if not
- [ ] **Migration sequence** — Features 37, 40, 42, 43, 49, 53, 66, 73, 74 each add migrations:
  - Next migration after current `0009`: `0010_add_github_integration` → `0011_add_resume_archive`
    → `0012_add_collaboration` → `0013_add_resume_views` → `0014_ats_score_to_history`
    → `0015_add_workspaces` → `0016_add_portfolio` → `0017_add_recruiter_notes`
    → `0018_add_resume_comments`
