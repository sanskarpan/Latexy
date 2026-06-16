# Latexy TUI — Design Specification

**Version:** 2.0 (complete rewrite — Hermes-style React+Ink architecture)
**Date:** 2026-06-15
**Status:** Approved for implementation

---

## Table of Contents

1. Executive Summary
2. Goals and Success Metrics
3. User Personas
4. Architecture Overview
5. Confirmed Tech Stack
6. Interaction Model
7. State Management Design
8. WebSocket and Streaming Design
9. Slash Command Registry
10. Tool Registry (all 35 feature domains)
11. Component Architecture
12. Store Design
13. Distribution and Packaging
14. CI/CD and Non-Interactive Mode
15. Non-Functional Requirements
16. Testing Strategy
17. Implementation Plan (3 Phases)

---

## 1. Executive Summary

Latexy TUI is a **standalone terminal application** that exposes every Latexy feature — resume management, LaTeX compilation, AI optimization, ATS scoring, BYOK key management, analytics, billing, job application tracking, cover letters, interview prep, and more — through a **Hermes-style React+Ink chat interface** with slash command shortcuts.

Users install it once (`npm install -g latexy`) and get full access to the Latexy SaaS from any terminal, SSH session, or CI/CD pipeline. It is a first-class product, not a wrapper script.

### Why this architecture?

- **React + Ink** (TypeScript): The same stack as Hermes Agent TUI — proven for rich streaming terminal UIs, excellent component model, `@inkjs/ui` component library, `incrementalRendering` for 60fps streaming.
- **Direct WebSocket connection** to Latexy's existing `/ws/jobs` endpoint — no Python subprocess gateway needed (Latexy's backend is already a remote API, not embedded).
- **Agent + slash commands**: Natural language input routes to an AI agent (backed by any BYOK provider) that uses all Latexy APIs as tools; `/compile`, `/optimize`, `/ats`, etc. are direct shortcuts that skip the AI.
- **Standalone npm package**: `npm install -g latexy`, `npx latexy`, and Homebrew tap — no Python runtime, no Docker, no dependencies beyond Node.js 22+.

### Research basis

This spec is grounded in parallel deep-dives of:
- **Hermes Agent TUI** (`nousresearch/hermes-agent`) — full architecture, gateway protocol, slash commands, streaming, nanostores
- **OpenCode TUI** (`sst/opencode`) — SolidJS+OpenTUI, daemon pattern, SSE batching, route model
- **Ink v7 ecosystem** — `incrementalRendering`, `ink-virtual-list`, `@inkjs/ui`, `ink-testing-library`
- **CLI packaging standards** — tsup, pnpm workspaces, Changesets, Homebrew releaser, OIDC npm publishing

---

## 2. Goals and Success Metrics

| Goal | Metric |
|------|--------|
| **G1 — Full feature parity** | All 35 feature domains available via agent or slash command |
| **G2 — Streaming-first** | `log.line` events appear in < 100ms; `llm.token` renders at ~60fps |
| **G3 — Zero-friction install** | `npm install -g latexy` works on macOS/Linux/Windows in < 30s |
| **G4 — CI/CD compatibility** | Every command supports `--json` flag; exit codes 0/1/2 |
| **G5 — Agent quality** | Free-text prompts ("compile my SWE resume for Google") complete in < 3 tool calls |
| **G6 — Offline awareness** | Clear degraded state when backend unreachable; retry command available |

**Phase 1 acceptance:** user can log in, list resumes, compile with streaming logs, download PDF.
**Phase 2 acceptance:** all 35 domains work interactively via slash commands.
**Phase 3 acceptance:** agent mode handles multi-step tasks; CI job passes; Homebrew formula ships.

---

## 3. User Personas

### Persona 1 — Power User ("Riya")
Software engineer, lives in Neovim + tmux. Edits LaTeX in `$EDITOR`, wants instant compile feedback without leaving the terminal. Uses AI optimization before every job application.
**Needs:** fast resume list, `$EDITOR` integration, streaming compile logs, ATS score display.

### Persona 2 — DevOps / Sysadmin ("Marcus")
Manages a self-hosted Latexy instance over SSH. Monitors Celery queue health, Redis connectivity, worker failures.
**Needs:** system health panel, feature flag toggling, job queue monitoring, cleanup trigger.

### Persona 3 — CI/CD Pipeline ("automated-pipeline")
GitHub Actions runner. Checks out LaTeX resume, compiles, optimizes for a target job, saves PDF artifact, reports ATS score.
**Needs:** `--json` mode, exit codes, environment variable credentials, no terminal rendering.

### Persona 4 — Developer ("Priya")
Latexy API integrator. Tests job submissions, watches WS event sequences, inspects Redis state.
**Needs:** job detail view, raw event JSON inspector, BYOK key rotation, live event stream.

---

## 4. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     latexy (npm package)                            │
│                                                                     │
│  packages/tui/src/                                                  │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  cli.tsx (entry)                                            │   │
│  │  ├─ CI mode? → run headless tool → exit(0/1/2)              │   │
│  │  └─ TTY?    → render(<App />, {incrementalRendering:true})  │   │
│  │                                                             │   │
│  │  App.tsx                                                    │   │
│  │  ├─ AppShell (header + transcript + prompt)                 │   │
│  │  ├─ nanostores: $session, $messages, $overlay, $ui          │   │
│  │  ├─ PromptInput (TextInput + slash autocomplete)            │   │
│  │  ├─ TranscriptView (Static history + live turn)             │   │
│  │  └─ Overlay layer ($overlay atom → full-screen modal)       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                           │                                         │
│              REST (httpx-compatible fetch)                          │
│              WebSocket (ws library, reconnect+replay)               │
│                           │                                         │
└───────────────────────────┼─────────────────────────────────────────┘
                            │
          ┌─────────────────▼──────────────────┐
          │      Latexy Backend (FastAPI)        │
          │      http://localhost:8030           │
          │                                      │
          │  REST API (140+ endpoints)           │
          │  WS  /ws/jobs (event stream)         │
          └──────────────────────────────────────┘
