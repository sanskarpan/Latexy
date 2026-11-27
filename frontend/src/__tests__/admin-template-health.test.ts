import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin template health surface', () => {
  const page = read('../app/admin/page.tsx')
  const component = read('../components/admin/AdminTemplateHealth.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('is wired into the admin Quality tab', () => {
    expect(page).toContain("import AdminTemplateHealth from '@/components/admin/AdminTemplateHealth'")
    expect(page).toContain('<AdminTemplateHealth />')
    expect(page).toContain("{ id: 'quality', label: 'Quality' }")
    expect(component).toContain('Template compile and visual health')
  })

  it('shows pass/fail/unknown, stale evidence and CI links', () => {
    expect(component).toContain("'pass'")
    expect(component).toContain("'fail'")
    expect(component).toContain("'unknown'")
    expect(component).toContain('stale_evidence')
    expect(component).toContain('CI evidence')
    expect(component).toContain('evidence.ci_url')
    expect(component).toContain('evidence.log_url')
    expect(component).toContain('evidence.commit_url')
    expect(component).toContain('Runbook')
    expect(apiClient).toContain('/admin/templates/health')
  })

  it('uses an audited idempotent retry with reason and confirmation', () => {
    expect(component).toContain('Retry check')
    expect(component).toContain('Confirm retry')
    expect(component).toContain('reason')
    expect(component).toContain('request_id')
    expect(component).toContain('retryAdminTemplateHealth')
    expect(apiClient).toContain('/health/retry')
    expect(apiClient).toContain('confirm: true')
  })

  it('never exposes template source, document content or per-user history', () => {
    expect(component).toContain('No template source')
    expect(component).not.toContain('latex_content')
    expect(component).not.toContain('user_id')
    expect(component).not.toContain('email')
    expect(component).not.toContain('document_content')
  })
})
