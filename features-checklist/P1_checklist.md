# P1 Feature Implementation Checklist

> Deep implementation guide for all 26 P1 features. Each item maps directly to the current codebase —
> file paths, specific functions, and exact changes. Work through features in dependency order.
>
> **Branch convention:** one branch per feature (e.g. `feat/shareable-links`)
> **Key files to know:** see `MEMORY.md` for architecture overview.
> **Numbering:** continues from P0 (Features 1–8); P1 starts at Feature 9.

---

## Legend
- `[ ]` — not started
- `[x]` — done
- `[~]` — in progress
- Complexity: **S** = < 1 week | **M** = 1–3 weeks | **L** = 1–2 months

---

## Build Order (recommended)

```
Quick wins first (S complexity, high impact):
  11 → 34 → 31 → 30 → 27 → 19

Backend-first features:
  10 → 13 → 14 → 16

AI features (share LLM infrastructure):
  22 → 24 → 23 → 25 → 26

Full-stack features:
  9 → 20 → 28 → 29 → 18 → 17

Large features (own sprints):
  15 → 21 → 32 → 33
```

---

## Feature 9 — Multiple LaTeX Compilers (XeLaTeX, LuaLaTeX) · P1 · L ✅ COMPLETED

**Goal:** Let users choose between `pdflatex`, `xelatex`, and `lualatex` per-resume. The Docker
texlive image already ships all three — this is backend config + API + frontend selector.
Compiler preference stored in resume `metadata` JSONB column.

### 9A · Database Migration — Resume Metadata Column
- [x] Create `backend/alembic/versions/0007_add_resume_metadata.py`
  ```sql
  ALTER TABLE resumes ADD COLUMN metadata JSONB DEFAULT '{}';
  COMMENT ON COLUMN resumes.metadata IS 'Per-resume settings: compiler, custom flags, etc.';
  ```
  - No index needed (metadata is read per-resume, not filtered globally)
  - Default `'{}'::jsonb` so existing resumes get an empty object
- [x] Update `Resume` model in `backend/app/database/models.py`:
  ```python
  from sqlalchemy.dialects.postgresql import JSONB
  metadata: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True, default={})
  ```
  - Note: attribute named `resume_settings` (mapped to `"metadata"` column) to avoid SQLAlchemy reserved name conflict
- [x] Update `ResumeResponse` Pydantic schema in `resume_routes.py`:
  - Add `metadata: Optional[Dict] = None`
  - Already returns from `GET /resumes/{id}` — just add field

### 9B · Config — Allowed Compilers
- [x] Add to `backend/app/core/config.py`:
  ```python
  ALLOWED_LATEX_COMPILERS: List[str] = ["pdflatex", "xelatex", "lualatex"]
  DEFAULT_LATEX_COMPILER: str = "pdflatex"
  ```
  - Validation: `compiler not in settings.ALLOWED_LATEX_COMPILERS → 400`

### 9C · Backend — Compile Task Update
- [x] In `backend/app/workers/latex_worker.py`:
  - Add `compiler: str = "pdflatex"` to `compile_latex_task` signature:
    ```python
    def compile_latex_task(
        self,
        latex_content: str,
        job_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_plan: str = "free",
        device_fingerprint: Optional[str] = None,
        metadata: Optional[Dict] = None,
        resume_id: Optional[str] = None,
        compiler: str = "pdflatex",   # ADD
    ) -> Dict[str, Any]:
    ```
  - Validate compiler:
    ```python
    if compiler not in ["pdflatex", "xelatex", "lualatex"]:
        compiler = "pdflatex"
    ```
  - Replace hardcoded `"pdflatex"` in subprocess command with `compiler`:
    ```python
    cmd = [
        compiler,                        # was: "pdflatex"
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-synctex=1",                    # supported by all three
        "-output-directory", str(work_dir),
        str(tex_file),
    ]
    ```
  - Note: `-synctex=1` is supported by all three engines; no change needed
  - Note: XeLaTeX is slower (2–3×) — no timeout change needed (already plan-tiered by Feature 11)
  - Include `compiler` in job result and `job.completed` event payload:
    ```python
    publish_event(job_id, "job.completed", {
        "percent": 100,
        "pdf_job_id": job_id,
        "compiler": compiler,   # ADD — helps frontend show which engine ran
    })
    ```

- [x] Update `submit_latex_compilation()` helper in `latex_worker.py`:
  ```python
  def submit_latex_compilation(
      latex_content: str,
      job_id: str,
      user_id: Optional[str] = None,
      user_plan: str = "free",
      device_fingerprint: Optional[str] = None,
      metadata: Optional[Dict] = None,
      resume_id: Optional[str] = None,
      compiler: str = "pdflatex",     # ADD
  ) -> None:
      compile_latex_task.apply_async(
          kwargs={
              ...,
              "compiler": compiler,   # ADD
          },
          queue="latex",
          priority=get_task_priority(user_plan),
      )
  ```

### 9D · Backend — Resume Compiler Preference Endpoint
- [x] Add `PATCH /resumes/{resume_id}/settings` to `backend/app/api/resume_routes.py`:
  - Auth required, verify ownership
  - Body: `{ compiler?: str, custom_flags?: str }`
  - Validates `compiler` is in `ALLOWED_LATEX_COMPILERS`
  - Merges into `resume.metadata`: `resume.metadata = {**(resume.metadata or {}), **body}`
  - Returns updated `ResumeResponse`
  - This is a lightweight settings endpoint; no need for a separate route file

### 9E · Backend — Pass Compiler at Compile Time
- [x] In `backend/app/api/job_routes.py`, `compile_latex_endpoint()`:
  - Three-tier resolution: explicit request compiler → resume metadata lookup → default pdflatex
  - Pass to `submit_latex_compilation(..., compiler=compiler)`
  - When compiling without a resume (anonymous on `/try`): uses `pdflatex` (default)
- [x] In `backend/app/workers/orchestrator.py` (for optimize+compile pipeline):
  - Similarly accept and pass `compiler` parameter through the orchestration chain

### 9F · Backend — Job Submit API Update
- [x] In `backend/app/api/job_routes.py`, `JobSubmissionRequest` schema:
  - Add optional `compiler: Optional[str] = None` field
  - Validated against `ALLOWED_LATEX_COMPILERS` in endpoint handler
  - Pass to `submit_latex_compilation()`

### 9G · Frontend — API Client
- [x] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  updateResumeSettings(
    resumeId: string,
    settings: { compiler?: 'pdflatex' | 'xelatex' | 'lualatex'; custom_flags?: string }
  ): Promise<ResumeResponse>
  ```
- [x] Update `ResumeResponse` interface: add `metadata?: { compiler?: string; [key: string]: unknown }`
- [x] Added `LatexCompiler` type export and `compiler` param to `compileLatex()` / `optimizeAndCompile()`

### 9H · Frontend — Compiler Selector in Editor Toolbar
- [x] Create `frontend/src/components/CompilerSelector.tsx`:
  - Props: `current`, `onChange`, `disabled`, `resumeId`
  - Dropdown with pdflatex/xelatex/lualatex options with description tooltips
  - On change: calls `apiClient.updateResumeSettings()`, shows toast
  - Cyan styling for non-pdflatex engines
- [x] Mount in `frontend/src/app/workspace/[resumeId]/edit/page.tsx` editor toolbar
  - Reads initial value from `resume.metadata?.compiler ?? 'pdflatex'`
  - Disabled while compilation is running
- [x] Mount in `frontend/src/app/workspace/[resumeId]/optimize/page.tsx` as well

### 9I · Frontend — Compiler in Job Submit
- [x] When submitting a compile job on edit page:
  - Reads `compiler` state and passes as `compiler` in job submit body
  - Defaults to `"pdflatex"` if not set

### 9J · Tests
- [x] `backend/test/test_compiler_selection.py` — 10/10 passing:
  - `PATCH /resumes/{id}/settings` with valid compiler → 200, metadata updated
  - `PATCH /resumes/{id}/settings` with invalid compiler → 400
  - `compile_latex_task` with `compiler="xelatex"` uses xelatex binary (mock subprocess)
  - `compile_latex_task` with `compiler="lualatex"` uses lualatex binary
  - `compile_latex_task` with invalid compiler falls back to `pdflatex`
- [x] Full test suite: 917/917 passing
- [x] Live E2E API tests: 17/17 passing against running server
- [x] Frontend build: zero TypeScript errors

---

## Feature 10 — Shareable Resume Links · P1 · M ✅ COMPLETED

**Goal:** Generate public `/r/{token}` URLs for sharing compiled resumes. Token is per-resume,
generated on demand, revocable. Public route renders PDF without login.

### 10A · Database Migration
- [x] Create `backend/alembic/versions/0008_add_resume_share_token.py`
  ```sql
  ALTER TABLE resumes ADD COLUMN share_token TEXT UNIQUE;
  ALTER TABLE resumes ADD COLUMN share_token_created_at TIMESTAMPTZ;
  CREATE UNIQUE INDEX idx_resumes_share_token ON resumes(share_token) WHERE share_token IS NOT NULL;
  ```
  - Nullable by default — share link only exists when explicitly generated
  - Unique partial index (only on non-null rows) — efficient for token lookups

### 10B · Backend Model Update
- [x] In `backend/app/database/models.py`, `Resume` model:
  ```python
  share_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True, unique=True, index=False)
  share_token_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
  ```
- [x] Update `ResumeResponse` Pydantic schema: add `share_token: Optional[str] = None`,
  `share_url: Optional[str] = None` (computed via `@model_validator(mode='after')`)
  - Added `FRONTEND_URL: str = "http://localhost:5180"` to `config.py`

### 10C · Backend — Share Endpoints
- [x] Added to `backend/app/api/resume_routes.py`:
  - `POST /resumes/{resume_id}/share` — idempotent token generation, lazy PDF upload to MinIO
  - `DELETE /resumes/{resume_id}/share` — revokes token, returns 204
- [x] Added `GET /share/{share_token}` to `backend/app/api/routes.py` (root level, no auth)
  - MinIO presigned URL (1h TTL) + temp dir fallback
  - Returns `{ resume_title, share_token, pdf_url, compiled_at }`

### 10D · Frontend — Share Modal Component
- [x] Created `frontend/src/components/ShareResumeModal.tsx`:
  - States: no link (Generate button) → link exists (URL + Copy + Revoke)
  - Two-step revoke confirmation
  - Escape key + backdrop click close
  - Copy shows checkmark for 2s

### 10E · Frontend — API Client Methods
- [x] Added to `frontend/src/lib/api-client.ts`:
  - `createShareLink()`, `revokeShareLink()`, `getSharedResume()`
  - `ShareLinkResponse` and `SharedResumeResponse` interfaces
  - `ResumeResponse` extended with `share_token` and `share_url` fields

### 10F · Frontend — Share Button Integration
- [x] `frontend/src/app/workspace/page.tsx`: Share button on every resume card (sky when active)
- [x] `frontend/src/app/workspace/[resumeId]/edit/page.tsx`: Share button in editor header

### 10G · Frontend — Public `/r/[token]` Route
- [x] Created `frontend/src/app/r/[token]/page.tsx`:
  - Loading spinner → error state (revoked/no PDF) → full-height iframe PDF viewer
  - Minimal layout (no nav), "View only" header, Latexy branding footer

### 10H · Tests
- [x] `backend/test/test_share_links.py` — 11/11 passing:
  - Token creation, idempotency, auth boundaries, ownership checks
  - Revoke + verify token cleared from ResumeResponse
  - GET nonexistent/revoked → 404, no compilation → 404, MinIO PDF → 200
  - `ResumeResponse` includes `share_token` and `share_url` fields
- [x] `frontend/e2e/share-links.spec.ts` — 46/46 passing:
  - Workspace Share button states (active/inactive), modal open/close
  - Generate link flow, copy, revoke with confirmation
  - Public `/r/[token]` page: loading, error, success, no-auth access
  - API route verification (POST/DELETE/GET endpoints called correctly)

---

## Feature 11 — Compile Timeout per Plan · P1 · S ✅ COMPLETED

**Goal:** Free users get 30s compile timeout; Basic 120s; Pro/BYOK 240s. When timeout hits,
return `compile_timeout` error code with upgrade CTA. Latency SLA differentiation.

### 11A · Config — Timeout Tiers
- [x] Add to `backend/app/core/config.py`:
  ```python
  # Compile timeout per subscription plan (seconds)
  COMPILE_TIMEOUT_FREE: int = 30
  COMPILE_TIMEOUT_BASIC: int = 120
  COMPILE_TIMEOUT_PRO: int = 240
  COMPILE_TIMEOUT_BYOK: int = 240
  ```
  - Keep existing `COMPILE_TIMEOUT = 30` as fallback for unauthenticated requests
- [x] Add helper function in `config.py` or `latex_worker.py`:
  ```python
  def get_compile_timeout(user_plan: str) -> int:
      return {
          "free":  settings.COMPILE_TIMEOUT_FREE,
          "basic": settings.COMPILE_TIMEOUT_BASIC,
          "pro":   settings.COMPILE_TIMEOUT_PRO,
          "byok":  settings.COMPILE_TIMEOUT_BYOK,
      }.get(user_plan, settings.COMPILE_TIMEOUT_FREE)
  ```

### 11B · Worker — Enforce Timeout
- [x] In `backend/app/workers/latex_worker.py`:
  - The worker already checks `time.time() - start_time > settings.COMPILE_TIMEOUT` per log line
  - Replace the hardcoded `settings.COMPILE_TIMEOUT` check with `timeout` parameter:
    ```python
    def compile_latex_task(
        self,
        ...
        compiler: str = "pdflatex",
        timeout_seconds: Optional[int] = None,  # ADD
    ) -> Dict[str, Any]:
        timeout = timeout_seconds or settings.COMPILE_TIMEOUT
        # ... in the log-reading loop:
        if time.time() - start_time > timeout:
            process.kill()
            publish_event(job_id, "job.failed", {
                "error": f"Compilation exceeded {timeout}s time limit",
                "error_code": "compile_timeout",   # specific code for frontend
                "upgrade_message": "Upgrade to Pro for 4-minute compile timeout",
                "user_plan": user_plan,
            })
            return {"success": False, "error_code": "compile_timeout"}
    ```
  - Catch `SoftTimeLimitExceeded` (from Celery task `soft_time_limit`):
    ```python
    from celery.exceptions import SoftTimeLimitExceeded
    except SoftTimeLimitExceeded:
        publish_event(job_id, "job.failed", {
            "error": "Compilation timed out",
            "error_code": "compile_timeout",
        })
    ```

### 11C · Submit Helper — Pass Timeout
- [ ] In `submit_latex_compilation()`:
  ```python
  def submit_latex_compilation(..., user_plan: str = "free", ...):
      timeout = get_compile_timeout(user_plan)
      compile_latex_task.apply_async(
          kwargs={
              ...,
              "timeout_seconds": timeout,
          },
          queue="latex",
          priority=get_task_priority(user_plan),
          time_limit=timeout + 30,       # Celery hard kill (+30s buffer for cleanup)
          soft_time_limit=timeout + 15,  # raises SoftTimeLimitExceeded (+15s buffer)
      )
  ```

### 11D · Orchestrator — Same Change
- [ ] In `backend/app/workers/orchestrator.py`:
  - Pass `timeout_seconds` when spawning the compile sub-task
  - Orchestrator also has its own `time_limit` — ensure it's `timeout + llm_timeout` (don't cut LLM short)

### 11E · Frontend — Timeout Error Handling
- [ ] In `frontend/src/hooks/useJobStream.ts`, `job.failed` handler:
  - Detect `error_code === "compile_timeout"` in event payload
  - Set special state: `timeoutError: { plan: string; upgradeMessage: string }`
- [ ] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx` and try/page.tsx:
  - When `stream.timeoutError` is set:
    ```tsx
    {stream.timeoutError && (
      <div className="flex items-center gap-3 px-4 py-2 bg-amber-500/10 border border-amber-500/20 rounded-lg">
        <span className="text-xs text-amber-300">
          ⏱ Compile timed out ({stream.timeoutError.plan} plan: {getTimeoutForPlan(stream.timeoutError.plan)}s limit)
        </span>
        <button onClick={() => router.push('/settings/billing')}
          className="text-xs text-amber-200 underline">
          Upgrade for longer timeouts →
        </button>
      </div>
    )}
    ```

### 11F · Tests
- [ ] `backend/test/test_compile_timeout.py`:
  - `get_compile_timeout("free")` returns 30
  - `get_compile_timeout("pro")` returns 240
  - `get_compile_timeout("unknown")` returns 30 (fallback)
  - Mock: when process takes > timeout → `error_code == "compile_timeout"` in published event
  - `submit_latex_compilation()` passes correct `time_limit` to `.apply_async()`

---

## Feature 12 — Compilation History Diff Viewer · P1 · M ✅ COMPLETED

**Goal:** Users can select any two entries from the optimization/checkpoint history and see a
side-by-side Monaco diff. Includes colored diff stats (+N / -N lines) and restore actions.
**Note:** P0 Feature 2 built `DiffViewerModal` and `VersionHistoryPanel`; this feature extends
them to support any two optimization-history entries (not just checkpoints).