```

### Connection model

- **REST**: Node.js `fetch` (or `undici`) with `Authorization: Bearer <token>` header. Retry 3× with exponential backoff (1s, 2s, 4s) on 5xx. 30s timeout.
- **WebSocket**: `ws` library singleton. Connects to `ws://localhost:8030/ws/jobs`. Sends `{type:"subscribe",job_id,last_event_id}` per job. Auto-reconnects with 100ms→30s exponential backoff. Replays missed events via `last_event_id` on reconnect.
- **Auth**: Better Auth session token stored in `~/.config/latexy/config.toml` (chmod 600). Sent as `Authorization: Bearer <token>` on all requests. 401 triggers re-auth prompt without losing navigation state.

### No Python gateway

Unlike Hermes (which spawns `python -m tui_gateway.entry` as a subprocess), Latexy TUI connects directly to the existing FastAPI backend. The Latexy backend is a remote API — there is no local Python logic to embed. This simplifies the architecture significantly.

---

## 5. Confirmed Tech Stack

| Concern | Choice | Version | Rationale |
|---------|--------|---------|-----------|
| TUI framework | React + Ink | v7 (ESM only) | Hermes-proven, `incrementalRendering`, best ecosystem |
| React | React | 19.2+ | Required by Ink v7 |
| Language | TypeScript | 5.8+ | `"module": "NodeNext"` |
| Runtime | Node.js | ≥22 (LTS) | Required by Ink v7 |
| Build tool | tsup (esbuild) | 8.x | Single ESM bundle, shebang injection, fastest |
| State management | nanostores | 0.11+ | Hermes-proven, tiny, works outside React |
| Package manager | pnpm | 10+ | Existing Latexy toolchain |
| Monorepo build | Turborepo | — | Already in Latexy repo |
| HTTP client | native fetch / undici | — | Node 22 built-in fetch is sufficient |
| WebSocket client | `ws` | 8.x | Mature, supports auth headers on upgrade |
| UI components | `@inkjs/ui` | 2.x | Spinner, ProgressBar, Badge, Select, Alert |
| Text input | `ink-text-input` | 6.x | Richer control than @inkjs/ui TextInput |
| Virtual list | `ink-virtual-list` | 1.x | Required for unbounded resume/job lists |
| Config storage | `tomllib` equivalent | `@iarna/toml` | TOML read/write for `~/.config/latexy/config.toml` |
| Clipboard | `clipboardy` | 4.x | Cross-platform clipboard copy for share links |
| Markdown | `marked-terminal` | 7.x | Render AI agent responses as markdown in terminal |
| Distribution | npm global + npx | — | `npm install -g latexy` |
| Versioning | Changesets | — | Independent versioning across monorepo packages |
| Release CI | `changesets/action` | v1 | OIDC npm trusted publishing |

---

## 6. Interaction Model

### Two modes, seamlessly unified

**Agent mode** (default): User types free-text. The input is sent to an AI agent backed by the user's active BYOK provider (selected via `/model`). If no BYOK key is configured, the TUI shows: "No model configured — run `/byok` to add an API key or `/model` to select a provider." Free-plan users with no BYOK key can still use all slash commands; only free-text agent mode requires a configured model.

```
You › compile my software engineer resume for Google SWE role

  ◐ compile_pdf — running
    resume_id: "abc-123"
    compiler: "pdflatex"
  
  ✓ compile_pdf — 2.3s
    PDF: 2 pages, 83 KB
    ATS Score: 72%

  ✓ Compiled successfully. Your PDF is ready.
  
  Run /pdf to open it, or /ats to see the full analysis.
```

**Slash command mode**: User types `/command [args]`. Routes directly to the tool — no AI involved.

```
You › /compile
  → Submits compile job directly, streams logs
  
You › /optimize --jd "https://jobs.google.com/..." --level aggressive
  → Submits optimize job directly, streams LLM tokens

You › /list
  → Opens resume picker overlay
```

### Slash command autocomplete

When the input begins with `/`, a suggestion menu renders above the input showing matching commands with descriptions. Tab or ↑/↓ to navigate, Enter or Tab to complete.

### Transcript structure

The transcript is a scrollable history of turns. Each turn contains:
- **User message row**: prompt text with timestamp
- **Tool cards** (inline): one card per tool call, showing name, state (running/success/error), duration, expandable args/result
- **Agent response**: streamed markdown text, finalized when `message.complete`
- **Separator**: thin rule between turns

For slash commands, the "agent response" is replaced by a structured result card (compile result, ATS score table, resume list, etc.).

### Streaming behaviour

- `log.line` events → appended to the active `LogStreamCard` (one per compile job)
- `llm.token` events → accumulated in `bufRef` (plain class property), flushed to nanostore at 16ms intervals (~60fps)
- `ats.deep_complete` → renders the ATS score card inline
- `job.completed` → finalizes the active tool card, shows result summary

---

## 7. State Management Design

All state lives in nanostores atoms. React components subscribe via `useStore($atom)` or computed selectors. No state in component `useState` except ephemeral UI state (input value, focused row index).

### Store hierarchy

