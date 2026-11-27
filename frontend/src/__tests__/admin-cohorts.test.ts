import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin cohort sync surface', () => {
  const page = read('../app/admin/page.tsx')
  const component = read('../components/admin/AdminCohorts.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('is wired into the operational feature-flags tab', () => {
    expect(page).toContain(
      "import AdminCohorts from '@/components/admin/AdminCohorts'",
    )
    expect(page).toContain('<AdminCohorts />')
    expect(component).toContain('getAdminCohorts')
    expect(apiClient).toContain('/admin/cohorts')
    expect(apiClient).toContain('AdminCohortListResponse')
  })

  it('shows cohort size, sync status, errors and mapped flags', () => {
    expect(component).toContain('Synced size')
    expect(component).toContain('Last successful sync')
    expect(component).toContain('Last sync failed with code')
    expect(component).toContain('Flags using this cohort')
    expect(component).toContain('Size is hidden and mapped')
    expect(component).toContain('Never synced')
    expect(component).toContain('Sync error')
    expect(component).toContain('Below minimum')
  })

  it('explains the fail-closed and consent boundaries', () => {
    expect(component).toContain('Evaluation is fail-closed until a successful sync.')
    expect(component).toContain('Every mapped flag is disabled until the cohort is')
    expect(component).toContain('fail-closed on the anonymous config')
    expect(component).toContain('current first-party analytics grant')
    expect(component).toContain('Aggregate-only')
    expect(component).toContain('five-user minimum')
    expect(component).toContain('no member identifiers')
  })

  it('requires a reason and confirmation for mutations', () => {
    expect(component).toContain('Reason for cohort changes')
    expect(component).toContain('I confirm these audited cohort changes.')
    expect(component).toContain('Enter a reason and tick the confirmation box first')
    expect(component).toContain('confirm: true')
  })

  it('uses the audited admin endpoints and the consent-gated evaluation route', () => {
    expect(apiClient).toContain(
      "`/admin/cohorts/${encodeURIComponent(cohortId)}/mappings`",
    )
    expect(apiClient).toContain(
      "`/admin/cohorts/${encodeURIComponent(cohortId)}/sync`",
    )
    expect(apiClient).toContain("'/analytics/cohorts/evaluate'")
    expect(apiClient).toContain('member_identifiers_returned')
    expect(apiClient).toContain('exposures_30d')
  })

  it('never renders a member identifier field', () => {
    expect(component).not.toContain('member_user_id')
    expect(component).not.toContain('email')
    expect(component).not.toContain('user_agent')
    expect(component).not.toContain('ip_address')
  })
})
