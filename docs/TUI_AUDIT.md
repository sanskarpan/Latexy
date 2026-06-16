# Latexy TUI Audit

**Purpose:** Comprehensive technical audit of the Latexy codebase for the purpose of building a
Python/Textual Terminal User Interface (TUI). This document catalogues every API endpoint, WebSocket
event, database model, Celery worker, and Redis key namespace, then evaluates which features are
feasible in a terminal environment and which require workarounds.

**Audit date:** 2026-06-15  
**Branch audited:** track/477-api-client-response

---

## Table of Contents

1. Backend API Endpoints
2. WebSocket Event Types
3. Database Models
4. Celery Workers and Task Signatures
5. Redis Key Namespaces
6. Frontend Pages and Data
7. Identified Gaps and TUI Constraints
8. Feasibility Summary

---

## 1. Backend API Endpoints

All endpoints are served from `http://localhost:8030` (dev). The router is assembled in
`backend/app/api/routes.py` and includes sub-routers from every domain module.

### 1.1 System / Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Overall service health: LaTeX, DB, Redis status |
| GET | `/metrics` | None | Prometheus scrape endpoint (not in OpenAPI schema) |
| GET | `/jobs/health` | None | Job system health: Redis connectivity and queue info |

`HealthResponse` fields: `status`, `version`, `latex_available`, `database`, `redis`

### 1.2 Compile (synchronous, legacy path)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/compile` | Optional | Compile LaTeX to PDF (multipart or form field) |
| POST | `/public/compile` | None | Anonymous compile with trial limit enforcement |
| GET | `/download/{job_id}` | None | Download compiled PDF by job_id |
| GET | `/download/{job_id}/synctex` | None | Download decompressed SyncTeX data |
| GET | `/logs/{job_id}` | None | Fetch pdflatex log file for a job |
| POST | `/optimize` | None | Synchronous LLM optimization (no streaming) |
| POST | `/optimize-and-compile` | None | Synchronous optimize then compile in one call |

### 1.3 Jobs (async, event-driven — primary path)

Prefix: `/jobs`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/jobs/submit` | Optional | Submit a new async job to Celery |
| POST | `/jobs/compile-watermarked` | Optional | Submit compile job with watermark overlay |
| POST | `/jobs/batch` | Required | Fork resume N times and submit combined jobs for each |
| GET | `/jobs/batch/{batch_id}` | Required | Poll aggregated status for a batch |
| GET | `/jobs/{job_id}/state` | Optional | REST polling fallback for current job state |
| GET | `/jobs/{job_id}/result` | Optional | Fetch final job result after completion |
| DELETE | `/jobs/{job_id}` | Optional | Request cancellation (sets Redis cancel flag) |
| GET | `/jobs/` | Optional | List recent jobs for authenticated user (ZSET) |
| POST | `/jobs/system/cleanup` | None | Trigger background cleanup Celery task |

**JobSubmissionRequest fields:**
- `job_type`: `"latex_compilation"` | `"llm_optimization"` | `"combined"` | `"ats_scoring"`
- `latex_content` (str): required for all types except `ats_scoring`
- `job_description` (str, optional): required for `llm_optimization` and `combined`
- `optimization_level`: `"conservative"` | `"balanced"` | `"aggressive"`
- `user_plan`: `"free"` | `"basic"` | `"pro"` | `"byok"` | `"team"`
- `device_fingerprint` (str, optional)
- `industry` (str, optional): ATS industry override
- `target_sections` (list[str], optional): sections to focus optimization on
- `custom_instructions` (str, optional): free-text LLM instructions
- `model` (str, optional): LLM model override
- `compiler`: `"pdflatex"` | `"xelatex"` | `"lualatex"`
- `persona` (str, optional): optimization persona key

**JobStateResponse fields:** `status`, `stage`, `percent`, `last_updated`

**Job status values:** `queued` | `processing` | `running` | `completed` | `failed` | `cancelled`

### 1.4 Resumes

Prefix: `/resumes`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/resumes/` | Required | List resumes (paginated, filter by archived/document_type) |
| POST | `/resumes/` | Required | Create a new resume |
| GET | `/resumes/stats` | Required | Aggregated stats: count, avg ATS score, best ATS score |
| GET | `/resumes/search` | Required | Full-text search across title + LaTeX content |
| GET | `/resumes/error-history` | Required | Grouped LaTeX error history per user |
| GET | `/resumes/export/bulk` | Required | ZIP export of all resumes (tex/pdf/docx) |
| GET | `/resumes/{resume_id}` | Required | Fetch one resume by ID |
| PUT | `/resumes/{resume_id}` | Required | Full update of a resume |
| DELETE | `/resumes/{resume_id}` | Required | Delete a resume |
| PATCH | `/resumes/{resume_id}/settings` | Required | Update per-resume compiler/flags/TeX settings |
| PATCH | `/resumes/{resume_id}/tags` | Required | Replace tags on a resume |
| PATCH | `/resumes/{resume_id}/pin` | Required | Pin resume to top of workspace |
| PATCH | `/resumes/{resume_id}/unpin` | Required | Unpin resume |
| PATCH | `/resumes/{resume_id}/archive` | Required | Soft-archive resume |
| PATCH | `/resumes/{resume_id}/unarchive` | Required | Restore archived resume |
| POST | `/resumes/{resume_id}/fork` | Required | Create a variant (fork) of a resume |
| POST | `/resumes/{resume_id}/quick-tailor` | Required | Fork + kick off aggressive optimization |
| GET | `/resumes/{resume_id}/variants` | Required | List all child variants of a resume |
| GET | `/resumes/{resume_id}/diff-with-parent` | Required | Get raw LaTeX diff vs parent |
| POST | `/resumes/{resume_id}/record-optimization` | Required | Save optimization record after job |
| GET | `/resumes/{resume_id}/optimization-history` | Required | Last 20 optimization records |
| GET | `/resumes/{resume_id}/score-history` | Required | ATS score timeseries for chart |
| POST | `/resumes/{resume_id}/restore-optimization/{opt_id}` | Required | Restore to prior optimization |
| POST | `/resumes/{resume_id}/checkpoints` | Required | Create named manual checkpoint |
| GET | `/resumes/{resume_id}/checkpoints` | Required | List all checkpoints + auto-saves |
| GET | `/resumes/{resume_id}/checkpoints/{checkpoint_id}/content` | Required | Fetch LaTeX of a checkpoint |
| DELETE | `/resumes/{resume_id}/checkpoints/{checkpoint_id}` | Required | Delete a manual checkpoint |
| POST | `/resumes/{resume_id}/share` | Required | Create/update share link |
| DELETE | `/resumes/{resume_id}/share` | Required | Revoke share link |
| GET | `/resumes/{resume_id}/analytics` | Required | View analytics for a resume |
| GET | `/resumes/{resume_id}/academic-cv-report` | Required | Detect if resume looks like academic CV |
| POST | `/resumes/{resume_id}/academic-cv-convert` | Required | Convert academic CV to industry resume fork |
| POST | `/resumes/{resume_id}/collaborators` | Required | Invite collaborator by email |
| GET | `/resumes/{resume_id}/collaborators` | Required | List collaborators |
| PATCH | `/resumes/{resume_id}/collaborators/{collab_id}` | Required | Update collaborator role |
| DELETE | `/resumes/{resume_id}/collaborators/{collab_id}` | Required | Remove collaborator |

