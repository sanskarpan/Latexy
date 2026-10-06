import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const exportSource = readFileSync(
  new URL('../components/ExportDropdown.tsx', import.meta.url),
  'utf8',
)
const clientSource = readFileSync(
  new URL('../lib/api-client.ts', import.meta.url),
  'utf8',
)

describe('compiled document email delivery action', () => {
  it('offers only verified-account delivery for saved resumes', () => {
    expect(exportSource).toContain("key: 'email'")
    expect(exportSource).toContain('verified account email')
    expect(exportSource).toContain("if (format === 'email' && !resumeId)")
    expect(exportSource).toContain('apiClient.emailResumePdf(resumeId)')
    expect(clientSource).toContain("body: JSON.stringify({})")
    expect(clientSource).not.toContain('recipient_email')
  })

  it('keeps provider failures retryable in persistent UI state', () => {
    expect(exportSource).toContain("setExportError({ format, message })")
    expect(exportSource).toContain('Email provider did not accept the PDF')
    expect(exportSource).toContain('>Retry</button>')
    expect(exportSource).toContain('smtp_best_effort')
  })
})
