# Local remediation ledger — 2026-08-31

> **Historical payment snapshot:** Razorpay references below describe the earlier
> implementation. Current runtime billing uses Dodo hosted checkout and signed
> webhooks; see [Dodo operations](../BILLING_DODO.md) and the October 2026 migration audit.


This is the working ledger for the current uncommitted QA pass. It records
locally reproduced findings and verification evidence; GitHub issue #1621 and
the canonical `docs/HANDOFF.md` remain authoritative after publication.

## Completed locally

### Backend resource lifecycle

- Redis clients are closed across API, worker, fixture, feature-flag, and
  entitlement paths.
- event-bus and collaboration listeners have deterministic startup/teardown.
- WebSocket heartbeat, delayed cleanup, reference fetch, and compiler subprocess
  tasks are cancelled and awaited.
- Observed Redis factories now own and close the connection pools they create,
  matching redis-py's factory contract. Database shutdown clears its process
  singletons before disposal so repeated lifespan/test loops cannot reuse a
  closed-loop engine.
- The complete backend suite passes against real local PostgreSQL and Redis with
  `ResourceWarning`, `RuntimeWarning`, and unraisable warnings promoted to
  errors. Its only output is one upstream Starlette/httpx2 deprecation warning.
- Backend Ruff, compileall, workflow YAML parsing, and 68 static deployment and
  observability tests passed.

### TUI resume reachability

- Reproduced: `/list` and every resume-taking command fetched only page one.
  The client requested 200 rows while the API caps a page at 100, so older
  resumes were unreachable.
- Fixed: one shared paginator now loads all pages, preserves archive/document
  filters, and feeds both picker paths.
- Verification: two focused pagination regressions, TUI typecheck, and production
  build pass.

### Résumé-list pagination contract

- Reproduced: OpenAPI accepted `limit=200`, then the handler silently rewrote it
  to 100, making client page calculations disagree with the advertised contract.
- Fixed: validated limits are honored; a focused handler regression asserts the
  query and response both retain 200.

### Web résumé reachability

- Reproduced: the main workspace and several résumé selectors called the
  20-row default list method with no pagination, making résumé 21+ unreachable.
- Fixed: the frontend API client has one complete paginator and the workspace,
  archived library, tracker-link picker, team-workspace picker, and quick-tailor
  refresh and résumé-merge selector all use it.
- The merge selector also distinguishes a list outage from a truly empty account
  and provides retry instead of inviting unnecessary résumé creation.

### Cross-browser download lifetime

- Reproduced: multiple export/download paths revoked their Blob URL immediately
  after the synthetic anchor click, which can cancel the navigation in Firefox.
- Fixed: a shared helper attaches/clicks/removes the anchor and revokes after a
  bounded delay; workspace bulk/filtered exports, editor PDFs, optimized PDFs,
  cover letters, watermarks, references, templates, and the export dropdown use it.

### TUI logout truthfulness

- Reproduced: `/logout` cleared the config file but an active
  `LATEXY_SESSION_TOKEN` environment override remained effective while the TUI
  claimed success.
- Fixed: the override is removed from the running process and the user is told
  when the parent shell must also be updated for logout to persist after restart.
- Command help now accurately says logout returns to sign-in rather than exiting.
- Verification: 12 focused dispatch tests and TUI typecheck pass.

### TUI narrow status bar

- Reproduced from the TUI audit: account and connection fields collide around
  60 columns.
- Fixed: the bar follows terminal resize events, hides the email in compact mode,
  and reduces connection/health labels to glyphs on very narrow terminals.
- Verification: six status-bar tests at normal, 60-column, and 40-column widths,
  plus TUI typecheck and production build pass.

### TUI agent-mode guidance

- Reproduced: free text told users to run `/model` to select a provider, while
  `/model` is intentionally informational until the later agent-mode phase.
- Fixed: runtime guidance and the package README now state the current capability
  honestly and direct users to `/help` for executable commands.
- Verification: focused dispatch tests and TUI typecheck pass.

### Historical-document truthfulness

- `docs/todo.md` now warns that its unchecked observability program predates the
  shipped implementation and routes readers to current evidence.
- `packages/tui/issues.md` now labels its remaining/version statements as
  revision-specific evidence and links current implementation/delivery sources.

### Frontend static and unit baseline

- ESLint passes with zero warnings/errors.
- All 82 Vitest files pass (666 tests), including the offline, builder,
  session-refresh, workflow-load, developer, BYOK, settings, billing, template
  library, and history regressions added during this pass.
- A current full strict TypeScript pass succeeds across all frontend source.
  The recovered legacy device-tracking utility now narrows Chromium's optional
  `navigator.deviceMemory` capability instead of assuming it is in the standard
  DOM type, so it no longer has to be isolated from validation.
- Full lint also exposed one obsolete suppression naming an uninstalled
  TypeScript ESLint rule in an ATS E2E helper. The helper now uses its existing
  `object` response contract and the repository-wide lint pass is clean.

### Backend static and collection baseline

- Ruff passes across the complete backend application and all tests.
- Pytest successfully imports and collects 3,136 tests, and
  runs the complete backend suite against the
  dedicated local PostgreSQL/Redis test services. Lifecycle warnings are strict
  errors, so passing also proves sockets, pools, tasks, and subprocess transports
  are released at teardown.
- Repository diff whitespace validation is clean.

### Authenticated route session recovery

- Reproduced: many protected routes treated a first session lookup failure as
  either a confirmed logout, a public sign-in state, or an empty page. This was
  distinct from the already-fixed mid-session identity refresh issue.
- Fixed: dashboard, personal workspace, tracker, team workspace list/detail,
  recruiter dashboard, cover-letter library, merge, career, batch tailoring,
  optimization, cover-letter generation, new résumé, and the editor now expose
  an accessible retryable session error. The editor still restores an available
  offline draft before showing that error.
- Focused route regressions, repository-wide strict TypeScript, and targeted
  ESLint pass.

### Workspace load failure state

- Reproduced: a primary résumé/job request failure was swallowed in production
  and the workspace rendered the same empty state as a genuinely new account.
- Fixed: the page exposes an accessible error banner, preserves previously loaded
  session data when available, provides retry, and suppresses the misleading
  create-first-résumé state during an outage.

### Tracker load failure state

- Reproduced: a failed initial board/stats request emitted a transient toast and
  then rendered the normal zero-applications onboarding state.
- Fixed: the tracker keeps a retryable accessible error state, preserves stale
  session data when present, and no longer invites duplicate application creation
  during an outage.

### Run-history load failure state

- Reproduced: a failed jobs request logged to the console and rendered the
  ordinary no-runs message.
- Fixed: authenticated run history now distinguishes an outage, surfaces the
  request error accessibly, and provides retry.

### Cover-letter library load failure state

- Reproduced: initial, search, and pagination failures rendered as an empty
  library after a transient toast.
- Fixed: the library keeps an accessible retryable error, preserves prior
  results, and suppresses the false empty state during an outage.

### Team-workspace load failure state

- Reproduced: a failed workspace-list request rendered the same no-workspaces
  onboarding state as a new account.
- Fixed: the page exposes the request failure with retry and suppresses the
  misleading empty state.
- The detail route also no longer returns a blank page when its initial request
  group fails; it provides back navigation, the error, and retry.
- Both routes now use the shared confirmed-session guard and terminate their
  loading state when signed out, eliminating the permanent spinner before login
  redirection.

### Authenticated-route loading termination

- Reproduced: the editor, optimizer, résumé-merge, recruiter-dashboard, and new
  résumé routes initialized primary loading to true, skipped their fetch for a
  signed-out visitor, and never cleared loading while redirecting.
- Fixed: all use the shared confirmed-session guard, terminate route loading when
  no session is returned, and avoid rendering protected content during redirect.
- The career-analysis page now also terminates its past-analysis spinner without
  a session instead of displaying an indefinitely loading subsection.
- Verification: eight focused authenticated/loading regressions pass as part of
  the complete frontend suite.

### Recruiter-dashboard load failure state

- Reproduced: a failed initial workspace/resume request emitted only a toast and
  then returned a blank page.
- Fixed: the owner dashboard now renders the primary error, offers workspace back
  navigation and retry, and suppresses false empty content.

### Secondary résumé-data failure states

- Reproduced: the application modal silently converted a failed résumé request
  into a `None`-only selector, and career history silently converted a failed
  request into `No analyses yet`.
- Fixed: both surfaces distinguish loading, failure, and empty data and provide
  retry. The application form remains explicitly usable without a linked résumé.

### Compile-settings security parity

- Reproduced: the backend and worker intentionally prohibit `--shell-escape`, but
  the frontend still offered it in Compile Settings and advertised the `minted`
  package that requires it. Saving that choice failed validation; enabling it in
  a compiler would permit arbitrary command execution.
- Reproduced alongside it: the modal offered TeX Live 2022/2023/2024 pinning and
  reported a successful save, but the deployed worker never reads that value and
  always uses its image-managed runtime.
- Fixed: the frontend whitelist now matches the backend, the unsafe package is
  absent from the insertion catalog, the dead version selector is replaced by an
  accurate managed-runtime notice, and the settings UI explains both boundaries.
- Verification: focused source/data regressions prove the prohibited flag and
  package cannot be offered.

### Historical gap-report reconciliation

- Revalidated all six claims in `docs/GAPS_ISSUES.md` against current source.
  Resume/JD caching, both rate-limit middleware, unified BYOK encryption,
  onboarding, provider selection, and user/admin job queues are all wired now.
- The document remains historical evidence as labeled by `docs/README.md`; none
  of those six claims is being carried into the current remediation backlog.

### Streamed optimization completeness and cancellation

- Reproduced: when an LLM stream omitted its closing delimiter, the parser never
  flushed its delimiter-sized hold-back buffer and silently removed the tail of
  otherwise valid LaTeX.
- Fixed: EOF flushes residual LaTeX/changes content; the normal shared validation
  gate still rejects genuinely incomplete or unsafe output before compilation.
- Reproduced: cancellation observed during LLM token streaming raised a generic
  runtime error, so Celery retried the whole billed provider request and could
  later report an internal failure instead of the user's cancellation.
- Fixed: mid-stream cancellation has a dedicated terminal control path, records
  the Compilation as cancelled, emits the terminal event, and never calls retry.
- Verification: six focused orchestrator streaming/cancellation tests and Ruff
  pass.

### Account-menu route reachability

- Reproduced: the signed-in account menu labeled `/byok` as `Settings`, leaving
  the actual `/settings` integration/preferences page without that navigation
  path and making the label's destination misleading.
- Fixed: BYOK is labeled `AI Providers` and the real Settings page has its own
  menu item. A focused route-contract regression passes.

### Batch-tailor variant correctness

- Reproduced: batch submission created each variant as a byte-identical parent
  copy, but successful orchestration only queued a checkpoint and never updated
  the variant row. A completed batch therefore opened the untailored résumé.
- Fixed: batch jobs explicitly request owner-scoped result persistence; the
  orchestrator writes the optimized LaTeX before publishing completion.
- A persistence failure is terminal and stores/returns the optimized LaTeX with
  a specific non-retryable error, avoiding a second billed LLM request.
- The batch page now uses the shared auth guard and turns a failed first status
  poll into visible retryable recovery rather than an infinite spinner.
- Verification: eight focused orchestrator tests, two frontend route regressions,
  targeted ESLint, Ruff, and diff whitespace validation pass. The database-backed
  owner-scope regression is added for the full integration environment.

### Editor save, visual-mode, and offline recovery

- Reproduced: an empty title caused every debounced autosave to receive 422,
  swallow the failure, remain dirty, and schedule another failing request.
  Manual Save replaced the useful backend validation with a generic message.
- Fixed: title requirements are enforced before manual/offline/automatic writes,
  the input is bounded to the backend's 255-character contract, and save errors
  remain visible in the live save-status indicator.
- IndexedDB draft and offline compile-queue writes now have explicit failure
  handling rather than unhandled promise rejections.
- Reproduced: reloading a résumé whose persisted mode was `wysiwyg` restored the
  mode string but not the parsed document, leaving `Parsing…` forever.
- Fixed: the visual document and raw-block warning state are rebuilt after resume
  data loads.
- Reproduced: starting a new compile immediately revoked the last successful PDF,
  so a failed replacement left no preview or reliable download. The old artifact
  now remains until a new PDF has downloaded successfully.
- Reproduced: non-PDF editor exports used the saved résumé ID rather than the live
  buffer, dropping unsaved edits; the PDF entry did not invoke the existing
  download handler. Live content is now preferred and PDF export is wired to the
  last successful artifact.
- Reproduced: offline drafts were write-only. Refreshing while offline had no
  session response, skipped the résumé request, and rendered a blank page;
  reconnect could also flush/delete a pending draft before the editor restored
  it, allowing the older server copy to win visually.
- Fixed: the auth guard no longer treats an offline session lookup as a logout,
  the editor restores a device-local draft without a network session, prefers a
  pending draft over an older server body, and delays reconnect flushing until
  initial restoration finishes. Failed syncs retain an accurate pending count.
- Initial server/draft load failures now render accessible back/retry recovery
  instead of redirecting after a transient request failure.
- Nine focused editor/download regressions, targeted ESLint, and a scoped strict
  TypeScript pass succeed.

### Job-queue response contract

- Reproduced: the backend/job shim supplied `job_type` at the top level, while
  queue labels, search, and filters read `metadata.job_type`; every job therefore
  appeared as a LaTeX compile and type filtering was ineffective.
- Reproduced: the health footer rendered absent WebSocket and active-job counters
  as literal `undefined` because `/jobs/health` only returns status, Redis health,
  and a timestamp.
- Fixed: type consumers prefer the actual top-level field, health types mirror
  the API, and optional counters render only when supplied. Seventeen focused
  queue/gap regressions and ESLint pass.

### Guided-builder authentication and save reliability

- Reproduced: both guided-builder routes were listed as protected but had no
  client session guard. The new route fetched public templates while signed out,
  and the edit route requested protected data before redirect behavior existed.
- Fixed: both routes use the shared confirmed-session guard and delay their
  primary requests until authentication resolves.
- Reproduced: template/load failures became a toast plus an empty selector, or
  immediately redirected away from the editor, preventing recovery from a
  transient outage. Both routes now keep accessible error state with retry, and
  the genuinely empty template state is distinct.
- Reproduced: an autosave response unconditionally cleared `dirty`, so a user
  edit made while that request was in flight could be marked saved even though
  its content was not in the request. Revision tracking now clears dirty state
  only for the exact saved edit; later edits schedule their own save. Save errors
  remain visible with retry, title limits match the backend, and unload/advanced
  editor navigation warns while changes remain unsaved.
- Four focused regressions, targeted ESLint, and a scoped strict TypeScript pass
  succeed.

### Session-refresh authentication preservation

- Reproduced: protected-route guards correctly avoided redirecting on a
  transient Better Auth session error, but the root token synchronizer still
  converted that indeterminate response into `setAuthToken(null)` and disabled
  authenticated WebSockets. Subsequent API calls could therefore fail as 401
  even though the user's session cookie remained valid.
- Fixed: pending/error states preserve the last published API and WebSocket
  authentication. Only a successful, authoritative empty-session response now
  clears them.
- The shared route guard and global header also retain the last confirmed
  identity while a refresh is pending or failed, but explicitly clear their
  latches after a confirmed logout so a later error cannot resurrect stale user
  UI on a shared device.
- Three focused session regressions, targeted ESLint, and a scoped strict
  TypeScript pass succeed.

### Optimization and cover-letter load recovery

- Reproduced: both primary résumé workflows redirected to the workspace after
  any initial request failure, so a transient backend outage looked like forced
  navigation and offered no retry. Optimization and cover-letter loading now
  retain an accessible error with back/retry actions and cancellation-safe state
  updates.
- Reproduced: the cover-letter route never terminated its own loading state when
  signed out, leaving a permanent spinner underneath the login redirect. It now
  follows the confirmed-session loading contract.
- A `?cl=` deep link that does not belong to the résumé no longer silently opens
  a different recent cover letter; it reports that the requested document was
  not found.
- Three focused regressions, targeted ESLint, and a scoped strict TypeScript pass
  succeed.

### Developer-portal load truthfulness

- Reproduced: developer-key and usage failures emitted transient toasts and then
  rendered `No developer API keys yet`, making an outage indistinguishable from
  a valid empty account. Session-probe failure also left the page on a permanent
  `Loading developer portal…` message.
- Fixed: partial/full API failures remain visible with retry while preserving any
  successfully loaded or stale data, and session verification failure has an
  explicit recovery state. Confirmed signed-out rendering terminates cleanly
  while the shared guard redirects.
- Two focused regressions, targeted ESLint, and a scoped strict TypeScript pass
  succeed.

### BYOK credential-page gating and error states

- Reproduced: `/byok` invoked the auth hook but rendered its credential manager
  immediately, allowing protected key/provider requests before session
  resolution and leaving session failure indistinguishable from normal content.
- Reproduced: failed key retrieval became `No API Keys Yet`, while failed
  provider configuration still enabled the Add Key dialog with an unusable empty
  selector.
- Fixed: the route gates child mounting on a confirmed session, session failure
  has explicit retry, key/provider failures remain visible independently, and
  adding a key is disabled until provider configuration is actually available.
  Key deletion also URL-encodes its identifier.
- Three focused regressions, targeted ESLint, and a scoped strict TypeScript pass
  succeed.

### Settings and billing session-state accuracy

- Settings now uses the shared confirmed-session guard and renders session
  verification failure explicitly instead of presenting an authenticated user
  with the signed-out settings card during a transient refresh outage.
- Billing remains a public pricing surface, so it does not redirect; it now
  latches the last confirmed identity through pending/error refreshes. Current
  subscription, verification, and team-seat UI cannot temporarily flip to guest
  state. A confirmed empty response still clears the latch after logout.
- Four focused regressions, targeted ESLint, and a scoped strict TypeScript pass
  succeed.

### Public template-library recovery

- Reproduced: a failed template/category request rendered the normal `No
  templates found` result with a zero count after a transient toast, and offered
  no retry.
- Fixed: the public library has a distinct accessible outage state with retry.
  Search/category empty results remain separate.
- Template creation also retains the last confirmed identity during a transient
  session refresh, so an already-authenticated user is not incorrectly sent to
  login when clicking Use Template. Confirmed logout still clears the latch.
- Two focused regressions, targeted ESLint, and a scoped strict TypeScript pass
  succeed.

### Run-history session accuracy

- The history page now preserves the last confirmed identity through pending or
  failed session refreshes instead of replacing an authenticated user's run list
  with the sign-in card. A first-load verification failure is explicit and
  retryable; confirmed logout still clears the identity latch.
- The existing run-list outage/empty-state regression remains green alongside
  the new session regression, targeted ESLint, and scoped strict TypeScript.

### Malformed UUID route boundaries

- Reproduced: newer résumé-adjacent endpoints queried PostgreSQL UUID columns
  with unchecked string path/body identifiers. Malformed values therefore
  reached asyncpg and could become internal 500s instead of resource-not-found
  responses, repeating the older résumé CRUD defect.
- Fixed at each boundary before database or external-provider work: career
  analyze/list/detail; interview generate/list/detail; application PDF/submission
  detail; all per-résumé GitHub and Dropbox sync operations; Zotero import/clear;
  Mendeley import; workspace/member/resume/recruiter-note operations;
  collaboration comments; macros; snippets; tenants; tracker applications; and
  team-seat removal.
- Thirty-nine focused regressions assert a clean not-found response/close and no
  database call for malformed identifiers, including the collaboration
  WebSocket handshake. The entire backend API package passes Ruff and diff
  whitespace validation is clean.
- Body-carried UUID collections now have the same boundary: semantic matching
  rejects malformed IDs and more than 20 selections instead of silently slicing
  or reaching asyncpg; merge requires 2–4 distinct valid IDs and only permits a
  section source from the selected set. Focused schema regressions pass.
- The surrounding GitHub and Dropbox authorization-contract tests pass with
  syntactically valid UUID fixtures. The career-role route test reaches its real
  database query and is blocked solely by this sandbox's PostgreSQL socket ban;
  its failure contains no application assertion mismatch.