```
stores/
  session.ts    — auth token, user email, subscription plan, backend URL
  messages.ts   — transcript messages[], activeJobId, streamingBuffer
  resumes.ts    — resumeList, selectedResumeId, selectedResume (computed)
  jobs.ts       — jobHistory, jobStates map
  overlay.ts    — current overlay node (null = no overlay)
  ui.ts         — currentView, notifications queue, theme
  ws.ts         — wsConnected, lastEventId per job
```

### The `$isBlocked` pattern (from Hermes)

```typescript
// stores/ui.ts
export const $overlay = atom<React.ReactNode | null>(null)
export const $isBlocked = computed($overlay, o => o !== null)
// useInput in PromptInput uses: { isActive: !$isBlocked.get() }
// When an overlay is open, the prompt input is disabled
```

### Streaming token accumulation (Hermes `bufRef` pattern)

```typescript
// In JobController (plain class, not React):
class JobController {
  private bufRef = ''
  private flushTimer: NodeJS.Timeout | null = null

  onLLMToken(token: string) {
    this.bufRef += token
    if (!this.flushTimer) {
      this.flushTimer = setTimeout(() => {
        $messages.set(appendStreamingToken($messages.get(), this.bufRef))
        this.flushTimer = null
        // bufRef is NOT cleared — it accumulates the full content
        // Only the delta since last flush needs to be computed by storing lastFlushedLen
      }, 16) // ~60fps
    }
  }
}
```

### WS event buffering pre-drain (Hermes CircularBuffer pattern)

```typescript
// lib/ws-client.ts
class LatexyWSClient extends EventEmitter {
  private buffered: Array<LatexyEvent> = []  // max 2000
  private drained = false

  private publish(ev: LatexyEvent) {
    if (this.drained) return void this.emit('event', ev)
    if (this.buffered.length < 2000) this.buffered.push(ev)
  }

  drain() {
    this.drained = true
    for (const ev of this.buffered) this.emit('event', ev)
    this.buffered = []
  }
}
// App.tsx calls wsClient.drain() after React tree mounts
```

---

## 8. WebSocket and Streaming Design

### Connection lifecycle

1. On startup: `wsClient.connect(wsUrl, token)` — connects immediately
2. Events buffered until `wsClient.drain()` called after Ink tree mounts
3. On job submit: `wsClient.subscribe(jobId, "0")` → `{type:"subscribe",job_id,last_event_id:"0"}`
4. Events route to `JobController` per `job_id`
5. On WS disconnect: auto-reconnect with backoff; re-subscribes all active jobs with their `last_event_id`
6. On job complete/failed/cancelled: `wsClient.unsubscribe(jobId)`

### Event routing

```typescript
wsClient.on('event', (ev: LatexyEvent) => {
  const controller = jobControllers.get(ev.job_id)
  if (!controller) return

  switch (ev.type) {
    case 'log.line':    controller.onLogLine(ev); break
    case 'llm.token':   controller.onLLMToken(ev.token); break
    case 'llm.complete':controller.onLLMComplete(ev); break
    case 'job.progress':controller.onProgress(ev.percent, ev.stage); break
    case 'job.completed':controller.onComplete(ev); break
    case 'job.failed':  controller.onFailed(ev); break
    case 'job.cancelled':controller.onCancelled(); break
    case 'ats.deep_complete': controller.onATSComplete(ev); break
    case 'sys.heartbeat': updateHeartbeat(ev.server_time); break
  }
})
```

---

## 9. Slash Command Registry

All slash commands dispatch directly to the relevant Latexy tool without going through the AI agent.

### Core commands

| Command | Usage | Description |
|---------|-------|-------------|
| `/compile` | `/compile [resume-id] [--compiler pdflatex\|xelatex\|lualatex]` | Compile selected or specified resume |
| `/optimize` | `/optimize [resume-id] [--jd url\|file] [--level conservative\|balanced\|aggressive] [--model gpt-4o]` | LLM optimize resume |
| `/combined` | `/combined [resume-id] [--jd url\|file]` | Optimize + compile in one job |
| `/ats` | `/ats [resume-id] [--jd url\|file] [--industry software_engineering]` | Run ATS deep analysis |
| `/quick-ats` | `/quick-ats [resume-id]` | Fast rule-based ATS (no LLM) |
| `/list` | `/list [--archived] [--type resume\|academic_cv]` | Open resume picker overlay |
| `/new` | `/new [title]` | Create new resume (title prompt if not provided) |
| `/edit` | `/edit [resume-id]` | Open selected resume in `$EDITOR` |
| `/fork` | `/fork [resume-id] [new-title]` | Fork resume into a variant |
| `/tailor` | `/tailor [resume-id] --jd url\|file` | Quick fork + optimize for a job |
| `/batch` | `/batch [resume-id] --jobs file.csv` | Batch tailor to multiple job descriptions |
| `/pdf` | `/pdf [job-id]` | Download and open last compiled PDF |
| `/log` | `/log [job-id]` | View full pdflatex log |
| `/cancel` | `/cancel [job-id]` | Cancel running job |
| `/jobs` | `/jobs` | Open job monitor overlay |
| `/byok` | `/byok` | Open BYOK key management overlay |
| `/analytics` | `/analytics [--period 7d\|30d\|90d]` | View personal analytics dashboard |
| `/billing` | `/billing` | View subscription and billing overlay |
| `/tracker` | `/tracker` | Open job application tracker |
| `/cover` | `/cover [resume-id] --company "Google" --role "SWE"` | Generate cover letter |
| `/interview` | `/interview [resume-id] --jd url\|file` | Generate interview questions |
| `/health` | `/health` | Show backend health status |
| `/history` | `/history [resume-id]` | Show optimization history with ATS sparkline |
| `/checkpoint` | `/checkpoint [resume-id] [label]` | Create named checkpoint |
| `/restore` | `/restore [resume-id]` | Restore to a checkpoint (opens picker) |
| `/diff` | `/diff [resume-id]` | Show diff with parent variant |
| `/export` | `/export [resume-id] --format docx\|markdown\|html` | Export resume |
| `/share` | `/share [resume-id]` | Generate and copy share link |
| `/enhance` | `/enhance` | Enhance a bullet point (paste LaTeX) |
| `/scrape` | `/scrape <url>` | Scrape job description from URL |
| `/snippets` | `/snippets` | Browse snippet marketplace |
| `/macros` | `/macros` | Manage keyboard macros |
| `/settings` | `/settings` | Open notification settings |
| `/help` | `/help [command]` | Show help text |
| `/model` | `/model` | Open model picker for agent mode |
| `/clear` | `/clear` | Clear transcript |
| `/logout` | `/logout` | Clear session and return to login |