**Builder sub-routes** (guided resume builder):

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/resumes/builder/templates` | None | List builder-compatible templates |
| POST | `/resumes/builder/seed-upload` | Required | Parse uploaded file to structured content |
| POST | `/resumes/builder` | Required | Create resume via guided builder |
| GET | `/resumes/{resume_id}/builder` | Required | Get builder data for a resume |
| PATCH | `/resumes/{resume_id}/builder` | Required | Update resume via builder |

**ResumeResponse key fields:** `id`, `user_id`, `title`, `latex_content`, `document_type`,
`parent_resume_id`, `variant_count`, `content_source`, `builder_status`, `tags`, `share_token`,
`share_url`, `github_sync_enabled`, `metadata` (resume_settings), `pinned`, `archived_at`,
`days_since_updated`, `freshness_status`, `created_at`, `updated_at`

### 1.5 ATS Scoring

Prefix: `/ats`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/ats/score` | Optional | Score resume (async or sync) |
| POST | `/ats/analyze-job` | Optional | Extract keywords from job description |
| POST | `/ats/recommendations` | Optional | Generate improvement recommendations |
| GET | `/ats/industry-profiles` | None | List available industry ATS profiles |
| GET | `/ats/industry-profiles/{key}` | None | Fetch specific industry profile |
| POST | `/ats/quick-score` | Optional | Lightweight rule-based ATS score (no LLM) |
| POST | `/ats/deep-analyze` | Optional | Deep LLM-based analysis (layer 2) |
| GET | `/ats/job-match/{resume_id}` | Required | Semantic job match vs last embedding |
| GET | `/ats/simulator` | None | List ATS simulator profiles |
| POST | `/ats/simulate` | Optional | Simulate resume through a specific ATS |
| GET | `/ats/benchmark` | Optional | Compare ATS score to cohort percentile |

### 1.6 BYOK (Bring Your Own Key)

Prefix: `/byok`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/byok/keys` | Required | Add an API key for a provider |
| GET | `/byok/keys` | Required | List all stored API keys (masked) |
| DELETE | `/byok/keys/{key_id}` | Required | Delete a stored API key |
| POST | `/byok/validate` | Required | Validate an API key against provider |
| GET | `/byok/providers` | Required | List supported LLM providers |
| POST | `/byok/test/{provider}` | Required | Test the stored key for a provider |
| GET | `/byok/usage` | Required | Token usage stats per provider |

**Supported providers:** `openai`, `anthropic`, `openrouter`, `gemini`

### 1.7 Analytics

Prefix: `/analytics`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/analytics/track` | None | Track an analytics event |
| GET | `/analytics/user` | Required | Aggregated user analytics (compilations, optimizations) |
| GET | `/analytics/user/timeseries` | Required | Detailed timeseries for user activity |
| GET | `/analytics/system` | Admin | System-wide analytics (admin only) |
| GET | `/analytics/funnel` | Admin | Conversion funnel data (admin only) |

### 1.8 Subscriptions and Billing

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/subscription/plans` | None | Available plans (free, basic, pro, byok, team) |
| POST | `/subscription/create` | Required | Create a new subscription via Razorpay |
| GET | `/subscription/current` | Required | Fetch current user subscription |
| POST | `/subscription/cancel` | Required | Cancel current subscription |
| GET | `/subscription/student/verify/{token}` | None | Verify student email for student plan |
| POST | `/billing/validate-coupon` | Optional | Validate a coupon code |
| POST | `/billing/webhook` | None | Razorpay webhook handler (HMAC verified) |

### 1.9 Trial System (Anonymous)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/public/trial-status` | None | Trial usage for a device fingerprint |
| POST | `/public/track-usage` | None | Track anonymous usage atomically |

### 1.10 Public Share

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/share/{share_token}` | None | Public resume view: returns presigned PDF URL |

### 1.11 Tenants (White-label / Multi-tenant)

Prefix: `/tenants`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/tenants/` | Required | Create a new tenant |
| GET | `/tenants/` | Required | List tenants the current user belongs to |
| GET | `/tenants/{tenant_id}` | Required | Fetch tenant details |
| PUT | `/tenants/{tenant_id}` | Required | Update tenant (owner only) |
| DELETE | `/tenants/{tenant_id}` | Required | Delete tenant (owner only) |
| POST | `/tenants/{tenant_id}/members` | Required | Add member to tenant |
| GET | `/tenants/{tenant_id}/members` | Required | List tenant members |
| DELETE | `/tenants/{tenant_id}/members/{member_id}` | Required | Remove tenant member |
| GET | `/tenants/{tenant_id}/stats` | Required | Tenant usage statistics |

### 1.12 Team Billing Seats

Prefix: `/team`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/team/seats/invite` | Required | Invite user to team seat |
| GET | `/team/seats` | Required | List own team seats |
| DELETE | `/team/seats/{seat_id}` | Required | Revoke team seat |
| POST | `/team/seats/accept` | Required | Accept team seat invitation |

### 1.13 Cover Letters

Prefix: `/cover-letters`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/cover-letters/` | Required | Generate a new cover letter for a resume |
| GET | `/cover-letters/` | Required | List cover letters |
| GET | `/cover-letters/{cover_letter_id}` | Required | Fetch one cover letter |
| DELETE | `/cover-letters/{cover_letter_id}` | Required | Delete cover letter |
| POST | `/cover-letters/{cover_letter_id}/compile` | Required | Compile cover letter LaTeX to PDF |

### 1.14 Templates

