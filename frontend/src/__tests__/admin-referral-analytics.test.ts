import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin referral programme analytics', () => {
    const growth = read('../components/admin/AdminGrowth.tsx')
    const component = read('../components/admin/AdminReferralAnalytics.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('wires a dedicated referral section into the Growth tab', () => {
        expect(growth).toContain(
            "import AdminReferralAnalytics from '@/components/admin/AdminReferralAnalytics'"
        )
        expect(growth).toContain('<AdminReferralAnalytics days={days} />')
    })

    it('calls the admin-only summary and CSV endpoints', () => {
        expect(apiClient).toContain('getAdminReferralSummary')
        expect(apiClient).toContain('/admin/referrals/summary')
        expect(apiClient).toContain('/admin/referrals/summary/export.csv')
        expect(component).toContain('getAdminReferralSummary')
        expect(component).toContain('downloadAdminReferralSummaryCsv')
    })

    it('renders every required referral signal and the programme issue link', () => {
        expect(component).toContain('Captured')
        expect(component).toContain('Qualified')
        expect(component).toContain('Paid conversion')
        expect(component).toContain('Reward ledger')
        expect(component).toContain('Rejection reasons')
        expect(component).toContain('Time to qualify')
        expect(component).toContain('Fraud review queue')
        expect(component).toContain('By plan')
        expect(component).toContain('Reconciliation')
        expect(component).toContain('issues/1341')
    })

    it('keeps suppression, privacy and no-automation guardrails visible', () => {
        expect(component).toContain('five-user floor')
        expect(component).toContain('aggregate-only')
        expect(component).toContain('No referral is paid out')
        expect(component).toContain('manual')
        expect(component).toContain('suppressed')
    })

    it('never renders raw referral or payment identifiers', () => {
        expect(component).not.toContain('code_digest')
        expect(component).not.toContain('device_fingerprint')
        expect(component).not.toContain('ip_address')
        expect(component).not.toContain('provider_payment_id')
        expect(component).not.toContain('payment_method')
    })
})
