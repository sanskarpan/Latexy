# Latexy TUI

> LaTeX resume compilation, ATS scoring, and AI optimization — right in your terminal.

## Install

```bash
npm install -g @sanskarpan/latexy
# or
pnpm add -g @sanskarpan/latexy
```

## Quick start

```bash
latexy                                         # interactive mode
latexy compile my-resume.tex                   # compile a local .tex file
latexy compile --resume-id <uuid>              # compile by resume ID
latexy compile --resume-id <uuid> --output out.pdf
latexy optimize <uuid> --jd job-description.txt
latexy ats score <uuid> --jd job-description.txt
latexy status <job-id> --wait
latexy list
```

## Authentication

Interactive mode opens the sign-in overlay automatically when no valid session
is available.

For CI / headless use, set the `LATEXY_SESSION_TOKEN` env var:

```bash
LATEXY_SESSION_TOKEN=<token> latexy compile --resume-id <uuid> --json
```

## Available Commands

| Command | Description | Type |
|---------|-------------|------|
| `/compile` | Compile selected resume to PDF | api |
| `/optimize` | AI-optimize resume for a job | api |
| `/combined` | Optimize + compile in one job | api |
| `/ats` | Run ATS deep analysis | api |
| `/quick-ats` | Fast rule-based ATS (no LLM) | api |
| `/list` | Open resume picker | local |
| `/new` | Create new resume | api |
| `/edit` | Open resume in $EDITOR | api |
| `/fork` | Fork resume into a variant | api |
| `/pdf` | Download and open last PDF | api |
| `/log` | View full pdflatex log | api |
| `/cancel` | Cancel running job | api |
| `/jobs` | Open job monitor overlay | local |
| `/byok` | Manage BYOK API keys | local |
| `/analytics` | View personal analytics | api |
| `/billing` | View subscription and billing | local |
| `/tracker` | Open job application tracker | local |
| `/cover` | Generate cover letter | api |
| `/interview` | Generate interview questions | api |
| `/health` | Show backend health status | api |
| `/history` | Show optimization history | api |
| `/checkpoint` | Create named checkpoint | api |
| `/restore` | Restore to a checkpoint | local |
| `/diff` | Show diff with parent variant | api |
| `/export` | Export resume to another format | api |
| `/share` | Generate and copy share link | api |
| `/snippets` | Browse snippet marketplace | local |
| `/settings` | Open notification settings | local |
| `/help` | Show help | local |
| `/model` | List supported providers and models | api |
| `/clear` | Clear transcript | local |
| `/logout` | Clear session and return to sign-in | local |

## CI / Headless mode

Free-text agent mode and an interactive provider picker are planned work. The
current `/model` command is informational; all working interactive actions are
listed by `/help`.

When stdout is not a TTY (CI pipelines, scripts), Latexy runs in headless mode and outputs JSON:

```bash
latexy compile --resume-id <uuid> --json
# → { "success": true, "job_id": "…", "pages": 2, "ats_score": null, "compilation_time_ms": 1450, "compiler": "pdflatex" }

latexy optimize <uuid> --jd job-description.txt --level balanced --json
# → { "success": true, "job_id": "…", "optimized_latex": "…", "changes_made": [...] }

latexy ats score <uuid> --jd job-description.txt --industry software_engineering --json
# → { "success": true, "job_id": "…", "ats_score": 87.5, "category_scores": {...} }

latexy status <job-id> --json                 # current state, without blocking
latexy status <job-id> --wait --json          # wait and return the final result
latexy list --page 1 --limit 100 --json
```

`--jd` accepts a local file, an HTTP(S) job-posting URL, or literal job-description
text. Progress and compiler logs are written to stderr; stdout contains exactly
one JSON document, so it can be piped directly to `jq`.

When `defaultResumeId` is set in the config, headless `compile` (without a local
file or `--resume-id`), `optimize`, and `ats score` use that resume. An explicit
resume ID or local `.tex` path always takes precedence.

Exit codes:

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Command or asynchronous job failed |
| `2` | Not authenticated |
| `3` | Unknown subcommand / invalid args |
| `4` | Backend unreachable |

## Configuration

Config file: `~/.config/latexy/config.toml`

```toml
backendUrl = "https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run"
appUrl = "https://latexy.xyz"
defaultResumeId = "uuid-of-your-default-resume"
```

Fresh installs use those live SaaS endpoints automatically. Set both URL values
when connecting to a local or self-hosted deployment; `appUrl` is the Next.js
origin that hosts authentication, while `backendUrl` is the FastAPI origin.

Environment variable overrides:

| Variable | Description |
|----------|-------------|
| `LATEXY_API_URL` | FastAPI backend URL |
| `LATEXY_APP_URL` | Next.js app and authentication URL |
| `LATEXY_SESSION_TOKEN` | Auth token (skips interactive login) |

## Requirements

- Node.js >= 22
- A Latexy account at [latexy.xyz](https://latexy.xyz)

## MCP server

The same package installs `latexy-mcp`, a local stdio MCP server with typed
tools for listing, reading, creating, updating, archiving, compiling, and ATS
scoring Latexy documents, plus `resume:///…` LaTeX resources. It reuses the TUI
login or `LATEXY_SESSION_TOKEN` and supports the same self-hosting URL overrides.

```bash
codex mcp add latexy -- latexy-mcp
```

See the repository's [MCP guide](https://github.com/sanskarpan/Latexy/blob/main/docs/mcp.md) for client setup, tool
contracts, resources, and security behavior.
