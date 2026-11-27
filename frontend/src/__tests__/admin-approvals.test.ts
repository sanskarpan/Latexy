import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin two-person approvals', () => {
    const page = read('../app/admin/page.tsx')
    const approvals = read('../components/admin/AdminApprovals.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('adds a dedicated Approvals tab and renders the queue', () => {
        expect(page).toContain("import AdminApprovals from '@/components/admin/AdminApprovals'")
        expect(page).toContain("{ id: 'approvals', label: 'Approvals' }")
        expect(page).toContain("tab === 'approvals'")
        expect(page).toContain('<AdminApprovals />')
        expect(approvals).toContain('id="admin-approvals"')
        expect(approvals).toContain('Two-person approvals')
        expect(approvals).toContain('Pending approval')
    })

    it('requires a second admin and makes replay and expiry explicit', () => {
        expect(approvals).toContain('The requester cannot approve their own request')
        expect(approvals).toContain('Execute once')
        expect(approvals).toContain('cannot be replayed')
        expect(approvals).toContain('payload_hash')
        expect(approvals).toContain('approved_by')
        expect(approvals).toContain('append-only admin audit log')
        expect(apiClient).toContain('/admin/approvals')
        expect(apiClient).toContain('/execute')
        expect(apiClient).toContain('export type AdminApprovalStatus')
    })

    it('integrates role escalation with an approval id from the queue', () => {
        expect(page).toContain('Promoting a user to admin requires a second admin approval')
        expect(page).toContain('approvalId')
        expect(page).toContain('updateUserRole(user.id, role, {')
        expect(apiClient).toContain('approval_id')
        expect(apiClient).toContain('options?.approvalId')
        expect(approvals).toContain("request_type: 'role_escalation'")
    })

    it('shows only bounded action metadata, never document or customer payloads', () => {
        expect(approvals).not.toContain('latex_content')
        expect(approvals).not.toContain('structured_content')
        expect(approvals).not.toContain('job_description')
        expect(approvals).not.toContain('prompt')
        expect(approvals).not.toContain('customer_email')
        expect(approvals).not.toContain('provider_payload')
        expect(approvals).toContain('bounded action summary')
    })
})