Prefix: `/templates`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/templates/` | None | List all active templates |
| GET | `/templates/{template_id}` | None | Fetch template by ID |
| GET | `/templates/{template_id}/thumbnail` | None | Serve template thumbnail image |
| GET | `/templates/{template_id}/pdf` | None | Serve template preview PDF |

### 1.15 Format Detection

Prefix: `/format`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/format/supported` | None | List supported resume formats |
| POST | `/format/detect` | None | Detect format of an uploaded file |
| POST | `/format/convert` | Optional | Convert uploaded file to LaTeX |

### 1.16 Export

Prefix: `/export`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/export/docx` | Required | Export a resume as DOCX |
| POST | `/export/markdown` | Required | Export a resume as Markdown |
| POST | `/export/html` | Required | Export a resume as HTML |

### 1.17 AI Tools

Prefix: `/ai`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/ai/enhance-bullet` | Required | Rewrite a single bullet point |
| POST | `/ai/skills-gap` | Required | Identify skills gap vs job description |
| POST | `/ai/keywords` | Required | Extract keywords from content |
| POST | `/ai/career-objective` | Required | Generate career objective statement |

### 1.18 References (BibTeX)

Prefix: `/references`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/references/parse` | Required | Parse a BibTeX string |
| POST | `/references/format` | Required | Format references as LaTeX |
| GET | `/references/{resume_id}` | Required | List references for a resume |

### 1.19 Job Application Tracker

Prefix: `/tracker`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/tracker/applications` | Required | Create a job application entry |
| GET | `/tracker/applications` | Required | List applications with filters |
| GET | `/tracker/applications/{id}` | Required | Fetch one application |
| PATCH | `/tracker/applications/{id}` | Required | Update application status/notes |
| DELETE | `/tracker/applications/{id}` | Required | Delete application |
| GET | `/tracker/applications/stats` | Required | Application funnel stats |

**Application status values:** `applied` | `phone_screen` | `technical` | `onsite` | `offer` |
`rejected` | `withdrawn`

### 1.20 Interview Prep

Prefix: `/interview`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/interview/generate` | Required | Generate interview questions from resume + JD |
| GET | `/interview/{interview_id}` | Required | Fetch generated questions |
| GET | `/interview/resume/{resume_id}` | Required | List interview preps for a resume |
| DELETE | `/interview/{interview_id}` | Required | Delete an interview prep |

### 1.21 Job Scraper

Prefix: `/scraper`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/scraper/scrape` | Required | Scrape job description from a URL |

### 1.22 GitHub Integration

Prefix: `/github`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/github/auth` | Required | Start GitHub OAuth flow |
| GET | `/github/callback` | None | Handle GitHub OAuth callback |
| POST | `/github/sync/{resume_id}` | Required | Push resume LaTeX to GitHub repo |
| GET | `/github/repos` | Required | List user's GitHub repos |
| DELETE | `/github/disconnect` | Required | Unlink GitHub account |

### 1.23 Zotero / Mendeley Integrations

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/zotero/auth` | Required | Start Zotero OAuth |
| GET | `/zotero/callback` | None | Zotero OAuth callback |
| GET | `/zotero/collections` | Required | List Zotero collections |
| GET | `/zotero/items/{collection_id}` | Required | List BibTeX items in collection |
| GET | `/mendeley/auth` | Required | Start Mendeley OAuth |
| GET | `/mendeley/callback` | None | Mendeley OAuth callback |
| GET | `/mendeley/documents` | Required | List Mendeley documents |

### 1.24 Team Workspaces

Prefix: `/workspaces`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/workspaces/` | Required | Create a shared workspace |
| GET | `/workspaces/` | Required | List workspaces |
| GET | `/workspaces/{workspace_id}` | Required | Fetch workspace details |
| POST | `/workspaces/{workspace_id}/members` | Required | Add member |
| DELETE | `/workspaces/{workspace_id}/members/{member_id}` | Required | Remove member |

### 1.25 Resume Comments

Prefix: `/comments`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/comments/{resume_id}` | Required | Add comment to a resume |
| GET | `/comments/{resume_id}` | Required | List comments on a resume |
| PATCH | `/comments/{resume_id}/{comment_id}` | Required | Update comment |
| DELETE | `/comments/{resume_id}/{comment_id}` | Required | Delete comment |

### 1.26 Dropbox Sync

Prefix: `/dropbox`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/dropbox/auth` | Required | Start Dropbox OAuth |
| GET | `/dropbox/callback` | None | Dropbox OAuth callback |
| POST | `/dropbox/sync/{resume_id}` | Required | Push resume to Dropbox folder |
| DELETE | `/dropbox/disconnect` | Required | Unlink Dropbox account |

### 1.27 Portfolio

Prefix: `/portfolio`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/portfolio/` | Required | Fetch portfolio config |
| PATCH | `/portfolio/` | Required | Update portfolio settings |
| POST | `/portfolio/publish` | Required | Enable public portfolio |
| GET | `/portfolio/u/{username}` | None | Public portfolio by username |

### 1.28 Career Path

Prefix: `/career`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/career/paths` | Required | Generate a career path analysis |
| GET | `/career/paths` | Required | List career paths |
| GET | `/career/paths/{path_id}` | Required | Fetch one career path |
| DELETE | `/career/paths/{path_id}` | Required | Delete a career path |

### 1.29 Snippets Marketplace

Prefix: `/snippets`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/snippets/` | None | List marketplace snippets |
| GET | `/snippets/{snippet_id}` | None | Fetch snippet details |
| POST | `/snippets/` | Required | Publish a snippet |
| PATCH | `/snippets/{snippet_id}` | Required | Update own snippet |
| DELETE | `/snippets/{snippet_id}` | Required | Delete own snippet |
| POST | `/snippets/{snippet_id}/import` | Required | Import snippet into a resume |

### 1.30 Keyboard Macros

Prefix: `/macros`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/macros/` | Required | List macros |
| POST | `/macros/` | Required | Create macro |
| PUT | `/macros/{macro_id}` | Required | Update macro |
| DELETE | `/macros/{macro_id}` | Required | Delete macro |

### 1.31 Developer API and Public API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/developer/keys` | Required | Create a developer API key |
| GET | `/developer/keys` | Required | List developer API keys |
| DELETE | `/developer/keys/{key_id}` | Required | Delete developer API key |
| GET | `/developer/usage` | Required | Developer API usage stats |
| POST | `/v1/compile` | API Key | Public API: compile endpoint |
| POST | `/v1/optimize` | API Key | Public API: optimize endpoint |
| POST | `/v1/ats/score` | API Key | Public API: ATS score endpoint |

