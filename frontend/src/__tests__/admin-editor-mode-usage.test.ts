import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin editor mode usage surface', () => {
  const product = read('../components/admin/AdminProduct.tsx')
  const component = read('../components/admin/AdminEditorModeUsage.tsx')
  const apiClient = read('../lib/api-client.ts')
  const service = read(
    '../../../backend/app/services/editor_mode_analytics_service.py',
  )

  it('is mounted as a dedicated Product section', () => {
    expect(product).toContain(
      "import AdminEditorModeUsage from './AdminEditorModeUsage'",
    )
    expect(product).toContain('<AdminEditorModeUsage />')
  })

  it('reads the admin-only aggregate route and shows adoption, success and latency', () => {
    expect(apiClient).toContain('getAdminEditorModeUsage')
    expect(apiClient).toContain('/admin/analytics/editor-modes')
    expect(component).toContain('Mode adoption by plan')
    expect(component).toContain('Compile outcomes by mode')
    expect(component).toContain('Success rate')
    expect(component).toContain('p50')
    expect(component).toContain('p95')
    expect(component).toContain('Auto-compile')
    expect(component).toContain('SyncTeX')
    expect(component).toContain('minimum_cohort_size')
  })

  it('documents the aggregate-only boundary and excludes content fields', () => {
    expect(component).toContain('Consent-gated editor mode adoption')
    expect(component).toContain('SHA-256')
    expect(component).toContain('suppressed')
    expect(component).not.toContain('latex_source')
    expect(component).not.toContain('document_id')
    expect(component).not.toContain('user_id')
    expect(component).not.toContain('row.filename')
    expect(component).not.toContain('filename:')
    expect(service).toContain('MIN_GROUP_SIZE = 5')
    expect(service).toContain('per_user_rows')
    expect(service).toContain('LaTeX source or document content')
    expect(service).toContain('document_hash')
    expect(service).toContain('TOGGLE_DEDUPE_SECONDS')
  })
})
