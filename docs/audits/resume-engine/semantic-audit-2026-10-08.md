# Semantic engine follow-up audit — October 8, 2026

This audit continues draft PR #1833 after the owner approved resuming work.
The review began at `20ae2039`; root then rebased the branch onto current main
`bdee4892`, producing checkpoint `87ea1232`. No production database, paid
provider, remote renderer, or deployment was used for these regressions.

## Reproduced defects and repairs

Four negative regressions failed before their production repairs on real
isolated PostgreSQL and Redis. They were not inferred from static source alone.

| Defect | Deterministic reproduction | Repair |
| --- | --- | --- |
| Expired staged PDFs incorrectly exhaust an owner's pending-import cap. | `test_pdf_imports.py::test_expired_cleanup_backlog_does_not_block_live_owner_admission`: insert 201 older expired rows belonging to another owner and ten newer expired rows belonging to this owner. The global 200-row sweep cannot reach this owner's rows. A valid upload wrongly returns 429. | Count only live staged rows while preserving the bounded global sweep, owner admission lock, and ten-live-import cap. |
| A preloaded ORM document can overwrite a newer semantic field despite holding the document row lock. | `test_resume_structure_db.py::test_stale_loaded_resume_cannot_overwrite_newer_field`: both sessions load revision one; one commits a heading edit; the stale session submits its old field/revision/source tokens. The old write was accepted and overwrote the newer heading. | Canonical semantic write access now locks and refreshes the complete Resume using `populate_existing=True` before projection and access recheck. Source PUT already performs its own refresh; structure previously had a separate refresh. |
| Private durable-run identity remains an unkeyed checksum. | `test_resume_durable_ledger.py::test_private_run_context_rotated_server_key_cannot_restore_paid_run`: keep the admitted credential scope fixed, rotate the server key, then restore the same private snapshot. It previously restored successfully. | Use a purpose-specific HKDF-derived HMAC for durable run admission context. |
| Private paid-stage input identity remains an unkeyed checksum. | `test_resume_durable_ledger.py::test_rotated_server_key_cannot_replay_completed_private_stage_input`: complete a synthetic paid stage, verify ordinary replay, rotate the server key, then attempt input replay. It previously returned the completed output. | Use a separate purpose-specific HKDF-derived HMAC for paid request input. |

The last two repairs address the production private-input path discussed in
security issue #1843. Output/result checksums remain unchanged. This audit does
not claim a fresh CodeQL pass; root must obtain and inspect that scan.

## Identity and compatibility rules

- Credential scope and legacy optimization-checkpoint MAC bytes remain unchanged.
  The previous credential implementation has a frozen synthetic known-answer
  vector in `test_resume_private_stage_fingerprint.py`; it no longer recomputes
  a second stdlib HMAC expression inside that test.
- Durable run context and paid input have distinct HKDF purpose labels and
  message domains, separate from credentials and legacy checkpoints.
- Canonical JSON ordering makes equivalent requests stable. Modified inputs,
  missing/invalid server configuration, and key rotation fail closed.
- Old unkeyed private run/input identities are intentionally not migrated into
  replayable identities. Their bytes do not prove that historical paid work may
  safely replay under the new namespace. Two actual database regressions install
  these obsolete identities and verify refusal.
- Historical public output checksums and completed candidate-review records are
  unchanged. The new MACs authorize paid execution/replay, not automatic source
  mutation or acceptance of AI wording.
- No schema or backfill is required; the new identities still occupy existing
  64-character context/input columns.

## Additional integration coverage

The follow-up also verifies that ten live staged imports still return 429, and
that two adaptation writers which preload the same unbound PDF produce exactly
one saved resume and retain the exact original bytes. Existing suites cover
owner isolation, staged expiry, saved-original retention and cascading deletion,
source and field CAS, stable imported node IDs, linked variants, bounded budgets,
ambiguous paid outcomes, concurrent stage admission, explicit candidate
acceptance, factual dependencies, and scoped provider admission.

The earlier seven-file focused run completed with exit zero. The enlarged final
twelve-file run passed **179 tests in 305.10 seconds**, with zero skips, failures
or errors. JUnit independently records 179 tests and zero skips/failures/errors.
Overlapping test runs must not be summed. All nine changed Python files pass
Ruff; the owned diff passes whitespace checks.

JUnit SHA-256:
`c32596a6ba55765395cbeb24fe70ce0c9b511bd33d0494998b8fb70b649dfdec`.
The retained local report is
`C:/Users/Sansk/.codex/worktrees/resume-engine/semantic-qa-20261008/focused.xml`.

## Reproduction environment

Use an isolated database whose name ends in `_test`, with the committed schema
through `0064`. This audit used `latexy_engine_semantic_20261008_test` and separate
QA Redis indices 11/10, never the development queue or another agent's indices.
The QA image was `latexy-engine-qa:20261007-v2`; the repository mount was read-only.
The local env file contained QA configuration, not production credentials.

From `backend`, with `DATABASE_URL` and `TEST_DATABASE_URL` naming that isolated
database, and `TEST_REDIS_URL` / `TEST_REDIS_CACHE_URL` naming its isolated Redis:

```text
python -m pytest -p no:cacheprovider -o addopts= -q --junitxml=/evidence/focused.xml \
  test/test_pdf_imports.py test/test_resume_structure_db.py \
  test/test_resume_durable_ledger.py test/test_resume_private_stage_fingerprint.py \
  test/test_resume_credential_scope.py test/test_resume_stage_checkpoints.py \
  test/test_imported_identity_db.py test/test_resume_acceptance_dependencies.py \
  test/test_resume_provider_fairness.py test/test_resume_semantic_engine.py \
  test/test_resume_structure.py test/test_imported_identity.py
```

Infrastructure checks remained enabled. Route-function integration exercises
real storage/transactions and owner checks, with synthetic provider responses;
it is not live browser authentication, paid model-quality certification, or
production PDF-import acceptance. These repairs do not certify renderer speed,
the complete frozen backend suite, production rollout, or release readiness.
