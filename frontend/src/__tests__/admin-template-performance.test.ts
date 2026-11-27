import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin template performance surface', () => {
  const page = read('../app/admin/page.tsx')
  const component = read('../components/admin/AdminTemplatePerformance.tsx')
  const apiClient = read('../lib/api-client.ts')
  const templatesPage = read('../app/templates/page.tsx')

  it('is wired as an admin-only Quality tab with CSV export', () => {
    expect(page).toContain("import AdminTemplateHealth from '@/components/admin/AdminTemplateHealth'")
    expect(page).toContain("import AdminTemplatePerformance from '@/components/admin/AdminTemplatePerformance'")
    expect(page).toContain("{ id: 'quality', label: 'Quality' }")
    expect(page).toContain('<AdminTemplateHealth />')
    expect(page).toContain('<AdminTemplatePerformance />')
    expect(page).not.toContain("SUPPORT_TABS: Array<{ id: TabId; label: string }> = [\n  { id: 'quality'")
    expect(component).toContain('Template catalog performance')
    expect(component).toContain('Export CSV')
    expect(component).toContain('downloadAdminTemplatePerformanceCsv')
    expect(component).toContain('getAdminTemplatePerformance')
  })

  it('surfaces latency, failure rate and regressions', () => {
    expect(component).toContain('failure_rate')
    expect(component).toContain('p50_compile_seconds')
    expect(component).toContain('p95_compile_seconds')
    expect(component).toContain('Regression')
    expect(apiClient).toContain('p50_compile_seconds')
    expect(apiClient).toContain('regression_reason')
  })

  it('keeps the report aggregate-only and explicitly documents suppression', () => {
    expect(component).toContain('minimum_users')
    expect(component).toContain('suppressed_templates')
    expect(component).toContain('ranked by successful exports')
    expect(component).toContain('No résumé content or per-user template history is read')
    expect(component).not.toContain('latex_content')
    expect(component).not.toContain('user_id')
    expect(component).not.toContain('email')
    expect(apiClient).toContain('/admin/templates/performance/export.csv')
    expect(apiClient).toContain('AdminTemplatePerformanceResponse')
  })

  it('captures privacy-safe view and select events from the catalog', () => {
    expect(templatesPage).toContain("apiClient.trackTemplateEvent(id, 'view')")
    expect(templatesPage).toContain("apiClient.trackTemplateEvent(id, 'select')")
    expect(apiClient).toContain('/templates/${encodeURIComponent(templateId)}/events')
    expect(apiClient).toContain("event: 'view' | 'select'")
  })
})