### BYOK generation input bounds

- Reproduced: the direct provider relay accepted empty/oversized message lists,
  malformed roles and shapes, unbounded output-token requests, and non-finite or
  provider-invalid temperature values before making an external request.
- Fixed: supported providers and model length are constrained; messages require
  an exact role/content shape with per-message, aggregate, and count ceilings;
  `max_tokens` and temperature now have finite provider-safe bounds.
- Stored/validated provider keys and their database-backed display names now
  have matching provider, text, and column-length boundaries as well.
- Eighteen focused schema regressions and Ruff pass. The existing HTTP-level
  stream-rejection test remains database-fixture limited in this sandbox.

### Team invitation recovery

- Reproduced: a team seat was committed before its Redis invitation token. A
  token-store or email-delivery failure therefore left a pending row that the
  owner could not retry; resends could also be rejected at the plan seat limit.
- Reproduced: accepted seats use status `active`, while duplicate protection
  checked only for `joined`. Re-inviting an active teammate could reset the seat
  to pending and clear its user binding.
- Fixed: invite emails are normalized/validated, the token is persisted before
  the seat commit with rollback/cleanup on failure, pending seats are resendable
  without consuming another capacity slot, undelivered tokens are removed, and
  every non-pending/non-removed seat is protected from reinvitation. Corrupt
  Redis token payloads close as not-found before database work, while
  post-commit token cleanup is best-effort and cannot falsify activation.
- Five focused state-machine/saga/schema regressions, Ruff, and diff validation
  pass.

### Deep-analysis dispatch visibility

- Reproduced: `/ats/deep-analyze` logged and ignored failure to create the
  initial Redis job state, then dispatched work and returned a job id the client
  could not reliably poll. The caller's plan/trial usage could still be spent.
- Fixed: Redis state creation is now a required dispatch gate. State or broker
  failure uses one compensation path to refund plan quota or anonymous trial
  usage, returns 503, and never launches an invisible worker.
- A focused authenticated dispatch regression proves quota refund and zero
  worker submission; Ruff and diff validation pass.

### Async job submission cleanup

- Reproduced: rule-based ATS/JD analysis also returned success after initial
  Redis state failure, and broker failures across shared job submission could
  leave `queued` snapshots, streams, sequence keys, and user job-index entries
  for work that was never dispatched.
- Fixed: ATS state creation is required and both ATS dispatch paths return a
  recoverable 503 without launching work. A shared best-effort cleanup removes
  every initial Redis artifact and user index entry after pre-dispatch failure;
  main, watermarked, and batch submission failure paths now invoke it.
- Reproduced: a post-dispatch telemetry/bookkeeping exception could enter the
  generic enqueue-failure handler, erase a running job's state, refund its
  charge, and return an error that encouraged a duplicate retry. Dispatch is now
  latched; later bookkeeping failure returns the already-accepted job instead.
- Four dispatch/cleanup regressions, full backend Ruff, and diff validation pass.
  Database-backed batch integration remains environment-limited here.

### Cover-letter generation saga

- Reproduced: generation committed an empty cover-letter row before plan quota
  authorization, so a legitimate 402 could leave a permanent orphan. A later
  broker failure deleted the row but left its queued Redis job artifacts.
- Fixed: plan/BYOK/quota resolution now precedes row creation; database, initial
  Redis state, and worker dispatch are one compensated pre-dispatch saga. Any
  failure refunds platform quota, removes job state, and deletes or rolls back
  the placeholder row.
- Two focused quota/broker regressions, Ruff, and diff validation pass; the
  existing database-backed orphan regression remains available outside this
  sandbox.

### Async request-size and storage boundaries

- Reproduced: shared job submission allowed oversized documents, job
  descriptions, nested lists/metadata, provider-model fields, and 256+ character
  device fingerprints even though several downstream database columns cap the
  fingerprint at 255. Batch tailoring also queried a UUID column with an
  unchecked body `resume_id`.
- Fixed: job/watermark/ATS/deep-analysis/analytics request models now enforce
  document and prompt ceilings, finite list/dict counts and per-item lengths,
  supported optimization modes, provider field widths, and database-aligned
  fingerprint sizes. Batch resume IDs validate as UUIDs before database work.
- Eighteen focused request/dispatch regressions, full backend Ruff, full test
  collection/import, and diff validation pass.

### SMTP event-loop safety

- Reproduced: the async email service called blocking `smtplib` directly and
  opened the SMTP connection without a timeout, allowing a slow mail server to
  stall the API/worker event loop indefinitely.
- Fixed: SMTP delivery runs through `asyncio.to_thread`, and the underlying
  connection has a 15-second timeout. Resend remains natively asynchronous.
- Two focused lifecycle regressions, Ruff, and diff validation pass.

### DNS event-loop safety

- Reproduced: job/URL-import SSRF checks and custom portfolio verification ran
  blocking `socket.getaddrinfo` calls directly inside async handlers, so slow DNS
  could stall unrelated requests.
- Fixed: initial URL checks, every redirect transport hop, and both portfolio
  resolutions run in worker threads; the independent portfolio lookups also run
  concurrently. SSRF address policy and redirect validation are unchanged.
- Three focused async lifecycle regressions, Ruff, and diff validation pass.

### Batch partial-dispatch recovery

- Reproduced: when the broker accepted the first jobs in a batch and rejected a
  later one, the endpoint returned 500 even though paid work was already running.
  A normal client retry could create duplicate variants and duplicate jobs.
- Fixed: a partially accepted batch returns its stable tracking ID, marks every
  undispatched entry failed, and refunds only those entries. A zero-dispatch
  failure still returns an error, but now removes the batch record and all newly
  committed variants as well as refunding the full charge.
- Two compensation regressions and the database-backed batch module pass.

### Bounded job-page downloads

- Reproduced: the job scraper buffered an arbitrary remote HTML response through
  `AsyncClient.get()` before parsing it, allowing an upstream page to consume
  unbounded process memory despite the extracted-description character cap.
- Fixed: HTML is streamed and stopped at 2 MiB, with both declared-length and
  chunked-response enforcement plus defensive charset decoding.
- Three focused streaming regressions and all 65 scraper tests pass.

### Real local integration baseline

- Recreated and migrated the dedicated `latexy_test` database through Alembic;
  development data was not used or modified by the backend suite.
- The complete backend suite passes against real local PostgreSQL and Redis. Its
  only output is one upstream Starlette TestClient/httpx2 deprecation warning.
- The complete ordinary TUI suite passes: 34 files / 197 tests, with seven
  opt-in live files / 66 tests skipped by design. This includes the real-PTY
  keyboard suite and the WebSocket resume-position suite that were previously
  socket-blocked. A separate real-service run passes all 66 live tests.
- GitHub CLI access is healthy. Recent `main` CI and automatic Modal backend
  deployment runs are successful; the remediation epic remains open and the
  only open pull requests are Dependabot updates.

### Celery Redis health ownership

- Reproduced: forked Celery workers initialized only the event-publisher Redis
  client, so their scheduled health task reported queue/cache Redis as degraded
  even while both services were healthy.
- Fixed: every child now creates and pings its own synchronous queue/cache
  clients during worker initialization and closes them through the existing
  child shutdown path. Failed replacement clients are closed before the error
  propagates.
- Focused lifecycle/fork regressions pass. A live scheduled health task on the
  local worker reports queue, cache, and event Redis healthy.

### Auth cold-start and custom-domain availability

- Reproduced: the first Better Auth session route compilation took about 4.8s,
  while API requests abandoned the auth gate after 1.5s and could issue a
  protected request without its token.
- Fixed: the bounded gate allows an 8s cold start and starts its timer lazily
  only when an API request actually waits. A page that makes no API request no
  longer emits a false auth timeout warning.
- Custom-domain middleware now bypasses API/public-user and known first-party
  hosts, includes the configured app hostname, excludes `/api` from its matcher,
  and aborts a portfolio lookup after two seconds rather than blocking a request
  indefinitely.
- Eight focused auth/middleware regressions pass.

### Format, OCR, and document parser safety

- Reproduced: ordinary contact text containing `Email:` and `Phone:` was
  classified as YAML; a `{` prefix was treated as JSON without parsing it.
- Fixed: JSON detection requires a parsed object/list and YAML detection requires
  a structured mapping/list, leaving normal prose reachable by the text parser.
- PDF, image/OCR, and DOCX extraction now run off the async request loop. DOCX
  archives are rejected before extraction when they exceed 1,000 entries or
  50 MiB of declared uncompressed content.
- A shared chunked reader now caps all format, compile, builder-seed, and
  LinkedIn import uploads even when `Content-Length` and `UploadFile.size` are
  absent.
- Parser, builder, conversion, LinkedIn, and upload-limit regressions pass.

### Stale-job and streaming-state correctness

- Reproduced: cleanup measured a processing job from submission time, so long
  queue wait could make newly started work look timed out; it also ignored an
  already-written terminal result and never revoked work it marked failed.
- Fixed: processing timeout uses the latest state heartbeat, skips jobs with a
  terminal result, and revokes a genuinely stale Celery task before publishing
  failure.
- `llm.token` events no longer overwrite the last meaningful REST progress
  snapshot with an empty stage and zero percent.
- Cover-letter and legacy LLM streams now expose only LaTeX between delimiters,
  including when markers are split across provider chunks; scaffold/prose stays
  out of the editor.
- Cleanup, event-publisher, worker, and split-delimiter regressions pass.

### Database index and capability-report drift

- Reproduced against the migrated `latexy_test` catalog: eight foreign-key
  columns had no usable leading index, while `session.token` had both its unique
  btree and a redundant plain btree.
- Migration 0037 adds the eight indexes, drops the duplicate, and aligns model
  metadata. Upgrade → downgrade → upgrade succeeds; the final catalog is at
  0037 with all eight indexes and no redundant session index.
- LaTeX health detection now requires a reachable Docker daemon and the exact
  configured image rather than accepting the presence of a CLI binary. The
  legacy compiler also uses the configured image instead of a hard-coded tag.

### Admin control-plane reliability

- Reproduced: startup promoted configured admin emails without requiring a
  verified address and re-promoted explicitly demoted accounts on every restart.
  Concurrent demotions could both pass the last-admin count, promoted RBAC admins
  had no header navigation, mutations had no structured audit events, and a 503
  authorization probe rendered the full admin shell.
- Fixed: configured emails bootstrap only verified users and only when no admin
  exists; role mutations serialize under a transaction advisory lock; every
  mutation emits an actor/target/action audit event; `/me` returns the RBAC role
  used by navigation; and indeterminate authorization renders retryable recovery
  without mounting admin controls.
- Admin API/auth/user-preference and focused header/session tests pass.

### Rendered local browser evidence

- The anonymous Studio compiled a real sample through the local API, Redis,
  Celery worker, TeX engine, WebSocket, and PDF viewer: one-page PDF rendered,
  extracted text was visible, ATS score was 59, and trial usage decremented once.
- Signed-out workspace access redirected to the encoded login destination.
  Public platform/templates/pricing/resources/FAQ/updates/privacy/terms/auth
  routes rendered their expected primary headings without browser errors.
- At 390×844 the Studio has no horizontal overflow, exposes mobile
  Tools/Editor/PDF controls, and opens its tools drawer.
- A 75-test focused Playwright tranche for compile timeouts, cover letters,
  GitHub OAuth binding, and health passes. The ATS quick-score suite passes all
  37 tests after replacing fake-clock sleeps and WebSocket-hostile network-idle
  waits with deterministic signals.

### Editor initialization and live-buffer integrity

- Reproduced in the optimized production artifact: collaborative Monaco mounted
  with an empty default model while its imports and WebSocket handshake were
  still pending. Its initial change event could replace fetched résumé content
  with an empty parent buffer.
- Reproduced on `/try`: Save, login continuation, and GitHub project insertion
  could run after the imperative wrapper existed but before Monaco itself was
  ready. The wrapper reported an empty value, so the flow stored an empty draft
  or discarded the imported project.
- Reproduced in the authenticated editor: autosave and adjacent live-buffer
  consumers trusted the same transitional empty value and could persist a blank
  résumé shortly after a valid lint fix.
- Fixed: collaborative Monaco starts from fetched REST content; project insertion
  detects a no-op editor; and persistence/live-buffer paths fall back to React's
  current content when Monaco has not produced a usable snapshot. Focused unit
  regressions and the repaired development-browser tranche pass.

### TUI responsive sign-in overlay

- Reproduced: unlike the résumé and select overlays, sign-in retained a fixed
  50-column frame and overflowed a 40-column terminal.
- Fixed: sign-in uses the shared resize-aware overlay width and compact padding.
  Three sizing regressions, the complete 195-test TUI suite, typecheck, and
  production build pass.

### Frontend dependency and runtime modernization

- Upgraded Next.js and its ESLint preset from 14.2.35 to 15.5.21 and migrated
  async route parameters to the Next 15 contract. Upgraded React-PDF to 10.5.0
  and kept PDF.js behind a client-only boundary so all application routes remain
  prerenderable.
- Replaced the editor's runtime jsDelivr dependency with a pinned local
  `monaco-editor` 0.55.1 distribution prepared into ignored generated assets by
  `predev` and `prebuild`. Browser traces confirm the editor workers load from
  `/monaco/vs`, with no CDN requests.
- Development now uses Turbopack because the PDF.js 5 worker construct triggers
  an upstream bug in Next 15's bundled development Webpack. The production
  Webpack build remains authoritative and passes.
- Replaced `next lint`, deprecated by Next 15 and removed in Next 16, with the
  ESLint CLI. Only the generated Monaco vendor copy is excluded; authored
  source, tests, scripts, and configuration remain in scope.
- Production dependency audit went from 69 advisories at the start of the pass
  to zero. On 2026-09-07, four newly published `fast-uri` advisories were also
  remediated by advancing the existing override to 3.1.6; a fresh
  `pnpm audit --prod --audit-level low` reports no known vulnerabilities.

### Production artifact and PDF-renderer verification

- The Node 22.23.2 optimized build compiled, linted, type-checked, generated all
  36 static pages, collected traces, and passed the repository artifact
  validator. The first build is intentionally heavier because Monaco language
  workers are now local rather than downloaded by each browser at runtime.
- The actual standalone server passed nine focused production-mode Playwright
  scenarios covering builder import, compile timeout recovery, Monaco linter
  mutation, parent diff, anonymous import/auth gating, and privacy, terms, and
  changelog routes.
- A real anonymous local compilation produced a valid one-page A4 PDF (PDF 1.7,
  28,329 bytes). The standalone UI consumed those exact bytes, rendered the
  React-PDF canvas and preview controls, and emitted no browser page error.

### Browser-suite flake remediation

- The complete 445-scenario development suite reached a passing final status
  (440 passed, five intentionally skipped), but retained timing recoveries on
  the first attempt under two-worker cold-start load.
- ATS fake-clock tests now wait for the asynchronously loaded Monaco status bar
  before advancing the debounce; fake-clock navigations stop at
  `domcontentloaded`. Variant tests no longer wait on WebSocket-hostile
  `networkidle`, page-count tests use the shared visible editor signal, and
  template navigation avoids waiting on nonessential subresources.
- Playwright's global test timeout is 60 seconds so a pair of cold editor-route
  Turbopack compilations is not misclassified as an application failure.
  The formerly flaky set passes 36/36 across three repetitions, two workers,
  and zero retries.
- One later API-route assertion sampled a request listener synchronously even
  though the workspace fetch begins after hydration. The rendered page already
  contained the mocked API data when the assertion failed. It now polls for the
  observable request; the focused regression passes 5/5 with two workers and
  zero retries.
- Current-tree broad coverage is green without retries when run in its intended
  modes: all 426 production-compatible scenarios pass against the standalone
  artifact, and all 14 tests that deliberately require the development-only
  Monaco control hook pass against Turbopack. Five scenarios remain intentionally
  skipped, yielding the complete 440-pass / five-skip inventory.
- A monolithic development rerun was stopped after macOS reported system-wide
  `ENFILE` from the Turbopack watcher. The host already held about 23,115 of its
  30,720 global file slots before that run; the production/development partition
  removes that host constraint without weakening scenario coverage.

### Real-account route, auth, and artifact audit

- Seeded and compiled the complete current template catalog against the real
  local PostgreSQL, MinIO, Redis, Celery, and TeX stack. All 56 templates now
  have current PDF and PNG artifacts; direct thumbnail retrieval follows its
  signed redirect and returns a non-empty `image/png` response.
- Reproduced: repeated authenticated navigation exhausted the custom default
  20/minute auth bucket for `/get-session`. Better Auth also had a second
  process-local global limiter, so behavior differed across instances.
- Fixed: the shared atomic PostgreSQL limiter is the sole auth gate and gives
  the high-frequency session-read endpoint its own 300/minute bucket. Sixty
  sequential real session reads return 60 HTTP 200 responses and one shared
  counter records all 60.
- Reproduced: tenant administration requested protected data before session
  resolution and exposed actionable UI to a signed-out visitor. It now uses the
  shared confirmed-session guard, renders retryable session failure, and makes
  no tenant request while signed out.
- Reproduced: the PDF preview fetched optional SyncTeX text with a raw
  cross-origin `fetch`, omitting the bearer token. A real authenticated compile
  returned the PDF but the SyncTeX request received 403. The API client now
  performs that download through the authenticated gate with cancellation;
  live verification returns 200 for both artifacts and enables source sync.
- The route-audit harness now owns its screenshot directory and builder fixture
  and uses a fresh page/listener set for every route. The resulting crawl reports
  zero findings across anonymous, authenticated, résumé-scoped, builder, admin,
  and signed-out protection states.

### Assertive edge-case and live-TUI coverage

- The edge browser audit previously logged malformed-route failures, share-link
  leaks, and trial behavior without failing. It now asserts accessible recovery,
  absence of uncaught browser errors, immediate anonymous share readability,
  revocation denial at both UI and API layers, exact trial charging, and
  cooldown enforcement.
- All four edge groups pass against the real local stack. Anonymous compilation
  decrements the device counter once; an immediate second submission receives
  429 without another charge; a new fingerprint receives the documented quota.
- The live TUI suite now creates its own tracker row when the isolated account
  has none, rather than depending on mutable developer data. All seven live files
  / 66 tests pass serially against real auth, API, PostgreSQL, Redis, workers,
  WebSockets, TeX compilation, checkpoints, forks, sharing, hostile editors, and
  recovery paths.

### Local runtime parity

- Reproduced: `scripts/dev.sh` launched the frontend with whichever host Node
  happened to be first on `PATH`; pnpm only warned when that was Node 23 even
  though the package, CI, and production images require Node 22.
- Fixed: the launcher reuses an active Node 22 or resolves Node 22 through mise,
  and fails clearly when neither is available. Stale Next-process cleanup now
  matches the actual Turbopack command line, and shell cleanup terminates each
  background job without unsafe word splitting.
- A clean stop/infrastructure restart/migration/app start was verified. The live
  Next process resolves to mise Node 22.23.2, and both frontend and backend health
  endpoints return HTTP 200.

### Assertive interactive browser coverage

- The interactive audit previously relied mainly on screenshots and console
  output. It now fails on backend 429/5xx responses, uncaught page errors,
  unsuccessful compile/ATS/SyncTeX responses, a missing rendered PDF canvas,
  a non-terminal WebSocket job, or a UI left in an error/loading state.
- The dashboard, anonymous Studio, and authenticated editor all pass against the
  real local stack. The anonymous path completes through the submit API, worker,
  WebSocket, TeX engine, and React-PDF renderer. The authenticated editor also
  completes its intentional initial compile and receives HTTP 200 from both ATS
  quick-score and the authenticated SyncTeX artifact request.
- The reusable audit account was restored to its original non-admin, unverified,
  free/inactive fixture state after the run.

### Repository security controls

- GitHub secret scanning and push protection are enabled and report no open
  alerts. A local content scan also confirms that the supplied Upstash REST
  token was not written into the repository.
- Dependabot vulnerability alerts and automated security updates are enabled.
  The repository currently reports no open Dependabot alerts, matching the
  zero-advisory production dependency audit.
