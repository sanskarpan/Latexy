# Latexy TUI — Product Requirements Document

**Document version:** 1.0  
**Date:** 2026-06-15  
**Author:** Latexy Engineering  
**Status:** Draft — pre-implementation

---

## Table of Contents

1. Executive Summary and Goals
2. User Personas
3. Functional Requirements
   - 3.1 Authentication
   - 3.2 Resume Management
   - 3.3 LaTeX Compilation
   - 3.4 AI Optimization
   - 3.5 ATS Scoring
   - 3.6 BYOK Key Management
   - 3.7 Analytics
   - 3.8 Subscription and Billing
   - 3.9 Job Monitoring
   - 3.10 System Health
   - 3.11 Job Application Tracker
   - 3.12 Cover Letter Generation
   - 3.13 Interview Prep
   - 3.14 Career Features
   - 3.15 CI/CD and Non-Interactive Mode
4. Non-Functional Requirements
5. Architecture
6. Screen and Panel Layout
7. Keyboard Shortcut Map
8. Implementation Plan (3 Phases)
9. TUI State Data Models
10. Testing Strategy
11. Technology Choices

---

## 1. Executive Summary and Goals

### Background

Latexy is a LaTeX resume SaaS with a FastAPI backend (port 8030) and a Next.js 14 frontend
(port 5180). The system is fully event-driven: job submissions go to Celery workers, and
real-time updates arrive via a Redis Pub/Sub → WebSocket fanout. The REST API is complete and
all features are independently accessible without the web frontend.

### Why a TUI?

Four categories of users work outside the browser by preference or necessity:

1. **Power users** who live in the terminal and resist context-switching to a browser.
2. **DevOps / sysadmin users** who need system health, queue monitoring, and log inspection.
3. **CI/CD pipeline users** who need scriptable, non-interactive resume compilation and
   optimization as part of automated workflows.
4. **Developers** building on the Latexy API who need a fast feedback loop for testing jobs.

The web frontend cannot serve these users well. A Python/Textual TUI can expose every Latexy
feature in a rich, interactive terminal interface that runs over SSH, in Docker, or locally.

### Goals

**G1 — Feature parity:** Expose all Latexy features that are terminal-compatible (approximately
80% of the full feature set per the TUI Audit).

**G2 — First-class streaming:** Display `log.line` and `llm.token` WebSocket events in real time
within the TUI — the primary competitive differentiator vs. a plain CLI.

**G3 — CI/CD compatibility:** Provide a non-interactive `--json` mode for every command so
scripts and pipelines can consume structured output.

**G4 — Zero-dependency install:** Single `pip install latexy-tui` or a standalone binary.
No browser required at runtime.

**G5 — Offline awareness:** When the backend is unreachable, the TUI shows a clear degraded
state and offers a reconnect command.

### Success Metrics

- Phase 1 complete: a user can log in, list resumes, compile a resume, and watch log lines stream
  in the terminal.
- Phase 2 complete: all named features (ATS, BYOK, analytics, AI optimize) work interactively.
- Phase 3 complete: CI/CD mode is tested in GitHub Actions; admin health panel ships.

---

## 2. User Personas

### Persona 1 — Power User ("Riya")

- Software engineer, uses Neovim as primary editor, runs everything in tmux.
- Edits LaTeX in `$EDITOR`, wants instant compile feedback without leaving the terminal.
- Uses AI optimization when preparing for job applications; cares deeply about ATS score trends.
- Needs: fast resume list, `$EDITOR` integration, streaming compile logs, ATS score display,
  checkpoint management.

### Persona 2 — DevOps / Sysadmin ("Marcus")

- Infrastructure engineer at a startup, manages the Latexy self-hosted instance.
- Monitors Celery queue health, Redis connectivity, and worker failures over SSH.
- Needs: system health panel, feature flag toggling, job queue depth monitoring, Redis key
  inspection, worker log tailing.

### Persona 3 — CI/CD Pipeline User ("automated-pipeline")

- GitHub Actions or GitLab CI runner, not a human.
- Checks out a LaTeX resume, compiles it, optionally optimizes for a target job, saves the PDF
  artifact, and reports the ATS score.
- Needs: non-interactive JSON mode, exit codes that reflect job success/failure, environment
  variable credentials, no terminal UI rendering.

### Persona 4 — Developer ("Priya")

- Latexy API integrator or contributor, running the backend locally.
- Tests job submissions, watches WS event sequences, inspects Redis state for debugging.
- Needs: job detail view with all events listed in sequence, raw event JSON inspection, quick
  BYOK key rotation, live event stream.

---

## 3. Functional Requirements

Requirements are numbered `TUI-NNN` and grouped by domain. Each requirement includes the
backend API call(s) it depends on.

### 3.1 Authentication

**TUI-001** — The TUI must support login with email and password, posting to the Better Auth
`/api/auth/sign-in/email` endpoint and storing the returned session token.

**TUI-002** — The session token must be persisted to `~/.config/latexy/config.toml` with
`chmod 600` permissions.

**TUI-003** — The TUI must display the currently logged-in user's email in the status bar at all
times.

**TUI-004** — The TUI must detect a 401 response from the backend and automatically prompt for
re-authentication without losing the user's current navigation state.

**TUI-005** — The TUI must support a `logout` command that clears the stored session token and
returns to the login screen.

**TUI-006** — The TUI must support `--email` and `--password` environment variables or flags for
non-interactive authentication in CI/CD mode (see Section 3.15).

**TUI-007** — The TUI must display the user's current subscription plan (free/basic/pro/byok/team)
in the status bar, fetched from `GET /subscription/current`.

**TUI-008** — The TUI must handle session expiry gracefully, prompting for password without
requiring a full restart.

### 3.2 Resume Management

**TUI-009** — The TUI must display a paginated resume list from `GET /resumes/` with columns:
title, document_type, tags, freshness_status, variant_count, updated_at.

**TUI-010** — The resume list must support filtering by archived status (`archived=true/false`)
and document type (`resume` / `academic_cv` / `presentation`).

**TUI-011** — The TUI must support full-text search across resume titles and LaTeX content via
`GET /resumes/search?q=<query>`, displaying matches with highlighted line excerpts.

**TUI-012** — The TUI must allow creating a new resume (title prompt + optional template
selection) via `POST /resumes/`.

**TUI-013** — The TUI must allow editing a resume's LaTeX content by opening `$EDITOR` (respecting
the `EDITOR` and `VISUAL` environment variables), then reloading and saving the content via
`PUT /resumes/{resume_id}`.

**TUI-014** — The TUI must allow deleting a resume with a confirmation prompt (yes/no) before
calling `DELETE /resumes/{resume_id}`.

**TUI-015** — The TUI must allow renaming a resume title via `PUT /resumes/{resume_id}`.

