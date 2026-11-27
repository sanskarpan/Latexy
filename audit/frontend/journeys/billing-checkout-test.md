# Billing checkout in Dodo test mode - 2026-11-28

**Verdict:** checkout creation and webhook-driven activation PASS in test mode; hosted card entry was not automated.

## Setup

- Local backend: `ENVIRONMENT=test`, `DODO_MODE=test`, local Postgres `latexy_test` (`127.0.0.1:5435`), local Redis (`127.0.0.1:6380`).
- Synthetic free user with a direct DB session token (no production user data).
- Provider: Dodo **test mode** (`test.checkout.dodopayments.com`); no live charge possible.

## Checkout creation

`POST /subscription/create` with `planId=byok`, `billingPeriod=monthly`:

```json
{"success":true,"checkoutSessionId":"cks_...","shortUrl":"https://test.checkout.dodopayments.com/session/cks_...","checkoutType":"hosted"}
```

Local DB immediately after:

| Record | State |
|---|---|
| User | `subscription_plan=free`, `subscription_status=checkout_pending` |
| Subscription | plan `byok`, status `checkout_pending`, provider checkout session set, amount `19900` (₹199) |

The Dodo sandbox page rendered **“Latexy BYOK (Bring Your Own Key) (Sandbox) — ₹199.00/mo — Test Mode”**; screenshot: `checkout-test-page.png`.

## Webhook activation

A signed `payment.succeeded` webhook was sent to the local backend with the test webhook secret, the local intent metadata, the sandbox product ID, and `total_amount=19900`.

```text
POST /billing/webhook -> 200 {"status":"ok"}
```

Local DB after the webhook:

| Record | State |
|---|---|
| User | plan **byok**, status **active** |
| Subscription | plan **byok**, status **active**, period end set |
| Payment | ₹19,900 paise INR, status **paid** |
| Webhook inbox | status **processed**, `last_error=null` |

This validates the full local flow: checkout intent → provider hosted session → signed payment webhook → plan/payment activation.

## Limitation

The hosted Dodo page’s card-entry step was not automated; Dodo’s sandbox checkout UI kept the contact fields disabled and required its own interactive flow. The webhook path was therefore validated with a correctly signed test event rather than a real card capture. No live payment was attempted.

## Cleanup

- Local test payment, subscription, session and user deleted; remaining user count for the fixture: **0**.
- Local backend stopped.
- The unpaid sandbox checkout session is left to expire; it cannot charge.

## Issues affected

- Billing checkout blocker is now **test-mode checkout + activation PASS** rather than unexecuted.
- Hosted card-entry automation remains a manual/QA gap, not a product defect.
