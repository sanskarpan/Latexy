# Email delivery, bounce, and complaint monitoring (F7 / #2117)

Latexy sends transactional and compiled-document email through Resend or SMTP.
Resend delivery evidence is ingested through a signed webhook and summarized in
the admin-only **Email health** tab. The implementation is intentionally
flag-driven: nothing is sent by the monitoring path.

## Endpoint and signature verification

- `POST /webhooks/resend` (also `POST /email/webhooks/resend`)
- Configure `RESEND_WEBHOOK_SECRET` from the Resend webhook detail page. In
  production it is provisioned as the dedicated Modal secret
  `latexy-resend-webhook`, which `modal_app.py` attaches to the backend.
- Resend uses the Svix signature scheme. The endpoint verifies the raw request
  body against `svix-id`, `svix-timestamp`, and `svix-signature` before parsing
  JSON. Standard-webhook `webhook-*` header aliases are accepted for compatible
  relays.
- Signatures older than five minutes are rejected. A missing secret fails
  closed with `503`; invalid or malformed requests get `400`.
- The raw payload is never logged or persisted.

## Event ingestion and idempotency

Events are stored in `email_delivery_events`:

| Field | Purpose |
| --- | --- |
| `provider_event_id` | Signed webhook id; unique per provider, so retries are idempotent. |
| `provider_message_id` | Resend email id (`email_id` / suppression `source_id`). |
| `delivery_id` | Maps to `document_email_deliveries.provider_message_id` when known. |
| `event_type` | Normalized `email.*` / `suppression.*` type, or `unknown`. |
| `bounce_type`, `bounce_subtype` | Bounded operational labels only. |
| `retryable` | True only for a delivery delay or temporary bounce. |
| `recipient_hash` | SHA-256 of the normalized mailbox; never the address. |

Unknown event types are acknowledged and recorded as `unknown` so Resend does
not retry them forever. Duplicate webhook ids return `duplicate` without
creating a second row or repeating suppression/delivery side effects. Genuine
storage outages return `503`, which lets Resend retry the same signed event.
Delivery mapping captures the provider email id returned by Resend when a
compiled document is accepted.

## Retry policy

Only transient failures are retryable:

- Resend `429`, `5xx`, timeouts, and network errors are retryable.
- Validation errors, invalid recipients, authentication/configuration errors,
  and other `4xx` responses are permanent and exhaust the delivery attempt.
- `email.delivery_delayed` and temporary bounces are labelled retryable.
- Hard bounces, complaints, `email.failed`, and suppressions are never retried.

The existing bounded document-delivery backoff remains the only automatic
retry path.

## Suppression and reputation handling

- Resend automatically suppresses addresses after a hard bounce or spam
  complaint. That provider-side suppression remains authoritative.
- Latexy mirrors suppression locally in `email_recipient_suppressions`, keyed by
  a one-way recipient digest. `suppression.added` / `suppression.removed`,
  hard bounces, complaints, and explicit provider suppressions update this state.
- Before a compiled-document email is submitted, the document delivery route
  and recovery worker check local suppression and refuse to send to a suppressed
  mailbox.
- Transient bounces do **not** suppress an address.
- Review thresholds surfaced by the admin view: complaint rate at or above
  `0.1%` or bounce rate at or above `5%` puts health in `review`. Any
  bounce/complaint/failed event below that shows `watch`.
- A suppression row linked to a document delivery is deleted with that
  delivery through the existing foreign-key cascade. Resend's own suppression
  list remains authoritative for addresses used outside document delivery and
  must be managed in Resend.

Operational response:

1. Check **Admin → Email health** for the window's rates, recent failures and
   suppression status.
2. Confirm the cause in Resend (hard bounce, complaint, domain reputation or
   suppression) without copying recipient data into tickets.
3. Do not remove provider suppression for a hard bounce or complaint unless the
   mailbox owner explicitly requests it and the address has been re-verified.
4. If complaints exceed `0.1%`, pause non-essential email, review list quality
   and sending volume, then re-check the trend before resuming.

## Admin view and privacy

`GET /admin/email/health?days=30` requires an admin actor. It returns:

- aggregate outbound acceptance counts and event counts;
- delivery, bounce and complaint rates with a five-outcome minimum sample
  (rates are `null` and `rates_withheld=true` below five);
- recent failure metadata (event type, bounce labels, retryable flag, whether a
  delivery was mapped, delivery status and time);
- active suppression count, additions/removals in the period, review thresholds
  and the local/provider policy.

The response and UI never include recipient addresses, subjects, message
bodies, provider payloads, raw webhook ids, document content, or secrets.