### Command dispatch (two-tier)

```typescript
// Tier 1: local TypeScript handlers (open overlays, navigate)
const LOCAL_COMMANDS = new Set(['list', 'jobs', 'byok', 'billing', 'tracker', 'model', 'clear', 'help', 'logout'])

// Tier 2: API commands (submit jobs, fetch data)
// All other commands call the relevant Latexy REST endpoint directly
```

---

## 10. Tool Registry (all 35 domains)

Each tool wraps one or more Latexy API endpoints. The AI agent selects tools from this registry to fulfill free-text requests.

### Tool definitions

```typescript
interface Tool {
  name: string
  description: string          // shown to agent in system prompt
  inputSchema: JSONSchema      // validated before execution
  execute: (args, ctx) => Promise<ToolResult>
  cancel?: (jobId: string) => Promise<void>
  confirmationRequired?: boolean  // show confirmation dialog before running
}

interface ToolResult {
  success: boolean
  data?: unknown
  jobId?: string     // if async — WS tracks progress
  error?: string
  displayCard?: React.ReactNode  // custom render for the result
}
```

### Domain → Tool mapping

| Domain | Tools |
|--------|-------|
| **Auth** | `login`, `logout`, `get_session_info` |
| **Resume Management** | `list_resumes`, `get_resume`, `create_resume`, `update_resume`, `delete_resume`, `rename_resume`, `pin_resume`, `archive_resume`, `tag_resume`, `fork_resume`, `list_variants`, `get_resume_settings`, `update_resume_settings`, `get_resume_diff`, `get_optimization_history`, `get_score_history`, `create_checkpoint`, `list_checkpoints`, `restore_checkpoint`, `quick_tailor`, `share_resume`, `revoke_share`, `get_resume_analytics`, `export_resumes`, `get_error_history`, `academic_cv_report` |
| **LaTeX Compilation** | `compile_resume`, `compile_watermarked`, `download_pdf`, `get_compile_log`, `cancel_job` (shared with Job Monitoring) |
| **AI Optimization** | `optimize_resume`, `combined_optimize_compile`, `batch_tailor`, `list_personas`, `get_batch_status` |
| **ATS Scoring** | `score_ats`, `quick_ats_score`, `deep_ats_analyze`, `list_industry_profiles`, `analyze_job_description`, `get_ats_benchmark`, `simulate_ats`, `get_ats_score_history` |
| **BYOK Management** | `list_byok_keys`, `add_byok_key`, `delete_byok_key`, `validate_byok_key`, `test_byok_key`, `get_byok_usage`, `list_byok_providers` |
| **Analytics** | `get_user_analytics`, `get_analytics_timeseries`, `get_system_analytics` (admin), `get_funnel` (admin) |
| **Subscription & Billing** | `get_current_plan`, `list_plans`, `create_subscription`, `cancel_subscription`, `validate_coupon`, `get_trial_status` |
| **Job Monitoring** | `list_jobs`, `get_job_state`, `get_job_result`, `cancel_job` (shared with LaTeX Compilation), `replay_job_events` |
| **System Health** | `get_health`, `get_jobs_health`, `trigger_cleanup`, `list_feature_flags` (admin), `toggle_feature_flag` (admin) |
| **Job Application Tracker** | `list_applications`, `create_application`, `update_application`, `delete_application`, `get_application_stats` |
| **Cover Letters** | `generate_cover_letter`, `list_cover_letters`, `get_cover_letter`, `delete_cover_letter`, `compile_cover_letter` |
| **Interview Prep** | `generate_interview_questions`, `list_interview_preps`, `get_interview_prep`, `delete_interview_prep` |
| **Format Conversion** | `detect_format`, `convert_file_to_latex`, `list_supported_formats` |
| **Export** | `export_as_docx`, `export_as_markdown`, `export_as_html` |
| **AI Micro-tools** | `enhance_bullet`, `skills_gap_analysis`, `extract_keywords`, `generate_career_objective` |
| **References / BibTeX** | `parse_bibtex`, `format_references`, `list_references` |
| **Snippet Marketplace** | `list_snippets`, `get_snippet`, `import_snippet`, `publish_snippet`, `delete_snippet` |
| **Keyboard Macros** | `list_macros`, `create_macro`, `update_macro`, `delete_macro` |
| **Template Gallery** | `list_templates`, `get_template`, `create_from_template` |
| **Career Path** | `generate_career_path`, `list_career_paths`, `get_career_path`, `delete_career_path` |
| **Portfolio** | `get_portfolio`, `update_portfolio`, `publish_portfolio` |
| **GitHub Sync** | `start_github_auth`, `sync_to_github`, `list_github_repos`, `disconnect_github` |
| **Dropbox Sync** | `start_dropbox_auth`, `sync_to_dropbox`, `disconnect_dropbox` |
| **Zotero / Mendeley** | `start_zotero_auth`, `list_zotero_collections`, `start_mendeley_auth`, `list_mendeley_documents` |
| **Collaboration** | `invite_collaborator`, `list_collaborators`, `update_collaborator_role`, `remove_collaborator` |
| **Resume Comments** | `add_comment`, `list_comments`, `update_comment`, `delete_comment` |
| **Team Workspaces** | `create_workspace`, `list_workspaces`, `add_workspace_member`, `remove_workspace_member` |
| **Team Seats** | `invite_seat`, `list_seats`, `revoke_seat`, `accept_seat` |
| **Tenant Management** | `create_tenant`, `list_tenants`, `update_tenant`, `manage_tenant_members` |
| **Developer API Keys** | `list_dev_keys`, `create_dev_key`, `delete_dev_key`, `get_dev_usage` |
| **One-Click Apply** | `submit_application`, `get_submission_status` |
| **Notification Settings** | `get_notification_prefs`, `update_notification_prefs` |
| **Job Scraper** | `scrape_job_url` |

