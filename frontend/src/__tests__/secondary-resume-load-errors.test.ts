import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = (relativePath: string) =>
  readFileSync(new URL(relativePath, import.meta.url), 'utf8')

describe('secondary résumé data failures', () => {
  it('keeps the application form usable and makes its résumé selector retryable', () => {
    const modal = source('../components/AddApplicationModal.tsx')
    expect(modal).toContain('Resumes could not be loaded. You can add the application without one.')
    expect(modal).toContain('setResumesReloadNonce((value) => value + 1)')
    expect(modal).toContain('disabled={resumesLoading}')
  })

  it('separates a career-history outage from a genuinely empty history', () => {
    const career = source('../app/workspace/[resumeId]/career/page.tsx')
    expect(career).toContain('Past analyses could not be loaded')
    expect(career).toContain('setPastReloadNonce((value) => value + 1)')
    expect(career).toContain('pastError ?')
  })
})