**TUI-016** — The TUI must allow pinning and unpinning resumes (`PATCH /resumes/{id}/pin`,
`PATCH /resumes/{id}/unpin`).

**TUI-017** — The TUI must allow archiving and unarchiving resumes.

**TUI-018** — The TUI must allow tagging resumes (up to 10 tags, max 30 chars each) via
`PATCH /resumes/{id}/tags`.

**TUI-019** — The TUI must support forking a resume into a variant via `POST /resumes/{id}/fork`
and display the parent→variant tree.

**TUI-020** — The TUI must allow listing all variants of a parent resume (`GET /resumes/{id}/variants`)
with their last-updated timestamp and ATS score if available.

**TUI-021** — The TUI must display per-resume settings (compiler, texlive_version, latexmk_flags,
extra_packages) and allow updating them via `PATCH /resumes/{id}/settings`.

**TUI-022** — The TUI must allow generating and displaying a share link (`POST /resumes/{id}/share`),
copying the URL to the clipboard using the `pyperclip` library.

**TUI-023** — The TUI must allow revoking a share link (`DELETE /resumes/{id}/share`).

**TUI-024** — The TUI must display resume view analytics (total views, views last 7/30 days,
top countries, top referrers) from `GET /resumes/{id}/analytics` in a compact table.

**TUI-025** — The TUI must allow creating manual checkpoints with a label
(`POST /resumes/{id}/checkpoints`) and listing them in a scrollable panel.

**TUI-026** — The TUI must allow restoring to a prior optimization/checkpoint by selecting from
the checkpoint list and calling `POST /resumes/{id}/restore-optimization/{opt_id}`.

**TUI-027** — The TUI must allow forking + immediately optimizing a resume for a job via
`POST /resumes/{id}/quick-tailor` with a job description prompt.

**TUI-028** — The TUI must allow exporting all resumes as a ZIP archive (`GET /resumes/export/bulk`)
in tex, pdf, or docx format, saving to a user-specified path.

**TUI-029** — The TUI must display the resume error history (`GET /resumes/error-history`) in a
table showing error type, count, last seen, and whether the error has been resolved.

**TUI-030** — The TUI must display resume optimization history (`GET /resumes/{id}/optimization-history`)
with ATS score progression as an ASCII sparkline.

**TUI-031** — The TUI must allow diff view between a variant and its parent
(`GET /resumes/{id}/diff-with-parent`), rendered as a unified diff using the `difflib` module
with colour highlighting.

**TUI-032** — The TUI must allow running the academic CV detection report
(`GET /resumes/{id}/academic-cv-report`) and offer to convert it to an industry resume fork.

### 3.3 LaTeX Compilation

**TUI-033** — The TUI must submit a LaTeX compilation job via `POST /jobs/submit` with
`job_type: "latex_compilation"` and subscribe to the resulting WebSocket channel.

**TUI-034** — The TUI must display `log.line` events in real time in a scrolling log panel,
colour-coding error lines (red) vs. informational lines (default).

**TUI-035** — The TUI must display a progress bar driven by `job.progress` events showing the
current stage name and percent complete.

**TUI-036** — On `job.completed`, the TUI must display compilation time, PDF size in KB, and
page count.

**TUI-037** — On `job.completed`, the TUI must offer to download the PDF via
`GET /download/{job_id}` and open it with the OS default PDF viewer (`open` on macOS,
`xdg-open` on Linux, `start` on Windows).

**TUI-038** — On `job.failed`, the TUI must display the specific LaTeX error line extracted from
the log and the retryable flag.

**TUI-039** — The TUI must allow selecting the LaTeX compiler (`pdflatex` / `xelatex` / `lualatex`)
before submission, defaulting to the per-resume stored setting if available.

**TUI-040** — The TUI must allow cancelling an in-progress job via `DELETE /jobs/{job_id}` and
display confirmation on receipt of the `job.cancelled` event.

**TUI-041** — The TUI must support submitting a watermarked compile via
`POST /jobs/compile-watermarked` with a watermark text prompt.

**TUI-042** — The TUI must support downloading and displaying the pdflatex log file for any
completed job via `GET /logs/{job_id}`.

### 3.4 AI Optimization

**TUI-043** — The TUI must allow submitting an LLM optimization job via `POST /jobs/submit` with
`job_type: "llm_optimization"` and an optional job description.

**TUI-044** — The TUI must display incoming `llm.token` events in a scrolling text panel,
accumulating tokens in real time so the user sees the LaTeX being generated.

**TUI-045** — On `llm.complete`, the TUI must display the total token count and offer to open the
generated LaTeX in `$EDITOR`.

**TUI-046** — The TUI must allow submitting a combined optimize + compile job (`job_type: "combined"`)
with all relevant parameters: job description, optimization_level, target_sections,
custom_instructions, model, persona.

**TUI-047** — The TUI must present a list of available optimization personas (from
`VALID_PERSONA_KEYS`) and allow the user to select one interactively.

**TUI-048** — The TUI must allow selecting the optimization level: `conservative` / `balanced` /
`aggressive` from a radio-style selector.

**TUI-049** — On `job.failed` after LLM phase, if `optimized_latex` is present in the event,
the TUI must offer to save the LLM output anyway (even though compile failed).

**TUI-050** — The TUI must allow submitting a batch tailor job (`POST /jobs/batch`) with a CSV
or interactive form for company_name, role_title, job_description per row (max 10 rows).

**TUI-051** — The TUI must poll and display batch job status (`GET /jobs/batch/{batch_id}`) in a
progress table showing per-fork status.

**TUI-052** — The TUI must display the ATS score improvement from the `job.completed` event's
`ats_score` and `changes_made` list.

### 3.5 ATS Scoring

**TUI-053** — The TUI must allow submitting an ATS scoring job via `POST /jobs/submit` with
`job_type: "ats_scoring"` for the current resume.

**TUI-054** — The TUI must allow running a quick rule-based ATS score via `POST /ats/quick-score`
without submitting a full async job.

**TUI-055** — On `ats.deep_complete`, the TUI must display:
- Overall score as a percentage bar
- Per-section scores in a compact table (section name, score, top recommendation)
- ATS compatibility issues list
- Job match score and missing requirements (if job description was provided)
- Multi-dimensional scores (`multi_dim_scores`) as an ASCII bar chart

**TUI-056** — The TUI must display the detected or selected industry label next to the ATS score.

**TUI-057** — The TUI must list available industry profiles from `GET /ats/industry-profiles` and
allow the user to select an industry override.

**TUI-058** — The TUI must allow submitting a job description analysis (`POST /ats/analyze-job`)
and display extracted keywords, requirements, and optimization tips.