### 12A · Verify P0 Coverage
- [x] Confirm `VersionHistoryPanel` supports multi-select (checkbox on each entry):
  - P0 implemented selection state (max 2), "Compare Selected" button when 2 selected
  - `DiffViewerModal` loads content via `getCheckpointContent` for any optimization record
- [x] Confirm `DiffViewerModal` supports loading `original_latex` vs `optimized_latex` for any
  two optimization records (not just checkpoints) via `GET /resumes/{id}/checkpoints/{id}/content`

### 12B · Backend — Ensure Content Endpoint is General
- [x] `GET /resumes/{resume_id}/checkpoints/{checkpoint_id}/content` queries `Optimization`
  table without `is_checkpoint` filter — works for AI runs, auto-saves, and manual checkpoints

### 12C · Frontend — Diff Statistics in DiffViewerModal
- [x] Added `DiffStats` state + `computeDiffStats` via `editor.onDidUpdateDiff()` + `editor.getLineChanges()`
- [x] Header displays `+{added}  −{removed}  · N sections changed` in green/red

### 12D · Frontend — Fullscreen Toggle
- [x] Added fullscreen toggle with `Maximize2`/`Minimize2` icons; `isFullscreen` state changes modal CSS

### 12E · Frontend — "Restore Left" and "Restore Right" Actions
- [x] Restore buttons set `confirmRestore` state instead of calling `onRestore` directly
- [x] Confirmation overlay with Cancel / Restore buttons; Escape dismisses dialog first
- [x] After confirm → `onRestore(latex)` called → parent updates editor

### 12F · Frontend — HistoryPanel Tab in Optimize Page
- [x] Added collapsible "Version History" section to optimize page aside (toggle show/hide)
- [x] `VersionHistoryPanel` with `onRestore` / `onCompare` handlers wired up
- [x] On compare → opens `DiffViewerModal` with `checkpointA`/`checkpointB`
- [x] `historyRefreshKey` incremented on optimization completion to auto-refresh panel

### 12G · Tests
- [x] `backend/test/test_history_diff.py` (18 tests, all passing):
  - List/create/fetch/delete checkpoints for own resume
  - 404 for wrong resume_id, non-existent checkpoint, other user's checkpoint
  - Auth required for all endpoints

---

## Feature 13 — Project-Wide Search · P1 · S ✅ COMPLETED

**Goal:** Cmd+Shift+F opens a search modal that searches LaTeX content and title across ALL
user resumes using Postgres full-text search. Results show title, line number, snippet,
highlighted match. Clicking opens the resume with cursor at matching line.

### 13A · Backend — Search Endpoint
- [x] Add `GET /resumes/search` to `backend/app/api/resume_routes.py`:
  - Query params: `q: str` (required, min 2 chars), `limit: int = 20` (max 50)
  - Must add before `GET /resumes/{resume_id}` in router to avoid conflict with `{resume_id}` capture
  - Implementation:
    ```python
    from sqlalchemy import func, cast, Text

    async def search_resumes(q: str, limit: int, db: AsyncSession, user_id: str):
        # Postgres ILIKE search on title and latex_content
        # Return snippet with context around match
        stmt = (
            select(
                Resume.id,
                Resume.title,
                Resume.updated_at,
                # Extract snippet: find line containing match
            )
            .where(
                Resume.user_id == user_id,
                Resume.is_template == False,
                or_(
                    Resume.title.ilike(f"%{q}%"),
                    Resume.latex_content.ilike(f"%{q}%"),
                )
            )
            .order_by(Resume.updated_at.desc())
            .limit(limit)
        )
        results = await db.execute(stmt)
        resumes = results.fetchall()
        # For each resume, find line numbers with match and extract snippet
        output = []
        for resume in resumes:
            matches = extract_search_matches(resume.latex_content, q, context_lines=2)
            output.append({
                "resume_id": str(resume.id),
                "resume_title": resume.title,
                "updated_at": resume.updated_at,
                "matches": matches[:3],  # max 3 snippet matches per resume
            })
        return output
    ```
  - Helper `extract_search_matches(latex_content, query, context_lines=2) -> List[SearchMatch]`:
    - Split `latex_content` by `\n` to get lines
    - Find all lines (case-insensitive) containing `query`
    - For each match: `{ line_number, line_content, context_before, context_after, highlight_start, highlight_end }`
    - Return first 5 matching line numbers

  - Response schema:
    ```python
    class SearchMatch(BaseModel):
        line_number: int
        line_content: str
        context_before: List[str]  # 2 lines before
        context_after: List[str]   # 2 lines after
        highlight_start: int       # char offset in line_content
        highlight_end: int

    class ResumeSearchResult(BaseModel):
        resume_id: str
        resume_title: str
        updated_at: datetime
        matches: List[SearchMatch]

    class SearchResponse(BaseModel):
        results: List[ResumeSearchResult]
        total_resumes_matched: int
        query: str
    ```
  - Empty query (`q=""`) → return empty results (no search)
  - Minimum 2 chars: `q.strip()` length check → 422 if < 2

### 13B · Frontend — API Client
- [x] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  searchResumes(query: string, limit?: number): Promise<SearchResponse>
  ```
  - Interfaces: `SearchMatch`, `ResumeSearchResult`, `SearchResponse`

### 13C · Frontend — Search Modal Component
- [x] Create `frontend/src/components/ProjectSearchModal.tsx`:
  - Opens as a command-palette style modal (centered, `max-w-2xl`)
  - Search input at top with magnifying glass icon, auto-focused on open
  - Results list below with loading indicator
  - **Result item:**
    - Resume title (bold) + last edited date
    - Each snippet match: code block style (monospace), line number badge, highlighted query term
    - Highlight: wrap query text in `<mark className="bg-yellow-500/30 text-yellow-200">`
    - Max 3 snippet matches shown per resume; "+ N more" link if more exist
  - Debounce: 300ms after typing stops
  - Empty state: "No results for '{query}'" with icon
  - Clicking a result: close modal + navigate to `/workspace/{resume_id}/edit`
    + pass `?line={line_number}` query param to open editor at that line
  - Max height: `70vh` with scrollable results list
  - Keyboard: Up/Down arrows navigate results; Enter opens selected; Escape closes

### 13D · Frontend — Keyboard Shortcut (Cmd+Shift+F)
- [x] In `frontend/src/app/workspace/page.tsx`:
  - Add state: `searchOpen: boolean`
  - Register global `keydown` listener:
    ```typescript
    useEffect(() => {
      const handler = (e: KeyboardEvent) => {
        if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'f') {
          e.preventDefault()
          setSearchOpen(true)
        }
      }
      document.addEventListener('keydown', handler)
      return () => document.removeEventListener('keydown', handler)
    }, [])
    ```
  - Render `<ProjectSearchModal open={searchOpen} onClose={() => setSearchOpen(false)} />`
  - Also: add search icon button in workspace header (top-right)

### 13E · Frontend — Open Editor at Line
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Read `searchParams.get('line')` on mount
  - If present: after editor loads, call:
    ```typescript
    editorRef.current?.revealLineInCenter(lineNumber)
    editorRef.current?.setPosition({ lineNumber, column: 1 })
    ```
  - Clear the query param from URL after navigation (replace history state)

### 13F · Tests
- [x] `backend/test/test_search.py`:
  - `GET /resumes/search?q=foo` with 3 resumes where 1 matches → returns 1 result
  - Query too short (1 char) → 422
  - Query matches title only → match in result without latex snippet
  - Match in latex_content → correct line number in response
  - Results scoped to current user (cannot see other users' resumes)
  - `limit=5` → max 5 resumes returned

---

## Feature 14 — BibTeX Smart Import (DOI / arXiv) · P1 · M ✅ COMPLETED

**Goal:** In the editor's "References" sidebar tab, users paste a DOI or arXiv ID and get a
properly formatted BibTeX entry inserted at cursor. Supports batch import of multiple IDs.
Uses Crossref API (DOI) and arXiv Atom API (arXiv) — both free, no API key needed.

### 14A · Backend — References Fetch Endpoint
- [x] Create `backend/app/api/reference_routes.py`:
  ```python
  router = APIRouter(prefix="/references", tags=["references"])
  ```

  **`POST /references/fetch`**:
  - Body: `{ identifiers: List[str], source_hint?: str }` (max 20 identifiers)
  - For each identifier:
    - Detect type: DOI pattern `r"^10\.\d{4,}/"` or arXiv pattern `r"^\d{4}\.\d{4,}(v\d+)?$"`
    - Call appropriate fetcher (with 10s httpx timeout)
    - Return BibTeX string or error per identifier

  **`POST /references/detect`** (optional, for real-time identifier detection):
  - Accepts raw text (pasted URLs or IDs), extracts all DOIs and arXiv IDs
  - Returns detected identifiers with type labels

- [x] Add DOI fetcher using Crossref:
  ```python
  async def fetch_doi_bibtex(doi: str) -> str:
      url = f"https://api.crossref.org/works/{doi}/transform/application/x-bibtex"
      headers = {
          "User-Agent": "Latexy/1.0 (mailto:support@latexy.io; https://latexy.io)",
          # Crossref "polite pool" requires User-Agent with mailto or URL
      }
      async with httpx.AsyncClient() as client:
          response = await client.get(url, headers=headers, timeout=10.0)
          if response.status_code == 200:
              return response.text  # already BibTeX
          raise ValueError(f"DOI not found: {doi}")
  ```
  - Cache result: `cache_manager.set(f"bibtex:doi:{doi}", bibtex, ttl=86400 * 30)` (30 days — stable data)

- [x] Add arXiv fetcher:
  ```python
  async def fetch_arxiv_bibtex(arxiv_id: str) -> str:
      # arXiv Atom API returns structured metadata
      clean_id = arxiv_id.split("v")[0]  # strip version suffix
      url = f"https://export.arxiv.org/api/query?id_list={clean_id}"
      async with httpx.AsyncClient() as client:
          response = await client.get(url, timeout=10.0)
          # Parse Atom XML, extract: title, authors, year, doi (if any), abstract
          # Construct BibTeX manually:
          # @article{arxiv_{id},
          #   title = {Title Here},
          #   author = {Last1, First1 and Last2, First2},
          #   year = {2023},
          #   eprint = {2103.00020},
          #   archivePrefix = {arXiv},
          #   primaryClass = {cs.LG},
          # }
          return bibtex_string
  ```
  - Use `xml.etree.ElementTree` (stdlib) to parse Atom XML — no extra dependency
  - Cache with `ttl=86400 * 7` (7 days — arXiv entries don't change often)

- [x] Response schema:
  ```python
  class BibTeXEntry(BaseModel):
      identifier: str
      bibtex: Optional[str]  # None if fetch failed
      cite_key: str           # e.g. "Smith2023" or "arxiv_2103.00020"
      title: Optional[str]   # for display in UI
      authors: Optional[str] # for display
      year: Optional[int]
      error: Optional[str]   # if fetch failed
  ```

- [x] Register router in `backend/app/api/routes.py`

### 14B · Backend — Batch Import
- [x] In `POST /references/fetch`, batch logic:
  - Fire concurrent requests with `asyncio.gather()` (not sequential)
  - Enforce max 20 identifiers per request (Pydantic `max_length=20` on list field)
  - Return partial results (some succeed, some fail)
  - Total timeout: 30s across all concurrent fetches

### 14C · Frontend — API Client
- [x] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  fetchReferences(identifiers: string[]): Promise<BibTeXEntry[]>
  ```

### 14D · Frontend — References Panel Component
- [x] Create `frontend/src/components/ReferencesPanel.tsx`:
  - Rendered as a sidebar panel/tab in the LaTeX editor
  - **Input section:**
    - Textarea with placeholder: "Paste DOI(s) or arXiv ID(s), one per line\nExamples: 10.1145/3386569.3392408\n2103.00020"
    - "Fetch" button (primary) — disabled while loading
    - Auto-detect identifier type as user types: show "DOI" or "arXiv" badge per line
  - **Results section:**
    - Loading skeleton per identifier during fetch
    - Each result card:
      - Title (bold), authors (truncated), year
      - BibTeX preview in expandable `<pre>` block (collapsed by default, expand on click)
      - Cite key shown: `\cite{Smith2023}` with copy button
      - "Insert BibTeX" button → calls `onInsertBibTeX(entry.bibtex)` prop
      - Error state if fetch failed: "Not found — check the ID and try again"
    - "Insert All" button at bottom: inserts all successful BibTeX entries at once
  - **Props:**
    ```typescript
    {
      onInsertBibTeX: (bibtex: string) => void  // inserts at editor cursor
      onInsertCiteKey: (citeKey: string) => void // inserts \cite{key} at cursor
    }
    ```

### 14E · Frontend — Editor Integration
- [x] In `frontend/src/components/LaTeXEditor.tsx`:
  - Expose `insertAtCursor(text: string)` via `LaTeXEditorRef`:
    ```typescript
    insertAtCursor(text: string): void {
      const editor = editorRef.current
      const position = editor.getPosition()!
      editor.executeEdits('insert-bibtex', [{
        range: new monaco.Range(
          position.lineNumber, position.column,
          position.lineNumber, position.column
        ),
        text,
      }])
      editor.focus()
    }
    ```
  - This method is useful for BibTeX AND future features (snippet insert, package manager)

- [x] Wire `ReferencesPanel` in editor sidebar (tab system):
  - Add "References" tab to whatever sidebar tabs exist in the editor pages
  - Pass `onInsertBibTeX={(bibtex) => editorRef.current?.insertAtCursor(bibtex)}`
  - Pass `onInsertCiteKey={(key) => editorRef.current?.insertAtCursor(key)}`

### 14F · Tests
- [x] `backend/test/test_references.py` — 27 tests, all pass:
  - Known DOI (`10.1145/1327452.1327492`) → returns valid BibTeX with `@` entry
  - Known arXiv ID (`1706.03762`) → returns BibTeX for "Attention Is All You Need"
  - Invalid DOI → error in result (not 500)
  - Invalid arXiv ID → error in result
  - Batch of 3 IDs → 3 results (some may fail)
  - Cache: second call for same DOI uses cached result (mock httpx, verify no second call)
  - DOI with special chars → encoded properly in URL

---

## Feature 15 — Job Application Tracker · P1 · L ✅ COMPLETED

**Goal:** Kanban board at `/tracker` where users manage job applications linked to resume variants.
Cards show company logo, ATS score, status. Drag-and-drop between status columns.
New `job_applications` DB table with full CRUD API.

### 15A · Database Migration
- [ ] Create `backend/alembic/versions/0009_add_job_applications.py`:
  ```sql
  CREATE TYPE application_status AS ENUM (
    'applied', 'phone_screen', 'technical', 'onsite', 'offer', 'rejected', 'withdrawn'
  );

  CREATE TABLE job_applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    role_title TEXT NOT NULL,
    status application_status NOT NULL DEFAULT 'applied',
    resume_id UUID REFERENCES resumes(id) ON DELETE SET NULL,
    ats_score_at_submission FLOAT,
    job_description_text TEXT,
    job_url TEXT,
    company_logo_url TEXT,      -- cached from Clearbit
    notes TEXT,
    applied_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX idx_job_applications_user_id ON job_applications(user_id);
  CREATE INDEX idx_job_applications_status ON job_applications(status);
  CREATE INDEX idx_job_applications_resume_id ON job_applications(resume_id);
  ```

### 15B · Backend Model
- [ ] Add `JobApplication` SQLAlchemy model to `backend/app/database/models.py`:
  ```python
  class JobApplication(Base):
      __tablename__ = "job_applications"
      id: Mapped[uuid.UUID] = mapped_column(...)
      user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
      company_name: Mapped[str] = mapped_column(Text, nullable=False)
      role_title: Mapped[str] = mapped_column(Text, nullable=False)
      status: Mapped[str] = mapped_column(Text, default="applied")
      resume_id: Mapped[Optional[uuid.UUID]] = mapped_column(
          ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
      )
      ats_score_at_submission: Mapped[Optional[float]]
      job_description_text: Mapped[Optional[str]] = mapped_column(Text)
      job_url: Mapped[Optional[str]] = mapped_column(Text)
      company_logo_url: Mapped[Optional[str]] = mapped_column(Text)
      notes: Mapped[Optional[str]] = mapped_column(Text)
      applied_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, default=datetime.utcnow)
      updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, default=datetime.utcnow)
      created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, default=datetime.utcnow)
      # Relationships
      user: Mapped["User"] = relationship(back_populates="job_applications")
      resume: Mapped[Optional["Resume"]] = relationship()
  ```
- [ ] Add reverse relation on `User`: `job_applications: Mapped[List["JobApplication"]] = relationship(...)`

