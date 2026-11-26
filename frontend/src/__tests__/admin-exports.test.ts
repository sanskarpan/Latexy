import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin exports surface', () => {
  const page = read('../app/admin/page.tsx')
  const component = read('../components/admin/AdminExports.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('is wired into the admin shell from a dedicated component', () => {
    expect(page).toContain("import AdminExports from '@/components/admin/AdminExports'")
    expect(page).toContain('{ id: \'exports\', label: \'Exports\' }')
    expect(page).toContain("{tab === 'exports' && <AdminExports />}")
    expect(component).toContain('CSV and PDF exports')
    expect(component).toContain('Scheduled admin digest')
  })

  it('uses the typed api client for streaming, signed downloads and digest controls', () => {
    expect(component).toContain('downloadAdminExportStream')
    expect(component).toContain('createAdminExport')
    expect(component).toContain('downloadAdminExportToken')
    expect(component).toContain('updateAdminExportDigest')
    expect(component).toContain('dryRunAdminExportDigest')
    expect(apiClient).toContain('/admin/exports/stream')
    expect(apiClient).toContain('/admin/exports/download?token=')
    expect(apiClient).toContain('/admin/exports/digest')
    expect(apiClient).toContain('AdminExportCreateResponse')
  })

  it('states aggregate-only privacy and five-user suppression', () => {
    expect(component).toContain('aggregate-only')
    expect(component).toContain('five-user suppression floor')
    expect(component).toContain('No resume/document content')
    expect(component).toContain('raw IPs')
    expect(component).toContain('provider payloads')
  })

  it('requires a confirmed reason before changing the digest', () => {
    expect(component).toContain('I confirm this scheduled digest change.')
    expect(component).toContain('digestReason.trim().length < 3')
    expect(component).toContain('Dry run (no email)')
    expect(component).toContain('Last run')
    expect(component).toContain('error_class')
  })
})
