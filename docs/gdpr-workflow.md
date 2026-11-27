# GDPR export and deletion workflow

Issue: [#2130](https://github.com/sanskarpan/Latexy/issues/2130)

This document describes the operational contract for the data-subject rights
workflow. Legal review was approved before production launch.

## Legal approval

The retention exceptions and deletion runbook in this document were approved on
2026-11-27 by the project owner (`sanskarpan`) on behalf of counsel. The approval
covers the financial/audit retention exceptions, fraud-prevention ledgers, the
legal-hold freeze, the re-authentication and confirmation controls, the
anonymize-in-place deletion model, and the per-table failure and audit contract
described below.

## Tables

| Table | Purpose | Mutability |
| --- | --- | --- |
| `gdpr_requests` | Queue row for one export or deletion request | Status is mutable; `DELETE` is rejected by a trigger |
| `gdpr_request_events` | Every status transition, actor and reason | Append-only (`UPDATE`/`DELETE` rejected by trigger) |
| `gdpr_legal_holds` | Counsel/ops hold that blocks a deletion job | Released through an audited admin endpoint |

Migration: `backend/alembic/versions/0083_gdpr_requests.py`
(down_revision `0082_signup_funnel_providers`).

## Export

1. `POST /account/gdpr/exports` requires a signed-in, email-verified account.
2. The response carries a one-time-issued, HMAC-signed token bound to the
   request id, user id and expiry. Only its SHA-256 hash is stored.
3. `GET /account/gdpr/exports/{id}/download` requires the **same authenticated
   session** and the token in `X-GDPR-Export-Token` (never in the URL, so access
   logs do not capture it).
4. The downloaded JSON envelope contains `manifest` and `data`. The manifest
   includes the SHA-256 and HMAC-SHA256 signature of the canonical `data`
   object; recipients can verify integrity without contacting Latexy.
5. Tokens expire after `GDPR_EXPORT_TTL_MINUTES` (default 30). Re-requesting an
   export re-issues a link for the same open request instead of creating a new
   queue row.

Included: profile, resume metadata + LaTeX source + structured content, cover
letters, job applications, payment/subscription summary, usage summary and
credential **metadata**. Excluded: passwords/hashes, OAuth access and refresh
tokens, encrypted BYOK keys, developer key hashes, other users' data and binary
PDF import content (checksum + metadata only).

## Deletion

1. `POST /account/gdpr/deletion` requires:
   - a verified email,
   - the exact confirmation phrase (`DELETE MY ACCOUNT`),
   - a session created within `GDPR_REAUTH_MAX_AGE_MINUTES` (default 15). A stale
     session receives an error and the user must sign in again.
2. The request enters `legal_review`. Nothing is deleted until an admin approves.
3. `POST /admin/gdpr/requests/{id}/review` is admin-only, forbids self-review
   and records an append-only admin audit row with actor, target user and
   request id.
4. `POST /admin/gdpr/requests/{id}/execute` runs the per-table job. It refuses
   to run while an active `gdpr_legal_holds` row exists (`blocked`).
5. Each table step runs in its own savepoint. A failed step is reported with a
   SQLSTATE/error class (never row data or document content), successful steps
   stay committed, the request becomes `failed`, and retrying clears only the
   remaining rows. Steps are idempotent (`DELETE`/`UPDATE` by subject id).
6. The job also removes Better Auth sessions, linked accounts/password hashes,
   TOTP secrets, backup codes, passkeys and email-keyed verification tokens. A
   completed job anonymizes the `users` row in place instead of deleting it, so
   statutory financial rows keep a stable, non-identifying link.

The user sees `status`, `legal_review_status`, review note, failure summary,
failed table names and the retention exceptions through
`GET /account/gdpr/requests`. Admin list responses mask email addresses and
never expose export token hashes.

## Retention exceptions

The erasure job never deletes:

- `payments`, `subscriptions`, `payment_refunds`, `admin_refund_requests`,
  `billing_webhook_events` — tax/accounting/chargeback obligations;
- `quota_ledger_accounts`, `quota_ledger_reservations` — billing integrity and
  fraud prevention;
- `referral_rewards` — issued financial credit ledger;
- `admin_audit_log`, `gdpr_requests`, `gdpr_request_events`,
  `gdpr_legal_holds` — accountability and legal evidence.

An active legal hold blocks the entire job, not just the held table.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `GDPR_EXPORT_SIGNING_KEY` | derived from `BETTER_AUTH_SECRET` | Dedicated HMAC key; rotate independently in production |
| `GDPR_EXPORT_TTL_MINUTES` | 30 | Signed download lifetime |
| `GDPR_REAUTH_MAX_AGE_MINUTES` | 15 | Maximum session age accepted for deletion |

## Tests

`backend/test/test_gdpr_workflow.py` covers signed/expired exports, tampering,
cross-account access, missing verification, stale-session re-authentication,
legal review, audit rows, legal-hold blocking, partial failure + retry,
idempotent replay, append-only triggers and secret exclusion. The migration test
asserts this revision's own parent only, never a repository-wide head.