### 1.32 One-Click Applications

Prefix: `/applications`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/applications/submit` | Required | Submit one-click job application |
| GET | `/applications/{submission_id}` | Required | Track submission status |

### 1.33 Settings and Notifications

Prefix: `/settings`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/settings/notifications` | Required | Fetch notification preferences |
| PATCH | `/settings/notifications` | Required | Update notification preferences |

### 1.34 Admin

Prefix: `/admin`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/admin/feature-flags` | Admin | List all feature flags |
| PATCH | `/admin/feature-flags/{key}` | Admin | Toggle a feature flag |
| GET | `/admin/config` | None | Public config (plans, limits) |

### 1.35 WebSocket

| Protocol | Path | Auth | Description |
|----------|------|------|-------------|
| WS | `/ws/jobs` | Optional | Multiplexed job event stream |

**WebSocket client messages:**
- `{ type: "subscribe", job_id, last_event_id? }` — subscribe to job events (with optional replay)
- `{ type: "unsubscribe", job_id }` — stop receiving events for a job
- `{ type: "cancel", job_id }` — request job cancellation
- `{ type: "ping" }` — keepalive

**WebSocket server messages:**
- `{ type: "subscribed", job_id, replayed_count }` — subscription ack with replay count
- `{ type: "unsubscribed", job_id }` — unsubscription ack
- `{ type: "cancelled", job_id }` — cancellation ack
- `{ type: "pong", server_time }` — heartbeat response
- `{ type: "event", event: AnyEvent }` — a job event
- `{ type: "error", code, message }` — server-side error

---

## 2. WebSocket Event Types

Source: `frontend/src/lib/event-types.ts`

All events extend `BaseEvent`:
```typescript
{
  event_id: string,    // UUID
  job_id: string,      // UUID
  timestamp: number,   // Unix epoch float
  sequence: number,    // monotonically increasing per job
  type: EventType      // discriminant string
}
```

### 2.1 Job Lifecycle Events

| Event Type | Key Fields | Description |
|-----------|------------|-------------|
| `job.queued` | `job_type`, `user_id`, `estimated_seconds` | Job accepted by API, placed in Celery queue |
| `job.started` | `worker_id`, `stage` | Celery worker picked up the task |
| `job.progress` | `percent` (0-100), `stage`, `message` | Intermediate progress milestone |
| `job.completed` | `pdf_job_id`, `ats_score`, `ats_details`, `changes_made`, `compilation_time`, `optimization_time`, `tokens_used`, `page_count` | Job finished successfully |
| `job.failed` | `stage`, `error_code`, `error_message`, `retryable`, `optimized_latex?`, `changes_made?`, `upgrade_message?`, `user_plan?` | Job failed with error details |
| `job.cancelled` | _(no extra fields)_ | Job was cancelled by user or system |

### 2.2 LLM Streaming Events

| Event Type | Key Fields | Description |
|-----------|------------|-------------|
| `llm.token` | `token` (str) | Single token delta from OpenAI streaming |
| `llm.complete` | `full_content`, `tokens_total` | Full assembled LaTeX + token count |

`llm.token` events are filtered to only include tokens between `<<<LATEX>>>` and `<<<END_LATEX>>>` markers.

### 2.3 LaTeX Log Events

| Event Type | Key Fields | Description |
|-----------|------------|-------------|
| `log.line` | `source` (str), `line` (str), `is_error` (bool) | Single pdflatex log line, streaming |

### 2.4 ATS Events

| Event Type | Key Fields | Description |
|-----------|------------|-------------|
| `job.pdf_extracted` | `text` (str), `page_count` (int) | PDF text extracted for deep ATS analysis |
| `ats.deep_complete` | `overall_score`, `overall_feedback`, `sections`, `ats_compatibility`, `job_match`, `tokens_used`, `analysis_time`, `multi_dim_scores?`, `industry_key?`, `industry_label?` | Deep LLM-based ATS analysis complete |

**ATSDeepSection structure:**
```
{ name, score, strengths[], improvements[], rewrite_suggestion? }
```

**ATSDeepCompatibility structure:**
```
{ score, issues[], keyword_gaps[] }
```

**ATSJobMatch structure:**
```
{ score, matched_requirements[], missing_requirements[], recommendation }
```

### 2.5 System Events

| Event Type | Key Fields | Description |
|-----------|------------|-------------|
| `sys.heartbeat` | `server_time` (float) | Server-side heartbeat every 30 seconds |
| `sys.error` | `message` (str) | System-level error notification |

### 2.6 Document Conversion Events

| Event Type | Key Fields | Description |
|-----------|------------|-------------|
| `document.convert_complete` | `source_format`, `latex_content`, `tokens_used`, `conversion_time` | Document-to-LaTeX conversion complete |

---

## 3. Database Models

Source: `backend/app/database/models.py`

All models use PostgreSQL via SQLAlchemy async with `asyncpg` driver. UUIDs stored as `VARCHAR`.

### 3.1 Core User Models

**users** table:
- `id` (UUID PK)
- `email` (VARCHAR 255, unique, indexed)
- `name` (VARCHAR 255)
- `avatar_url` (VARCHAR 500)
- `subscription_plan` (VARCHAR 50, default `"free"`)
- `subscription_status` (VARCHAR 50)
- `subscription_id` (VARCHAR 255)
- `email_verified` (BOOLEAN)
- `trial_used` (BOOLEAN)
- `email_notifications` (JSONB)
- `github_access_token` (TEXT)
- `github_username` (VARCHAR 255)
- `dropbox_access_token`, `dropbox_refresh_token`, `dropbox_account_id`
- `user_metadata` (JSONB) — Zotero/Mendeley tokens
- `public_username` (TEXT, unique) — portfolio
- `portfolio_enabled` (BOOLEAN)
- `portfolio_custom_domain` (TEXT, unique)
- `portfolio_theme`, `portfolio_tagline`
- `default_tenant_id` (FK → tenants)
- `created_at`, `updated_at`

**Better Auth tables** (managed by Next.js auth library):
- `session`: `id`, `user_id`, `token`, `expires_at`, `created_at`, `updated_at`
- `account`: OAuth provider accounts
- `verification`: email verification tokens

**device_trials** table:
- `device_fingerprint` (VARCHAR 255, unique)
- `ip_address` (INET)
- `usage_count` (INTEGER)
- `last_used` (TIMESTAMPTZ)
- `blocked` (BOOLEAN)

**deep_analysis_trials** table:
- `device_fingerprint` (VARCHAR 255, unique)
- `usage_count` (INTEGER)
- `last_used` (TIMESTAMPTZ)

### 3.2 Resume Models

**resumes** table:
- `id` (UUID PK)
- `user_id` (FK → users, CASCADE)
- `title` (VARCHAR 255)
- `latex_content` (TEXT)
- `structured_content` (JSONB) — builder structured data
- `structured_version` (INTEGER)
- `is_template` (BOOLEAN)
- `tags` (ARRAY[VARCHAR])
- `content_embedding` (ARRAY[FLOAT]) — 1536-dim OpenAI embedding
- `resume_settings` / `metadata` column (JSONB) — compiler prefs, share settings
- `selected_template_id` (FK → resume_templates)
- `content_source`: `"manual_latex"` | `"builder"`
- `builder_status`: `"active"` | `"detached"`
- `share_token` (TEXT, unique)
- `share_token_created_at` (TIMESTAMPTZ)
- `parent_resume_id` (FK → resumes, self-referential, SET NULL)
- `archived_at` (TIMESTAMPTZ)
- `github_sync_enabled` (BOOLEAN), `github_repo_name`, `github_last_sync_at`
- `dropbox_sync_enabled` (BOOLEAN), `dropbox_folder_path`, `dropbox_last_sync_at`
- `document_type`: `"resume"` | `"presentation"` | `"academic_cv"`
- `created_at`, `updated_at`
- Index: `idx_resumes_user_updated` on `(user_id, updated_at)`

**compilations** table:
- `id` (UUID PK)
- `user_id` (FK → users, SET NULL)
- `resume_id` (FK → resumes, SET NULL)
- `device_fingerprint` (VARCHAR 255)
- `job_id` (VARCHAR 255, unique)
- `status` (VARCHAR 50): `"processing"` | `"completed"` | `"failed"`
- `pdf_path` (VARCHAR 500) — MinIO object key
- `compilation_time` (FLOAT, seconds)
- `pdf_size` (INTEGER, bytes)
- `error_message` (TEXT)
- `created_at`
- Index: `idx_compilations_resume_status` on `(resume_id, status)`

**optimizations** table:
- `id` (UUID PK)
- `user_id` (FK → users, SET NULL)
- `resume_id` (FK → resumes, CASCADE)
- `device_fingerprint`, `job_description`, `original_latex`, `optimized_latex`
- `provider`, `model`
- `tokens_used` (INTEGER), `optimization_time` (FLOAT)
- `ats_score` (FLOAT)
- `changes_made` (JSON)
- `job_desc_embedding` (ARRAY[FLOAT]) — JD embedding for semantic search
- `checkpoint_label` (TEXT)
- `is_checkpoint` (BOOLEAN), `is_auto_save` (BOOLEAN)
- `created_at`

**resume_templates** table:
- `id`, `name`, `description`, `category`, `tags` (ARRAY[VARCHAR])
- `thumbnail_url`, `latex_content`
- `is_active`, `sort_order`
- `document_type`: `"resume"` | `"presentation"` | `"academic_cv"`

**resume_job_matches** table (semantic job matching cache):
- `resume_id`, `jd_hash` (SHA256 of JD), `similarity_score` (FLOAT)
- `matched_keywords`, `missing_keywords` (ARRAY[VARCHAR])
- `semantic_gaps` (JSONB)

**resume_collaborators** table:
- `resume_id` (FK), `user_id` (FK), `role`: `"editor"` | `"commenter"` | `"viewer"`
- `invited_by`, `joined_at`, `created_at`
- Unique: `(resume_id, user_id)`

**resume_views** table (share link analytics):
- `resume_id`, `share_token`, `country_code`, `user_agent`, `referrer`, `session_id`
- `viewed_at`

### 3.3 Subscription and Billing Models

**subscriptions** table:
- `user_id`, `razorpay_subscription_id` (unique), `plan_id`, `status`
- `current_period_start`, `current_period_end`, `cancelled_at`

**payments** table:
- `user_id`, `subscription_id`, `razorpay_payment_id` (unique, nullable)
- `amount` (INTEGER, paise), `currency` (VARCHAR 3, default "INR")
- `status`, `payment_method`

**coupon_codes** table:
- `code` (TEXT, unique), `discount_percent` (INTEGER)
- `applicable_plans` (ARRAY[VARCHAR]), `max_uses`, `used_count`, `expires_at`

**coupon_redemptions** table:
- `coupon_id` (FK), `user_id` (FK), `redeemed_at`

### 3.4 Team and Tenant Models

**team_seats** table:
- `owner_user_id`, `member_email`, `member_user_id` (nullable FK)
- `status`: `"invited"` | `"active"` | `"revoked"`
- `invited_at`, `joined_at`
- Unique: `(owner_user_id, member_email)`

**tenants** table (Feature 85):
- `id`, `slug` (3-40 chars, unique), `name`
- `logo_url`, `primary_color` (hex), `custom_domain`
- `plan_id`, `max_members`, `active` (BOOLEAN)
- `owner_id` (FK → users)

**tenant_members** table:
- `tenant_id`, `user_id`, `role`: `"admin"` | `"member"`

### 3.5 Analytics Model

**usage_analytics** table:
- `user_id` (FK, SET NULL), `device_fingerprint`
- `action` (VARCHAR 100), `resource_type` (VARCHAR 50)
- `event_metadata` (JSON), `ip_address` (INET), `user_agent` (TEXT)
- `created_at` (indexed)

### 3.6 Feature Flag Model

**feature_flags** table:
- `key` (VARCHAR 100, PK), `enabled` (BOOLEAN), `label`, `description`, `updated_at`

### 3.7 Application Tracking Models

**job_applications** table:
- `user_id`, `company_name`, `role_title`
- `status`: `"applied"` | `"phone_screen"` | `"technical"` | `"onsite"` | `"offer"` | `"rejected"` | `"withdrawn"`
- `resume_id` (FK, SET NULL), `ats_score_at_submission`, `job_description_text`, `job_url`
- `company_logo_url`, `notes`, `applied_at`

**application_submissions** table (one-click apply):
- `user_id`, `resume_id`, `job_tracker_id`
- `platform`: `"greenhouse"` | `"lever"` | `"manual"`
- `platform_job_id`, `application_url`, `job_title`, `company_name`
- `status`: `"pending"` | `"submitted"` | `"failed"`
- `submitted_at`, `error_message`

### 3.8 Content Creation Models

**cover_letters** table:
- `user_id`, `resume_id` (FK CASCADE)
- `job_description`, `company_name`, `role_title`
- `tone`: `"formal"` | `"conversational"` | `"creative"`
- `length_preference`: `"1_paragraph"` | `"3_paragraphs"` | `"full_page"`
- `latex_content`, `pdf_path`, `generation_job_id`

**interview_prep** table:
- `user_id`, `resume_id` (FK CASCADE)
- `job_description`, `company_name`, `role_title`
- `questions` (JSONB array)
- `generation_job_id`

### 3.9 Developer API Model

**developer_api_keys** table:
- `user_id`, `key_hash` (TEXT, unique), `key_prefix` (VARCHAR 32)
- `name`, `last_used_at`, `request_count` (INTEGER)
- `is_active`, `scopes` (ARRAY[VARCHAR])

### 3.10 BYOK Model

**user_api_keys** table:
- `user_id`, `provider` (VARCHAR 50), `encrypted_key` (TEXT, Fernet-encrypted)
- `key_name` (VARCHAR 100), `is_active`, `last_validated`

---

## 4. Celery Workers and Task Signatures

All workers use the `celery_app` from `backend/app/core/celery_app.py`. Workers are sync (no
asyncio) and communicate with Redis via the sync `event_publisher` helpers.

### 4.1 LaTeX Worker

**File:** `backend/app/workers/latex_worker.py`

```python
@celery_app.task(
    name="app.workers.latex_worker.compile_latex_task",
    max_retries=2,
    default_retry_delay=30,
    time_limit=300,       # 5 min hard kill (pro/byok get 240s compile timeout)
    soft_time_limit=270,
)
def compile_latex_task(
    latex_content: str,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    metadata: Optional[Dict] = None,
    compiler: str = "pdflatex",   # "pdflatex" | "xelatex" | "lualatex"
    watermark: Optional[str] = None,
    compile_settings: Optional[Dict] = None,  # main_file, extra_packages, latexmk_flags
    resume_id: Optional[str] = None,
) -> Dict[str, Any]
```

**Publishes:** `job.started` → `log.line` (×N) → `job.progress` → `job.pdf_extracted`
(optional) → `job.completed` | `job.failed`

**Queue:** `latex`

**Submission helper:**
```python
def submit_latex_compilation(latex_content, job_id, user_id, user_plan, ...) -> None
```

### 4.2 LLM Worker

**File:** `backend/app/workers/llm_worker.py`

```python
@celery_app.task(
    name="app.workers.llm_worker.optimize_resume_task",
    max_retries=2,
    default_retry_delay=120,
    time_limit=180,
    soft_time_limit=150,
)
def optimize_resume_task(
    latex_content: str,
    job_description: Optional[str] = None,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    optimization_level: str = "balanced",
    user_api_key: Optional[str] = None,
    metadata: Optional[Dict] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]
