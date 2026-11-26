import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin linter rule quality surface', () => {
  const page = read('../app/admin/page.tsx')
  const component = read('../components/admin/AdminLinterRules.tsx')
  const apiClient = read('../lib/api-client.ts')
  const service = read('../../../backend/app/services/linter_telemetry_service.py')

  it('is wired into the admin Quality tab', () => {
    expect(page).toContain("import AdminLinterRules from '@/components/admin/AdminLinterRules'")
    expect(page).toContain("{ id: 'quality', label: 'Quality' }")
    expect(page).toContain("tab === 'quality' && (")
    expect(page).toContain('<AdminLinterRules />')
  })

  it('uses the admin-only aggregate route and shows frequency, fix rate and trend', () => {
    expect(apiClient).toContain('getAdminLinterRules')
    expect(apiClient).toContain('/admin/linter/rules?')
    expect(component).toContain('Top noisy rules')
    expect(component).toContain('Fix rate')
    expect(component).toContain('Daily rule trend')
    expect(component).toContain('minimum_users')
    expect(component).toMatch(/suppressed/i)
  })

  it('documents the aggregate-only boundary and excludes content fields', () => {
    expect(component).not.toContain('latex_content')
    expect(component).not.toContain('document_id')
    expect(component).not.toContain('user_id')
    expect(component).not.toContain('line_text')
    expect(service).toContain('LINTER_RULE_IDS')
    expect(service).toContain('MIN_GROUP_SIZE = 5')
    expect(service).toContain('per_user_rows')
    expect(service).toContain('LaTeX source')
  })
})
