# Dodo payment acceptance — 8 October 2026

This continues draft PR [#1834](https://github.com/sanskarpan/Latexy/pull/1834)
after reviewing and fast-forwarding to `cf1beb4673413f1c1b44dc5f86bab0c5d58aaeb8`.
Earlier reports are dated checkpoints, not evidence that every later revision
passed the same checks. All provider operations here used Dodo test mode and
owned disposable `example.com` identities. Credentials and private fixture
state remain in ignored local files.

## Review findings and implementation

- The latest commits renumbered Dodo migrations to 0065–0067 after OAuth and
  engine migrations. The original Windows database was still at the old Dodo
  0061. Running ordinary upgrade against that marker would skip missing engine
  work and re-run already applied billing changes. A guarded transactional
  bridge now verifies the exact old schema, applies only the missing OAuth and
  engine migrations, and advances the marker to the single repository head.
- The adapter now constructs its network origin from official test/live URL
  literals, permits only supported methods and resource paths, and refuses
  redirects. It has a total request deadline in addition to HTTPX I/O timeouts.
  Fresh CodeQL results are required before declaring the previous SSRF finding
  cleared.
- Authenticated, bodyless `POST /subscription/reconcile` resolves only the
  owner's stored current checkout. Provider checkout, payment, and subscription
  IDs, customer, metadata, product, quantity, tax basis, currency, quote and paid
  state must agree. Browser redirect query parameters do not grant access.
- Recurring Dodo payment responses can have `product_cart: null`. Recovery then
  derives product evidence from the independently verified linked subscription;
  an explicit wrong or empty cart is rejected. This was confirmed with a real
  BYOK payment, not inferred from fixtures.
- Recovery refreshes authoritative rows under locks, follows intent-then-user
  lock order, rechecks ownership and preserves newer lifecycle/cancellation
  changes. An active lifecycle row alone is insufficient proof of paid access.
  Redis uses a 75-second lease and a separate 20-second provider-read cooldown.
- Terminal subscription events cannot reopen failed, cancelled, expired or
  refunded intents. A settled refund ID cannot later change amount/currency or
  repeat referral reversals.
- Partial refund requests now use the documented `items` array and require an
  explicit item and positive amount. The previous unsupported top-level amount
  could have been interpreted as a full refund. Full refund is an explicit
  separate call. Current SDK contracts are listed in the sources below.
- Billing downgrades refuse to discard provider identifiers, webhook/refund
  evidence, immutable tax quotes or coupon intent links. Rollback after billing
  activity requires a verified backup and reconciliation.
- The billing UI performs recovery after return and offers an authenticated
  status retry. It obtains access from `/subscription/current`; pending payments
  stay pending and network failures remain actionable.

## Original database bridge

Before stopping API, worker, beat and Flower, a PostgreSQL custom-format backup
was saved outside Git (277,302 bytes). SHA-256:

`09E2F844330B4715779A344DBF2C95B764C75B27F8122C26C79FA753758E3658`

A restored clone reached 0067 with identical protected row fingerprints. A
forced post-migration failure on a second clone rolled back both DDL and the
marker to old 0061, with the same fingerprints. Repeat execution was refused.
The original local database then passed dry-run and the bridge transaction.
Before/after counts and hashes matched for 8 payments, 11 subscriptions,
51 webhook records, 2 coupon redemptions, 1 coupon, 0 refunds and all 10 user
entitlement records. The original database is now at **0067 (head)**.

Subsequent sandbox payment/recovery operations legitimately change these
records; the matching fingerprints describe the bridge transaction alone.

## Real enabled-SKU matrix

Amounts are minor units of the actual charged payment currency. Each row was
checked against provider GETs, one owned local paid ledger row, and the
authenticated account endpoint. All six provider subscriptions subsequently
confirmed `cancel_at_next_billing_date=true`; paid access continues through the
current cycle while cancellation is scheduled.

| Case | Charged amount | Payment ID | Subscription ID |
| --- | ---: | --- | --- |
| Basic Annual | INR 287100 | `pay_0NpBFToZYAPEf9Ld1BImg` | `sub_0NpBFToofexrxQtNiQ42D` |
| Pro Monthly | INR 59900 | `pay_0NpBHD8AuoPbvQfwR2QTp` | `sub_0NpBHD8JynC6c0LsWrIFs` |
| Pro Annual | INR 575000 | `pay_0NpINpPlNfZaE2juU342d` | `sub_0NpINpPsvbVl8mmS9OfJk` |
| BYOK Monthly | INR 19900 | `pay_0NpDEs97YDRHKvXB3C3eu` | `sub_0NpDEs9EKULDdOArcs81C` |
| BYOK Annual | INR 191000 | `pay_0NpDF8jzyneZMLXyBLXsZ` | `sub_0NpDF8k92q0yxzwrnWc0D` |
| Team Monthly | INR 249900 | `pay_0NpIP4GB06rBmFS2l2CqG` | `sub_0NpIP4GUdP0xsPj3vG3zJ` |

BYOK Monthly had succeeded at Dodo while the relay was offline and the local
account still had Free access. The new owner-scoped recovery recorded that
existing payment and restored BYOK without another checkout. BYOK Annual was
already paid locally and remained unchanged. The original failed Pro Annual
checkout was conclusively closed through provider recovery before one new
checkout. The unused Team checkout had no provider payment before its pending
local intent was closed and one replacement session created.

Student checkout remains pending at the user's explicit request; no academic
mailbox was substituted. Weekly/Lifetime remain unavailable because their
configured prices are absent.

## Refund evidence

The corrected item-based partial request for BYOK Monthly (amount 1, tax
inclusive, explicit product ID) was rejected with HTTP 400
`PARTIAL_REFUND_NOT_ALLOWED`. Its provider line-items resource reports USD while
the charged payment is INR; no implicit conversion was performed.

An explicitly separate full refund was accepted for **INR 19900**:
`ref_0NpIPlsNtWiRNXJAZb27m`. At the latest read-only check it is **pending**.
The provider payment remains succeeded, the local payment remains paid, and no
`refund.%` event has reached the signed webhook inbox. Access remains BYOK with
cancellation scheduled. Acceptance is not evidence of settled refund handling.
No synthetic webhook, signature bypass, wallet funding or support message was
used. Earlier 409 wallet errors remain historical observations rather than the
current full-refund outcome.

## Validation checkpoint

- 305 focused billing/quota/manifest/bridge checks passed in a whole-repository
  Linux QA image. Windows Bash subprocess manifest failures did not reproduce
  there. The Linux image adds Git for shell fixtures only.
- Current frozen-lock frontend validation passed: **178 files / 1105 tests**,
  TypeScript, and full ESLint. Host `node_modules` was stale and lacked the
  newly locked test-only selector parser; that host run is not the final result.
- Recovery/refund/correctness checks passed, including later real-shape null
  cart regressions. A final combined payment suite, broader backend run and
  current-source production build are still being recorded.
- The dev frontend returned HTTP 500 after the Team checkout redirect and its
  login route was slow to compile. Runtime diagnosis is in progress; this is not
  yet a completed local UI acceptance result.

## Remaining release conditions

1. Confirm the provider's USD subscription/line-item representation versus
   actual INR charges, including recurring changes and proration. Existing
   exact charged-payment quote validation remains enforced; no conversion or
   relaxation was introduced.
2. Observe the accepted full refund reach terminal state and its genuine signed
   delivery, then verify ledger/access and duplicate delivery behavior.
3. Complete current-source runtime/build/backend acceptance and fresh GitHub
   security checks.
4. Keep Student pending until the user provides an authorized academic mailbox.
   Reconcile legacy live Razorpay mandates before any production cutover.

No additional issue was closed solely because implementation exists in this
unmerged draft PR. Earlier issue closure evidence remains in `ISSUES.md`.

## Primary provider contracts

- [Official Dodo API/SDK index](https://github.com/dodopayments/dodopayments-python/blob/main/api.md)
- [Checkout status schema](https://github.com/dodopayments/dodopayments-python/blob/main/src/dodopayments/types/checkout_session_status.py)
- [Refund creation parameters](https://github.com/dodopayments/dodopayments-python/blob/main/src/dodopayments/types/refund_create_params.py)
