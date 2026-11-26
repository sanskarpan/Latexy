import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin incident timeline', () => {
  const page = read('../app/admin/page.tsx')
  const timeline = read('../components/admin/AdminIncidentTimeline.tsx')
  const operations = read('../components/admin/AdminOperations.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('adds a dedicated Operations tab and renders the timeline component', () => {
    expect(page).toContain("import AdminIncidentTimeline from '@/components/admin/AdminIncidentTimeline'")
    expect(page).toContain("{ id: 'operations', label: 'Operations' }")
    expect(page).toContain("tab === 'operations' && <AdminIncidentTimeline />")
    expect(timeline).toContain('id="admin-incident-timeline"')
    expect(timeline).toContain('Record incident')
    expect(timeline).toContain('Incident timeline')
  })

  it('supports service, severity, status and date filters plus the lifecycle actions', () => {
    expect(timeline).toContain('Filter incidents by service')
    expect(timeline).toContain('Filter incidents by severity')
    expect(timeline).toContain('Filter incidents by status')
    expect(timeline).toContain('Filter incidents from date')
    expect(timeline).toContain('Filter incidents to date')
    expect(timeline).toContain('getAdminIncidents')
    expect(timeline).toContain('createAdminIncident')
    expect(timeline).toContain('updateAdminIncident')
    expect(timeline).toContain('resolveAdminIncident')
    expect(timeline).toContain('reopenAdminIncident')
    expect(timeline).toContain('deploy_sha')
    expect(timeline).toContain('related_alert_keys')
    expect(timeline).toContain('append-only admin audit log')
    expect(apiClient).toContain('/admin/operations/incidents')
  })

  it('correlates active incidents into the needs-attention strip', () => {
    expect(operations).toContain("'incidents.active': 'Incident timeline'")
    expect(operations).toContain('medium:')
    expect(operations).toContain('Active incidents')
    expect(apiClient).toContain("export type AdminAttentionSeverity = 'critical' | 'high' | 'medium' | 'low'")
  })

  it('does not render document or customer PII fields', () => {
    expect(timeline).not.toContain('latex_content')
    expect(timeline).not.toContain('customer_email')
    expect(timeline).not.toContain('customer_phone')
    expect(timeline).not.toContain('job_description')
    expect(apiClient).toContain('AdminIncidentList')
  })
})
