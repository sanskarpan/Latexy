# Latexy MCP server

The `@sanskarpan/latexy` package includes a local Model Context Protocol server
for reading and editing Latexy documents from MCP-capable clients. It uses the
same authenticated API client and configuration as the Latexy TUI. The server
communicates over stdio and writes no protocol data to logs or files.

## Install and authenticate

```bash
npm install -g @sanskarpan/latexy
latexy
```

Signing in once through `latexy` stores the session in the existing
permission-restricted Latexy configuration file. For an isolated or automated
client, set `LATEXY_SESSION_TOKEN` in that client's MCP environment instead.
Self-hosted deployments can also set `LATEXY_API_URL` and `LATEXY_APP_URL`.

Treat the session token like a password. Do not put it in a repository or paste
it into prompts. The MCP server sends it only as an authorization header to the
configured Latexy API.

## Configure a client

The server command is `latexy-mcp`.

### Codex

Codex supports local stdio servers and can register the command directly:

```bash
codex mcp add latexy -- latexy-mcp
```

When using environment-based authentication, forward variables from the local
environment in `~/.codex/config.toml` (or a trusted project configuration):

```toml
[mcp_servers.latexy]
command = "latexy-mcp"
env_vars = ["LATEXY_SESSION_TOKEN", "LATEXY_API_URL", "LATEXY_APP_URL"]
```

This follows the current [official Codex MCP configuration](https://developers.openai.com/codex/mcp/),
which documents `command` for stdio processes and `env_vars` for forwarding
local environment variables.

### JSON-based clients

Claude Desktop, Cursor, and other clients that accept the common stdio server
shape can use:

```json
{
  "mcpServers": {
    "latexy": {
      "command": "latexy-mcp"
    }
  }
}
```

If the client does not inherit the existing Latexy CLI configuration, use its
documented environment-variable mechanism to provide `LATEXY_SESSION_TOKEN`.
The exact settings-file location is client- and platform-specific.

## Tools

| Tool | Effect |
|---|---|
| `list_resumes` | Lists every active or archived document, with pagination handled server-side |
| `read_resume` | Reads complete LaTeX source and document metadata |
| `create_resume` | Creates a document from complete LaTeX source |
| `update_resume` | Updates explicitly supplied title, source, type, or tags |
| `archive_resume` | Reversibly archives a document; permanent deletion is intentionally not exposed |
| `compile_resume` | Queues compilation and returns a job ID |
| `score_resume` | Queues ATS scoring and returns a job ID |
| `get_job_status` | Reads job progress and includes results after terminal completion |

Mutating and read-only behavior is declared through MCP tool annotations. Input
schemas enforce UUIDs, document types, string sizes, and required fields before
an API request is made. API errors are returned as tool errors rather than
terminating the MCP process.

## Resources

Active documents are discoverable as `resume:///<resume-id>` resources with
the `application/x-latex` media type. Reading a resource returns only its LaTeX
source. Tool responses use an explicit allowlist and do not forward owner IDs,
share tokens, share URLs, or unrelated backend internals to the MCP client.

## Development verification

```bash
pnpm --filter @sanskarpan/latexy run typecheck
pnpm --filter @sanskarpan/latexy run test:unit
pnpm --filter @sanskarpan/latexy run build
```

The test suite connects a real MCP client and server through an in-memory
transport to verify discovery, schema validation, structured results, resource
reads, update guards, pagination, route methods, asynchronous jobs, and response
data minimization. The release build is also smoke-tested over a spawned stdio
process.
