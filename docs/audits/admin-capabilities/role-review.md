# Role, UI and service review of draft #1864

Reviewed from `1e0f1c459dff1e44db7f79bac992008244b2913e` on 2026-10-10.
This is an additional independent review of the previously green implementation.
No merge, manual deployment, production setting change or real provider action is
part of this work. Exact-head CI, rather than the earlier green run, is required.

## Real roles and effective policy

Latexy account roles are `user`, `support`, and `admin`. `anonymous` describes an
unauthenticated request; it is not an assignable account role. There is no account
role called `reader`. Document permissions (`owner`, `editor`, `commenter`,
`viewer`), workspace permissions (`owner`, `editor`, `viewer`), and tenant roles
remain separate ACLs and never confer account-admin authority.

For optional product use, all of these must allow the operation:

- Global capability and every parent
- Current account role/context and every parent
- Current plan family and exact SKU, including every parent
- Original authentication, document/workspace/tenant ownership and role checks
- Original quotas, input validation and provider constraints

The `0063_capability_roles` migration adds explicit role grants without rewriting
existing global/SKU denials, user roles, subscriptions or data. Rollback preserves
administrator choices; re-upgrade validates the retained schema and role domain.
Missing grants, unknown roles/SKUs, malformed values and unavailable policy state
deny optional use. Account identity plus grants are read in one async SQL snapshot;
synchronous admission uses one short read-only repeatable-read transaction. A
long-lived ORM object's cached role or plan cannot authorize access.

Only account admins can read or edit the control plane. Switching off an admin's
product grants does not remove the controls required to restore them. Current
admin UI writes compare the previously read cell value and reject stale intent
with 409; simultaneous edits to different cells remain independent. Legacy direct
admin writes without `expected_enabled` retain last-writer-wins compatibility.

## Defects corrected in this pass

- Added the missing account-role matrix, role-scoped admin controls and narrow
  role/family/SKU/parent explanations. Existing global switches did not previously
  provide role restrictions.
- Scoped admin navigation and the complete admin screen to the verified current
  account. Main-page state is remounted on confirmed account switches, including
  A→B→A; previous account keys, dialogs and workspace data are not retained for a
  different signed-in identity.
- Retained same-account verified grants during bounded background refresh instead
  of unmounting tools every 30 seconds. Initial load, explicit invalidation,
  account switches, timeout, errors, expiry and actual revocation fail closed.
  UI refresh is bounded at 30 seconds plus an 8-second request timeout; server
  admission always rechecks independently. A local/offline draft is retained
  during transient session checks rather than destroyed.
- Closed missing nested and management UI controls, including optional writing,
  ATS/optimization, cover letters, workspace/recruiter actions, references,
  developer/BYOK integrations, sharing and extension actions. New optional
  controls hide when OFF; relevant old data/removal/disconnect controls remain.
- Removed remaining links to unavailable optional destinations (grid/list/variant
  Optimize, Merge, Career, visibility management, builder source and onboarding).
  Baseline source-editor links remain usable when structured reattachment is OFF;
  an in-flight fork falls back to its saved source if linked-variant UI is revoked.
- Real browser execution exposed bootstrap reads exhausting the expensive-action
  rate bucket during navigation. `/me` and `/config/entitlements` now use the
  existing bounded lightweight bucket (300/minute, 6,000/hour); no global limit,
  authorization check or expensive endpoint budget was changed. Ten dedicated
  regressions and actual local TCP/Redis exhaustion checks verify the separation.
- Normalized payload booleans before gate selection, matching Pydantic's accepted
  JSON values. Values such as `"true"` and `1` cannot bypass publication, public
  review or builder reattachment restrictions. False-value revocation remains
  available without creating a new share link or dispatching compilation.
- Added current actor and owner restrictions to shared-source reads and writes,
  workspace downloads and suggestions. Turning off workspace use hides other
  members' documents while the member retains their own submitted source and
  removal controls. Original resource ACLs still apply.
- Rechecked active collaboration recipients before outbound data, and senders
  before persistence. Idle connection checks and current ACL checks reject role
  changes, deleted membership/ownership and newly disabled capabilities.
- Rechecked recurring saved-search alerts as new admissions; OFF pauses them
  without recording a successful delivery. Explicit already-admitted reminders
  and queued work retain fulfillment semantics.
- Added current-role snapshots to optional compiler/ATS settings. Disabled
  industry profiling cannot return through automatic industry detection.
- Closed stored BYOK use in GitHub imports before quota/dispatch and carried a
  nonsecret admission snapshot into workers. Automatic checkpoints and linked
  variant refresh also require their current optional grants.
- New purchases use the purchaser's current account role plus the target SKU.
  The current free plan cannot accidentally forbid upgrading to an allowed
  target offer. Student verification uses the recorded token owner's role before
  any new provider checkout. Existing paid fulfillment, renewals, cancellation
  and refunds are not gated by a new-sale switch.
- The capability router rejects unclassified product HTTP handlers at registration
  rather than silently granting new endpoints omitted from its policy map.

## Tested versus unverified

The generated [129-feature matrix](feature-matrix.json) now contains four explicit
role/context entries per capability, including UI and API verification status.
Policy coverage is not mislabeled as a completed role-by-feature UI workflow.