---

## 11. Component Architecture

### Component hierarchy

```
App (app.tsx)
└── AppShell
    ├── StatusBar (top)
    │   ├── BrandLogo ("Latexy")
    │   ├── UserBadge (email + plan)
    │   ├── HealthDot (green/yellow/red)
    │   └── HelpHint ("? for help · / for commands")
    │
    ├── TranscriptPane (flexGrow=1, overflow=hidden)
    │   ├── <Static items={completedMessages}> (finalized history)
    │   │   └── MessageRow (per message)
    │   │       ├── UserMessageRow
    │   │       ├── AssistantMessageRow (markdown)
    │   │       ├── ToolUseCard (running/success/error, expandable)
    │   │       ├── LogStreamCard (compile log lines, scrollable)
    │   │       ├── ATSResultCard (score table, multi-dim bars)
    │   │       ├── CompileResultCard (time, size, pages)
    │   │       ├── ResumeListCard (table of resumes)
    │   │       └── SystemCard (health, analytics, billing)
    │   └── StreamingPane (active turn, dynamic)
    │       ├── ToolUseCard (state=running, with Spinner)
    │       └── StreamingAssistant (live LLM token buffer)
    │
    ├── Overlay layer (conditional, full-screen when $overlay !== null)
    │   ├── ResumePicker
    │   ├── ModelPicker (provider → model, 2-step)
    │   ├── ConfirmDialog
    │   ├── JobMonitorOverlay
    │   ├── BYOKOverlay
    │   ├── BillingOverlay
    │   ├── TrackerOverlay (Kanban board)
    │   ├── CheckpointPicker
    │   ├── SnippetBrowser
    │   ├── MacroManager
    │   └── HelpOverlay
    │
    └── PromptZone (flexShrink=0)
        ├── SlashSuggestions (above input, when input starts with /)
        └── PromptInput (TextInput + submit handler)
```

### Key component specs

#### StatusBar
- Always visible, 1 row height
- Format: `Latexy  ·  riya@example.com  [PRO]  ·  ● healthy  ·  ? help`
- Health dot color: green (healthy), yellow (degraded), red (unhealthy), gray (unknown)
- Updates every 30s via background health poll

#### MessageRow variants

**UserMessageRow**:
```
  You  12:34
  ╰─ compile my SWE resume for the Google SWE role
```

**ToolUseCard** (running):
```
  ◐ compile_pdf  running...
    resume: "Software Engineer Resume"
    compiler: pdflatex
```

**ToolUseCard** (success, collapsed):
```
  ✓ compile_pdf  2.3s  [▼ details]
```

**ToolUseCard** (success, expanded):
```
  ✓ compile_pdf  2.3s  [▲ details]
  ├─ args: { resume_id: "abc", compiler: "pdflatex" }
  └─ result: { pages: 2, size_kb: 83, ats_score: 72 }
```

**LogStreamCard**:
```
  ┌─ pdflatex log ──────────────────────────────────────┐
  │ This is pdflatex Version 3.14159265                 │
  │ entering extended mode                              │
  │ [ERR] LaTeX Warning: Font shape undefined           │ ← red
  │ Output written on resume.pdf (2 pages, 85234 bytes) │
  └────────────────────── 47 lines ─────────────────────┘
```

**ATSResultCard**:
```
  ┌─ ATS Score: 72%  ·  Industry: Software Engineering ─┐
  │ ████████████████████░░░░░░░  72 / 100               │
  │                                                      │
  │ Section Scores:                                      │
  │   Experience    ████████░░  82%  Strong              │
  │   Skills        █████░░░░░  52%  Add Python, K8s     │
  │   Education     ██████████  95%  Excellent            │
  │   Keywords      ██████░░░░  61%  Missing 4 terms     │
  │                                                      │
  │ [J] Analyze JD  [B] Benchmark  [S] Simulate ATS     │
  └──────────────────────────────────────────────────────┘
```

#### PromptInput
- Single-line text input by default; Shift+Enter for multiline
- When value starts with `/`: render SlashSuggestions above
- When value is empty + Ctrl+D: exit
- When agent is busy: show "Queued: ..." preview of next message
- Masked input mode for BYOK keys (`/byok add`)

#### Overlays (full-screen takeover)

**ResumePicker**:
```
  ╔══ Select Resume ════════════════════════════════════╗
  ║ ↑↓ navigate · Enter select · / filter · Esc cancel ║
  ╠═════════════════════════════════════════════════════╣
  ║ ▶ Software Engineer Resume     resume  fresh  ★     ║
  ║   Google SWE Variant           resume  fresh   ↳    ║
  ║   Academic CV 2024             cv      stale        ║
  ║   Product Manager Resume       resume  30d ago      ║
  ╚═════════════════════════════════════════════════════╝
```