### 15C · Backend — Job Application Routes
- [ ] Create `backend/app/api/tracker_routes.py`:
  ```
  POST   /tracker/applications               — create application
  GET    /tracker/applications               — list all (grouped by status or flat)
  GET    /tracker/applications/{id}          — get single
  PUT    /tracker/applications/{id}          — update (status, notes, etc.)
  DELETE /tracker/applications/{id}          — delete
  PATCH  /tracker/applications/{id}/status   — quick status update (drag-drop)
  GET    /tracker/stats                      — aggregate statistics
  ```
  - All endpoints: `Depends(get_current_user_required)` — tracker is authenticated only
  - `POST /tracker/applications` body:
    ```python
    class CreateApplicationRequest(BaseModel):
        company_name: str = Field(..., max_length=200)
        role_title: str = Field(..., max_length=200)
        status: str = "applied"
        resume_id: Optional[str] = None
        job_description_text: Optional[str] = Field(None, max_length=20000)
        job_url: Optional[str] = Field(None, max_length=500)
        notes: Optional[str] = Field(None, max_length=5000)
        applied_at: Optional[datetime] = None  # defaults to now
    ```
  - On creation: if `company_name` given, attempt Clearbit logo fetch (async, non-blocking):
    ```python
    logo_url = await fetch_clearbit_logo(company_name)  # GET https://logo.clearbit.com/{domain}
    # Uses DuckDuckGo or simple domain guessing: company_name.lower().replace(" ", "") + ".com"
    ```
  - If `resume_id` given: load ATS score from latest optimization → store as `ats_score_at_submission`

  - `GET /tracker/applications` response:
    - Query param: `?status=applied` (filter by status) or omit for all
    - Returns grouped: `{ by_status: { applied: [...], phone_screen: [...], ... } }`
    - OR `?flat=true` for a simple list ordered by `applied_at DESC`

  - `GET /tracker/stats` — no params needed:
    ```python
    class TrackerStats(BaseModel):
        total_applications: int
        by_status: Dict[str, int]          # { "applied": 5, "rejected": 2, ... }
        avg_ats_score: Optional[float]     # across all submitted
        applications_this_week: int
        applications_this_month: int
        response_rate: float               # (phone_screen + technical + onsite + offer) / total
        offer_rate: float                  # offer / total
    ```
- [ ] Register router in `backend/app/api/routes.py`

