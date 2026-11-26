import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin document complexity surface', () => {
    const page = read('../app/admin/page.tsx')
    const component = read('../components/admin/AdminDocumentComplexity.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('is wired into the admin analytics section from a dedicated component', () => {
        expect(page).toContain(
            "import AdminDocumentComplexity from '@/components/admin/AdminDocumentComplexity'"
        )
        expect(page).toContain('<AdminDocumentComplexity />')
        expect(component).toContain('Document complexity and error classes')
        expect(component).toContain('getAdminDocumentComplexity')
        expect(apiClient).toContain('/admin/analytics/document-complexity')
        expect(apiClient).toContain('AdminDocumentComplexityResponse')
    })

    it('exposes page-count, latency, failure-class and overflow distributions', () => {
        expect(component).toContain('Page-count distribution')
        expect(component).toContain('Compile-latency distribution')
        expect(component).toContain('Failure classes')
        expect(component).toContain('Overflow indicators')
        expect(component).toContain('Mutually exclusive failure classes')
        expect(component).toContain('Segments')
        expect(component).toContain('P95 pages')
    })

    it('offers 7/30/90-day presets and honours five-user suppression', () => {
        expect(component).toContain("{ days: 7, label: '7d' }")
        expect(component).toContain("{ days: 30, label: '30d' }")
        expect(component).toContain("{ days: 90, label: '90d' }")
        expect(component).toContain('distinct users are suppressed')
        expect(component).toContain('Metrics suppressed: this selection contains fewer than')
        expect(component).toContain('hidden under the five-user rule')
    })

    it('states that content and per-user rows are never returned', () => {
        expect(component).toContain('Only aggregate counts are read')
        expect(component).toContain('LaTeX/PDF content')
        expect(component).toContain('per-user rows are never returned')
        expect(component).toContain('anonymised compiles')
        expect(component).toContain('excluded from user-cohort segments')
    })
})
