import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const TRACKER_SOURCE = readFileSync(
  new URL('../app/tracker/page.tsx', import.meta.url),
  'utf8',
)

describe('tracker load failures', () => {
  it('keeps an explicit retryable error instead of presenting an empty pipeline', () => {
    expect(TRACKER_SOURCE).toContain('setLoadError(error instanceof Error')
    expect(TRACKER_SOURCE).toContain('Tracker data could not be loaded')
    expect(TRACKER_SOURCE).toContain("onClick={() => { void loadBoard() }}")
  })

  it('distinguishes an outage from a genuinely empty tracker', () => {
    expect(TRACKER_SOURCE).toContain('loadError && totalApps === 0')
    expect(TRACKER_SOURCE).toContain('Tracker unavailable')
    expect(TRACKER_SOURCE).toContain('role="alert"')
  })
})
