import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const OPTIMIZE = readFileSync(
  new URL('../app/workspace/[resumeId]/optimize/page.tsx', import.meta.url),
  'utf8',
)
const COVER_LETTER = readFileSync(
  new URL('../app/workspace/[resumeId]/cover-letter/page.tsx', import.meta.url),
  'utf8',
)

describe('resume workflow load recovery', () => {
  it('keeps optimization load failures visible and retryable', () => {
    expect(OPTIMIZE).toContain('Optimization workspace could not be loaded')
    expect(OPTIMIZE).toContain('setLoadAttempt(value => value + 1)')
    expect(OPTIMIZE).not.toContain("toast.error('Failed to load resume')")
    expect(OPTIMIZE).not.toContain("router.push('/workspace')\n      } finally")
  })

  it('terminates cover-letter loading when signed out', () => {
    expect(COVER_LETTER).toContain('if (sessionLoading) return')
    expect(COVER_LETTER).toContain('setIsLoading(false)')
    expect(COVER_LETTER).toContain('if (!session)')
  })

  it('keeps cover-letter load failures visible and retryable', () => {
    expect(COVER_LETTER).toContain('Cover-letter workspace could not be loaded')
    expect(COVER_LETTER).toContain('setLoadAttempt(value => value + 1)')
    expect(COVER_LETTER).not.toContain("router.push('/workspace')")
    expect(COVER_LETTER).toContain('The requested cover letter was not found for this resume.')
  })
})
