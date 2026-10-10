import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const BILLING_SOURCE = readFileSync(new URL('../app/billing/page.tsx', import.meta.url), 'utf8')
const CARD_SOURCE = readFileSync(new URL('../components/billing/PricingCard.tsx', import.meta.url), 'utf8')

describe('B57 pricing contract', () => {
  it('opens the Dodo hosted checkout returned by the backend', () => {
    expect(BILLING_SOURCE).toContain('result.data.shortUrl')
    expect(BILLING_SOURCE).toContain('window.location.assign(result.data.shortUrl)')
    expect(BILLING_SOURCE).toContain('openInTab(checkoutTab, result.data.shortUrl)')
    expect(BILLING_SOURCE).not.toContain('order_id:')
  })

  it('does not invent unavailable B57 prices in the card', () => {
    expect(CARD_SOURCE).toContain("plan.purchase_type === 'one_time' ? 'one-time payment'")
    expect(CARD_SOURCE).toContain("plan.id === 'free'")
    expect(CARD_SOURCE).toContain('No payment required')
    expect(BILLING_SOURCE).toContain("['free', 'basic', 'pro', 'byok', 'student', 'team', 'weekly', 'lifetime']")
  })

  it('does not offer student checkout while the provider is unavailable', () => {
    expect(BILLING_SOURCE).toContain("planId !== 'free' && billingStatus && !billingStatus.available")
    expect(BILLING_SOURCE).not.toContain("planId !== 'student'")
  })
})