### 15D · Frontend — API Client
- [ ] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  // Types
  interface JobApplication { id, company_name, role_title, status, resume_id?, ats_score_at_submission?, job_url?, company_logo_url?, notes?, applied_at, updated_at }
  interface TrackerStats { total_applications, by_status, avg_ats_score?, applications_this_week, response_rate, offer_rate }

  // Methods
  createApplication(body: CreateApplicationRequest): Promise<JobApplication>
  listApplications(status?: string): Promise<{ by_status: Record<string, JobApplication[]> }>
  getApplication(id: string): Promise<JobApplication>
  updateApplication(id: string, body: Partial<JobApplication>): Promise<JobApplication>
  deleteApplication(id: string): Promise<void>
  updateApplicationStatus(id: string, status: string): Promise<JobApplication>
  getTrackerStats(): Promise<TrackerStats>
  ```

### 15E · Frontend — Tracker Page (Kanban)
- [ ] Create `frontend/src/app/tracker/page.tsx`:
  - Layout: full-width board with horizontal scroll for columns
  - **Status columns (7):** Applied · Phone Screen · Technical · On-Site · Offer · Rejected · Withdrawn
    - Column headers: status name + count badge
    - Column color coding: Applied(blue), PhoneScreen(violet), Technical(amber), OnSite(orange), Offer(emerald), Rejected(rose), Withdrawn(zinc)
  - **Cards:** Each `JobApplication` shown as a card with:
    - Company logo (img from `company_logo_url`) or fallback initials avatar
    - Company name + role title
    - "N days ago" (relative from `applied_at`)
    - ATS score badge (if `ats_score_at_submission` set) — color coded like P0 Feature 6
    - Linked resume name (fetched from resume list on mount) — click to open
    - Overflow menu: Edit, View Details, Delete
  - **Drag-and-drop:** Install `@dnd-kit/core` and `@dnd-kit/sortable`:
    - `pnpm add @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities`
    - `DndContext` wraps the board
    - Each column is a `SortableContext` (vertical list)
    - On drag end: `PATCH /tracker/applications/{id}/status` with new status
    - Optimistic update: move card immediately, revert on API error
  - **"Add Application" button** (top right): opens `AddApplicationModal`

### 15F · Frontend — Add Application Modal
- [ ] Create `frontend/src/components/AddApplicationModal.tsx`:
  - Fields:
    - Company name (required, text)
    - Role title (required, text)
    - Status (select, default "applied")
    - Job URL (optional, URL input)
    - Link resume (optional, dropdown of user's resumes)
    - Job description (optional, expandable textarea)
    - Notes (optional, textarea)
    - Applied date (optional, date picker — defaults to today)
  - "Add Application" submit button → `apiClient.createApplication()`
  - After submit: add card to board in correct column + show success toast
  - "Add to Tracker" deep link from workspace card: pre-fill `resume_id` + ATS score

### 15G · Frontend — Statistics Dashboard
- [ ] Add stats bar at top of tracker page:
  - "Total: 12 applications" · "Response rate: 42%" · "Avg ATS: 74"
  - Small sparkline or progress bar showing funnel (Applied → Phone → Technical → Offer)
  - Fetched from `GET /tracker/stats`

### 15H · Frontend — Workspace Integration
- [ ] In workspace resume cards: add "Add to Tracker" option in actions dropdown
  - Opens `AddApplicationModal` pre-filled with `resume_id`
  - If resume has recent optimization: pre-fill `ats_score_at_submission`

### 15I · Tests
- [ ] `backend/test/test_tracker.py`:
  - Create application → 201, returns correct fields
  - Update status → reflects in GET list
  - Stats: `response_rate = 0` when all applications are `applied`
  - Delete removes from list
  - Cannot access another user's applications → 404
  - `resume_id` referencing non-owned resume → 400 or 403
  - Stats with multiple applications in various statuses → correct counts

---

## Feature 16 — LinkedIn Profile Import (Structured) · P1 · M ✅ COMPLETED

**Goal:** LinkedIn PDF exports have a predictable structure. Add a `source_hint=linkedin` mode
to the existing `/formats/upload` endpoint that uses a LinkedIn-specific LLM prompt for higher
accuracy parsing. Add LinkedIn import CTA with step-by-step instructions.

### 16A · Backend — LinkedIn Parser Variant
- [x] In `backend/app/services/document_converter_service.py`, add LinkedIn-specific prompt:
  ```python
  LINKEDIN_SYSTEM_PROMPT = """
  You are parsing a LinkedIn profile PDF export. LinkedIn PDFs follow a strict structure:
  - Name and headline at top
  - "About" section (summary)
  - "Experience" section: each entry has Company, Title, Dates (Month Year – Month Year or Present), Location, Description bullets
  - "Education" section: Institution, Degree, Field, Dates, Activities
  - "Skills" section: list of skills with endorsement counts
  - "Certifications": Name, Issuing org, Date
  - "Languages": Language, Proficiency level
  - "Recommendations": ignore these (not part of resume)
  - "Honors & Awards", "Publications", "Projects" (if present)

  Map these to LaTeX resume sections:
  - Experience → \\section{Experience} with \\resumeSubheading{Company}{Dates}{Title}{Location} (or equivalent)
  - Education → \\section{Education} similarly
  - Skills → \\section{Skills} as comma-separated or grouped list
  - Certifications → \\section{Certifications}
  - Languages → add to Skills section

  IMPORTANT:
  - Preserve all dates exactly as written
  - Keep all bullet points verbatim (improve formatting but not content)
  - Use the same LaTeX template class as the document being edited
  """
  ```
- [x] Add a `source_hint` parameter to the upload/convert pipeline:
  - `build_conversion_prompt(structure, source_format, source_hint=None)` added
  - `source_hint="linkedin"` selects `LINKEDIN_SYSTEM_PROMPT`; anything else uses default
- [x] In `backend/app/api/format_routes.py`, `POST /formats/upload`:
  - Accept optional `source_hint: str = Form(default=None)` field
  - Pass to `submit_document_conversion()` → `convert_document_task` → `build_conversion_prompt`

### 16B · Frontend — LinkedIn Import UI
- [x] In `frontend/src/app/workspace/new/page.tsx` (template gallery page):
  - Added `'linkedin'` mode; 3-column toggle grid (Template / Import File / Import from LinkedIn)
  - Step-by-step instructions panel with sky-blue accent (numbered steps 1–4)
  - `MultiFormatUpload` rendered with `sourceHint="linkedin"`
  - Sky-blue Linkedin icon + border on selected state

### 16C · Frontend — API Client Update
- [x] In `frontend/src/lib/api-client.ts`, `uploadForConversion(file, sourceHint?)`:
  - Optional `sourceHint` appended as `source_hint` form field when present
- [x] `useFormatConversion.ts` — `startConversion(file, sourceHint?)` threads hint to API client
- [x] `MultiFormatUpload.tsx` — `sourceHint?` prop passed through to `startConversion`

### 16D · Tests
- [x] `backend/test/test_linkedin_import.py` — 14 tests, all passing:
  - `source_hint=linkedin` → uses `LINKEDIN_SYSTEM_PROMPT`
  - `source_hint=resume` / `null` / unknown → uses default prompt
  - Upload endpoint passes `source_hint` to worker
  - LaTeX files are still direct passthrough even with `source_hint=linkedin`
  - Converter worker `.run()` passes `source_hint` to `build_conversion_prompt`

---

## Feature 17 — Interview Question Generator · P1 · M

**Goal:** After optimizing for a job, generate role-specific interview questions with STAR hints.
New Celery task on `llm` queue. Questions saved in DB alongside the resume. "Interview Prep"
tab in edit page sidebar.

### 17A · Database Migration
- [ ] Create `backend/alembic/versions/0010_add_interview_prep.py`:
  ```sql
  CREATE TABLE interview_prep (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    resume_id UUID NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    job_description TEXT,
    company_name TEXT,
    role_title TEXT,
    questions JSONB NOT NULL DEFAULT '[]',
    -- questions format: [{
    --   category: "behavioral"|"technical"|"motivational"|"difficult",
    --   question: "...",
    --   what_interviewer_assesses: "...",
    --   star_hint: "Situation: ... | Task: ... | Action: ... | Result: ..."
    -- }]
    generation_job_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX idx_interview_prep_resume ON interview_prep(resume_id);
  CREATE INDEX idx_interview_prep_user ON interview_prep(user_id);
  ```

### 17B · Backend Model
- [ ] Add `InterviewPrep` SQLAlchemy model to `backend/app/database/models.py`:
  ```python
  class InterviewPrep(Base):
      __tablename__ = "interview_prep"
      id, user_id, resume_id, job_description, company_name, role_title
      questions: Mapped[List[Dict]] = mapped_column(JSONB, default=list)
      generation_job_id, created_at, updated_at
      resume: Mapped["Resume"] = relationship()
  ```

### 17C · Interview Prep Worker
- [ ] Create `backend/app/workers/interview_prep_worker.py`:
  - Task `generate_interview_prep_task` on `llm` queue (no new queue needed)
  - System prompt:
    ```
    You are a senior hiring manager and interview coach. Generate realistic interview questions
    for the role based on the candidate's resume and job description.

    Generate EXACTLY:
    - 5 behavioral questions (STAR format expected): based on specific resume experiences
    - 5 technical questions: based on skills/technologies listed on the resume
    - 3 motivational questions: about this specific company/role
    - 2 difficult questions: about gaps, short tenures, or unusual career moves

    For each question, provide:
    - category: "behavioral" | "technical" | "motivational" | "difficult"
    - question: the actual interview question
    - what_interviewer_assesses: 1 sentence on what they're really testing
    - star_hint: brief S/T/A/R framework guide for answering (behavioral only; others can be null)

    Output as valid JSON array. No markdown. No explanations. Only the JSON.
    ```
  - Event flow (same as `llm_worker.py`):
    1. `job.started` → `job.progress` 5%
    2. Build prompt from resume LaTeX + JD
    3. Non-streaming JSON call to OpenAI (gpt-4o-mini, `response_format={"type": "json_object"}`)
    4. Parse JSON → save to `interview_prep.questions` JSONB
    5. `job.completed`
  - Helper: `submit_interview_prep_generation(resume_id, user_id, job_description, ...)`

### 17D · Interview Prep Routes
- [ ] Create `backend/app/api/interview_routes.py`:
  ```
  POST /interview-prep/generate    — starts generation task, returns { job_id, prep_id }
  GET  /interview-prep/{id}        — get questions for a prep session
  GET  /resumes/{resume_id}/interview-prep  — list all prep sessions for a resume
  DELETE /interview-prep/{id}      — delete prep session
  ```
  - Body for generate: `{ resume_id, job_description?, company_name?, role_title? }`
  - Auth required
  - Verify resume ownership before generating
- [ ] Register router in `backend/app/api/routes.py`

### 17E · Frontend — API Client
- [ ] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  generateInterviewPrep(body: GenerateInterviewPrepRequest): Promise<{ job_id: string; prep_id: string }>
  getInterviewPrep(prepId: string): Promise<InterviewPrepResponse>
  listInterviewPrep(resumeId: string): Promise<InterviewPrepResponse[]>
  deleteInterviewPrep(prepId: string): Promise<void>
  ```

### 17F · Frontend — Interview Prep Panel
- [ ] Create `frontend/src/components/InterviewPrepPanel.tsx`:
  - Sidebar panel tab (or slide-out panel) with:
    - "Generate Interview Questions" button
    - Job description input (optional — uses existing resume JD if available)
    - Company/role inputs (optional — helps personalize)
    - Progress indicator while job is running (reuse `useJobStream` hook)
  - **Questions view:**
    - Tabs: "Behavioral (5)" | "Technical (5)" | "Motivational (3)" | "Difficult (2)"
    - Each question card:
      - Question text (bold)
      - "What they're assessing" in italic below
      - Expandable "STAR hint" for behavioral questions (collapsed by default)
      - "Add notes" area (local textarea, not saved — session only for privacy)
    - Previous sessions: dropdown to switch between generated sets
    - "Regenerate" button to generate a new set
  - When no questions yet: empty state with "Generate Questions" CTA

### 17G · Tests
- [ ] `backend/test/test_interview_prep.py`:
  - POST generate → creates `interview_prep` record, returns job_id
  - GET → returns correct questions after job completes (mock LLM response)
  - Questions JSON has expected structure (behavioral, technical, motivational, difficult)
  - Cannot access another user's prep → 404
  - List returns prep sessions for a resume in descending order

---

## Feature 18 — Multi-Dimensional Score Card · P1 · M ✅ COMPLETED

**Goal:** Extend ATS deep analysis with additional scoring dimensions: Grammar, Bullet Clarity,
Section Completeness, Page Density, Keyword Density. Surface as a radar/spider chart in
`DeepAnalysisPanel`. Extends existing `ats_scoring_service.py`.

### 18A · Backend — Additional Scoring Dimensions
- [x] In `backend/app/services/ats_scoring_service.py`, add new dimension methods:

  **Grammar Score (0–100):**
  ```python
  def _score_grammar(self, text: str) -> float:
      # Rule-based checks (no LLM needed):
      issues = 0
      # 1. Sentence fragments: lines with verbs but no subject (heuristic)
      # 2. Starting bullet with lowercase letter (resume convention violation)
      # 3. Inconsistent tense: past-tense verbs in bullets then present tense → flag
      # 4. Double spaces, trailing spaces, double periods
      # Use regex patterns for each check
      # Score: max(0, 100 - issues * 10)
      return min(100.0, max(0.0, 100.0 - issues * 8))
  ```

  **Bullet Clarity Score (0–100):**
  ```python
  def _score_bullet_clarity(self, text: str) -> float:
      # Extract all \item content lines
      bullet_lines = re.findall(r'\\item\s+(.+?)(?=\\item|\\end\{)', text, re.DOTALL)
      scores = []
      for bullet in bullet_lines:
          score = 0
          # +30 if starts with action verb (from ACTION_VERBS list)
          # +30 if contains a number/percentage (quantified impact)
          # +20 if length is 80-160 chars (appropriate length)
          # +20 if no passive voice patterns ("was improved by", "were responsible for")
          scores.append(score)
      return sum(scores) / len(scores) if scores else 0.0
  ```

  **Section Completeness Score (0–100):**
  ```python
  def _score_section_completeness(self, latex_content: str) -> float:
      # Extract section names from \section{...} commands
      sections = re.findall(r'\\section\{([^}]+)\}', latex_content, re.IGNORECASE)
      sections_lower = [s.lower() for s in sections]
      required = ['experience', 'work', 'education', 'skills', 'contact']
      recommended = ['summary', 'objective', 'projects', 'certifications', 'publications']
      required_found = sum(1 for r in required if any(r in s for s in sections_lower))
      recommended_found = sum(1 for r in recommended if any(r in s for s in sections_lower))
      return (required_found / len(required)) * 70 + (recommended_found / len(recommended)) * 30
  ```

  **Page Density Score (0–100):**
  ```python
  def _score_page_density(self, latex_content: str) -> float:
      # Target: 600-900 words for 1-page resume; 1100-1500 for 2-page
      # Extract prose text (strip LaTeX commands)
      text = self._extract_plain_text(latex_content)
      word_count = len(text.split())
      # Optimal single-page: 600-900 words → score 90-100
      # Below 400: too sparse → score 50
      # Above 1200 (for 1-page): too dense → score 40
      if 600 <= word_count <= 900: return 95.0
      if 400 <= word_count < 600: return 70.0
      if 900 < word_count <= 1100: return 80.0
      if word_count < 400: return 50.0
      return max(30.0, 80.0 - (word_count - 1100) * 0.05)
  ```

  **Keyword Density Score (0–100):**
  ```python
  def _score_keyword_density(self, text: str, job_description: Optional[str]) -> float:
      # Only meaningful with a JD; without JD → return 50 (neutral)
      if not job_description:
          return 50.0
      # Tokenize JD and resume
      # Find JD keywords (top 30 by TF ignoring stopwords)
      # Count how many appear in resume text
      # Score: (matched / total_jd_keywords) * 100
      ...
  ```

- [x] Update `score_resume()` in `ats_scoring_service.py` to compute all 5 new dimensions
- [x] Update `ATSScoreResult` dataclass to include new dimension scores:
  ```python
  @dataclass
  class ATSScoreResult:
      ...
      multi_dim_scores: Optional[Dict[str, float]] = None
      # Keys: "grammar", "bullet_clarity", "section_completeness", "page_density", "keyword_density"
  ```

### 18B · Backend — Event Schema Update
- [x] In `backend/app/models/event_schemas.py`:
  - Add `multi_dim_scores: Optional[Dict[str, float]] = None` to `ATSDeepCompleteEvent`
- [x] `ats.deep_complete` WebSocket event includes `multi_dim_scores` (computed via `score_resume()` in `_async_deep_analyze`)

### 18C · Frontend — Radar/Spider Chart Component
- [x] Hand-rolled SVG pentagon radar chart — no recharts dep needed
- [x] Created `frontend/src/components/ats/ATSRadarChart.tsx`

### 18D · Frontend — DeepAnalysisPanel Update
- [x] In `frontend/src/components/ats/DeepAnalysisPanel.tsx`:
  - "Score Breakdown" card with radar chart + 5 dimension progress bars
  - Shown when `multi_dim_scores` is available
  - Existing sections unchanged below

### 18E · Tests
- [x] `backend/test/test_multi_dim_score.py` (17 tests, all passing):
  - `_score_bullet_clarity()` on resume with quantified action-verb bullets → score > 70 ✓
  - `_score_bullet_clarity()` on resume with passive-voice bullets → score < 50 ✓
  - `_score_grammar()` on resume with consistent tense → high score ✓
  - `_score_page_density()` at 750 words → score > 90 ✓
  - Full `score_resume()` returns `multi_dim_scores` dict with all 5 keys ✓

---

## Feature 19 — Email Notifications · P1 · S

**Goal:** Implement the stub `email_worker.py`. Send job completion emails to opted-in users.
Weekly digest via Celery Beat. Notification preferences in settings. Uses Resend (primary) or
any SMTP provider via settings.

### 19A · Config — Email Settings
- [ ] Add to `backend/app/core/config.py`:
  ```python
  # Email
  EMAIL_PROVIDER: str = "resend"     # "resend" | "sendgrid" | "smtp"
  RESEND_API_KEY: Optional[str] = None
  SENDGRID_API_KEY: Optional[str] = None
  SMTP_HOST: Optional[str] = None
  SMTP_PORT: int = 587
  SMTP_USER: Optional[str] = None
  SMTP_PASSWORD: Optional[str] = None
  EMAIL_FROM: str = "noreply@latexy.io"
  EMAIL_FROM_NAME: str = "Latexy"
  EMAIL_ENABLED: bool = False  # master toggle — default False until configured
  ```
  - Guard all email sends: `if not settings.EMAIL_ENABLED: return` (graceful no-op)

### 19B · Backend — Email Service
- [ ] Create `backend/app/services/email_service.py`:
  ```python
  class EmailService:
      async def send_email(
          self,
          to: str,
          subject: str,
          html_body: str,
          text_body: Optional[str] = None,
      ) -> bool:
          """Returns True if sent, False if skipped (disabled/no key)."""
          if not settings.EMAIL_ENABLED:
              logger.debug(f"Email disabled, skipping: {subject} → {to}")
              return False
          if settings.EMAIL_PROVIDER == "resend":
              return await self._send_via_resend(to, subject, html_body, text_body)
          elif settings.EMAIL_PROVIDER == "smtp":
              return await self._send_via_smtp(to, subject, html_body, text_body)
          return False

      async def _send_via_resend(self, ...) -> bool:
          # POST https://api.resend.com/emails with bearer token
          import httpx
          ...
  ```
- [ ] Add `resend` to `backend/requirements.txt`: `resend>=2.0.0` OR just use `httpx` directly (simpler)
  - Using plain `httpx` avoids the dependency

### 19C · Backend — Email Templates
- [ ] Create `backend/app/templates/email/` directory:
  - `job_completed.html` — "Your {job_type} is complete" with link to result
  - `optimization_complete.html` — "Your resume has been optimized" with ATS score summary
  - `weekly_digest.html` — weekly summary with score trends
  - Keep templates simple (inline CSS only — email clients don't support external stylesheets)
  - Plain text fallback for each

### 19D · Backend — Email Worker Implementation
- [ ] Replace stub in `backend/app/workers/email_worker.py`:
  ```python
  @celery_app.task(name="send_job_completion_email", queue="email")
  def send_job_completion_email(
      user_id: str,
      job_type: str,         # "latex_compilation" | "llm_optimization"
      job_id: str,
      result_summary: Dict,  # ats_score, pdf_url, etc.
  ) -> None:
      # 1. Look up user email and notification preferences in DB
      # 2. If user has email notifications disabled → return
      # 3. Build email body from template
      # 4. Call email_service.send_email(...)
  ```

  ```python
  @celery_app.task(name="send_weekly_digest", queue="email")
  def send_weekly_digest(user_id: str) -> None:
      # 1. Fetch user's last 7 days of activity from usage_analytics
      # 2. Get all resume ATS scores (latest per resume)
      # 3. Build weekly summary HTML
      # 4. Send email
  ```

### 19E · Backend — Dispatch from Workers
- [ ] In `backend/app/workers/latex_worker.py` (after job completion):
  ```python
  # After successful compilation, dispatch email notification
  if user_id:
      send_job_completion_email.apply_async(
          args=[user_id, "latex_compilation", job_id, {"pdf_job_id": job_id}],
          queue="email",
          countdown=2,  # 2s delay so job result is in Redis first
      )
  ```
- [ ] Same dispatch in `orchestrator.py` after combined job completes

### 19F · Backend — Notification Preferences Column
- [ ] Create `backend/alembic/versions/0011_add_notification_prefs.py`:
  ```sql
  ALTER TABLE users ADD COLUMN email_notifications JSONB DEFAULT '{
    "job_completed": true,
    "weekly_digest": false
  }'::jsonb;
  ```
- [ ] Update `User` model with `email_notifications: Mapped[Optional[Dict]] = mapped_column(JSONB)`
- [ ] Add `GET /settings/notifications` and `PUT /settings/notifications` endpoints to a new or existing settings route file

### 19G · Backend — Celery Beat for Weekly Digest
- [ ] In `backend/app/core/celery_app.py`, add Beat schedule:
  ```python
  app.conf.beat_schedule = {
      "weekly-digest-monday-9am": {
          "task": "send_weekly_digest_to_all",
          "schedule": crontab(hour=9, minute=0, day_of_week="monday"),
          # Uses UTC — frontend displays in user's local time
      },
  }
  ```
- [ ] Create `backend/app/workers/email_worker.py::send_weekly_digest_to_all()` task:
  - Queries all users with `email_notifications.weekly_digest = true`
  - Fires individual `send_weekly_digest` subtask per user (fan-out)

### 19H · Frontend — Notification Preferences
- [ ] In `frontend/src/app/settings/page.tsx` (or create settings page if it doesn't exist):
  - "Email Notifications" section:
    - Toggle: "Job completion emails" (default: on)
    - Toggle: "Weekly digest" (default: off)
    - "Save preferences" button → `PUT /settings/notifications`

### 19I · Tests
- [ ] `backend/test/test_email_notifications.py`:
  - `send_job_completion_email` with `EMAIL_ENABLED=False` → no HTTP call made (mock)
  - `send_job_completion_email` with `EMAIL_ENABLED=True` + valid API key → sends HTTP request to Resend
  - User with `email_notifications.job_completed = false` → task returns without sending
  - `send_weekly_digest_to_all` queries only users who opted in

---

## Feature 20 — Font & Color Visual Editor · P1 · M

**Goal:** "Design" panel in editor sidebar with font picker, accent color picker, font size
radio, and margin slider. Each change generates correct LaTeX preamble modifications and
triggers auto-compile for instant preview. Replaces manual preamble editing for styling.

### 20A · Backend — No New Endpoints Needed
- The font/color editor is entirely client-side. It reads and writes the Monaco editor content
  directly (preamble manipulation). No backend changes required.
- Exception: store design preferences in `resume.metadata`:
  - `PATCH /resumes/{id}/settings` (from Feature 9) already handles `metadata` updates
  - The visual editor reads current values from parsed LaTeX preamble on mount

### 20B · Backend — Font/Color Reference Data
- [ ] Create `backend/app/data/latex_fonts.json` (or in frontend):
  - List of 30 LaTeX fonts with correct `\usepackage{}` declarations:
    ```json
    [
      { "name": "Computer Modern", "package": null, "command": null, "preview": "CMU Serif" },
      { "name": "Times New Roman", "package": "mathptmx", "command": null },
      { "name": "Palatino", "package": "palatino", "command": null },
      { "name": "Helvetica", "package": "helvet", "command": "\\renewcommand{\\familydefault}{\\sfdefault}" },
      { "name": "Latin Modern", "package": "lmodern", "command": null },
      { "name": "Garamond", "package": "garamondx", "command": null },
      { "name": "Charter", "package": "charter", "command": null },
      { "name": "Source Code Pro", "package": "sourcecodepro", "command": null, "type": "monospace" },
      ...
    ]
    ```
  - Actually simpler: hardcode in the frontend component (no backend endpoint needed)

### 20C · Frontend — LaTeX Preamble Parser/Modifier
- [ ] Create `frontend/src/lib/latex-preamble.ts`:
  ```typescript
  // Utilities for reading/writing common preamble settings

  export function extractFontFromPreamble(latex: string): string {
    // Look for \usepackage{times}, \usepackage{palatino}, etc.
    const match = latex.match(/\\usepackage\{(times|palatino|helvet|lmodern|...)\}/)
    return match?.[1] ?? 'default'
  }

  export function setFontInPreamble(latex: string, fontPackage: string | null, fontCommand: string | null): string {
    // Remove existing font packages, add new one
    // Insert after \documentclass line or before \begin{document}
    ...
  }

  export function extractAccentColorFromPreamble(latex: string): string | null {
    // Look for \definecolor{accent}{HTML}{RRGGBB}
    const match = latex.match(/\\definecolor\{accent\}\{HTML\}\{([A-Fa-f0-9]{6})\}/)
    return match?.[1] ?? null
  }

  export function setAccentColorInPreamble(latex: string, hexColor: string): string {
    // Replace \definecolor{accent}{HTML}{...} or add it if not present
    // Must be in preamble (before \begin{document})
    const pattern = /\\definecolor\{accent\}\{HTML\}\{[A-Fa-f0-9]{6}\}/
    const newDef = `\\definecolor{accent}{HTML}{${hexColor}}`
    if (pattern.test(latex)) return latex.replace(pattern, newDef)
    // Add before \begin{document}
    return latex.replace(/(\\begin\{document\})/, `${newDef}\n$1`)
  }

  export function extractFontSizeFromPreamble(latex: string): '10pt' | '11pt' | '12pt' {
    const match = latex.match(/\\documentclass\[([^\]]*)\]/)
    if (!match) return '11pt'
    const opts = match[1].split(',').map(s => s.trim())
    return (opts.find(o => /^\d+pt$/.test(o)) as any) ?? '11pt'
  }

  export function setFontSizeInPreamble(latex: string, size: '10pt' | '11pt' | '12pt'): string {
    // Replace existing pt in \documentclass[..., 11pt, ...]{...}
    ...
  }

  export function extractMarginsFromPreamble(latex: string): string {
    // Extract from \geometry{margin=...} or \geometry{left=..., right=..., top=..., bottom=...}
    ...
  }

  export function setMarginsInPreamble(latex: string, margin: string): string {
    // margin like "0.5in" | "0.75in" | "1in"
    const pattern = /\\geometry\{[^}]*\}/
    const newGeo = `\\geometry{margin=${margin}}`
    if (pattern.test(latex)) return latex.replace(pattern, newGeo)
    return latex.replace(/(\\begin\{document\})/, `\\geometry{margin=${margin}}\n$1`)
  }
  ```

### 20D · Frontend — DesignPanel Component
- [ ] Create `frontend/src/components/DesignPanel.tsx`:
  - Props:
    ```typescript
    {
      currentLatex: string
      onPreambleChange: (newLatex: string) => void  // called when any design value changes
      onTriggerCompile?: () => void                  // called after change if auto-compile on
    }
    ```
  - **Font Picker section:**
    - Label: "Font Family"
    - Dropdown with 30 font options (or grid of font name chips)
    - Current font detected from `extractFontFromPreamble(currentLatex)` on mount
    - On change: `setFontInPreamble(currentLatex, font.package, font.command)` → `onPreambleChange()`
    - Font preview: each option shows the font name rendered in itself (CSS font-family)
      - For LaTeX fonts, use approximate web font equivalents for preview only
  - **Accent Color Picker section:**
    - Label: "Accent Color"
    - Color swatch grid: 12 preset colors + "Custom" button
    - Current color from `extractAccentColorFromPreamble(currentLatex)` → highlight active swatch
    - Custom: `<input type="color">` HTML color picker
    - On change: `setAccentColorInPreamble(currentLatex, hexColor)` → `onPreambleChange()`
    - Note: only affects templates that use `\definecolor{accent}{...}` — show hint if not found
  - **Font Size section:**
    - Label: "Base Font Size"
    - 3-option radio: 10pt | 11pt (default) | 12pt
    - Current from `extractFontSizeFromPreamble(currentLatex)`
    - On change: `setFontSizeInPreamble(...)` → `onPreambleChange()`
  - **Margins section:**
    - Label: "Margins"
    - Slider or 3-option radio: Tight (0.5in) | Normal (0.75in) | Spacious (1in)
    - Current from `extractMarginsFromPreamble(currentLatex)` → nearest preset
    - On change: `setMarginsInPreamble(...)` → `onPreambleChange()`
  - **"Reset to Defaults" button:**
    - Resets all values to `11pt`, no custom font, no accent color, `0.75in` margins
    - Confirmation: "This will remove your custom styling. Continue?"
  - **Auto-compile on change:** call `onTriggerCompile()` after each design change
    (if auto-compile is enabled in parent page)

### 20E · Frontend — Integration in Edit/Optimize Pages
- [ ] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Add "Design" tab to sidebar (alongside whatever existing sidebar tabs there are)
  - `onPreambleChange` handler: `editorRef.current?.setValue(newLatex)` + `apiClient.updateResume()`
  - Pass `currentLatex={editorContent}` (live Monaco content, not saved content)
  - Pass `onTriggerCompile={autoCompileEnabled ? triggerCompile : undefined}`

### 20F · Tests
- [ ] `frontend` — unit tests for `latex-preamble.ts` utilities:
  - `extractFontSizeFromPreamble('\\documentclass[11pt]{article}')` → `'11pt'`
  - `setAccentColorInPreamble(latex, 'FF6B6B')` → inserts correct `\definecolor` in preamble
  - `setMarginsInPreamble(latex, '0.5in')` → updates/inserts `\geometry{margin=0.5in}`
  - Idempotent: calling twice doesn't add duplicate declarations

---

## Feature 21 — Developer Public API · P1 · M

**Goal:** Let third-party developers call Latexy's core capabilities (compile, optimize, ATS score,
export) via API keys with `lx_sk_` prefix. Rate-limited per plan. Separate from BYOK LLM keys.
Enables agency/platform integrations.

### 21A · Database Migration — Developer API Keys
- [ ] Create `backend/alembic/versions/0012_add_developer_api_keys.py`:
  ```sql
  CREATE TABLE developer_api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash TEXT UNIQUE NOT NULL,    -- sha256(full_key), stored for lookup
    key_prefix TEXT NOT NULL,         -- first 12 chars of key for display (e.g. lx_sk_abc123)
    name TEXT NOT NULL,               -- user-given label: "My App", "Production Key"
    last_used_at TIMESTAMPTZ,
    request_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    scopes TEXT[] DEFAULT '{"compile","optimize","ats","export"}',
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX idx_dev_api_keys_user ON developer_api_keys(user_id);
  CREATE UNIQUE INDEX idx_dev_api_keys_hash ON developer_api_keys(key_hash);
  ```
  - Key is NEVER stored in plaintext — only the sha256 hash
  - `key_prefix` shown in UI to help user identify which key (lx_sk_Ab3d...)

### 21B · Backend Model
- [ ] Add `DeveloperAPIKey` SQLAlchemy model to `backend/app/database/models.py`
- [ ] Add reverse relation on `User`: `developer_api_keys: Mapped[List["DeveloperAPIKey"]] = relationship(...)`

### 21C · Backend — API Key Service
- [ ] Create `backend/app/services/developer_key_service.py`:
  ```python
  import hashlib, secrets

  def generate_api_key() -> tuple[str, str, str]:
      """Returns (full_key, key_hash, key_prefix)"""
      random_part = secrets.token_urlsafe(32)   # 43-char URL-safe string
      full_key = f"lx_sk_{random_part}"
      key_hash = hashlib.sha256(full_key.encode()).hexdigest()
      key_prefix = full_key[:12]                # "lx_sk_" + 6 chars of random
      return full_key, key_hash, key_prefix

  async def verify_api_key(key: str, db: AsyncSession) -> Optional[DeveloperAPIKey]:
      """Verify a key and return the key record (increments request_count)."""
      if not key.startswith("lx_sk_"):
          return None
      key_hash = hashlib.sha256(key.encode()).hexdigest()
      stmt = select(DeveloperAPIKey).where(
          DeveloperAPIKey.key_hash == key_hash,
          DeveloperAPIKey.is_active == True,
      )
      result = await db.execute(stmt)
      api_key = result.scalar_one_or_none()
      if api_key:
          # Update last_used_at and increment counter
          api_key.last_used_at = datetime.utcnow()
          api_key.request_count += 1
          await db.commit()
      return api_key
  ```

### 21D · Backend — API Key Management Routes
- [ ] Create `backend/app/api/developer_routes.py`:
  ```
  GET    /developer/keys          — list all keys (shows prefix, name, stats; never full key)
  POST   /developer/keys          — create new key (returns full key ONCE in response)
  DELETE /developer/keys/{id}     — revoke key
  PATCH  /developer/keys/{id}     — rename key
  ```
  - `POST /developer/keys` body: `{ name: str }` (max 100 chars)
  - Response includes `full_key` ONCE — after that, only `key_prefix` is visible
  - Show warning: "Copy this key now. It will never be shown again."
  - Max keys per user: 5 (enforce in endpoint, return 400 if exceeded)

### 21E · Backend — API Key Auth Middleware
- [ ] In `backend/app/middleware/auth_middleware.py`:
  - Add `get_api_key_user` dependency:
    ```python
    async def get_api_key_user(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> Optional[str]:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer lx_sk_"):
            key = auth[7:]  # strip "Bearer "
            api_key_record = await developer_key_service.verify_api_key(key, db)
            if api_key_record:
                return api_key_record.user_id
        return None
    ```

### 21F · Backend — Rate Limiting per Plan
- [ ] In `backend/app/services/developer_key_service.py`:
  ```python
  DAILY_RATE_LIMITS = {
      "free":  10,
      "basic": 100,
      "pro":   1000,
      "byok":  500,
  }

  async def check_rate_limit(user_id: str, user_plan: str) -> bool:
      """Returns True if within limit."""
      key = f"dev_api_rate:{user_id}:{datetime.utcnow().strftime('%Y%m%d')}"
      count = await redis_cache_client.incr(key)
      if count == 1:
          await redis_cache_client.expire(key, 86400)  # 24h TTL
      limit = DAILY_RATE_LIMITS.get(user_plan, DAILY_RATE_LIMITS["free"])
      return count <= limit
  ```
  - Called at the start of each public API endpoint

### 21G · Backend — Public API v1 Endpoints
- [ ] Create `backend/app/api/public_api_routes.py`:
  - Router prefix: `/api/v1`
  - All endpoints use `get_api_key_user` for auth (no session cookie needed)
  ```
  POST /api/v1/compile           — compile LaTeX → returns job_id + polling URL
  POST /api/v1/optimize          — optimize resume → returns job_id
  POST /api/v1/ats/score         — synchronous ATS score (not async) → returns score
  GET  /api/v1/jobs/{job_id}     — poll job status
  GET  /api/v1/jobs/{job_id}/pdf — download PDF (stream)
  ```
  - Keep responses simple/clean (public API contracts must be stable):
    ```python
    class V1CompileRequest(BaseModel):
        latex_content: str = Field(..., max_length=500_000)
        compiler: str = "pdflatex"

    class V1CompileResponse(BaseModel):
        job_id: str
        status: str  # "queued"
        poll_url: str  # "/api/v1/jobs/{job_id}"
        estimated_seconds: int
    ```
  - Reuse existing Celery tasks — just a different entry point

### 21H · Frontend — Developer Portal Page
- [ ] Create `frontend/src/app/developer/page.tsx`:
  - **API Key Management:**
    - List of existing keys: name, prefix, created date, last used, request count
    - "Create New API Key" button → modal with name input
    - After creation: show full key in modal with copy button + warning banner
    - "Revoke" button per key with confirmation
  - **Documentation section:**
    - Interactive code examples (curl, Python, Node.js tabs)
    - Link to FastAPI auto-generated docs: `https://api.latexy.io/docs`
    - Rate limit info per plan
  - **Usage stats:** bar chart of daily API usage (last 7 days) using visx

### 21I · Tests
- [ ] `backend/test/test_developer_api.py`:
  - `POST /developer/keys` → returns full key once, only prefix in subsequent GET
  - Key hash stored, not plaintext
  - `Authorization: Bearer lx_sk_{valid}` → resolves to correct user_id
  - `Authorization: Bearer lx_sk_{invalid}` → returns None (not 401 — handled by endpoint)
  - Rate limit: 11th request by free user → 429
  - `DELETE /developer/keys/{id}` → key no longer valid for auth
  - Cannot delete another user's key → 404

---

## Feature 22 — AI Bullet Point Generator · P1 · M

**Goal:** Floating widget appears when editor cursor is on a `\item` line. User describes a task;
AI generates 5 strong bullet options. Click to insert at cursor. LLM call is non-streaming,
fast (gpt-4o-mini, ~1s). Frontend-only feature — reuses existing `explainLatexError` API pattern.

### 22A · Backend — Bullet Generator Endpoint
- [ ] Add `POST /ai/generate-bullets` to `backend/app/api/ai_routes.py`:
  ```python
  class GenerateBulletsRequest(BaseModel):
      job_title: str = Field(..., max_length=200)
      responsibility: str = Field(..., max_length=500)
      context: Optional[str] = Field(None, max_length=1000)  # surrounding resume content
      tone: str = Field(default="technical")  # technical | leadership | analytical | creative
      count: int = Field(default=5, ge=1, le=10)

  class GenerateBulletsResponse(BaseModel):
      bullets: List[str]  # list of LaTeX \item lines (without leading \item)
      cached: bool
  ```
  - System prompt:
    ```
    You are a professional resume writer. Generate {count} strong bullet points for a resume.
    Each bullet must:
    - Start with a strong action verb (past tense for past roles)
    - Include quantified impact where plausible (numbers, percentages, scale)
    - Be 80-150 characters (fits on ~1 line in a resume)
    - Match the {tone} tone: technical=precise/technical, leadership=impact/ownership,
      analytical=data/metrics, creative=innovative/design
    - Be LaTeX-compatible (escape special chars: &, %, $, #, _, {, })
    Return JSON: { "bullets": ["Led cross-functional team...", "Engineered scalable..."] }
    Only JSON, no markdown.
    ```
  - Cache key: `sha256(job_title + responsibility + tone + str(count)).hexdigest()[:16]`
  - Cache TTL: `86400` (24h)
  - Auth: optional (works for anon + authenticated)
  - Model: `settings.OPENAI_MODEL` (gpt-4o-mini)
  - `temperature=0.8` (higher for creative variety)

### 22B · Frontend — API Client
- [ ] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  generateBullets(request: GenerateBulletsRequest): Promise<GenerateBulletsResponse>
  ```

### 22C · Frontend — BulletGeneratorWidget Component
- [ ] Create `frontend/src/components/BulletGeneratorWidget.tsx`:
  - Position: floating panel attached to the current `\item` line (positioned near cursor)
  - Triggered by: cursor is on a line matching `/^\s*\\item/`
  - **Widget layout (compact, ~320px wide):**
    - Header: "AI Bullet Generator" with close button (X)
    - "Job title" input (small, pre-filled if detectable from context)
    - "Describe what you did" textarea (2 rows)
    - Tone selector: small pill buttons — Technical | Leadership | Analytical | Creative
    - "Generate" button (primary, with sparkle icon)
    - Bullet results list (after generation):
      - Each bullet: text preview + "Insert" button (check icon)
      - Hover highlights bullet
    - "Regenerate" link at bottom
  - Loading state: spinner with "Generating 5 bullets..."
  - After "Insert": replaces the empty `\item ` line content in Monaco, widget closes
  - Escape key closes widget

### 22D · Frontend — Cursor Detection in LaTeXEditor
- [ ] In `frontend/src/components/LaTeXEditor.tsx`:
  - Add prop: `onCursorLineChange?: (lineContent: string, lineNumber: number) => void`
  - In `handleEditorDidMount`, register:
    ```typescript
    editor.onDidChangeCursorPosition((e) => {
      const line = editor.getModel()?.getLineContent(e.position.lineNumber) ?? ''
      props.onCursorLineChange?.(line, e.position.lineNumber)
    })
    ```
  - Debounce at 200ms to avoid excessive calls

### 22E · Frontend — Integration in Edit Page
- [ ] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - State: `bulletWidgetOpen: boolean`, `bulletWidgetLine: number | null`
  - `onCursorLineChange` handler:
    ```typescript
    const handleCursorLineChange = (lineContent: string, lineNumber: number) => {
      const isItemLine = /^\s*\\item/.test(lineContent)
      setBulletWidgetLine(isItemLine ? lineNumber : null)
      // Widget opens automatically when cursor on \item line? Or on button click?
      // Recommended: show a small "✨" icon in gutter → click to open
    }
    ```
  - Gutter decoration: when on `\item` line, show a subtle sparkle button via Monaco
    `editor.createDecorationsCollection([{ range, options: { glyphMarginClassName: 'bullet-ai-glyph' } }])`
  - Clicking the glyph: `setBulletWidgetOpen(true)`
  - Position widget near cursor using `editor.getScrolledVisiblePosition(position)` → absolute CSS

### 22F · Tests
- [ ] `backend/test/test_bullet_generator.py`:
  - POST returns 5 bullets (default count)
  - Each bullet starts with a capital letter (action verb)
  - `count=3` → returns 3 bullets
  - Same request twice → `cached=true`
  - `responsibility` too long (>500) → 422

---

## Feature 23 — AI Writing Assistant (In-Editor) · P1 · M

**Goal:** Highlight text in Monaco → right-click context menu shows AI rewrite actions (Improve,
Shorten, Quantify, Power Verbs, Expand). Shows diff of proposed change. Accept/reject/regenerate.
LLM call is non-streaming (fast for small selections).

### 23A · Backend — Writing Assistant Endpoint
- [ ] Add `POST /ai/rewrite` to `backend/app/api/ai_routes.py`:
  ```python
  class RewriteRequest(BaseModel):
      selected_text: str = Field(..., min_length=5, max_length=2000)
      action: str = Field(...)  # improve | shorten | quantify | power_verbs | change_tone | expand
      context: Optional[str] = Field(None, max_length=1000)  # surrounding LaTeX for context
      tone: Optional[str] = Field(None)  # for change_tone action: formal | casual

  class RewriteResponse(BaseModel):
      rewritten: str
      action: str
      cached: bool
  ```
  - System prompts per action:
    ```python
    REWRITE_PROMPTS = {
        "improve": "Rewrite for stronger impact and clarity. Keep length similar. LaTeX-safe.",
        "shorten": "Condense to 50% fewer words while preserving the core meaning. No filler.",
        "quantify": "Add specific metrics, numbers, or percentages where plausible. Keep LaTeX valid.",
        "power_verbs": "Replace weak verbs ('responsible for', 'helped with', 'worked on') with strong action verbs (Led, Engineered, Delivered, Architected). Keep rest unchanged.",
        "change_tone": "Rewrite in a {tone} tone. Keep all factual content identical.",
        "expand": "Add more detail and supporting context. Max 50% longer. LaTeX-safe.",
    }
    ```
  - User message: `"Text to rewrite:\n{selected_text}\n\nContext (for reference only):\n{context}"`
  - Returns only the rewritten text (not LaTeX boilerplate) — will replace selection directly
  - Temperature: 0.7
  - Cache: `sha256(action + selected_text + tone).hexdigest()[:16]`, TTL 3600s (shorter — more fresh)

### 23B · Frontend — API Client
- [ ] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  rewriteText(request: RewriteRequest): Promise<RewriteResponse>
  ```

### 23C · Frontend — WritingAssistantWidget Component
- [ ] Create `frontend/src/components/WritingAssistantWidget.tsx`:
  - Appears when text is selected in Monaco (triggered from context menu or selection toolbar)
  - **Initial state (action picker):**
    - Small floating toolbar above selection (absolute positioned)
    - Buttons: ✨ Improve | ✂ Shorten | # Quantify | 🔥 Power Verbs | ↕ Expand
    - Click action → transitions to "loading" state
  - **Loading state:**
    - "Rewriting..." spinner
    - Cancel button
  - **Result state:**
    - Monaco-style inline diff: strikethrough original (red), new text (green)
    - Action buttons: "Accept" (checkmark, emerald) | "Reject" (X, zinc) | "Regenerate" (refresh)
    - "Accept" → replaces selection in editor with rewritten text
    - "Reject" → closes widget, selection restored
    - "Regenerate" → fires same API call again (cache-busting: add timestamp to cache key)
  - Positioning: use `editor.getScrolledVisiblePosition()` for cursor position → absolute CSS offset

### 23D · Frontend — Monaco Context Menu Integration
- [ ] In `frontend/src/components/LaTeXEditor.tsx`:
  - Add prop: `onWritingAssistantAction?: (selectedText: string, context: string, lineNumber: number) => void`
  - In `handleEditorDidMount`:
    ```typescript
    editor.addAction({
      id: 'latexy.writingAssistant',
      label: '✨ AI Writing Assistant',
      contextMenuGroupId: 'navigation',
      contextMenuOrder: 1.5,
      precondition: 'editorHasSelection',
      run: (editor) => {
        const selection = editor.getSelection()!
        const selectedText = editor.getModel()!.getValueInRange(selection)
        if (!selectedText.trim()) return
        // Get surrounding context (5 lines before/after selection)
        const context = editor.getModel()!.getValueInRange(...)
        props.onWritingAssistantAction?.(selectedText, context, selection.startLineNumber)
      }
    })
    ```

### 23E · Frontend — Integration in Edit Page
- [ ] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - State: `writingAssistantState: { selectedText, context, lineNumber, loading, result } | null`
  - `onWritingAssistantAction` handler: sets state, user picks action
  - Apply action: calls `apiClient.rewriteText(...)`, sets `result`
  - Accept handler: `editorRef.current?.executeEdits(...)` to replace selection

### 23F · Tests
- [ ] `backend/test/test_writing_assistant.py`:
  - Each action (`improve`, `shorten`, `quantify`, `power_verbs`, `expand`) returns non-empty string
  - `shorten` output is shorter than input (mock LLM: verify prompt says "50% fewer words")
  - `action=invalid` → 422
  - `selected_text` too short (< 5 chars) → 422
  - Cache hit on second identical request

---

## Feature 24 — AI Professional Summary Generator · P1 · M

**Goal:** "Generate Summary" button appears in editor when cursor is in the summary/objective
section. Generates 3 alternative summaries (technical, leadership, unique). User picks one to
insert. Non-streaming, fast LLM call.

### 24A · Backend — Summary Generator Endpoint
- [ ] Add `POST /ai/generate-summary` to `backend/app/api/ai_routes.py`:
  ```python
  class GenerateSummaryRequest(BaseModel):
      resume_latex: str = Field(..., max_length=50_000)  # full resume for context
      target_role: Optional[str] = Field(None, max_length=200)
      job_description: Optional[str] = Field(None, max_length=5000)
      count: int = Field(default=3, ge=1, le=5)

  class GenerateSummaryResponse(BaseModel):
      summaries: List[SummaryVariant]
      cached: bool

  class SummaryVariant(BaseModel):
      emphasis: str     # "technical" | "leadership" | "unique"
      title: str        # short display name: "Technical Skills Focus"
      text: str         # 2-3 sentence plain text summary (not LaTeX — inserted by frontend)
  ```
  - System prompt:
    ```
    You are an expert resume writer. Generate 3 professional summary alternatives for this resume.
    Each summary: 2-3 sentences, punchy, tailored to the role (if provided).
    Variant 1 (technical): Lead with technical skills and technical achievements
    Variant 2 (leadership): Lead with impact, leadership, and results
    Variant 3 (unique): Lead with most distinctive/unusual differentiators
    Each summary: NO filler phrases ("passionate about", "results-driven", "team player")
    Each summary: Start with a strong descriptor of the candidate, not "I" or "My"
    Target role: {target_role or "general"}
    Output JSON: { "summaries": [{ "emphasis": "technical", "title": "...", "text": "..." }, ...] }
    ```
  - Extract candidate name from LaTeX for context (regex: `\\name{...}` or first `\\textbf`)
  - Cache TTL: 1800s (30 min — summaries are context-specific)

### 24B · Frontend — Summary Detection
- [ ] In `frontend/src/components/LaTeXEditor.tsx`:
  - Add prop: `onCursorInSummarySection?: (inSummary: boolean) => void`
  - Detect if cursor is in summary section:
    ```typescript
    const isSummarySection = (lineContent: string, lineNumber: number): boolean => {
      // Check if any \section{} above current line matches summary/objective/profile
      // Scan upward from lineNumber looking for \section{Summary} etc.
      const content = editor.getModel()!.getValue()
      const lines = content.split('\n')
      for (let i = lineNumber - 1; i >= 0; i--) {
        if (/\\section\{(summary|objective|profile|about)\}/i.test(lines[i])) return true
        if (/\\section\{/i.test(lines[i])) return false  // different section
      }
      return false
    }
    ```
  - Fire `onCursorInSummarySection` from `onDidChangeCursorPosition`

### 24C · Frontend — SummaryGeneratorWidget Component
- [ ] Create `frontend/src/components/SummaryGeneratorWidget.tsx`:
  - Appears as a small floating button when `inSummarySection = true`:
    - Button: "✨ Generate Summary" (small, `violet` accent, positioned at top of section)
  - On click → opens modal/panel:
    - Target role input (optional)
    - Job description paste area (optional, collapsed by default)
    - "Generate 3 Alternatives" button
  - **Result view:**
    - 3 cards, each showing emphasis label + full text
    - Selected card: ring highlight
    - "Insert this summary" button per card
    - On insert: replaces the content after `\section{Summary}...\vspace{...}` or wherever cursor is
      - Simpler: insert at cursor position directly (user positions cursor first)

### 24D · Frontend — Integration
- [ ] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Track `cursorInSummarySection: boolean` from `onCursorInSummarySection`
  - Show `SummaryGeneratorWidget` when `cursorInSummarySection === true`
  - Pass full `editorContent` as `resume_latex` for context

### 24E · Tests
- [ ] `backend/test/test_summary_generator.py`:
  - POST returns 3 summaries (default count)
  - Each summary has `emphasis`, `title`, `text` fields
  - `text` is not empty and doesn't contain JSON artifacts
  - `count=1` → returns 1 summary
  - `resume_latex` too large → 422

---

## Feature 25 — AI Proofreader (Writing Quality) · P1 · M

**Goal:** Analyze resume prose for writing weaknesses (weak verbs, passive voice, buzzwords,
missing quantification, vague claims). Show as Monaco decorations. Panel lists issues with
quick-fix suggestions. Rule-based (fast, no LLM needed for MVP).

### 25A · Backend — Proofreader Endpoint
- [ ] Add `POST /ai/proofread` to `backend/app/api/ai_routes.py`:
  ```python
  class ProofreadRequest(BaseModel):
      latex_content: str = Field(..., max_length=200_000)

  class ProofreadIssue(BaseModel):
      line: int
      column_start: int
      column_end: int
      category: str    # "weak_verb" | "passive_voice" | "buzzword" | "no_quantification" | "vague"
      severity: str    # "error" | "warning" | "info"
      message: str     # "Replace 'responsible for' with a strong action verb"
      suggestion: Optional[str]   # "Led" | "Managed" | "Delivered"
      original_text: str
      suggested_text: Optional[str]

  class ProofreadResponse(BaseModel):
      issues: List[ProofreadIssue]
      summary: Dict[str, int]  # { "weak_verb": 5, "passive_voice": 2, ... }
      overall_score: int        # 0-100 based on issue density
  ```

- [ ] Create `backend/app/services/proofreader_service.py`:
  ```python
  WEAK_VERB_PATTERNS = [
      (r'\bresponsible for\b', 'Replace with an action verb (Led, Managed, Owned)'),
      (r'\bhelped (to |with )?\b', 'Replace with direct action verb'),
      (r'\bworked on\b', 'Replace with specific action verb'),
      (r'\bwas involved in\b', 'Replace with action verb showing ownership'),
      (r'\bassisted (?:with|in)\b', 'Replace with action verb'),
      (r'\bparticipated in\b', 'Replace with specific contribution'),
      (r'\bcontributed to\b', 'Replace with specific action'),
  ]

  PASSIVE_VOICE_PATTERNS = [
      (r'\bwas (?:improved|optimized|reduced|increased|built|created|developed) by\b', 'Rewrite in active voice'),
      (r'\bwere (?:responsible|required|expected)\b', 'Rewrite in active voice'),
      (r'\bhas been\b', 'Consider rewriting in active voice'),
  ]

  BUZZWORD_PATTERNS = [
      (r'\bsynergy\b', 'Remove buzzword or replace with specific collaboration example'),
      (r'\bleverag(?:e|ed|ing)\b', 'Replace with a specific action (Used, Applied, Deployed)'),
      (r'\bproactive(?:ly)?\b', 'Remove buzzword; show proactiveness through actions'),
      (r'\bpassionate about\b', 'Remove; show passion through achievements'),
      (r'\bteam player\b', 'Remove; show teamwork through collaboration examples'),
      (r'\bhard[- ]?working\b', 'Remove; let achievements speak for themselves'),
      (r'\bself[- ]?starter\b', 'Remove; show initiative through examples'),
      (r'\bthought leader\b', 'Remove; too vague'),
      (r'\bgo[- ]?getter\b', 'Remove; too informal'),
      (r'\boutside[- ]the[- ]box\b', 'Remove; too cliché'),
  ]

  def proofread_latex(latex_content: str) -> ProofreadResponse:
      # 1. Split into lines
      # 2. Extract text content from \item lines (skip preamble/commands)
      # 3. Run each pattern against extracted text lines
      # 4. Map character positions back to line numbers
      # 5. Return issues list
  ```

### 25B · Frontend — API Client
- [ ] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  proofreadResume(latexContent: string): Promise<ProofreadResponse>
  ```

### 25C · Frontend — Monaco Decoration Integration
- [ ] In `frontend/src/components/LaTeXEditor.tsx`:
  - Add prop: `proofreadIssues?: ProofreadIssue[]`
  - When `proofreadIssues` changes, register decorations:
    ```typescript
    const decorations = proofreadIssues.map(issue => ({
      range: new monaco.Range(issue.line, issue.column_start, issue.line, issue.column_end),
      options: {
        inlineClassName: issue.category === 'passive_voice' ? 'proofreader-passive'
                       : issue.category === 'buzzword' ? 'proofreader-buzzword'
                       : 'proofreader-weak',
        hoverMessage: { value: `**${issue.category}**: ${issue.message}` },
        className: 'proofreader-highlight',  // underline decoration
      }
    }))
    decorationsRef.current = editor.createDecorationsCollection(decorations)
    ```
  - CSS (in globals.css or tailwind arbitrary):
    - `proofreader-weak`: amber underline (wavy via `text-decoration`)
    - `proofreader-passive`: blue underline
    - `proofreader-buzzword`: violet underline

### 25D · Frontend — ProofreadPanel Component
- [ ] Create `frontend/src/components/ProofreadPanel.tsx`:
  - Sidebar panel tab titled "Proofreader"
  - "Run Proofreader" button (triggers API call with current editor content)
  - Loading: "Analyzing writing quality..."
  - Results:
    - Summary bar: "5 weak verbs · 2 passive voice · 3 buzzwords · 1 vague claim" (colored counts)
    - Overall writing score badge (0-100, colored)
    - Issue list grouped by category:
      - Each issue: line number, offending text (highlighted), suggested fix
      - "Apply fix" button per issue → calls `editorRef.current?.executeEdits(...)` to replace
      - "Ignore" button → removes issue from list (client-side only)
    - "Auto-fix Safe Issues" button → applies all suggestions with `suggested_text` set
  - Auto-run option: "Auto-proofread on compile" toggle (runs after each successful compile)

### 25E · Tests
- [ ] `backend/test/test_proofreader.py`:
  - Text with "responsible for" → `weak_verb` issue detected at correct line
  - Text with "was improved by" → `passive_voice` issue detected
  - Text with "synergy" → `buzzword` issue detected
  - Clean resume text → zero issues
  - Response `summary` dict counts match number of issues per category
  - `overall_score` is 100 for clean text, lower for text with many issues

---

## Feature 26 — One-Click Resume Tailoring · P1 · M

**Goal:** "Quick Tailor" button in workspace card. Opens a modal to paste JD. One click fires
the full optimization pipeline with aggressive preset settings, and automatically creates a
new resume variant (fork) with the result. Original resume is never modified.

### 26A · Backend — Quick Tailor Endpoint
- [ ] Add `POST /resumes/{resume_id}/quick-tailor` to `backend/app/api/resume_routes.py`:
  - Auth required, verify ownership
  - Body: `{ job_description: str, company_name?: str, role_title?: str }`
  - Steps:
    1. Fork resume (same logic as `POST /resumes/{id}/fork`):
       - Title: `f"{parent.title} — {role_title or company_name or 'Tailored'}"`
       - `parent_resume_id = resume_id`
    2. Submit combined optimize+compile job for the NEW fork:
       - `optimization_level = "aggressive"`
       - `job_description = request.job_description`
       - Custom instructions: `"Tailor this resume for the specific role. Maximize keyword alignment with the job description. Keep all factual information accurate."`
    3. Return: `{ fork_id, job_id }` (client streams job progress, fork is updated after)

- [ ] After optimization completes in orchestrator, update the fork resume's `latex_content`:
  - The orchestrator already saves optimized content to DB (verify this)
  - If it saves to the parent resume → change to save to fork: pass `resume_id_to_update = fork_id`

### 26B · Frontend — Quick Tailor Modal
- [ ] Create `frontend/src/components/QuickTailorModal.tsx`:
  - Triggered from workspace resume card: "Quick Tailor" action (lightning bolt icon)
  - **Step 1 — Job Description:**
    - Large textarea: "Paste job description here"
    - Optional: Company name + Role title inputs
    - "Start Tailoring" button (primary)
  - **Step 2 — Progress (after submit):**
    - Progress bar + stage label (streaming via `useJobStream`)
    - "Cancel" button
    - Live preview of streaming optimized LaTeX (optional — can skip for simplicity)
  - **Step 3 — Complete:**
    - "✓ Tailored resume created!"
    - "Open Tailored Resume" button → navigates to `/workspace/{fork_id}/edit`
    - "View Original" link
    - Option to run ATS score immediately
  - Error state: if optimization fails, show error + "Try Again" button

### 26C · Frontend — Workspace Integration
- [ ] In `frontend/src/app/workspace/page.tsx`:
  - Add "Quick Tailor" to resume card actions dropdown (lightning bolt icon)
  - Opens `QuickTailorModal` with `resumeId` pre-set
  - After completion: refresh resume list (new fork appears in workspace)

### 26D · Frontend — API Client
- [ ] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  quickTailorResume(resumeId: string, body: QuickTailorRequest): Promise<{ fork_id: string; job_id: string }>
  ```

### 26E · Tests
- [ ] `backend/test/test_quick_tailor.py`:
  - POST → creates fork with `parent_resume_id` set
  - Fork title includes role_title or company_name or "Tailored"
  - Returns `fork_id` and `job_id`
  - Job submitted with `optimization_level = "aggressive"`
  - Original resume's `latex_content` is unchanged after tailoring

---

## Feature 27 — Before/After Optimization Comparison · P1 · S

**Goal:** After AI optimization completes, show "Compare PDFs" button. Side-by-side PDF viewer
comparing original and optimized PDF. Synchronized scroll. Uses existing `PDFPreview` component
rendered twice. No backend changes needed — data is already in `optimization_history`.

### 27A · Backend — No Changes Needed
- The `Optimization` record already has `original_latex` and `optimized_latex`
- The existing `/download/{job_id}` endpoint serves the optimized PDF
- Need a way to compile the ORIGINAL PDF on demand for comparison:
  - Option A: Compile original_latex as a separate job (adds latency)
  - Option B: Show source diff (LaTeX) side-by-side instead (faster, no compile)
  - **Recommended for MVP:** LaTeX source diff using `DiffViewerModal` (already built) + link to compiled PDF for the optimized version
  - True PDF comparison requires Option A; add as enhancement later

### 27B · Frontend — Trigger in Optimize Page
- [ ] In `frontend/src/app/workspace/[resumeId]/optimize/page.tsx`:
  - After `stream.status === 'completed'` and optimized PDF is available:
    - Show "Compare with Original" button in results section (next to "Download PDF")
  - On click: open `CompareModal` with `{ originalLatex, optimizedLatex, optimizedPdfUrl }`
- [ ] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - History panel entry for optimization runs: "Compare" button → same modal

### 27C · Frontend — CompareModal Component
- [ ] Create `frontend/src/components/CompareModal.tsx`:
  - Full-screen modal (or large drawer from bottom)
  - **Tab toggle:** "LaTeX Diff" | "PDF Preview" (tabs at top)
  - **LaTeX Diff tab:**
    - Reuse `DiffViewerModal` internals: `MonacoDiffEditor` with original (left) vs optimized (right)
    - Diff statistics: "+N / -N lines"
    - "Restore Original" action button
  - **PDF Preview tab (Phase 2):**
    - Side-by-side `PDFPreview` components (left: original, right: optimized)
    - Synchronized scroll: `onScroll` event on left → set scrollTop on right
    - "Swap" button to switch which is left/right
    - "Download Original" and "Download Optimized" buttons
    - Note: Original PDF requires compiling `original_latex` → show "Compile Original" button
      that fires a background compile job; while pending show skeleton
  - **For MVP:** Only LaTeX Diff tab is required; PDF Preview tab is a nice-to-have

### 27D · Frontend — Synchronized PDF Scroll
- [ ] If implementing PDF comparison:
  ```typescript
  // In CompareModal, two PDFPreview refs
  const leftPdfRef = useRef<HTMLDivElement>(null)
  const rightPdfRef = useRef<HTMLDivElement>(null)
  const handleLeftScroll = (e: Event) => {
    if (rightPdfRef.current) {
      const ratio = (e.target as HTMLDivElement).scrollTop /
                    (e.target as HTMLDivElement).scrollHeight
      rightPdfRef.current.scrollTop = ratio * rightPdfRef.current.scrollHeight
    }
  }
  ```

### 27E · Tests
- [ ] Manual E2E:
  - Run optimization → "Compare" button appears → opens modal
  - LaTeX Diff shows meaningful differences between original and optimized
  - "Restore Original" replaces editor content with `original_latex`
  - Escape key closes modal

---

## Feature 28 — LaTeX Package Manager UI · P1 · M

**Goal:** "Packages" sidebar panel. Search CTAN packages from a local curated list. Shows
description, usage example. "Add to Preamble" inserts `\usepackage{name}` in correct location.
Auto-detects already-installed packages from current preamble.

### 28A · Frontend — Package Database
- [ ] Create `frontend/src/data/latex-packages.ts`:
  - Curated list of 200+ most useful LaTeX packages:
    ```typescript
    export const LATEX_PACKAGES: LaTeXPackage[] = [
      {
        name: "geometry",
        description: "Flexible page margin and layout control",
        category: "layout",
        usage: "\\usepackage[margin=1in]{geometry}",
        example: "\\geometry{left=1in, right=1in, top=1in, bottom=1in}",
        related: ["fullpage", "vmargin"],
        conflicts: [],
        loadOrder: 10,  // lower = load earlier in preamble
      },
      { name: "hyperref", description: "Hyperlinks and PDF metadata", category: "links",
        usage: "\\usepackage[colorlinks=true]{hyperref}", loadOrder: 90,
        note: "Must be loaded LAST among most packages" },
      { name: "fontenc", description: "Font encoding for proper hyphenation", category: "fonts",
        usage: "\\usepackage[T1]{fontenc}", loadOrder: 5 },
      // ... 200+ more packages across categories:
      // layout, fonts, math, tables, graphics, colors, links, bibliography, misc
    ]
    ```
  - Categories: layout, fonts, math, tables, graphics, colors, links, bibliography, utils

### 28B · Frontend — Preamble Package Detection
- [ ] In `frontend/src/lib/latex-preamble.ts`, add:
  ```typescript
  export function getInstalledPackages(latex: string): string[] {
    const matches = latex.matchAll(/\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}/g)
    return Array.from(matches).flatMap(m => m[1].split(',').map(s => s.trim()))
  }

  export function addPackageToPreamble(latex: string, packageName: string, options?: string): string {
    const usePackage = options
      ? `\\usepackage[${options}]{${packageName}}`
      : `\\usepackage{${packageName}}`
    // Find correct insert position (before \begin{document}, after other \usepackage lines)
    const lastPackageLine = findLastUsepackageLine(latex)
    if (lastPackageLine >= 0) {
      const lines = latex.split('\n')
      lines.splice(lastPackageLine + 1, 0, usePackage)
      return lines.join('\n')
    }
    // Fallback: insert before \begin{document}
    return latex.replace(/(\\begin\{document\})/, `${usePackage}\n$1`)
  }
  ```

### 28C · Frontend — PackageManagerPanel Component
- [ ] Create `frontend/src/components/PackageManagerPanel.tsx`:
  - Props:
    ```typescript
    {
      currentLatex: string
      onAddPackage: (newLatex: string, packageName: string) => void
    }
    ```
  - **Search bar:** instant filter by package name or description
  - **Category filter tabs:** All | Layout | Fonts | Math | Tables | Graphics | Colors | Links | Misc
  - **Package list:**
    - Each item: package name (monospace), description (gray), category badge
    - Installed packages: green checkmark + "Installed" badge
    - Not installed: "Add" button (plus icon)
    - Click package name → expand to show full description + usage example + example code
    - Conflict warning: if adding a package that conflicts with an installed one → amber warning
    - Note for packages with special requirements (hyperref → "load last")
  - **Installed packages section at top:** chips of currently installed packages with "×" remove button
    - "×" button: calls `removePackageFromPreamble(latex, packageName)` → `onAddPackage()`

### 28D · Frontend — Integration in Edit Page
- [ ] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Add "Packages" tab to editor sidebar
  - `onAddPackage` handler: `editorRef.current?.setValue(newLatex)` + auto-save

### 28E · Tests
- [ ] Unit tests for `latex-preamble.ts` package functions:
  - `getInstalledPackages` on preamble with 3 packages → returns array of 3 names
  - `addPackageToPreamble` adds `\usepackage{amsmath}` after existing packages
  - `addPackageToPreamble` on latex without existing packages → inserts before `\begin{document}`
  - Idempotent: adding already-present package → no duplicate

---

## Feature 29 — LaTeX Linter (Real-Time Best Practices) · P1 · M

**Goal:** Rule-based checker (debounced 3s) detecting LaTeX anti-patterns. Registers Monaco
markers with severity. "Auto-Fix All" for safe automatic fixes. Frontend-only — no backend needed.

### 29A · Frontend — Linter Rules
- [ ] Create `frontend/src/lib/latex-linter.ts`:
  ```typescript
  export interface LintIssue {
    line: number
    column: number
    endColumn: number
    severity: 'error' | 'warning' | 'info'
    ruleId: string
    message: string
    fixable: boolean
    fix?: (lineContent: string) => string  // returns fixed line content
  }

  export const LINT_RULES: LintRule[] = [
    {
      id: 'deprecated-bf',
      pattern: /(?<!\w)\\bf(?=\s|\{|\\)/g,
      message: 'Deprecated: use \\textbf{} instead of \\bf',
      severity: 'warning',
      fixable: true,
      // fix: replace \bf{text} with \textbf{text} — requires context
    },
    {
      id: 'deprecated-it',
      pattern: /(?<!\w)\\it(?=\s|\{|\\)/g,
      message: 'Deprecated: use \\textit{} instead of \\it',
      severity: 'warning',
      fixable: true,
    },
    {
      id: 'wrong-quotes',
      pattern: /"([^"]+)"/g,
      message: 'Use LaTeX curly quotes: ``text\'\' instead of "text"',
      severity: 'info',
      fixable: true,
      fix: (match) => match.replace(/"([^"]+)"/g, "``$1''"),
    },
    {
      id: 'hyperref-order',
      // Detect if hyperref is loaded before geometry/color/other packages
      pattern: /specific cross-line check/,
      message: 'hyperref should be loaded as the last package in preamble',
      severity: 'warning',
      fixable: false,
    },
    {
      id: 'missing-label',
      // \section{...} not followed by \label{...} within 2 lines
      pattern: /\\section\{[^}]+\}/g,
      message: '\\section without a \\label — add \\label{sec:name} for cross-references',
      severity: 'info',
      fixable: false,
    },
    {
      id: 'redundant-space',
      // "e.g. " → "e.g.\ " or "e.g.~"
      pattern: /\b(e\.g\.|i\.e\.|etc\.)\s/g,
      message: 'Use e.g.\\ or e.g.~ to prevent incorrect inter-sentence spacing',
      severity: 'info',
      fixable: true,
    },
  ]

  export function lintLatex(content: string): LintIssue[] {
    const lines = content.split('\n')
    const issues: LintIssue[] = []
    // Run per-line rules
    lines.forEach((line, lineIdx) => {
      if (line.trim().startsWith('%')) return  // skip comments
      LINT_RULES.forEach(rule => {
        // ... match and record issues
      })
    })
    // Run cross-line rules (hyperref order, missing labels)
    // ...
    return issues
  }
  ```

### 29B · Frontend — Monaco Marker Registration
- [ ] In `frontend/src/components/LaTeXEditor.tsx`:
  - Add prop: `lintIssues?: LintIssue[]`
  - When `lintIssues` changes, call `monaco.editor.setModelMarkers(model, 'latex-lint', markers)`:
    ```typescript
    const markers: monaco.editor.IMarkerData[] = (lintIssues ?? []).map(issue => ({
      startLineNumber: issue.line,
      endLineNumber: issue.line,
      startColumn: issue.column,
      endColumn: issue.endColumn,
      severity: issue.severity === 'error' ? monaco.MarkerSeverity.Error
               : issue.severity === 'warning' ? monaco.MarkerSeverity.Warning
               : monaco.MarkerSeverity.Info,
      message: issue.message,
      source: `latexy-lint(${issue.ruleId})`,
    }))
    ```
  - Markers appear as squiggles in editor (same as error markers)

### 29C · Frontend — Lint Hook
- [ ] Create `frontend/src/hooks/useLatexLinter.ts`:
  ```typescript
  export function useLatexLinter(latexContent: string, enabled: boolean) {
    const [issues, setIssues] = useState<LintIssue[]>([])
    const timerRef = useRef<NodeJS.Timeout | null>(null)

    useEffect(() => {
      if (!enabled) { setIssues([]); return }
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        const result = lintLatex(latexContent)
        setIssues(result)
      }, 3000)  // 3s debounce
      return () => { if (timerRef.current) clearTimeout(timerRef.current) }
    }, [latexContent, enabled])

    const autoFixAll = (latex: string): string => {
      // Apply all fixable rules sequentially
      let fixed = latex
      // ... apply fixes
      return fixed
    }

    return { issues, autoFixAll }
  }
  ```

### 29D · Frontend — LinterPanel Component
- [ ] Create `frontend/src/components/LinterPanel.tsx`:
  - "Linter" tab in editor sidebar
  - Toggle: "Enable real-time linting" (default: on)
  - Issues list:
    - Grouped by severity: Warnings (amber), Info (blue)
    - Each item: rule ID chip, message, line number link (click → jump to line)
    - Fixable items: "Fix" button (applies single fix)
  - "Auto-Fix All Warnings" button → applies all fixable issues at once
  - Issue count badge on the "Linter" tab title

### 29E · Tests
- [ ] Unit tests for `latex-linter.ts`:
  - `\\bf` in content → `deprecated-bf` issue detected
  - `"quoted text"` → `wrong-quotes` issue detected
  - Comment line with `\\bf` → no issue (comments ignored)
  - Clean LaTeX → zero issues
  - `autoFixAll` on `\\bf text` → produces `\\textbf{text}` (if applicable)

---

## Feature 30 — Smart Code Snippet Auto-Insert · P1 · S

**Goal:** Extend Monaco completion provider in `LaTeXEditor.tsx` with trigger-sequence snippets.
When user types `\begin{itemize}`, auto-expand with `\item ` lines and cursor positioning.
All client-side, no backend needed.

### 30A · Frontend — Monaco Snippet Provider
- [ ] In `frontend/src/components/LaTeXEditor.tsx`, in `handleEditorDidMount`:
  - Register completion provider with Monaco snippet syntax:
    ```typescript
    monaco.languages.registerCompletionItemProvider('latex', {
      triggerCharacters: ['\\', '{'],
      provideCompletionItems(model, position) {
        const word = model.getWordUntilPosition(position)
        const lineContent = model.getLineContent(position.lineNumber)

        const snippets: monaco.languages.CompletionItem[] = [
          {
            label: '\\begin{itemize}',
            kind: monaco.languages.CompletionItemKind.Snippet,
            insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
            insertText: '\\begin{itemize}\n\t\\item ${1:First item}\n\t\\item ${2:Second item}\n\\end{itemize}',
            documentation: 'Unordered list environment',
          },
          {
            label: '\\begin{enumerate}',
            kind: monaco.languages.CompletionItemKind.Snippet,
            insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
            insertText: '\\begin{enumerate}\n\t\\item ${1:First item}\n\t\\item ${2:Second item}\n\\end{enumerate}',
            documentation: 'Numbered list environment',
          },
          {
            label: 'doc',
            kind: monaco.languages.CompletionItemKind.Snippet,
            insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
            insertText: '\\documentclass[11pt]{article}\n\\usepackage[T1]{fontenc}\n\\usepackage[utf8]{inputenc}\n\\usepackage{geometry}\n\\geometry{margin=1in}\n\n\\begin{document}\n\n${1:Content here}\n\n\\end{document}',
            documentation: 'Full document boilerplate',
          },
          {
            label: 'sec',
            kind: monaco.languages.CompletionItemKind.Snippet,
            insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
            insertText: '\\section{${1:Section Title}}\n\\label{sec:${2:label}}\n\n${3}',
            documentation: 'Section with label',
          },
          {
            label: 'fig',
            kind: monaco.languages.CompletionItemKind.Snippet,
            insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
            insertText: '\\begin{figure}[htbp]\n\t\\centering\n\t\\includegraphics[width=0.8\\textwidth]{${1:filename}}\n\t\\caption{${2:Caption text}}\n\t\\label{fig:${3:label}}\n\\end{figure}',
            documentation: 'Figure environment',
          },
          {
            label: 'eq',
            kind: monaco.languages.CompletionItemKind.Snippet,
            insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
            insertText: '\\begin{equation}\n\t${1:formula}\n\t\\label{eq:${2:label}}\n\\end{equation}',
            documentation: 'Numbered equation',
          },
          {
            label: '\\begin{tabular}',
            kind: monaco.languages.CompletionItemKind.Snippet,
            insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
            insertText: '\\begin{tabular}{${1:lll}}\n\t${2:Col1} & ${3:Col2} & ${4:Col3} \\\\\\\\\n\t\\hline\n\t${5:Row1} & ${6:Data} & ${7:Data} \\\\\\\\\n\\end{tabular}',
            documentation: 'Table environment',
          },
        ]

        return { suggestions: snippets }
      }
    })
    ```
  - Note: Monaco uses `${}` for tab stops in snippets — ensure correct escaping

### 30B · Tests
- [ ] Manual verification:
  - Type `doc` in Monaco → completion popup shows → Tab to expand → full boilerplate inserted
  - Type `\begin{itemize}` → Tab → expands with `\item ` lines and cursor in first item
  - Snippet tab stops: Tab moves between `${1}`, `${2}`, etc.

---

## Feature 31 — Regex-Aware Find & Replace · P1 · S

**Goal:** Enhance Monaco's built-in find/replace with LaTeX-specific preset search patterns.
Toggle between normal and "LaTeX-Aware" mode. Preset patterns for section headers, textbf content,
item bullets. No backend changes needed.

### 31A · Frontend — LaTeX Search Presets
- [ ] Create `frontend/src/data/latex-search-presets.ts`:
  ```typescript
  export const LATEX_SEARCH_PRESETS = [
    {
      label: "All section headers",
      pattern: "\\\\section\\{([^}]+)\\}",
      isRegex: true,
      description: "Find all \\section{...} commands",
    },
    {
      label: "All \\textbf content",
      pattern: "\\\\textbf\\{([^}]+)\\}",
      isRegex: true,
      description: "Find all bold text",
    },
    {
      label: "All \\item bullets",
      pattern: "^\\s*\\\\item\\s+(.+)$",
      isRegex: true,
      isMultiline: false,
    },
    {
      label: "All \\href links",
      pattern: "\\\\href\\{([^}]+)\\}\\{([^}]+)\\}",
      isRegex: true,
    },
    {
      label: "All dates (Month Year format)",
      pattern: "(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\.?\\s+\\d{4}",
      isRegex: true,
    },
    {
      label: "All company names (subsection)",
      pattern: "\\\\resumeSubheading\\{([^}]+)\\}",
      isRegex: true,
    },
  ]
  ```

### 31B · Frontend — LaTeX Search Panel Component
- [ ] Create `frontend/src/components/LaTeXSearchPanel.tsx`:
  - Positioned as a slide-down panel from editor top-right (similar to native Monaco find)
  - **Search input** with regex toggle, case-sensitive toggle, whole-word toggle
  - **Preset dropdown:** "LaTeX Patterns" → shows `LATEX_SEARCH_PRESETS`
    - Selecting a preset fills the search input with the regex pattern
  - **Replace input** (expandable)
  - **Navigate buttons:** ↑ Previous, ↓ Next (wraps around)
  - **"Replace" and "Replace All" buttons**
  - **Result count:** "3 of 12 matches"
  - Implementation via Monaco find actions:
    ```typescript
    // Open Monaco find widget programmatically:
    editor.getAction('actions.find')?.run()
    // Or use the FindController API directly for more control
    ```
  - Actually: instead of building custom UI, extend Monaco's existing find widget:
    - Use `editor.trigger('keyboard', 'actions.find', null)` to open native Monaco find
    - Then inject preset pattern via `editor.getContribution('editor.contrib.findController')`
    - **Simpler approach:** Add a small "Presets" button overlay above the Monaco editor
      that, when clicked, shows a dropdown of presets, and clicking a preset calls:
      ```typescript
      const findController = editor.getContribution('editor.contrib.findController') as any
      findController.setSearchString(preset.pattern)
      findController.toggleRegex(true)
      editor.getAction('actions.find')?.run()
      ```

### 31C · Frontend — Keyboard Shortcut
- [ ] Register Cmd+Shift+H for LaTeX-aware replace (Cmd+H is built-in replace in Monaco)
  - Add custom key binding in `handleEditorDidMount`:
    ```typescript
    editor.addCommand(
      monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyH,
      () => setSearchPanelOpen(true)
    )
    ```

### 31D · Tests
- [ ] Manual verification:
  - Click "All section headers" preset → Monaco find widget opens with regex pre-filled
  - All `\section{...}` occurrences are highlighted
  - Replace all works with regex groups (e.g. replace `\textbf{X}` with `\textit{X}`)

---

## Feature 32 — Advanced Subscription Tiers · P1 · M

**Goal:** Add annual billing (20% off), student plan (50% off + .edu verification), and agency/
team plan (5 seats). Add coupon code support. Show upgrade prompts at friction points. Uses
existing Razorpay infrastructure.

### 32A · Config — New Plan Definitions
- [ ] Update `backend/app/core/config.py` plan definitions:
  ```python
  # Existing monthly plan IDs (Razorpay)
  RAZORPAY_PLAN_BASIC_MONTHLY = "plan_..."
  RAZORPAY_PLAN_PRO_MONTHLY = "plan_..."
  RAZORPAY_PLAN_BYOK_MONTHLY = "plan_..."

  # New annual plan IDs (20% discount = 10 months price)
  RAZORPAY_PLAN_BASIC_ANNUAL = "plan_..."   # 299*12*0.8 = 2871 INR/year
  RAZORPAY_PLAN_PRO_ANNUAL = "plan_..."     # 599*12*0.8 = 5750 INR/year
  RAZORPAY_PLAN_BYOK_ANNUAL = "plan_..."    # 199*12*0.8 = 1910 INR/year

  # Student plan (50% off Pro monthly)
  RAZORPAY_PLAN_STUDENT = "plan_..."        # 299 INR/month

  # Team plan
  RAZORPAY_PLAN_TEAM = "plan_..."           # 2499 INR/month for 5 seats
  TEAM_PLAN_MAX_SEATS: int = 5
  ```
  - Create these plans in Razorpay dashboard first, then paste IDs here

### 32B · Database — Team Seats
- [ ] Create `backend/alembic/versions/0013_add_team_members.py`:
  ```sql
  CREATE TABLE team_seats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    member_email TEXT NOT NULL,
    member_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    status TEXT DEFAULT 'invited',  -- invited | active | removed
    invited_at TIMESTAMPTZ DEFAULT NOW(),
    joined_at TIMESTAMPTZ
  );
  CREATE INDEX idx_team_seats_owner ON team_seats(owner_user_id);
  CREATE UNIQUE INDEX idx_team_seats_owner_email ON team_seats(owner_user_id, member_email);
  ```

### 32C · Database — Coupon Codes
- [ ] Add to the same migration:
  ```sql
  CREATE TABLE coupon_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT UNIQUE NOT NULL,
    discount_percent INTEGER NOT NULL CHECK (discount_percent > 0 AND discount_percent <= 100),
    applicable_plans TEXT[] DEFAULT '{}',  -- empty = all plans
    max_uses INTEGER DEFAULT NULL,         -- NULL = unlimited
    used_count INTEGER DEFAULT 0,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE TABLE coupon_redemptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coupon_id UUID REFERENCES coupon_codes(id),
    user_id TEXT REFERENCES users(id),
    redeemed_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```

### 32D · Backend — Annual/Student/Team Billing
- [ ] Add to existing billing/subscription routes (`routes.py`):
  - `POST /subscription/create` already exists — extend it to accept:
    - `billing_period: "monthly" | "annual"` — maps to correct Razorpay plan ID
    - `coupon_code?: str` — validates coupon, applies Razorpay discount
    - `student_email?: str` — for student plan: verify `.edu` domain
  - Student email verification:
    ```python
    if plan == "student":
        if not student_email or not student_email.endswith(".edu"):
            raise HTTPException(400, "Student plan requires a .edu email address")
        # Send verification email to student_email (reuse email_worker)
        # Store pending verification in Redis with 24h TTL
        # Only activate student plan after email verified
    ```
  - Annual billing: Razorpay subscriptions with `interval: "yearly"` and `interval_count: 1`

### 32E · Backend — Team Seat Management
- [ ] Create `backend/app/api/team_routes.py`:
  ```
  GET    /team/seats         — list team seats (owner only)
  POST   /team/invite        — invite member by email
  DELETE /team/seats/{id}    — remove member
  GET    /team/join/{token}  — accept team invitation (validates token in email link)
  ```
  - `POST /team/invite`: user must be on team plan; max 5 members
  - Sends invitation email with join link via email_worker
  - Invited member must create/have Latexy account
  - Invited members get pro-equivalent features while on team seat
  - Verify seat count: `SELECT COUNT(*) FROM team_seats WHERE owner_user_id = :uid AND status != 'removed'`

### 32F · Backend — Coupon Code Validation
- [ ] Add `POST /billing/validate-coupon`:
  ```python
  async def validate_coupon(code: str, plan_id: str) -> CouponValidationResponse:
      coupon = await db.execute(select(CouponCode).where(
          CouponCode.code == code.upper(),
          CouponCode.expires_at > datetime.utcnow() if CouponCode.expires_at else True,
      ))
      if not coupon or coupon.used_count >= (coupon.max_uses or float('inf')):
          return CouponValidationResponse(valid=False, message="Invalid or expired code")
      if coupon.applicable_plans and plan_id not in coupon.applicable_plans:
          return CouponValidationResponse(valid=False, message="Code not valid for this plan")
      return CouponValidationResponse(valid=True, discount_percent=coupon.discount_percent, ...)
  ```

### 32G · Frontend — Annual Billing Toggle
- [ ] In `frontend/src/app/pricing/page.tsx` (or wherever pricing is):
  - Add "Monthly / Annual" toggle with "20% off" badge for annual
  - Prices update dynamically when toggled
  - Annual: show crossed-out monthly price + "Save INR {amount}/year" tag

### 32H · Frontend — Coupon Code Input
- [ ] In subscription checkout flow:
  - Expandable "Have a coupon code?" section
  - Input + "Apply" button → calls `POST /billing/validate-coupon`
  - If valid: show "INR {discount} off applied ✓" with discount in summary

### 32I · Frontend — Student Plan CTA
- [ ] In pricing page: "Student? Get 50% off" card/button
  - Opens modal: enter .edu email → verification email sent → link activates student plan

### 32J · Frontend — Upgrade Prompts at Friction Points
- [ ] When anonymous user hits compile trial limit → show plan comparison modal
- [ ] When compile timeout hit (Feature 11) → show "Upgrade for 4× compile time" inline
- [ ] When deep analysis trial (2 uses) exhausted → show upgrade prompt
- [ ] When trying to use BYOK features without setting key → link to subscription page

### 32K · Tests
- [ ] `backend/test/test_subscriptions.py`:
  - Valid `.edu` email → student plan verification email sent
  - Non-`.edu` email for student plan → 400
  - Valid coupon code → discount_percent returned
  - Expired coupon → valid=false
  - Team invite → creates seat record + email sent
  - Invite when at seat limit (5) → 400

---

## Feature 33 — Job Board URL Scraper · P1 · M

**Goal:** User pastes a job posting URL (LinkedIn, Indeed, Greenhouse, Lever, Workday).
Backend scrapes title, company, description. Pre-fills the JD textarea in optimization panel.
Cache scraped JDs by URL hash. Uses `httpx` + `BeautifulSoup4` (already in requirements).

### 33A · Backend — Scraper Service
- [ ] Create `backend/app/services/job_scraper_service.py`:
  ```python
  import httpx
  from bs4 import BeautifulSoup
  import hashlib

  class JobScraperResult:
      title: Optional[str]
      company: Optional[str]
      description: Optional[str]
      url: str
      scraped_at: datetime
      error: Optional[str]

  class JobScraperService:
      # Platform-specific extractors
      EXTRACTORS = {
          "greenhouse.io": self._extract_greenhouse,
          "lever.co": self._extract_lever,
          "jobs.lever.co": self._extract_lever,
          "indeed.com": self._extract_indeed,
          "workday.com": self._extract_workday,
          "myworkdayjobs.com": self._extract_workday,
          "linkedin.com": self._extract_linkedin_fallback,  # LinkedIn requires login; use OG tags only
      }

      async def scrape(self, url: str) -> JobScraperResult:
          # 1. Check Redis cache
          cache_key = f"job_scrape:{hashlib.md5(url.encode()).hexdigest()}"
          cached = await cache_manager.get(cache_key)
          if cached:
              return JobScraperResult(**cached)

          # 2. Determine extractor by domain
          domain = urlparse(url).netloc.lstrip("www.")
          extractor = next((v for k, v in self.EXTRACTORS.items() if k in domain), self._extract_generic)

          # 3. Fetch page
          async with httpx.AsyncClient(
              headers={"User-Agent": "Mozilla/5.0 (compatible; Latexy/1.0)"},
              follow_redirects=True,
              timeout=15.0,
          ) as client:
              response = await client.get(url)
              if response.status_code != 200:
                  return JobScraperResult(url=url, error=f"HTTP {response.status_code}")
              soup = BeautifulSoup(response.text, "html.parser")
              result = extractor(soup, url)

          # 4. Cache for 24h
          await cache_manager.set(cache_key, result.__dict__, ttl=86400)
          return result

      def _extract_greenhouse(self, soup, url) -> JobScraperResult:
          # Greenhouse: <h1 class="app-title">Job Title</h1>
          # Company: from URL or <span> in header
          # Description: <div id="content">
          ...

      def _extract_lever(self, soup, url) -> JobScraperResult:
          # Lever: <h2 data-qa="posting-name"> or <h2 class="posting-headline">
          # Description: <div class="section-wrapper">
          ...

      def _extract_generic(self, soup, url) -> JobScraperResult:
          # Fallback: use Open Graph tags
          title = soup.find("meta", property="og:title")
          description = soup.find("meta", property="og:description")
          # Also try: <title>, structured data (ld+json)
          # Try to find <div class="job-description"> or similar
          job_div = (
              soup.find(id="job-description") or
              soup.find(class_=lambda c: c and "job-description" in c) or
              soup.find("article") or
              soup.find("main")
          )
          ...
  ```

### 33B · Backend — Scraper Endpoint
- [ ] Add `POST /scrape-job-description` to `backend/app/api/routes.py`:
  ```python
  class ScrapeJobRequest(BaseModel):
      url: str = Field(..., max_length=500)

  class ScrapeJobResponse(BaseModel):
      title: Optional[str]
      company: Optional[str]
      description: Optional[str]
      url: str
      cached: bool
      error: Optional[str]
  ```
  - Auth: optional (works for anon users on `/try` page too)
  - Validate URL: must start with `http://` or `https://`
  - Rate limit: 10 scrapes/min per IP (SlowAPI or Redis counter)
  - Handle errors gracefully — return partial results rather than 500

### 33C · Frontend — API Client
- [ ] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  scrapeJobDescription(url: string): Promise<ScrapeJobResponse>
  ```

### 33D · Frontend — URL Scraper UI
- [ ] In job description textarea (used in optimize page, try page, quick tailor modal):
  - Add a URL input row above the textarea:
    ```tsx
    <div className="flex gap-2 mb-2">
      <input
        type="url"
        placeholder="Paste job posting URL (LinkedIn, Indeed, Greenhouse...)"
        value={jobUrl}
        onChange={e => setJobUrl(e.target.value)}
        className="flex-1 text-sm ..."
      />
      <button
        onClick={handleScrapeUrl}
        disabled={!jobUrl || isScraping}
        className="..."
      >
        {isScraping ? <Spinner /> : "Import"}
      </button>
    </div>
    ```
  - `handleScrapeUrl`:
    1. Calls `apiClient.scrapeJobDescription(jobUrl)`
    2. On success: fills JD textarea with `result.description`
    3. Also fills company/role inputs if present and result has those fields
    4. Shows toast: "Imported from {result.company || 'job posting'}"
    5. On error: "Couldn't scrape this URL — paste the job description manually"
  - Support platforms note: "LinkedIn, Indeed, Greenhouse, Lever, Workday"

### 33E · Tests
- [ ] `backend/test/test_scraper.py`:
  - URL with Greenhouse domain → uses `_extract_greenhouse`
  - Cached URL → `cached=true`, no new HTTP request (mock httpx)
  - Non-200 response → returns `error` field, not 500
  - Invalid URL (not http/https) → 422
  - Rate limit: 11th request per IP → 429

---

## Feature 34 — Compile Queue Priority · P1 · S

**Goal:** Pro/BYOK users' compilation tasks get higher Celery queue priority, so they never
wait behind free-tier users during peak load. Priority badge shown in editor for pro users.

### 34A · Backend — Priority Helper
- [ ] In `backend/app/workers/latex_worker.py`, verify `get_task_priority()` exists:
  ```python
  def get_task_priority(user_plan: str) -> int:
      return {
          "free":  5,
          "basic": 6,
          "pro":   8,
          "byok":  8,
      }.get(user_plan, 5)
  ```
  - If this function doesn't exist yet, create it in `latex_worker.py`
  - Celery priority range: 0 (highest) to 9 (lowest) — higher number = higher priority in most brokers
  - Note: Redis-backed Celery uses `priority` on `.apply_async()` via task routing or `acks_late`

### 34B · Backend — Pass Priority in All Workers
- [ ] In `submit_latex_compilation()`: verify `priority=get_task_priority(user_plan)` is passed
  ```python
  compile_latex_task.apply_async(
      kwargs={...},
      queue="latex",
      priority=get_task_priority(user_plan),  # ensure this line exists
  )
  ```
- [ ] In `submit_resume_optimization()` in `llm_worker.py`:
  - Same: pass `priority=get_task_priority(user_plan)` to `.apply_async()`
- [ ] In `orchestrator.py` `submit_combined_job()`:
  - Pass `priority` to both the orchestrate task and any sub-tasks it spawns

### 34C · Backend — Queue Configuration for Priority
- [ ] In `backend/app/core/celery_app.py`:
  - Ensure Redis broker is configured for priority queues:
    ```python
    app.conf.broker_transport_options = {
        'priority_steps': list(range(10)),
        'sep': ':',
        'queue_order_strategy': 'priority',
    }
    ```
  - This is required for Redis-backed Celery priority to work correctly
  - Without this, `priority` parameter has no effect on Redis broker

### 34D · Frontend — Priority Badge in Editor
- [ ] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - If `user.subscription_plan` is `"pro"` or `"byok"`:
    ```tsx
    <span className="text-xs text-violet-400 bg-violet-500/10 border border-violet-500/20 rounded px-2 py-0.5">
      Priority Queue
    </span>
    ```
  - Show in editor toolbar next to compile button
  - Tooltip: "Your compilations are prioritized over free-tier users"
- [ ] Also show "Priority Compilation" in editor status bar for pro users

### 34E · Tests
- [ ] `backend/test/test_queue_priority.py`:
  - `get_task_priority("free")` returns 5
  - `get_task_priority("pro")` returns 8
  - `get_task_priority("byok")` returns 8
  - `get_task_priority("unknown")` returns 5 (fallback)
  - `submit_latex_compilation(user_plan="pro")` → `.apply_async()` called with `priority=8` (mock)
  - `submit_resume_optimization(user_plan="free")` → `.apply_async()` called with `priority=5` (mock)

---

## Cross-Feature Dependencies

```
Feature 9 (Compilers) requires:
  └── Feature 11 (Timeout) — both modify compile task; build together to avoid conflicts

Feature 21 (Developer API) requires:
  └── Features 9, 11, 34 — to expose correct compile capabilities

Feature 26 (Quick Tailor) requires:
  └── Feature 5 (P0) — fork system must be complete

Feature 27 (Before/After Comparison) requires:
  └── Feature 2 (P0) — DiffViewerModal must be complete

Feature 32 (Subscription Tiers) requires:
  └── Feature 19 (Email) — team invites need email sending

Feature 33 (URL Scraper) integrates into:
  └── Features 15, 17, 26 — all use JD textarea; scraper enhances all

Feature 15 (Job Tracker) integrates with:
  └── Feature 26 (Quick Tailor) — tracker cards can trigger tailoring

Recommended build order:
  1. Feature 34 (Queue Priority) — 1 day, pure config change
  2. Feature 11 (Timeout) — 1 day, config + worker change
  3. Features 34+11 can be done in same PR
  4. Feature 31 (Regex Find) — 1-2 days, frontend only
  5. Feature 30 (Snippets) — 1 day, frontend only
  6. Feature 27 (Before/After) — 2 days, frontend only
  7. Feature 19 (Email) — 3 days, backend worker impl
  8. Feature 9 (Compilers) — 1 week, migration + worker + UI
  9. Feature 10 (Shareable Links) — 1 week, migration + route + public page
  10. Feature 13 (Search) — 1 week, backend + UI
  11. Feature 14 (BibTeX) — 1 week, backend + UI
  12. Feature 16 (LinkedIn Import) — 2-3 days, prompt tuning
  13. Feature 20 (Font Editor) — 1-2 weeks, frontend only
  14. Feature 28 (Package Manager) — 1-2 weeks, frontend only
  15. Feature 29 (Linter) — 1-2 weeks, frontend only
  16. Feature 22 (Bullet Generator) — 1 week, new AI endpoint + widget
  17. Feature 24 (Summary Generator) — 1 week, new AI endpoint + widget
  18. Feature 23 (Writing Assistant) — 1-2 weeks, context menu + LLM + diff
  19. Feature 25 (Proofreader) — 1-2 weeks, rule-based service + decorations
  20. Feature 26 (Quick Tailor) — 1 week, backend fork+optimize + modal
  21. Feature 18 (Multi-Dim Score) — 1-2 weeks, scoring extension + radar chart
  22. Feature 17 (Interview Prep) — 1-2 weeks, Celery task + UI tab
  23. Feature 21 (Developer API) — 2-3 weeks, API keys + new endpoints + portal
  24. Feature 33 (URL Scraper) — 1-2 weeks, scraper service + UI
  25. Feature 32 (Subscriptions) — 2-3 weeks, Razorpay plans + team seats
  26. Feature 15 (Job Tracker) — 4-6 weeks, kanban board + full CRUD
```

---

## Shared Infrastructure Needed

- [ ] **`httpx`** — **NOT in `backend/requirements.txt`** — must add before implementing Features 14, 33
  - Add: `httpx==0.27.0` (async HTTP client for Crossref/arXiv/job-scraper calls)
  - `pip install httpx` then freeze to `backend/requirements.txt`
- [ ] **`@dnd-kit/core` + `@dnd-kit/sortable`** — not in `package.json` — needed for Feature 15 kanban
  - `pnpm add @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities`
- [ ] **`recharts`** — not in `package.json` — needed for Feature 18 radar chart
  - `pnpm add recharts`
  - Note: `framer-motion@^12.35.2` is already present (can use for animations instead of recharts transitions)
- [ ] **Rate limiting middleware** — `backend/app/middleware/rate_limiting.py` already has a full
  Redis-based `RateLimitMiddleware` — just not registered in `main.py`. Wire it up (needed for P0
  ATS/AI endpoints and P1 Features 13, 33). No SlowAPI dep needed.
- [ ] **Celery Beat scheduler** — for Feature 19 weekly digest
  - `celery==5.3.4` already present in requirements.txt — just needs schedule config in `celery_app.py`
  - `beautifulsoup4==4.12.3` already present — used directly by Feature 33 scraper
  - Production: run a separate `celery beat` process (`make run` docker-compose may need update)
- [ ] **Status bar layout** — Features 9 adds compiler indicator; Features 11 adds timeout badge;
  all should coordinate with P0's ATS badge and page count badge already in status bar
  - Recommended order: `[🔧 pdflatex] [Auto ●] [~2 pages ⚠] [ATS 74] [1,234 chars] [⌘S · ⌘↵]`
- [ ] **Preamble utility library** — Features 20, 28, 29, 30 all manipulate/read the LaTeX preamble
  - Centralize in `frontend/src/lib/latex-preamble.ts` (Feature 20 creates this; others import from it)
- [ ] **`frontend/src/lib/latex-linter.ts`** — Feature 29; import from Feature 30's completion provider
  to avoid duplicating LaTeX command knowledge