| Layer | Actual evidence | Boundary |
| --- | --- | --- |
| Role × registry × SKU policy | Every one of 160 registry entries, four contexts and eleven SKUs; OFF/ON and cross-role isolation; missing/unknown grants and parent intersections | Pure policy tests, not 7,040 distinct browser workflows |
| Role API integration | Real isolated PostgreSQL/Redis; real stored sessions; current role changes; admin isolation/recovery; stale/concurrent edits; rollback/re-upgrade | ASGI requests plus a separate local TCP HTTP smoke |
| Local TCP HTTP | Actual FastAPI server, PostgreSQL 17 and Redis 8; user/support/admin search OFF=403 and ON=200; owner list/account recovery; current effective map; anonymous isolation; stale write=409 | Synthetic local records; no mocked HTTP handlers; not a browser pass |
| Sharing and jobs | Registered route denial, normalized payload variants, owner/actor checks, real DB sharing/recovery, websocket recipients, admitted completion/failure and refund regressions | Provider boundaries mocked or unavailable; no real purchase/email/model/OAuth success |
| Frontend | Rendered/hook/unit assertions for identity races, nested controls, menu actions, deadline/refresh behavior and native editor command wiring | A source assertion or component test is not full visual acceptance |
| Browser | API-mocked capability/editor scenarios plus new `capability-fullstack.spec.ts`, wired to real Next auth → FastAPI → PostgreSQL with desktop/mobile assertions and no API interception | Check the exact-head GitHub job/artifact for execution results; local Chromium cannot open its required IPC socket |

The full-stack case uses synthetic local accounts and a loopback `_test` database,
exercises the admin toggle itself, then verifies the current account's visible
control and the direct API. It also checks anonymous Studio, unchanged owner
source and admin recovery. Model/email keys are absent and no paid provider is
called. GitHub retains screenshots/traces for 14 days.

## Local verification checkpoint

- Frontend: 189 files / 1,334 tests passed; TypeScript, strict ESLint, Node 22
  production build and artifact validation passed. Extension: 13 tests plus
  syntax/package validation passed.
- Actual local HTTP also verified Next/Better Auth signup, its cookie session,
  the same session's FastAPI identity, admin page HTTP delivery and role-based
  API denial. This does not execute or visually validate client-side React.
- Final full backend run: 5,414 passed, 15 failed and four skipped. All fifteen
  failures are host TeX format/font failures reproduced with the exact same test
  IDs on the unchanged prior head; see [the comparison](role-environment-comparison.json).
  The reused synthetic provider-ID fixture was fixed; 40 related tests and a
  repeat pass. Exact-head GitHub CI remains a separate requirement.
- The full-stack launcher now generates per-run synthetic auth/encryption keys,
  rejects non-loopback/non-test databases before migrations and refuses unrelated
  running servers. It ignores inherited persistent keys and disables model/email
  providers. The keys are never printed or persisted. Isolation/deployment/transport
  tests: 102 passed; frontend launcher tests: eight passed.
- Earlier proxy-dependent tests needed the local runtime's optional SOCKS support;
  local tracing tests needed deterministic sampling instead of the inherited 1%
  sampler. These are local test environment adjustments, not application or
  lockfile changes. No network or browser security policy was weakened.

### Browser-driven follow-through

The initial real browser run exposed a test launcher configured as staging,
which correctly strips credentialed loopback CORS. The isolated launcher now
forces test mode; production/staging CORS rules remain unchanged. 107 local
security/isolation/deployment tests and actual allowed/denied-origin HTTP
preflights pass. A subsequent browser run exercised user OFF/ON and support OFF
with matching API decisions, then found the bootstrap rate-budget issue above.
The final exact-head run must verify the complete scenario after that correction.
The user case now also checks cross-tab refresh without navigating or reloading.

The mobile API-mocked fixture now explicitly enables Studio/Templates in ON
cases, rather than expecting those links while returning an empty grant map.
Separate OFF assertions still require those links to disappear while account
recovery, login and sign-out remain available.

## Deliberate exceptions and merge gates

- OFF stops new optional admissions. Already-admitted paid work completes or
  fails under its existing job ownership/finalization/refund rules. No switch
  synthesizes a refund or cancels an admitted job.
- Existing owner source, history/results, ordinary compilation/PDF/source export,
  deletion, revocation, disconnect, receipts and account/billing recovery remain.
  For B09, explicit structured reattachment is optional; ordinary source editing
  and detachment remain recovery baselines and are now described explicitly.
- An already downloaded artifact cannot be recalled. Previously issued storage
  bearer URLs remain valid until their original expiry: up to one hour for shared
  PDFs and 24 hours for template assets. OFF prevents new issuance; immediate
  recall of prior URLs would require a different serving/storage design.
- Live provider success, exhaustive manual visual workflows for all 129 entries,
  and production performance/load remain unverified. Database-authoritative
  role/recipient checks introduce real reads; production latency must be measured.
- The migration/model overlap with open engine #1833 and billing #1834 must still
  be reconciled before combining branches. No unrelated PR was merged here.
- Old application binaries do not enforce this new policy. Migrate before rollout
  and avoid a mixed old/new serving fleet when immediate enforcement is required.
- Keep this PR draft and unmerged. Green exact-head checks are necessary and do
  not alone establish exhaustive manual/provider acceptance.
