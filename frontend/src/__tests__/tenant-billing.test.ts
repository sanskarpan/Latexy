import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('tenant billing and seat utilization view', () => {
  const page = read('../app/admin/tenant/page.tsx')
  const component = read('../components/admin/TenantBillingPanel.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('wires a dedicated billing panel into tenant administration', () => {
    expect(page).toContain("import TenantBillingPanel from '@/components/admin/TenantBillingPanel'")
    expect(page).toContain('<TenantBillingPanel')
    expect(page).toContain('tenantId={selected.id}')
    expect(page).toContain('requestContext={requestContext}')
  })

  it('calls the owner/admin billing and audited upgrade-intent endpoints with account context', () => {
    expect(apiClient).toContain('getTenantBilling(')
    expect(apiClient).toContain('`/tenants/${tenantId}/billing`')
    expect(apiClient).toContain('recordTenantUpgradeIntent(')
    expect(apiClient).toContain('`/tenants/${tenantId}/billing/upgrade-intent`')
    expect(apiClient).toContain('TenantUpgradeIntentResponse')
  })

  it('renders plan, active/invited/available seats and conversion', () => {
    expect(component).toContain('Billing &amp; seats')
    expect(component).toContain('Active seats')
    expect(component).toContain('Invited')
    expect(component).toContain('Available')
    expect(component).toContain('Seat limit')
    expect(component).toContain('Invite conversion')
    expect(component).toContain('invite_conversion')
    expect(component).toContain('minimum_cohort_size')
  })

  it('shows the CTA only from the server threshold and records the click', () => {
    expect(component).toContain('billing.upgrade.cta_visible')
    expect(component).toContain('billing.upgrade.cta_label')
    expect(component).toContain('billing.upgrade.threshold_percent')
    expect(component).toContain('apiClient.recordTenantUpgradeIntent(')
    expect(component).toContain("reason: 'intent_recorded'")
    expect(component).toContain('does not charge a card or change billing')
  })

  it('keeps unavailable subscription and seat mappings explicit', () => {
    expect(component).toContain('Renewal status unavailable')
    expect(component).toContain('billing.subscription.available')
    expect(component).toContain('billing.seats.invited_available')
    expect(component).toContain('Invitation store could not be read')
    expect(component).toContain('not linked to a subscription record')
  })

  it('isolates a billing failure from the rest of tenant management', () => {
    expect(component).toContain('Tenant management stays available even when billing details cannot load.')
    expect(component).toContain('Retry billing')
    expect(component).toContain('role="alert"')
  })

  it('never renders member identifiers, documents or payment credentials', () => {
    for (const forbidden of [
      'member_email',
      'owner_email',
      'user_id',
      'provider_subscription_id',
      'provider_customer_id',
      'card_number',
      'cvc',
      'payment_method',
      'dangerouslySetInnerHTML',
    ]) {
      expect(component).not.toContain(forbidden)
    }
    expect(component).not.toContain('localStorage')
    expect(component).not.toContain('document.cookie')
  })
})
