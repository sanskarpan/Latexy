import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(new URL('../app/templates/page.tsx', import.meta.url), 'utf8')

describe('template library recovery', () => {
  it('surfaces the verified PDF extraction contract without promising ATS outcomes', () => {
    expect(SOURCE).toContain('Verified PDF text contract.')
    expect(SOURCE).toContain('checked for embedded Unicode mapping')
    expect(SOURCE).toContain('employer parsers may differ')
  })

  it('does not present a library outage as zero matching templates', () => {
    expect(SOURCE).toContain('Template library could not be loaded')
    expect(SOURCE).toContain('setLoadAttempt(value => value + 1)')
    expect(SOURCE.indexOf('loadError ? (')).toBeLessThan(SOURCE.indexOf('filteredTemplates.length === 0 ? ('))
  })

  it('does not send a previously authenticated user to login on a transient session refresh error', () => {
    expect(SOURCE).toContain('lastKnownSessionRef')
    expect(SOURCE).toContain('(sessionPending || sessionError) ? lastKnownSessionRef.current : null')
    expect(SOURCE).toContain('if (!effectiveSession)')
    expect(SOURCE).toContain('if (effectiveSession) handleUseTemplate(useId)')
  })
})
