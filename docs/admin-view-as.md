# Audited read-only view-as-user

Issue: [#2125](https://github.com/sanskarpan/Latexy/issues/2125)

## What is implemented

Latexy intentionally does **not** implement full session impersonation. There
is no target-user session, cookie, password or token to steal, and an admin
never assumes the target's identity on product routes.

Instead, an admin can request a **read-only, server-composed snapshot** of one
explicit target user:

1. `POST /admin/view-as/requests` creates a normal two-person approval with
   `request_type=impersonation`, `payload.mode=view_as` and one target user id.
   The approval and its request audit expire within 5-15 minutes.
2. A different admin approves it. The requester cannot approve their own
   request, and the existing separation-of-duties constraints still apply.
3. `POST /admin/view-as/sessions` consumes the approved request exactly once
   and returns an opaque `lx_view_…` token. The token is stored only as a
   SHA-256 hash; it is never written to the audit log or any response after
   start.
4. `GET /admin/view-as/sessions/{id}` accepts that token in the
   `X-View-As-Token` header and returns the snapshot. The session is bound to
   the starting admin, one target, a fixed `read_only` scope and a hard
   15-minute expiry.
5. `POST /admin/view-as/sessions/{id}/end` closes the preview immediately and
   writes the closing audit row. Ending is idempotent.

The snapshot surfaces only:

- dashboard counts and activation booleans;
- resume titles, document type and timestamps (no LaTeX, structured content,
  prompts or job descriptions);
- plan, subscription metadata, effective feature state and quota;
- usage action names/counts and recent action names (no event metadata);
- the existing support billing timeline.

It never returns raw email/name, passwords, sessions, target cookies, API keys,
tokens, user agents, raw IP addresses or provider payloads. Target identity is
masked with the existing `mask_email`/`mask_name` helpers.

## Write refusal

`ViewAsReadOnlyMiddleware` runs before route handling. Any request that carries
`X-View-As-Token` is allowed only for preview `GET`/`HEAD` requests (and the
preview end control). Every other request, including product and admin
mutations, receives `403` with `code=view_as_read_only`. The token is not an
Authorization credential, so it cannot authenticate any non-preview route.

## Audit trail

Every transition writes an append-only `admin_audit_log` row:

- `admin.view_as.requested` (requesting admin, target, approval, reason);
- the existing `admin.approval.requested` / `admin.approval.approved` rows;
- `admin.view_as.started` (session, target, scope, expiry);
- `admin.view_as.expired` once when a token is first used after expiry;
- `admin.view_as.ended` (closing reason and actor).

Request id and server-observed context are captured by the shared audit helper.
No preview token, document body or raw target PII is stored in these rows.

## Limitation

Because this is a snapshot rather than a live target session, it cannot show
target-only UI state that requires the target's own session, does not exercise
the target's CSRF/session boundary, and cannot reproduce real-time target
mutation flows. That is deliberate: the feature is a diagnostic/support surface,
not an impersonation tool.

The migration `0101_view_as_user` is additive and reversible. The only stored
credential material is the SHA-256 token hash; deleting the operator or target
cascades the preview row.
