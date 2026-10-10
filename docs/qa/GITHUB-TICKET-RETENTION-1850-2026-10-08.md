# GitHub completion ticket ownership — #1850

Base: `d80757cdbb2710633e942de878f61d7e78aa7f63` (current main).

## Confirmed defect and bounded repair

An authenticated wrong-account `/github/complete` request was rejected with
403, but first consumed the rightful owner's one-time ticket. This was not an
account takeover: the existing post-claim owner check prevented provider/DB
work. It was a denial of the legitimate completion.

The endpoint now reads and validates the pending owner before claiming the
ticket. Wrong-owner requests leave the payload and remaining TTL untouched.
The claim remains Redis GETDEL, with the existing post-claim shape/owner checks;
concurrent legitimate requests cannot exchange one code twice. Tickets are
random, written once by the callback, and expire after 300 seconds. No grant,
credential, callback redirect, encryption, or provider-error policy changed.

## Local evidence

Real isolated Redis: localhost:6397 databases 9/8. Test PostgreSQL:
localhost:5547 `latexy_quota_release_test`. Python 3.12.10. No live provider,
paid API, real account, or production database was used. HTTP and durable DB
operations in the new endpoint controls were mocked.

- Before repair: new Redis suite **1 failed / 2 passed**. The retained-key
  assertion failed immediately after the wrong-account 403.
- After repair: combined `test_github_ticket_retention.py` and
  `test_github_sync.py`: **45 passed / 0 skipped**.
- Controls cover matching-owner exchange failure and replay, concurrent
  matching-owner completion, missing/malformed payloads, expiry between the
  read and atomic claim, and the existing successful endpoint/grant cases.
- Ruff on all three changed Python files and `git diff --check` passed.
- Independent read-only agent review found no blocker in ownership,
  concurrency, retention, or the changed endpoint fixtures.

Evidence retained locally (outside Git):

| Artifact | SHA-256 |
| --- | --- |
| `/private/tmp/latexy-github-ticket-retention-red-20261008.log` | `a3da81052a97d9eb237d1f7042176cca22f15b5d443be13ac83009c292809a38` |
| `/private/tmp/latexy-github-ticket-retention-final-20261008.xml` | `51d7fede8cf4679c64556cb55b62b0092e2f14aa37ce48fb89223d20e1f2f1d4` |

## Limits and release gates

This is GitHub integration completion, not Google sign-in or all-provider OAuth
acceptance. No synthetic wrong-account request was made against production.
Full protected CI and automatic post-merge deployment checks are separate gates.
Client-side Settings token-retarget and stale provider actions are separately
tracked in #1829 and #1828; this server defense does not claim those are fixed.

## Fresh review and completion — 2026-10-10

Reconfirmed against current main `bdee48926ce0e2e6c9c5e2b281d2ab07c4355b98`.
The wrong-account request still destroys its owner's ticket on that revision.
The three comparable original Redis controls produced **1 failed / 2 passed**:
only rightful-owner retention failed. The expiry-after-GET control is not a
valid baseline comparison because main has no pre-claim GET; the initial broad
baseline run also failed that setup-dependent control, not a second defect.

Integrated current main without importing any unmerged feature branch. The
existing 16-line production repair needed no additional behavior changes.
Strengthened the real-Redis regression suite to cover:

- Three wrong-account attempts preserve both the payload and exact Redis expiry
  deadline, including when less than the original 300-second lifetime remains.
- Both matching-owner requests read the same payload before either reaches
  GETDEL; exactly one reaches the fake provider. The earlier in-flight-provider
  replay control remains as a separate case.
- After wrong-account rejection, the matching account completes successfully
  against fake provider/profile responses and a mocked database, preserving
  unrelated metadata and public-import-only scope. A replay is rejected.
- An unauthenticated ASGI request returns 401 without consuming the real ticket.
- A deliberately substituted owner between read and claim is rejected by the
  retained post-claim owner check, with no provider or database work.

Validation used isolated loopback PostgreSQL 17 and Redis 7, a dedicated test
database and Redis databases 15/14. Dependency locks match the reused Python
3.12 environment. Provider credentials are blank; all provider traffic and
durable user writes remain fake.

- Focused ticket/sync suite: **49 passed, zero skipped**.
- GitHub import/sync/tickets, authentication, auth middleware/schema, and OAuth
  verification-storage suite: **116 passed, zero skipped** (includes the 49).
- Whole-backend Ruff and `git diff --check`: passed.
- A new test initially used a synchronous patch as an async context manager;
  that fixture error was corrected before the passing runs and is not counted
  as an application failure.
- Independent backend/security review found no production blocker. Future
  PR #1864's capability-router dependency and frontend document-lifetime claims
  are complementary; keep those gates and this handler when later combining.

Reproduce the bounded regression group with isolated test infrastructure:

```sh
cd backend
python -m pytest test/test_github_ticket_retention.py test/test_github_sync.py \
  test/test_github_import.py test/test_auth.py \
  test/test_auth_middleware_extended.py test/test_auth_plugin_schema.py \
  test/test_oauth_verification_storage.py -o addopts='' -q
```

The old head `d6e11f97` passed GitHub Actions and security checks but retained a
failing required Vercel quota status. A Ready bot comment for a different build
does not clear that gate. Require fresh protected checks on the published final
head. No real GitHub-account linking, production Redis mutation, manual deploy,
provider-setting change, or cross-provider/browser account-switch certification
is claimed by these tests.