- GitHub default CodeQL setup is enabled for Actions, Python, and
  JavaScript/TypeScript. The initial run `34129534283` and extended-suite run
  `34132616877` both completed successfully. The extended suite is now the
  repository default with the remote threat model.
- The extended result was triaged by class, not bulk-suppressed. Its 123 Python
  log-injection alerts are centrally mitigated by the process-wide JSON
  formatter; an adversarial CR/LF regression proves each event remains exactly
  one JSON record, and those alerts are dismissed with that evidence.
- Real findings fixed locally include a silent-compiler timeout/cancellation
  hang, DNS-rebinding SSRF in the generic scraper, hostname-lookalike acceptance
  in Greenhouse/Lever and reference URL detection, unencoded provider path
  components, OAuth popup messages without origin/source binding, tenant logo
  URL XSS, chained LaTeX/TikZ escaping, sensitive upstream error reflection,
  predictable temporary files, and unsafe logging of provider/Redis failures.
- The shared JSON logging boundary now also redacts credentials embedded inside
  free-form messages and exception strings (URL passwords, bearer tokens, and
  named secret assignments), not only structured fields. Adversarial regressions
  cover both record-forging line breaks and credential-bearing messages.
- Every action used by a tracked GitHub workflow is pinned to a verified full
  commit SHA. The default token is explicitly read-only unless an individual
  release job grants narrower write access.
- The 65 polynomial-regex candidates now run through a compatibility facade
  with a 250 ms engine timeout. A catastrophic-pattern regression confirms a
  100,000-character adversarial input is interrupted rather than monopolizing
  a worker.
- `pnpm audit --prod` reports no known JavaScript vulnerabilities. A local
  Python environment audit identified the unfixed Minerva timing advisory in
  `ecdsa`, pulled only by unused `python-jose`; the application uses PyJWT, so
  the dead `python-jose`/`ecdsa`/`rsa`/`pyasn1` dependency chain was removed.
- A later full-graph audit (including development tooling) found a critical
  Vitest file-read/execute advisory in the TUI's older test runner plus patched
  Vite and js-yaml advisories. The TUI now uses Vitest 4.1.10, the workspace
  forces js-yaml 4.3.1 for the legacy ESLint graph, and CI fails on any low or
  higher JavaScript advisory. Full `pnpm audit` and the installed Python
  environment audit now both report zero known vulnerabilities. The upgraded
  runner passes 34 files / 197 ordinary tests and all seven files / 66 live
  tests; its WebSocket constructor mock was migrated to Vitest 4 semantics.

### Final live-stack audit corrections

- Reproduced a local-only stale-bundle failure: a restarted Next process had the
  correct `NEXT_PUBLIC_API_URL=http://localhost:8030` environment but reused
  Turbopack output compiled with port 8000. Preserving/removing the generated
  `.next` cache and restarting produced the correct bundle; the live dashboard,
  Studio, editor, and API traffic then used port 8030 throughout.
- Reproduced a more serious hybrid-infrastructure collision: Homebrew Redis was
  listening on loopback port 6379 while Docker Desktop also advertised the
  `latexy-redis` container on that port. Host processes silently reached the
  unrelated native daemon (1,946 existing keys), which leaked old quota state
  into the QA account. Local Docker Redis now uses host port 6380 (internal
  container networking remains 6379), and `dev.sh` validates all three infra
  containers plus the expected Redis port before deciding the stack is healthy.
  Celery and both backend Redis clients were verified on port 6380 with a clean
  container database.
- Audit-mode Playwright discovery is now genuinely opt-in via
  `PLAYWRIGHT_AUDIT=1`; the former unconditional ignore also ignored explicitly
  named audit files. Live specs derive the backend origin from `AUDIT_BE` instead
  of hard-coding one port, select realistic résumé fixtures, and compile an
  artifact before asserting share-link readability.
- A dashboard visit made 48 backend responses because every completed history
  row opened a live job subscription and independently fetched terminal state
  and result. Terminal rows no longer mount that hook, reducing the same audited
  load to 14 responses. Concurrent dashboard consumers now share one in-flight
  `/jobs/` read, and the canonical trailing slash removes its 307 round trip.
- A 27-request quota concurrency regression exposed the non-blocking Redis
  client's `MaxConnectionsError` behavior: a momentary burst denied valid
  callers before Redis could allocate the free plan's ten slots. Async and sync
  clients now use bounded blocking pools, preserving the configured connection
  cap while applying up to five seconds of backpressure. The focused burst now
  admits exactly ten calls, and the complete backend suite is green against the
  isolated Docker Redis databases.
- The test bootstrap previously isolated only the queue Redis URL; it could
  inherit `REDIS_CACHE_URL` from a developer `.env` and let quota/cache tests
  mutate the running application or a remote Upstash database. Queue and cache
  now default to distinct Docker Redis databases 15 and 14, both are forced
  before settings import, and both are flushed before and after the suite. CI
  explicitly maps those test databases to its runner-local Redis service.
- Full ESLint was also traversing generated Playwright HTML-report bundles and
  reporting third-party hook violations as authored source failures. Next,
  Playwright, test-result, and generated Monaco trees are now excluded while
  every application and test source remains linted; the complete lint pass is
  clean.
- The all-route audit now treats friendly in-place auth guards, public billing,
  and a normal user's expected admin 403 as explicit contracts, while asserting
  that every other console/network/page failure and auth leak is absent. Its
  authenticated/protected rerun reports zero problems and zero leaks.
- A repository-wide Bandit pass found no high-severity Python findings and
  exposed one credible medium parser boundary: the fixed-origin arXiv feed was
  still external XML parsed by the standard library. Reference ingestion now
  uses `defusedxml`, rejects entity-bearing/malformed feeds with a stable error,
  and defines Crossref/arXiv/ORCID timeouts at the HTTP client boundary. The
  hostile external-entity regression and all 34 reference tests pass.
- Worker health labelled every retained `latexy:job:*:state` key as active,
  including terminal history and its own periodic health probes; an idle local
  queue therefore reported 32 active jobs. It now scans incrementally, batches
  state reads with `MGET`, ignores malformed/synthetic/terminal snapshots, and
  counts only queued/pending/processing/running/retrying user jobs. The same
  live Redis held 33 retained states and correctly reported zero active work.
- The health pass also surfaced host disk pressure. The 1.1 GB stale Next cache
  preserved during diagnosis was a generated temporary copy and has been
  removed; no repository or unrelated user data was deleted.
- Workbox previously cached authenticated `/resumes` API responses in a global
  browser Cache Storage entry that survives logout, creating a shared-browser
  cross-account disclosure risk. Authenticated payload caching is removed until
  it can be encrypted and partitioned per user. A Node 22 production build
  completed across all 36 pages, and the generated service worker contains only
  the app-shell and public PDF caches.
- Programmatic external navigation now rejects non-HTTP(S) billing destinations
  and severs `window.opener` for payment, verification, generated-portfolio, and
  slide-PDF tabs. OAuth popups retain their opener intentionally because their
  callback is separately bound to the expected origin and popup window.
- Frontend HTML previously shipped without a response-level security baseline.
  Every Next response now denies framing, MIME sniffing, foreign base URLs, and
  object embedding; applies a strict-origin referrer policy and disables unused
  camera/microphone/geolocation capabilities; and omits `X-Powered-By`. A live
  Playwright header contract verifies all six properties without introducing a
  broad CSP source allowlist that would break Next bootstrap or Monaco workers.
- Next's dev warning survived an empty `turbopack: {}` because its config checker
  flattens only leaf keys. The normal development module-id strategy is now
  explicit; a live config reload starts cleanly as Next 15.5.21 (Turbopack)
  without the Webpack/Turbopack warning.
- A redacted working-tree Gitleaks pass classified every tracked match. The only
  credential-shaped production artifact was a stale audit record preserving the
  already-removed Kubernetes default passwords; their literal/base64 values are
  now removed from that historical evidence. Remaining tracked matches are test
  fixtures, placeholders, or ordinary copy (for example “LinkedIn export”).
- The final backend pass collected and passed all 3,102 tests. The deprecated
  Starlette 413 constant was replaced and its seven middleware regressions pass;
  the only remaining warning is Starlette's upstream TestClient/httpx2 migration
  notice. The live readiness probe reports database, queue Redis, and cache Redis
  all `ok`, and scheduled health reports zero active jobs on an idle queue.
- The exact warning-enabled #1702 reproduction also passes without an unclosed
  Redis connection, `StreamWriter`, or selector-transport warning. While proving
  that boundary, authored deprecations were removed ahead of their upstream
  removals: Pydantic response models use `ConfigDict`, list constraints use
  `max_length`, UTC timestamps are timezone-aware, and all application plus test
  Redis TTL writes use `SET ... EX` instead of deprecated `SETEX`. The only
  warning-enabled notices left are inside Celery's Redis result backend and
  Starlette's TestClient adapter; an ordinary full run emits only the latter.
  The exact CI gate also passes all 3,102 tests with `ResourceWarning`,
  `RuntimeWarning`, and `PytestUnraisableExceptionWarning` promoted to errors.

### Historical finding closure and final regression pass

- Public portfolio contact is now a real, bounded endpoint and form: input is
  validated and HTML-escaped, recipient/IP rates are enforced in Redis, delivery
  failures fail closed, and disabled or unknown portfolios cannot be contacted.
- Per-résumé portfolio visibility is stored and enforced through migration 0038,
  the API, and the workspace controls instead of publishing every résumé whenever
  a user's portfolio is enabled.
- Snippet installs/upvotes use PostgreSQL conflict handling and atomic counters;
  concurrent toggles no longer lose increments or drive aggregate counts negative.
- Billing now forwards the provider webhook event id, preserves checkout semantics
  for student verification, and makes team pause/resume update seat and member
  entitlements consistently without overwriting independently purchased plans.
- Semantic matching no longer truncates the candidate set to an arbitrary first 20
  rows and excludes archived résumés unless the caller explicitly selected ids.
- Empty Monaco documents keep the editor instance, undo stack, providers, and
  history mounted. REST job polling now hydrates queued/processing snapshots into
  the same reducer used by WebSocket events.
- Local Make/worktree commands now target the canonical compose services and real
  image namespace. The production backend image includes OCR/PDF prerequisites.
- Preview, anonymous-redaction, and TikZ-derived compiles no longer create user
  version checkpoints; ordinary owned compiles still do.
- Writing assistance no longer reports echoed input as a successful rewrite when
  no provider exists or a provider fails; failed calls refund their quota.
- BYOK Anthropic validation uses the auth-only models endpoint instead of a billed
  completion against retired model ids. Unknown model pricing is explicitly marked
  unknown rather than billed using a fabricated fallback, and help copy describes
  the actual provider routing and Gemini limitation.
- Request body limits now cover chunked bodies. A full-suite regression exposed and
  fixed a false-disconnect bug in that middleware which had truncated every streamed
  ZIP export; a dedicated streaming response test pins the ASGI lifecycle.
- Worker event publication now atomically allocates sequence, persists to the
  replay stream, publishes live delivery, refreshes TTLs, and updates the REST
  snapshot in one Redis Lua call. Token/log deltas skip state writes so they cannot
  reset progress to zero. The transaction was exercised against local Redis.
- Workspace roles now have enforced semantics: owners/editors can create and mutate
  their recruiter notes, viewers remain read-only even after demotion, while all
  members retain workspace and résumé read access.
- Synchronous compile endpoints use the in-image/local engine fallback, clean failed
  job directories immediately, and validate anonymous input before spending a trial.
  LaTeX health capability is re-probed instead of remaining frozen at import time.
- The isolated database migration chain successfully round-trips from 0038 to 0030
  and back to 0038, proving the repaired index rollback and later schema revisions.
- Current verification: 3,136 backend tests collect; the complete backend suite,
  repository-wide Ruff, 82 frontend Vitest files / 666 tests, strict TypeScript,
  full ESLint, 34 TUI files / 197 tests (66 live tests opt-in), TUI typecheck/build,
  migration round-trip, and full JavaScript dependency audit are green. The exact
  CI warning gate passes the full backend suite with resource, runtime, and
  unraisable-exception warnings promoted to errors. The optimized Node 22 frontend
  build validates all artifacts and generates all 36 pages.
- The final mocked-browser regression covers 451 Chromium scenarios without
  retries: 446 pass and five documented opt-in/conditional cases skip. The 11
  opt-in unmocked audits also pass against the restarted local stack, covering the
  anonymous, authenticated, résumé-scoped, authorization, malformed-id, sharing,
  trial, dashboard-budget, compile, WebSocket replay, collaboration, PDF, SyncTeX,
  and ATS paths. The page crawl reports zero page problems and zero auth leaks.
- Independent live probes report healthy database, queue/cache Redis, object
  storage, LaTeX capability, job service, and frontend. A fresh anonymous document
  compiled successfully in 1.07 seconds and its 14,396-byte PDF downloaded with a
  200 response. An in-app browser inspection found the landing and anonymous
  studio structurally complete, interactive controls exposed, local autosave
  active, and no browser warnings or errors.
