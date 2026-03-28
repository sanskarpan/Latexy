# Latexy — Feature Catalog

> **Purpose**: Complete inventory of planned features — Overleaf parity, resume builder parity, advanced AI, editor improvements, and platform growth. Review this list to decide what to build next. Features are organized by category and annotated with priority tier and implementation complexity.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| **P0** | Ship immediately — conversion/retention blocker |
| **P1** | High value — build within 3–9 months |
| **P2** | Medium value — build within 9–18 months |
| **P3** | Future vision — 18+ months |
| **S** | Small — < 1 week, mostly frontend changes |
| **M** | Medium — 1–3 weeks, full-stack work |
| **L** | Large — 1–2 months, architectural changes |
| **XL** | Extra Large — 3+ months, major infrastructure |

---

## Table of Contents

1. [Overleaf Parity Features](#1-overleaf-parity-features)
2. [Resume Builder Parity Features](#2-resume-builder-parity-features)
3. [Advanced AI Features](#3-advanced-ai-features)
4. [Editor Features](#4-editor-features)
5. [Platform & Growth Features](#5-platform--growth-features)
6. [Priority Matrix](#6-priority-matrix)
7. [Market Gap Features](#7-market-gap-features) ← new, based on competitive research

---

## 1. Overleaf Parity Features

These are features that Overleaf provides and that users migrating from Overleaf will expect. Missing these creates friction and churn for power LaTeX users.

---

### 1.1 Template Gallery (50+ Templates)
**Priority:** P0 | **Complexity:** M

**Description:**
Latexy currently ships with exactly 2 resume templates — "Standard Professional" and "Engineering/CS". This is a critical conversion blocker. When a new user lands on `/workspace/new`, they need to immediately see the range of what Latexy can produce. Overleaf has 500+ templates; Kickresume has 40+; even basic resume builders offer 12–16 templates.

**What to build:**
- Expand `frontend/src/lib/latex-templates.ts` from 2 entries to 50+ full LaTeX templates
- Build a category-filter gallery UI on `/workspace/new` with categories: **Software Engineering**, **Finance & Banking**, **Academic / Research CV**, **Creative & Design**, **Minimal / Clean**, **ATS-Safe / Plain**, **Two-Column**, **Executive**, **Marketing & Sales**, **Medical / Healthcare**, **Legal**, **Graduate Student**
- Each template should have: a name, category tags, a thumbnail preview image (generated PNG from compiled PDF), and the full LaTeX source
- Add a "Preview" hover state that shows a large rendered preview before the user selects
- Templates stored as `is_template: true` resumes with `user_id = null` (global templates) OR per-user templates they've saved

**Why it matters:** 2 templates makes Latexy look unfinished. 50 templates signals production quality and dramatically improves the new-user experience. Templates are the #1 discovery mechanism — users come for a template and stay for the features.

---

### 1.2 Document Version History + Diff
**Priority:** P0 | **Complexity:** M

**Description:**
Users currently lose prior states between edit sessions. The only history that exists is the optimization history (showing `original_latex` vs `optimized_latex` per LLM run). But there is no mechanism to save a manual checkpoint, label it, and restore to it — or compare two arbitrary historical states.

**What to build:**
- Add a "Save Checkpoint" button in the editor header that prompts for a label (e.g., "Before tailoring for Google"), saves a snapshot using the existing `recordOptimization` endpoint
- Extend the existing HistoryPanel to support multi-selection of two entries
- Render a `MonacoDiffEditor` between the two selected snapshots in a side-by-side diff view
- Add "Restore to this version" action per snapshot
- Show a timeline view of all checkpoints with labels and timestamps
- Auto-save a snapshot on every compile (labeled "Auto-save — [timestamp]")
- The `optimization_history` table already has `original_latex`, `optimized_latex`, and `created_at` columns — no new schema needed

**Why it matters:** Users making drastic AI optimizations need confidence that they can roll back. Without version history, users are afraid to experiment. Overleaf's version history is one of its most-used premium features.

---

### 1.3 Compile-on-Save / Auto-Compile
**Priority:** P0 | **Complexity:** S

**Description:**
Currently users must click "Compile" or press Cmd+Enter to see the PDF output. Overleaf defaults to auto-compile mode where the PDF updates continuously as you type with a brief debounce. This is the core UX differentiator of online LaTeX editors.

**What to build:**
- Add an "Auto-Compile" toggle button in the editor status bar (default: off)
- When enabled, wrap the existing `runCompile()` call in a debounce (2 seconds after last keystroke)
- The `onSave` callback already fires in `LaTeXEditor.tsx` — wire it to trigger compile as well
- Persist the user's auto-compile preference in localStorage
- Show a subtle "Compiling..." badge in the status bar during debounced auto-compile runs

**Why it matters:** This is the single biggest UX quality-of-life feature. Very low implementation cost, very high perceived value.

---

### 1.4 Multiple LaTeX Compilers (XeLaTeX, LuaLaTeX)
**Priority:** P1 | **Complexity:** L

**Description:**
Latexy currently only runs `pdflatex`. However:
- **XeLaTeX** is required for templates using custom fonts via `fontspec`, right-to-left languages, or Unicode characters outside Latin-1
- **LuaLaTeX** is used for advanced typography, Lua scripting, and certain modern packages
- Many resume templates on CTAN specifically require XeLaTeX

The Docker texlive image already ships with all three compilers — this is purely a backend configuration and API change.

**What to build:**
- Add a `compiler` field to the job submission request (`pdflatex` | `xelatex` | `lualatex`)
- Modify `latex_worker.py` to accept the `compiler` parameter and pass it to the Docker `run` command
- Add a compiler selector dropdown in the editor toolbar
- Store compiler preference in the resume's `metadata` JSONB field
- Default to `pdflatex` for all existing resumes; upgrade is opt-in per-resume

**Why it matters:** A significant portion of the LaTeX template ecosystem is locked behind XeLaTeX. Without it, Latexy cannot compile ~30% of templates users might want to use.

---

### 1.5 Shareable Resume Links (Read-Only PDF URL)
**Priority:** P1 | **Complexity:** M

**Description:**
Currently users must download the PDF and send it as an email attachment. A shareable link enables direct sharing with recruiters, peer reviewers, or for embedding in portfolio sites.

**What to build:**
- Add a `share_token` UUID field to the `resumes` table (nullable, generated on demand)
- Add a "Share" button in the workspace card and edit page that generates and copies the share URL
- Create a public `/r/[token]` Next.js route that renders the resume PDF via the existing `PDFPreview` component
- Store the last compiled PDF path in MinIO (the `compilations` table's `pdf_path` field already exists)
- Add a "Revoke link" option that clears `share_token`
- Optional: 30-day expiry on links

**Why it matters:** Shareable links are the most basic sharing primitive. Also unlocks view tracking as a downstream capability.

---

### 1.6 Compile Timeout per Plan
**Priority:** P1 | **Complexity:** S

**Description:**
Complex resumes can exceed the default compilation timeout. Overleaf uses this as a premium differentiator: 10 seconds on free, 240 seconds on premium.

**What to build:**
- Define plan-based timeout limits in `config.py`: free=30s, basic=120s, pro/byok=240s
- In the job submission flow, determine the user's plan tier and pass the appropriate `time_limit` to the Celery task
- The `latex_compilation_task` already accepts `time_limit` and `soft_time_limit` — just wire them to plan tier
- When a timeout is hit, return `error_code: "compile_timeout"` with an upgrade CTA message

**Why it matters:** Low implementation cost, high monetization signal. Users hitting timeout are exactly the power users who need to upgrade.

---

### 1.7 Compilation History Diff Viewer
**Priority:** P1 | **Complexity:** M

**Description:**
Users want to compare LaTeX source changes between any two optimization runs. The HistoryPanel already displays a list of past runs; it needs multi-selection and side-by-side diff.

**What to build:**
- Extend HistoryPanel to support checkbox selection of any two history entries
- Render `MonacoDiffEditor` in a resizable split panel comparing `original_latex` of one entry to `optimized_latex` of the other
- Add colored diff statistics: "+N lines, -N lines, N sections changed"
- Add "Restore left" and "Restore right" action buttons within the diff view
- Share implementation with Version History (1.2) — build together

---

### 1.8 Project-Wide Search
**Priority:** P1 | **Complexity:** S

**Description:**
As users accumulate many resumes, finding content within them becomes impossible. Cross-resume search across the entire workspace.

**What to build:**
- New `GET /resumes/search?q=<query>` endpoint with Postgres full-text search on `latex_content` and `title`
- Return result snippets with resume title, matching line number, 2 lines of context, highlighted match
- Add Cmd+Shift+F search modal in the workspace page
- Clicking a result opens the resume editor with cursor positioned at the matching line

---

### 1.9 BibTeX Smart Import (DOI / arXiv)
**Priority:** P1 | **Complexity:** M

**Description:**
Academic users building CVs spend enormous time formatting bibliography entries. Direct DOI/arXiv lookup auto-fetches properly formatted BibTeX.

**What to build:**
- "References" panel tab in the editor sidebar
- Input field accepting DOI (e.g., `10.1145/3386569.3392408`) or arXiv ID (e.g., `2103.00020`)
- Backend endpoint `POST /references/fetch` hitting `api.crossref.org` (DOI) or `export.arxiv.org/api` (arXiv)
- Returns properly formatted BibTeX entry
- "Insert at cursor" button to append the BibTeX to the editor
- Support batch import: paste multiple DOIs separated by newlines

---

### 1.10 Spell Check & Grammar
**Priority:** P2 | **Complexity:** L

**Description:**
Spelling and grammar errors in a resume are career-damaging. Monaco doesn't natively spell-check prose embedded in LaTeX markup.

**What to build:**
- LaTeX-aware text extractor that strips commands to isolate prose content (partially available in `document_export_service.py`)
- Send extracted prose to LanguageTool REST API (free community tier) or WASM build client-side
- Register errors back as Monaco diagnostic markers via `monaco.editor.setModelMarkers()`, mapped to original LaTeX line numbers
- Misspellings: red squiggle; grammar suggestions: blue squiggle
- Right-click context menu on marked text shows suggestions with one-click apply
- Personal dictionary in localStorage

---

### 1.11 Symbol Palette
**Priority:** P2 | **Complexity:** S

**Description:**
A visual browser for LaTeX math symbols. Removes the biggest barrier to LaTeX adoption for academic CV users.

**What to build:**
- Toggleable sidebar panel with symbol search and categorized grid
- Categories: Greek letters, Math operators, Arrows, Relations, Set notation, Miscellaneous
- Each item shows Unicode symbol and LaTeX command on hover, package requirement in tooltip
- Click inserts at current cursor position via `editorRef.current`
- No backend changes required

---

### 1.12 GitHub / Git Integration
**Priority:** P2 | **Complexity:** L

**Description:**
Sync resume versions to a private GitHub repository as git commits. Developer users already trust git as their truth.

**What to build:**
- GitHub OAuth flow → connect GitHub account in Settings
- Per-resume "Enable GitHub Sync" toggle
- On every checkpoint save or optimization run, commit LaTeX source to linked GitHub repo
- Commit message: "Latexy checkpoint: [label] — [timestamp]"
- Pull changes made directly to GitHub back into Latexy
- The `optimization_history` table provides content for each commit

---

### 1.13 Compiler Settings per Resume
**Priority:** P2 | **Complexity:** M

**Description:**
Power users configure compiler, main entry file, and custom `latexmkrc` rules per document.

**What to build:**
- "Compile Settings" modal per resume
- Settings: compiler, TeX Live version, main `.tex` file, custom latexmk flags
- Store in resume's `metadata` JSONB field
- Pass settings forward to Celery task at compile time

---

### 1.14 Project-Level Tags & Organization
**Priority:** P2 | **Complexity:** S

**Description:**
The `Resume` model already has a `tags` array field — the workspace just doesn't expose it. Users need organization by job campaign, company, or status.

**What to build:**
- Tag assignment in workspace card context menu and edit page header
- Filter-by-tag sidebar in workspace page
- Pin/unpin favorites (`pinned: boolean` on resume)
- Archive action (`archived_at` field, soft-delete)
- Tag-based visual grouping with colored chips
- "My Templates" section for `is_template: true` resumes

---

### 1.15 Real-Time Collaboration (Multi-Cursor CRDT)
**Priority:** P2 | **Complexity:** XL

**Description:**
Multiple users editing the same resume simultaneously, each seeing the other's cursor and live changes. Overleaf's core premium value proposition.

**What to build:**
- **Yjs** CRDT library with `y-monaco` binding
- `y-websocket` provider to sync document state through WebSocket
- Each connected user gets unique cursor color and name label in the editor
- Document awareness: see who's currently editing and where their cursor is
- Role-based access: owner, editor, commenter, viewer
- Extends existing WebSocket infrastructure in `ws_routes.py` with a new document-sync channel

---

### 1.16 Track Changes (Accept/Reject)
**Priority:** P2 | **Complexity:** XL

**Description:**
When collaborators make edits, see each change highlighted with ability to accept or reject individually — like Microsoft Word Track Changes.

**What to build:**
- Built on top of the Yjs CRDT collaboration layer (1.15)
- Insertions: green with underline; deletions: red with strikethrough
- Accept/reject buttons on hover or in "Changes" sidebar panel
- "Accept All" and "Reject All" batch actions

---

### 1.17 Dropbox / Cloud Storage Sync
**Priority:** P3 | **Complexity:** L

**Description:**
Two-way sync with Dropbox. Every resume save syncs LaTeX source to `Dropbox/Apps/Latexy/` folder. Users can edit `.tex` locally and Latexy picks up changes on next open.

---

### 1.18 Zotero / Mendeley Reference Import
**Priority:** P2 | **Complexity:** L

**Description:**
Import an entire reference library from Zotero or Mendeley as a `.bib` file attached to the resume.

**What to build:**
- Zotero: OAuth → `api.zotero.org/users/{userId}/items?format=bibtex`
- Mendeley: OAuth → Mendeley API → export BibTeX
- Store `.bib` content in resume metadata
- "References" panel shows all entries; clicking inserts `\cite{key}` at cursor

---

### 1.19 WYSIWYG / Rich Text Editor Mode
**Priority:** P3 | **Complexity:** XL

**Description:**
Toggle from raw LaTeX to a visual WYSIWYG view where the resume renders inline. Users who don't know LaTeX format text using a toolbar and the platform generates LaTeX behind the scenes. Very high complexity due to bidirectional LaTeX ↔ DOM representation.

---

### 1.20 Mobile App (PWA First, Then Native)
**Priority:** P3 | **Complexity:** XL

**Description:**
PWA first: service worker caching, manifest for home screen installation, IndexedDB for offline drafts, background sync for queued compilations. React Native app in Phase 2. Monaco doesn't run on mobile — mobile view needs a simplified editing interface.

---

## 2. Resume Builder Parity Features

These are features that modern resume builders (Kickresume, Rezi, Teal, Novoresume, Enhancv, Jobscan) provide. Users comparing Latexy to these tools will notice these gaps.

---

### 2.1 Cover Letter Generator
**Priority:** P0 | **Complexity:** M

**Description:**
Cover letters are the second most common job application artifact. Users who have uploaded their resume and a job description have everything needed for an AI cover letter. This is a natural extension of the existing LLM optimization pipeline.

**What to build:**
- New Celery task `cover_letter_generation` on the `llm` queue in a new `cover_letter_worker.py`
- Prompt: resume LaTeX + job description → professional cover letter in matching LaTeX document class
- New page `/workspace/[resumeId]/cover-letter` with:
  - Job description textarea (reuses JD component from optimize page)
  - Tone selector: "Formal", "Conversational", "Enthusiastic"
  - Length selector: "3 paragraphs", "4 paragraphs", "Detailed"
  - Live streaming output in Monaco editor (reuses `useJobStream` + WebSocket streaming)
  - Compile the cover letter PDF inline
- Store cover letters linked to the resume (new `cover_letters` table with `resume_id` FK)
- "Generate Cover Letter" CTA in workspace resume card actions

**Why it matters:** Every job application needs a cover letter. Adding this converts Latexy from a resume tool to a full job application preparation platform. Very high upsell value.

---

### 2.2 Resume Variant / Fork System
**Priority:** P0 | **Complexity:** M

**Description:**
Power users maintain one master resume and create role-specific forks (e.g., "Master → Google SWE Variant", "Master → Startup CTO Variant"). Currently they must duplicate manually, losing the parent-child relationship.

**What to build:**
- Add `parent_resume_id UUID REFERENCES resumes(id) ON DELETE SET NULL` to the `resumes` table (one Alembic migration)
- "Create Variant" action in workspace card and edit page header — duplicates content with new title and sets `parent_resume_id`
- Workspace view groups variants under their parent with an expandable tree
- "Compare with Parent" action opens `MonacoDiffEditor` between variant and parent
- Show variant count badge on master resume card
- Variants are independent — they have their own optimization history, ATS scores, and can be further forked

**Why it matters:** Multi-application job search is the primary power-user use case. Variants with diff view is a unique feature no basic resume builder offers.

---

### 2.3 Real-Time ATS Score (Debounced)
**Priority:** P0 | **Complexity:** M

**Description:**
Currently, ATS score only appears after explicitly running the ATS pipeline. A lightweight debounced check against raw LaTeX text (no compilation needed) changes ATS from a post-hoc metric to a live writing signal.

**What to build:**
- New `POST /ats/quick-score` endpoint:
  - Accepts raw `latex_content` as text
  - Runs lightweight text-extraction + keyword-scoring pipeline on LaTeX source
  - Returns score (0–100) in < 500ms
  - No embeddings or deep analysis — just keyword presence + basic formatting checks
- Live "ATS" score badge in the editor status bar
- Debounce quick-score call at 10 seconds after last keystroke
- Clicking badge opens full ATS panel for deep analysis
- Color-code badge: green (≥80), amber (60–79), red (<60)

**Why it matters:** Changes ATS from a one-time quality gate to a continuous real-time signal. Users making manual edits get immediate feedback on whether changes improve or hurt their ATS score.

---

### 2.4 Job Application Tracker
**Priority:** P1 | **Complexity:** L

**Description:**
Users optimize multiple resume variants for different roles and lose track of which version they sent to which company. A kanban-style tracker turns Latexy from a writing tool into a career management platform.

**What to build:**
- New `job_applications` table: `id, user_id, company_name, role_title, status (applied|phone_screen|technical|onsite|offer|rejected|withdrawn), resume_id (FK nullable), ats_score_at_submission, job_description_text, notes, applied_at, updated_at`
- New `/tracker` page with:
  - Kanban board with status columns (drag-and-drop to move cards)
  - Each card: company logo (Clearbit API), role title, days since applied, linked resume variant, ATS score
  - "Add Application" modal: company, role, paste JD, link to a resume variant
  - Timeline view (alternative to kanban)
  - Statistics: applications per week, average ATS score by stage, stage conversion rates
- "Add to Tracker" button in workspace export dropdown

**Why it matters:** Teal, Huntr, and Notion job trackers are popular separate tools. Integrating job tracking into Latexy creates compelling daily retention. Users who track applications come back daily.

---

### 2.5 LinkedIn Profile Import (Structured)
**Priority:** P1 | **Complexity:** M

**Description:**
Most professionals have a more current LinkedIn profile than resume. LinkedIn PDF exports have a very specific structure that can be parsed with higher accuracy using LinkedIn-specific heuristics.

**What to build:**
- Extend `/formats/upload` with optional `source_hint=linkedin` parameter
- Custom LLM prompt in `DocumentConverterService` tuned for LinkedIn PDF structure:
  - LinkedIn PDFs always have: Experience with company/title/dates/description, Education, Skills, Certifications
  - Prompt explicitly maps LinkedIn section names to LaTeX resume sections
- "Import from LinkedIn" CTA with instructions: "LinkedIn → Me → View Profile → More → Save to PDF"
- Higher confidence parsing vs generic PDF import

---

### 2.6 Interview Question Generator
**Priority:** P1 | **Complexity:** M

**Description:**
After optimizing a resume, the natural next user action is interview prep. Generating role-specific questions closes the career preparation loop and significantly increases session depth.

**What to build:**
- New Celery task `interview_prep_generation` on the `llm` queue
- Given resume + job description → LLM generates:
  - 5 behavioral questions tailored to specific experience on the resume
  - 5 technical questions based on skills and technologies listed
  - 3 motivational questions about the specific company/role
  - 2 difficult questions based on gaps or unusual career moves
  - Each question includes: "What the interviewer is really assessing" + STAR/SOAR framework hint
- New "Interview Prep" tab in right panel of edit page
- Questions saved alongside the resume variant

**Why it matters:** Extends the user session from "optimize resume" to "prepare for interview" — doubling time spent in Latexy per job application. High upsell potential.

---

### 2.7 Multi-Dimensional Score Card
**Priority:** P1 | **Complexity:** M

**Description:**
The current ATS score covers keyword alignment but not writing quality, visual density, or content completeness. A richer score card gives more actionable feedback.

**What to build:**
- Extend deep analysis in `ats_scoring_service.py` with additional dimensions:
  - **Grammar Score** (0–100): grammatical error presence
  - **Bullet Clarity Score** (0–100): action-verb-led, quantified, appropriate length
  - **Section Completeness** (0–100): expected sections present for job type
  - **Page Density Score** (0–100): appropriate content density (not too sparse, not too dense)
  - **Keyword Density Score** (0–100): JD keyword coverage ratio
- Surface as a radar/spider chart in `DeepAnalysisPanel`
- `ATSDeepSection` in `event-types.ts` already has `strengths`/`improvements` structure — extend it

---

### 2.8 Email Notifications
**Priority:** P1 | **Complexity:** S

**Description:**
`email_worker.py` Celery queue is defined but sends no emails. Email re-engagement is a critical retention mechanism.

**What to build:**
- Dispatch email via `email_worker.py` after `job.completed` for opted-in users:
  - "Your resume optimization is complete" with link to view results
  - "Compilation succeeded" for long-running compilations
- Weekly digest (triggered by `celery-beat`): ATS score trend + top improvement suggestions
- Notification preferences page in Settings
- Email provider: Resend, SendGrid, or SES — add SMTP settings to `config.py`

---

### 2.9 Resume View Analytics (Link Tracking)
**Priority:** P2 | **Complexity:** M

**Description:**
When users share via shareable link (1.5), they want to know if recruiters opened it.

**What to build:**
- New `resume_views` table: `id, resume_id (FK), share_token, viewed_at, country_code (CHAR(2)), user_agent, referrer`
- Record view events on `/r/[token]` visits (debounced to prevent counting refreshes within 5 min)
- "Analytics" tab in share link modal: total views, views over time sparkline, country breakdown, referrer breakdown
- Privacy: store country only (no city or IP), no personal data about viewers

---

### 2.10 Multilingual Resume Translation
**Priority:** P2 | **Complexity:** M

**Description:**
Professionals applying to non-English markets need translated versions. The LLM pipeline can translate prose while preserving all LaTeX commands.

**What to build:**
- New `translation` job type on the `llm` queue
- Language selector in optimize panel (50+ languages via GPT-4o)
- LLM prompt: translate prose only, preserve all LaTeX commands, environments, and technical terms
- Translated resume saved as a new variant with title "[Original Title] — [Language]"

---

### 2.11 Salary Estimator from Resume
**Priority:** P2 | **Complexity:** M

**Description:**
Resume content + target role + location → AI estimates expected salary range.

**What to build:**
- Input: target job title + location (city/country)
- LLM call: given experience level, skills, and last role on resume → estimate market salary range
- Display: low/median/high range, percentile estimate, top skills contributing to estimate
- Disclaimer about estimates vs verified market data
- Free for all users (lightweight LLM call)

---

### 2.12 Industry-Specific ATS Calibration
**Priority:** P2 | **Complexity:** L

**Description:**
ATS systems and recruiter priorities vary significantly by industry. A Goldman Sachs role needs different keywords than a Series A startup role. The current ATS scorer is generic.

**What to build:**
- Extract company name and industry from job description (LLM call)
- Maintain industry-specific keyword weight profiles: Tech/SaaS, Finance/Banking, Healthcare, Consulting, etc.
- Apply industry weights when computing ATS keyword score
- Show industry label in ATS results: "Calibrated for: Technology / Enterprise SaaS"

---

### 2.13 Anonymous Resume Mode (Blind Review)
**Priority:** P2 | **Complexity:** S

**Description:**
Users sharing for peer review don't always want to reveal their identity. One-click anonymization redacts PII.

**What to build:**
- "Anonymous Mode" toggle in share link settings
- When enabled, shared PDF is generated with blanked: name, email, phone, address, LinkedIn URL, GitHub URL
- Original resume unmodified — anonymization applied only at render time
- Show "This resume has been anonymized for blind review" banner in shared view

---

### 2.14 Resume Freshness Tracker
**Priority:** P2 | **Complexity:** S

**Description:**
Resumes not updated in a long time lose relevance. Alerts prompt users to update.

**What to build:**
- "Last updated N days ago" indicator on workspace resume cards
- Color-code by staleness: green (<30 days), amber (30–90 days), red (>90 days)
- Weekly digest email includes staleness alerts
- Dashboard widget showing freshness status across all resumes

---

### 2.15 Bulk / Batch Resume Export (ZIP)
**Priority:** P2 | **Complexity:** S

**Description:**
Users who want to backup all resumes or send multiple versions to a recruiter need to download them all at once.

**What to build:**
- "Export All" button in workspace header
- Format selector: ZIP of PDFs, ZIP of TEX files, ZIP of DOCXs
- Backend: compile all resumes with latest cached PDF → zip → return as download stream
- Progress indicator during zip creation

---

## 3. Advanced AI Features

Differentiated AI features that neither Overleaf nor resume builders currently offer. These leverage Latexy's unique position at the intersection of LaTeX precision and AI pipeline.

---

### 3.1 AI LaTeX Error Explainer
**Priority:** P0 | **Complexity:** M

**Description:**
The current `LogViewer` displays raw pdflatex output. Lines like `! Undefined control sequence. l.47 \textbff{...}` are incomprehensible to non-LaTeX users. Abandonment after the first compile error is Latexy's highest-friction moment.

**What to build:**
- `parseLogErrors()` in `LaTeXEditor.tsx` already extracts error lines with line numbers and positions them as Monaco diagnostic markers
- Add a small "Explain" button that appears in the Monaco gutter next to each error marker
- Clicking "Explain" sends: raw pdflatex error message + surrounding 5 lines of LaTeX source → to `POST /explain-error` LLM endpoint
- Response: plain English explanation + suggested fix with corrected code
- "Apply Fix" button patches the editor content automatically
- Cache error explanations by error hash (same error → instant cached response)

**Why it matters:** This is Latexy's most impactful feature for reducing abandonment. Users who can't understand a compilation error leave and never come back. AI-explained errors with one-click fixes turn the most painful UX moment into a teaching moment.

---

### 3.2 Real-Time Page Count Warning
**Priority:** P0 | **Complexity:** S

**Description:**
The #1 resume mistake is exceeding one page. Users currently have no page count feedback without compiling.

**What to build:**
- After each successful compilation, extract page count from pdflatex log: `Output written on output.pdf (2 pages, 48237 bytes)` — the log parser already processes this
- Display page count badge in editor status bar: "1 page" (green), "2 pages" (amber + warning icon), "3+ pages" (red)
- Pre-compile heuristic: formula based on character count, section count, and estimated line heights
- When >1 page: inline notification "Your resume exceeds 1 page. Consider reducing content."
- "Trim to 1 page" AI quick-action button when >1 page detected

**Why it matters:** Zero backend changes. Pure frontend. Prevents the most common resume mistake.

---

### 3.3 Font & Color Visual Editor
**Priority:** P1 | **Complexity:** M

**Description:**
Non-LaTeX users cannot modify fonts or colors without understanding `\usepackage{fontspec}` or color definitions. A visual editor generates correct preamble code automatically.

**What to build:**
- "Design" panel tab in the editor sidebar
- **Font Picker**: dropdown of 30 most commonly used LaTeX resume fonts with correct `\usepackage{}` declarations
- **Accent Color Picker**: color wheel + preset palette → generates `\definecolor{accent}{HTML}{hex}` in preamble
- **Font Size Selector**: 10pt / 11pt / 12pt as `\documentclass` option
- **Margin Slider**: tight (0.5in) / normal (0.75in) / spacious (1in) → updates `\geometry{...}`
- Changes update the preamble section automatically and optionally trigger auto-compile
- "Reset to Template Defaults" button

**Why it matters:** Personalizing a template is the first thing users try to do. Without a visual editor, this requires LaTeX knowledge.

---

### 3.4 Developer Public API
**Priority:** P1 | **Complexity:** M

**Description:**
Agencies, ATS vendors, and developers want to embed resume generation in their own products programmatically. `api_access: boolean` is already a plan flag in `PricingCard.tsx`.

**What to build:**
- API key management page: generate, revoke, rotate API keys (separate from BYOK AI keys)
- API key authentication middleware: `Authorization: Bearer lx_sk_...`
- Rate limiting per plan: free=10 req/day, pro=1000 req/day, enterprise=unlimited
- Public API endpoints:
  - `POST /api/v1/resumes/compile` — compile LaTeX → PDF URL
  - `POST /api/v1/resumes/optimize` — LLM optimize → optimized LaTeX
  - `POST /api/v1/resumes/ats-score` — score LaTeX → JSON breakdown
  - `GET /api/v1/resumes/{id}/export/{format}` — export saved resume
- Developer portal: interactive docs (FastAPI OpenAPI auto-generates), code examples, live playground

---

### 3.5 AI Bullet Point Generator
**Priority:** P1 | **Complexity:** M

**Description:**
The hardest part of writing a resume is turning vague responsibilities into strong, quantified bullet points.

**What to build:**
- Floating "Bullet AI" widget appearing when cursor is on a `\item` line
- Input: job title (auto-detected from context) + brief responsibility description
- Output: 5 bullet options, each:
  - Starting with a strong action verb
  - Including a quantified impact where inferable
  - Using industry-appropriate keywords
  - Fitting in 1–2 lines
- Click to insert at `\item` cursor position
- Configurable tone: "Technical", "Leadership", "Analytical", "Creative"

---

### 3.6 AI Writing Assistant (In-Editor)
**Priority:** P1 | **Complexity:** M

**Description:**
Highlight any text → right-click context menu shows AI actions. Like Notion AI, but LaTeX-aware.

**What to build:**
- Monaco context menu extension: when text is selected, add AI actions:
  - **Improve** — rewrite for stronger impact and clarity
  - **Shorten** — condense to 50% fewer words preserving meaning
  - **Quantify** — add specific metrics and numbers
  - **Add Power Verbs** — replace weak verbs with strong action verbs
  - **Change Tone** — toggle formal/casual
  - **Expand** — add more detail and context
- Each action sends selected text + surrounding context to LLM → shows diff of proposed change
- User can accept, reject, or regenerate

---

### 3.7 AI Professional Summary Generator
**Priority:** P1 | **Complexity:** M

**Description:**
The professional summary is the hardest section to write — it must be concise, punchy, and targeted to the specific role.

**What to build:**
- "Generate Summary" button when cursor is in the summary/objective section
- Reads: entire resume content + optional target job title
- Generates 3 alternative professional summaries (2–3 sentences each) with different emphasis:
  - Technical skills emphasis
  - Leadership and impact emphasis
  - Unique differentiators emphasis
- User selects one to insert; can regenerate for more options
- "Tailor to job description" mode

---

### 3.8 AI Proofreader (Writing Quality)
**Priority:** P1 | **Complexity:** M

**Description:**
A resume-specific proofreader that checks for common writing weaknesses reducing recruiter impact.

**What to build:**
- Analysis runs on resume prose content, flags:
  - **Weak action verbs**: "responsible for", "helped with" → suggests "Led", "Engineered"
  - **Passive voice**: "systems were improved by" → "improved systems by 40%"
  - **Overused buzzwords**: "synergy", "leverage", "proactive" — suggests concrete alternatives
  - **Missing quantification**: bullets with no numbers or percentages
  - **Vague claims**: "improved performance significantly" — add a specific metric
  - **Inconsistent tense**: past roles use past tense, current role present tense
- Shown as Monaco decorations with category labels
- "Proofreader" panel tab lists all issues with quick-fix options

---

### 3.9 ATS Simulator + PDF Parse Pre-flight Check
**Priority:** P2 | **Complexity:** L

**Description:**
Two related but distinct capabilities. Layer 1 is LaTeX-source-level diagnostics (pre-compile warnings). Layer 2 is post-compile PDF text extraction — showing the user exactly what an ATS would extract from their compiled PDF before they submit it anywhere. Different ATS systems (Greenhouse, Lever, Workday, Taleo, iCIMS, Ashby) each have different parsing behavior which Layer 3 models.

**What currently exists:**
The ATS scoring pipeline (`ats_scoring_service.py`, `ats_quick_scorer.py`, `ats_worker.py`) operates entirely on LaTeX source text — it scores based on keyword presence and structural heuristics applied to the raw `.tex` content. The compile pipeline (`latex_worker.py`) returns only `{pdf_job_id, compilation_time, pdf_size, page_count}` — it never extracts or returns any text from the compiled PDF. This means users have no way to see what an ATS actually reads from their compiled output.

**Layer 1 — LaTeX Pre-flight Linter Rules (extend existing linter)**

Add these rules to `latex-linter.ts` (the linter already runs on source text, zero new infrastructure needed):

- **`missing-glyphtounicode`**: If `\input{glyphtounicode}` is absent from the preamble, flag a warning: "pdflatex will encode text as glyph IDs instead of Unicode — ATS parsers and copy-paste will produce garbled output. Add `\input{glyphtounicode}` and `\pdfgentounicode=1` to your preamble." Severity: `warning`, fixable: true (auto-insert the two lines before `\begin{document}`).
- **`multicol-ats-risk`**: If `\usepackage{multicol}` or `\begin{multicols}` is present, flag: "Two-column layouts are read left-to-right across both columns by most ATS systems, mixing your contact info with your work experience. Use a single-column layout for ATS-safe output." Severity: `warning`, fixable: false.
- **`fontawesome-ats-risk`**: If `\usepackage{fontawesome}` or `\usepackage{fontawesome5}` is detected, flag: "FontAwesome icon characters render as unrecognized symbols in ATS plain-text extraction. Replace icon bullets with standard `•` or text." Severity: `info`, fixable: false.
- **`tabular-layout`**: If `\begin{tabular}` is used outside a math/figure environment, flag: "Tabular environments used for layout cause content to be invisible or mis-ordered in ATS parsing. Consider using standard LaTeX spacing commands instead." Severity: `info`, fixable: false.

**Layer 2 — PDF Text Extraction ("Show What ATS Sees")**

After compilation succeeds, extract the actual text content from the compiled PDF and show it alongside the PDF preview:

- Backend: after `latex_worker.py` produces `resume.pdf`, run `pdftotext -layout resume.pdf -` (already available in the texlive Docker image) and include `extracted_text: str` in the compile result
- Alternatively use `pymupdf` (fitz) in Python: `doc.load_page(0).get_text("text")` — no subprocess needed
- New WebSocket event type `job.pdf_text_extracted` published after successful compile
- New panel tab "ATS View" in the editor sidebar: shows the raw extracted text in a monospace view with no formatting
- Diff-style highlighting: sections recognized correctly (green), sections that appear garbled or out of order (red), sections that are completely missing from the extraction (amber)
- "Copy ATS Text" button to manually paste into any external ATS scanner

**Layer 3 — Per-ATS Behavior Simulation**

Apply known parsing rules for major ATS platforms on top of the extracted text:

- Knowledge base of parse behaviors:
  - **Greenhouse**: generally good PDF parsing; multi-column layouts cause section mixing
  - **Taleo** (Oracle): notoriously bad with PDFs; prefers plain text input; tables and graphics cause field mis-assignment
  - **Workday**: good PDF parsing; doesn't recognize custom section names — must match expected section headers exactly
  - **Lever**: modern parser; handles most pdflatex PDF output well; struggles with custom fonts
  - **iCIMS**: moderate PDF support; known issues with special characters and accented letters
  - **Ashby**: good modern parser; minimal known issues
- ATS simulator panel: user selects target ATS → system applies platform-specific parse rules to the extracted text → shows "this is how [ATS] would read your resume"
- Highlights specific sections where that ATS would have parsing errors or drop content
- Concrete recommendations: "For Taleo: remove tables, use plain section headers matching 'Work Experience', 'Education', 'Skills'"
- Recommendation: apply `\input{glyphtounicode}` fix for all platforms (always safe)

**Implementation path (incremental):**
1. Add 4 linter rules to `latex-linter.ts` — 1 day, zero backend changes
2. Add `pdftotext` call in `latex_worker.py`, include in result, add WebSocket event — 1 day
3. Build "ATS View" panel tab in frontend — 2 days
4. Per-ATS simulation layer (Layer 3) — 1 week

---

### 3.10 One-Click Resume Tailoring
**Priority:** P1 | **Complexity:** M

**Description:**
Collapse the multi-step optimization flow into a single action for a specific job description.

**What to build:**
- "Quick Tailor" button in workspace resume card (next to Optimize)
- Modal: paste job description or URL (with scraper via feature 5.6)
- One click → full optimization pipeline with preset aggressive settings targeted to the JD
- Progress shown inline with streaming preview
- Result: new resume variant (automatic fork via feature 2.2)
- Original resume never modified

---

### 3.11 Before/After Optimization Comparison
**Priority:** P1 | **Complexity:** S

**Description:**
After AI optimization, users want side-by-side PDF comparison of before and after states.

**What to build:**
- "Compare PDFs" button in optimization completion notification
- Side-by-side view: original PDF left, optimized PDF right, synchronized scroll
- Visual diff overlay: highlight changed pages with colored border
- Toggle: "Show diff" / "Hide diff"
- Uses the existing `PDFPreview` component rendered twice

---

### 3.12 Resume Heatmap (Recruiter Attention Prediction)
**Priority:** P2 | **Complexity:** M

**Description:**
Overlay on PDF preview showing predicted recruiter attention zones. Research shows recruiters spend ~6 seconds on initial review.

**What to build (V1 — rule-based):**
- Apply attention weights from known recruiter behavior:
  - Top 20% of first page: highest weight (5x) — name and contact info
  - Section headers: high weight (3x)
  - First bullet under each job: high weight (2x)
  - Bold text anywhere: elevated weight (1.5x)
  - Bottom 30% of last page: lowest weight (0.3x)
  - Page 2+: progressively lower weight
- Render as colored overlay on PDF preview (red=high attention, blue=low attention)
- Toggle button: "Show Recruiter Heatmap" in PDF viewer toolbar

**V2 (future):** CNN trained on eye-tracking research datasets → actual attention map prediction.

---

### 3.13 Resume Score History Chart
**Priority:** P2 | **Complexity:** S

**Description:**
Track ATS score improvement over time across optimization cycles.

**What to build:**
- Sparkline chart in ATS panel showing score over time from `optimization_history` entries with recorded `ats_score`
- Improvement delta: "↑ 12 points since you started this resume"
- Dashboard: "Average ATS score across all resumes: 78 (+5 this month)"

---

### 3.14 AI Section Reordering
**Priority:** P2 | **Complexity:** M

**Description:**
Optimal resume section order depends on job type and career stage. New grads lead with Education; experienced engineers lead with Experience.

**What to build:**
- AI analysis of resume + job description → recommendation for section order
- "Suggested order for [role type]: Experience → Skills → Education → Projects → Certifications"
- One-click reordering: AI restructures `\section{}` blocks in LaTeX source
- Diff view showing reorder change before applying

---

### 3.15 Industry Keyword Density Map
**Priority:** P2 | **Complexity:** M

**Description:**
Visual representation of how well resume keywords match industry standard vocabulary for a given role.

**What to build:**
- Based on `job_description_analysis` endpoint which already extracts required and preferred keywords
- Tag cloud / grid visualization:
  - Present in resume: green background, larger text
  - Partially present (related word): amber background
  - Missing but required: red background, with suggestion of where to add them
- Clicking a missing keyword shows suggested resume locations

---

### 3.16 Resume Age Analysis
**Priority:** P2 | **Complexity:** S

**Description:**
Recruiters focus on the last 10 years. Older entries take valuable space. Age analysis flags entries that may hurt more than help.

**What to build:**
- Parse dates from LaTeX content (regex on date patterns like "2010–2013")
- Flag work experience entries older than 10 years with amber indicator
- Recommendation: "Consider removing or condensing your [Company] role (2008–2010)"
- Exception: don't flag prestigious institutions even if old

---

### 3.17 AI Custom Optimization Persona
**Priority:** P2 | **Complexity:** M

**Description:**
Replace/supplement the optimization level selector with intuitive persona presets.

**What to build:**
- Persona presets:
  - **Startup Mode**: Impact-focused, ownership language, punchy ("scaled", "built from 0 to 1")
  - **Enterprise Mode**: Professional, formal, process improvements, large-scale impact
  - **Academic Mode**: Publications-first, grant writing, formal, research contributions
  - **Career Change Mode**: Transferable skills emphasis, downplay irrelevant experience, industry reframing
  - **Executive Mode**: C-suite language, board-level impact, governance and strategy
- Each persona modifies the LLM system prompt for the optimization

---

### 3.18 Smart Date Formatting Standardizer
**Priority:** P2 | **Complexity:** S

**Description:**
Resumes with inconsistent date formats ("Jan 2020" vs "January 2020" vs "2020-01") look unprofessional.

**What to build:**
- "Standardize Dates" action in editor
- Detect all date patterns in LaTeX content
- User chooses consistent format: "Jan 2020" / "January 2020" / "2020-01" / "MM/YYYY"
- Apply transformation across all date occurrences
- Preview changes in diff view before applying

---

### 3.19 Publication List Auto-Generator
**Priority:** P2 | **Complexity:** M

**Description:**
Researchers maintain publication lists on Google Scholar and ORCID. Auto-generation from a public profile URL removes tedious manual formatting.

**What to build:**
- Input: Google Scholar profile URL or ORCID identifier
- Backend: fetch publications via SerpAPI (Google Scholar) or ORCID's public API
- Format each publication as a properly cited LaTeX `\bibitem` entry
- Generate complete `\begin{enumerate}` publications section sorted by year (descending) or citation count
- User filters: "Journal papers only", "Last 5 years only", "Exclude preprints"

---

### 3.20 Resume Confidence Score
**Priority:** P2 | **Complexity:** M

**Description:**
A holistic quality score measuring writing strength, professional presentation, and completeness — independent of any specific job description.

**What to build:**
- Composite score (0–100):
  - Writing quality (grammar, active voice, strong verbs): 30%
  - Completeness (expected sections present): 20%
  - Quantification rate (% of bullets with a number): 20%
  - Formatting consistency (date formats, spacing, capitalization): 15%
  - Section order appropriateness: 15%
- Separate "Quality Score" badge alongside ATS score
- Detailed breakdown on click with specific improvement actions

---

### 3.21 Career Path Visualization + Skills Gap Analysis
**Priority:** P3 | **Complexity:** XL

**Description:**
Beyond single-job matching, show users their career trajectory. Given a resume + target senior role, identify which skills to develop to reach that role in 2–3 years. Requires a career graph knowledge base and retrieval augmentation.

---

### 3.22 Resume Benchmarking (Anonymous Percentile)
**Priority:** P3 | **Complexity:** L

**Description:**
Anonymous comparison against other resumes in the same industry: "Your resume scores in the top 23% of Software Engineering resumes on Latexy." Only valuable when there's sufficient volume of anonymized resume data.

---

## 4. Editor Features

Deep LaTeX editor improvements that go beyond Overleaf's editor capabilities.

---

### 4.1 LaTeX Package Manager UI
**Priority:** P1 | **Complexity:** M

**Description:**
Adding LaTeX packages requires knowing exact package names. A visual browser for the CTAN package registry removes this barrier.

**What to build:**
- "Packages" panel tab in editor sidebar
- Search CTAN registry (via `ctan.org/pkg/[name]` API or local subset for top 500 packages)
- Each package shows: name, description, typical use case, usage example
- "Add to Preamble" button inserts `\usepackage{packagename}` in preamble
- Currently installed packages (auto-detected from preamble) shown with checkmarks
- Warning if a package conflicts with another already installed

---

### 4.2 LaTeX Linter (Real-Time Best Practices)
**Priority:** P1 | **Complexity:** M

**Description:**
A real-time linter detecting LaTeX anti-patterns, deprecated commands, and common mistakes as the user types — like ESLint for LaTeX.

**What to build:**
- Rule-based checker (debounced at 3 seconds) against editor content:
  - **Deprecated commands**: `\bf`, `\it`, `\rm` → `\textbf{}`, `\textit{}`, `\textrm{}`
  - **Wrong quote style**: `"quote"` → ` ``quote'' ` (LaTeX curly quotes)
  - **Hard-coded font size**: `{\large text}` instead of semantic markup
  - **Missing \label after \section**: warns if section has no label
  - **Over-nesting**: deeply nested environments
  - **Package order issues**: known conflicts (e.g., `hyperref` before `geometry`)
  - **Redundant spacing**: `\ ` after abbreviations mid-sentence
- Register as Monaco info/warning/error markers with specific rule codes
- "Auto-Fix All" button for safe automatic fixes

---

### 4.3 Smart Code Snippet Auto-Insert
**Priority:** P1 | **Complexity:** S

**Description:**
When the user types certain trigger sequences, auto-insert useful boilerplate. Expand existing completion provider in `LaTeXEditor.tsx`.

**What to build:**
- `\begin{itemize}` → auto-insert with `\item ` line and tab stop inside
- `\begin{enumerate}` → same
- `\begin{tabular}{lll}` → auto-insert header row and sample rows
- `doc` → full `\documentclass{...}` boilerplate
- `sec` → `\section{<cursor>}`
- `fig` → full `\begin{figure}` environment with `\includegraphics`, `\caption`
- `eq` → `\begin{equation}...\end{equation}`

---

### 4.4 Regex-Aware Find & Replace
**Priority:** P1 | **Complexity:** S

**Description:**
Monaco has built-in find/replace (Cmd+F / Cmd+H). Extend it with LaTeX-specific search modes.

**What to build:**
- "LaTeX-Aware Search" mode toggle in find widget
- When enabled, understands LaTeX scope:
  - "Find all section headers": `/\\section\{(.*?)\}/g`
  - "Find all \textbf content": `/\\textbf\{(.*?)\}/g`
  - "Find all \item bullets": `/\\item\s+(.*?)(?=\\item|\\end)/gs`
- Preset search patterns dropdown for common resume patterns
- "Replace all occurrences of company name" across entire resume

---

### 4.5 LaTeX Documentation Lookup Panel
**Priority:** P2 | **Complexity:** M

**Description:**
The existing hover provider shows a brief description for ~200 commands. For deeper documentation (full syntax, all options, examples), users need texdoc-level access.

**What to build:**
- Right-click on any LaTeX command → "Show Documentation" context menu
- Side panel with full documentation from a curated knowledge base
- Documentation includes: description, full syntax, all optional parameters, complete usage example, "See also" related commands
- Dedicated "Command Reference" panel accessible from sidebar with search

---

### 4.6 Keyboard Shortcuts Reference Panel
**Priority:** P2 | **Complexity:** S

**Description:**
A searchable popup (Cmd+? or help icon) showing all keyboard shortcuts in the editor.

**What to build:**
- Grouped by category: File, Edit, Compilation, Navigation, AI Actions
- Each entry shows key combination and description
- Searchable with instant filter
- "Customize Shortcuts" link to a settings page (future)

---

### 4.7 LaTeX Snippet Marketplace
**Priority:** P3 | **Complexity:** L

**Description:**
Community-shared LaTeX snippets: two-column skills tables, publication list templates, timeline experience formats, boxed summary sections. Users browse, preview, and install snippets directly.

---

### 4.8 Keyboard Macro System
**Priority:** P3 | **Complexity:** L

**Description:**
Record a sequence of editor actions and replay them as a named macro. Useful for repetitive formatting tasks. Requires custom implementation since Monaco doesn't natively support macro recording.

---

### 4.9 TikZ / Diagram Visual Editor
**Priority:** P3 | **Complexity:** XL

**Description:**
Drag-and-drop visual editor for TikZ diagrams (flowcharts, timelines, skill bars, network diagrams) that generates corresponding TikZ code. Useful for academic CVs and technical resumes.

---

### 4.10 QR Code Auto-Inserter
**Priority:** P2 | **Complexity:** S

**Description:**
Many modern resumes include a QR code linking to LinkedIn or portfolio. Requires `qrcode` LaTeX package.

**What to build:**
- "Insert QR Code" button in editor toolbar
- Input: URL (LinkedIn, GitHub, personal website)
- Inserts: `\usepackage{qrcode}` in preamble + `\qrcode[height=1.5cm]{https://...}` at cursor
- Client-side QR preview inline using a QR generation library

---

### 4.11 Resume Template Customizer
**Priority:** P2 | **Complexity:** M

**Description:**
Visual sidebar panel for adjusting template-level parameters without editing LaTeX directly.

**What to build:**
- Page margins slider
- Base font size radio (10pt / 11pt / 12pt)
- Section spacing selector (compact / normal / spacious)
- Column layout toggle (single / two-column) for applicable templates
- Each adjustment modifies specific preamble lines and triggers auto-compile for preview

---

### 4.12 Contact Info Formatter
**Priority:** P2 | **Complexity:** S

**Description:**
Standardize contact info formatting across the resume.

**What to build:**
- Normalize phone numbers to `+1 (555) 555-5555`
- Normalize LinkedIn URLs to `linkedin.com/in/username`
- Normalize GitHub URLs to `github.com/username`
- Lowercase emails
- One-click "Normalize Contact Info" action in editor

---

### 4.13 Browser Push Notifications
**Priority:** P2 | **Complexity:** S

**Description:**
When a long-running compilation or optimization completes while the tab is in the background, a push notification brings the user back.

**What to build:**
- Request notification permission on first compile
- After `job.completed` WebSocket event: trigger `Notification("Compilation complete", { body: "Your resume is ready to view" })`
- Works for both compilation and optimization jobs
- User-disableable in settings

---

## 5. Platform & Growth Features

Infrastructure, monetization, and growth features needed to scale the platform.

---

### 5.1 Advanced Subscription Tiers
**Priority:** P1 | **Complexity:** M

**Description:**
Current 4 tiers (free, basic, pro, byok) lack important commercial options.

**What to build:**
- **Annual billing**: 20% discount vs monthly. Add annual plan IDs to `config.py` (Razorpay already supports subscription intervals)
- **Student plan**: 50% discount with `.edu` email verification
- **Agency / Team plan**: $49/month for 5 seats with shared workspace (links to feature 5.2)
- **Coupon/promo code support**: discount codes for partnerships and student outreach
- **Conversion optimization**: show upgrade prompt at friction moments (compile timeout, trial limit hit, advanced feature blocked)

---

### 5.2 Team / Agency Workspace
**Priority:** P2 | **Complexity:** L

**Description:**
Career coaches managing 50+ client resumes need a team view. Recruiting agencies need to collaborate on candidate resumes.

**What to build:**
- New `workspaces` table: `id, name, owner_id (FK users), plan_id, max_members, created_at`
- New `workspace_members` table: `workspace_id, user_id, role (owner|editor|viewer), invited_at, joined_at`
- `workspace_resumes` join table: `workspace_id, resume_id, shared_by (user_id)`
- Workspace dashboard: grid of all shared resumes, member list, aggregated analytics
- Invite members by email
- Per-workspace billing billed to workspace owner

---

### 5.3 Custom Domain Resume Hosting
**Priority:** P2 | **Complexity:** L

**Description:**
Hosted portfolio page at `resume.yourname.com` (custom domain via CNAME) or `latexy.io/u/[username]`.

**What to build:**
- `/u/[username]` public portfolio page: display public resumes, PDFs, professional summary
- Optional custom domain: user adds CNAME record, Latexy verifies and routes to their portfolio
- Portfolio customization: theme, which resumes to show, contact form toggle
- Analytics: view count, time on page, CTA clicks

---

### 5.4 White-Label for Agencies / Career Centers
**Priority:** P3 | **Complexity:** XL

**Description:**
University career centers and recruiting agencies want to offer Latexy under their own brand. Requires full multi-tenancy: custom domains, custom branding (logo, colors), per-tenant user management, per-tenant billing.

---

### 5.5 Resume-to-Portfolio Site
**Priority:** P2 | **Complexity:** L

**Description:**
Auto-generate a static portfolio website from resume content.

**What to build:**
- "Generate Portfolio Site" action after resume is compiled
- Uses resume's JSON export (available via `document_export_service`) to populate a portfolio template
- Hosted at `latexy.io/u/[username]`
- Shows: professional summary, experience timeline, skills, projects, contact info
- Shareable link; auto-updates when resume is re-optimized

---

### 5.6 Job Board URL Scraper
**Priority:** P1 | **Complexity:** M

**Description:**
Currently users must manually copy-paste job descriptions. URL scraping eliminates this friction.

**What to build:**
- Input field accepting LinkedIn Jobs, Indeed, Greenhouse, Lever, Workday job posting URLs
- Backend `POST /scrape-job-description` endpoint using Playwright or Scrapy:
  - Fetches job posting page
  - Extracts job title, company name, full description
  - Returns: `{ title, company, description, url }`
- Extracted JD pre-populates optimization and ATS scoring panels
- Cache scraped JDs by URL hash to avoid re-scraping

---

### 5.7 Multi-Resume Merge
**Priority:** P2 | **Complexity:** M

**Description:**
Users with multiple specialized resumes want to merge the best sections into a master comprehensive resume.

**What to build:**
- "Merge Resumes" action in workspace header
- Multi-select: choose 2–4 resumes to merge
- Per-section selection: choose which resume's version of each section to keep
- Preview merged result in Monaco diff editor
- Save as a new resume

---

### 5.8 Reference Page Generator
**Priority:** P2 | **Complexity:** S

**Description:**
A separate references page in a matching LaTeX format, consistent with the main resume.

**What to build:**
- "Generate References Page" action in workspace actions menu
- Input: up to 5 references (name, title, company, email, phone, relationship)
- Generates complete LaTeX document with same `\documentclass` and color scheme as main resume
- Output as downloadable `.tex` file and compiled PDF

---

### 5.9 Watermark Control
**Priority:** P2 | **Complexity:** S

**Description:**
For sharing draft resumes for feedback, a watermark ("CONFIDENTIAL", "DRAFT", "For Review Only") prevents unauthorized forwarding.

**What to build:**
- "Add Watermark" option in PDF download/share settings
- Watermark options: "DRAFT", "CONFIDENTIAL", "For Review Only", custom text
- Applied via `draftwatermark` LaTeX package in the preamble at compile time
- Only applied when downloading/sharing — stored LaTeX source never modified

---

### 5.10 Compile Queue Priority
**Priority:** P1 | **Complexity:** S

**Description:**
Pro users shouldn't wait in the same compilation queue as free users during peak load.

**What to build:**
- Add `priority` parameter to Celery compilation task (Celery supports `priority` argument)
- Free users: `priority=5`; Basic: `priority=6`; Pro/BYOK: `priority=8`
- Pro users never wait behind free-tier users in the queue
- "Priority Compilation" badge in editor for pro users

---

### 5.11 Presentation / Beamer Support
**Priority:** P3 | **Complexity:** L

**Description:**
Extend Latexy beyond resumes to LaTeX Beamer presentations. Academic users who use Latexy for CVs could also use it for conference presentations. Requires Beamer-specific templates and a presentation preview mode in the PDF viewer.

---

### 5.12 Smart Import from Resume Builders
**Priority:** P2 | **Complexity:** M

**Description:**
Users migrating from Kickresume, Resume.io, or Novoresume can export in JSON Resume format. Latexy already supports JSON Resume import — this adds dedicated import wizards per platform.

**What to build:**
- "Import from Resume Builder" option in workspace new resume flow
- Step-by-step guides per platform: "In Kickresume, go to Settings → Export → JSON Resume format"
- Custom import hints per platform for higher-accuracy parsing
- Preview imported content before converting to LaTeX

---

### 5.13 One-Click Job Application Integration
**Priority:** P3 | **Complexity:** XL

**Description:**
Apply directly from Latexy to job postings on LinkedIn Easy Apply, Indeed Direct Apply, Greenhouse, and Lever. After optimizing the resume, click "Apply Now" → the job board's application form is pre-filled and the job tracker is updated automatically.

---

### 5.14 Recruiter / Agency View
**Priority:** P2 | **Complexity:** L

**Description:**
Separate recruiter interface for agencies managing multiple candidate resumes.

**What to build:**
- Candidate list with resumes and ATS scores
- Side-by-side candidate comparison
- Recruiter notes and ratings per candidate
- Share shortlisted candidates with clients via password-protected link
- Bulk operations: run ATS scoring on all candidates simultaneously

---

### 5.15 Resume Collaboration Comments
**Priority:** P2 | **Complexity:** L

**Description:**
Async line-level comments on a resume, like GitHub Pull Request reviews.

**What to build:**
- Comment threads per resume per line range: `resume_id, line_start, line_end, author_id, comment_text, resolved, created_at`
- Comments shown as Monaco gutter icons; clicking opens thread in side panel
- Share-for-review link gives reviewer comment-only access
- Email notification when new comment is left on a resume you own

---

### 5.16 Bulk Apply Package
**Priority:** P2 | **Complexity:** M

**Description:**
For job seekers applying to 10+ similar roles simultaneously, batch tailoring automates the multi-application workflow.

**What to build:**
- "Batch Tailor" action: input multiple JDs or URLs at once
- Parallel LLM optimization jobs for each JD → separate resume variant for each
- Progress board showing status of each tailoring job
- Download all variants as ZIP when complete
- Automatically adds each to job tracker with corresponding company/role

---

### 5.17 Dark Mode PDF Preview
**Priority:** P2 | **Complexity:** S

**Description:**
Dark mode viewing of the PDF preview to reduce eye strain during long editing sessions.

**What to build:**
- Toggle button in PDF preview toolbar: "Dark Preview"
- When enabled: apply `filter: invert(1) hue-rotate(180deg)` CSS to PDF canvas
- LaTeX source and actual PDF are unmodified — display-only

---

### 5.18 Compile Error History
**Priority:** P3 | **Complexity:** S

**Description:**
Track which compilation errors a user has encountered and fixed over time. Build a personal "error log" that helps users avoid repeating the same mistakes.

---

### 5.19 Print Preview Mode
**Priority:** P3 | **Complexity:** S

**Description:**
Preview how the resume looks when printed on a black-and-white printer. Shows the PDF with a grayscale CSS filter applied, revealing any color-dependent design choices as they'd appear in print.

---

### 5.20 Export to Canva / Figma
**Priority:** P3 | **Complexity:** M

**Description:**
Users who want a visually designed resume alongside the ATS-safe LaTeX version can export their resume content (structured JSON) to Canva or Figma for visual redesign. Uses Canva's Content Import API or Figma's plugin API to populate a resume design template.

---

## 6. Priority Matrix

### P0 — Ship Next (8 features, all within reach)

| # | Feature | Why Critical | Complexity |
|---|---------|-------------|------------|
| 1.1 | Template Gallery (50+ templates) | 2 templates kills new-user conversion | M |
| 1.2 | Document Version History + Diff | `optimization_history` table 80% done; users afraid to experiment | M |
| 1.3 | Compile-on-Save / Auto-Compile | Core LaTeX editor UX; already has `onSave` hook | S |
| 2.1 | Cover Letter Generator | Every job application needs one; full pipeline reuse | M |
| 2.2 | Resume Variant / Fork System | One migration field; unlocks entire multi-application workflow | M |
| 2.3 | Real-Time ATS Score (Debounced) | Changes ATS from one-shot to continuous signal | M |
| 3.1 | AI LaTeX Error Explainer | #1 abandonment moment; log parsing already done | M |
| 3.2 | Real-Time Page Count Warning | #1 resume mistake; zero backend changes | S |

### P1 — High Value (26 features)

1.4 Multiple LaTeX Compilers • 1.5 Shareable Resume Links • 1.6 Compile Timeout per Plan • 1.7 Compilation History Diff • 1.8 Project-Wide Search • 1.9 BibTeX Smart Import • 2.4 Job Application Tracker • 2.5 LinkedIn Profile Import • 2.6 Interview Question Generator • 2.7 Multi-Dimensional Score Card • 2.8 Email Notifications • 3.3 Font & Color Visual Editor • 3.4 Developer Public API • 3.5 AI Bullet Point Generator • 3.6 AI Writing Assistant • 3.7 AI Professional Summary Generator • 3.8 AI Proofreader • 3.10 One-Click Resume Tailoring • 3.11 Before/After Optimization Comparison • 4.1 LaTeX Package Manager UI • 4.2 LaTeX Linter • 4.3 Smart Snippet Auto-Insert • 4.4 Regex-Aware Find & Replace • 5.1 Advanced Subscription Tiers • 5.6 Job Board URL Scraper • 5.10 Compile Queue Priority

### P2 — Medium Value (35 features)

Shareable link analytics • Multilingual translation • Salary estimator • Industry ATS calibration • Anonymous resume mode • Freshness tracker • Bulk export • ATS simulator • Heatmap • Score history • Section reordering • Keyword density map • Age analysis • Optimization personas • Date standardizer • Publication list generator • Confidence score • Documentation lookup • Keyboard shortcuts panel • QR code inserter • Template customizer • Contact formatter • Push notifications • Team workspace • Custom domain hosting • Portfolio site • Smart resume builder import • Recruiter view • Collaboration comments • Bulk apply • Dark mode PDF • GitHub integration • Zotero import • Resume view analytics • Multi-resume merge

### P3 — Future Vision (11 features)

Real-time collaboration (CRDT) • Track changes • WYSIWYG editor • Mobile app • Dropbox sync • White-label • One-click job application • Beamer presentations • Career path visualization • Benchmarking • LaTeX snippet marketplace • Keyboard macros • TikZ visual editor • Compile error history • Print preview • Export to Canva/Figma

---

## 7. Market Gap Features

These features were identified through direct market research as genuine gaps — combinations that no existing product currently covers. They are prioritized for their market differentiation potential, not just incremental product improvement. These are the features that create a defensible moat.

---

### 7.1 Academic CV → Industry Resume Conversion
**Priority:** P1 | **Complexity:** M

**Description:**
PhD students, postdocs, and researchers transitioning to industry must convert a multi-page academic CV to a 1-page industry resume. This is one of the most articulated pain points in the CS/research community (constant threads on r/phd, r/MachineLearning, r/csgrad, r/AskAcademia). The conversion is not mere shortening — it requires a complete reframing of how accomplishments are described: publication counts become impact metrics, grant amounts become quantified achievements, teaching experience becomes leadership, conference presentations become speaking engagements.

**Why no good solution exists:**
- Generic AI resume tools (Rezi, Kickresume, Enhancv) are word-processing tools with no understanding of academic content structure
- **FirstResume.ai** is the only product specifically targeting this transition, but it is not LaTeX-native — it outputs Word/PDF, not `.tex` source
- The `document_converter_service.py` in Latexy explicitly tells the LLM to "preserve all dates, companies, achievements EXACTLY" — the opposite of what academic-to-industry conversion requires
- Researchers specifically are LaTeX users — they write papers in LaTeX, and many maintain their CV in LaTeX. This is Latexy's exact target user.

**What currently exists in Latexy:**
- `templates/academic/phd_applicant.tex` — academic template (not a conversion tool)
- `document_converter_service.py` LINKEDIN_SYSTEM_PROMPT — a special conversion mode exists as a pattern
- `llm_worker.py` `_create_optimization_prompt()` — generic optimizer with `custom_instructions` parameter available but unused for academic detection
- 3.17 "AI Custom Optimization Persona" has an "Academic Mode" toggle — but this only adjusts optimization tone for writing academic content, not converting from academic to industry format

**What to build:**

**Academic content detector (backend):**
- Detect academic CV indicators in LaTeX source:
  - `\section{Publications}`, `\section{Refereed Publications}`, `\section{Conference Papers}` → academic publications sections
  - `\bibliographystyle`, `\bibliography`, `\cite{}` → bibliography usage
  - `\section{Teaching}`, `\section{Teaching Experience}` → teaching sections
  - `\section{Grants}`, `\section{Fellowships}`, `\section{Awards & Honors}` → academic funding
  - `\section{Research}`, `\section{Research Interests}` → research sections
  - Long document: >2 pages (page count from compile result)
- `detect_academic_cv(latex_content) -> AcademicCVReport` in `ats_scoring_service.py` or a new `cv_detector.py`
- Returns: `is_academic_cv: bool`, `detected_sections: list[str]`, `estimated_pages: int`, `confidence: float`

**Conversion LLM prompt (new job type in `llm_worker.py`):**

The prompt must handle each academic section type with specific transformation rules:

```
Publications section:
  - Keep only the 2-3 most impactful or most recent publications
  - Reframe as: "Published research on [topic] in [venue] — [impact if available e.g., cited N times]"
  - If venue is top-tier (NeurIPS, ICML, CVPR, Nature, Science), keep venue name explicitly
  - Remove co-author lists, page numbers, DOIs

Teaching section:
  - Reframe as leadership/communication experience
  - "Taught [course] to [N] undergraduate students" → "Led instruction for [N] students in [topic], receiving [rating] course evaluations"
  - TA experience → "Mentored and evaluated [N] students"

Grants / Fellowships:
  - Dollar amounts are quantified achievements — keep them
  - "NSF Graduate Research Fellowship ($138,000)" stays prominent
  - "Received [grant] ($X) to fund research on [topic]"

Research Experience:
  - Focus on concrete deliverables and scale, not methodology
  - "Developed [system/model] that achieved [metric] improvement over baseline"
  - Remove: hypothesis-first framing, literature review language, hedged conclusions
  - Add: owned-outcome framing ("built", "shipped", "reduced", "improved by X%")

Conference Presentations:
  - "Presented research to [N] attendees at [venue]" → speaking experience signal

Page target:
  - Output must be 1 page for 0-10 years post-PhD, 2 pages for 10+ years
  - Prioritize: most recent 5 years; most impactful quantified results; skills relevant to target role
```

**New Celery task:**
- `cv_to_resume_task` on the `llm` queue (or a new `mode='cv_to_resume'` parameter on existing `latex_optimization_task`)
- Input: `latex_content`, `target_industry` (tech/finance/consulting/data-science/product), optional `target_role_description`
- Output: 1-page LaTeX resume (same `\documentclass` and template structure as input, not a new template)
- Streams tokens via existing WebSocket pipeline — no new infrastructure

**Frontend UI:**

- **Auto-detection banner**: after a resume is compiled and `is_academic_cv=true` is detected, show a banner in the editor: "This looks like an academic CV (N pages, publication list detected). Want to convert it to a 1-page industry resume?"
- **Conversion wizard modal** (triggered by banner or explicit button in editor header):
  - Step 1: Confirm academic → industry conversion (shows detected academic sections to be transformed)
  - Step 2: Select target industry (Tech/Software Engineering, Data Science/ML, Finance/Quant, Consulting, Product Management, Other)
  - Step 3: Optional job description paste (improves keyword targeting in the conversion)
  - Step 4: Conversion runs — streams result into a new resume variant (never overwrites original)
- Result page: side-by-side MonacoDiffEditor: original CV (left) vs converted resume (right) + both PDFs compiled

**Key differentiation vs. competitors:**
1. Output is actual LaTeX source (not Word/PDF) — user can continue editing, recompile, use linter, run ATS scoring
2. The conversion creates a new variant — original multi-page CV preserved for academic job applications
3. Industry targeting shapes the transformation — a ML PhD converting for a quant hedge fund gets different framing than one targeting a FAANG PM role
4. Integrates naturally with the ATS scoring pipeline — after conversion, immediately score the 1-page result against a job description

**Validation signal:**
- r/phd has repeated threads asking specifically about LaTeX CV → industry resume
- FirstResume.ai exists and charges $20+/month for the same use case without LaTeX output — confirms willingness to pay
- The academia-to-industry coaching market ($200–500/hour for career coaches) signals high value placed on this transition

---

### 7.2 DOCX Export Quality (Macro-Aware Conversion)
**Priority:** P1 | **Complexity:** M

**Description:**
LaTeX → DOCX export is already fully implemented in Latexy (`document_export_service.py` → `to_docx()`, `export_routes.py`, `ExportDropdown` in frontend). The feature exists and is wired end-to-end. However, the current pipeline has a quality ceiling that will produce poor output for the most popular resume templates:

**The current pipeline:**
`LaTeX source → regex strip (to_markdown()) → python-docx`

The Markdown intermediary stage uses regex to strip LaTeX commands. For resume templates that use custom macros like `\resumeSubheading{Company}{Dates}{Title}{Location}`, `\cventry{year}{degree}{institution}{}{}{}`, or tabular environments for two-column layouts — these get stripped to raw text or dropped entirely, losing the semantic structure.

**Why this matters right now:**
- Many job application portals (Taleo instances, some Workday configs, certain enterprise HR systems) reject PDF uploads and require `.docx`
- Overleaf has no DOCX export at all (GitHub issue #668, filed 2019, closed without implementation in 2025)
- Pandoc — the community's fallback — breaks on custom macros and two-column layouts, producing 70% quality output
- Latexy's DOCX export is the only clean solution in the market IF the quality is good enough for popular templates

**What to fix:**

**Tier 1 — Jake's Resume / standard single-column templates (highest priority):**
Jake's Resume (`sb2nov/resume` on GitHub, 7,900+ stars) and similar templates use these custom macros:
```latex
\resumeSubheading{Company}{Date}{Title}{Location}
\resumeItem{bullet text}
\resumeSubItem{key}{value}
\resumeItemListStart / \resumeItemListEnd
```
These map cleanly to Word document structure:
- `\resumeSubheading` → bold company name + right-aligned date on one line, italic title + location on next line (mimics standard Word resume formatting)
- `\resumeItem` → `List Bullet` style paragraph
- `\resumeSubItem` → bold key + normal value inline

Add macro-specific handlers to `DocumentExportService.to_docx()` that detect and convert these patterns before the regex-stripping stage:

```python
KNOWN_RESUME_MACROS = {
    'resumeSubheading': _convert_resume_subheading,  # → heading row + title row
    'resumeItem': _convert_resume_item,              # → List Bullet paragraph
    'resumeItemListStart': None,                     # → strip, open list context
    'resumeItemListEnd': None,                       # → strip, close list context
    'cventry': _convert_cv_entry,                    # moderncv format
    'cvevent': _convert_cv_event,                    # altacv format
    'job': _convert_job_entry,                       # common custom macro
}
```

**Tier 2 — Moderncv / AltaCV / two-column templates:**
These use `multicols` or side-by-side minipages. For DOCX output, collapse to single column (since DOCX itself cannot replicate multi-column resume layouts without complex sectioning). Add a pre-processing step that detects two-column structures and linearizes them: left column content first, then right column content.

**Tier 3 — Pandoc fallback path (optional):**
For templates that can't be handled by Tier 1/2 macro processing, add an optional Pandoc execution path in `document_export_service.py`:
- Run `pandoc --from=latex --to=docx input.tex -o output.docx` via subprocess
- If Pandoc is available and the result is non-empty, use it as fallback
- Note: Pandoc is not in the current Docker image — would require adding to `backend/Dockerfile`

**Quality target:**
A Jake's Resume or standard single-column template DOCX output should be usable as-is in Microsoft Word without needing manual cleanup. Formatting: correct section headers, correct bullet indentation, correct bold/italic on company names and dates. A recruiter opening the DOCX should see a recognizable resume, not a wall of unformatted text.

**Why this is worth building now:**
- The infrastructure is already in place — this is a quality improvement, not a new feature build
- DOCX export is the single most-asked-about LaTeX resume format question in community forums ("how do I submit my LaTeX resume to [portal that only accepts Word]")
- No competitor offers this. Overleaf hasn't shipped it in 6 years of open requests.
- Once quality is good, this becomes a pull marketing asset — "Latexy is the only place you can go from LaTeX source to ATS-quality DOCX in one click"

---

## Unique Differentiation Thesis

> **Latexy is the only platform where LaTeX precision, AI rewriting, ATS intelligence, and streaming compilation exist as first-class objects in a single real-time pipeline.**

Overleaf is a LaTeX editor that bolted on AI. Resume builders are drag-and-drop tools that tacked on LaTeX export as an afterthought. Latexy is built from scratch with the AI + ATS + LaTeX feedback loop as the core primitive. No competitor can replicate this without rebuilding from scratch.

The highest-ROI investments are features that **tighten this closed feedback loop**: Real-Time ATS as you type, Auto-Compile, AI Error Explainer, Cover Letter generation from the same resume, Version Diff to track AI improvements over time. Build these first.

The market gap features in Section 7 represent Latexy's strongest long-term moat: Academic CV conversion targets a user who is already a LaTeX power-user, is actively desperate for a solution, and has demonstrable willingness to pay. DOCX export quality makes Latexy the only viable choice for job seekers whose target portals reject PDFs. ATS parse pre-flight (Section 3.9) closes the loop between compilation and submission confidence — no LaTeX tool currently shows users what their compiled PDF actually looks like to a recruiter's ATS.
