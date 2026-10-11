# Plan catalog and commercial safety

The Admin → Plan Catalog screen owns the customer-facing merchandising of the eleven existing billing SKUs. Public `/pricing`, `/billing` plan cards and current-subscription display use the same catalog service. Numeric compile, optimization and AI-assist limits are versioned per exact SKU. Pricing cards derive capability access from the same global, account-role, family, concrete-SKU and parent-feature decisions used by backend enforcement. The intentional free Developer API allowance is displayed from its enforced daily quota.

## Editable controls

Administrators can change a stable SKU's display name, description, sort order, pricing visibility and availability for **new purchases**. Updates require the current integer version; concurrent or stale edits return HTTP 409, preserving the later administrator's changes. Each accepted update adds an audit snapshot in `plan_catalog_revisions`. The free fallback cannot be hidden or disabled.

Visibility and purchase availability are separate controls. Hiding a card does not prohibit a direct purchase request. Pause new purchases to retire an offer. The create-subscription endpoint resolves annual aliases before checking availability; student-verification completion also checks availability. Missing or failed catalog reads never silently permit a checkout. New purchases also require `i01`, including token-owner Student verification. Signed webhooks, existing payment reconciliation, cancellation and refunds remain recovery operations.

## Deliberate read-only boundaries

- SKU identity, entitlement family, currency, interval, amounts and provider price/plan IDs are read-only in this screen.
- Compile, optimization and AI-assist limits can be edited from 0 to 1,000,000,000, or set to unlimited. Their daily/monthly windows remain fixed. Developer API daily request limits remain operator-configured. The boolean capability matrix is a separate control; disabling a capability does not rewrite quota ledgers.
- New commercial amounts require an operator-reviewed **new configured SKU/version** and a reviewed provider mapping through the existing deployment/payment workflow. This feature does not create new commercial SKUs or mutate any payment provider.
- Existing subscriptions, outstanding payment verification, refunds, cancellation, subscription IDs and period boundaries are not modified by catalog edits. Pausing sales does not revoke an existing plan's features. Feature-matrix changes are the explicit way to restrict capability access.
- Unconfigured weekly and lifetime offers remain absent from public pricing; they cannot become a free or payable offer through an admin switch. Unconfigured annual offers remain unavailable for purchase.

The admin view identifies the provider as Dodo and displays the configured product mapping read-only. Product IDs never appear in the public catalog. All paid offers, including annual aliases, require an operator-configured Dodo product; a switch cannot create a provider product. No provider calls or real payments are required to operate catalog editing, migrations or tests.

## Quota changes

Quota overrides apply to the next admission for every existing or new subscriber on the exact SKU. A monthly Pro override does not implicitly change Pro Annual, Student, Weekly or Lifetime; those retain their configured family defaults unless independently overridden. SKU aliases such as `team_member` resolve to the canonical Team SKU.

Edits require the current quota version and add an audit revision. Counter keys, current usage, reset windows, in-flight job receipts and exactly-once refunds are unchanged. Lowering a limit below existing usage immediately denies new requests; raising it allows new requests against the same usage. Unlimited continues counting usage. Database-policy errors deny new admissions rather than falling back to stale or unlimited defaults. The UI explicitly discloses that these changes affect existing subscribers and that unlimited can increase provider costs.

## Recovery and rollout

Run Alembic through the single head `0072_capability_roles` before deploying these application changes. The released-main revision `0068` is followed by `0069_capability_catalog`, `0070_plan_catalog`, `0071_plan_quotas` and `0072_capability_roles`, adding capability/catalog/quota/role controls without rewriting user, subscription, payment or refund records. The earlier unpublished draft revision IDs are unsupported; inspect the database revision before rollout (see [integration review](../audits/admin-capabilities/2026-10-11-integration-review.md)). Unedited SKUs resolve to the stable application defaults; their first edit creates a versioned row atomically.

Catalog and entitlement failures do not block an existing subscriber from retrieving their subscription identity and cancellation information. The current-subscription display reads catalog state in a separate transaction and labels optional feature availability as unavailable if that lookup fails.

A migration downgrade retains catalog settings and audit snapshots. Re-upgrade validates the preserved table shape before reuse. Rolling back application code can stop enforcing controls introduced in this version; retaining rows does not teach older binaries about them. Avoid mixed application versions when relying on immediate sales or capability restrictions.

## API

- GET `/subscription/plans`: public keyed catalog plus billing availability
- GET `/admin/plan-catalog`: admin-only complete catalog, including hidden/unconfigured SKUs and read-only commercial configuration
- PATCH `/admin/plan-catalog/{sku}`: admin-only merchandising, strict field allow-list, current `version` required
- PATCH `/admin/plan-catalog/{sku}/quotas/{dimension}`: admin-only limit changes, current `version` and explicit `limit` required
- GET `/subscription/current`: existing subscription identity with catalog-derived display copy; remains readable if catalog availability fails

## Verification

Backend regressions cover public/admin consistency, free API allowance, hidden and paused offers, unknown SKU/field rejection, strict input validation, free fallback protection, audit snapshots, real concurrent edits, current-display outage recovery, unchanged existing subscriptions and non-destructive migration round-trips. Quota regressions cover strict bounds, exact SKU scope, concurrent edits, lower/raise/unlimited transitions on the same Redis counter, old-receipt exactly-once refunds, availability errors and non-destructive migration round trips. Existing B57 pricing and subscription regressions are included in focused verification.

Frontend unit tests cover shared period selection, canonical keyed IDs, display order, visibility, API allowance and disabled purchase controls. Browser tests cover public-pricing error/retry, monthly/annual switching, paused offers, admin save and version-conflict recovery. Run the repository's supported lint/typecheck and test commands before rollout.
