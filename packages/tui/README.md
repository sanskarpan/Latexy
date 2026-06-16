# Latexy TUI

> LaTeX resume compilation, ATS scoring, and AI optimization — right in your terminal.

## Install

```bash
npm install -g latexy
# or
pnpm add -g latexy
```

## Quick start

```bash
latexy                                         # interactive mode
latexy compile my-resume.tex                   # compile a local .tex file
latexy compile --resume-id <uuid>              # compile by resume ID
latexy compile --resume-id <uuid> --output out.pdf
```

## Authentication

In interactive mode, run `/login` to open the sign-in overlay.

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
| `/model` | Open model picker for agent mode | local |
| `/clear` | Clear transcript | local |
| `/logout` | Clear session and exit | local |

## CI / Headless mode

When stdout is not a TTY (CI pipelines, scripts), Latexy runs in headless mode and outputs JSON:

```bash
latexy compile --resume-id <uuid> --json
# → { "success": true, "pages": 2, "size_bytes": 45123, "ats_score": 84 }
```

Exit codes:

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Compilation failed |
| `2` | Not authenticated |
| `3` | Unknown subcommand / invalid args |

## Configuration

Config file: `~/.config/latexy/config.toml`

```toml
backendUrl = "https://api.latexy.com"
defaultResumeId = "uuid-of-your-default-resume"
```

Environment variable overrides:

| Variable | Description |
|----------|-------------|
| `LATEXY_API_URL` | Backend URL |
| `LATEXY_SESSION_TOKEN` | Auth token (skips interactive login) |

## Requirements

- Node.js >= 22
- A Latexy account at [latexy.com](https://latexy.com)
