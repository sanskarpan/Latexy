import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin weekly and lifetime plan health', () => {
    const billing = read('../components/admin/AdminBilling.tsx')
    const component = read('../components/admin/AdminPlanHealth.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('wires a dedicated plan-health section into the billing tab', () => {
        expect(billing).toContain("import AdminPlanHealth from './AdminPlanHealth'")
        expect(billing).toContain('<AdminPlanHealth />')
    })

    it('calls the admin-only aggregate endpoint', () => {
        expect(apiClient).toContain('AdminPlanHealthResponse')
        expect(apiClient).toContain('/admin/analytics/plan-health?days=')
        expect(component).toContain('getAdminPlanHealth')
    })

    it('renders active, new, cancelled, revenue, refunds and chargebacks per plan', () => {
        expect(component).toContain('const PLAN_ORDER = [')
        expect(component).toContain("'weekly'")
        expect(component).toContain("'lifetime'")
        expect(component).toContain('Active')
        expect(component).toContain('New')
        expect(component).toContain('cancelled in window')
        expect(component).toContain('Gross revenue')
        expect(component).toContain('Refunds')
        expect(component).toContain('Chargebacks')
        expect(component).toContain('Lifetime refund rate')
        expect(component).toContain('Renewal rate')
        expect(component).toContain('Churn')
        expect(component).toContain('Monthly cohort retention')
    })

    it('keeps suppression and advisory-only guardrails visible', () => {
        expect(component).toContain('minimum_cohort_size')
        expect(component).toContain('suppressed')
        expect(component).toContain('Advisory only.')
        expect(component).toContain('Human review is required')
        expect(component).toContain('does not')
        expect(component).toContain('refund, downgrade, cancel or grant access automatically')
        expect(component).toContain('auto action: none')
    })

    it('never renders customer identifiers, emails or provider payloads', () => {
        for (const forbidden of [
            'user_id',
            'customer_email',
            'recipient_email',
            'provider_payment_id',
            'provider_subscription_id',
            'payment_method',
            'dangerouslySetInnerHTML',
        ]) {
            expect(component).not.toContain(forbidden)
        }
    })
})