**TUI-059** — The TUI must allow running the ATS benchmark (`GET /ats/benchmark`) and display
the user's percentile rank in the industry cohort.

**TUI-060** — The TUI must allow running the ATS simulator (`POST /ats/simulate`) against
specific ATS profiles (Workday, Greenhouse, Lever, etc.) and display which resume fields
pass/fail each ATS filter.

**TUI-061** — The TUI must display ATS score history as an ASCII sparkline in the resume detail
panel, fetched from `GET /resumes/{id}/score-history`.

### 3.6 BYOK Key Management

**TUI-062** — The TUI must display all stored API keys from `GET /byok/keys` in a table with
columns: provider, key name, masked key (last 4 chars), is_active, last_validated, created_at.

**TUI-063** — The TUI must allow adding a new API key for a supported provider via
`POST /byok/keys` with a key input field that masks characters as they are typed.

**TUI-064** — The TUI must validate the key on add (calling `POST /byok/validate`) and display
validation result (valid/invalid, available models, capabilities).

**TUI-065** — The TUI must allow deleting a stored API key (`DELETE /byok/keys/{key_id}`) with
confirmation.

**TUI-066** — The TUI must display supported providers and their capabilities from
`GET /byok/providers`.

**TUI-067** — The TUI must allow testing the active key for a provider (`POST /byok/test/{provider}`)
and display the test result.

**TUI-068** — The TUI must display per-provider token usage statistics from `GET /byok/usage`.

### 3.7 Analytics

**TUI-069** — The TUI must display aggregated user analytics from `GET /analytics/user` with
period selector (7d / 30d / 90d):
- Total compilations with success rate
- Total optimizations
- Average compilation time
- Most active day
- Feature usage breakdown

**TUI-070** — The TUI must display compilation timeseries from `GET /analytics/user/timeseries`
as an ASCII line chart (using unicode block characters) with daily total, success, and failure
counts.

**TUI-071** — Admin users must be able to view system-wide analytics from `GET /analytics/system`
including: total users, new users, active subscriptions, total revenue (INR), trial-to-paid
conversion rate.

**TUI-072** — Admin users must be able to view the conversion funnel from `GET /analytics/funnel`.

**TUI-073** — The TUI must track usage events via `POST /analytics/track` when the user performs
key actions (compile, optimize, ats_score) so the web dashboard stays consistent.

### 3.8 Subscription and Billing

**TUI-074** — The TUI must display the current subscription plan, status, and period end date
from `GET /subscription/current`.

**TUI-075** — The TUI must display all available plans from `GET /subscription/plans` with plan
name, price, feature list, and a clear comparison of limits.

**TUI-076** — When the user requests an upgrade, the TUI must call `POST /subscription/create`
and display the returned `short_url` (Razorpay payment page), instructing the user to open it in
a browser to complete payment.

**TUI-077** — After displaying the payment URL, the TUI must poll `GET /subscription/current`
every 10 seconds (up to 5 minutes) to detect subscription activation and confirm success.

**TUI-078** — The TUI must allow cancelling the subscription via `POST /subscription/cancel`
after a confirmation prompt.

**TUI-079** — The TUI must allow validating a coupon code via `POST /billing/validate-coupon`
before displaying a plan upgrade prompt.

**TUI-080** — The TUI must clearly indicate when a trial limit has been reached (via
`GET /public/trial-status`) and prompt the user to sign up or upgrade.

### 3.9 Job Monitoring

**TUI-081** — The TUI must display a scrollable job list from `GET /jobs/` showing: job_id
(truncated), job_type, status, stage, percent, last_updated.

**TUI-082** — The TUI must allow selecting a job from the list and viewing its full event stream
history by replaying from `latexy:stream:{job_id}` via the WebSocket `subscribe` message with
`last_event_id: "0"`.

**TUI-083** — The TUI must display a live job detail panel with: status badge, current stage,
progress bar, log lines, LLM tokens (for combined/llm jobs), and final result summary.

**TUI-084** — The TUI must allow cancelling any running job from the job list with a single
keypress.

**TUI-085** — The TUI must display the estimated completion time in the job panel (derived from
`estimated_seconds` in `job.queued` and current elapsed time).

**TUI-086** — The TUI must display the job result payload in a scrollable JSON inspector panel
accessible after `job.completed`.

**TUI-087** — The TUI must distinguish between retryable (`retryable: true`) and permanent
failures and display an appropriate message for each.

### 3.10 System Health

**TUI-088** — The TUI must display a system health panel with status from `GET /health`:
- Overall status badge (healthy / degraded / unhealthy)
- LaTeX compiler availability
- Database connectivity
- Redis connectivity
- App version

**TUI-089** — The TUI must display job system health from `GET /jobs/health` with Redis Pub/Sub
and Stream connectivity indicators.

**TUI-090** — Admin users must be able to view and toggle feature flags (`GET /admin/feature-flags`,
`PATCH /admin/feature-flags/{key}`).

**TUI-091** — The TUI must provide a manual cleanup trigger (`POST /jobs/system/cleanup`) with
cleanup_type selection (temp_files / expired_jobs) and max_age_hours input.

**TUI-092** — The TUI must display a live health indicator in the status bar that updates every
30 seconds via the `sys.heartbeat` WebSocket event or a background REST poll.

**TUI-093** — The TUI must display a "Backend unreachable" banner when HTTP requests fail with
connection errors, and offer a reconnect/retry command (mapped to `r`).

### 3.11 Job Application Tracker

**TUI-094** — The TUI must display the job application tracker as a Kanban-style text board or
table from `GET /tracker/applications` with columns by status.

**TUI-095** — The TUI must allow creating a new application entry with company name, role title,
URL, and linked resume.

**TUI-096** — The TUI must allow updating application status via `PATCH /tracker/applications/{id}`
with a status picker: `applied → phone_screen → technical → onsite → offer → rejected/withdrawn`.

**TUI-097** — The TUI must allow adding notes to an application entry.

**TUI-098** — The TUI must display application funnel stats (`GET /tracker/applications/stats`)
as an ASCII funnel diagram.

### 3.12 Cover Letter Generation

**TUI-099** — The TUI must allow generating a cover letter for a selected resume via
`POST /cover-letters/` with prompts for company name, role title, job description, tone, and
length.

**TUI-100** — The TUI must display the generated cover letter LaTeX content in a scrollable text
panel and offer to open it in `$EDITOR`.

**TUI-101** — The TUI must allow listing all cover letters (`GET /cover-letters/`) for the
current user.

### 3.13 Interview Prep

**TUI-102** — The TUI must allow generating interview questions for a selected resume via
`POST /interview/generate` with prompts for company name, role title, and job description.

**TUI-103** — The TUI must display the generated questions in a numbered list with the question,
type (behavioural/technical/situational), and a space for the user to type notes.

