# Application acceptance and recovery — October 16, 2026

Production launch remains **HOLD**. This record distinguishes isolated
application evidence from deployment, live sales acceptance, and completion of
every product journey.

## Tested source and PDF matrix

The new execution used exact candidate
`e9d6f1c2b71722e30efe861703e648ed744c3327`:

| Tree | SHA |
|---|---|
| Root | `6ab2b6137adaa4fa8e522d5f24a8a5b3509771fa` |
| Backend | `a0753b9f8999dfb2e0d3ff3679cd534144a0f65c` |
| Frontend | `f583d8daf19efa7fcc8ed2a7eecf36d054e7e8b2` |

All 45 remaining cases (15 builder/language profiles and 30 templates) completed
through normal application admission and workers. Each case has locally saved
PDF, geometry and SyncTeX artifacts, an observed browser PDF paint, and a normal
UI download whose SHA256 equals the API artifact. Six fresh, independent owners
were used. The initial eight admissions used the frozen V12 harness; subsequent
execution and final reports used V13. Bounded batch deadlines stopped between
cases; resumption retained completed jobs and did not replay admissions.

At **15:11:32 UTC**, the read-only verifier checked all 45 accepted durable
finalizations and the complete compilation/finalization sets of these owners.
There were no extra jobs. The API/checkpoint evidence records exactly one quota
increment per case. This is not an independent database quota-ledger assertion.

Combined with the previously verified 31 template cases, the defined PDF matrix
covers **76 cases**. The frontend tree and `backend/app` tree were unchanged
between the prior browser source and this candidate; this does not assert that
deployment scripts or migrations were unchanged. Cache admission checks from
earlier runs remain separate; this execution submitted no cache-test jobs.

| Private evidence (retained locally) | SHA256 |
|---|---|
| Final 76-case aggregate, `normal-ui-evidence-verification-launch-round10-20261016T151132266627Z.private.json` | `4a0ba96aef98e7ce596d095d4ac39d0bc0809aa0af5842644a7b548c1271e495` |
| Corrected-format 45-case browser manifest | `012e62a8aa646b14dcd66bcfb2489bb55978ffe75993e0c87c4ff0e6787af46d` |
| V19 read-only verifier source | `ece2e92efbf636440dae3128fd7a689cd2f09f9c7dc921a22ca3acb2ac02eb1d` |
| Prior 31-case verification | `3780efbfb5c77b49dcd25f30b288874f3d4fe24bd6eb5c5b286755622ca8e1d4` |

The original manifests and failed verification attempts are preserved. Fixes to
the verifier aligned its attempt-ID and checkpoint-manifest contracts with the
actual preparation/harness constructors. Screenshot captures contain JPEG
bytes despite historical `.png` filenames and initial PNG labels. A new manifest
corrected only the format labels after verifying the original byte hashes;
images and capture timestamps were not changed.

One paralegal case initially reported an accepted-PDF lookup error. A manual
lookup Retry recovered the original artifact, and its UI download matched the
API PDF. The failed view is retained separately. Several entitlement checks also
temporarily failed closed before recovering. Matrix completion records eventual
PDF paint/download correctness, not first-attempt availability or latency SLOs.

## Separate Guided Builder journey

After the matrix snapshot, a separate synthetic résumé was created through
Create Resume → Guided Builder. Profile, experience, education and skills were
entered using the form. Preview was clicked immediately after the final skills
edit. The UI reached “All changes saved” and displayed the generated PDF.

The ordinary Download PDF action returned a one-page PDF with SHA256
`93f42ad1ff5fe6ddffbaa4f1edb6794cbe8662a741834648d8db1b5e1edb3638`.
Text extraction and visual inspection confirmed all entered sections, including
the final skills edit. At **15:22:20 UTC**, a separate read-only database check
verified the saved builder content, current LaTeX hash and accepted finalization.
The owner's complete compilation and finalization sets contained exactly the
five matrix jobs plus one new builder job. The normal UI download matched that
new durable PDF's hash and size; Download did not create a second compilation.
This does not independently prove a builder quota-ledger increment. This work
occurred after the matrix's no-extra-job snapshot and does not rewrite that
historical assertion.

The separate guided verification report has SHA256
`e9720cc17a2e43abb3f2a9940abd32b870d164de55fae2f891198f67830230c2`;
its verifier source is
`6537a6bf2a2a78fb399e977fcca9116fbed009ef5b6e45b9d08ce22b0ad950e6`.
This is a single synthetic happy path, not exhaustive builder import, cancellation,
mobile or accessibility certification.

The owned local API/frontend and temporary QA backend/infrastructure applications
were stopped after evidence capture. Both remote QA apps were confirmed stopped
with zero tasks, and the local ports were no longer listening. The separate
`LatexyBackup` Redis instance was not changed.

## Recovery and production preflight

An isolated restore rehearsal restored 61 tables and verified counts/hashes.
The distinct recovery revision `4182705dfb88a378fcef8c19d19b19e1a53afbd6`
and candidate `e9d6f1c2` both migrated the temporary restored database to `0075`,
started the application and returned `/readyz` 200 with database/Redis/cache
checks passing. Legacy projections remained intact. The temporary restore
database was removed after pooled connections drained. Source backup branches
and their databases were retained.

