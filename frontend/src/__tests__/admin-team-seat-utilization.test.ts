import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin team seat utilization analytics', () => {
    const billing = read('../components/admin/AdminBilling.tsx')
    const component = read('../components/admin/AdminTeamSeatUtilization.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('wires a dedicated team-seat card into the revenue tab', () => {
        expect(billing).toContain(
            "import AdminTeamSeatUtilization from './AdminTeamSeatUtilization'"
        )
        expect(billing).toContain('<AdminTeamSeatUtilization />')
        expect(component).toContain('Team seat utilization')
    })

    it('calls the admin-only aggregate endpoint with owner and tenant filters', () => {
        expect(apiClient).toContain('AdminTeamSeatResponse')
        expect(apiClient).toContain('/admin/analytics/team-seats')
        expect(component).toContain('getAdminTeamSeatUtilization')
        expect(component).toContain('owner_id')
        expect(component).toContain('tenant_id')
    })

    it('renders reconciliation, aging, acceptance and utilization metrics', () => {
        expect(component).toContain('Active seats')
        expect(component).toContain('Utilization')
        expect(component).toContain('Invite → active')
        expect(component).toContain('Invite → accept')
        expect(component).toContain('Median accept')
        expect(component).toContain('Stale invites')
        expect(component).toContain('over_30_days')
        expect(component).toContain('seat_capacity')
        expect(component).toContain('tenant_max_members')
        expect(component).toContain('all_checks_passed')
    })

    it('keeps suppression and tenant isolation visible', () => {
        expect(component).toContain('minimum_group_size')
        expect(component).toContain('summary_suppressed')
        expect(component).toContain('suppressed_owner_rows')
        expect(component).toContain('suppressed_tenant_rows')
        expect(component).toContain('cross-tenant')
        expect(component).toContain('Hidden (<5 seats)')
    })

    it('never renders invitee emails, invitee ids or invite tokens', () => {
        for (const forbidden of [
            'member_email',
            'member_user_id',
            'invite_preview_url',
            'invite_token',
            'dangerouslySetInnerHTML',
        ]) {
            expect(component).not.toContain(forbidden)
        }
    })
})
