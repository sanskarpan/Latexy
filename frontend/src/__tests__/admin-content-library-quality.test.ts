import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin content library adoption surface', () => {
    const page = read('../app/admin/page.tsx')
    const component = read('../components/admin/AdminContentLibraryQuality.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('is wired into the admin-only Quality tab', () => {
        expect(page).toContain(
            "import AdminContentLibraryQuality from '@/components/admin/AdminContentLibraryQuality'"
        )
        expect(page).toContain('<AdminContentLibraryQuality />')
        expect(page).not.toContain(
            "SUPPORT_TABS: Array<{ id: TabId; label: string }> = [\n  { id: 'quality'"
        )
        expect(component).toContain('Content library adoption')
        expect(component).toContain('Snippet adoption')
        expect(component).toContain('Macro adoption')
    })

    it('offers CSV export and the time/status/category filters', () => {
        expect(component).toContain('Export CSV')
        expect(component).toContain('downloadAdminContentLibraryAdoptionCsv')
        expect(component).toContain('getAdminContentLibraryAdoption')
        expect(component).toContain('Stale')
        expect(component).toContain('Never used')
        expect(component).toContain('Deleted')
        expect(component).toContain('Category')
        expect(apiClient).toContain('/admin/content-library/adoption/export.csv')
        expect(apiClient).toContain('/admin/content-library/adoption${suffix}')
        expect(apiClient).toContain('AdminContentLibraryResponse')
    })

    it('documents suppression and never renders body, macro source or user ids', () => {
        expect(component).toContain('minimum_users')
        expect(component).toContain('suppressed')
        expect(component).toContain('Aggregate-only because a macro has one owner')
        expect(component).toContain('snippet body, macro source, document text')
        expect(component).not.toContain('row.user_id')
        expect(component).not.toContain('row.content')
        expect(component).not.toContain('row.script')
        expect(component).not.toContain('row.actions')
        expect(apiClient).not.toContain('/admin/content-library/adoption/export.csv?token')
    })
})