**ModelPicker** (2-step, same as Hermes):
```
  Step 1: Provider
  ▶ OpenAI          (key saved)
    Anthropic        (key saved)
    Gemini           (no key)
    OpenRouter       (no key)

  Step 2: Model
  ▶ gpt-4o          latest
    gpt-4o-mini      fast, cheap
    o3-mini          reasoning
```

---

## 12. Store Design

### `stores/session.ts`
```typescript
interface SessionState {
  token: string | null
  userId: string | null
  email: string | null
  plan: 'free' | 'basic' | 'pro' | 'byok' | 'team' | null
  backendUrl: string    // from config or LATEXY_API_URL env
  wsUrl: string
  isAuthenticated: boolean
}
export const $session = atom<SessionState>(initialSessionState)
```

### `stores/messages.ts`
```typescript
export type MessageRole = 'user' | 'assistant' | 'tool_use' | 'tool_result'
  | 'log_stream' | 'ats_result' | 'compile_result' | 'resume_list'
  | 'system' | 'error'

export interface Message {
  id: string
  role: MessageRole
  content: string           // text content (markdown for assistant)
  timestamp: string
  streaming?: boolean       // true while llm.token events arriving
  // Tool cards
  toolName?: string
  toolArgs?: Record<string, unknown>
  toolState?: 'running' | 'success' | 'error' | 'cancelled'
  toolResult?: unknown
  durationMs?: number
  jobId?: string            // associated async job
  // Structured result data (for non-text roles)
  resultData?: unknown
}

export const $messages = atom<Message[]>([])
export const $activeJobId = atom<string | null>(null)
```

### `stores/ui.ts`
```typescript
interface UIState {
  theme: 'dark' | 'light'
  notifications: Notification[]
  healthStatus: 'healthy' | 'degraded' | 'unhealthy' | 'unknown'
  wsConnected: boolean
}
// $overlay is separate from $ui to allow the computed $isBlocked to derive cleanly
export const $overlay = atom<React.ReactNode | null>(null)
export const $isBlocked = computed($overlay, o => o !== null)
export const $ui = atom<UIState>(defaultUI)
```

---

## 13. Distribution and Packaging

### Monorepo layout

```
latexy/
├── backend/              ← existing FastAPI — unchanged
├── frontend/             ← existing Next.js — unchanged
├── packages/
│   ├── tui/              ← NEW: React+Ink CLI
│   │   ├── src/
│   │   │   ├── cli.tsx           ← #!/usr/bin/env node entry
│   │   │   ├── app.tsx           ← root App component
│   │   │   ├── stores/           ← nanostores
│   │   │   ├── commands/         ← slash command registry
│   │   │   ├── tools/            ← tool definitions (35 domains)
│   │   │   ├── components/       ← Ink components
│   │   │   ├── hooks/            ← useJobStream, useAuth
│   │   │   └── lib/              ← api-client, ws-client, event-types
│   │   ├── tsup.config.ts
│   │   ├── tsconfig.json
│   │   └── package.json          ← name: "latexy", bin: {latexy: dist/cli.js}
│   └── types/            ← shared TypeScript types (optional)
├── pnpm-workspace.yaml   ← add packages/* entry
├── turbo.json            ← add tui build task
└── package.json          ← root
```

### `packages/tui/package.json`
```json
{
  "name": "latexy",
  "version": "1.0.0",
  "description": "Terminal UI for the Latexy LaTeX resume SaaS",
  "type": "module",
  "bin": { "latexy": "./dist/cli.js" },
  "engines": { "node": ">=22" },
  "files": ["dist/", "README.md"],
  "publishConfig": { "access": "public", "provenance": true },
  "scripts": {
    "build": "tsup",
    "dev": "tsup --watch",
    "typecheck": "tsc --noEmit",
    "prepublishOnly": "pnpm run build"
  }
}
```

### `tsup.config.ts`
```typescript
import { defineConfig } from 'tsup'
export default defineConfig({
  entry: { cli: 'src/cli.tsx' },
  format: ['esm'],
  target: 'node22',
  platform: 'node',
  bundle: true,
  clean: true,
  dts: false,
  banner: { js: '#!/usr/bin/env node' },
})
```

### How `lib/` code is shared with frontend

The `api-client.ts`, `ws-client.ts`, and `event-types.ts` files are adapted copies of `frontend/src/lib/*`. They share the same interface but use the Node.js `ws` library instead of the browser WebSocket API. **Decision: use a `@latexy/types` private workspace package** (`packages/types/`) to share TypeScript interfaces. Both `frontend/` and `packages/tui/` depend on `@latexy/types: workspace:*`. The frontend uses `transpilePackages: ['@latexy/types']` in `next.config.js` to handle the raw `.ts` exports. Implementation files (`api-client`, `ws-client`) are separate per-package — only the type interfaces are shared.

### Distribution channels

| Channel | Command | Timeline |
|---------|---------|----------|
| npm global | `npm install -g latexy` | v1.0 |
| npx | `npx latexy` | v1.0 (auto) |
| Homebrew | `brew install latexy/tap/latexy` | v1.0 (Phase 3) |
| Standalone binary | GitHub Releases | v2.0 |

### Release CI/CD

- **Versioning**: Changesets (`pnpm changeset` per PR, `pnpm changeset version` on merge to main)
- **Publishing**: `changesets/action@v1` creates a "Version Packages" PR; merging it publishes to npm via OIDC trusted publishing (no NPM_TOKEN secret needed)
- **Homebrew**: `Justintime50/homebrew-releaser@v3` auto-updates the tap formula on release