This was source startup in an isolated controller, not deployment of either
public API. Separate canonical API-image availability/hash checks passed.
The rehearsal does not substitute for a fresh recovery point at actual cutover.

A fresh exact-candidate production diagnostic reported canonical rollout safety,
with production database still `0059`, startup upgrade required, and sales
safely disabled. Production was not migrated or deployed during these checks.
A read-only fleet observation confirmed the existing deployment metadata; it
did not claim a drain, whole-fleet image mapping or serving-source attestation.

## Current admission and cache check

A separate isolated normal-API run at exact source
`ec07c17ea05bc2a94ce79d66e575ff9b993e106a` passed three submissions: a cold
compile, an identical cache hit, and a cache miss after editing the same saved
document from revision 1 to revision 2. Two fresh synthetic owners exercised
normal authentication and owner-only access. Purchases and outgoing email were
disabled; this run used the previously certified immutable renderer image and
assets, without another security probe.

The cold and hit results had different job/artifact identities and identical
PDF bytes, plain SyncTeX, canonical geometry and actual durable renderer
fingerprints. Each admission charged one quota unit. Other-owner PDF, preview,
geometry, SyncTeX, job-state and job-result requests were denied. Read-only
database, Redis and object checks verified the accepted results and stored
bytes. Editing invalidated the current-artifact lookup before the final
compile; its accepted result belonged to revision 2 and changed the PDF.

An independent read-only database snapshot confirmed exactly one document,
three finalizations, three compilations and three accepted artifacts for the
two owners, with no extra work. The first count-check helper was rejected by
Neon's pooler before SQL because it passed unsupported startup options. A
separate corrected helper applied transaction-local timeouts and passed; it
replayed no API requests. The original attempt remains recorded.

Private evidence SHA-256 values:

- Three-step report: `75bd0b783a8c8933034ef7ac7637ad775e284e15db444998942b25e37c3a5de4`.
- Checkpoint: `3cb922199a7b5ca8a5f270fea30cbd24f1926245c16bd9c5f7dec682696510f9`.
- Independent count report: `51bab62951592412bc2262f00e920703f2085f79ba5dc87c4ec521c36fe1642b`.

Both temporary QA applications were subsequently confirmed stopped with zero
tasks, and local QA ports 8030/5180 were closed. This was API acceptance, not a
new browser-paint or performance certification. It predates the following
Modal secret-precedence repair, which changes deployment binding rather than
the renderer or admission implementation and requires its own current-head CI.

The historical recovery revision `4182705d` above predates the traffic hold.
Its restore/schema evidence remains valid within that scope, but it cannot be
nominated for the held rollout. Production requires a distinct hold-capable
recovery revision with canonical CI, actual image availability and separate
readiness/recovery validation before migration.

## Dodo live catalog

The merchant UI showed live verification approved. The production lifecycle
webhook remained disabled pending backend readiness. No merchant settings were
changed and no payment was made.

Live read-only checks retrieved the eight configured products and calculated
checkout previews. Identity, price, currency, billing interval, tax setting and
preview currency matched the saved contract. Explicit `archived=false` and
`archived=true` product-list membership established that all eight products were
unarchived. Product detail responses do not expose an archive flag.

The V3 aggregate included a saved `created` flag as a current-state condition.
Its false result is preserved. A separate offline derivation checks
current provider evidence without treating that saved flag as an activity test.
The local contract producer's meaning of `created` was not established from
source. This derivation made no additional provider requests.

Weekly/lifetime products were outside the eight-product contract and were not
certified. Real Student checkout remains pending by user choice. No successful
real purchase, lifecycle webhook delivery, production activation or full product
certification is claimed.

## Follow-up

The tested baseline editor waited for accepted-artifact recovery before making source
available, and that request has no explicit timeout. The paralegal recovery
failure and slow loading warrant a focused repair: make source available while
recovery runs, bound and cancel recovery reads, honor bounded `Retry-After`, and
keep unknown recovery outcomes from authorizing duplicate preview admission.
The follow-up implementation makes source available while that read runs and
gates preview admission for the exact owner, document, generation, source and
content revision. Recovery has an eight-second overall deadline covering auth,
transport, response parsing and at most one bounded `Retry-After` retry. Leaving
the document aborts the current read. An authoritative matching no-artifact
response permits one initial compile; unknown or failed reads remain retryable.

Independent review caught and the follow-up repaired a stale-revision guard:
editing away and saving the same text again must not leave the new revision
blocked by an older failed lookup. Regression tests execute the production
admission callback and scope cleanup, including hung transport/body parsing,
same-deadline auth readiness, stale identity, preview admission and export paths.
This repair and its verification belong to the new PR revision, separately from
the recorded `e9d6f1c2` browser execution. PR #1908 was subsequently integrated
as `ec47d6c7`; it changes preflight/deployment checks and preserves the matrix's
frontend and backend application trees.

Local verification of the follow-up passed TypeScript without incremental
state, ESLint with zero warnings for every changed frontend file, 103 focused
recovery/bootstrap/export tests, 103 source-scope/capability/generator tests,
and 31 manual-admission/save tests. The full frontend suite and exact-PR CI
results are recorded on the follow-up PR. Windows-only fixture repairs retain
the existing assertions: source matching tolerates newline conventions, and
the temporary Monaco patch fixture disables Git's automatic newline conversion
so its pinned byte-integrity checks remain exact.
