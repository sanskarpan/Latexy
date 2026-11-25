import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin revenue dashboard', () => {
    const billing = read('../components/admin/AdminBilling.tsx')
    const revenue = read('../components/admin/AdminRevenueBreakdown.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('wires the dedicated revenue breakdown into the revenue tab', () => {
        expect(billing).toContain("import AdminRevenueBreakdown from './AdminRevenueBreakdown'")
        expect(billing).toContain('<AdminRevenueBreakdown')
        expect(billing).toContain('granularity')
        expect(revenue).toContain('Revenue breakdown')
        expect(revenue).toContain('Plan mix & MRR normalization')
        expect(revenue).toContain('Chargebacks & disputes')
        expect(revenue).toContain('Revenue reconciliation')
    })

    it('shows daily and monthly revenue ranges with refunds and chargebacks', () => {
        expect(revenue).toContain("(['day', 'month'] as const)")
        expect(revenue).toContain("option === 'day' ? 'Daily' : 'Monthly'")
        expect(revenue).toContain('revenue_series')
        expect(revenue).toContain('gross_revenue_minor')
        expect(revenue).toContain('refunds_minor')
        expect(revenue).toContain('chargebacks_minor')
        expect(revenue).toContain('net_revenue_after_chargebacks_minor')
        expect(revenue).toContain('mrr_normalization')
        expect(revenue).toContain('by_interval')
    })

    it('renders reconciliation checks against payments and payment_refunds', () => {
        expect(revenue).toContain('view.checks.map')
        expect(revenue).toContain('gross_from_payments_minor')
        expect(revenue).toContain('refunded_from_payment_refunds_minor')
        expect(revenue).toContain('difference_minor')
        expect(revenue).toContain('Balanced')
        expect(revenue).toContain('Needs review')
        expect(revenue).toContain('test_mode_policy')
    })

    it('formats money with the explicit summary currency', () => {
        expect(revenue).toContain('formatMoney(minor / 100, currency)')
        expect(revenue).toContain('summary.currency')
        expect(billing).toContain('formatMoney(summary.mrr, summary.currency)')
        expect(billing).toContain('formatMoney(summary.gross_revenue, summary.currency)')
        expect(apiClient).toContain("qs.set('granularity', params.granularity)")
    })

    it('never renders customer identifiers, provider credentials, or payloads', () => {
        expect(revenue).not.toContain('email')
        expect(revenue).not.toContain('payload_sha256')
        expect(revenue).not.toContain('provider_payment_id')
        expect(revenue).not.toContain('DODO_API_KEY')
        expect(revenue).not.toContain('user_id')
    })
})
