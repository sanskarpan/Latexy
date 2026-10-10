import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const BILLING_SOURCE = readFileSync(new URL('../app/billing/page.tsx', import.meta.url), 'utf8')
const CARD_SOURCE = readFileSync(new URL('../components/billing/PricingCard.tsx', import.meta.url), 'utf8')

describe('B57 pricing contract', () => {
  it('renders lifetime as a one-time Razorpay Orders checkout', () => {
    expect(BILLING_SOURCE).toContain("checkoutType === 'one_time'")
    expect(BILLING_SOURCE).toContain('order_id: result.data.orderId')
    expect(BILLING_SOURCE).toContain('Payment received. Your Lifetime access will appear after verification.')
  })

  it('does not invent unavailable B57 prices in the card', () => {
    expect(CARD_SOURCE).toContain("plan.purchase_type === 'one_time' ? 'one-time payment'")
    expect(CARD_SOURCE).toContain("plan.id === 'free'")
    expect(CARD_SOURCE).toContain('No payment required')
    expect(BILLING_SOURCE).toContain('catalogPlansForPeriod(plans, billingPeriod)')
  })

  it('does not offer student checkout while the provider is unavailable', () => {
    expect(BILLING_SOURCE).toContain("planId !== 'free' && billingStatus && !billingStatus.available")
    expect(BILLING_SOURCE).not.toContain("planId !== 'student'")
  })
})
