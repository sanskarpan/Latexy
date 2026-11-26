import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin ATS score distribution surface', () => {
  const page = read('../app/admin/page.tsx')
  const component = read('../components/admin/AdminAtsScoreDistribution.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('is wired into the admin analytics section from a dedicated component', () => {
    expect(page).toContain(
      "import AdminAtsScoreDistribution from '@/components/admin/AdminAtsScoreDistribution'",
    )
    expect(page).toContain('<AdminAtsScoreDistribution />')
    expect(component).toContain('ATS score distribution and improvement')
    expect(component).toContain('getAdminAtsScoreDistribution')
    expect(apiClient).toContain('/admin/analytics/ats-score-distribution')
    expect(apiClient).toContain('AdminAtsScoreDistributionResponse')
  })

  it('renders before/after buckets, median delta and improvement rate', () => {
    expect(component).toContain('Score distribution')
    expect(component).toContain('Before optimization')
    expect(component).toContain('After optimization')
    expect(component).toContain('Median delta')
    expect(component).toContain('Improvement rate')
    expect(component).toContain('median_improvement')
    expect(component).toContain('improvement_rate_pct')
    expect(apiClient).toContain('median_delta: number | null')
    expect(apiClient).toContain('improvement_rate_pct: number')
  })

  it('documents missing baselines, five-user suppression and privacy', () => {
    expect(component).toContain('Missing baseline')
    expect(component).toContain('minimum_users')
    expect(component).toContain('distinct users')
    expect(component).toContain('Excluded from score and delta math')
    expect(component).toContain('résumé content, job descriptions and identities are never returned')
    expect(component).not.toContain('latex_content')
    expect(component).not.toContain('job_description')
    expect(component).not.toContain('user_id')
    expect(component).not.toContain('resume_id')
  })
})
