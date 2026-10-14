# Suggestion recovery and BYOK claim corrections

Integrated base: `d22998e0f45d55fd0a675e4cc622ab603c612d23` (D14 #1883, 2026-10-13).
Prior reviewed F07 checkpoint: `f48c7f6eb86f1e305b692ed09da7710b267c80d4`.
Shared auth/source-ownership foundation and the final D14 Suspense repair are
inherited unchanged from main rather than duplicated in this remaining diff.
This is a narrow correction to the current capability contract, not a claim of
complete launch readiness or live-provider acceptance.

## F07 decision contract

- A POST with `status: accepted` requires both F07 and C01 before the handler
  queries or mutates a document. Accepted POST retries remain admission-gated.
- `rejected` and `conflicted` are recovery outcomes. F07/C01 denial does not
  prevent an authenticated owner or authorized editor from recording them.
- Document ownership and resolver roles remain mandatory. Editors still require
  F04 for both themselves and the document owner. Viewers, commenters and
  outsiders cannot persist any outcome, including an arbitrary conflict.
- The resolver ACL and acceptance grants are checked again after acquiring the
  resume-row lock. Acceptance additionally checks the owner's F07/C01 grants.
- The first committed outcome wins, regardless of a later recovery payload.
  Recovery cannot change an accepted outcome into a rejected/conflicted one.
  CAS checks, per-user/per-document rate limits, bounded storage and replay
  tombstones are unchanged. Rejection/conflict do not change document source.
- Authenticated GET decision recovery remains independent of F07/C01. It keeps
  the existing owner/collaborator/F04 read-access requirements.
- The editor's Suggestions tab remains reachable when F07/C01 is disabled.
  Creation requires F07; acceptance requires F07, source-edit permission and
  owner/editor access. Owner/editor rejection no longer depends on C01.
  Nonresolver authors may only withdraw their own local ephemeral proposal;
  they do not create a shared server decision.
- Suggestion state and all captured actions, retries, remote presence and remote
  decision confirmations are fenced to the current owner/document incarnation.
  Confirmed scope changes reset proposals, decisions, drafts, retries, mode and
  errors. A→B→A does not resurrect an old callback or in-flight response.
- The current authenticated source load establishes the resolver role and new
  source-admission readiness. Same-owner transient refresh retains local recovery
  state, while creation/acceptance wait for fresh source readiness.
- Source-admission tickets are renewed synchronously during render when the
  session snapshot, authentication readiness or token changes. Old same-token
  loads and queued acceptances cannot reopen admissions before the next load
  effect, including snapshot/token A→B→A transitions.
- Better Auth's authenticated `isRefetching` lifecycle independently suspends
  creation/acceptance even when `isPending` is false and the session object is
  unchanged. Current-owner rejection and confirmed-result recovery remain
  available; successful refresh still requires a fresh document load.
- An explicit numeric session HTTP 401 ends the confirmed identity, unlike
  network/503 uncertainty. Guarded session, API/WebSocket auth and header/offline
  identity use the same classification; old actions and responses do not revive
  after reauthentication to the same account.
- Source/title/CAS and PDF content is marked committed for one render-renewed
  owner/document incarnation, in the same React update lane as its matching
  buffers. A higher-priority render cannot trust a synchronous loaded ref. Confirmed logout/401 masks remembered offline content immediately;
  unknown cold offline recovery can still use the last confirmed browser-profile
  owner. A PDF-only load for a new document clears the prior source/title/CAS
  buffer before exposing its matching PDF. Cold authoritative401 or settled
  logout also clears the persisted app offline identity/private cache, even
  when the header has not previously observed an owner.
- New source actions additionally require the exact layout-committed load
  ticket. Same-owner asynchronous reloads cannot admit from queued ready refs.
  Captured actions consult the outer render-current account/route authority,
  including before the old child rerenders or passive cleanup runs. Missing
  outer authority fails closed. Its stable recovery identity is separate from
  a render-renewed, lease-bound admission value: parent-only pending/refetch/
  error/session-reference A→B→A cannot revive a queued acceptance when a child
  misses the uncertain render. A fresh matching source commit is required.
- Both POST and GET dispatch pin the initiating auth token. Nonowners need the
  actor's current F04 before dispatch and before consuming late outcomes. F07/C01
  changes after admission do not cancel an already committed result; independent
  document-access revocation prevents local consumption of that result.

Proposal payloads remain ephemeral awareness state. This change preserves the
existing document-resolver contract; it does not introduce a persisted proposal
registry or author-provenance verification for owners/editors' arbitrary IDs.

## D25 BYOK families

`APIKeyService.provider_classes` registers OpenAI, Anthropic and OpenRouter.
The catalog and public pricing now name those three BYOK families. A Gemini
BYOK key is not supported. No provider adapter, price, entitlement allowance or
subscription contract was changed.

The unused `LLMProvider.GEMINI` enum and Gemini masking branch are not provider
registrations. Existing platform Gemini/OpenAI-compatible configuration and
Gemini models served through OpenRouter are distinct from direct Gemini BYOK.
Historical audit documents and proposed architecture descriptions were not
rewritten as part of this correction.

## Verification scope

- Registered ASGI routes with deterministic database doubles cover F07/C01
  OFF/ON, all decision outcomes, invalid/missing/malformed input, owner/editor
  versus nonresolver access, F04 and owner policy, post-lock revocation, CAS,
  idempotency and denial before mutation.
- Real isolated PostgreSQL/Redis tests exercise real session authentication and
  user/support/admin account contexts with global, account-role and exact-SKU
  F07/C01 restrictions, owned recovery, and re-enabling acceptance. Existing
  concurrent acceptance, tombstone and authorization regressions also run.
- Actual SuggestionsPanel markup and editor wiring checks cover recovery
  controls independently of the backend. Deterministic tests execute the actual
  recovery hook and API client across account/document switches, queued requests,
  stale callbacks, late responses/errors, source refresh and F04 revocation. A Playwright regression covers live
  entitlement refresh, leaving/reopening Suggestions, disabled acceptance and
  successful rejection with unchanged source.
- The generated feature matrix records conditional acceptance separately from
  recovery and names the exact backend evidence. Tests verify catalog/provider
  registry/pricing consistency.
- The installed Better Auth session atom, actual guarded/auth-sync/header paths,
  and actual saved-editor identity/load/return-guard code cover authenticated
  refetch, numeric401 versus503, before-effect account/document changes, source
  load ABA and offline draft-to-PDF-only transitions. Installed React18
  ConcurrentRoot tests verify default-lane load versus synchronous render
  ordering, source admission before commit, and direct PDF publication. Normal
  protected layout/account and dynamic route keys already remount those pages;
  reused-page document cases exercise the additional defensive content fence.
  Cold401 header purge followed by a fresh offline503 editor mount cannot
  recover the previous remembered owner.

Cloud Chromium could not launch because its singleton Unix socket was blocked;
approved escalation failed constructing the executor's bubblewrap mounts.
Therefore the new Playwright workflow is **not verified** in this environment.
TypeScript, ESLint, Ruff, unit and ASGI/database checks do not substitute for that
browser acceptance. No credentials or live providers were used.