**TUI-104** — The TUI must allow listing past interview preps for a resume
(`GET /interview/resume/{resume_id}`).

### 3.14 Career and Other Features

**TUI-105** — The TUI must allow viewing the snippet marketplace (`GET /snippets/`), searching
by category, and importing a snippet into a resume (`POST /snippets/{id}/import`).

**TUI-106** — The TUI must allow managing keyboard macros (`GET /macros/`, `POST /macros/`,
`PUT`, `DELETE`) in a table with macro name, trigger key, and LaTeX expansion.

**TUI-107** — The TUI must display developer API key management (`GET /developer/keys`,
`POST /developer/keys`, `DELETE`) with key prefix, scopes, and usage stats.

**TUI-108** — Admin users must be able to list tenants (`GET /tenants/`), view tenant members,
and update tenant settings.

**TUI-109** — Team plan owners must be able to manage team seats (`GET /team/seats`,
`POST /team/seats/invite`, `DELETE /team/seats/{id}`).

### 3.15 CI/CD and Non-Interactive Mode

**TUI-110** — Every TUI command must support a `--json` flag that outputs structured JSON to
stdout and suppresses all terminal UI rendering.

**TUI-111** — The TUI must exit with code 0 on job success, code 1 on job failure, and code 2
on authentication or network errors.

**TUI-112** — The TUI must support environment variables for all configuration:
- `LATEXY_API_URL` — backend URL (default `http://localhost:8030`)
- `LATEXY_SESSION_TOKEN` — pre-authenticated session token
- `LATEXY_EMAIL` / `LATEXY_PASSWORD` — credentials for automatic login
- `LATEXY_DEFAULT_RESUME_ID` — resume to use when not specified

**TUI-113** — The TUI must provide a `compile` subcommand: `latexy compile <file.tex> [--compiler pdflatex] [--output resume.pdf] [--json]`.

**TUI-114** — The TUI must provide an `optimize` subcommand: `latexy optimize <resume_id> --jd <jd_file.txt> [--level balanced] [--model gpt-4o] [--json]`.

**TUI-115** — The TUI must provide an `ats` subcommand: `latexy ats score <resume_id> [--jd <jd_file.txt>] [--industry software_engineering] [--json]`.

**TUI-116** — The TUI must provide a `status` subcommand: `latexy status <job_id> [--wait] [--json]` that blocks until the job completes when `--wait` is specified.

**TUI-117** — In `--json` mode, `log.line` events must be written to stderr and structured result
to stdout, so they can be separated with standard shell redirection.

---

## 4. Non-Functional Requirements

### 4.1 Performance

**NFR-001** — The TUI must render the resume list within 500ms of startup (excluding network RTT).

**NFR-002** — `log.line` events must appear in the TUI log panel within 100ms of arrival on the
WebSocket.

**NFR-003** — `llm.token` events must update the token panel without visible lag — use Textual's
`call_from_thread` to post updates from the WebSocket background thread.

**NFR-004** — The TUI must not block the main event loop on any network I/O. All HTTP calls must
be async (`httpx.AsyncClient`) or run in a thread pool.

**NFR-005** — The TUI must debounce health check polls to at most one request per 30 seconds.

### 4.2 Security

**NFR-006** — Session tokens must be stored with `chmod 600` on the config file; the TUI must
warn if the file is world-readable on startup.

**NFR-007** — API keys entered for BYOK must not appear in terminal history. Use a masked input
widget (replaces characters with `*`).

**NFR-008** — The TUI must validate that LATEXY_API_URL starts with `https://` when connecting
to a non-localhost host, and warn if plain HTTP is used in production.

**NFR-009** — Credential environment variables must be consumed and cleared from the process
environment after login (`os.environ.pop`) to prevent leakage to child processes.

### 4.3 Offline Mode and Resilience

**NFR-010** — When the backend is unreachable at startup, the TUI must show an error screen with
the configured API URL and a retry prompt rather than crashing.

**NFR-011** — When the WebSocket connection drops during a job, the TUI must automatically
reconnect and replay missed events via `XREAD` (sending `last_event_id` in the subscribe message).

**NFR-012** — The TUI must not lose buffered log lines or token output during a WebSocket
reconnect — the local state accumulator must be preserved across reconnects.

**NFR-013** — REST API calls must use a 30-second timeout and retry up to 3 times with
exponential backoff (1s, 2s, 4s) on transient network errors (5xx, connection reset).

### 4.4 Compatibility

**NFR-014** — The TUI must support Python 3.11+ and run on macOS, Linux, and WSL2 (Windows).

**NFR-015** — Minimum terminal size: 80 columns × 24 rows. The TUI must degrade gracefully if
the terminal is narrower, collapsing non-essential panels.

**NFR-016** — The TUI must work in 256-colour and true-colour terminals. Colour selection must
fall back gracefully in 16-colour terminals.

**NFR-017** — The TUI must work over SSH without X forwarding — no GUI widgets or clipboard
operations that require a display server.

---

## 5. Architecture

### 5.1 Connection to the Backend

```
┌─────────────────────────────────────────────────────────────┐
│                   Latexy TUI Process                        │
│                                                             │
│  ┌─────────────┐    httpx.AsyncClient    ┌──────────────┐  │
│  │  Textual    │ ────────────────────── ▶│  REST API    │  │
│  │  App Loop   │ ◀────────────────────── │  :8030       │  │
│  │             │                         └──────────────┘  │
│  │             │    websockets library   ┌──────────────┐  │
│  │             │ ────────────────────── ▶│  WS /ws/jobs │  │
│  │             │ ◀── event messages ───── │  :8030       │  │
│  │             │                         └──────────────┘  │
│  └─────────────┘                                            │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Authentication Flow

```
1. User launches TUI
2. TUI checks ~/.config/latexy/config.toml for session_token
3. If token exists: GET /health → if 401 (token expired) → go to step 4
4. TUI shows login screen: email + password fields
5. POST https://<backend>/api/auth/sign-in/email
   Body: { "email": "...", "password": "..." }
   Response: { "token": "...", "user": { "id": "...", "email": "..." } }
