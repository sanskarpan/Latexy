import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const HISTORY_SOURCE = readFileSync(
  new URL('../app/workspace/history/page.tsx', import.meta.url),
  'utf8',
)

describe('run-history load failures', () => {
  it('renders a retryable error instead of the no-runs empty state', () => {
    expect(HISTORY_SOURCE).toContain('setLoadError(error instanceof Error')
    expect(HISTORY_SOURCE).toContain('loadError && jobs.length === 0')
    expect(HISTORY_SOURCE).toContain('Run history could not be loaded')
    expect(HISTORY_SOURCE).toContain("onClick={() => { void load() }}")
  })

  it('does not present a transient session outage as a logged-out account', () => {
    expect(HISTORY_SOURCE).toContain('lastKnownSessionRef')
    expect(HISTORY_SOURCE).toContain('(sessionLoading || sessionError) ? lastKnownSessionRef.current : null')
    expect(HISTORY_SOURCE).toContain('sessionError && !effectiveSession')
    expect(HISTORY_SOURCE).toContain('Run history could not verify your session')
  })
})
