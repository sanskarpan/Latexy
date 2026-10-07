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