6. Store token in config file (chmod 600)
7. Set default Authorization header: "Bearer <token>" on all API clients
8. Subscribe to /ws/jobs WebSocket with same token in Authorization header
9. Show main navigation screen
```

Note: Better Auth may use cookie-based sessions. If so, the TUI must capture the
`set-cookie: session=<token>` header from the login response and send `Cookie: session=<token>`
on subsequent requests. Test with the actual Better Auth instance to confirm the token transport.

### 5.3 WebSocket State Management

```python
# Background thread approach (not coroutine) to avoid asyncio/Textual conflicts
class LatexyWSClient:
    def __init__(self, ws_url: str, token: str, on_event: Callable):
        self.ws_url = ws_url
        self.token = token
        self.on_event = on_event   # Called with (event_dict) from background thread
        self._thread: Optional[threading.Thread] = None
        self._subscriptions: dict[str, str] = {}   # job_id → last_event_id
        self._stop_event = threading.Event()
        self._reconnect_delay = 0.1   # seconds, doubles up to 30s

    def connect(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def subscribe(self, job_id: str, last_event_id: str = "0") -> None:
        # Send {"type": "subscribe", "job_id": ..., "last_event_id": ...}
        ...

    def unsubscribe(self, job_id: str) -> None:
        # Send {"type": "unsubscribe", "job_id": ...}
        ...

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                with websocket.create_connection(
                    self.ws_url,
                    header={"Authorization": f"Bearer {self.token}"},
                ) as ws:
                    self._reconnect_delay = 0.1
                    # Re-subscribe to all active subscriptions with last seen id
                    for job_id, last_id in self._subscriptions.items():
                        ws.send(json.dumps({
                            "type": "subscribe",
                            "job_id": job_id,
                            "last_event_id": last_id,
                        }))
                    while not self._stop_event.is_set():
                        raw = ws.recv()
                        msg = json.loads(raw)
                        if msg["type"] == "event":
                            evt = msg["event"]
                            # Track last stream_id per job for replay on reconnect
                            self._subscriptions[evt["job_id"]] = msg.get("stream_id", "0")
                            self.on_event(evt)
            except Exception:
                time.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 30.0)
```

The `on_event` callback must use `app.call_from_thread(handler, event)` to safely post events
into Textual's message queue from the background thread.

### 5.4 REST Client

```python
import httpx

