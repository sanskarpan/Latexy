# P0 Feature Implementation Checklist

> Deep implementation guide for all 8 P0 features. Each item maps directly to the current codebase —
> file paths, specific functions, and exact changes. Work through features in dependency order.
>
> **Branch convention:** one branch per feature (e.g. `feature/template-gallery`)
> **Key files to know:** see `MEMORY.md` for architecture overview.

---

## Legend
- `[ ]` — not started
- `[x]` — done
- `[~]` — in progress
- Complexity: **S** = < 1 week | **M** = 1–3 weeks | **L** = 1–2 months

---

## Feature 1 — Template Gallery (50+ Templates) · P0 · M

**Goal:** Replace the 2-template hardcoded picker on `/workspace/new` with a full gallery UI backed by
a real `resume_templates` DB table with category filtering, thumbnail previews, and 50+ templates.

### 1A · Database Migration
- [x] Create `backend/alembic/versions/0004_add_resume_templates.py`
  - New table `resume_templates`:
    ```sql
    id UUID PK DEFAULT gen_random_uuid()
    name TEXT NOT NULL
    description TEXT
    category TEXT NOT NULL  -- values: software_engineering | finance | academic | creative |
                            --   minimal | ats_safe | two_column | executive | marketing |
                            --   medical | legal | graduate
    tags TEXT[] DEFAULT '{}'
    thumbnail_url TEXT       -- MinIO path: templates/{id}/thumbnail.png
    latex_content TEXT NOT NULL
    is_active BOOLEAN DEFAULT TRUE
    sort_order INTEGER DEFAULT 0
    created_at TIMESTAMPTZ DEFAULT NOW()
    ```
  - Indexes: `idx_templates_category ON resume_templates(category)`,
    `idx_templates_active ON resume_templates(is_active)`
  - Do NOT reuse the `resumes` table with `is_template=true`; templates are global, have no
    `user_id`, no optimization history, and need different fields

### 1B · Backend Model
- [x] Add `ResumeTemplate` SQLAlchemy model to `backend/app/database/models.py`
  - All columns from migration above
  - No relationships needed (templates are read-only data)

### 1C · Backend API — `template_routes.py`
- [x] Create `backend/app/api/template_routes.py` with `router = APIRouter(prefix="/templates")`
- [x] `GET /templates` — list templates
  - Optional query params: `?category=` (filter), `?search=` (ILIKE on name/tags), `?active_only=true`
  - Returns `List[TemplateResponse]`: id, name, description, category, tags, thumbnail_url, sort_order
  - Does NOT return `latex_content` in list (too heavy); only in single-get
  - Order: `sort_order ASC, name ASC`
- [x] `GET /templates/categories` — returns `{ category: str, count: int }[]` for UI tab counts
- [x] `GET /templates/{template_id}` — returns full `TemplateDetailResponse` including `latex_content`
- [x] `POST /templates/{template_id}/use` — authenticated; creates a new `Resume` cloning the
  template's `latex_content`; accepts `{ title?: str }` body; returns `{ resume_id: str }`
  - Sets `title = body.title or template.name`
  - Triggers `embed_resume_task` if OpenAI key available (same pattern as `resume_routes.py:POST /resumes/`)
  - Records `UsageAnalytics` event `template_used`
- [ ] Admin endpoints (guarded by `settings.ADMIN_SECRET_KEY` header): — _skipped; templates managed via seed script_
  - `POST /templates` — create template
  - `PUT /templates/{id}` — update template
  - `PATCH /templates/{id}/activate` / `deactivate`
  - `DELETE /templates/{id}`
- [x] Register router in `backend/app/main.py`: `app.include_router(template_router, prefix="/api")`

### 1D · Template Content — 50+ LaTeX files
- [x] Create directory `backend/app/data/templates/` with subdirectories per category
- [x] Write minimum **4 templates per category × 12 categories = 50 templates** (51 total)
  - Each template: complete compilable LaTeX document (has `\documentclass`, `\begin{document}`, `\end{document}`)
  - All templates should compile with `pdflatex` in the existing Docker texlive container
  - Categories and minimum counts:
    - `software_engineering/` — 6 templates (SWE, ML engineer, DevOps, fullstack, mobile, data)
    - `finance/` — 4 (investment banking, quant, accounting, fintech)
    - `academic/` — 5 (research CV, PhD applicant, postdoc, professor, STEM grad)
    - `creative/` — 4 (UX designer, product designer, art director, copywriter)
    - `minimal/` — 4 (ultra-clean, single-column minimalist variants)
    - `ats_safe/` — 4 (plain text friendly, zero tables/columns, max keyword density)
    - `two_column/` — 4 (classic two-column, sidebar skill bars, etc.)
    - `executive/` — 4 (C-suite, VP, director-level)
    - `marketing/` — 4 (growth marketer, brand manager, content strategist, PMM)
    - `medical/` — 4 (MD CV, nursing, biotech, clinical research)
    - `legal/` — 4 (attorney, law clerk, corporate counsel, paralegal)
    - `graduate/` — 4 (recent grad, bootcamp, MBA, career changer)

### 1E · Seed Script
- [x] Create `backend/app/scripts/seed_templates.py`
  - Reads all `.tex` files from `backend/app/data/templates/{category}/`
  - Upserts into `resume_templates` table (match on name + category to allow re-running)
  - Sets `sort_order` based on file sort order within each category directory
  - Run with: `cd backend && python -m app.scripts.seed_templates`
  - Document in `README.md` under "Initial setup"

### 1F · Thumbnail Generation
- [x] Create `backend/app/scripts/compile_templates.py` (combines thumbnail + PDF generation)
  - For each template in DB without a `thumbnail_url`:
    1. Write `latex_content` to temp file
    2. Run `pdflatex -interaction=nonstopmode` via subprocess
    3. Convert first page to PNG: use `pdftoppm -r 150 -png -singlefile` or `pdf2image`
    4. Resize to 400×566px (A4 aspect, preserving quality)
    5. Upload to MinIO bucket `templates` at key `{template_id}/thumbnail.png`
    6. Update `thumbnail_url` in DB
  - [x] Add `pdf2image` and `Pillow` to `backend/requirements.txt`
  - [x] MinIO storage via `backend/app/services/storage_service.py` (boto3 S3 client)

