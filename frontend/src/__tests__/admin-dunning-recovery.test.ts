import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin dunning recovery', () => {
    const page = read('../app/admin/page.tsx')
    const component = read('../components/admin/AdminDunningRecovery.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('wires a dedicated dunning section into the Subscriptions tab', () => {
        expect(page).toContain(
            "import AdminDunningRecovery from '@/components/admin/AdminDunningRecovery'"
        )
        expect(page).toContain('<AdminDunningRecovery />')
        expect(component).toContain('id="admin-dunning-recovery"')
        expect(component).toContain('Dunning recovery needs review')
    })

    it('calls the admin-only aggregate endpoint with cohort and date filters', () => {
        expect(apiClient).toContain('getAdminDunningRecovery')
        expect(apiClient).toContain('/admin/billing/dunning-recovery')
        expect(component).toContain('getAdminDunningRecovery')
        expect(component).toContain('Dunning event start date')
        expect(component).toContain('Dunning event end date')
        expect(component).toContain('Dunning signup cohort filter')
        expect(component).toContain('Dunning plan filter')
    })

    it('renders past-due, on-hold, recovery and median outcome metrics', () => {
        expect(component).toContain('Past due')
        expect(component).toContain('On hold')
        expect(component).toContain('Recovery rate')
        expect(component).toContain('Median time to active')
        expect(component).toContain('Median time to cancel')
        expect(component).toContain('Recovery by plan')
        expect(component).toContain('Recovery by signup cohort')
        expect(component).toContain('Recovery reconciliation')
    })

    it('keeps suppression and advisory guardrails visible', () => {
        expect(component).toContain('minimum_cohort_size')
        expect(component).toContain('suppressed_groups')
        expect(component).toContain('Advisory')
        expect(component).toContain('automatic_downgrade')
        expect(component).toContain('automatic_refund')
        expect(component).toContain('never downgrades, refunds or changes access')
        expect(component).toContain('append-only')
    })

    it('never renders or requests account PII, documents or provider payloads', () => {
        expect(component).not.toContain('user_id')
        expect(component).not.toContain('customer_email')
        expect(component).not.toContain('customer_phone')
        expect(component).not.toContain('latex_content')
        expect(component).not.toContain('provider_event_id')
        expect(component).not.toContain('job_description')
    })
})
