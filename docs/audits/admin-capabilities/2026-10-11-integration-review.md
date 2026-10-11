# Capability catalog integration review — 11 October 2026

## Target and current context

This review updates PR [#1864](https://github.com/sanskarpan/Latexy/pull/1864) against main `fb68ae06`, rather than its earlier base `bdee4892`. The previous successful CI at `90ba4b3f` does not verify this integration.

Newly merged work includes Dodo billing and guided résumé reliability (#1834), GitHub completion-ticket ownership (#1851), onboarding account isolation (#1858), frontend dependency updates (#1859), and legacy OAuth callback ownership (#1861). Engine PR #1833 remains open and is not silently integrated.

The owner explicitly confirmed that **new core résumé creation, content/source editing, and compilation must also have admin switches**. Security protections, account/admin recovery, existing document reads/downloads, deletion, revocation, cancellation, refund accounting and already-admitted fulfillment remain available. Product permissions do not bypass resource ownership or collaborator permissions.

## Gaps identified before changes

1. The capability migration chain branched from `0059`, while current main advances through `0068` (the webhook resource identity migration). A normal merge would create multiple Alembic heads.
2. Plan merchandising consulted Razorpay IDs even though current main uses Dodo products. Dodo-only annual offers could appear unconfigured.
3. The catalog treated creation, source editing and compilation as immutable baselines. Direct compile routes, generic job admission and developer compile needed the same new-work restrictions as the UI.
4. New institutional membership/domain setup and new billing purchases were grouped with mandatory tenant routing and billing recovery.
5. Main's newly merged visual editor, guided PDF preview, save-before-export and owner-isolation behavior needed explicit preservation and capability wiring.
6. Some nested editor controls remained visible or actionable after revocation: linked-parent comparison, the academic-CV banner trigger, and stale spellcheck quick fixes. Source recovery was also incorrectly grouped with the optional visual-mode switch.
7. The integration inventory still labelled newly merged PR groups as unmerged. Coverage must follow reachable code, rather than an unchanged feature count.
8. Combined quick-tailor, batch-tailor and academic conversion dispatched compilation without the new compilation gate. Secondary optimize, cover-letter and comparison preview controls also needed that gate.
9. Resolving Settings conflicts dropped main's protection against callback-ticket redispatch across account-boundary remounts. Existing ownership regressions must pass after capability controls are layered onto the merged implementation.
10. Real browser compilation exposed a delivery retry gap: Retry fetched only the offline cache rather than the currently owned, completed PDF job. Retry must not admit another compilation and must discard stale owner/document/job responses.
11. Quick Tailor checked only part of its combined admission dependencies. Its workspace entry and stale modal submission must require all six permissions (`d04`, `d01`, `d18`, `c05`, `b01`, `c01`). AI optimization similarly needs source editing and document-processing permissions as well as compilation.
12. Monaco's imperative insert/fix methods and design/linter/generated-source controls could mutate local source while editing was disabled. Source mutation callbacks need current permission guards in addition to hidden buttons and the editor's read-only setting.
13. Student verification translated a typed capability denial into a generic verification error. It must preserve the 403 admission denial, retain the verification token and release the verification lock without contacting the payment provider.
14. Browser fixtures still assumed that missing permissions grant manual compilation, and a live-catalog test targeted main's static marketing `/pricing` route. Fixtures must explicitly grant core work, test policy-outage denial and exercise the live catalog on `/billing`.
15. Checkpoint recovery used local arbitrary-source callbacks instead of the authenticated stored-version endpoint. Recovery must restore the server-owned checkpoint, reject stale account/document responses, and update the visible read-only source without reopening arbitrary editor mutations.
16. Revocation during a successful admission response discarded already-admitted job identities. Starting and retrying remain gated; the same owner's admitted job must retain progress/results, while applying new source remains subject to current editing access.

## Verification discipline

Work uses an isolated managed checkout. Local runtime verification uses dedicated loopback PostgreSQL/Redis services and synthetic accounts, with model, email and payment providers disabled. Original application data and services are preserved. Global, role, family, exact-SKU and parent denials must remain effective; missing/failed policy reads must not grant new work.

Verification results and remaining limits will be recorded after the integrated implementation is frozen. Inventory/policy combinations are distinct from individually exercised browser or provider workflows. Earlier screenshots, counts and CI results remain historical evidence.

The integration follow-up passed 348 focused backend tests for route/role denials, Student-token/lock preservation, Modal preflight and test isolation, plus 61 real-engine/cache/output-boundary and generated-inventory tests. The earlier complete backend run had 6,254 passes and five failures: two CJK cold-cache timeouts, two stale preflight fixtures and a matrix changed during collection. The hosted font preparation and current-head fixtures resolved those failures in focused reruns; a fresh complete backend run is required before merge. Frontend verification is repeated after the final recovery review.

## Database verification

A fresh isolated pgvector PostgreSQL 16 database was upgraded from base through released main revision `0068`, then through the single capability head `0072_capability_roles`. Two pre-existing global denials and three family/exact-SKU denials survived. The role seed contains 576 entries (four account contexts × 144 keys). Existing operational feature flags are retained, so the total global table count is larger than the gateable inventory.

The chain does not support databases stamped with the earlier unpublished draft IDs `0060_capability_catalog` through `0063_capability_roles`. No deployment of that draft lineage was identified. Deployment must inspect the actual revision; released main IDs remain unchanged. A draft-stamped database must be reconciled explicitly before upgrade, without blindly restamping or rewriting released migration history.

## Inventory and billing boundaries

The inventory contains 129 product entries: 113 gateable capabilities and 16 immutable security, recovery and existing-data baselines. Including the 31 parent controls, the admin registry contains 160 entries with 144 switches. Global, account-role, plan-family, exact-SKU and ancestor permissions all intersect; a grant at one scope cannot override denial at another.

Main's compatibility rule for active, server-owned legacy subscriptions is retained. Such subscriptions may still resolve their existing paid family without a Dodo subscription identity; canceled subscriptions resolve to Free. Product capability denials still apply to those users. This integration is not a forced migration of legacy billing accounts. New purchases consult the target catalog SKU and its Dodo configuration. Provider identities are exposed only in the authorized admin catalog and remain read-only there.
