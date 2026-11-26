import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin optimization acceptance surface', () => {
  const page = read('../app/admin/page.tsx')
  const component = read('../components/admin/AdminOptimizationAcceptance.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('is wired as an admin-only Quality card with CSV export', () => {
    expect(page).toContain(
      "import AdminOptimizationAcceptance from '@/components/admin/AdminOptimizationAcceptance'",
    )
    expect(page).toContain("{tab === 'quality' && (")
    expect(page).toContain('<AdminOptimizationAcceptance />')
    expect(component).toContain('Optimization candidate acceptance')
    expect(component).toContain('Export CSV')
    expect(component).toContain('downloadAdminOptimizationAcceptanceCsv')
    expect(component).toContain('getAdminOptimizationAcceptance')
    expect(apiClient).toContain('/admin/analytics/optimization-acceptance')
    expect(apiClient).toContain('/admin/analytics/optimization-acceptance/export.csv')
  })

  it('keeps shown and decided denominators explicit', () => {
    expect(component).toContain('Candidates shown')
    expect(component).toContain('Decided')
    expect(component).toContain('acceptance_rate_pct')
    expect(component).toContain('decision_rate_pct')
    expect(component).toContain('accepted_of_shown_pct')
    expect(component).toContain('Accepted / decided')
    expect(apiClient).toContain('AdminOptimizationAcceptanceResponse')
    expect(apiClient).toContain('candidates_shown: number')
    expect(apiClient).toContain('decided: number')
  })

  it('documents aggregate-only reads and five-user suppression', () => {
    expect(component).toContain('minimum_users')
    expect(component).toContain('distinct users')
    expect(component).toContain('No suggestion text, candidate text, résumé content or per-user rows')
    expect(component).toContain('Reconciled to both decision tables')
    expect(component).not.toContain('user_id')
    expect(component).not.toContain('result_content')
    expect(component).not.toContain('suggestion_id')
    expect(component).not.toContain('latex_content')
  })
})