```

**Publishes:** `job.started` → `job.progress` → `llm.token` (×N) → `llm.complete` →
`job.completed` | `job.failed`

**Queue:** `llm`

### 4.3 Orchestrator (Combined)

**File:** `backend/app/workers/orchestrator.py`

```python
@celery_app.task(
    name="app.workers.orchestrator.optimize_and_compile_task",
    max_retries=1,
    default_retry_delay=60,
    time_limit=600,
    soft_time_limit=570,
)
def optimize_and_compile_task(
    latex_content: str,
    job_description: Optional[str] = None,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    optimization_level: str = "balanced",
    user_api_key: Optional[str] = None,
    device_fingerprint: Optional[str] = None,
    target_sections: Optional[List[str]] = None,
    custom_instructions: Optional[str] = None,
    model: Optional[str] = None,
    compiler: str = "pdflatex",
    persona: Optional[str] = None,
    compile_settings: Optional[Dict] = None,
    resume_id: Optional[str] = None,
) -> Dict[str, Any]
```

**Stage progression:** LLM optimization (0–40%) → LaTeX compile (40–80%) → ATS score (80–100%)

**Publishes:** `job.started` → `llm.token` (×N) → `llm.complete` → `job.progress 40%` →
`log.line` (×N) → `job.progress 80%` → `job.completed` | `job.failed`

**Queue:** `combined`

**Submission helper:**
```python
def submit_optimize_and_compile(latex_content, job_description, job_id, ...) -> None
```

### 4.4 ATS Worker

**File:** `backend/app/workers/ats_worker.py`

```python
@celery_app.task(
    name="app.workers.ats_worker.score_resume_ats_task",
    max_retries=2,
    default_retry_delay=60,
    time_limit=60,
    soft_time_limit=50,
)
def score_resume_ats_task(
    latex_content: str,
    job_id: Optional[str] = None,
    job_description: Optional[str] = None,
    industry: Optional[str] = None,
    industry_profile_key: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]
