import { readFileSync } from 'node:fs'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import PricingCard from '@/components/billing/PricingCard'
import { apiAllowance, catalogPlansForPeriod, quotaLimitUpdate, type CatalogPlan } from '@/lib/plan-catalog'

const plan = (id: string, overrides: Partial<CatalogPlan> = {}): CatalogPlan => ({
  id, name: id, price: id === 'free' ? 0 : 29900, currency: 'INR', interval: 'month',
  billing_period: 'monthly', visible: true, purchasable: true,
  features: { compilations: '10 / day', optimizations: '3 / month', historyRetention: 0, prioritySupport: false, apiAccess: true, apiDailyLimit: 10 },
  ...overrides,
})

describe('shared plan catalog', () => {
  it('uses server order and visibility rather than marketing plan arrays', () => {
    const plans = {
      free: plan('free', { display_order: 10 }),
      basic: plan('basic', { display_order: 3 }),
      hidden: plan('hidden', { visible: false, display_order: 0 }),
    }
    expect(catalogPlansForPeriod(plans, 'monthly').map((p) => p.id)).toEqual(['basic', 'free'])
  })

  it('switches annual variants while preserving offers without an annual counterpart', () => {
    const plans = {
      free: plan('free'), basic: plan('basic'),
      basic_annual: plan('basic_annual', { billing_period: 'annual', interval: 'year' }),
      student: plan('student'),
      weekly: plan('weekly', { billing_period: 'weekly', interval: 'week' }),
    }
    expect(catalogPlansForPeriod(plans, 'monthly').map((p) => p.id)).toEqual(['free', 'basic', 'student', 'weekly'])
    expect(catalogPlansForPeriod(plans, 'annual').map((p) => p.id)).toEqual(['free', 'basic_annual', 'student'])
  })

  it('advertises the intentional free API daily allowance', () => {
    expect(apiAllowance(plan('free'))).toBe('10 / day')
    const html = renderToStaticMarkup(createElement(PricingCard, { plan: plan('free'), onSelectPlan: () => {} }))
    expect(html).toContain('API requests')
    expect(html).toContain('10 / day')
    expect(html).toContain('No payment required')
  })

  it('renders a retired SKU but disables starting a new purchase', () => {
    const html = renderToStaticMarkup(createElement(PricingCard, {
      plan: plan('pro', { purchasable: false, unavailable_reason: 'Sales paused' }), onSelectPlan: () => {},
    }))
    expect(html).toContain('disabled=""')
    expect(html).toContain('Sales paused')
  })

  it('never presents a disabled API capability as included', () => {
    const entry = plan('free')
    entry.features.apiAccess = false
    expect(apiAllowance(entry)).toBe('Unavailable')
  })

  it('reads the same API and card for public pricing and billing', () => {
    const publicSource = readFileSync(new URL('../components/billing/PublicPlanCatalog.tsx', import.meta.url), 'utf8')
    const billingSource = readFileSync(new URL('../app/billing/page.tsx', import.meta.url), 'utf8')
    for (const source of [publicSource, billingSource]) {
      expect(source).toContain('apiClient.getSubscriptionPlans()')
      expect(source).toContain('catalogPlansForPeriod(plans,')
      expect(source).toContain('<PricingCard')
    }
  })

  it('only exposes permitted catalog edits and passes the current version', () => {
    const source = readFileSync(new URL('../components/admin/AdminPlanCatalog.tsx', import.meta.url), 'utf8')
    expect(source).toContain('version: plan.version ?? 1')
    expect(source).toContain('disabled={saving || isFree}')
    expect(source).toContain('Configured price (read-only)')
    expect(source).toContain('Reload catalog')
    expect(source).not.toContain('setPrice')
  })
})


describe('quota limit editing', () => {
  it('supports zero, positive integers and explicit unlimited without a window field', () => {
    expect(quotaLimitUpdate(2, '0', false)).toEqual({ version: 2, limit: 0 })
    expect(quotaLimitUpdate(1, '25', false)).toEqual({ version: 1, limit: 25 })
    expect(quotaLimitUpdate(4, '', true)).toEqual({ version: 4, limit: null })
  })

  it.each(['', ' ', '-1', '1.5', 'NaN', 'Infinity', '1000000001'])('rejects invalid limit %s', (limit) => {
    expect(quotaLimitUpdate(1, limit, false)).toBeNull()
  })

  it('rejects missing or fractional versions', () => {
    expect(quotaLimitUpdate(0, '10', false)).toBeNull()
    expect(quotaLimitUpdate(1.5, '10', false)).toBeNull()
  })

  it('discloses existing-subscriber and usage-window effects', () => {
    const source = readFileSync(new URL('../components/admin/AdminPlanCatalog.tsx', import.meta.url), 'utf8')
    expect(source).toContain('including existing subscribers')
    expect(source).toContain('Current usage, reset windows and refund receipts stay unchanged')
    expect(source).toContain('apiClient.updateAdminPlanQuota')
    expect(source).toContain('Fixed reset window:')
  })
})
