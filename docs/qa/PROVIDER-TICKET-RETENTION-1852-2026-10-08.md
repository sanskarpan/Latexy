# Dropbox, Zotero and Mendeley ticket retention — #1852

Base: exact main `d80757cdbb2710633e942de878f61d7e78aa7f63`.

## Verified impact and repair

All three handlers atomically consumed completion tickets before checking the
authenticated account against the callback's stored owner. A wrong-owner
request returned 403 without exchanging/persisting a grant, but destroyed the
rightful owner's completion. This is an availability/reconnect defect if a
ticket leaks, not demonstrated account takeover.

Each handler now reads and checks ownership first, then retains its atomic
Redis GETDEL claim and existing post-claim shape/owner verification. Random,
single-write callback tickets retain their existing TTL. Provider grants,
configuration checks, encryption and error policy are unchanged. GitHub is
handled separately by #1850 / PR #1851; Google Drive already checks owner first.

## Evidence and review

- Fresh real-Redis baseline: **3 failed retention assertions**, one per
  provider. After the wrong-account 403, each cached ticket was absent.
- Candidate real-Redis controls: **6 passed**. They prove retained payload/TTL,
  rightful-owner claim followed by synthetic provider failure, true replay
  rejection, and exactly one exchange under concurrent matching-owner claims.
- Full `test_provider_ticket_retention.py`, `test_dropbox_sync.py`, and
  `test_zotero_import.py`: **58 passed / 0 failed / 0 skipped**; one pre-existing
  Starlette/httpx deprecation warning. Ruff and diff check passed.
- Existing cross-owner HTTP tests now reject both repeated wrong-owner
  attempts with 403 and assert no pop. They no longer model artificial expiry
  as replay. The new real-cache tests cover legitimate consumption and replay.
- Root independently reviewed the agent's implementation and requested that
  endpoint-fixture correction before the final full-module run.

Isolation: PostgreSQL localhost:5547 `latexy_quota_release_test`, Redis
localhost:6397 databases 9/8, immutable Python 3.12.10 environment. Provider
HTTP and DB mutations were mocked. No real credentials, live provider call,
payment, account write, or production test request was used.

| Local evidence | SHA-256 |
| --- | --- |
| `/private/tmp/latexy-provider-ticket-retention-red-20261008.log` | `3d4374242afe5ee57362df504b1fefd3f3be1ba36e195e1e19495774bc92ae40` |
| `/private/tmp/latexy-provider-ticket-retention-full-20261008.xml` | `fef024dacb63452686d0eadc017eeef4dc7fefb5d044a65e0a477a1c41558f19` |

## Release limits

Protected CI and automatic post-merge deployment verification remain separate
gates. Vercel rejected the concurrent GitHub defense PR's required preview
check due build quota; no bypass or protection relaxation is permitted here.
This work does not complete all-provider client dispatch or live OAuth QA.