```

**Additional ATS tasks:**
```python
def deep_analyze_ats_task(...)  # Deep LLM analysis, publishes ats.deep_complete
def submit_job_description_analysis(...)  # JD keyword extraction
def embed_resume_task(resume_id, latex_content, user_id)  # background embedding (priority 1)
```

**Queue:** `ats`

### 4.5 Cleanup Worker

**File:** `backend/app/workers/cleanup_worker.py`

```python
@celery_app.task(name="app.workers.cleanup_worker.cleanup_temp_files_task")
def cleanup_temp_files_task(
    max_age_hours: int = 24,
    target_directory: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]

@celery_app.task(name="app.workers.cleanup_worker.cleanup_expired_jobs_task")
def cleanup_expired_jobs_task(max_age_hours: int = 24) -> Dict[str, Any]
```

**Queue:** `cleanup`

### 4.6 Email Worker

**File:** `backend/app/workers/email_worker.py`

```python
@celery_app.task(name="app.workers.email_worker.send_job_completion_email_task")
def send_job_completion_email_task(user_id, job_id, job_type, success, result) -> Dict

@celery_app.task(name="app.workers.email_worker.send_weekly_digest_task")
def send_weekly_digest_task(user_id) -> Dict
```

**Queue:** `email`

### 4.7 Cover Letter Worker

**File:** `backend/app/workers/cover_letter_worker.py`

```python
@celery_app.task(name="app.workers.cover_letter_worker.generate_cover_letter_task")
def generate_cover_letter_task(
    resume_id, user_id, job_description, company_name, role_title, tone, length_preference
) -> Dict
```

**Queue:** `llm`

### 4.8 Converter Worker

**File:** `backend/app/workers/converter_worker.py`

```python
@celery_app.task(name="app.workers.converter_worker.convert_document_task")
def convert_document_task(file_bytes, filename, mime_type, job_id, user_id) -> Dict
```

Publishes `document.convert_complete` event.

**Queue:** `llm`

### 4.9 Interview Prep Worker

**File:** `backend/app/workers/interview_prep_worker.py`

```python
@celery_app.task(name="app.workers.interview_prep_worker.generate_interview_questions_task")
def generate_interview_questions_task(
    resume_id, user_id, job_description, company_name, role_title, interview_prep_id
) -> Dict
```

**Queue:** `llm`

### 4.10 Auto-Save Worker

**File:** `backend/app/workers/auto_save_worker.py`

```python
@celery_app.task(name="app.workers.auto_save_worker.auto_save_checkpoint_task")
def auto_save_checkpoint_task(resume_id, user_id, latex_content, trigger) -> Dict
```

**Queue:** `cleanup` (low priority)

---

## 5. Redis Key Namespaces

All keys use the `latexy:` prefix. TTL is 86400 seconds (24 hours) unless noted.

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `latexy:job:{job_id}:state` | String (JSON) | 86400s | `{status, stage, percent, last_updated}` snapshot |
| `latexy:job:{job_id}:result` | String (JSON) | 86400s | Final job result payload |
| `latexy:job:{job_id}:meta` | String (JSON) | 86400s | `{job_id, user_id, job_type, submitted_at}` |
| `latexy:job:{job_id}:cancel` | String `"1"` | 3600s | Cancel flag; workers poll `is_cancelled()` |
| `latexy:job:{job_id}:seq` | String (integer) | 86400s | Monotonic event sequence counter |
| `latexy:stream:{job_id}` | Redis Stream | 86400s | Ordered event log for WS replay on reconnect |
| `latexy:events:{job_id}` | Pub/Sub channel | ephemeral | Live event delivery to WebSocket fanout |
| `latexy:user:{user_id}:jobs` | Sorted Set | 86400s | Score = timestamp; members = job_ids for listing |
| `latexy:batch:{batch_id}` | String (JSON) | 86400s | Batch tailor metadata: jobs[], user_id |
| `latexy:cache:ats:{hash}` | String (JSON) | 3600s | ATS score cache keyed by LaTeX+JD hash |
| `latexy:cache:analytics:{user_id}` | String (JSON) | 300s | Analytics cache |
| `rateview:{share_token}:{session_id}` | String `"1"` | 300s | Resume view deduplication (5-min debounce) |

**Redis Stream format** (`latexy:stream:{job_id}`):
Each entry has fields: `payload` (JSON event), `type` (event type string), `sequence` (integer),
`event_id` (UUID).

**Replay:** WebSocket clients send `last_event_id` in the subscribe message; the server uses
`XREAD COUNT 1000 STREAMS stream_key last_event_id` to replay missed events.

**Celery broker:** Redis DB 0 (`REDIS_URL`)  
**Cache / WS state:** Redis DB 1 (`REDIS_CACHE_URL`)

---

## 6. Frontend Pages and Data Displayed

| Page | Route | Key Data Sources | Description |
|------|-------|-----------------|-------------|
| Landing | `/` | None | Marketing: 3D hero, feature cards |
| Login | `/login` | Better Auth | Email/password or OAuth login |
| Sign Up | `/signup` | Better Auth | Account creation |
| Dashboard | `/dashboard` | `GET /analytics/user`, `GET /analytics/user/timeseries` | KPI cards, activity chart, recent compilations |
| Resume Studio (Try) | `/try` | `POST /jobs/submit`, WS `/ws/jobs` | Monaco editor + streaming log viewer + PDF iframe |
| Workspace (list) | `/workspace` | `GET /resumes/`, `GET /resumes/stats` | Resume grid/table with search, create/edit/optimize actions |
| New Resume | `/workspace/new` | `POST /resumes/` | Create form + template picker |
| Edit Resume | `/workspace/[resumeId]/edit` | `GET /resumes/{id}`, `POST /jobs/submit` | Monaco editor, compile, job stream, PDF preview |
| Optimize Resume | `/workspace/[resumeId]/optimize` | `POST /jobs/submit`, WS | Job submit form + LLM token stream + diff view |
| Billing | `/billing` | `GET /subscription/plans`, `GET /subscription/current` | Plan cards, current subscription, upgrade/cancel |
| BYOK Settings | `/byok` | `GET /byok/keys`, `GET /byok/providers` | API key management table |
| Settings | `/settings` | `GET /settings/notifications` | Notification preferences |
| Platform / Marketing | `/platform`, `/resources`, `/faq`, `/updates` | None | Static content |
| Public Portfolio | `/portfolio/u/{username}` | `GET /portfolio/u/{username}` | Public profile with resumes |
| Share | `/r/{share_token}` | `GET /share/{share_token}` | Public PDF view iframe |

**Key frontend hooks:**
- `useJobStream`: useReducer accumulating all WS events, keyed by `job_id`
- `useJobStatus`: wrapper around `useJobStream` with `onComplete`/`onFail` callbacks
- `useJobManagement`: job submission, listing, health polling
- `useATSScoring`: ATS analysis and industry keywords
- `useTrialStatus`: anonymous trial limit tracking with localStorage fallback
- `WSClient`: singleton WebSocket with 100ms→30s exponential backoff reconnect

---

## 7. Identified Gaps and TUI Constraints

### 7.1 PDF Preview (Critical Gap)

The Monaco editor + PDF iframe are central to the Latexy UX. A terminal cannot render PDF pages
inline. Workarounds:

- **Option A (recommended):** Download the PDF after compilation and open it in the system default
  PDF viewer via `subprocess.run(["open", pdf_path])` (macOS) or `xdg-open` (Linux).
- **Option B:** Print a compilation summary (page count, file size, time) and provide a CLI
  command to open the file.
- **Option C (partial):** Render first page as ASCII art using `pdftotext` output display.

The TUI must implement `GET /download/{job_id}` to retrieve the PDF, save it locally, and
trigger the OS viewer.

### 7.2 Monaco Editor (Critical Gap)

The LaTeX editor in the web app is Monaco (VS Code's editor) with syntax highlighting, bracket
matching, and auto-complete. A TUI replacement options:

- **Embedded micro-editor:** Textual has no built-in code editor widget. Use `$EDITOR` subprocess
  (vim/nano/VS Code) for editing, then reload content on return.
- **Built-in text area:** Textual's `TextArea` widget provides basic editing — suitable for viewing
  and small edits but lacks LaTeX syntax highlighting.
- **External editor integration:** Preferred for power users. The TUI opens the file in `$EDITOR`,
  watches for save, then auto-compiles.

### 7.3 LLM Token Streaming (Partially Feasible)

`llm.token` events stream individual LaTeX tokens over WebSocket. In a TUI, these can be
accumulated in a `Static` or `TextArea` widget that updates per token — this is feasible. The
"Monaco streaming" of tokens into the editor at specific cursor positions is not needed since there
is no Monaco.

### 7.4 Real-time Log Streaming (Fully Feasible)

`log.line` events are simple strings with an `is_error` flag. A Textual `RichLog` widget can
display them in real time with colour coding (red for errors). This is a natural fit for a TUI.

### 7.5 WebSocket Connection Management (Requires Implementation)

The frontend uses a singleton `WSClient` with exponential backoff reconnect (100ms→30s). The TUI
needs an equivalent Python implementation using the `websockets` library running in a background
thread or async task, publishing events to the Textual event system via `call_from_thread`.

Authentication: The TUI must obtain a `session_token` from Better Auth and pass it as an HTTP
header or query parameter on the WebSocket upgrade request.

### 7.6 Authentication (TUI-specific Challenge)

Better Auth is Next.js-native (server-side session management). The TUI must:

1. Call the Better Auth `/api/auth/sign-in/email` endpoint with email + password via `httpx`.
2. Store the `session.token` from the response cookie or JSON body.
3. Pass `Authorization: Bearer <token>` or `Cookie: session=<token>` on all subsequent API calls.
4. Handle session refresh (Better Auth tokens expire; TUI should detect 401 and re-authenticate).
5. Store credentials securely in `~/.config/latexy/config.toml` with appropriate file permissions.

### 7.7 File Upload (Feasible with Path Input)

Endpoints like `/format/convert`, `/resumes/builder/seed-upload`, and `/compile` accept file
uploads. A TUI can collect a local file path, read the bytes, and POST as `multipart/form-data`
using `httpx`.

### 7.8 Webhook (Not Applicable)

`POST /billing/webhook` is a Razorpay server-to-server webhook. The TUI does not need to handle
this — billing actions are triggered via `POST /subscription/create` and `POST /subscription/cancel`.

### 7.9 GitHub / Dropbox / Zotero OAuth Flows (Browser-Required)

OAuth flows for GitHub, Dropbox, Zotero, and Mendeley require a browser redirect. The TUI can:
- Open the OAuth URL in the system browser via `webbrowser.open()`.
- Provide a local callback server (e.g., `localhost:9999/callback`) to capture the redirect.
- Or skip these integrations in Phase 1/2 and note them as advanced features.

### 7.10 Subscription Billing UI (Partially Feasible)

The billing page renders Razorpay payment flows in an iframe. The TUI can:
- Display plan details and the Razorpay `short_url` from `POST /subscription/create`.
- Prompt the user to open the `short_url` in a browser to complete payment.
- Poll `GET /subscription/current` to detect successful payment.

### 7.11 Template Browser (ASCII Thumbnails)

Template thumbnails are PNG images served from `/templates/{id}/thumbnail`. A TUI cannot render
them natively. Options:
- List templates by name and category in a table.
- Use `sixel` terminal graphics if the terminal supports it (iTerm2, foot, etc.).
- Show template LaTeX source in the text area for preview.

### 7.12 Analytics Charts (Text-Based)

The dashboard shows bar charts and line charts (React recharts). A TUI can use:
- `rich.table.Table` for tabular stats.
- ASCII bar charts using the `plotext` library or manual unicode block characters.
- Textual's future chart support.

### 7.13 Collaboration Features (Partial)

Real-time cursor presence and collaborative editing (Feature 40) are web-only. However:
- Listing collaborators, inviting by email, and changing roles are all REST calls and are feasible.
- Live presence indicators require WebSocket — the TUI can poll `/resumes/{id}/collaborators`.

---

## 8. Feasibility Summary

| Feature Area | TUI Feasibility | Implementation Approach |
|-------------|----------------|------------------------|
| Authentication (login/logout) | Full | `httpx` POST to Better Auth; store session token |
| Resume CRUD (list/create/update/delete) | Full | REST via `httpx` |
| LaTeX Editing | Partial | External `$EDITOR` subprocess |
| LaTeX Compilation (submit + stream logs) | Full | Job submit + WS `log.line` events in `RichLog` |
| LLM Optimization (submit + token stream) | Full | Job submit + WS `llm.token` in `TextArea` |
| Combined optimize+compile | Full | As above |
| ATS Scoring | Full | REST + WS `ats.deep_complete` event |
| PDF Download and Open | Full | Download via REST, open with OS viewer |
| Job Monitoring (state, cancel) | Full | REST polling + WS subscription |
| Batch Tailor | Full | REST only |
| BYOK Key Management | Full | REST via `httpx` |
| Analytics Dashboard | Full | REST + `rich.table` + ASCII charts |
| Subscription/Billing | Partial | REST + browser for payment URL |
| Resume Search | Full | REST query parameter |
| Checkpoints / Version History | Full | REST |
| Share Links | Full | REST (display URL in TUI) |
| Template Browser | Partial | Text list; no visual thumbnails |
| Cover Letter Generation | Full | REST + WS |
| Interview Prep Generation | Full | REST + WS |
| Job Application Tracker | Full | REST CRUD |
| Job Scraper | Full | REST |
| GitHub / Dropbox / OAuth | Partial | Browser redirect for OAuth; sync via REST |
| Collaboration (invite/roles) | Partial | REST only; no live presence |
| Career Path / Snippets / Macros | Full | REST |
| Admin (feature flags) | Full | REST (admin role required) |
| CI/CD Mode (non-interactive) | Full | All endpoints support JSON I/O |
| PDF Preview Inline | Not feasible | OS viewer external launch |
| Monaco Editor | Not feasible | External `$EDITOR` subprocess |
| Billing Payment UI | Not feasible | Browser redirect |
| Template Thumbnails | Not feasible | Text-only listing |

**Overall assessment:** Approximately 80% of Latexy's features can be fully exposed in a TUI.
The 20% that cannot be fully reproduced (PDF inline viewer, Monaco editor, Razorpay payment iframe)
can be gracefully handled with OS-level redirects and clear messaging. The event-driven WebSocket
architecture is well-suited for a terminal with streaming log and token display panels.