---

## 14. CI/CD and Non-Interactive Mode

When `process.stdout.isTTY === false` or `--json` flag is set, the TUI runs headlessly — no Ink render, structured JSON to stdout, logs to stderr.

### Subcommands

```bash
# Compile — local .tex file is uploaded to the backend via POST /compile (multipart)
# OR pass a resume ID to compile an already-stored resume
latexy compile resume.tex [--compiler pdflatex|xelatex|lualatex] [--output out.pdf] [--json]
latexy compile --resume-id <uuid> [--compiler pdflatex] [--json]

# Optimize
latexy optimize <resume-id> --jd <file|url> [--level balanced] [--model gpt-4o] [--json]

# ATS score
latexy ats score <resume-id> [--jd <file>] [--industry software_engineering] [--json]

# Job status (blocks until done with --wait)
latexy status <job-id> [--wait] [--json]

# List resumes
latexy list [--json]
```

### JSON output format

```json
// Success
{ "success": true, "job_id": "...", "pdf_url": "...", "ats_score": 72, "pages": 2, "compilation_time": 2.3 }

// Failure
{ "success": false, "error": "LaTeX compilation failed", "error_code": "latex_error", "retryable": true }
```

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Job failure (LaTeX error, LLM failure) |
| `2` | Auth or network error |
| `3` | Input validation error (bad file path, missing arg) |

### Environment variables

```bash
LATEXY_API_URL=http://localhost:8030   # backend URL (default: http://localhost:8030)
LATEXY_SESSION_TOKEN=<token>           # skip login — use pre-authenticated session token
LATEXY_EMAIL=user@example.com          # auto-login credentials
LATEXY_PASSWORD=secret                 # auto-login (read once, then cleared from process.env)
LATEXY_DEFAULT_RESUME_ID=<uuid>        # default resume for commands that require one
```

---

## 15. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-01 | First meaningful render (login screen or resume list) in < 500ms |
| NFR-02 | `log.line` events appear in UI within 100ms of WS arrival |
| NFR-03 | LLM token stream renders at ≥ 60fps (16ms flush interval) |
| NFR-04 | No blocking network I/O on the main thread — all API calls via async |
| NFR-05 | Session token stored with chmod 600; warn on world-readable config |
| NFR-06 | BYOK key input uses masked mode (no echo, no history) |
| NFR-07 | HTTPS required for non-localhost backends; HTTP triggers a warning |
| NFR-08 | `LATEXY_PASSWORD` env var cleared from `process.env` after login |
| NFR-09 | Minimum terminal: 80 columns × 24 rows; degraded gracefully below |
| NFR-10 | Works in 256-color and truecolor terminals; 16-color fallback safe |
| NFR-11 | Works over SSH without X forwarding |
| NFR-12 | WS reconnects automatically with backoff; replays missed events |
| NFR-13 | Local state (log lines, LLM tokens) preserved across WS reconnects |
| NFR-14 | Backend unreachable at startup → clear error screen, retry on `r` |
| NFR-15 | `CI=true` env → static mode (no live-render), final frame on exit |

---

## 16. Testing Strategy

### Unit tests (`packages/tui/src/__tests__/`)

Use `ink-testing-library` for component tests:

```typescript
import { render } from 'ink-testing-library'
import { MessageRow } from '../components/MessageRow.js'

test('renders tool card in running state', () => {
  const { lastFrame } = render(<ToolUseCard message={runningMsg} />)
  expect(lastFrame()).toContain('compile_pdf')
  expect(lastFrame()).toContain('running')
})
```

### Integration tests

- Mock WS server (uses `ws` in test mode) → subscribe → push events → assert store updates
- Mock REST API (`msw` or simple express mock server) → assert tool execution
- Auth flow: mock login response → assert token stored in `$session`

### E2E tests (CI job)

GitHub Actions job that:
1. Spins up the Latexy backend via `docker-compose.test.yml`
2. Runs `latexy compile tests/fixtures/sample.tex --json` → asserts exit code 0
3. Runs `latexy ats score <id> --json` → asserts `ats_score` in output
4. Runs `latexy optimize <id> --jd tests/fixtures/jd.txt --json` → asserts `success: true`

### Snapshot tests

```typescript
// verify screen layouts don't regress
test('resume list renders correctly at 80 columns', () => {
  const { frames } = render(<ResumePicker resumes={fixtures} />)
  expect(frames[0]).toMatchSnapshot()
})
```

---

## 17. Implementation Plan

### Phase 1 — MVP (Weeks 1–4)

**Goal:** Working TUI with login, resume list, compile with streaming logs, PDF download.

**Deliverables:**
1. `packages/tui/` scaffold — `package.json`, `tsup.config.ts`, `tsconfig.json`
2. `src/cli.tsx` — entry point: TTY check, CI mode guard, `render(<App />)`
3. `src/lib/ws-client.ts` — WS singleton, reconnect, event buffering, drain()
4. `src/lib/api-client.ts` — REST client: fetch wrapper with auth header, retry, timeout
5. `src/lib/event-types.ts` — TypeScript interfaces for all 14 WS event types
6. `src/stores/` — session, messages, ui, overlay stores
7. `src/components/AppShell.tsx` — alternate screen, StatusBar, TranscriptPane, PromptZone
8. `src/components/TranscriptView.tsx` — Static history + StreamingPane
9. `src/components/PromptInput.tsx` — TextInput + slash suggestion menu
10. `src/components/MessageRow.tsx` — UserMessageRow, AssistantMessageRow, ToolUseCard
11. `src/components/LogStreamCard.tsx` — streaming pdflatex log display
12. `src/components/CompileResultCard.tsx` — time, size, pages
13. `src/commands/` — slash registry, parser, dispatch
14. `src/tools/compile.ts` — compile tool (submit job + stream)
15. `src/hooks/useJobStream.ts` — WS → JobController → store bridge
16. `LoginScreen` overlay — email + password fields, error display
17. `ResumePicker` overlay — list with filter
18. CI mode: `latexy compile <file.tex> --json`
19. Auth: config.toml read/write, chmod 600, token validation
20. `src/components/StatusBar.tsx` — health dot, user badge