class LatexyAPIClient:
    def __init__(self, base_url: str, token: str):
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    async def get(self, path: str, **kwargs) -> dict:
        resp = await self._client.get(path, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def post(self, path: str, json: dict = None, **kwargs) -> dict:
        resp = await self._client.post(path, json=json, **kwargs)
        resp.raise_for_status()
        return resp.json()
    # ... put, patch, delete
```

### 5.5 Application State

The TUI maintains a single global `AppState` dataclass (see Section 9) held by the root
`LatexyApp` Textual application. Child screens and widgets access state by calling
`app.state`. State mutations always happen on the Textual main thread.

### 5.6 Screen Navigation Model

```
LatexyApp (root)
├── LoginScreen          — auth, no navigation bar
├── MainScreen           — permanent nav bar + dynamic content area
│   ├── ResumeListScreen — default view
│   ├── ResumeDetailScreen
│   │   ├── EditPanel (launches $EDITOR subprocess)
│   │   ├── CompilePanel (log streaming, progress)
│   │   ├── OptimizePanel (token streaming)
│   │   ├── ATSPanel (scores, recommendations)
│   │   ├── HistoryPanel (checkpoints, score sparkline)
│   │   └── AnalyticsPanel (resume views)
│   ├── JobMonitorScreen  — live job list + detail
│   ├── ATSScreen         — standalone ATS tools
│   ├── BYOKScreen        — API key management
│   ├── AnalyticsScreen   — user/system analytics
│   ├── BillingScreen     — subscription info
│   ├── TrackerScreen     — job application kanban
│   ├── HealthScreen      — system health + admin
│   └── SettingsScreen    — preferences, notifications
└── ErrorScreen          — backend unreachable
```

---

## 6. Screen and Panel Layout

### 6.1 Main Screen (Resume List)

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ Latexy TUI v1.0          riya@example.com    Plan: PRO    Backend: healthy    q:Quit │
├──────────────────────────┬──────────────────────────────────────────────────────────┤
│ [r] Resumes              │ Resumes  (42 total, 3 archived)          [/] Search       │
│ [j] Jobs                 │                                                           │
│ [a] ATS Tools            │ ▶  My Software Engineer Resume    resume  fresh  ★ ★      │
│ [b] BYOK Keys            │    Google SWE — Variant          resume  fresh   ↳ fork  │
│ [s] Analytics            │    Academic CV 2024              academic_cv  stale       │
│ [B] Billing              │    Product Manager Resume         resume  30d ago         │
│ [t] Job Tracker          │    ...                                                    │
│ [h] Health               │                                                           │
│ [q] Quit                 │ [n] New  [e] Edit  [c] Compile  [o] Optimize  [A] ATS    │
│                          │ [f] Fork [d] Delete [p] Pin  [T] Tag  [↵] Open           │
└──────────────────────────┴──────────────────────────────────────────────────────────┘
```

### 6.2 Resume Detail Screen — Compile Panel

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ Latexy TUI    My Software Engineer Resume    [e] Edit  [o] Optimize  [A] ATS  [←]  │
├────────────────────────────────────────────────────────────────────────────────────┤
│ COMPILE                                       Compiler: pdflatex         [c] Recompile│
├──────────────────────────┬─────────────────────────────────────────────────────────┤
│ PROGRESS                 │ LOG STREAM                                               │
│                          │                                                          │
│  Stage: latex_compiling  │ [log] This is pdflatex Version 3.14159265               │
│  ████████░░░░  60%       │ [log] entering extended mode                             │
│                          │ [err] LaTeX Warning: Font shape undefined                │
│ ● Completed              │ [log] Output written on resume.pdf (2 pages, 85234 bytes)│
│   Time:   2.3s           │ [log] Transcript written on resume.log.                  │
│   Size:   83 KB          │                                                          │
│   Pages:  2              │                                                          │
│                          │ [p] Download PDF  [l] View full log  [←] Back           │
└──────────────────────────┴─────────────────────────────────────────────────────────┘
```

### 6.3 Resume Detail Screen — Optimize Panel

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ Latexy TUI    My Software Engineer Resume    AI Optimize                     [←]    │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ Job Description: [software engineer at Google, building distributed systems...]     │
│ Level: ( ) conservative  (●) balanced  ( ) aggressive   Persona: [software_engineer]│
├──────────────────────────┬─────────────────────────────────────────────────────────┤
│ PROGRESS                 │ LLM TOKEN STREAM                                         │
│                          │                                                          │
│  Stage: llm_optimization │ \documentclass[letterpaper,11pt]{article}               │
│  ████████████░░  85%     │ \usepackage{latexsym}                                    │
│                          │ \usepackage[empty,scale=0.75]{geometry}                  │
│ Tokens: 1,247            │ ...                                                      │
│                          │                                                          │
│  ATS Score: 87.4 ▲ +6.2  │ [s] Save to resume  [e] Open in editor  [x] Cancel      │
│  Changes: 8 made         │                                                          │
└──────────────────────────┴─────────────────────────────────────────────────────────┘
```

### 6.4 ATS Scoring Panel

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ Latexy TUI    My Software Engineer Resume    ATS Score                       [←]    │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ Industry: Software Engineering (auto-detected)           Score: 82.5 / 100          │
│ ████████████████████░░░░  82.5%                                                     │
├──────────────────────────────────────┬──────────────────────────────────────────────┤
│ SECTION SCORES                       │ RECOMMENDATIONS                              │
│                                      │                                              │
│ Contact Info         ████████  92%   │ ● Add LinkedIn URL to contact section        │
│ Work Experience      ██████░░  78%   │ ● Quantify impact in work experience bullets │
│ Skills               ████████  88%   │ ● Add distributed systems keywords           │
│ Education            ████████  95%   │ ● Shorten summary to 2-3 sentences           │
│ Summary              ██████░░  75%   │                                              │
│ Keywords             ███████░  84%   │ Missing: Kubernetes, gRPC, Protobuf          │
│                                      │                                              │
│ ATS Compatibility: 79%               │ [d] Deep analysis  [S] Simulate ATS  [←]    │
│ Issues: 2 formatting, 1 keyword gap  │ [i] Industry profiles  [B] Benchmark         │
└──────────────────────────────────────┴──────────────────────────────────────────────┘
```

### 6.5 Job Monitor Screen

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ Latexy TUI    Job Monitor                                             [←] Back      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ JOB LIST                                                                            │
│                                                                                     │
│  job_id       type        status      stage           percent  updated              │
│  ─────────────────────────────────────────────────────────────────────────         │
│  3f2a1b8...   combined    ● running   llm_optimization   45%   2s ago              │
│  9e4c2d1...   latex       ✓ complete  done              100%   5min ago             │
│  7b1f3e0...   ats_scoring ✗ failed    ats_scoring         0%   12min ago            │
│                                                                                     │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ JOB DETAIL — 3f2a1b8...                                                             │
│                                                                                     │
│  Type: combined    Plan: pro    Estimated: 90s    Elapsed: 41s                      │
│  ████████████░░░░░░░░░  45%  Stage: LLM Optimization                                │
│                                                                                     │
│  LLM output: \documentclass[letterpaper,11pt]{article}\n\usepackage{latexsym}...   │
│                                                                                     │
│  [x] Cancel job  [↵] View full events  [r] Refresh list                            │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 6.6 Health Screen

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ Latexy TUI    System Health                                           [←] Back      │
├────────────────────────┬────────────────────────────────────────────────────────────┤
│ SERVICE STATUS         │ FEATURE FLAGS (admin only)                                 │
│                        │                                                            │
│ Backend API:   ● OK    │  Key             Enabled  Label                            │
│ Database:      ● OK    │  billing         ✓ ON     Billing subsystem               │
│ Redis:         ● OK    │  deep_analysis   ✓ ON     Deep ATS analysis               │
│ LaTeX:         ● OK    │  team_features   ✗ OFF    Team workspaces                 │
│ Celery:        ● OK    │                                                            │
│                        │  [t] Toggle flag                                           │
│ Version: 0.9.2         │                                                            │
├────────────────────────┴────────────────────────────────────────────────────────────┤
│ CLEANUP                                                                              │
│  Type: [temp_files ▾]    Max age: [24h ▾]    [c] Run cleanup                        │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Keyboard Shortcut Map

### 7.1 Global Shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit TUI (with confirmation if a job is running) |
| `?` or `F1` | Show help overlay |
| `←` or `Escape` | Go back / close modal |
| `Tab` | Move focus to next widget |
| `Shift+Tab` | Move focus to previous widget |
| `Ctrl+C` | Interrupt (same as quit) |

### 7.2 Main Navigation

| Key | Screen |
|-----|--------|
| `r` | Resume list |
| `j` | Job monitor |
| `a` | ATS tools |
| `b` or `k` | BYOK key management |
| `s` | Analytics dashboard |
| `B` | Billing / subscription |
| `t` | Job application tracker |
| `h` | System health |
| `S` | Settings |

### 7.3 Resume List

| Key | Action |
|-----|--------|
| `↑` / `↓` or `j` / `k` | Move selection |
| `Enter` | Open resume detail |
| `n` | New resume |
| `e` | Edit selected resume in `$EDITOR` |
| `c` | Compile selected resume |
| `o` | Optimize selected resume |
| `A` | ATS score selected resume |
| `f` | Fork selected resume |
| `d` | Delete selected resume (confirm) |
| `p` | Pin / unpin selected resume |
| `T` | Edit tags for selected resume |
| `z` | Archive / unarchive selected resume |
| `/` | Search resumes |
| `v` | Toggle view (archived / active) |
| `g` | Go to top of list |
| `G` | Go to bottom of list |

### 7.4 Compile Panel

| Key | Action |
|-----|--------|
| `c` | (Re)compile |
| `x` | Cancel running job |
| `p` | Download and open PDF |
| `l` | View full pdflatex log |
| `C` | Change compiler |
| `L` | Toggle log auto-scroll |

### 7.5 Optimize Panel

| Key | Action |
|-----|--------|
| `o` | Submit optimization (confirm prompts first) |
| `x` | Cancel running job |
| `s` | Save optimized LaTeX to resume |
| `e` | Open optimized LaTeX in `$EDITOR` |
| `d` | View diff between original and optimized |
| `L` | Toggle level (conservative / balanced / aggressive) |
| `P` | Select persona |

### 7.6 ATS Panel

| Key | Action |
|-----|--------|
| `A` | Run ATS score |
| `d` | Run deep analysis |
| `S` | Run ATS simulator |
| `i` | Select industry profile |
| `B` | View benchmark / percentile |
| `J` | Analyze job description |
| `q` | Quick score (rule-based, instant) |

### 7.7 Job Monitor

| Key | Action |
|-----|--------|
| `↑` / `↓` | Move job selection |
| `Enter` | View job detail / events |
| `x` | Cancel selected job |
| `r` | Refresh job list |
| `e` | View event stream (raw JSON) |
| `d` | Download result PDF (if complete) |

### 7.8 BYOK Screen

| Key | Action |
|-----|--------|
| `n` | Add new API key |
| `d` | Delete selected key |
| `t` | Test selected key |
| `v` | Validate key (enter key interactively) |
| `p` | Show providers list |

### 7.9 Checkpoints Panel

| Key | Action |
|-----|--------|
| `n` | Create new checkpoint (enter label) |
| `r` | Restore to selected checkpoint |
| `d` | Delete selected checkpoint |
| `v` | View checkpoint content |

---

## 8. Implementation Plan

### Phase 1 — MVP (Weeks 1–4)

**Goal:** A working TUI where a user can log in, list resumes, edit in `$EDITOR`, compile with
streaming logs, and see the result.

**Deliverables:**

1. **Project scaffold** — `pyproject.toml`, `latexy_tui/` package, entry point `latexy-tui`.
2. **Auth module** — `latexy_tui/auth.py`: login form, token storage, session validation.
3. **API client** — `latexy_tui/api.py`: `LatexyAPIClient` with all Phase 1 REST calls.
4. **WS client** — `latexy_tui/ws.py`: `LatexyWSClient` with reconnect and replay.
5. **LoginScreen** — email + password fields, error display, submit on Enter.
6. **ResumeListScreen** — `DataTable` widget with 8 columns, pagination, search bar.
7. **ResumeDetailScreen** with tabs: Edit, Compile, History.
8. **EditPanel** — launches `$EDITOR` subprocess, reads file back, saves via PUT API.
9. **CompilePanel** — job submit, progress bar, `RichLog` for `log.line` events, PDF download.
10. **StatusBar** — user email, plan, backend health indicator.
11. **Health check** — `GET /health` on startup, display degraded banner if needed.
12. **CI/CD mode** — `latexy compile <file.tex> --json` outputs `{"success": true, "job_id": "..."}`.

**Acceptance criteria for Phase 1:**
- User can `latexy-tui` and reach the resume list in < 2s.
- User can compile a resume and see log lines stream in the log panel.
- User can download the resulting PDF and it opens in the OS viewer.
- `latexy compile resume.tex --json` exits with code 0 on success, code 1 on failure.

### Phase 2 — Full Feature Set (Weeks 5–10)

**Goal:** All named features working: AI optimization, ATS, BYOK, analytics, billing, job tracker,
cover letters, interview prep.

**Deliverables:**

1. **OptimizePanel** — `llm.token` streaming in `TextArea`, level/persona selection.
2. **ATSPanel** — quick score, deep analyze, section table, compatibility view, benchmark.
3. **ATS Simulator** — profile selector, simulate call, per-field pass/fail display.
4. **BYOKScreen** — key table, add/delete/validate/test flows.
5. **AnalyticsScreen** — KPI cards, ASCII line chart for timeseries.
6. **BillingScreen** — plan cards, payment URL display, polling for activation.
7. **TrackerScreen** — application table, status picker, notes editor.
8. **CheckpointPanel** — list with ATS sparkline, create/restore/delete.
9. **CoverLetterFlow** — prompts, generation job + token stream, view/edit result.
10. **InterviewPrepFlow** — prompts, generation, numbered question list.
11. **BatchTailorFlow** — multi-row form, submit batch, progress table.
12. **SearchScreen** — full-text search with highlighted match excerpts.
13. **ShareLink** — generate, display, copy to clipboard, revoke.
14. **SnippetBrowser** — list, search, import to resume.
15. **MacroManager** — CRUD table.
16. **CI/CD commands** — `latexy optimize`, `latexy ats`, `latexy status`.

**Acceptance criteria for Phase 2:**
- All 117 functional requirements (TUI-001 through TUI-117) pass manual test.
- CI/CD mode tested in a GitHub Actions job that compiles and scores a resume.

### Phase 3 — Admin, Polish, and Plugin System (Weeks 11–16)

**Goal:** Admin/health panel for DevOps, deep CI/CD integration, plugin hooks, and production polish.

**Deliverables:**

1. **HealthScreen** — full service status table, feature flag toggle, cleanup trigger.
2. **Admin analytics** — system-wide stats, funnel diagram (admin role required).
3. **Tenant management** — list tenants, members, settings (for agency plan users).
4. **Developer API keys** — manage public API keys with scope and usage.
5. **Team seats** — invite, list, revoke.
6. **Job scraper** — URL input → scraped JD → auto-fill optimize form.
7. **GitHub sync flow** — browser-redirect OAuth, push-to-repo action.
8. **Dropbox sync flow** — browser-redirect OAuth, sync action.
9. **Plugin system** — `~/.config/latexy/plugins/` directory; TUI loads Python plugins that
   can add new screens and API calls.
10. **Error history panel** — per-user LaTeX error history with resolution status.
11. **Academic CV converter** — detection report + conversion wizard.
12. **Accessibility** — all interactive widgets labelled for screen readers; `aria`-equivalent
    Textual `TOOLTIP` strings on all buttons.
13. **Configuration screen** — live edit of `~/.config/latexy/config.toml` in TUI.
14. **Benchmark panel** — cohort percentile + ASCII histogram.
15. **Production package** — published to PyPI as `latexy-tui`; standalone binary via PyInstaller.

**Acceptance criteria for Phase 3:**
- DevOps engineer can toggle feature flags and trigger cleanup over SSH.
- CI/CD mode produces zero non-JSON output on stdout when `--json` is set.
- Plugin API documented with one example plugin that adds a custom screen.

---

## 9. TUI State Data Models

```python
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class AuthState:
    email: Optional[str] = None
    session_token: Optional[str] = None
    user_id: Optional[str] = None
    plan: str = "free"
    is_authenticated: bool = False


@dataclass
class JobEvent:
    event_id: str
    job_id: str
    timestamp: float
    sequence: int
    type: str
    data: dict = field(default_factory=dict)


@dataclass
class JobState:
    job_id: str
    job_type: str
    status: str = "queued"    # queued | processing | running | completed | failed | cancelled
    stage: str = ""
    percent: int = 0
    estimated_seconds: int = 0
    started_at: Optional[float] = None
    last_updated: float = 0.0
    events: list[JobEvent] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)
    llm_tokens: list[str] = field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None
    pdf_job_id: Optional[str] = None
    ats_score: Optional[float] = None
    tokens_used: Optional[int] = None
    page_count: Optional[int] = None


