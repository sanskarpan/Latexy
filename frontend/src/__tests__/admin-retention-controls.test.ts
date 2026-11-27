import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin data-retention controls', () => {
    const page = read('../app/admin/page.tsx')
    const component = read('../components/admin/AdminRetentionControls.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('wires a dedicated retention component into the Operations tab', () => {
        expect(page).toContain(
            "import AdminRetentionControls from '@/components/admin/AdminRetentionControls'"
        )
        expect(page).toContain('<AdminRetentionControls />')
    })

    it('calls the admin retention policy, preview and purge endpoints', () => {
        expect(apiClient).toContain('AdminRetentionOverview')
        expect(apiClient).toContain('/admin/operations/retention')
        expect(apiClient).toContain('/dry-run')
        expect(apiClient).toContain('/purge')
        expect(component).toContain('getAdminRetentionOverview')
        expect(component).toContain('updateAdminRetentionPolicy')
        expect(component).toContain('runAdminRetentionDryRun')
        expect(component).toContain('runAdminRetentionPurge')
    })

    it('shows configured vs effective windows, schedule and run history', () => {
        expect(component).toContain('configured')
        expect(component).toContain('effective')
        expect(component).toContain('next_run_at')
        expect(component).toContain('last_run')
        expect(component).toContain('Policy version')
        expect(component).toContain('Run history')
    })

    it('previews boundary ages and affected counts before purging', () => {
        expect(component).toContain('Boundary-age preview')
        expect(component).toContain('Rows exactly on the')
        expect(component).toContain('Crossing within')
        expect(component).toContain('Crossed in last')
        expect(component).toContain('Eligible for purge')
        expect(component).toContain('Dry run complete — nothing changed')
    })

    it('requires a reason and explicit confirmation for policy changes and purges', () => {
        expect(component).toContain('Change reason')
        expect(component).toContain('Run reason')
        expect(component).toContain('policyConfirm')
        expect(component).toContain('purgeConfirm')
        expect(component).toContain('Enter a reason of at least 3 characters.')
        expect(component).toContain('Confirm the purge before running it.')
        expect(component).toContain('confirm: true')
    })

    it('keeps active-job, legal-hold and immutable-audit guardrails visible', () => {
        expect(component).toContain('Active work refused')
        expect(component).toContain('Legal hold refused')
        expect(component).toContain('append-only')
        expect(component).toContain('cannot be deleted')
        expect(component).toContain('purge_supported')
        expect(component).toContain('Bounded delete')
        expect(component).toContain('Token scrub')
    })

    it('never renders per-user histories, document bodies or provider payloads', () => {
        for (const forbidden of [
            'user_id',
            'customer_email',
            'recipient_email',
            'latex_content',
            'document_text',
            'ip_address',
            'user_agent',
            'dangerouslySetInnerHTML',
        ]) {
            expect(component).not.toContain(forbidden)
        }
    })
})