- Current-source reconciliation found that onboarding and Help Center copy had
  escaped the earlier marketing-claim audit and still implied employer-ATS
  emulation and screening-outcome prediction. The copy now describes Latexy's
  heuristic document checks, explicitly disclaims employer-system reproduction
  and outcome prediction, and the CI phrase guard covers the missed variants
  ([#1711](https://github.com/sanskarpan/Latexy/issues/1711)).
- The epic's signup/onboarding coverage requirement previously had only page-load
  and localStorage-helper evidence. A four-scenario browser suite now verifies
  pre-request password validation, accessible Better Auth failure recovery,
  external redirect rejection, all onboarding steps, local completion, and the
  account preference PATCH ([#1712](https://github.com/sanskarpan/Latexy/issues/1712)).

### Security-dashboard reconciliation

- GitHub still reports dependency alerts against the published `main` lockfile,
  including Next, Vitest, tar, DOMPurify, js-yaml, nanoid, fast-uri, PostCSS,
  brace-expansion, and transitive build tooling. The current working lockfile
  upgrades or overrides every reported advisory family. A complete
  `pnpm audit --audit-level low` reports no known vulnerabilities.
- `pip-audit` was run inside the project's Python 3.12 environment rather than
  its Python-3.8-incompatible standalone resolver. It reports no known
  vulnerabilities for `backend/requirements.txt`; the unmaintained `ecdsa`
  dependency and its unused `python-jose` chain are absent.
- Every open CodeQL class on published `main` was reconciled against current
  source. Actions have least-privilege permissions and immutable SHA pins;
  temporary artifacts use private random directories; OAuth messages are bound
  to the expected origin and popup; untrusted URLs and output paths are parsed,
  allow-listed, encoded, and bounded; renderer inputs are escaped; public errors
  no longer include internal exception text; and untrusted WebSocket text is not
  copied to logs.
- The large Python polynomial-regex alert family is bounded centrally by the
  `regex`-backed `safe_regex` facade with a 250 ms timeout. All affected
  user-controlled LaTeX/ATS/export paths use that facade, and the focused
  catastrophic-pattern regression proves interruption in under one second.
- The Jinja autoescape alert is obsolete in current source: reference-page LaTeX
  is rendered without an HTML template engine after a single-pass LaTeX escape.
  SSRF alert sites now use fixed provider origins with validated, percent-encoded
  path components; generic URL import uses the DNS-pinning transport on every
  redirect hop.
- These dashboard alerts cannot close until the working tree is published and
  GitHub recomputes CodeQL and Dependabot against that exact SHA. They are
  publication evidence requirements, not unresolved current-source defects.

### Current production and delivery blockers (2026-09-08)

- Production `/health`, `/readyz`, and `/jobs/health` are healthy: database,
  queue Redis, cache Redis, storage, LaTeX, and synchronous Redis checks all pass.
  The capacity probe still reports provider `upstash`, status `unconfigured`,
  `configured=false`, confirming that #1628 still needs the three account-level
  management values already documented in the canonical handoff.
- The npm registry still serves `@sanskarpan/latexy@1.0.3` as `latest`; source is
  `1.0.4`. Issues #1668 and #1670 therefore remain blocked on the one-time npm
  trusted-publisher binding and subsequent tag-driven publication.
- Standard GitHub secret scanning and push protection are enabled, and there are
  currently no open secret-scanning alerts. Non-provider pattern scanning and
  validity checks are disabled. A repository API enablement attempt was accepted
  but left both disabled because those controls require an eligible organization
  with GitHub Secret Protection; this external entitlement is tracked by
  [#1713](https://github.com/sanskarpan/Latexy/issues/1713).
- Repository configuration cannot prove that the formerly documented production
  test accounts were rotated or disabled. #1683 remains an identity-operator
  action and must be verified by capability/status only, never by recording new
  credentials.
- A read-only production sweep rendered all 20 sampled public and auth-gated
  routes successfully. The deployed revision still exposes only its existing
  HSTS baseline; the additional locally verified Next security headers cannot be
  certified until this working tree is published.

### Late-pass frontend data integrity and recovery

- Saved BibTeX and Zotero/Mendeley status requests now distinguish provider or
  library outages from disconnected/empty states, clear cross-résumé stale data,
  recover a failed clear, and expose retry ([#1714](https://github.com/sanskarpan/Latexy/issues/1714),
  [#1715](https://github.com/sanskarpan/Latexy/issues/1715)).
- Tracker totals are derived from the canonical board rather than a secondary
  stats request. Create/edit/move/delete mutations no longer become false
  failures after successful writes, and cancelled/invalid/failed drags restore
  the pre-drag snapshot ([#1716](https://github.com/sanskarpan/Latexy/issues/1716)).
- Workspace résumé loading is independent from recent activity and archives.
  Both secondary collections have persistent error/retry states, and failed job
  result reads remain retryable rather than being cached as empty
  ([#1717](https://github.com/sanskarpan/Latexy/issues/1717),
  [#1718](https://github.com/sanskarpan/Latexy/issues/1718)).
- Quick Tailor now requests owner-scoped worker persistence before terminal
  completion. The browser is no longer authoritative for saving the result, and
  closing the modal leaves accepted work running while explicit Cancel remains
  destructive ([#1719](https://github.com/sanskarpan/Latexy/issues/1719)). The
  34 focused backend orchestration tests and all 14 Quick Tailor browser
  scenarios pass.
- Legacy OAuth callback success is reported only after provider status
  verification; Zotero/Mendeley popups remain open on failed verification rather
  than notifying their opener falsely ([#1720](https://github.com/sanskarpan/Latexy/issues/1720)).
  Optimization persona writes prevent overlap, roll back failed optimistic
  changes, and report the failure ([#1721](https://github.com/sanskarpan/Latexy/issues/1721)).
- Interview-prep history, keyboard macros, and cross-résumé search now separate
  request failure from valid empty results and provide retry. Search rejects
  stale out-of-order responses, immediately invalidates in-flight work when a
  query changes or clears, and cancels pending debounce work at teardown
  ([#1722](https://github.com/sanskarpan/Latexy/issues/1722)). User-triggered
  proofreading failures also remain visible and retryable
  ([#1723](https://github.com/sanskarpan/Latexy/issues/1723)).
- The full browser run exposed a pre-paint race in DiffViewerModal's passive
  Escape listener. It now attaches during layout and the failing scenario passes
  ten consecutive repetitions ([#1724](https://github.com/sanskarpan/Latexy/issues/1724)).
  A separate editor no-crash check no longer waits for global network-idle while
  the editor intentionally maintains background traffic; it uses the tested UI
  control as readiness and also passes ten parallel repetitions
  ([#1725](https://github.com/sanskarpan/Latexy/issues/1725)).
- Post-change verification is green: all 3,136 backend tests pass against a
  freshly recreated/migrated PostgreSQL database; all 82 frontend test files / 666
  tests, repository-wide ESLint, strict TypeScript, and the Node 22 production
  build pass. The only backend warning is the upstream Starlette TestClient/httpx2
  migration notice.

### Final recovery, compiler, and accessibility pass

- Secondary workspace panels now invalidate stale requests when their owning
  résumé changes and expose retryable failures instead of false empty states
  ([#1726](https://github.com/sanskarpan/Latexy/issues/1726)). Confidence scores
  likewise clear stale values and make a failed refresh recoverable
  ([#1727](https://github.com/sanskarpan/Latexy/issues/1727)). Tenant-admin list
  and detail outages are distinct from valid empty/not-found states
  ([#1728](https://github.com/sanskarpan/Latexy/issues/1728)).
- New root résumés default to LuaLaTeX while legacy metadata-less documents keep
  their pdfLaTeX compatibility fallback. Fork, merge, translation, template,
  and builder creation paths preserve or establish compiler metadata; explicit
  TUI `--compiler` remains authoritative and otherwise follows the saved résumé
  preference ([#1407](https://github.com/sanskarpan/Latexy/issues/1407)). A local
  36-compile benchmark across three representative templates produced a PDF in
  every run: warm pdfLaTeX was roughly 0.35–0.42 seconds and LuaLaTeX roughly
  0.48–0.56 seconds. An earlier Modal timing attempt did not produce comparable
  engine measurements, so no remote latency claim is made.
- Non-presentation templates using the `beamer` or `beamerarticle` document
  class are rejected before creation/update while presentation templates remain
  supported ([#1408](https://github.com/sanskarpan/Latexy/issues/1408)).
- Anonymous share links can no longer fall through to an original unredacted PDF
  while the redaction artifact is processing. They return no PDF URL, a generic
  title, safe readable text, processing status, and a retry control until the
  redacted object actually exists ([#1729](https://github.com/sanskarpan/Latexy/issues/1729)).
  Ordinary shares and public portfolio résumés now also expose bounded readable
  HTML text alternatives, completing the currently achievable share/portfolio
  portion of [#1403](https://github.com/sanskarpan/Latexy/issues/1403).
- A public accessibility statement accurately distinguishes implemented support
  from known limitations, avoids a conformance claim, provides a prioritized
  support address and response aim, and is linked from the public footer
  ([#1400](https://github.com/sanskarpan/Latexy/issues/1400),
  [#1402](https://github.com/sanskarpan/Latexy/issues/1402)). Named NVDA,
  VoiceOver, and TalkBack support remains unclaimed until the required manual
  platform matrix is reproducible ([#1401](https://github.com/sanskarpan/Latexy/issues/1401)).
- Enhanced high-contrast light/dark modes now honor the operating-system
  preference, can be toggled from every standard/fullscreen header, persist in a
  dedicated cookie, and override tenant branding while active. Atkinson
  Hyperlegible is available as a document font. Its official 4.1 MB CTAN TDS
  archive is digest-pinned in the shared Modal compiler/API base rather than
  restoring `texlive-fonts-extra`; an actual in-image pdfLaTeX compile succeeded
  ([#1404](https://github.com/sanskarpan/Latexy/issues/1404)).
- `latexy.io` currently fails DNS resolution. Public share/portfolio attribution,
  generated portfolios, external reference-service identification, and the
  custom-portfolio CNAME target now use the healthy canonical `latexy.xyz`
  origin ([#1731](https://github.com/sanskarpan/Latexy/issues/1731)). The separate
  tenant subdomain contract still needs infrastructure-aware reconciliation.
- The production font capability check uncovered a pre-existing mismatch: 20
  other design-panel packages are missing from the deliberately trimmed Modal
  image. The editor now enables only the ten hosted packages, labels unavailable
  legacy choices, and gives documents using one of them an explicit migration
  path instead of allowing a guaranteed failed compile. A checked-in verifier
  compiled the exact enabled set under pdfLaTeX, XeLaTeX, and LuaLaTeX both
  locally and inside the actual Modal worker image: all 30 combinations passed
  ([#1730](https://github.com/sanskarpan/Latexy/issues/1730)).
- The published privacy policy materially overstated current instrumentation,
  security controls, certifications, retention precision, and self-service
  deletion. Both served copies now describe the observed Vercel, Modal, Neon,
  Upstash, R2, Razorpay, email, optional integration/AI, first-party telemetry,
  sharing, storage, cookie, and request-based deletion behavior without claiming
  Google Analytics, Mixpanel, Sentry, DataDog, advertising, session replay, or
  unverified certifications. The copies are byte-identical and protected by
  content regressions ([#1732](https://github.com/sanskarpan/Latexy/issues/1732));
  counsel review remains a publication prerequisite for this legal text.
- The PDF extraction contract now discovers and compiles all 56 canonical seeded
  templates with LuaLaTeX, requires every embedded font to report a ToUnicode map,
  requires at least 25 extracted words, and rejects extracted lines beginning with
  a stray contact separator. The audit found and repaired one real wrapping defect
  in `software_engineering/swe_clean.tex`; the corrected matrix passes in the exact
  Modal worker image and has a dedicated CI job. The template library surfaces the
  verified, non-comparative contract and points users to their own ATS Text View
  while warning that employer parsers differ
  ([#1290](https://github.com/sanskarpan/Latexy/issues/1290)).
- The compliant LinkedIn on-ramp now distinguishes a fast partial PDF/DOCX import
  from the richer asynchronous user-owned archive route. Both creation and editor
  entry points link to the archive request, remember only its timestamp across a
  close/return flow, ignore invalid or denied browser storage, and clear progress
  after a successful ZIP import. A browser scenario proves the complete return and
  reset flow; no profile-URL scraping or LinkedIn API claim was introduced
  ([#1287](https://github.com/sanskarpan/Latexy/issues/1287)).
- The selection writing assistant now provides the requested three-option bullet
  workflow and a persisted per-résumé library. Variant sets are keyed by source
  and job-description fingerprints, retain only a user-defined target label (not
  the full posting), render reviewable source/option diffs, and support apply,
  copy, regenerate, and delete. Backend validation rejects changed LaTeX token
  structure, repeated/unchanged options, and bullets already in the saved résumé;
  the client independently blocks duplicates from unsaved edits. The new schema
  round-trips from 0039 to 0038 and back; 31 focused backend writing tests and all
  16 Monaco browser scenarios pass without retry
  ([#1286](https://github.com/sanskarpan/Latexy/issues/1286)).
- Devanagari is now a production compiler capability rather than a research-only
  proposal. The shared Modal compiler/API image and both backend Docker images
  install Lohit Devanagari and LuaHBTeX; the new Hindi template explicitly uses
  Babel with HarfBuzz shaping. Hindi translations replace incompatible
  pdfLaTeX/font-language declarations, persist LuaLaTeX on the child variant,
  reject structurally incomplete model output, and disclose the engine choice in
  the workspace. The exact Modal image compiled all 60 discovered templates with
  ToUnicode fonts and clean extraction; three Hindi phrases round-tripped exactly
  ([#1291](https://github.com/sanskarpan/Latexy/issues/1291)). The separate tagged
  probe is reproducible but correctly fails on the deployed LaTeX2e 2022 runtime,
  where `document/metadata/tagging` is unknown; that prerequisite remains scoped
  to [#1288](https://github.com/sanskarpan/Latexy/issues/1288), and no tagged-Hindi
  claim is made.
- Regional employment formats are now first-class and discoverable rather than
  prose-only roadmap ideas. The shared gallery order includes a Regional Formats
  category with India professional biodata, India government/PSU application,
  and Polish CV/RODO sources. The Indian documents deliberately avoid Aadhaar,
  PAN, caste, and religion fields. The Polish consent is employer/role-specific,
  optional, duplicated as an official reusable snippet, and linked in source to
  UODO workplace guidance instead of presenting obsolete blanket consent as a
  universal requirement. The updated exact Modal matrix passes all 60 templates;
  66 focused backend and 24 focused frontend tests also pass
  ([#1292](https://github.com/sanskarpan/Latexy/issues/1292)).
- Builder responses now carry a vendor-neutral ATS projection derived from the
  one persisted structured résumé. It exposes split identity and location,
  single email/phone fields, typed LinkedIn/site links, canonical employment and
  education arrays, and a stable flat skill list. Partial dates preserve their
  observed year/month/day precision and represent current roles explicitly; no
  missing precision is fabricated. Existing simulator checks already cover the
  two associated content rules (vertical dates and skills with no work-history
  evidence). Fifty-eight focused backend tests and all four guided-builder
  browser scenarios pass ([#1293](https://github.com/sanskarpan/Latexy/issues/1293)).
- Compiled-PDF text is now reachable through Studio's ATS Text view and the ATS
  simulator without claiming to emulate Workday or any employer parser. The
  deeper verification found that the WebSocket path carried
  `job.pdf_extracted`, but REST completion reconciliation discarded the same
  `extracted_text` field. The fallback now reconstructs that event before
  completion, preserving both text and page count when event fanout is down.
  All 16 linter browser scenarios pass, including an intentionally dead-socket
  path; the complete frontend unit suite passes 93 files / 696 tests
  ([#1294](https://github.com/sanskarpan/Latexy/issues/1294)).
- Interview Prep now targets asynchronous spoken AI-screening preparation while
  explicitly remaining a planning surface rather than an audio/video recorder,
  employer simulator, or outcome predictor. Every new question has an assessment
  goal, spoken time target, delivery tip, evidence-grounded answer outline, and
  STAR guidance where applicable. A strict model-output boundary prevents empty
  or malformed sessions from being reported as successful, and retryable worker
  failures remain non-terminal until attempts are exhausted. Sixty-four focused
  backend tests and two browser scenarios pass; a configured live-model probe
  also produced the exact validated 5/5/3/2 question mix
  ([#1295](https://github.com/sanskarpan/Latexy/issues/1295)).
- A least-privilege Manifest V3 browser companion now captures job title,
  company, location, bounded full description, and sanitized URL from either
  schema.org data or the visible page under an explicit `activeTab` grant. A
  short-lived local handoff opens the authenticated tracker review form; no app
  credential enters the extension. Optional local-profile autofill touches only
  supported empty identity/contact fields and never uploads a résumé, overwrites
  an existing value, or submits. The extension has no broad host permission and
  does not add the deliberately excluded profile-URL scraper. Four Node 22 tests,
  three frontend boundary tests, a full authenticated capture-to-tracker browser
  save, the package validator, and a real unpacked-Chromium load pass. The browser
  flow also exposed and repaired inaccessible labels and small-viewport overflow
  in the existing application modal. CI now packages the tested source as an
  artifact ([#1296](https://github.com/sanskarpan/Latexy/issues/1296)).
- The repository-root reusable Action now renders a checked-in LaTeX CV through
  the scoped developer API on GitHub's Node 24 JavaScript-action runtime. It
  validates source/compiler/timeout inputs, confines filesystem paths, requires
  encrypted transport outside loopback, rejects redirects and cross-origin
  polling/download URLs before forwarding a bearer key, validates the PDF magic
  bytes, and replaces output atomically. Four tests exercise a real mock HTTP
  compile/poll/download cycle plus transport, traversal, origin, and corrupt-file
  boundaries; a dedicated CI job runs them without a production credential
  ([#1297](https://github.com/sanskarpan/Latexy/issues/1297)).
- JSON Resume is now a pinned v1.0.0 interchange adapter around the richer
  guided-builder model. The upload path maps structured contact, work,
  education, project, skill, certificate, award, language, interest, date,
  technology, section-order, and visibility data directly instead of flattening
  it through generic text. Unrepresentable standard sections and extra profiles
  generate visible loss warnings. Builder export uses the authoritative stored
  structure, omits empty formatted fields, and returns 422 for dates that cannot
  satisfy the pinned schema rather than emitting falsely valid JSON. Eight
  adapter tests and a broader 108-test backend slice pass; a generated fixture
  validates against the official Draft 4 v1.0.0 schema, and all five builder
  browser scenarios pass without retries. This pass also corrected the stale
  audit claim that v1.0.0 was Draft 7 and that the archived standalone repos
  meant abandonment: current development moved to the official monorepo
  ([#1298](https://github.com/sanskarpan/Latexy/issues/1298)).
- Career gap analysis now uses ESCO v1.2.1 as a conservative, versioned skill
  identity layer. Exact preferred/alternative-label matches compare by canonical
  URI, while unrelated search hits never relabel a skill and provider outages
  retain case-insensitive free-text behavior. Analyses persist taxonomy version,
  language, and mappings; an authenticated endpoint exposes discovery across all
  28 supported languages, and the UI shows attribution plus inspectable concept
  links. Forty-one focused backend tests pass, the real API returned a valid exact
  Python match, migration 0040 completed an upgrade/downgrade/upgrade round trip,
  and all 54 affected browser scenarios pass without retries
  ([#1299](https://github.com/sanskarpan/Latexy/issues/1299)).
- A complete 459-scenario browser pass found two regressions after earlier
  remediation: the public share viewer no longer exposed its view-only state,
  and the legal-page test still expected the superseded “Information We Collect”
  heading after the policy was made more accurate. The share header again labels
  the document “View only”; the legal assertion now targets the rendered
  “Information we process” heading. Both failures and their full affected suites
  are included in the 54-scenario retry-free pass above.
- The symbol-palette backlog entry was stale: Studio already carried a wired
  palette, but it had no direct regression tests and its controls relied on
  visual Unicode/title text for meaning. The audited palette has 186 unique
  commands across all eight advertised categories; search now has an accessible
  name, category selection exposes pressed state, and symbol buttons name both
  command and package requirement. Three catalog tests and two real-Monaco
  browser scenarios prove filtering, package provenance, and insertion at the
  current cursor; all 20 combined editor scenarios pass without retries
  ([#1300](https://github.com/sanskarpan/Latexy/issues/1300)).
- Zotero and Mendeley imports now persist explicit read-only snapshot provenance
  and materialize a bounded `references.bib` sidecar in direct, Celery, and Modal
  compile paths. Studio presents provider libraries as manual-refresh snapshots,
  permits cite-key insertion and download, and removes the invalid whole-library
  `.tex` insertion action. Mendeley pagination validates every continuation URL
  before reusing its bearer credential, closing a cross-origin token-exfiltration
  boundary. All 254 focused API/worker/orchestrator tests and 21 combined editor
  browser scenarios pass without retries. The Playwright server probe now warms
  the editor route with a cold-cache allowance, after measurement showed the old
  root-only 60-second probe could expire before Turbopack compiled the first test
  route ([#1301](https://github.com/sanskarpan/Latexy/issues/1301)).
- Natural-language LaTeX generation is now a separate creation workflow rather
  than an overloaded rewrite action. An authenticated, quota-aware endpoint
  produces bounded insertable fragments, discards malformed cached/provider
  output, and rejects full documents, preamble/file-loading commands, unsafe
  primitives, and structurally unbalanced LaTeX. Studio previews the fragment
  and leaves Monaco untouched until explicit insert-at-cursor approval. Eighty-six
  focused backend regressions, 702 frontend unit tests, strict frontend checks,
  and all 18 writing-assistant browser scenarios pass without retries
  ([#1344](https://github.com/sanskarpan/Latexy/issues/1344)).
- Table generation now accepts pasted CSV/TSV through a deterministic converter
  and bounded PNG/JPEG/WebP uploads through a vision transcription path. The
  latter strips image metadata, asks the model only for a JSON cell matrix, and
  renders the final package-free `table`/`tabular` fragment in trusted code.
  Both paths enforce row/column/cell limits, normalize ragged rows, infer numeric
  alignment, escape LaTeX metacharacters, preview before insertion, and preserve
  the document on failure. Fourteen focused tests include a real `pdflatex`
  compile; the combined 77-test backend slice, 702 frontend units, strict static
  checks, and all 20 generator browser scenarios pass without retries
  ([#1345](https://github.com/sanskarpan/Latexy/issues/1345)).
- Math generation now accepts text descriptions and bounded, metadata-stripped
  PNG/JPEG/WebP transcription input. Provider output is a raw JSON math body;
  trusted code normalizes model-added wrappers, applies inline/display/equation
  mode, rejects unsafe or structurally invalid LaTeX, and leaves the editor
  untouched until explicit preview approval. Ninety-three focused backend tests
  include real `pdflatex` compilation in every mode; 702 frontend units, strict
  checks, and all 22 generator browser scenarios pass without retries
  ([#1346](https://github.com/sanskarpan/Latexy/issues/1346)).
- Citation checking now audits pasted BibTeX or the saved read-only library
  against canonical DOI/arXiv records and Crossref search. Its bounded,
  brace-aware parser does not evaluate TeX, ignores non-work directives, caps
  each batch at 20, preserves result order, and reports title/year/author
  discrepancies separately from missing records and provider failures. All 63
  focused reference/parser/budget tests, 702 frontend units, strict checks, and
  all 22 affected editor browser scenarios pass without retries
  ([#1347](https://github.com/sanskarpan/Latexy/issues/1347)).
- The Writing Assistant now exposes five explicit rewrite intents—Paraphrase,
  Concise, Scientific, Split sentences, and Join sentences—with separate cache
  identities and fact-preserving prompts. Tone values are allowlisted, Quantify
  no longer asks the model to invent plausible metrics, and cached/fresh output
  must pass the shared LaTeX safety and structure gate before preview; rejected
  paid output refunds its allowance. All 122 focused rewrite/BYOK/sandbox tests,
  strict frontend checks, and all 23 writing-assistant browser scenarios pass
  without retries ([#1348](https://github.com/sanskarpan/Latexy/issues/1348)).
- Synonyms now live as a discrete, context-sensitive action inside the
  selection-scoped assistant. The API accepts only bounded word/phrase input,
  requires structured output, deduplicates suggestions, rejects the original
  and command-like values, and uses existing metering/cache/refund controls.
  Monaco changes only after the user picks a replacement. All 138 focused
  synonym/rewrite/BYOK/sandbox tests, 702 frontend units, strict non-incremental
  checks, and all 24 assistant browser scenarios pass without retries
  ([#1349](https://github.com/sanskarpan/Latexy/issues/1349)).
- Interview prep now conducts a text-only practice session in Coach mode
  (per-answer feedback) or Mock mode (feedback only after completion). Answers
  are transient and never persisted; the evaluator checks ownership and bounded
  ordered input/output, grounds feedback in the generated question rubric,
  forbids hiring predictions, and refunds malformed provider output. Studio
  states the no-storage/no-microphone/no-camera boundary before the session.
  All 71 focused interview/worker/BYOK tests, 702 frontend units, strict
  non-incremental checks, and all 24 affected editor browser scenarios pass
  without retries ([#1350](https://github.com/sanskarpan/Latexy/issues/1350)).
- The required language-server evaluation recommends texlab, not Typst-only
  tinymist, behind a future authenticated and tenant-isolated workspace service.
  A checked-in dependency-free stdio spike proves command/label/citation
  completion, symbols, and advertised hover support against texlab 5.26.0; the
  architecture record defines URI isolation, process limits, reconnect,
  version-pinning, load, and canary gates before production adoption
  ([#1394](https://github.com/sanskarpan/Latexy/issues/1394)).
- Monaco autocomplete now covers commands, common natbib/biblatex citation
  forms, hyperref/cleveref reference forms, local labels, inline bibliography
  entries, and the saved read-only `references.bib`. Multi-cites complete only
  the active key, library changes flow into the provider live, and global
  language providers survive editor remounts. Six parser regressions and a real
  Monaco suggestion-widget scenario—including an unmount/remount—pass; all 708
  frontend units, strict non-incremental checks, and all 25 affected editor
  browser scenarios also pass without retries
  ([#1351](https://github.com/sanskarpan/Latexy/issues/1351)).
- Continuous background compilation was present but could be a no-op because
  its mount-only effect ran before dynamic Monaco initialization; its listener
  now binds in Monaco's actual mount callback and is cleaned up with that
  instance. The arbitrary 100-character edit threshold is gone, all four
  auto-compile controls announce pressed state, and a browser regression proves
  an exact short document is submitted after the two-second debounce
  ([#1352](https://github.com/sanskarpan/Latexy/issues/1352)).
- The document outline now parses the complete part-to-subparagraph hierarchy,
  starred/optional/multiline/nested titles, and exact source positions while
  excluding comments and literal code environments. It is an accessible,
  collapsible navigation region on desktop and mobile and moves Monaco to the
  chosen line. Five parser regressions plus a responsive real-browser navigation
  scenario pass ([#1353](https://github.com/sanskarpan/Latexy/issues/1353)).
- Monaco code folding now uses deterministic tested ranges for properly nested
  environments and section bodies. It excludes comments, ignores command-like
  text inside verbatim/listing/minted blocks, rejects mismatched closes, removes
  duplicate ranges, and survives editor remounts. Four parser regressions and a
  real-browser fold/unfold action check pass
  ([#1354](https://github.com/sanskarpan/Latexy/issues/1354)).
- Word count now measures Unicode-aware lexical tokens in the last compiled
  PDF's extracted text rather than misleading LaTeX source tokens. Four focused
  tests cover punctuation, compounds, marks, numbers, and empty output; the
  REST-reconciled compiled-text browser path verifies the rendered count in the
  editor status bar ([#1355](https://github.com/sanskarpan/Latexy/issues/1355)).
- Stop-on-first-error is now a strict, default-on per-resume compile setting
  propagated through direct and combined job dispatch into local/Docker TeX
  commands. Disabling it removes only `-halt-on-error`, retaining nonstop mode
  and all sandbox controls so users can collect more diagnostics safely. The
  settings dialog is now accessible and scrollable within short viewports; 146
  focused backend tests and a real browser persistence check pass
  ([#1356](https://github.com/sanskarpan/Latexy/issues/1356)).
- Draft mode is now a strict, default-off per-resume setting that injects a
  trusted, idempotent `graphicx` draft option only into transient compile input,
  preserving image layout boxes without storing mutated source. It propagates
  through direct/combined and local/Docker compile paths, recognizes existing
  draft configuration, and is covered by persistence, injection, and a real
  `pdflatex` missing-image success regression
  ([#1357](https://github.com/sanskarpan/Latexy/issues/1357)).
- Personal spell dictionaries are now normalized, bounded account preferences
  with offline/local fallback and merge-on-sign-in behavior. Editor markers
  react immediately to add/remove events, and Settings provides an accessible
  management surface. Four pure frontend regressions, 15 backend schema and
  authenticated persistence tests, strict frontend checks, and a browser flow
  covering device merge, removal, and addition pass
  ([#1358](https://github.com/sanskarpan/Latexy/issues/1358)).
- Multi-cursor behavior is now an explicit Monaco contract (Option/Alt-click,
  spread paste) and the shortcut guide documents cursor and matching-selection
  controls. A real Monaco browser regression creates two selections with the
  select-next action and verifies the active configuration without retries
  ([#1359](https://github.com/sanskarpan/Latexy/issues/1359)).
- Standard, Vim, and Emacs keybinding modes are selectable and persistent in
  every LaTeX editor, with lazy adapter loading and race-safe teardown across
  switches/remounts. A reproducible pnpm patch moves the legacy Emacs adapter
  from Monaco's non-bundleable AMD entry point to its ESM API. Unit contracts,
  strict checks, real Vim/Emacs keystrokes, and an optimized Node 22 build pass
  ([#1360](https://github.com/sanskarpan/Latexy/issues/1360)).
- Rich hovers now safely render math through pinned KaTeX, describe graphics
  honestly within the current single-source asset boundary, and resolve saved
  BibTeX metadata for multi-cites. Parsing excludes comments/literal blocks and
  malformed math pairs; work is debounced, the native textual hover remains for
  keyboard access, and six parser tests plus a real visual/keyboard browser flow
  pass ([#1361](https://github.com/sanskarpan/Latexy/issues/1361)).
- The duplicate thesaurus entry is formally fulfilled by the already-shipped,
  measured B18.6 contextual Synonyms workflow rather than maintained as a
  second competing surface ([#1362](https://github.com/sanskarpan/Latexy/issues/1362)).
- Presentation documents now have keyboard-accessible, bounded slide navigation
  over the compiled artifact. A three-page mocked compile/download browser flow
  verifies buttons, Home, and End while resume-only ATS behavior stays excluded
  ([#1363](https://github.com/sanskarpan/Latexy/issues/1363)).
- Regex find/replace now uses Monaco 0.55's correct public action identifier;
  the accessible preset bridge and native capture-group replacement are proven
  in a real two-match source transformation ([#1364](https://github.com/sanskarpan/Latexy/issues/1364)).
- The post-handoff package manager is confirmed as the in-app documentation
  lookup surface, with searchable purpose, usage, examples, notes, conflicts,
  and related packages beside installation controls. Missing accessible control
  names were repaired and the workflow passes in-browser
  ([#1365](https://github.com/sanskarpan/Latexy/issues/1365)).
- Institutional tenancy is now an active, privacy-scoped workflow: only
  DNS-proven custom domains route or receive credentialed CORS, branding is
  visible, invitations are expiring/single-use/email-bound, cohort students see
  only their explicit submissions, and all current/future tenant admins receive
  review access with removal cleanup. Started/opened/downloaded milestones,
  notes, authenticated PDF delivery, generic OIDC with PKCE, and LDAP-through-
  broker deployment guidance are covered by backend and browser regressions.
  The Razorpay Route revenue-share portion remains explicitly pending merchant
  enablement, linked-account KYC, commission/refund policy, and tenant checkout
  attribution rather than being represented as shipped
  ([#1319](https://github.com/sanskarpan/Latexy/issues/1319),
  [#1370](https://github.com/sanskarpan/Latexy/issues/1370),
  [#1371](https://github.com/sanskarpan/Latexy/issues/1371)).
- Guided-builder input now rejects unknown structured fields and type coercion
  with stable paths instead of silently discarding data or surfacing an internal
  500. JSON Resume syntax and semantic errors carry exact source line/column
  into a persistent import error panel, and malformed JSON can no longer be
  reclassified as permissive YAML. The focused backend suite and real Chromium
  upload workflow pass ([#1320](https://github.com/sanskarpan/Latexy/issues/1320)).
- Builder variants now retain one structured master rather than duplicating
  content. Each child stores only section, entry, and occurrence-safe list-item
  visibility; master edits regenerate linked children and prune selectors that
  no longer identify the same source item. The advanced editor is read-only
  until explicit detachment, including title/autosave and external-sync paths.
  Twenty-eight focused backend tests and a real Chromium workflow cover source
  propagation, duplicate bullets, reorder safety, detachment, and metadata-only
  saves ([#1321](https://github.com/sanskarpan/Latexy/issues/1321)).
- Page overflow now offers a formatting-only auto-fit before destructive AI
  trimming. One authenticated, owned-resume job tries bounded spacing/margin/
  font profiles in isolated compiler sandboxes, applies only a compiled one-page
  result, keeps the body byte-for-byte intact, and stops at a legible floor when
  content genuinely cannot fit. A strength slider supports explicit control;
  stale editor buffers are never overwritten and candidate compiles do not
  create version-history noise. Two hundred fifty focused compiler,
  quota, sandbox, and dispatch tests pass, including a real two-page-to-one-page
  TeX probe, plus a real Chromium apply/autosave journey
  ([#1322](https://github.com/sanskarpan/Latexy/issues/1322)).
- Achievement writing now includes a cached phrase library indexed by job title,
  seniority, industry, and skill category. Each request returns 8–12 unique
  suggestions tagged for high impact, ATS friendliness, leadership, and/or
  technical depth. Both this library and the existing bullet generator preserve
  user-evidenced metrics while replacing unsupported numeric claims with literal
  `[X]` placeholders, including unsafe legacy cache entries. Seventy-four focused
  backend tests, strict frontend type/lint checks, and a real Chromium
  browse/insert/autosave workflow pass
  ([#1323](https://github.com/sanskarpan/Latexy/issues/1323)).
- Cover letters now support typed, pointer-drawn, and PNG/JPEG/WebP-uploaded
  signatures with replace/remove controls. Typed names are LaTeX-escaped; image
  signatures are resized client-side, carried in reversible source markers,
  decoded and normalized without metadata on the backend, rejected before quota
  charging when malformed, and written only into the isolated compiler working
  directory. Fifty-eight focused backend job/service tests pass, including a real
  pdfLaTeX image compile; three frontend utility tests and all 56 cover-letter
  Chromium scenarios pass, including type, draw, upload, persistence, compile,
  and removal ([#1324](https://github.com/sanskarpan/Latexy/issues/1324)).
- The existing dark-PDF implementation is now verified against a real PDF.js
  render rather than only a synthetic localStorage assertion. Its accessible
  toggle filters the rendered page layer without mutating downloads or heatmap
  overlays, and the preference survives reload. The focused Chromium workflow
  passes ([#1325](https://github.com/sanskarpan/Latexy/issues/1325)).
- The ATS score card now closes the score-to-action loop: its current warnings
  and recommendations become explicit, fact-preserving optimizer instructions,
  and the resulting draft automatically opens the existing per-change
  accept/reject/edit review. Applying accepted changes recompiles but does not
  silently save. A streamed draft is now correctly recognized as the expected
  review candidate rather than misclassified as a conflicting manual edit; true
  intervening edits remain protected. Ten focused client tests and both the
  legacy selective-review journey and new score-to-review Chromium journey pass
  ([#1326](https://github.com/sanskarpan/Latexy/issues/1326)).
- ATS results now have explicit Global, India, US, and UK locale overlays. India
  does not penalize photo, date-of-birth, marital-status, or expected-salary
  fields, while US/UK profiles surface and penalize those fields with exact
  recommendations; the global option preserves previous role-only behavior.
  The score card also publishes **80 or higher** as Latexy's good document-check
  threshold, shows what the result was calibrated against, and states that it
  does not predict ATS passage or hiring outcomes. One hundred fifty focused
  scoring, route, and worker tests plus the real score-card locale/review browser
  journey pass ([#1327](https://github.com/sanskarpan/Latexy/issues/1327),
  [#1372](https://github.com/sanskarpan/Latexy/issues/1372),
  [#1373](https://github.com/sanskarpan/Latexy/issues/1373)).

### Tracker, review-only parsing, and outreach scope

- B46 tracker depth is implemented as a user-owned workflow: saved jobs and
  conversion to applications, recurring reminders for user-supplied search
  URLs, due application reminders, stale-application prompts, interview
  records with downloadable ICS, and company/contact records. Notification
  delivery claims one row immediately before provider I/O, recovers stale
  claims, commits each row independently, and supplies stable provider
  idempotency keys where supported. The search-alert message explicitly does
  not claim that Latexy scraped or found new jobs. Celery Beat and a configured
  five-minute Modal scheduled entry are code paths; this ledger does not claim
  a production deployment.
- B47 is deliberately narrow and review-only: the authenticated
  `/tracker/email-status/parse` endpoint accepts one bounded, user-pasted RFC 5322
  message and returns conservative status/company/role suggestions with
  evidence and `requires_review=true`. It has no mailbox access, tracker-row
  mutation, or sending behavior.
- B48a returns one transient, editable/copy-only outreach or referral draft
  from an owned application and optional user-supplied contact. The response
  is `sent=false`; the endpoint does not persist or send the draft. B48b is an
  explicit scope boundary: Latexy does not look up or scrape recruiters or
  hiring managers, and contacts must come from the user.
- B49 remains a telemetry limitation, not employer insight. The stale-
  application view is framed as “since your last update,” not an
  employer-response signal. Existing
  workspace opened/downloaded milestones are explicitly labeled
  `candidate_self`; they do not mean an employer or ATS viewed/downloaded a
  résumé. Latexy has no employer-side rejection, ghosting, application-view,
  or resume-download feed, and no candidate-side signal is exposed to a hirer.

### Concurrency, invitation, and artifact-boundary hardening

- Quota consumption now rejects and rolls back over-limit increments inside the
  same Redis Lua transaction. Refunds are receipt-idempotent and clamp at zero,
  and consumption repairs legacy counters that were left without a TTL by the
  former two-command implementation. Route-level quota tests stub worker
  dispatch so a live local Celery worker cannot race the assertion by refunding
  an intentionally failed test compile.
- Team seat caps and tenant provisioning/member caps are serialized by row
  locks; concurrent uniqueness races return stable conflicts instead of leaking
  database errors. Workspace member invites and résumé submissions likewise map
  database-enforced duplicate races to `409`.
- Team invitation links are now read-only on `GET`. An authenticated user sees
  a preview and must explicitly confirm a same-origin or bearer-authenticated
  `POST`; acceptance is email-bound, row-locked, and safe on retained-token
  replay. The billing page exposes the confirmation and retry states.
- Every local compiled-artifact fallback now validates the server job UUID before
  constructing a path. PDF selection for application/export/workspace flows is
  owner-scoped, artifact download/log/SyncTeX authorization fails closed when
  Redis ownership metadata is absent, malformed, or unavailable, and local log
  reads retain only the configured bounded transcript.
- Cohort résumé downloads now enforce the same viewer privacy boundary as the
  cohort submission list. A tenant-backed cohort viewer can download their own
  submitted résumé, but a guessed classmate résumé ID is indistinguishable from
  a missing submission.
- Lifetime-payment failure events can no longer revoke an order that a captured
  event already activated, student-verification checkout creation is serialized,
  and weekly plans reject coupons whose discounted amount cannot be reconciled
  safely. Razorpay webhook replay protection distinguishes a short-lived
  `processing` claim from the 24-hour `done` marker: concurrent delivery is
  retried, explicit handling failure releases the claim, and only a successful
  handler promotes the event to completed.

### Request integrity and read-only HTTP behavior

- Unsafe cookie-authenticated backend requests now require a trusted `Origin`
  (or, only when `Origin` is absent, a trusted `Referer`). Trusted deployment and
  verified tenant origins are accepted; strict bearer-authenticated and
  cookie-less webhook requests retain their non-browser contracts. Basic or an
  arbitrary `Authorization` value cannot bypass the check, and CORS still wraps
  the rejection response.
- `GET /jobs/{id}/result` is read-only again. Result retrieval no longer performs
  database reconciliation or any other write as a side effect; worker-owned
  completion paths retain responsibility for state reconciliation.
- The personal analytics timeseries endpoint now uses the same `analytics`
  entitlement dependency as the rest of the richer analytics surface; disabling
  that feature for a plan returns the standard `feature_disabled` response
  instead of leaving one ungated read path.

### Realtime transport boundaries

- A presented invalid or expired jobs-WebSocket ticket is rejected before the
  upgrade; the ticket-less anonymous trial contract remains limited by the
  existing per-job ownership metadata check. Jobs frames are capped at 64 KiB
  before JSON parsing, malformed and oversized frames count toward the connection
  rate limit, and non-object JSON receives a stable error without terminating the
  socket.
- The per-connection limiter retains at most its configured one-second allowance
  rather than appending every rejected timestamp. Uvicorn entrypoints now apply a
  512 KiB transport allocation ceiling, above the collaboration protocol's 256
  KiB application limit; Modal's managed ASGI ingress retains the application
  limits because it does not expose Uvicorn flags.

### Deployment and external-I/O reproducibility

- Python 3.12 production and development dependencies now use canonical hashed
  lock files. Docker, Modal, local setup, and CI install those locks with hash
  enforcement, while CI regenerates and diffs them to catch stale inputs.
- The frontend package manager is pinned consistently to pnpm 10.10.0 across the
  root contract, Docker images, and GitHub workflows. Vercel certification waits
  for main CI and verifies a public, no-store deployment identity against the
  exact 40-character commit SHA.
- Compiler subprocess streams, compile logs, external reference responses, and
  compiled PDFs are byte-bounded. Docker cleanup targets the exact named
  container, capture failures reap local subprocesses, and unsupported stream
  objects fail before they can be consumed through an unbounded fallback.
- PDF text extraction and auxiliary compiler reads now preserve those limits all
  the way through external converters and pdfminer. `pdftotext` stdout is drained
  through a 4 MiB cap with timeout/overflow termination and guaranteed reaping;
  the pdfminer sink aborts before retaining more than the same cap. Poppler and
  template-compiler diagnostics that are not consumed are sent directly to the
  null device rather than accumulated in memory.

### Frontend asynchronous ownership

- Format conversion and job-management hooks use generation guards so stale
  requests cannot overwrite a new job or a newly selected format; detached old
  jobs are cleared and unmounts invalidate pending work.
- Tenant invitation acceptance tracks both token and generation, so React
  StrictMode, token changes, and late promise resolution cannot double-claim an
  invitation or replace the state for a newer token.
- Contact formatting and date standardization use generation ownership too;
  closing, changing format, or starting a newer request invalidates late results.
  Their dialogs now provide modal semantics, focus containment/restoration,
  Escape handling, labeled controls, and safe button types. The compiler picker
  exposes menu semantics with arrow, Home/End, and Escape keyboard behavior, and
  shared loading indicators announce status to assistive technology.
- OAuth handoffs accept only the exact configured HTTPS provider endpoints. The
  shared validator rejects credentials, non-default ports, look-alike hosts, and
  unexpected paths before top-level navigation. Reference-import popup replies
  still require the expected window and origin, and the popup capability is
  consumed after the first accepted message so it cannot be replayed.
- Builder-import preview ownership now covers replacement files, Back/reset,
  and unmount. Deferred success, failure, and settled callbacks first prove that
  their request generation is still current, so an older parse cannot reopen the
  preview step or clear a newer request's loading state.
- PWA reconnection no longer performs next-pwa's unconditional online reload.
  This leaves the editor's owner-scoped draft and queued-compile recovery in
  control of reconnection instead of risking a reload while that flush is active.
- Workspace and recruiter PDF downloads use the shared delayed Blob-URL release
  path. Firefox and Safari therefore have time to consume the URL after the
  synthetic anchor click, while the one-second timer still bounds its lifetime.

### Migration integrity

- The admin-control-plane downgrade no longer deletes shared feature-flag rows
  that its conflict-tolerant upgrade cannot prove it created. The mapped `User`
  model also includes migration 0047's non-null `two_factor_enabled` column.
  A disposable PostgreSQL database upgraded from base through revision 0056 and
  model/table inspection found every application table and column present.

### Current API inventory reconciliation

- Recomputed 2026-09-26 from `backend/app.main:app.openapi()`: **322 HTTP
  paths / 377 OpenAPI operations**, plus `/ws/jobs` and
  `/ws/collab/{resume_id}`. The application inventory records older static
  totals as historical context rather than the current mounted contract count.

## Candidates still requiring current-source verification

- TUI model/provider config fields are reserved for the later free-text agent-mode
  phase; do not route résumé optimization through them without a new requirement.
- Additional TUI headless commands are a product-scope decision, not a verified
  defect in the documented compile/optimize/ATS/status/list contract.
- Continue current-source checks across backend correctness/security, frontend
  error handling and offline behavior, workflow/deployment contracts, and PRD
  feature reachability. Historical audit findings are regression ideas, not proof.

## Environment-limited checks

- Revalidated 2026-09-26 with Node 22 through `mise`: repository-wide frontend
  ESLint and strict TypeScript pass, and all 128 Vitest files / 872 tests pass.
- The complete backend gate collected the current suite against only
  `latexy_test` and isolated Redis DBs: 3,752 passed, 3 skipped, and one
  catastrophic-regex wall-clock assertion measured 1.09 seconds against a
  1.0-second threshold. Four of five immediate isolated reruns passed. The
  engine still enforces its 250 ms operation timeout; the test now allows two
  seconds for process scheduling during a saturated full gate and passes ten
  consecutive isolated runs. Full backend Ruff passes.
- The current TUI evidence is: frozen install, typecheck, and production bundle
  clean; the exact aggregate test command passes 37 files / 224 tests with 66
  explicitly skipped scenarios.
- A real anonymous Studio compile was rerun after the terminal-event recovery
  fix and again after the resource-boundary work. The latter completed in 27.9
  seconds as job `a958a980-4fa2-4c4c-86f9-6a988000a958` with a 15,128-byte PDF;
  `/download/{job_id}` began with a valid `%PDF-1.7` header. The browser also
  rendered the one-page PDF text with the `Compiled` status. This specifically
  closes the reproduced state where the job completed but the preview remained
  on its placeholder.
- The mocked Playwright inventory now discovers 548 tests across 54 files. A
  full cold run did not reach assertions for seven editor-heavy cases because
  Next 15 Turbopack panicked in `aggregation_update.rs`; isolated Webpack cold
  compilation of the editor graph also took more than five minutes. Treat that
  run as harness-infrastructure evidence, not seven product failures. The
  browser harness is isolated from the working tree and constrained to a
  single Webpack worker so it cannot corrupt `.next`, `next-env.d.ts`, or
  `tsconfig.json` while a developer server is running.
- The isolated harness now copies no `.env*` files, defaults HTTP/WebSocket API
  traffic to unused fail-closed ports, terminates and cleans its child runtime,
  and has an explicit reuse path for the prestarted full-stack smoke. That real
  smoke was rerun successfully in 2.6 minutes, as do all 58 scenarios in the three files that previously
  surfaced only cold-navigation failures (academic publications, admin feature
  flags, and ATS quick scoring) against the warmed local stack.
- Cold editor compilation is slow rather than deadlocked. An isolated Webpack
  probe compiled the `/try` graph's 5,124 modules in 119.8 seconds and then
  rendered successfully; the main development server also eventually completed
  the route and subsequently served warm `/` and `/try` requests in 4.1 and 6.4
  seconds. This reproduces the cost outside Turbopack and points to the large
  module graph plus concurrent local CPU/memory pressure, not a route-render
  deadlock.
- The first isolated production-browser pass also exposed two harness/layout
  issues before it was deliberately stopped at 55/548 cases. The optimize route
  emitted a hydration error while using an inner `main` beneath the root layout's
  `main`; that nested landmark is removed. Monaco behavior assertions depended
  on a development-only test hook even though the harness was running a
  production bundle; the disposable launcher now enables that hook through an
  explicit test-build-only public flag while ordinary production builds retain
  the guard. A clean production rerun remains the completion gate.
- Authenticated browser workflows now use a real local account and cover every
  authenticated route plus compile, ATS, PDF, SyncTeX, sharing, and revocation.
- GitHub publication and production certification are intentionally deferred at
  the owner's request until the local remediation pass is complete.

## 2026-10-04 continuation — current evidence and open work

This section supersedes older gate counts above. Historical passes are not proof
that the current dirty working tree passes; publication remains deferred.

- [x] Current frontend unit gate: 146 files / 924 tests passed, including deferred
  page-hook ownership checks. Repository-wide ESLint and strict TypeScript pass
  after the browser-harness fixes. Earlier counts above are historical.
- [x] TUI rerun: 37 passing files / 224 passing tests, 7 skipped files / 66
  skipped scenarios; typecheck and production bundle passed. The skipped
  scenarios are not counted as integration acceptance.
- [x] Browser extension: 4 passing tests; syntax and least-privilege package
  checks passed.
- [x] Real host-engine smoke (not a worker/browser integration substitute):
  pdfLaTeX, XeLaTeX, and LuaLaTeX each compiled a fresh fixed minimal document
  with no shell escape and recorder enabled. All exited zero, produced PDFs
  (14,504 / 3,994 / 4,334 bytes respectively), and passed recorder confinement.
  Reproduction artifacts are local-only in `/tmp/latexy-engine-probe.qXd90t`.
- [ ] Local dispatch isolation: pytest forces `ENVIRONMENT=test` and
  `DEPLOY_TARGET=local`; local dev/smoke launchers now force local dispatch too,
  so a production-oriented `.env` cannot silently enqueue remote Modal work.
  Shell syntax/Ruff pass; subprocess regression probes await the backend gate.
  Local auth precedence was also inconsistent: Next read the root `.env`, while
  FastAPI preferred `backend/.env` (the current values differ; no values were
  logged). The dev launcher now resolves dotenv quoting and backend/root/process
  precedence once and passes the same secret to Uvicorn, worker, beat, and Next.
  Five isolated launcher regressions await execution; `.env` files are unchanged.
- [ ] Backend full gate: 3,866 collected; 3,770 passed, 91 failed, 5 skipped.
  Ninety failures involve subprocess doubles that lack bounded reads; investigate
  and repair the doubles or runtime defect without restoring unbounded reads.
  The remaining failure is loss of actionable ORCID-not-found feedback after
  exception redaction. Typed safe feedback is implemented, awaiting regression
  verification. XML evidence: `/tmp/latexy-backend-2026-10-04.xml` (local only).
  First rerun: 3,879 collected; 3,838 passed, 36 failed, 5 skipped.
  The bounded-stream, ORCID, and new combined-settings checks pass. Remaining
  failures: 35 malformed `Path.stat().st_mode` test doubles and one outdated
  undispatched-cleanup assertion (dispatch marker now included). These require
  fixture repair and a fresh complete backend gate, not relaxed runtime checks.
  The repaired Beamer/timing/LaTeX-worker fixtures now pass all 102 focused
  tests. The cleanup assertion is updated. Broader lifecycle changes are still
  underway, so a final complete backend rerun remains required.
- [ ] Current complete production-mode browser gate: 554 scenarios collected;
  544 passed, 2 failed, 1 flaky, 7 skipped (21.3 minutes). Invitation ownership
  scenarios passed. Remaining harness failures were premature Monaco access,
  positioning the phrase-library cursor on `begin{itemize}` instead of an item,
  and a synchronous assertion before a captured share request arrived. The
  Monaco fix passed a focused production rerun; cursor/request waits are fixed
  and all 52 focused macro/phrase/share scenarios now pass in production mode
  (2.6 minutes, no retries). Repository-wide frontend ESLint passes. A fresh
  complete production-mode rerun is underway; a clean complete gate is required.
  The seven backend-dependent skips are not full-stack acceptance.
  Latest complete rerun: 545 passed, 2 flaky, 7 skipped (17.1 minutes), no final
  failures. Both retries remain open: Google Drive completed OAuth triggered two
  status reads, and a writing-assistant error-path test observed a React 418
  hydration mismatch. Do not suppress either error or count retry success as
  proof of deterministic correctness. Google Drive now has account/session/ticket
  ownership and delayed-query-cleanup regressions. Root's further StrictMode
  replay concern and related integration account-switch/unmount races now have
  fixes and eight focused component-hook tests. Current frontend gate: 147 unit
  files / 932 tests, TypeScript, and ESLint pass. The isolated production
  Drive/writing suite passed all 84 cases over three repeats, without filtering
  hydration errors. React 418 is still not reproduced or conclusively resolved;
  latest complete production browser gate: 546 passed, one ATS debounce retry,
  seven skipped, no final failures. The ATS artifact showed fake time advancing
  before Monaco/status readiness; its harness now waits for readiness before
  clock advancement, preserving debounce assertions. That specific scenario
  passed ten isolated production repetitions (3.0 minutes). A complete clean
  post-fix gate is still required; the original writing hydration event remains
  an unreproduced observation rather than a conclusively fixed runtime defect.
- [ ] Worker signal privacy and terminal ordering: truncated task-payload repr
  retained credentials/resume prefixes in seven-day dead-letter entries, and raw
  provider exception text reached failure notifications. Signals now retain only
  structural payload summaries and safe static client errors. A failed result
  must be accepted before its failure event, with no unfenced signal refund.
  A central postrun finally also stops the matching heartbeat and clears ownership
  even when metrics/recovery fail. Eleven focused regressions pass in the expanded
  659-test gate; Ruff and compile checks pass. Existing remote dead-letter data
  was not modified. Legacy terminal results now use atomic first-writer-wins
  publication, with a real-Redis regression.
- [ ] Latest expanded backend gate: 659 passed, no failures/errors/skips;
  `/tmp/latexy-expanded-gate-signal-final.xml`. Subsequent event/lifecycle gate:
  87 passed; lifecycle-only: 13 passed. An attempted unfiltered backend run
  collected 3,944 tests but hit 3,941 async-fixture/plugin setup errors and three
  skips, before any test body passed. This is not a runtime acceptance gate;
  investigate the invocation/configuration and rerun unfiltered.
  Root-invocation cause confirmed: backend-only pytest configuration was not
  selected from the repository root. A root `pytest.ini` now applies the same
  async auto/session-loop settings, and the root-invocation subset passes.
- [ ] Fresh actual local stack: migrations/template synchronization, API health,
  local queue/cache Redis and MinIO all start successfully on 8030/5180 with
  AI/billing disabled for smoke. The new loopback-only
  `scripts/ci/local-job-smoke.py` exercises real API → Celery → Docker TeX →
  Redis result/event → PDF download without mocks or remote requests. pdfLaTeX
  passed (13,750-byte PDF). XeLaTeX initially hit its real 30-second free-plan
  timeout; Docker emitted its first engine line only near the deadline, so
  startup/resource timing needs investigation before classifying the cause.
  LuaLaTeX reached successful result and completed state; the first probe
  incorrectly asserted event state immediately after result availability and
  has been corrected to allow bounded delivery latency. Fresh probes are pending.
  Celery does not hot-reload ongoing edits: restart after final lifecycle changes
  and migrations before calling these current-code final acceptance.
  Follow-up live evidence: frontend/API full-stack smoke passed (1 test, 45.1s),
  and LuaLaTeX's corrected probe passed with a 3,897-byte PDF. XeLaTeX failed
  again; a direct sandboxed Docker invocation on a trusted fixed document also
  exceeded 120 seconds, independently of worker/refund/30-second plan limits.
  Host XeLaTeX success does not clear this Docker-engine gap.
- [ ] Health and retained legacy adapter: compiler capability probing performed
  synchronous Docker subprocess calls directly on the health request's event
  loop. It now runs in a thread with a regression asserting thread isolation.
  The retained `LaTeXCompiler.compile_latex()` methods currently have no API
  callers, but bypassed shared shell/network/recorder/environment confinement
  and accepted traversal identifiers for cleanup. These now use the shared
  controls and validate workspaces; thirteen sandbox/traversal regressions,
  sandbox/privacy/basic-health subset passes 27 tests. Additional lifecycle,
  capability, and health-thread checks require the expanded/full backend gate.
  One successful subprocess double now writes its real required recorder fixture.
- [ ] Docker context/privacy and engine parity: backend `.dockerignore` omitted
  both dotenv credentials and `.venv` despite image `COPY .`; root/nested dotenv
  files and the local environment are now excluded, with eight regression checks.
  Both backend Dockerfiles also lacked an explicit XeTeX package; they now include
  `texlive-xetex`, matching Modal's existing three-engine contract. Existing
  image layers/remote artifacts were not inspected or rotated; do not claim old
  credentials are removed from historical images.
  Fontconfig debug evidence confirmed the full TeX image's caches compared
  fractional directory mtimes with OCI-extracted whole-second mtimes and rebuilt
  the font tree in every cold container. New `Dockerfile.tex-engine` normalizes
  font-directory timestamps and warms caches without application build context.
  Its local build passed (231.6s), and extracted cache mtimes now match. First
  warmed XeTeX probe still exceeded 30s; a repeated sandboxed invocation passed
  in 16.12s. This is improvement, not yet deterministic cold/live-worker proof.
  The local launcher selects/builds this credential-free sandbox; real worker
  probes after restart remain required before closing the XeTeX gap.
  A fresh host-bounded sandboxed XeTeX invocation passed in 12.38 seconds.
  Additional real-template testing found that the upstream sandbox lacks
  `Lohit Devanagari`: the shipped Hindi template failed with a real fontspec
  missing-font error (22.02s), despite the three engine commands existing.
  The sandbox now installs the same Lohit/Noto system fonts as application
  images and warms Lua's font lookup database. The launcher checks a Dockerfile
  source-hash label, so an old local image cannot silently outlive its source.
  Rebuild and Hindi-template acceptance were pending at that checkpoint; do not close from static
  package-name checks. Probe bounds now run on the host: the image's GNU timeout
  returned internal-error status 125 in a separate diagnostic, which is not a
  TeX compile failure or an elapsed compile timeout.
  Follow-up: multilingual sandbox rebuild succeeded (approximately 435s) with
  its Dockerfile hash matching the image label. The unchanged real Hindi template
  now compiles successfully in a fresh sandbox (11.79s, one-page 23,709-byte PDF).
  This closes the reproduced missing-font engine failure; the current API/worker
  integration still needs a restarted-worker acceptance run.
- [ ] Durable PDF persistence: verified upload failure could report completed
  with `pdf_path=NULL`. A typed persistence outcome now separates anonymous
  no-row jobs, durable success, and storage failure; canonical success must not
  be published for storage failure. Before/after Redis ownership checks do not
  close the DB commit/cancel race. A DB finalization arbiter is being implemented
  to linearize commit/cancel/cleanup and atomically apply generated resume content
  with durable PDF/Compilation success. It requires migration and real DB race
  tests; do not mark complete from a row lock or isolated storage mock alone.
  Migration 0057 applied successfully to the local application database only;
  no deployment was made. Eighteen real PostgreSQL arbiter tests and 22 artifact/
  share checks pass. Review caught and repaired payload-overflow validation after
  output mutation; it now fails before Resume/CoverLetter/Compilation changes.
  Main integration remains under review: lock order, DB commit before Redis refund,
  all job types, loop-safe worker DB sessions, retry/heartbeat leases, and committed
  success replay need end-to-end gates. An independent fresh agent is auditing
  the integrated implementation; helper-only passes do not close this item.
- [ ] Quota receipts must survive broker acceptance and failed refunds until a
  confirmed terminal outcome; stale processing and pre-dispatch queued work
  need exactly-once recovery without refunding live work.
  Independent review additionally requires an age grace period for fresh
  receipts, protection against dispatch/result TTL expiry masquerading as an
  undispatched job, and an explicit policy for ambiguous broker-call crashes.
- [ ] Standalone LLM dispatch needs durable crash-window recovery even without
  a Compilation row. Batch-tailor work needs per-job receipts, recovery records,
  and failed/cancelled-worker refunds instead of an untraceable aggregate charge.
  A queue-side lifecycle/lease implementation is under independent review.
  Review found expired-owner terminal writes, retry resurrection of fenced work,
  rejected success clearing receipts, missing failure results, retry admission,
  initialization-failure recovery, and GitHub-import `ai_assists` recovery gaps.
  These remain open until fixes and real-Redis race tests pass.
- [ ] Expanded metering inventory: cover-letter generation, document conversion,
  and deep ATS consume quota without a durable job-scoped receipt or worker
  refund payload. Ordinary enqueue failures are covered, but provider failures,
  cancellation, and worker crashes after dispatch are not. Carry the same
  lifecycle protocol through these paths and Modal signatures; verify each.
- [ ] Synchronous metering recovery: AI helpers, direct compile/optimize, career
  analysis, URL import, interview simulation, and outreach need cancellation/
  crash-window verification. Most `except Exception` handlers do not catch
  `asyncio.CancelledError`; outreach has explicit shielded compensation.
  Durable synchronous receipt/ownership semantics remain to be implemented.
- [ ] URL import must resolve BYOK before charging platform `ai_assists`; its
  documented exemption currently differs from the actual ordering. Fix and
  prove platform-fallback charging separately.
- [ ] Admission-policy review: interview-question generation and semantic/JD/
  résumé embeddings use platform keys without the above quota mechanisms.
  Confirm documented plan/budget promises before adding a new charging policy;
  unmetered provider calls alone do not justify silently changing allowances.
- [ ] Deep ATS response integrity: malformed JSON previously fabricated a
  successful 0/100 assessment. A bounded typed response now rejects non-object,
  missing, wrongly typed, non-finite, or out-of-range score payloads and publishes
  a real failure. Provider transports now close on success/error/cancellation,
  and result acceptance precedes completion events. Ruff/compile pass; dedicated
  regression tests and the new lifecycle integration await backend verification.
- [ ] Combined compilation must honor supported main-file/package/safe-flag
  settings, not silently use a different contract from direct compilation.
  Worker parity and embedded signature materialization now pass new tests;
  independent review additionally found omitted dispatch settings in batch,
  quick-tailor, and academic-CV conversion. Per-resume TeX Live version pinning
  remains explicitly unsupported in the UI, not promised compiler behavior.
- [ ] Quick-tailor and academic-CV conversion also need the job-scoped quota
  recovery protocol: current charges precede job-ID allocation and DB commits,
  dispatch omits worker refund payloads, and quick-tailor omits the resolved
  user plan. A failed DB commit can bypass the existing compensation handler.
- [ ] Team invitations: distinguish terminal acceptance errors from transient
  failures, suppress contradictory accept guidance, and reject late responses
  belonging to a previous token/account. Institutional invitations additionally
  need an explicit confirmation/retry contract review.
  Both invitation flows now have explicit confirmation, synchronous locks, and
  token/account/unmount ownership; billing student-verification responses are
  owner-scoped too. Focused tests/typecheck/lint and the complete production-mode
  mocked browser run cover these scenarios. Account/unmount races additionally
  have deferred hook-level tests; these are not live-provider acceptance.
- [ ] Finish browser keyboard/accessibility checks before making conformance
  claims; named screen-reader support still requires a manual platform matrix.
- [ ] Operator-limited acceptance remains open: Upstash capacity management,
  npm trusted publishing, production QA-account rotation, secret-validity
  scanning, PDF-UA runtime support, Razorpay Route/SKU configuration, referral
  reward policy, and remaining authenticated localization. These are not marked
  fixed merely because local automated gates pass.
  Read-only GitHub refresh: remote `main` is still `8ff2124` (August 29), with
  exact-SHA CI [33282390888](https://github.com/sanskarpan/Latexy/actions/runs/33282390888)
  and Modal deployment [33282611463](https://github.com/sanskarpan/Latexy/actions/runs/33282611463)
  passing on August 30. Those runs do not validate the current dirty tree.
  Issues #1628, #1668, #1670, #1683, #1713, and #1370 retain operator/delivery
  prerequisites; #1288 remains explicitly unsupported future PDF/UA work.

## Publication ledger

### October 4 orchestration review: additional verified integration gaps

These are local integration findings, not claims about the currently deployed
revision. Keep them open until the current worker code passes the listed gates.

Fresh frontend acceptance after the ATS harness-readiness fix:
`547 passed, 7 skipped, 0 failed`, with no retries/flakies, in isolated production
mode. Unit acceptance: 147 files/932 tests; TypeScript and zero-warning ESLint
passed. Skips require the explicit real-backend/live-search/PWA production flags,
plus one mobile-only contract skipped in the desktop project. The earlier writing
React 418 observation did not recur, but remains unreproduced/unresolved rather
than being declared fixed by a passing rerun.

The subsequent opt-in `PWA_PRODUCTION=1` gate is **not green**: 3 passed and
1 failed twice (cold offline saved-PDF restoration). Captured browser evidence
shows an unstyled replayed editor shell with no restored PDF. Service-worker
installation/precache/hydration readiness versus a runtime restoration defect
is under investigation; do not classify it as fixed or dismiss it as flaky.
Logout/account-switch privacy and the generic service-worker offline fallback
passed in this run.

Further source review identifies a real coverage/product mismatch: navigation
is intentionally NetworkOnly, so a genuine cold offline reload serves the
static fallback, which currently has no saved-PDF reader. Unregistering the
worker and fulfilling captured authenticated HTML/static assets can exercise
isolated editor restoration, but cannot certify cold offline navigation. The
frontend task is redirected to owner-scoped PDF access from the actual fallback
and genuine installed-worker acceptance, without caching private HTML, API, or
PDF responses or removing privacy assertions.

- [ ] Admission capabilities: Redis claims now assign an epoch, repairing the
  previously missing field that rejected lifecycle workers. Deep ATS's undefined
  admission `user_id` reference is removed. Real worker admission/retry tests
  remain required; every delivery must have a unique owner and retain its own
  epoch rather than adopting a later claim's mutable Redis epoch.
- [ ] Atomic typed finalization: compilation and generated resume updates must
  occur in the same database transaction as the arbiter success decision. Adding
  an arbiter call after the old output commits does not repair the crash window.
  Verify cancellation, failed storage, stale owners, changed resume snapshots,
  and process death between upload, DB commit, Redis result, and terminal event.
- [ ] Recovery coverage: consult durable decisions even for jobs without
  Compilation rows and expired Redis results; replay committed success instead
  of refunding it. Commit database fences before Redis fencing/refunds and use
  consistent arbiter → Compilation → Resume lock order.
  A read-only recovery helper now uses exact authenticated ownership, database
  expiry clocks, bounded generated payloads, and terminal-state filtering.
  Review added explicit rejection of NULL/empty owners, fenced-as-failed recovery,
  and a durable job-type discriminator instead of guessing from worker tokens.
  Migration 0058 is now applied nondestructively to both the local application
  and isolated test databases. Completed GitHub writer payloads and canonical
  Redis replay remain under integration review.
- [ ] Pre-charge intent and asynchronous coverage: cover-letter, converter,
  GitHub import, and deep ATS need database intent before quota consumption;
  ordinary async ATS scoring needs the same admission/cancellation contract.
- [ ] Clock, cancellation, and retention: use server-side clocks for dispatch
  expiry, renew database leases, release retry owners, wire retention GC, and
  preserve durable failed/fenced outcomes instead of publishing false cancels.
- [ ] Sharing repair: existing PDF paths remain unchanged on presign failures.
  Legacy NULL-path repairs now use unique owner-tokenized upload keys and a
  conditional database update. Explicit same-job concurrency with separate DB
  sessions proves one immutable winner and deletion of only the losing upload;
  bounded Redis fallback covers separate API/worker storage. The full share
  suite passes 19 tests, and the real DB arbiter suite passes 20.
- [ ] Compiler capability: Docker client installation is no longer treated as
  proof that its daemon/configured image can run. The bounded image probe uses
  the credential-minimal engine environment. The local warmed-image selection
  also respects exported/custom dotenv image settings. Fourteen new regression
  cases pass lint; backend execution and restarted-worker acceptance are pending.
- [ ] Worker integration review: the typed helper's current focused gate passes
  6 real database tests, the arbiter passes 20, and a cache subset passes 2.
  Broader worker fixtures still fail around subprocess mocks after capability
  probing changed; repair those doubles without weakening the runtime check.
  No fresh unfiltered backend acceptance or restarted-current-worker E2E has
  cleared the complete integration yet.

The subsequent quota/lifecycle integration gate passes **662/662** focused
tests, covering lifecycle/event fencing, arbiter, cleanup, quota, ATS dispatch,
cover letters, batch/quick tailoring, academic conversion, GitHub, environment,
and Docker contracts. Ruff, Python compilation, and whitespace checks pass.
This is not a replacement for the fresh unfiltered backend suite or actual
restarted-worker acceptance. Five dispatch-fixture `AsyncMock.db.add` warnings
remain to review rather than suppress.

The independent current TUI gate also passes on Node 22.23.2: strict
typecheck, the exact aggregate Vitest command (37 files/224 tests passed;
7 files/66 tests explicitly skipped), and the production CLI/MCP bundles.
Those skipped live-service scenarios are not certified by the offline gate.

Orchestrator review additionally found that typed PDF-storage/CAS failure
branches may commit a durable failure but return no canonical failure payload.
Callers then substitute a different error; the immutable FAILED-result guard
correctly refuses that different payload, potentially leaving Redis/UI recovery
pending. Return and publish the original terminal decision, test the caller
boundary, and verify failed Compilation terminalization. Cleanup replay also
needs fail-closed clock/database handling and must not refresh retained data
beyond its original deadline. These remain open integration requirements.

The loopback-only real-worker smoke script now also accepts `--fixture hindi`
to compile the unchanged shipped Hindi source with LuaLaTeX/HarfBuzz, alongside
the minimal three-engine probes. Remote origins and incompatible Hindi-engine
choices fail before any HTTP request. Restarted-worker execution is still
pending; a direct sandbox success is not proof of API/Celery integration.

An independent terminal-boundary review added the following open regressions:

- [ ] REST and WebSocket cancellation mistakenly treat the newly accepted
  durable CANCELLED decision as an already-terminal no-op, skipping the Redis
  flag/event. Verify running, queued, repeated, and unmetered cancellation,
  including a crash between DB commit and Redis publication.
- [ ] A stale worker's rejected failure may still reconcile a live replacement's
  Compilation to failed. Non-success writes need the same owner/epoch and
  accepted-terminal proof as successful writes, including combined paths.
- [ ] A storage exception after another attempt commits success must replay
  that original success, not return a false/failed helper outcome with a
  successful canonical payload. Otherwise callers can emit failure/refund
  side effects for an accepted success. Cover the blocked-upload replacement
  race at both the helper and caller boundary.
- [ ] Owner-token PDF uploads rejected after a cancellation/replacement race
  must be collected as unreferenced objects, not retained merely because some
  Compilation row with the same job ID exists. Preserve the committed winner,
  grace period, and fail-closed storage/database isolation guards.
- [ ] Durable failed/cancelled decisions need canonical transport recovery after
  a worker dies before Redis publication; timeout recovery must not substitute
  a different terminal decision.
- [ ] Existing queued/processing Redis state must not conceal a terminal DB
  decision when a process dies between result and completion-event publication.
  Public API polling now prefers the exact owner's unexpired terminal decision;
  three new DB/Redis tests cover completed, failed, and cancelled stale-cache
  snapshots. Generic and batch polling need equivalent verification.
- [ ] Synthetic cleanup tasks must not emit nonterminal progress after their
  completion. Recheck exact result/event ordering before claiming a defect.

Scoped orphan-cleanup implementation now compares exact references in both
Compilation and JobFinalization, retains ambiguous/recent/legacy objects, and
has real-DB winner/loser/finalization-only reference tests ready. Synthetic
temp-cleanup completion publishes its result first, no longer follows it with
nonterminal progress, and no longer advertises a nonexistent PDF. Static
checks pass; its isolated runtime tests still require the coordinated backend
test lease. A system-Python missing-dependency collection attempt is not a
failure of the repository's configured `.venv` and is not an accepted gate.

The next recovery-surface survey adds these open implementation requirements:

- [ ] Deep ATS durable results must retain the validated multi-dimensional
  scores and industry identity, not only the analysis text. REST recovery must
  hydrate the same deep-analysis UI state as `ats.deep_complete` when events
  are missed/expired, without inventing missing scores.
- [ ] Cover-letter successful REST recovery must apply the canonical generated
  LaTeX to the editor, not merely refresh its sidebar record. Preserve job/user
  identity guards and avoid repeated auto-compiles/output side effects.
- [ ] Partial batch dispatch must terminalize each proven never-dispatched
  durable intent before refunding it, while preserving the ambiguously attempted
  broker delivery. Live batch status must recover owned terminal jobs instead
  of defaulting missing cache state to queued. The aggregate's 24-hour expiry
  versus 40-day job retention is a contract question, not sufficient evidence
  to extend private-data retention without checking the PRD.

The genuine installed-worker offline-PDF gate now has an 8-case passing
checkpoint, plus a focused 2-case post-delta pass, with 147 frontend unit files /
934 tests, TypeScript, and ESLint passing. The fallback reads existing IndexedDB
without schema creation or data deletion, and invalidates stale owner/generation
reads. Request a fresh complete final-version PWA gate and cold repeats; the
older synthetic editor-HTML replay is not used as proof of real navigation.
Upcoming REST-recovery hook/page changes require a subsequent fresh full
frontend gate rather than relying on this earlier checkpoint.

The actual pure durable sanitizer also reproduced a deep-ATS payload defect:
`deep_analysis.sections[*].issues` and `suggestions` string arrays become
`[null]` at the existing generic depth limit. Typed sanitation must preserve
valid bounded guidance without relaxing credential/diagnostic filtering,
payload size, list-count, or depth limits for arbitrary input. The canonical
payload→REST recovery→UI integration is not closed by a reducer-only test.

The next lifecycle checkpoint reports 603 affected lifecycle tests and 48
quota tests passing. An earlier unfiltered backend run reports 3,879 passed
and 5 skipped, but precedes the latest race/recovery changes and is not the
final acceptance gate. Two cleanup clock test doubles still need correction
after the server-clock contract was tightened. Backend tests remain serialized
because their fixtures reset shared isolated test infrastructure.

Current source review still requires durable-terminal proof at the legacy
Compilation reconciliation boundary: absent worker ownership must not authorize
a failure write against a live replacement, and a Redis lease check alone is
not the database decision. Batch polling still needs durable owned terminal
recovery; proven never-dispatched partial-batch intents must be terminalized
before refund. These are open until source review and regression tests agree.

Offline PDF review also adds MIME normalization: persisted PDF-header bytes
must be served as application/pdf even if a stale/tampered IndexedDB Blob says
text/html. Test both the helper boundary and genuine offline preview, preserving
read-only fallback behavior and owner/generation isolation.

MIME normalization now passes five targeted unit tests and one genuine
production offline-browser non-execution test, with TypeScript and lint clean.
The fresh complete nine-case offline gate, cold repeats, and final aggregate
frontend suite remain pending recovery runtime freeze. Cover-letter source-string
assertions do not certify behavior: deferred compile responses, duplicate WS/REST
completion, route/account changes, and canonical job identity still need actual
browser regressions. A response for a different job must not be relabelled as
the current job's generated output.

Independent current peripheral checks pass: the browser extension's four Node
22 extraction/autofill tests and Manifest V3 package guard, and the reusable
Render CV action's four Node 24 transport/path/atomic-output tests. These are
offline package checks, not installed-extension or live GitHub action acceptance.
Current repository Ruff, whitespace, shell syntax, plaintext credential,
session-recording, and public marketing claim guards also pass.

Actual Chromium file I/O exposed another offline PDF defect: the helper awaited
Blob.text() within a read/write IndexedDB transaction, which had already
auto-committed before its later put() (InvalidStateError). It now completes the
read-only transaction before validating, then updates only the freshly read
row's LRU metadata in a separate transaction. A concurrent replacement is not
overwritten and a purged row is not reintroduced. Invalid snapshots are rejected
without deleting a possibly replaced row after asynchronous validation.
The actual repository helper plus real idb library passes three browser cases
repeated three times (9/9, zero retries), and the targeted PDF/migration unit gate
passes 9/9. Browser evidence: /tmp/latexy-offline-pdf-transactions-2026-10-04.
The initial test-loader CommonJS/import.meta mismatch was repaired before this
accepted gate; it was not an application failure. Editor-level late PDF reads,
downloads, and retry payloads still require owner/route/job identity guards.

Current ordinary backend test isolation now also forces RESEND_API_KEY empty:
local dispatch and disabled OpenAI alone did not prevent tests from inheriting
a developer's outbound email credential. The isolation subprocess test supplies
only a synthetic provider key and asserts it is disabled. Coordinated runtime
isolation/email/invitation tests remain pending. Real local acceptance must also
restart the launcher with outbound email explicitly disabled.

The subsequent complete frontend unit checkpoint passes **148 files / 942
tests**, with the current TypeScript gate and targeted offline-helper/test lint
also passing. Recovery/browser changes continue after that checkpoint; final
aggregate acceptance remains pending. Scoped editor PDF review adds late-read,
download, and pending-retry identity regressions to the active PWA agent's work.
Never carry a bare pending PDF Blob into another owner's/resume's retry, or apply
an old download after a different job/account/route has become current.

Job-list deduplication reproduced a separate privacy boundary defect in two
deferred-response tests: account/tenant switches could reuse and surface the
old context's in-flight list. The shared promise now checks a context version
after parsing; real token/tenant changes invalidate the cached in-flight list.
The affected auth/header/job-list gate passes 18 tests, TypeScript and targeted
lint pass. Same-context deduplication remains covered.

The cleanup agent's 91-test focused checkpoint is not final acceptance:
subsequent review rejected blanket retention of every durable PENDING row,
which would disable pre-dispatch/expired-worker crash recovery for jobs without
Compilation rows. A verified server-clock deadline must attempt the DB arbiter
fence first; live DB leases/BUSY decisions remain protected, and accepted
terminal decisions must be replayed before Redis fencing/refund. Tests must
distinguish an actually live DB lease from an advisory Redis lease. Review also
found that cleanup's refund dimension allowlist omitted ai_assists even though
deep ATS charges that dimension and can leave durable receipts after crashes.
Both fixes/regressions are assigned before the fresh unfiltered backend gate.

The subsequent coordinated cleanup/recovery checkpoint passes **94 tests**.
Partial-batch regression coverage now distinguishes two ambiguously attempted
broker deliveries from a third never-attempted job: the latter is durably
failed/refunded, while the former remain queued/charged for bounded recovery.
The new loopback-only authenticated worker smoke and test-isolation guards pass
**16 tests**, including refusal of remote origins, credential-bearing URLs,
mismatched cookie hostnames, and unbounded timeouts before HTTP operations.
The reusable smoke command is `scripts/ci/local-owned-job-smoke.py`; it uses
synthetic account/document data and checks exact PostgreSQL/MinIO PDF identity,
unauthenticated access denial, and cancellation. Its real runtime acceptance
remains pending; CLI safety tests are not worker acceptance.

The actual local launcher/workers were restarted with current source, the
cache-warmed TeX image, local MinIO bucket `latexy`, and explicit empty OpenAI
and Resend credentials plus disabled billing. Fresh real-worker PDFLaTeX,
minimal LuaLaTeX, and unchanged Hindi LuaLaTeX jobs passed. XeLaTeX exceeded its
free-plan 30-second compile budget in two attempts. One owned PDFLaTeX job
produced a valid PDF but exceeded the 45-second task soft limit during durable
post-processing; it was reported as `pdf_storage_failure`. MinIO access itself
is healthy. These failures are not waived as a passing gate: serial repeat and
resource/timing diagnosis remain open, and plan limits have not been raised to
hide them. Logs: `/tmp/latexy-local-app-2026-10-04.log`.

Real task-success logs also exposed the synthetic job's extracted document text
through Celery's default result representation. Existing signal/DLQ redaction
did not cover this tracer path. A real-Celery-tracer privacy regression and
narrow logging/event fix are assigned; preserve actual returned/backend results
and callbacks while excluding document/credential contents from observability.

The serial owned compile subsequently passed exact durable history/MinIO byte
and SHA-256 comparison plus anonymous result/download denial. Its cancellation
then exposed a separate verified defect: JobFinalization is CANCELLED, but the
associated Compilation remains processing because a pre-start cancelled worker
rejects admission and exits before reconciliation. Do not weaken the smoke's
history assertion. The arbiter owner must atomically reconcile cancellation
history under the existing arbiter→Compilation lock order, preserving a committed
winner and validating identity, with repeated/queued/running cancellation tests.

- [ ] Hindi template typography: real one-page worker output is visually
  legible without clipped/overlapping text, but LaTeX reports undefined Lohit
  bold/italic shapes and the PDF embeds only its regular face. Requested heading
  and role emphasis is silently lost. Review the translation helper as well as
  the shipped template; select provisioned real bold faces and an explicit
  supported italic/slant policy, then verify shaped text extraction and rendering.
  Do not call the unchanged-template compile a complete typography acceptance.

PDF visual inspection used the PDF skill and bundled Poppler on the actual
LuaLaTeX worker download, not a regenerated substitute. The PDF is untagged;
this does not certify PDF/UA or assistive-technology conformance. No user résumé
was accessed; the fixture source is repository-owned sample text.

Read-only GitHub revalidation confirms the CLI is authenticated and the remote
`Deploy Modal Backend` workflow has successful main-branch runs (latest shown:
2026-08-30, SHA `8ff2124aa21338d8a97ae60dbec1962af4921609`). In contrast,
`verify-vercel.yml` is present in this local delivery work but GitHub reports it
absent on the remote default branch. Do not confuse an implemented local guard
with a published/effective workflow. Publishing and exact-SHA deployment checks
remain deferred per the user's explicit instruction; these queries made no
remote changes.

Keep new work uncommitted during this pass. Before the eventual combined
publication, review this file against `git diff`, remove generated reports and
incremental build artifacts, split commits by file/logical concern as requested,
then run exact-SHA CI, automatic Vercel/Modal deployment, and production E2E.

Do not stage the unrelated untracked `.github/workflows/ci-cd.yml` draft. It
duplicates the canonical workflows and still assumes Node 18/npm, stale action
versions, a different test database contract, nonexistent/staging deployment
inputs, and SSH production hosts rather than the verified Vercel + Modal path.
The untracked root phase/status reports are likewise not current delivery
artifacts unless the owner separately reconciles them.

### 2026-10-04 continuation: fresh gates and remaining reproduction work

The parallel terminal-boundary agent reports 126/126 focused Celery,
cancellation, arbiter, and LaTeX tests passing, including real task tracing and
durable cancellation identity regressions. Source review confirms mismatched
Compilation identity now raises before cancellation history is mutated. Actual
long-lived worker restart and a fresh full backend run are still required after
the owned PDF route changes freeze; this checkpoint is not full-stack acceptance.

Deep ATS missed-WebSocket REST recovery passes a fresh isolated production
browser check (1 test). Focused stream/API/cover-page tests pass 35 tests and
TypeScript passes. Requested, envelope, and nested result job identities now
fail closed on conflict. The strengthened late cover-letter query-switch browser
test still needs a completed fresh run; source-string tests are not behavioral
proof of asynchronous ownership guards. Follow-up source review also flags
save/delete callbacks on the cover-letter page for mounted/context validation.

The repeated production offline/PDF transaction gate completed **42/45** checks.
All three failures are the same editor account-switch scenario timing out before
the delayed PDF request, not an accepted ownership boundary test. The agent is
investigating the fixture/runtime boundary without dropping its safety assertion.
Artifacts: `/tmp/latexy-pwa-ownership-production-2026-10-04`.

A controlled serial XeLaTeX job now passes with unchanged plan limits after the
production build completed (job `0166f6aa-3a26-4f39-adcc-a31c49c2e7d0`, 3570 PDF
bytes). This is one successful rerun, not evidence that every cold invocation
meets its budget. The revised Hindi Noto regular/bold/slant template timed out
at the existing 30-second compilation budget (job
`594d0095-d36a-47d7-8b8b-f0bc92be7304`). Its typography fix remains unaccepted
until a real shaped-text/rendered PDF is verified. Investigate font cache and
runtime timing rather than increasing limits to hide the failure.

A further source-verified recovery gap is assigned: owned terminal REST results
can survive expired Redis metadata, but the PDF download path still depended on
that metadata/cache despite a retained immutable MinIO artifact. A narrow
authenticated, unexpired, exact Finalization/Compilation ownership fallback is
being tested; wrong-owner, malformed metadata, outages, cancellation, and private
non-PDF job families must remain fail closed. The local owned smoke now simulates
expiry of only its own fixture transport keys and requires exact PDF recovery,
anonymous denial, and no recreated Redis metadata. This new runtime check has
not yet passed and must not be reported as verified merely because it exists.

The subsequent restarted real local stack **passes the whole owned smoke**:
job `9f913ff5-20e9-44d5-98ab-965cd3382010` produced 14105 bytes matching its
PostgreSQL size/hash and actual MinIO object. After deletion of only that
fixture's four transport keys, authenticated state/result/download recover the
same terminal result and exact PDF, unauthenticated access remains denied, and
those keys are not recreated. Immediate cancellation of fixture
`1b84466e-7729-4b52-9f9f-6103b3f3b4d0` leaves both Finalization and Compilation
cancelled and exposes no download. Evidence:
`/tmp/latexy-owned-recovery-runtime-2026-10-04.log`. These synthetic records
remain under normal retention; no user records, buckets, or Redis databases
were deleted. Restarted real worker logs use the sanitized tracer marker and
have no `extracted_text`, `return_value`, or synthetic document-text matches.
This is actual local runtime acceptance, not a production deployment claim.

Fresh complete-suite attempts are retained as failures until rerun:

- Backend: the complete pass found one failure in the new real-DB PDF recovery
  fixture. Its Finalization referenced a Compilation not yet flushed; parent
  rows now flush explicitly in FK order without removing constraints. The
  corrected focused route gate passes 21 tests; a second complete backend gate
  is running. Do not reuse the first attempt as green.
- Frontend: 947 tests pass and one structural editor test still expects the old
  `getDraft` expression rather than the captured owner used by the safety fix.
  Correct the structural assertion without reverting the implementation, then
  rerun the entire suite. TypeScript passes after the root cover-page review.

The mounted cover-letter switch test now uses Next's integrated `pushState`,
retains a same-document marker, drains the deferred response, and counts old
subscriptions/state/result/download requests rather than replacing the document.
Root review also added a monotonic owner/query context version so returning
from A to B to A cannot revive an older request, guarded generation against a
different selected letter, and detached old job streams when loading/deleting
an active letter. Fresh browser proof of these changes remains required.
Signature outcome handling is being reviewed separately: returning normally
from a rejected/stale save can cause the child panel to report false success.

Hindi font cache diagnosis found that the image's Lua name index was warm but
its per-font raw/compiled cache was empty. A small Noto shape probe succeeded
and populated that cache. A build-time probe now warms regular/bold/italic and
bold-italic faces; root corrected doubled TeX backslashes in its shell literals
before building. The image has not yet been rebuilt and the actual template
has not yet passed the unchanged free-plan budget or rendering checks.

Completed reruns now supersede the failed attempts above:

- Backend full, unfiltered: **4132 passed, 5 skipped, 5 warnings**, 274.94s;
  `/tmp/latexy_full_backend_final_fixed.log`.
- Frontend full: **149 files / 949 tests passed**, Node 22, two workers;
  `/tmp/latexy-frontend-full-reviewed-final-2026-10-04.log`.
- Latest TypeScript and targeted cover-page/signature-panel/browser-test lint
  pass. `git diff --check` passes.

Signature saves now report an explicit boolean persistence outcome to the child
panel. Root additionally checks ownership after the awaited compile step before
returning success, because switching context after persistence but before compile
completion is another stale-toast window. The deferred failure/switch browser
regressions still require a fresh integrated production run. These complete
unit suites do not substitute for the remaining Hindi and browser/runtime gates.

The cache-warmed local image now builds successfully and the actual revised
Hindi template compiles within the unchanged budget (job
`8d3b8402-4789-45e1-b934-f8c67d1fedcb`, 30524 bytes). Actual PDF inspection
**rejects rendering acceptance**: it embeds Noto regular/bold but renders the
Latin email and bullet glyphs as boxes. LaTeX reports missing Latin and bullet
characters. Poppler extracts the email nevertheless, so extraction alone would
be a false positive. Mixed-script font handling in the template and translation
helpers is assigned before another compile/render check. Retained actual
artifacts: `/tmp/latexy-pdf-qa-2026-10-04-hindi/worker-hindi-noto.pdf` and PNG.

The next read-only security survey added nine direct-route contract tests in
`backend/test/test_job_metadata_shape_contract.py`: **7 fail, 2 pass**. When
Redis ownership metadata is malformed or explicitly bound to another job,
state/result/stream/cancellation and WebSocket access can treat missing owner
fields as anonymous or ignore the binding mismatch. PDF ownership parsing
also ignores an explicit conflicting job ID. This is a verified fail-open
boundary under corrupt/misbound metadata; no public-client mechanism to write
such Redis metadata has been established. A shared strict owner-shape parser
must preserve explicit anonymous and documented legacy owner metadata, reject
present conflicting IDs, suppress all mutations on malformed ownership, and
leave missing-metadata authenticated durable recovery unchanged. Implementation
and full-suite rerun remain pending; the earlier 4132-test green checkpoint
predates these new failing regression tests.

Root implemented the shared ownership parser after survey-agent continuation
hit the tool's thread limit. Malformed owner shape and present conflicting IDs
return 503 before mutations; WebSocket authorization returns false. Valid
explicit-owner legacy envelopes without an ID remain compatible, explicit null
ownership remains anonymous, and list indexing no longer substitutes for an
owner check. The tightened direct/HTTP tests assert the clean 503 response and
no cancellation DB mutation, not merely any exception. The affected
metadata/PDF/jobs/WebSocket/batch gate passes **127 tests**. A fresh complete
backend run after the current Hindi changes freeze is still required.

The offline agent's fresh production Chromium gate passes **6/6, zero retries**
(two deferred editor ownership cases plus four real IndexedDB transactions).
Actual account-refresh testing found a duplicate old-job PDF fetch, which was
deduplicated. Root review then found that combining deduplication with effect
cleanup could discard a valid pending PDF on ordinary same-owner dependency
changes. The effect now relies on its live mounted/owner/resume/generation/job
guards without that per-effect cancellation flag. A new same-owner deferred
download regression is added; the new three editor cases plus IndexedDB tests
must be rerun against the latest production source before closing the broader
editor boundary. This later correction is not certified by the preceding six
passing checks. Cover-letter/signature integrated browser proof also remains
separate and pending.

#### 2026-10-04: mixed-script PDF acceptance and latest integrated gates

The corrected Hindi template now passes the actual local worker and visual PDF
gate without increasing the free-plan compile limit. Job
`8609478d-c055-4398-a1c3-b3575f9d4d17` produced a 35,531-byte, one-page A4 PDF.
Root inspected the rendered page: Hindi regular/bold/slanted text, Latin email,
and list bullets are legible, with no visible clipping or overlap. Worker logs
report zero missing-character and undefined-font-shape warnings. Poppler reports
embedded Noto Devanagari regular/bold and Latin Modern fonts; the expected name,
summary, experience, and email extract without replacement characters. Artifacts
are retained outside Git at
`/tmp/latexy-pdf-qa-2026-10-04-hindi/worker-hindi-mixed-script.pdf` and `.png`.
The PDF remains untagged; this is not PDF/UA certification.

The local development database's single built-in Hindi Professional template
(`82df6e35-3a5d-43e1-85fd-cf59c728cdc5`, `ats_safe`) was updated using a scoped
compare-and-swap of its LaTeX content. No other template, user resume, or metadata
was changed. Fetching that exact template through the API now returns the revised
fallback/bullet setup and the same source SHA-256 as the repository:
`866a47c87e75085b3ff8c9a16209fd2c7f546ff4313bc9371b111370e489b433`.
This is local validation only; the deployed template/image is not certified.

The fresh complete backend gate after strict metadata parsing and the Hindi
changes reports **4151 passed, 1 failed, 5 skipped, 5 warnings** in 117.24s
(`/tmp/latexy-backend-full-metadata-fonts-2026-10-04.log`). The failed assertion
expects Babel-only commands in a mixed CJK/RTL/Indic profile that selects
Polyglossia. Agent review of both profiles is in progress; this failure is not
waived. Root also corrected four dispatch-test database mocks to use the actual
`AsyncSession` specification: `add()` is synchronous, unlike the unconstrained
`AsyncMock` fixture that produced unawaited-coroutine warnings. Fresh focused and
full reruns are required before accepting these corrections.

One isolated Node 22 production browser build is now testing the latest PWA,
editor owner-switch/same-owner refresh, real IndexedDB transactions, deep ATS
recovery, and cover-letter/signature recovery races. The latest frontend source
is frozen during this snapshot gate; no overlapping production builder is used.
Result log: `/tmp/latexy-integrated-recovery-2026-10-04.log`. No commits, pushes,
PRs, or deployments have been performed in this pass.

Subsequent accepted checkpoints:

- Complete backend after correcting the Polyglossia contract and synchronous
  database mocks: **4152 passed, 5 skipped, 1 warning**, 199.26s. The remaining
  warning is Starlette's `httpx` TestClient deprecation, not an unawaited task.
  Log: `/tmp/latexy-backend-full-accepted-contracts-2026-10-04.log`.
- Latest complete frontend unit suite: **149 files / 949 tests passed**;
  TypeScript and scoped ESLint pass. Logs:
  `/tmp/latexy-frontend-latest-{units,ts,lint}-2026-10-04.log`.
- Real owned local smoke after strict metadata parsing passes: completed job
  `2aa38cb2-b99f-4269-8986-70b5b56a070d` has a 14,105-byte PDF matching PostgreSQL
  and MinIO; expired fixture transport recovers exactly, anonymous access stays
  denied, and cancelled job `c5391d47-240a-4ef5-a06f-ee1af6183575` has both durable
  records cancelled with no downloadable PDF. Log:
  `/tmp/latexy-owned-recovery-strict-metadata-2026-10-04.log`.
- Integrated production browser run: **21 passed, 1 failed**, zero retries.
  The only failure is an ambiguous `PDF` button locator in the new same-owner
  title-refresh regression, not a timeout or accepted ownership violation.
  The correction asserts actual rendered PDF/download-fallback state, exactly
  one submission/download/object URL, rather than an arbitrary tool button.
  Fresh same-22-case rerun is in progress:
  `/tmp/latexy-integrated-recovery-accepted-2026-10-04.log`.

The sandbox comment now accurately describes its writable ephemeral overlay,
not a read-only runtime filesystem. A comment-only Docker build reused every
engine/font layer and refreshed the source-hash label; image
`sha256:ffabd2fd9ec7418d16eab9575bd5f4119b7fb9a3612cda88bb8e81f23b704dcf`.
No sandbox flags or compile limits changed.

A new read-only recovery survey flags completed typed jobs whose bounded
durable payload lacks generated content, and repeated bounding that may lose
the `recovery_complete: false` marker. Narrow red regressions are being prepared
before runtime changes. The 4152-test checkpoint predates this additional
survey's regressions; do not treat it as certification of that boundary.

The fresh integrated production rerun now passes **22/22, zero retries**, 3.1m:
`/tmp/latexy-integrated-recovery-accepted-2026-10-04.log`. This certifies the
latest same-document cover-letter query/signature races, editor unmount/account
switch/same-owner title refresh, PWA cached-PDF cases, actual IndexedDB transaction
cases, and deep ATS missed-event recovery selected in that run. The complete
current production-mode browser collection is **572 scenarios / 57 files**;
its fresh full run is still required. Four backend-opt-in scenarios are expected
to skip in mocked mode and must not be reported as live acceptance.

The compact current tracker is now
[`ACTIVE-LOCAL-QA-2026-10-04.md`](ACTIVE-LOCAL-QA-2026-10-04.md). Output-integrity
checks supersede earlier unit counts: **4166 backend tests passed, 5 skipped,
1 Starlette deprecation warning**; **150 frontend files / 957 tests passed**;
repository-wide backend Ruff/frontend ESLint and TypeScript pass. The current-code
worker was restarted, and actual owned fixture
`b88c71c4-597a-45c6-9083-44e360bb6f19` verifies its 14,105-byte durable PDF,
transport-expiry recovery, and anonymous denial. Fixture
`f7897fc9-6977-4897-a1f6-fa8b2cb43dd7` has both durable records cancelled.
Runtime log: `/tmp/latexy-owned-recovery-output-integrity-2026-10-04.log`.

The next whole production-browser collection is **575 cases / 58 files**,
running with PWA enabled and zero retries. Its isolated bundle is sealed before
subsequent implementation. A separate fully mocked browser repro reusing that
server confirms an additional serious defect: a deferred GitHub pull for account
A overwrites account B's Monaco source after a same-document session switch.
The regression genuinely fails; no xfail/retry/waiver is applied. Artifact root:
`/tmp/latexy-editor-mutation-ownership-2026-10-04/`. Provider-sync mutation guards
are now assigned. The complete 575-case run does not contain this newly added
regression and cannot certify that boundary or the later source fix.

Additional code-review candidates include deferred auto-fit/source/save/job-ID
ownership, typed arbiter output admission, and cover-letter `llm.complete` before
durable acceptance. Their regression files are prepared but backend execution
waits until the browser's real Next auth-handler database usage finishes. Source
changes may proceed against the shared checkout; complete-suite results are tied
to their exact earlier snapshots, not relabeled as proof of later changes.

The sealed complete browser checkpoint finished **568 passed, 2 failed,
5 skipped** in 16.5m, with zero retries. Cover-letter hydration `#418` recurred;
the new deep ATS incomplete-output case also failed. Its screenshot/DOM evidence
shows an empty analysis-start screen: the hook's error was not passed to the
panel. Root now connects `deepStream.error` in `/try` and the saved editor and
adds an ordinary worker-failure regression. Fresh browser verification remains
required. Skip review identifies four backend-opt-in cases and one mobile-only
public-quality contract; they are not counted as accepted live/mobile scenarios.

The mixed cache-warmed image built successfully without application context:
`sha256:c6a01aa2025f73cce6f531fe3748b9b21ec606a0334d8b2ccd29526b08b7e52f`.
Build log: `/tmp/latexy-mixed-cache-image-2026-10-04.log`. The previously timed-out
synthetic mixed diagnostic now completes under the unchanged 45-second probe
budget in **9.96 seconds**, emitting a one-page, 31,761-byte PDF. However, Latin
email/bullets placed without explicit English switches inside non-Latin spans
produce missing-glyph warnings; speed and successful TeX exit do not constitute
rendering acceptance. Artifacts: `/tmp/latexy-mixed-cache-acceptance.NANhdj/`;
log: `/tmp/latexy-mixed-cache-acceptance-2026-10-04.log`. Modal shares the cache
contract in source only; no remote build/deployment has occurred.

The explicit-language-switch control now compiles in a fresh confined container
in **15.45s**, under the same 45-second probe limit, and emits a one-page,
31,475-byte PDF with zero missing-glyph/shape warnings. Root rendered/inspected
the complete page: Japanese, Arabic, Hebrew, Hindi, Latin email/bullets, nested
list labels, and Hindi bold/slanted shapes are legible without clipping/tofu.
Artifacts: `/tmp/latexy-mixed-wrapped-acceptance.2Nm0B2/`; log:
`/tmp/latexy-mixed-wrapped-acceptance-2026-10-04.log`. This validates the documented
explicit-English direction-switch control, not raw Latin in non-Latin spans,
actual restarted-worker parity, PDF/UA, or a deployed Modal image. A read-only
translation review identifies missing equivalent generated-output guidance for
Hindi/Marathi; user TeX bodies must remain unchanged.

The complete typed-admission/event/cache backend checkpoint is **4181 passed,
5 skipped, 1 warning**, 188.68s. The retained log is
`/tmp/latexy-backend-full-typed-event-cache-2026-10-04.log`. Subsequent genuine
real DB/Redis red tests prove a same-owner ABA terminal-event epoch hole and a
noncanonical `ALREADY_COMPLETED` transport overwrite. Narrow fixes and nine new
focused tests pass; this complete checkpoint deliberately does not certify them.

Root's owner-scoped offline compile-queue regressions initially failed **4/5**
against real fake-IndexedDB transactions. The implementation isolates enqueue,
queries/counts, and deletion by captured owner; v1 unowned work is preserved but
quarantined rather than guessed or silently submitted. Reconnect stops follow-up
requests/current UI updates after identity change. Accepted responses acknowledge
only the captured owner's queue item; draft acknowledgements compare the exact
revision in one read-write transaction, preserving edits made during the request.
All **18 focused storage tests**, TypeScript, and scoped lint pass. New actual
browser queue/isolation/migration cases run against persistent sealed production
port 5455; current application source is frozen for this verification window.

### October 4 reviewed canonical/ownership checkpoint

The subsequent complete backend gate accepts canonical-result/terminal-epoch
changes: **4,185 passed, 5 skipped, 1 warning**, 292.46s, retained at
`/tmp/latexy-backend-full-canonical-epoch-2026-10-04.log`. Complete frontend unit
acceptance is **152 files / 969 tests**, retained at
`/tmp/latexy-frontend-full-offline-owned-editor-accepted-2026-10-04.log`.
Sealed production recovery/reconnect cases pass **5/5**; the restarted real
worker also passes durable-PDF recovery, transport-expiry, anonymous-denial and
cancellation checks (`/tmp/latexy-owned-recovery-canonical-cache-2026-10-04.log`).

Fresh production interaction exposed a separate deep-analysis click-event JSON
serialization defect; the explicit no-argument wrapper is fixed in source but
not yet in the sealed 5455 bundle. Tracker rollback development acceptance is
3/3, not production acceptance; delayed-delete/Undo identity review continues.
Rapid connectivity flapping is a pending duplicate-submission reproduction.

The hydration failure is not closed: **48/50 passed, 2 failed**, zero retries,
with retained DOM-history artifacts in `/tmp/latexy-hydration-dom-50-2026-10-04/`.
The failing snapshots still show the loading spinner. Streaming boundary timing
is a hypothesis under controlled same-bundle testing, not an established cause.
Hindi/Marathi provider guidance is expanded without mutating user TeX bodies;
28 focused tests pass (1 skip), with the next full backend gate in progress.

The translation-guidance complete gate is now **4,187 passed / 5 skipped**
(4,192 collected); frontend complete units are **153 files / 972 tests**.
Fresh production port 5457 passes **31/31** targeted ownership/recovery/tracker/
offline cases with zero retries, including the deep-analysis click wrapper and
real connectivity-flap dedupe. Retained log:
`/tmp/latexy-reviewed-ownership-prod-2026-10-04.log`. This is not a whole-product
or deployed-site acceptance claim.

New workspace A→B counterexamples are confirmed: delayed list/stats overwrite
B with A's data, and delayed translation navigates B to A's generated variant.
Scoped guards/positive controls are approved, not yet accepted in production.
ATS non-PDF worker payloads are fixed with 138 affected tests after genuine red
assertions; publisher mocks delimit that proof. Durable async ATS/JD Redis-loss
recovery remains a separate reproduction/design task. Hydration remains open:
direct instrumented chunk delivery reproduced 1/50 failures at the root `main`
boundary, with retained diagnostic artifacts; no app workaround is accepted.

### October 4 — JD durable recovery and expanded owner-boundary acceptance

The workspace correction now has fresh production proof: **5/5 passed** at
port 5459, including deferred A list/stats, late translation, same-owner success,
and close/reopen controls. Complete frontend units pass **972/972**. The reviewed
offline/PWA checkpoints pass **16/16 + 3/3**. These are local snapshot results.

The complete zero-retry browser sweep of that sealed application finished
**601 passed, 1 failed, 5 skipped**, 17.0m, across 607 scenarios/64 files. The
failure is React `#418` on Optimize, widening the known shared-root issue beyond
cover letters. Its assertion remains intact. The diagnostic cover-letter
failure had initial seed/cache loading data present, falsifying that missing-data
hypothesis. Stream/cursor timing is still a hypothesis, not a confirmed cause.
Log: `/tmp/latexy-browser-complete-workspace-jd-2026-10-04.log`.

ATS scoring recovery was a false positive: the generic publisher already commits
its durable terminal row. JD recovery genuinely lacked admission/durable intent;
route/worker lifecycle and typed output are now corrected without duplicating
the publisher's arbiter bridge. Root additionally found valid long requirements
being truncated to 2,048 characters while claiming complete recovery. The narrow
JD serializer now preserves flat string arrays exactly within count/UTF-8 bounds,
validates closed metrics, and preserves incomplete omission evidence on rebounding.
Real failed-cache-loss and retry-readmission controls pass. **56 focused + 102
related tests** pass, followed by **4,212 passed, 5 skipped, 1 warning** in the
complete backend run (160.49s). Log:
`/tmp/latexy-backend-full-jd-exact-recovery-2026-10-04.log`.

After graceful, exact-target app restart, actual local Celery proof passes:
owned PDF job `b20e3ea0-1fb4-4f3f-8e85-3d0a6252b7ad` (14,105 bytes), cancellation
`3b91ac0b-c305-4321-83e3-7eb701789518`, and JD
`181a9518-e287-4e18-9c00-39989efb2dd6`. JD long output is exact before/after removal
of only its four loopback transport keys; anonymous denial, no fabricated PDF,
and no transport recreation pass. No provider, billing, Modal or deployed-runtime
claim. Log: `/tmp/latexy-owned-jd-exact-recovery-smoke-2026-10-04.log`.

Three dedicated native-share cases pass the same production build, preserving
same-owner download fallback and suppressing cancellation/stale-owner fallback.
New separate browser REDs verify tracker A-board overwrite and stale failure
clearing B's loading state, plus a deferred share-link response updating B's
editor to Manage share link. Fixes are under review/fresh build acceptance.
The first tracker render guard was too short-lived; root requires stable accepted
owner/generation stamps before acceptance. An attempted drag regression did not
prove its source concern and was withdrawn. Publication remains deferred.