@dataclass
class ResumeItem:
    id: str
    title: str
    document_type: str
    tags: list[str]
    freshness_status: str
    variant_count: int
    updated_at: datetime
    parent_resume_id: Optional[str]
    share_token: Optional[str]
    pinned: bool = False
    archived: bool = False
    latex_content: Optional[str] = None   # only loaded on demand
    compiler: str = "pdflatex"
    ats_score: Optional[float] = None     # from last optimization record


@dataclass
class ATSResult:
    overall_score: float
    category_scores: dict[str, float]
    recommendations: list[str]
    strengths: list[str]
    warnings: list[str]
    industry_key: Optional[str]
    industry_label: Optional[str]
    sections: list[dict] = field(default_factory=list)   # ATSDeepSection
    ats_compatibility: Optional[dict] = None
    job_match: Optional[dict] = None
    multi_dim_scores: Optional[dict] = None
    analysis_time: float = 0.0
    tokens_used: int = 0


@dataclass
class SubscriptionState:
    plan_id: str = "free"
    plan_name: str = "Free"
    status: str = "inactive"
    features: dict = field(default_factory=dict)
    current_period_end: Optional[str] = None
    subscription_id: Optional[str] = None


@dataclass
class AppState:
    auth: AuthState = field(default_factory=AuthState)
    subscription: SubscriptionState = field(default_factory=SubscriptionState)
    resumes: list[ResumeItem] = field(default_factory=list)
    active_jobs: dict[str, JobState] = field(default_factory=dict)   # job_id → JobState
    health_status: str = "unknown"    # healthy | degraded | unhealthy | unknown
    api_url: str = "http://localhost:8030"
    ws_connected: bool = False
    last_health_check: float = 0.0
    selected_resume_id: Optional[str] = None
    current_screen: str = "resume_list"
