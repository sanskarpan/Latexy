import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import {
    churnReasonLabel,
    cohortLabel,
    minorToMajor,
    movementDirectionLabel,
    movementLabel,
    planLabel,
    shareLabel,
    suppressedCohortNote,
} from '../lib/subscription-analytics'

describe('subscription analytics formatting', () => {
    it('treats backend amounts as minor units', () => {
        expect(minorToMajor(59900)).toBe(599)
        expect(minorToMajor(null)).toBe(0)
        expect(minorToMajor(Number.NaN)).toBe(0)
    })

    it('labels movements and plans without leaking raw enums', () => {
        expect(movementDirectionLabel('upgrade')).toBe('Upgrade')
        expect(movementDirectionLabel('downgrade')).toBe('Downgrade')
        expect(movementDirectionLabel('lateral')).toBe('Lateral')
        expect(movementLabel('Basic', 'Pro')).toBe('Basic → Pro')
        expect(planLabel('pro_annual')).toBe('Pro annual')
    })

    it('labels churn reasons and cohorts deterministically', () => {
        expect(churnReasonLabel('payment_failed')).toBe('Payment failed')
        expect(churnReasonLabel('cancellation_scheduled')).toBe('Cancel scheduled')
        expect(cohortLabel('2026-01')).toBe('Jan 2026')
        expect(cohortLabel('not-a-month')).toBe('not-a-month')
    })

    it('formats shares and suppression notes', () => {
        expect(shareLabel(33.333)).toBe('33.3%')
        expect(shareLabel(null)).toBe('0.0%')
        expect(suppressedCohortNote(5, 1)).toContain('cohort with fewer than 5')
        expect(suppressedCohortNote(5, 2)).toContain('cohorts with fewer than 5')
    })

    it('wires the admin-only subscriptions tab to the aggregate endpoint', () => {
        const page = readFileSync(new URL('../app/admin/page.tsx', import.meta.url), 'utf8')
        const component = readFileSync(
            new URL('../components/admin/AdminSubscriptions.tsx', import.meta.url),
            'utf8'
        )
        expect(page).toContain(
            "import AdminSubscriptions from '@/components/admin/AdminSubscriptions'"
        )
        expect(page).toContain("tab === 'subscriptions' && <AdminSubscriptions />")
        expect(component).toContain('getAdminSubscriptionAnalytics')
        expect(component).toContain('minimum_cohort_size')
        expect(component).toContain('suppressed')
    })
})
