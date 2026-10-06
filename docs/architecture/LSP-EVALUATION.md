# LaTeX language-server evaluation

Status: recommendation accepted for planning; production integration deferred.
Scope: B53b / GitHub #1394. Evaluated 2026-09-08 against Latexy's current
Next.js 15, Monaco 0.55, FastAPI, and Modal deployment architecture.

## Decision

Adopt **texlab** as the eventual language-server foundation, behind a separate
authenticated workspace service. Do not put a texlab child process in the
current Modal FastAPI web endpoint, and do not block the already-small B19.1
autocomplete correctness fixes on that service.

Tinymist is not an alternative for the current editor: it is a language service
for Typst, while Latexy edits and compiles LaTeX. It should be reconsidered only
if Latexy later adds Typst as a document language.

Until the workspace service exists, retain the in-browser Monaco provider for
commands, local labels, and BibTeX keys. Keep its parsing in pure, tested helpers
so it can be removed cleanly when the texlab client is enabled. B19.3 outline
and B19.11 hover keep their bounded, tested local extraction fallback until
texlab can supply semantic ranges. Rich presentation remains a client concern:
texlab does not render KaTeX, materialize user graphics that the current
single-source workspace does not store, or own Latexy's saved bibliography UI.

## Evidence and spike

The reproducible spike is `scripts/spikes/texlab_stdio_spike.py`. It speaks LSP
over stdio to an explicitly supplied binary, opens an in-memory `.tex` and
`.bib` pair, and fails unless texlab advertises completion, document-symbol,
and hover providers and returns a local label, a cross-file citation, and the
section outline.

The evaluated binary was the official macOS arm64 build of texlab 5.26.0. Run:

```sh
python3 scripts/spikes/texlab_stdio_spike.py --texlab /absolute/path/to/texlab
```

Observed result:

```json
{
  "texlab": "texlab 5.26.0",
  "providers": {
    "completion": true,
    "document_symbols": true,
    "hover": true
  },
  "reference_completion": true,
  "citation_completion": true,
  "document_symbols": ["Introduction"],
  "errors": []
}
```

Texlab's upstream project describes it as a LaTeX LSP server and distributes
precompiled binaries. The Monaco language-client project supports either a Web
Worker language server or an external process bridged over WebSocket. Texlab is
a native stdio process, not a browser/Web Worker bundle, so Latexy needs the
external-process topology.

Primary references:

- <https://github.com/latex-lsp/texlab>
- <https://github.com/TypeFox/monaco-languageclient>
- <https://github.com/Myriad-Dreamin/tinymist>

## Required production topology

1. The browser obtains a short-lived, single-use ticket scoped to one resume,
   following the existing jobs/collaboration WebSocket security pattern.
2. A dedicated workspace service authenticates and authorizes that resume,
   creates an isolated temporary directory, materializes only its permitted
   `.tex`/`.bib` assets, and starts one pinned texlab process without a shell.
3. A bounded WebSocket-to-stdio bridge validates JSON-RPC frame size, method,
   document URI, document count, and document bytes. It rejects filesystem URIs
   outside the allocated workspace.
4. The service enforces idle timeout, absolute lifetime, per-user/session
   concurrency, memory/CPU limits, and guaranteed process/workspace cleanup.
5. Monaco connects through a version-compatible `monaco-languageclient` and
   `vscode-ws-jsonrpc` pair behind a feature flag. Reconnect resynchronizes the
   complete authorized workspace.

## Why not the current API container

- Modal web containers can move or scale independently; a reconnect is not
  guaranteed to reach the process that owns an editor's workspace.
- The current resume model is principally one source buffer plus metadata. LSP
  needs an explicit policy for auxiliary files and canonical URIs.
- Long-lived native children add lifecycle, resource-exhaustion, and tenant
  isolation responsibilities to a request API that currently has none.
- Existing WebSockets carry application events or Y.js frames. Multiplexing raw
  LSP into either protocol would weaken their validation and failure isolation.
- No texlab binary or Monaco LSP client dependencies are currently shipped.

## Rollout gates

- Pin binary and npm versions and verify their release artifacts in builds.
- Contract-test initialize/open/change/close, completion, symbols, hover,
  diagnostics, reconnect, authorization failure, URI escape, size limits, and
  forced cleanup.
- Load-test concurrent sessions and measure memory, cold start, completion p95,
  reconnect success, and orphan-process count.
- Canary behind a server-controlled feature flag. Keep the local completion
  provider as fallback until the canary meets availability and latency targets.
- Remove each local semantic extractor only after texlab supplies B19.1, B19.3,
  and B19.11 ranges in production with equivalent browser coverage. Keep the
  client-side safe renderer and bibliography presentation above that transport.