### 1G · Frontend — API Client
- [x] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  getTemplates(category?: string, search?: string): Promise<TemplateResponse[]>
  getTemplateCategories(): Promise<{ category: string; count: number }[]>
  getTemplate(id: string): Promise<TemplateDetailResponse>
  useTemplate(id: string, title?: string): Promise<{ resume_id: string }>
  ```
- [x] Add TypeScript types `TemplateResponse`, `TemplateDetailResponse`, `TemplateCategory` to
  `frontend/src/lib/api-client.ts` or `frontend/src/types/templates.ts`

### 1H · Frontend — TemplateCard Component
- [x] Create `frontend/src/components/TemplateCard.tsx`
  - Props: `template: TemplateResponse, onSelect: (id) => void, onPreview: (id) => void`
  - Shows: thumbnail image (with skeleton placeholder while loading), template name, category badge,
    "Use Template" button
  - Hover state: overlay with a larger "Preview" button (eye icon)
  - Category badge colors: each category gets a distinct color (match the color scheme)
  - `thumbnail_url` missing → show a LaTeX/code icon placeholder

### 1I · Frontend — TemplatePreviewModal Component
- [x] Create `frontend/src/components/TemplatePreviewModal.tsx`
  - Props: `templateId: string | null, onUse: (id) => void, onClose: () => void`
  - Fetches `GET /templates/{id}` when `templateId` changes (includes `latex_content`)
  - Left panel: template metadata (name, description, category, tags)
  - Right panel: thumbnail image at full resolution or placeholder
  - "Use This Template" CTA → calls `onUse(templateId)`
  - Keyboard: close on Escape
  - Loading skeleton while fetching

### 1J · Frontend — `/workspace/new` Page Redesign
- [x] Rewrite `frontend/src/app/workspace/new/page.tsx`
  - On mount: fetch `getTemplates()` and `getTemplateCategories()`
  - Top: title input (still required)
  - Category tab bar: "All" + one tab per category with count badge
    - Active tab filters displayed templates (client-side filter on already-loaded data)
  - Template grid: 3-column grid of `TemplateCard` components (responsive: 2 on tablet, 1 on mobile)
  - Search input above grid: filters by `template.name` and `template.tags` client-side
  - "Start from Blank" card always pinned first in "All" and "Minimal" tabs
  - "Import File" option (existing `MultiFormatUpload`) available as a tab/toggle
  - On "Use Template" click: calls `useTemplate(id, title)` → navigates to `/workspace/{resume_id}/edit`
  - Preview icon on card → opens `TemplatePreviewModal`

### 1K · Tests
- [x] `backend/test/test_template_routes.py`:
  - `GET /templates` — returns list, category filter works
  - `GET /templates/categories` — returns counts
  - `GET /templates/{id}` — returns latex_content
  - `POST /templates/{id}/use` — creates resume, returns resume_id, auth required
  - ~~`POST /templates` without admin key → 403~~ (admin endpoints not implemented)
- [x] At least 3 template `.tex` files that are known-compilable (51 total, all compile successfully)

---

## Feature 2 — Document Version History + Diff · P0 · M

**Goal:** Let users save named checkpoints, auto-save on compile, and compare any two historical
versions side-by-side in a Monaco diff editor.

### 2A · Database Migration
- [x] Create `backend/alembic/versions/0005_add_checkpoint_columns.py`
  - Add columns to `optimizations` table:
    ```sql
    ALTER TABLE optimizations ADD COLUMN checkpoint_label TEXT;
    ALTER TABLE optimizations ADD COLUMN is_checkpoint BOOLEAN DEFAULT FALSE NOT NULL;
    ALTER TABLE optimizations ADD COLUMN is_auto_save BOOLEAN DEFAULT FALSE NOT NULL;
    ```
  - Manual checkpoints: `original_latex = optimized_latex = current content`, `is_checkpoint=true`,
    `is_auto_save=false`, `optimization_level='checkpoint'`, `job_description=null`
  - Auto-saves: `is_auto_save=true`, `is_checkpoint=true`, `checkpoint_label='Auto-save'`
  - Regular optimizations: both flags `false` (no change to existing records)

### 2B · Backend Model Update
- [x] Update `Optimization` model in `backend/app/database/models.py`:
  - Add columns: `checkpoint_label: Mapped[Optional[str]]`, `is_checkpoint: Mapped[bool] = False`,
    `is_auto_save: Mapped[bool] = False`

### 2C · Backend API — New Endpoints in `resume_routes.py`
- [x] `POST /resumes/{resume_id}/checkpoints`
  - Auth required, verify resume ownership
  - Body: `{ label: str }` (required, max 100 chars)
  - Creates `Optimization` record:
    - `original_latex = resume.latex_content`
    - `optimized_latex = resume.latex_content`
    - `is_checkpoint = True`, `is_auto_save = False`
    - `checkpoint_label = body.label`
    - `optimization_level = "checkpoint"`, all other fields null/0
  - Returns `{ id: str, created_at: datetime, label: str }`
  - Rate limit: max 20 manual checkpoints per resume (enforce in endpoint)

- [x] `GET /resumes/{resume_id}/checkpoints`
  - Auth required, verify ownership
  - Returns full checkpoint list (checkpoints + auto-saves + optimizations) sorted by `created_at DESC`
  - New response schema `CheckpointEntry`:
    ```python
    id: str
    created_at: datetime
    checkpoint_label: Optional[str]
    is_checkpoint: bool
    is_auto_save: bool
    optimization_level: Optional[str]
    ats_score: Optional[float]
    changes_count: int
    has_content: bool   # True; tells frontend content is fetchable
    ```
  - Does NOT include `original_latex`/`optimized_latex` in list (too heavy)
  - Pagination: `?limit=50&offset=0`

- [x] `GET /resumes/{resume_id}/checkpoints/{checkpoint_id}/content`
  - Auth required, verify ownership of both resume and checkpoint
  - Returns `{ original_latex: str, optimized_latex: str, checkpoint_label: str }`
  - Used by diff viewer to load content on-demand (lazy — only load when user opens diff)

- [x] `DELETE /resumes/{resume_id}/checkpoints/{checkpoint_id}`
  - Auth required
  - Only allow deleting `is_checkpoint=true` entries (not regular optimization records — those have history value)
  - Soft delete: set `checkpoint_label = '[deleted]'`, or hard delete is fine

### 2D · Auto-Save on Compile
- [x] In `backend/app/workers/latex_worker.py`:
  - After successful compilation (before `publish_job_result`), fire async task:
    ```python
    from .auto_save_worker import record_auto_save_checkpoint
    if resume_id and user_id:  # only if we have both
        record_auto_save_checkpoint.apply_async(
            args=[resume_id, user_id, latex_content],
            queue="cleanup"  # lightweight, use cleanup queue
        )
    ```
  - The `resume_id` must be passed into `compile_latex_task` — add it as an optional parameter
  - In job_meta (Redis `latexy:job:{job_id}:meta`), store `resume_id` if present; read it in worker

- [x] Create `backend/app/workers/auto_save_worker.py`:
  ```python
  @celery_app.task(name='record_auto_save_checkpoint', queue='cleanup')
  def record_auto_save_checkpoint(resume_id: str, user_id: str, latex_content: str):
      # Insert into optimizations with is_checkpoint=True, is_auto_save=True
      # Label: f"Auto-save — {datetime.utcnow().strftime('%b %d, %H:%M')}"
      # Dedup: if latest optimization for this resume was auto-saved < 5 minutes ago, skip
      # Keep at most 20 auto-saves per resume (delete oldest if over limit)
  ```

### 2E · Frontend — DiffViewerModal Component
- [x] Create `frontend/src/components/DiffViewerModal.tsx`
  - Props:
    ```typescript
    {
      resumeId: string
      checkpointA: CheckpointEntry | null  // older (left)
      checkpointB: CheckpointEntry | null  // newer (right) — null = current resume
      currentLatex?: string                // used when checkpointB is null
      onRestore: (latex: string) => void
      onClose: () => void
    }
    ```
  - On open: fetch `GET /resumes/{id}/checkpoints/{cpA.id}/content` and optionally cpB
  - `MonacoDiffEditor` from `@monaco-editor/react` — original (left) vs modified (right)
    - Left = `original_latex` of older checkpoint
    - Right = `optimized_latex` of newer checkpoint (or `currentLatex`)
  - Panel header: left label (checkpoint name + date) and right label
  - Diff stats: computed from Monaco's `ILineChange[]` → "+N / -N lines"
  - "Restore Left" button → calls `onRestore(leftLatex)`
  - "Restore Right" button → calls `onRestore(rightLatex)`
  - Close button + Escape key handler
  - Loading skeleton while content fetches

### 2F · Frontend — VersionHistoryPanel Component
- [x] Create `frontend/src/components/VersionHistoryPanel.tsx` (find at `frontend/src/components/` or inline in
  optimize page) to support:
  - Fetch from new `GET /resumes/{id}/checkpoints` endpoint instead of old optimization-history
  - Each entry shows:
    - Type badge: "Manual Checkpoint" (bookmark icon, blue) | "Auto-save" (clock icon, zinc) |
      "AI Optimization" (sparkle icon, orange)
    - Label (checkpoint_label) or "AI Optimization — {optimization_level}"
    - Relative timestamp: "2 hours ago" (use `date-fns` or similar)
    - ATS score badge if present
    - Changes count if present
  - Checkbox on each entry (max 2 selections)
  - "Compare" button appears when exactly 2 are selected → opens `DiffViewerModal`
  - "Restore" button per entry → calls restore endpoint, updates editor content
  - "Delete" button for manual checkpoints only (with confirmation)
  - Timeline visual: vertical line with dots connecting entries

### 2G · Frontend — Save Checkpoint Button
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx` (and optimize page header):
  - Add "Save Checkpoint" button (bookmark icon) in editor header
  - Click → small inline popover (not modal): label text input + "Save" button + "Cancel"
  - On save: calls `POST /resumes/{id}/checkpoints`, shows toast "Checkpoint saved"
  - Input validation: label required, max 100 chars