```

---

## 10. Testing Strategy

### 10.1 Unit Tests

- Auth module: test token storage, token loading, 401 detection.
- API client: mock `httpx` responses, test retry logic and timeout.
- WS client: mock websocket messages, test event dispatch and reconnect.
- State models: test state transitions (queued → running → completed).
- CI/CD output formatter: test JSON serialization of all result types.
- Event accumulator: test that `llm.token` events accumulate correctly, sequence ordering.

### 10.2 Integration Tests

- End-to-end compile job: submit → poll state → verify `job.completed` event arrives.
- End-to-end optimize job: submit → verify `llm.token` events, then `job.completed`.
- Auth flow: login with test credentials → verify token stored → verify 401 recovery.
- Resume CRUD: create → list → update → delete → verify not in list.
- BYOK: add key → list → test → delete.

### 10.3 Snapshot Tests (Textual)

Use Textual's built-in `pilot` and snapshot testing framework:

```python
async def test_resume_list_renders(snap_compare):
    app = LatexyApp()
    assert await snap_compare(app, press=["r"])
```

Snapshot tests confirm that screen layout does not regress across refactors.

### 10.4 CI/CD Mode Tests

GitHub Actions job that:
1. Spins up the Latexy backend via `docker-compose.test.yml`.
2. Runs `latexy compile tests/fixtures/sample.tex --json` and asserts exit code 0.
3. Runs `latexy ats score <resume_id> --jd tests/fixtures/jd.txt --json` and asserts
   `ats_score` in JSON output.
4. Runs `latexy optimize <resume_id> --jd tests/fixtures/jd.txt --json` and asserts
   `success: true`.

### 10.5 Manual Test Checklist (per release)

- Login with valid credentials.
- Login with invalid credentials (error display).
- Session expiry (manually expire token in DB, verify re-auth prompt).
- Compile with syntax error (verify error line highlighted in red).
- Compile success (verify PDF opens in OS viewer).
- Cancel running job (verify `job.cancelled` event in panel).
- WebSocket disconnect during job (kill Redis, verify reconnect and replay).
- ATS score on resume without job description (verify industry auto-detect).
- BYOK key addition (verify masked input, validation success/failure).
- Billing upgrade (verify `short_url` displayed, plan poll detects change).
- `--json` output on all subcommands (pipe through `jq` to verify valid JSON).

---

## 11. Technology Choices

### 11.1 Core TUI Framework

**Textual** (https://github.com/Textualize/textual) version 0.60+

- Python-native reactive TUI framework.
- `Screen`, `Widget`, `DataTable`, `TextArea`, `RichLog`, `ProgressBar`, `Input` built-in.
- CSS-like styling, responsive layout.
- Built-in async event loop that integrates naturally with `asyncio`.
- `app.call_from_thread()` for safe cross-thread widget updates (required for WS client).
- `Pilot` for headless testing.

Alternatives considered: `urwid` (older API, less modern), `blessed` (too low-level),
`prompt_toolkit` (more CLI-oriented than TUI).

### 11.2 HTTP Client

**httpx** version 0.27+

- Async-native, drop-in `requests` replacement.
- Supports async/await naturally within Textual's asyncio event loop.
- Built-in retry and timeout support.
- Excellent for multipart/form-data uploads (file import, compile).

### 11.3 WebSocket Client

**websockets** version 12+

- Used in a background daemon thread (not async) to avoid asyncio loop conflicts with Textual.
- Alternatively: `websocket-client` (sync-only, simpler threading model).
- The WS client thread calls `app.call_from_thread()` to safely dispatch events.

### 11.4 Rich Output

**rich** version 13+

- Already a Textual dependency.
- `rich.table.Table` for tabular analytics.
- `rich.syntax.Syntax` for LaTeX highlighting in diff view.
- `rich.progress.Progress` for the CI/CD mode progress bar (non-Textual).
- `rich.json.JSON` for raw event JSON inspector.

### 11.5 ASCII Charts

**plotext** (https://github.com/piccolomo/plotext)

- Pure Python terminal plotting library.
- Renders line charts, bar charts, and sparklines as ASCII/unicode.
- No external dependencies.
- Used for: compilation timeseries, ATS score history sparkline, multi-dim score bars.

### 11.6 Configuration

**tomllib** (Python 3.11+ stdlib) + **tomli-w** for writing TOML config files.

Config file location: `~/.config/latexy/config.toml`

```toml
[auth]
email = "user@example.com"
session_token = "sess_..."

[api]
url = "http://localhost:8030"
ws_url = "ws://localhost:8030/ws/jobs"

[tui]
editor = ""    # empty = use $EDITOR env var
color_theme = "dark"
default_compiler = "pdflatex"
```

### 11.7 Clipboard

**pyperclip** version 1.8+ — cross-platform clipboard access for copy-to-clipboard on share
link generation. Gracefully falls back to displaying the URL if no clipboard is available.

### 11.8 Diff Rendering

**difflib** (Python stdlib) for unified diff between original and optimized LaTeX.
Rendered with `rich.syntax.Syntax(diff_text, "diff")` for colour-coded output.

### 11.9 Package Distribution

- **PyPI**: `pip install latexy-tui` — entry point `latexy-tui` for interactive mode.
- **Standalone binary**: `pyinstaller --onefile` for environments without Python.
- **Docker**: `FROM python:3.11-slim; RUN pip install latexy-tui` for containerised CI/CD use.

### 11.10 Dependency Matrix

| Package | Version | Purpose |
|---------|---------|---------|
| textual | >=0.60 | TUI framework |
| httpx | >=0.27 | Async REST client |
| websockets | >=12.0 | WebSocket client |
| rich | >=13.0 | Text rendering (Textual dep) |
| plotext | >=5.2 | ASCII charts |
| tomli-w | >=1.0 | TOML config writing |
| pyperclip | >=1.8 | Clipboard integration |
| click | >=8.0 | CLI argument parsing (CI/CD mode) |
| python-dotenv | >=1.0 | .env file support for CI/CD |

**Python version:** 3.11+ (required for `tomllib` stdlib and `match` statement pattern matching
used in event dispatch).

---

*End of document.*
