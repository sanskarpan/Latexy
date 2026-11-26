import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin PDF artifact lifecycle and orphan cleanup', () => {
    const page = read('../app/admin/page.tsx')
    const component = read('../components/admin/AdminArtifactLifecycle.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('wires a dedicated lifecycle component into the Operations tab', () => {
        expect(page).toContain(
            "import AdminArtifactLifecycle from '@/components/admin/AdminArtifactLifecycle'"
        )
        expect(page).toContain('<AdminArtifactLifecycle />')
    })

    it('calls the admin-only lifecycle and guarded cleanup endpoints', () => {
        expect(apiClient).toContain('AdminArtifactLifecycleReport')
        expect(apiClient).toContain('/admin/operations/artifacts/lifecycle')
        expect(apiClient).toContain('/admin/operations/artifacts/cleanup')
        expect(component).toContain('getAdminArtifactLifecycle')
        expect(component).toContain('runAdminArtifactCleanup')
    })

    it('shows state, age, orphan, sweep and growth visibility', () => {
        expect(component).toContain('Manifests by state')
        expect(component).toContain('Manifests by age')
        expect(component).toContain('Object listing by state')
        expect(component).toContain('Orphan candidate keys')
        expect(component).toContain('Last sweep')
        expect(component).toContain('Storage growth')
        expect(component).toContain('Added · 7d')
        expect(component).toContain('Failed deletion keys')
    })

    it('requires a reason, a dry run and explicit confirmation before deleting', () => {
        expect(component).toContain('Reason for cleanup')
        expect(component).toContain('Dry run')
        expect(component).toContain('confirmDeletion')
        expect(component).toContain('Enter a reason of at least 3 characters.')
        expect(component).toContain('Confirm the deletion before running a real cleanup.')
        expect(component).toContain('dry_run: dryRun')
        expect(component).toContain('confirm: dryRun ? undefined : true')
    })

    it('keeps the reference, unaccepted and legal-hold guardrails visible', () => {
        expect(component).toContain('Referenced artifacts')
        expect(component).toContain('accepted or unaccepted')
        expect(component).toContain('legal-hold artifacts')
        expect(component).toContain('grace period')
        expect(component.replace(/\s+/g, ' ')).toContain('are never deleted')
        expect(component.replace(/\s+/g, ' ')).toContain('Aggregate-only suppression is preserved')
        expect(component).toContain('minimum cohort size')
    })

    it('never renders user identifiers, document contents or raw HTML', () => {
        for (const forbidden of [
            'user_id',
            'customer_email',
            'recipient_email',
            'latex_content',
            'document_text',
            'dangerouslySetInnerHTML',
        ]) {
            expect(component).not.toContain(forbidden)
        }
    })
})