- [x] Auto-save indicator in editor status bar: "Auto-saved N min ago" (updated after each
  successful compile, reading from last checkpoint's `created_at`)

### 2H · Tests
- [x] `backend/test/test_checkpoints.py`:
  - Create manual checkpoint, list it, fetch content, restore, delete
  - Auto-save deduplication (second call within 5 min is skipped)
  - Max 20 auto-saves per resume pruning
  - Cannot delete regular optimization records via checkpoint delete endpoint

---

## Feature 3 — Compile-on-Save / Auto-Compile · P0 · S

**Goal:** Toggle-able auto-compile that debounces 2 seconds after last keystroke, persisted in
localStorage. Zero backend changes.

### 3A · LaTeXEditor Component
- [x] In `frontend/src/components/LaTeXEditor.tsx`:
  - Add prop: `onAutoCompile?: (content: string) => void`
  - Inside `useEffect` where Monaco is initialized (after `editor` is created):
    ```typescript
    let autoCompileTimer: ReturnType<typeof setTimeout> | null = null
    const disposeContentChange = editor.onDidChangeModelContent(() => {
      if (!props.onAutoCompile) return
      if (autoCompileTimer) clearTimeout(autoCompileTimer)
      autoCompileTimer = setTimeout(() => {
        props.onAutoCompile!(editor.getValue())
      }, 2000)
    })
    return () => {
      disposeContentChange.dispose()
      if (autoCompileTimer) clearTimeout(autoCompileTimer)
    }
    ```
  - Guard: do not fire `onAutoCompile` if `editor.getModel()?.getValueLength() < 100` (avoid
    empty-doc compiles on initial load)

### 3B · Auto-Compile State Hook
- [x] Create `frontend/src/hooks/useAutoCompile.ts`:
  ```typescript
  // Manages auto-compile enabled/disabled state with localStorage persistence
  export function useAutoCompile() {
    const [enabled, setEnabled] = useState(() =>
      localStorage.getItem('latexy_auto_compile') === 'true'
    )
    const toggle = () => setEnabled(prev => {
      const next = !prev
      localStorage.setItem('latexy_auto_compile', String(next))
      return next
    })
    return { enabled, toggle }
  }
  ```

### 3C · `/try` Page Wiring
- [x] In `frontend/src/app/try/page.tsx`:
  - Add `const { enabled: autoCompile, toggle: toggleAutoCompile } = useAutoCompile()`
  - Pass `onAutoCompile={autoCompile && !isSubmitting ? (content) => runCompile('compile') : undefined}`
    to `LaTeXEditor`
  - Add "Auto" toggle button in editor toolbar area (next to Compile/Optimize buttons):
    - Shows: lightning bolt icon + "Auto" label
    - Active state: `bg-orange-500/20 text-orange-300 border-orange-500/30`
    - Inactive state: `text-zinc-500 border-white/10`
    - Tooltip: "Auto-compile on change (2s debounce)"
  - When auto-compile fires, set `isSubmitting = true` (blocks manual compile during auto)

### 3D · Edit/Optimize Pages
- [x] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Same `useAutoCompile` hook integration
  - Same "Auto" toggle button
  - `onAutoCompile` triggers compile-only (not optimize+compile)
- [x] In `frontend/src/app/workspace/[resumeId]/optimize/page.tsx`:
  - Auto-compile available; triggers compile-only (not the full optimize pipeline)
  - Show "Auto" toggle in editor toolbar

### 3E · Status Bar Indicator
- [x] In `frontend/src/components/LaTeXEditor.tsx` (or parent pages):
  - When `onAutoCompile` is defined (auto-compile active): show a subtle animated pulse dot +
    "Auto" label in editor status bar
  - While debounce is counting down (keystroke happened, timer running): show "Compiling in 2s..."
    fading text

---

## Feature 4 — Cover Letter Generator · P0 · M

**Goal:** AI-powered cover letter generation in LaTeX, matching the resume's style, with tone/length
controls and streaming output. Linked to a resume, stored in DB.

### 4A · Database Migration
- [x] Create `backend/alembic/versions/0006_add_cover_letters.py`
  - New table `cover_letters`:
    ```sql
    id UUID PK DEFAULT gen_random_uuid()
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL
    resume_id UUID REFERENCES resumes(id) ON DELETE CASCADE
    job_description TEXT
    company_name TEXT
    role_title TEXT
    tone TEXT DEFAULT 'formal'          -- formal | conversational | enthusiastic
    length_preference TEXT DEFAULT '3_paragraphs'  -- 3_paragraphs | 4_paragraphs | detailed
    latex_content TEXT
    pdf_path TEXT                       -- MinIO path after compilation
    generation_job_id TEXT              -- last job_id used for generation
    created_at TIMESTAMPTZ DEFAULT NOW()
    updated_at TIMESTAMPTZ DEFAULT NOW()
    ```
  - Indexes: `idx_cover_letters_user`, `idx_cover_letters_resume`

### 4B · Backend Model
- [x] Add `CoverLetter` SQLAlchemy model to `backend/app/database/models.py`
  - Relationship: `resume: Mapped[Resume] = relationship(back_populates="cover_letters")`
  - Add reverse relation on `Resume`: `cover_letters: Mapped[List["CoverLetter"]] = relationship(...)`

### 4C · LLM Prompt Design
- [x] Design cover letter system prompt (critical — determines quality):
  - Extract resume metadata: candidate name, current role, key skills from LaTeX
  - Extract from JD: company name, role title, key requirements
  - System prompt:
    ```
    You are an expert career coach and professional writer. Generate a cover letter in LaTeX format.

    REQUIREMENTS:
    - Use the SAME \documentclass, font packages, and color scheme from the resume preamble
    - Tone: {tone} (formal=professional/formal, conversational=warm/approachable, enthusiastic=energetic/passionate)
    - Length: {length} ({3_paragraphs: "3 focused paragraphs", 4_paragraphs: "4 paragraphs with more detail", detailed: "5+ paragraphs comprehensive"})
    - Structure: opening paragraph (interest + hook), body paragraphs (match skills to JD requirements), closing (CTA + next steps)
    - Include: date, company address block, salutation (use "Hiring Manager" if name unknown), signature block
    - Do NOT include: generic filler phrases, "I am writing to express interest", overused clichés
    - LaTeX: use \begin{letter}{} or article class with proper letter formatting
    - Output ONLY the complete LaTeX document, no explanations
    ```
  - Wrap output in `<<<LATEX>>>...<<<END_LATEX>>>` delimiters (same pattern as orchestrator.py)

### 4D · Cover Letter Worker
- [x] Create `backend/app/workers/cover_letter_worker.py`
  - Task `generate_cover_letter_task` on `llm` queue (reuse existing LLM queue — no infra changes)
  - Params: `resume_latex, job_description, tone, length_preference, job_id, user_id, cover_letter_id, user_api_key=None, model=None`
  - Event flow mirrors `llm_worker.py`:
    1. `job.started` → `job.progress` 5%
    2. Validate/get API key from `api_key_service`
    3. Build prompt (system + user message)
    4. OpenAI stream → publish `llm.token` for each delta
    5. Check cancellation every 20 tokens
    6. `llm.complete` with assembled LaTeX
    7. Save `latex_content` to `cover_letters` table (async DB update)
    8. `job.completed`
  - Error handling: `SoftTimeLimitExceeded`, rate limit retry (same as `llm_worker.py`)
  - Helper function: `submit_cover_letter_generation(...)` — enqueues task

### 4E · Cover Letter Routes
- [x] Create `backend/app/api/cover_letter_routes.py`
  ```
  POST /cover-letters/generate        — auth required
  GET  /cover-letters/{id}            — auth required
  PUT  /cover-letters/{id}            — auth required (update latex_content after manual edit)
  DELETE /cover-letters/{id}          — auth required
  GET  /resumes/{resume_id}/cover-letters  — auth required (list all for a resume)
  ```
  - `POST /cover-letters/generate`:
    - Body: `{ resume_id, job_description, company_name?, role_title?, tone, length_preference }`
    - Verify resume ownership
    - Create `CoverLetter` DB record with initial fields (latex_content=null)
    - Write initial Redis job state via `_write_initial_redis_state` (same as job_routes.py)
    - Fire `submit_cover_letter_generation(...)`
    - Return `{ job_id, cover_letter_id }`
  - `PUT /cover-letters/{id}`: allows updating `latex_content` (for manual edits post-generation)
- [x] Register router in `backend/app/api/routes.py`

### 4F · Frontend — Cover Letter Page
- [x] Create `frontend/src/app/workspace/[resumeId]/cover-letter/page.tsx`
  - Layout: 2-column (left sidebar config, right Monaco + PDF)
  - **Left sidebar:**
    - Company name input (text, optional)
    - Role title input (text, optional)
    - Job description textarea (large, required for best results; shows character count)
    - Tone selector: 3 pill buttons — "Formal" | "Conversational" | "Enthusiastic"
    - Length selector: 3 pill buttons — "3 Paragraphs" | "4 Paragraphs" | "Detailed"
    - "Generate Cover Letter" button (primary)
    - Progress bar + stage label (while `status === 'processing'`)
    - Collapsible log viewer (LogViewer component, same as optimize page)
  - **Right main:**
    - LaTeX editor (Monaco, read-only during generation; editable after)
    - Streaming via `streamingLatex` from `useJobStream` (same as optimize page)
    - "Compile PDF" button — triggers `apiClient.compileLatex(coverLetter.latex_content)`
    - PDF preview below editor (PDFPreview component)
    - "Download PDF" button
    - "Save Changes" button (if manual edits made post-generation)
  - **State management:**
    - `const { state: stream, cancel, reset } = useJobStream(activeJobId)`
    - On `stream.status === 'completed'`: save `latex_content` to DB via `PUT /cover-letters/{id}`
    - Show loading skeleton while fetching existing cover letters on mount
  - Route navigation: workspace resume card → actions dropdown → "Cover Letter" option

### 4G · Frontend — Workspace Integration
- [x] In `frontend/src/app/workspace/page.tsx`:
  - Add "Cover Letter" to resume card action dropdown (alongside "Edit" and "Optimize")
  - Link to `/workspace/{resumeId}/cover-letter`
  - If cover letters exist: show small badge count (e.g. "2 CLs") on resume card

### 4H · Frontend — API Client
- [x] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  generateCoverLetter(params: GenerateCoverLetterRequest): Promise<{ job_id: string; cover_letter_id: string }>
  getCoverLetter(id: string): Promise<CoverLetterResponse>
  updateCoverLetter(id: string, latex_content: string): Promise<CoverLetterResponse>
  deleteCoverLetter(id: string): Promise<void>
  getResumeCoverLetters(resumeId: string): Promise<CoverLetterResponse[]>
  ```

### 4I · Tests
- [x] `backend/test/test_cover_letter_routes.py`:
  - POST generate — creates cover_letter record, returns job_id
  - GET cover letter — auth ownership enforced
  - PUT update latex_content
  - DELETE
  - GET list for resume
- [x] `backend/test/test_cover_letter_worker.py`:
  - Task fires correct events (job.started, llm.token, llm.complete, job.completed)
  - Saves latex_content to DB on completion
  - Handles SoftTimeLimitExceeded gracefully

---

## Feature 5 — Resume Variant / Fork System · P0 · M

**Goal:** Users create role-specific forks of a master resume. Variants are linked to parent, can
be compared side-by-side with parent in a diff view, and are grouped in the workspace UI.

### 5A · Database Migration
- [ ] Create `backend/alembic/versions/0005_add_resume_parent.py`
  ```sql
  ALTER TABLE resumes ADD COLUMN parent_resume_id UUID REFERENCES resumes(id) ON DELETE SET NULL;
  CREATE INDEX idx_resumes_parent_id ON resumes(parent_resume_id);
  ```
- [ ] Update `Resume` model in `backend/app/database/models.py`:
  ```python
  parent_resume_id: Mapped[Optional[uuid.UUID]] = mapped_column(
      ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True, index=True
  )
  ```

### 5B · Backend Schema Updates
- [ ] Update `ResumeResponse` Pydantic schema in `resume_routes.py`:
  - Add `parent_resume_id: Optional[str] = None`
  - Add `variant_count: int = 0` (computed via subquery or separate count query)
- [ ] Update `GET /resumes/` list endpoint to:
  - Include `parent_resume_id` in each returned resume
  - Add optional `?parent_id=<uuid>` filter to list variants of a specific parent
  - Add `variant_count` to each resume (subquery: `SELECT COUNT(*) FROM resumes r2 WHERE r2.parent_resume_id = r.id`)

### 5C · Backend — Fork Endpoint
- [ ] Add `POST /resumes/{resume_id}/fork` to `backend/app/api/resume_routes.py`:
  - Auth required, verify ownership
  - Body: `{ title?: str }`
  - Creates new `Resume`:
    ```python
    new_resume = Resume(
        user_id=current_user_id,
        title=body.title or f"{parent.title} — Variant",
        latex_content=parent.latex_content,
        tags=parent.tags.copy(),
        parent_resume_id=parent.id,
        is_template=False,
    )
    ```
  - Triggers `embed_resume_task` for new resume
  - Returns full `ResumeResponse` of new resume
  - Records `UsageAnalytics` event `resume_forked`

### 5D · Backend — Variant Listing & Diff
- [ ] Add `GET /resumes/{resume_id}/variants`:
  - Auth required, verify ownership of parent resume
  - Returns `List[ResumeResponse]` of all direct children (where `parent_resume_id = resume_id`)
  - Ordered by `created_at DESC`

- [ ] Add `GET /resumes/{resume_id}/diff-with-parent`:
  - Auth required, verify ownership of variant
  - If `parent_resume_id` is null → 400 "This resume has no parent"
  - Fetches parent resume (verify parent also owned by same user)
  - Returns `{ parent_latex: str, parent_title: str, variant_latex: str, variant_title: str }`

### 5E · Frontend — DiffViewerModal (Reused from Feature 2)
- [ ] The `DiffViewerModal` from Feature 2 (2E) is designed generically enough to reuse here
  - Add a new usage mode: `mode: 'parent-diff'` where left = parent latex, right = variant latex
  - No checkpoint fetch needed in this mode — content passed directly
  - "Restore to Parent" button → calls update API to set variant's `latex_content = parent_latex`

### 5F · Frontend — Fork Action
- [ ] In `frontend/src/app/workspace/page.tsx`:
  - Add "Create Variant" to resume card actions dropdown
  - On click: small modal/popover with title input (pre-filled with `"${resume.title} — Variant"`)
  - "Create" → calls `forkResume(resume.id, title)` → navigates to `/workspace/{new_id}/edit`

- [ ] In `frontend/src/app/workspace/[resumeId]/edit/page.tsx`:
  - Add "Create Variant" button in editor header (fork icon)
  - Same inline title input + fork action

### 5G · Frontend — Workspace Grouping
- [ ] In `frontend/src/app/workspace/page.tsx`:
  - After fetching resumes, build variant map:
    ```typescript
    const masterResumes = resumes.filter(r => !r.parent_resume_id)
    const variantMap: Record<string, Resume[]> = {}
    resumes.filter(r => r.parent_resume_id).forEach(r => {
      variantMap[r.parent_resume_id!] ??= []
      variantMap[r.parent_resume_id!].push(r)
    })
    ```
  - Master resume cards: show "N variants" expandable badge if `variant_count > 0`
  - On expand: render variant cards indented below parent with a vertical connecting line
    (use CSS `border-left: 1px solid` on the indent container)
  - Variant cards show parent name as subtitle: "Variant of: {parent.title}"
  - Variant cards have "Compare with Parent" action → opens `DiffViewerModal`
  - "Create Variant" in both master and variant card dropdowns (variants can be further forked)

### 5H · Frontend — API Client
- [ ] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  forkResume(resumeId: string, title?: string): Promise<ResumeResponse>
  getResumeVariants(resumeId: string): Promise<ResumeResponse[]>
  getResumeDiffWithParent(resumeId: string): Promise<{ parent_latex: string; parent_title: string; variant_latex: string; variant_title: string }>
  ```

### 5I · Tests
- [ ] `backend/test/test_resume_variants.py`:
  - Fork creates new resume with correct parent_resume_id
  - Fork title defaults to "{parent} — Variant"
  - Can't fork another user's resume → 403
  - `GET /variants` returns only direct children
  - `GET /diff-with-parent` returns both latex contents
  - `GET /diff-with-parent` on resume with no parent → 400
  - List endpoint includes `variant_count`

---

## Feature 6 — Real-Time ATS Score (Debounced) · P0 · M

**Goal:** Live ATS score badge in the editor status bar, updating 10 seconds after the last
keystroke. Lightweight (<300ms) endpoint with no LLM or DB writes.

### 6A · Backend — Quick Score Service
- [x] Create `backend/app/services/ats_quick_scorer.py`
  - Function `quick_score_latex(latex_content: str, job_description: Optional[str] = None) -> QuickScoreResult`
  - `QuickScoreResult` dataclass: `score: int, grade: str, sections_found: List[str], missing_sections: List[str], keyword_match_percent: Optional[float]`
  - Algorithm (pure Python, no network calls, target < 50ms):
    ```
    1. Extract plain text from LaTeX (reuse existing utility from document_export_service.py)
    2. SECTION DETECTION (40 pts):
       - Detect section names from \section{...} commands in LaTeX
       - Expected sections: contact_info, experience/work, education, skills
       - Optional: projects, certifications, summary/objective, publications
       - Score: (required_found / 4) * 40
    3. CONTACT INFO CHECK (10 pts):
       - email regex match in text
       - phone regex match in text
       - Score: 5 pts each, max 10
    4. CONTENT QUALITY (20 pts):
       - Action verb count (match against ACTION_VERBS from ats_scoring_service.py)
       - Quantification: numbers/percentages in bullet points
       - Score: (action_verb_ratio * 10) + (quantification_ratio * 10)
    5. KEYWORD SCORE (30 pts, only if job_description provided):
       - Tokenize both texts (lowercase, split on non-alpha)
       - Remove stopwords (use simple 50-word list)
       - JD required keywords: top 30 by frequency minus stopwords
       - Match count / 30 * 30 pts
       - If no job_description: award 15 pts baseline (neutral)
    6. Total = section_score + contact_score + quality_score + keyword_score (0-100)
    7. Grade: A (≥90), B (80-89), C (70-79), D (60-69), F (<60)
    ```

### 6B · Backend — Quick Score Endpoint
- [x] Add `POST /ats/quick-score` to `backend/app/api/ats_routes.py`
  - New Pydantic models:
    ```python
    class QuickScoreRequest(BaseModel):
        latex_content: str = Field(..., max_length=200_000)
        job_description: Optional[str] = Field(None, max_length=10_000)

    class QuickScoreResponse(BaseModel):
        score: int               # 0-100
        grade: str               # A/B/C/D/F
        sections_found: List[str]
        missing_sections: List[str]
        keyword_match_percent: Optional[float]
    ```
  - Implementation:
    ```python
    @router.post("/quick-score", response_model=QuickScoreResponse)
    async def quick_score_ats(request: QuickScoreRequest):
        result = quick_score_latex(request.latex_content, request.job_description)
        return QuickScoreResponse(**result.__dict__)
    ```
  - No auth required (needed on `/try` for anonymous users)
  - No DB writes, no Redis, no Celery — pure synchronous function call
  - Add rate limiting: 20 req/min per IP (use SlowAPI or custom middleware)

### 6C · Frontend — useQuickATSScore Hook
- [x] Create `frontend/src/hooks/useQuickATSScore.ts`
  ```typescript
  export function useQuickATSScore(latexContent: string, jobDescription?: string) {
    const [score, setScore] = useState<number | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    useEffect(() => {
      if (!latexContent || latexContent.length < 200) return  // skip tiny content
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(async () => {
        setLoading(true)
        try {
          const result = await apiClient.quickScoreATS(latexContent, jobDescription)
          setScore(result.score)
        } catch {
          setError('Quick score failed')
        } finally {
          setLoading(false)
        }
      }, 10_000)  // 10 second debounce
      return () => { if (timerRef.current) clearTimeout(timerRef.current) }
    }, [latexContent, jobDescription])

    return { score, loading, error }
  }
  ```
  - Dependencies: only re-fire when `latexContent` or `jobDescription` meaningfully changes
  - Also expose `refetch()` for immediate on-demand score (e.g. after compile completes)

### 6D · Frontend — ATSScoreBadge Component
- [x] Create `frontend/src/components/ATSScoreBadge.tsx`
  ```tsx
  // Props: score: number | null, loading: boolean, onClick?: () => void
  //
  // Visual states:
  // - loading: small spinner + "ATS" label (zinc-500)
  // - null (no score yet): "ATS —" (zinc-600)  — appears after first edit
  // - score ≥80: "ATS 84" (emerald-400 background glow)
  // - score 60-79: "ATS 72" (amber-400)
  // - score <60: "ATS 41" (rose-400)
  //
  // Layout: fits in status bar (small, ~60px wide)
  // Transition: smooth color transition between score ranges
  // Tooltip: "Live ATS score (updates 10s after last change)"
  // Clickable: cursor-pointer, opens full ATS analysis on click
  ```

### 6E · Frontend — LaTeXEditor Status Bar Integration
- [x] In `frontend/src/components/LaTeXEditor.tsx`:
  - Add props: `atsScore?: number | null`, `atsScoreLoading?: boolean`, `onATSBadgeClick?: () => void`
  - In status bar (where char count is shown):
    ```tsx
    {(atsScore !== undefined || atsScoreLoading) && (
      <ATSScoreBadge
        score={atsScore ?? null}
        loading={atsScoreLoading ?? false}
        onClick={onATSBadgeClick}
      />
    )}
    ```

### 6F · Frontend — Page Integration
- [x] In `frontend/src/app/try/page.tsx`:
  - `const { score: quickScore, loading: quickScoreLoading } = useQuickATSScore(latexContent, jobDescription)`
  - Pass to `LaTeXEditor`: `atsScore={quickScore} atsScoreLoading={quickScoreLoading}`
  - `onATSBadgeClick`: scroll to/open the deep ATS analysis panel
  - After compile completes: call `refetch()` immediately (don't wait 10s after a compile)

- [x] Same in `frontend/src/app/workspace/[resumeId]/edit/page.tsx` and optimize page

### 6G · Frontend — API Client
- [x] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  quickScoreATS(latexContent: string, jobDescription?: string): Promise<QuickScoreResponse>
  ```

### 6H · Tests
- [x] `backend/test/test_ats_quick_score.py`:
  - Empty content → score low
  - Well-formed resume → score ≥70
  - Resume with JD → keyword_match_percent present
  - Too large content (>200KB) → 422
  - Performance: assert response time < 500ms (measure with time.time())

---

## Feature 7 — AI LaTeX Error Explainer · P0 · M

**Goal:** When Monaco shows a red error marker from a failed compile, a "Explain" code lens appears
at the error line. Click it → LLM explains the error in plain English + suggests a fix. "Apply Fix"
patches the editor in one click.

### 7A · Backend — Explain Error Endpoint
- [ ] Add `POST /ai/explain-error` to a new `backend/app/api/ai_routes.py`
  (or add to existing `routes.py`; prefer new file for clean separation)
  - Pydantic models:
    ```python
    class ExplainErrorRequest(BaseModel):
        error_message: str = Field(..., max_length=2000)
        surrounding_latex: str = Field(..., max_length=3000)  # 5 lines before + after error line
        error_line: int
        user_api_key: Optional[str] = None  # BYOK support

    class ExplainErrorResponse(BaseModel):
        explanation: str        # plain English, 1-2 sentences
        suggested_fix: str      # brief description of what to change
        corrected_code: str     # the corrected LaTeX snippet (just the affected lines)
        cached: bool
    ```
  - Implementation:
    1. Compute cache key: `sha256(error_message + surrounding_latex[:100]).hexdigest()[:16]`
    2. Check Redis: `CacheManager.get(f"error_explain:{cache_key}")`
    3. If cache miss: call LLM (gpt-4o-mini, non-streaming, `max_tokens=400`)
       - System: "You are a LaTeX expert helping non-expert users. Be concise and practical."
       - User:
         ```
         LaTeX compilation error at line {error_line}:
         Error: {error_message}
         Code context:
         {surrounding_latex}
         Respond with JSON only:
         {"explanation": "...", "suggested_fix": "...", "corrected_code": "..."}
         ```
    4. Cache result with TTL 86400s
    5. Return response
  - Auth: optional (both anonymous and authenticated users need error help)
  - Latency target: < 3s (gpt-4o-mini is fast for small prompts)
  - Error fallback: if LLM unavailable, return generic helpful message based on error pattern
    matching (e.g. "Undefined control sequence" → "You used a LaTeX command that doesn't exist...")

- [ ] Register `ai_router` in `backend/app/main.py`

### 7B · Backend — Error Pattern Fallback
- [ ] Create `backend/app/services/latex_error_patterns.py`
  - Dict of known LaTeX error patterns → human-readable explanations (no LLM needed for these):
    ```python
    ERROR_PATTERNS = {
        "Undefined control sequence": "You used a LaTeX command (\\something) that doesn't exist...",
        "Missing $ inserted": "LaTeX math mode error — a mathematical character was used outside $...$",
        "File not found": "A required file (like an image or include file) is missing...",
        "Runaway argument": "A curly brace { is opened but never closed...",
        "Missing } inserted": "You have an unclosed curly brace...",
        "Too many }'s": "You have an extra closing curly brace...",
        "Overfull \\hbox": "Some content is too wide for the line...",
        "Package not found": "A LaTeX package required by your document is not installed...",
    }
    ```
  - `get_fallback_explanation(error_message: str) -> Optional[str]`
  - Used when LLM is unavailable or as immediate pre-LLM response

### 7C · Frontend — API Client
- [ ] Add to `frontend/src/lib/api-client.ts`:
  ```typescript
  explainLatexError(request: ExplainErrorRequest): Promise<ExplainErrorResponse>
  ```

### 7D · Frontend — ErrorExplainerPanel Component
- [ ] Create `frontend/src/components/ErrorExplainerPanel.tsx`
  - Props:
    ```typescript
    {
      error: { line: number; message: string } | null
      explanation: ExplainErrorResponse | null
      loading: boolean
      onApplyFix: (correctedCode: string, errorLine: number) => void
      onClose: () => void
    }
    ```
  - Renders as a fixed panel at the bottom of the editor (slide up animation)
  - **Header:** error message (truncated), line number, close button (X)
  - **Loading state:** skeleton with "Analyzing error..." text
  - **Loaded state:**
    - "What went wrong" section: `explanation` text (plain English, styled nicely)
    - "How to fix it" section: `suggested_fix` text
    - Code block: `corrected_code` in Monaco-styled monospace with syntax highlight
    - "Apply Fix" button (primary, green) — replaces error line(s) with corrected code
    - "Dismiss" button (secondary)
  - Escape key closes panel
  - Do not render when `error === null`

### 7E · Frontend — LaTeXEditor Code Lens Integration
- [ ] In `frontend/src/components/LaTeXEditor.tsx`:
  - Add prop: `onExplainError?: (error: LogError, surroundingLatex: string) => void`
  - After `setModelMarkers(...)` is called (when log errors are parsed), register a Code Lens provider:
    ```typescript
    monaco.languages.registerCodeLensProvider('latex', {
      provideCodeLenses(model) {
        return {
          lenses: logErrors.map(err => ({
            range: new monaco.Range(err.line, 1, err.line, 1),
            id: `explain-${err.line}`,
            command: {
              id: 'latexy.explainError',
              title: '⚡ Explain this error',
              arguments: [err],
            },
          })),
          dispose: () => {}
        }
      }
    })
    ```
  - Register editor action `latexy.explainError`:
    ```typescript
    editor.addAction({
      id: 'latexy.explainError',
      label: 'Explain LaTeX Error',
      run(editor, error: LogError) {
        const model = editor.getModel()!
        const errorLine = error.line
        const startLine = Math.max(1, errorLine - 5)
        const endLine = Math.min(model.getLineCount(), errorLine + 5)
        const surrounding = model.getValueInRange(
          new monaco.Range(startLine, 1, endLine, model.getLineMaxColumn(endLine))
        )
        props.onExplainError?.(error, surrounding)
      }
    })
    ```
  - `logErrors` needs to be a `useRef` (mutable, accessed in closure) rather than local variable

### 7F · Frontend — Apply Fix Logic
- [ ] In parent pages (try/page.tsx, optimize/page.tsx, edit/page.tsx):
  - State: `explainTarget: LogError | null`, `errorExplanation: ExplainErrorResponse | null`, `isExplaining: boolean`
  - When `onExplainError` fires:
    1. Set `explainTarget` and `isExplaining = true`
    2. Call `apiClient.explainLatexError({...})`
    3. Set `errorExplanation`, `isExplaining = false`
  - "Apply Fix" handler (`onApplyFix(correctedCode, errorLine)`):
    ```typescript
    // Replace the error line content with corrected code
    editorRef.current?.executeEdits('explain-fix', [{
      range: new monaco.Range(errorLine, 1, errorLine, editor.getModel()!.getLineMaxColumn(errorLine)),
      text: correctedCode,
    }])
    setExplainTarget(null)
    setErrorExplanation(null)
    toast.success('Fix applied — try compiling again')
    ```
  - Render `<ErrorExplainerPanel>` below editor

### 7G · Tests
- [ ] `backend/test/test_ai_routes.py`:
  - POST explain-error → returns explanation, cached=false
  - POST same error again → cached=true (no LLM call)
  - Missing required field → 422
  - Content too long → 422

---

## Feature 8 — Real-Time Page Count Warning · P0 · S

**Goal:** After each successful compile, show an actual page count badge in the editor status bar.
Turn "2 pages" amber, "3+ pages" red. Offer a one-click AI trim action.
Zero new endpoints needed — piggybacks on existing job result payload.

### 8A · Backend — Extract Page Count in latex_worker.py
- [ ] In `backend/app/workers/latex_worker.py`:
  - Add `PAGE_COUNT_RE = re.compile(r'Output written on .*?\((\d+) page', re.IGNORECASE)` at module level
  - In the log parsing loop (where log lines are streamed), scan for the pattern:
    ```python
    page_count: Optional[int] = None
    for line in log_lines:
        m = PAGE_COUNT_RE.search(line)
        if m:
            page_count = int(m.group(1))
    ```
  - Include `page_count` in `publish_job_result` payload:
    ```python
    await publish_job_result(job_id, {
        "status": "completed",
        "pdf_path": pdf_path,
        "compilation_time": elapsed,
        "pdf_size": pdf_size,
        "page_count": page_count,  # ADD
    })
    ```
  - Also emit in the `job.completed` event so it's available before the result is fetched:
    ```python
    publish_event(job_id, "job.completed", {
        "percent": 100,
        "pdf_job_id": job_id,
        "page_count": page_count,  # ADD
    })
    ```

- [ ] Same extraction needed in `orchestrator.py` (which also runs pdflatex):
  - `orchestrator.py` calls pdflatex and streams `log.line` events — add same `PAGE_COUNT_RE` scan
  - Include `page_count` in its `job.completed` event and `publish_job_result` call

### 8B · Backend — Event Schema Update
- [ ] In `backend/app/models/event_schemas.py`:
  - Add `page_count: Optional[int] = None` to `JobCompletedEvent`
  - Add `page_count: Optional[int] = None` to job result schema if one exists

### 8C · Frontend — useJobStream Update
- [ ] In `frontend/src/hooks/useJobStream.ts`:
  - Add `pageCount: number | null` to `JobStreamState` initial state
  - In `job.completed` reducer case:
    ```typescript
    case 'job.completed':
      return { ...state, status: 'completed', pageCount: action.payload.page_count ?? null }
    ```
  - Also: scan `logLines` in `log.line` handler for page count pattern as early signal
    (before `job.completed` fires):
    ```typescript
    case 'log.line': {
      const match = action.payload.line?.match(/Output written on .+?\((\d+) page/)
      if (match) newState.pageCount = parseInt(match[1])
      ...
    }
    ```

### 8D · Frontend — LaTeXEditor Status Bar
- [ ] In `frontend/src/components/LaTeXEditor.tsx`:
  - Add props: `pageCount?: number | null`
  - In status bar (right side, alongside char count and ATS badge):
    ```tsx
    {pageCount !== null && pageCount !== undefined && (
      <span className={cn(
        "text-xs font-medium px-2 py-0.5 rounded-md",
        pageCount === 1
          ? "text-emerald-400 bg-emerald-500/10"
          : pageCount === 2
          ? "text-amber-400 bg-amber-500/10"
          : "text-rose-400 bg-rose-500/10 animate-pulse"
      )}>
        {pageCount} {pageCount === 1 ? 'page' : 'pages'}
        {pageCount > 1 && ' ⚠'}
      </span>
    )}
    ```

### 8E · Frontend — Page Overflow Warning Banner
- [ ] In `frontend/src/app/try/page.tsx` and edit/optimize pages:
  - When `stream.pageCount && stream.pageCount > 1`:
    - Show inline warning banner between editor toolbar and editor:
      ```tsx
      <div className="flex items-center justify-between px-4 py-2 bg-amber-500/10 border-b border-amber-500/20">
        <span className="text-xs text-amber-400">
          ⚠ Your resume is {stream.pageCount} pages. Most recruiters prefer 1 page.
        </span>
        <button
          onClick={handleTrimToOnePage}
          className="text-xs text-amber-300 hover:text-amber-100 underline"
        >
          Trim with AI →
        </button>
      </div>
      ```
  - "Trim with AI" handler:
    - Calls the existing optimize pipeline with `custom_instructions`:
      `"Condense this resume to fit on exactly ONE page. Prioritize recent and most impactful content.
       Remove less critical details, condense bullet points, reduce descriptions. Do NOT remove any
       job titles, companies, degrees, or institution names."`
    - Sets `optimization_level = "aggressive"` (most condensing)
    - Follows the same flow as clicking "Optimize Resume"

### 8F · Frontend — Pre-Compile Heuristic (Bonus)
- [ ] Add lightweight client-side page count estimate in `LaTeXEditor.tsx`:
  - On every `onDidChangeModelContent` (debounced at 3s):
    ```typescript
    const estimatePageCount = (content: string): number => {
      // Rough heuristic: count \item lines, \section lines, and text lines
      const lines = content.split('\n').filter(l => !l.trim().startsWith('%'))
      const textLines = lines.filter(l => !l.trim().startsWith('\\') || l.includes('item'))
      return Math.max(1, Math.round(textLines.length / 50))  // ~50 text lines per page
    }
    ```
  - Show as `~N pages` in status bar before first successful compile
  - Replace with actual count (`pageCount` prop) once a compile completes
  - Only show estimated count if `pageCount` prop is null

### 8G · Tests
- [ ] `backend/test/test_latex_worker.py` — add assertion:
  - Successful compile result includes `page_count` field
  - Page count is correct for known test fixtures (1-page template → 1, 2-page → 2)
- [ ] `backend/test/test_orchestrator.py` — same assertion on orchestrator's job result

---

## Cross-Feature Dependencies

```
Feature 2 (Version History)
  └── depends on: nothing; but DiffViewerModal component is reused by Feature 5

Feature 5 (Fork System)
  └── DiffViewerModal from Feature 2 — build 2 first (or build DiffViewerModal standalone)

Feature 4 (Cover Letter)
  └── depends on: nothing from P0 features; reuses useJobStream, WebSocket, Monaco patterns

Feature 6 (Quick ATS Score)
  └── ATSScoreBadge used in LaTeXEditor — LaTeXEditor props must be extended

Feature 8 (Page Count)
  └── LaTeXEditor status bar — must not conflict with Feature 6 ATSScoreBadge additions
  └── Should extend status bar alongside Feature 6 badge (they both live in status bar)

Recommended build order:
1. Feature 3 (Auto-Compile) — trivial, S complexity, pure frontend, can ship in 1-2 days
2. Feature 8 (Page Count) — S complexity, mostly backend log parsing + frontend badge
3. Feature 6 (Quick ATS) — M but self-contained; makes all editors smarter immediately
4. Feature 5 (Fork/Variant) — M, single migration + straightforward CRUD
5. Feature 2 (Version History) — M, builds DiffViewerModal shared with Feature 5
6. Feature 1 (Templates) — M but content-heavy; template writing takes time
7. Feature 7 (Error Explainer) — M, needs Code Lens API knowledge + caching
8. Feature 4 (Cover Letter) — M, most complex due to new Celery task + new DB table + new page
```

---

## Shared Infrastructure Needed

- [x] **`MonacoDiffEditor`** — import from `@monaco-editor/react`; needed by Features 2 and 5.
  Verify it's in `package.json`; add if missing: `pnpm add @monaco-editor/react`
- [ ] **SlowAPI rate limiting** — for `/ats/quick-score` and `/ai/explain-error` endpoints.
  Add `slowapi` to `backend/requirements.txt`; configure limiter in `backend/app/main.py`
- [x] **`pdf2image` + `Pillow`** — for thumbnail generation in Feature 1.
  Add to `backend/requirements.txt` (only needed in scripts, not main app)
- [x] **Alembic migrations must run in order** — Features 1–5 each add a migration. Run all before
  testing any feature: `cd backend && alembic upgrade head`
- [x] **`cover_letter` celery task** — uses existing `llm` queue, no new queue configuration needed
- [~] **Status bar layout** — Features 3, 6, and 8 all add elements to `LaTeXEditor` status bar.
  Coordinate layout: `[Auto ●] [~2 pages ⚠] [ATS 74] [1,234 chars] [⌘S save · ⌘↵ compile]`
