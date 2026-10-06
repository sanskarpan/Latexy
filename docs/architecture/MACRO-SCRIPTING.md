# B53c macro scripting boundary

Latexy scripts are a deliberately small, line-oriented document transformation
language. They are not JavaScript, Python, LaTeX, or a general-purpose plugin
runtime. The backend never evaluates source as code and never starts a process.

Supported commands (one per line, with quoted arguments):

```text
prepend "text"
append "text"
replace "old" with "new" [all|first]
delete-prefix <count>
delete-suffix <count>
```

`prepend` and `append` operate on the complete supplied document. Delete
commands remove characters from the corresponding edge. A replacement with no
mode replaces the first occurrence. Comments begin with `#` outside quoted
text. There is no cursor, loop, variable, function, import, network, file,
environment, clock, random, or shell capability.

The parser and interpreter enforce 128 non-empty operations/lines, a 16 KiB
source limit, 500 KiB input/output limits, and 100 KiB per literal. These finite
bounds make runtime linear in the source and document size; there is no need to
run untrusted code in FastAPI, Celery, Modal, Node, or the browser.

Scripts are stored with a SHA-256 digest and monotonically increasing version.
Script updates and executions require the caller's expected version, returning
409 on stale source. Execution is a pure operation and does not persist the
document, so retrying it is safe. The authenticated `/macros/{id}/execute`
route is entitlement-gated and owner-private; unknown IDs are returned as 404
for all users. The TUI previews by default and only saves with explicit
`--apply`.

The older recorded-action macro format remains supported, but the API bounds it
to 128 typed actions and 64 KiB of JSON. Recorded Monaco command names are
limited to identifier-like values and never reach a server-side evaluator.

## Pre-cap legacy recordings

Revision 0053 quarantines recorded-action JSON created before the 64 KiB database check. The exact JSONB value is retained in nullable `user_macros.legacy_actions` for rollback and administrator recovery; active `actions` is replaced with `[]` and the check is validated. Normal list/detail responses expose only `legacy_actions_available: true` and never serialize the archived payload.

Quarantined recordings are deliberately non-executable. The web panel and TUI label them and instruct the user to delete the old macro and record a replacement. Metadata-only edits and deletion remain available. There is no unbounded recovery/export endpoint: operators must use database rollback or a controlled administrator recovery path, and must not copy the archived payload into ordinary client responses.
