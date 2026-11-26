import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin career-feature adoption surface', () => {
    const page = read('../app/admin/page.tsx')
    const component = read('../components/admin/AdminCareerAdoption.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('is wired into the product section from a dedicated component', () => {
        expect(page).toContain(
            "import AdminCareerAdoption from '@/components/admin/AdminCareerAdoption'"
        )
        expect(page).toContain('<AdminCareerAdoption />')
        expect(component).toContain('Career features: adoption and cross-sell')
        expect(component).toContain('getAdminCareerAdoption')
        expect(apiClient).toContain('/admin/analytics/career-adoption')
        expect(apiClient).toContain('AdminCareerAdoptionResponse')
    })

    it('renders users, runs, repeat use, cross-sell and plan/cohort breakdowns', () => {
        expect(component).toContain('Users')
        expect(component).toContain('Runs')
        expect(component).toContain('Repeat use')
        expect(component).toContain('Repeat rate')
        expect(component).toContain('After optimization')
        expect(component).toContain('Signup cohort')
        expect(component).toContain('Cross-sell')
        expect(apiClient).toContain('after_optimization_users')
        expect(apiClient).toContain('repeat_rate')
        expect(apiClient).toContain('runs_per_user')
    })

    it('documents five-user suppression, reconciliation and privacy', () => {
        expect(component).toContain('five-user')
        expect(component).toContain('suppressed_segments')
        expect(component).toContain('reconciliation.features')
        expect(component).toContain('generated content')
        expect(component).toContain('identities are never returned')
        expect(component).not.toContain('latex_content')
        expect(component).not.toContain('job_description')
        expect(component).not.toContain('user_id')
        expect(component).not.toContain('resume_id')
    })
})