**Acceptance:** user can log in, list resumes, compile with streaming logs, download PDF.

### Phase 2 — Full Feature Parity (Weeks 5–10)

All 35 domains exposed via slash commands. Per-domain deliverables:

1. **AI Optimization** — `OptimizeResultCard`, `llm.token` streaming, persona picker, level selector
2. **ATS Scoring** — `ATSResultCard` with ASCII bars, industry picker, JD analysis, simulator
3. **BYOK** — `BYOKOverlay`, masked key input, provider picker, usage table
4. **Analytics** — `AnalyticsCard` with ASCII timeseries chart (unicode block chars)
5. **Billing** — `BillingOverlay`, plan comparison table, Razorpay URL display, payment poll
6. **Job Monitor** — `JobMonitorOverlay`, event replay, JSON inspector
7. **System Health** — `HealthCard`, feature flag table (admin), cleanup trigger
8. **Job Application Tracker** — `TrackerOverlay`, Kanban board, status pipeline
9. **Cover Letters** — generate flow, streaming result, compile
10. **Interview Prep** — generate flow, numbered questions display
11. **Format Conversion** — file path input, convert to LaTeX
12. **Export** — DOCX/Markdown/HTML download
13. **AI Micro-tools** — enhance bullet, skills gap, keywords
14. **BibTeX References** — parse, format, list
15. **Snippet Marketplace** — browse, search, import
16. **Keyboard Macros** — list, create, update, delete
17. **Template Gallery** — browse by category, create from template
18. **Career Path** — generate, list, view
19. **Portfolio** — configure, publish
20. **GitHub/Dropbox Sync** — OAuth flow (open browser), sync
21. **Zotero/Mendeley** — OAuth, list collections
22. **Collaboration** — invite, list, roles
23. **Comments** — add, list, delete
24. **Team Workspaces** — CRUD, members
25. **Team Seats** — invite, list, revoke
26. **Tenant Management** — CRUD (admin)
27. **Developer API Keys** — CRUD, usage
28. **One-Click Apply** — submit, track
29. **Notification Settings** — fetch, update
30. **Job Scraper** — scrape URL
31. **Resume Checkpoints / History** — create checkpoint, list, restore, ATS sparkline display
32. **Share Links** — generate, copy to clipboard, revoke
33. **Resume diff** — diff-with-parent view, academic CV detection
34. **Auth domain** — logout, session info display, 401 auto-reauth
35. **Admin tools** — feature flags, system analytics, tenant management (gated by admin role)

**Acceptance:** all 35 domains work via slash commands in the interactive TUI.

### Phase 3 — Agent Mode + Polish (Weeks 11–14)

1. **Agent loop** — AI agent system prompt with full tool catalog, free-text input routing
2. **Model picker** — `ModelPicker` overlay (2-step provider → model, save key)
3. **Multi-step agent tasks** — compile → optimize → ATS in one prompt
4. **`$EDITOR` integration** — open LaTeX in user's editor, watch for save, reload
5. **Homebrew formula** — `homebrew-latexy` tap, auto-update CI
6. **CI/CD GitHub Actions job** — full e2e test against `docker-compose.test.yml`
7. **Standalone binary** (optional) — `bun build --compile` for macOS + Linux
8. **Theme system** — Latexy brand colors, light/dark auto-detect, ASCII logo banner
9. **Checkpoint/history navigation** — checkpoint picker, ATS sparkline
10. **Diff view** — unified diff with color highlighting (difflib-style in terminal)
11. **Batch tailor UI** — CSV/interactive form for multi-job optimization
12. **Performance audit** — profile render cycle, ensure 60fps token streaming
13. **Manual test checklist** — login, compile error, cancel, WS disconnect, BYOK, billing

**Acceptance:** Phase 3 complete = agent handles multi-step tasks; CI job passes; Homebrew formula ships; 1.0 tagged.

---

## Appendix: Keyboard Shortcuts Reference

### Global (always active when not in overlay)

| Key | Action |
|-----|--------|
| `Ctrl+C` | Cancel running job / interrupt agent |
| `Ctrl+D` (empty input) | Exit TUI |
| `Ctrl+L` | Clear transcript |
| `Ctrl+K` | Delete to end of line |
| `Ctrl+R` | Open resume picker |
| `Ctrl+J` | Open job monitor |
| `Ctrl+B` | Open BYOK overlay |
| `Ctrl+M` | Open model picker |
| `?` | Show help overlay |
| `Esc` | Close overlay |

### TextInput

| Key | Action |
|-----|--------|
| `Enter` | Submit |
| `Shift+Enter` | Insert newline |
| `↑` / `↓` | History navigation (at start/end of input) |
| `Tab` | Complete slash command suggestion |
| `Ctrl+A` / `Ctrl+E` | Line start / end |
| `Ctrl+W` | Delete word backward |

### Overlays (ResumePicker, ModelPicker, etc.)

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate |
| `j` / `k` | Navigate (vim) |
| `Enter` | Select |
| `Esc` | Cancel |
| Type | Filter/search |

---

*This specification supersedes TUI_AUDIT.md and TUI_PRD.md at the repo root, which were the v1 Textual-based drafts.*
