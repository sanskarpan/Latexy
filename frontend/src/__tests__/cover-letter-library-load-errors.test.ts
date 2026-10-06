import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const LIBRARY_SOURCE = readFileSync(
  new URL('../app/workspace/cover-letters/page.tsx', import.meta.url),
  'utf8',
)

describe('cover-letter library load failures', () => {
  it('shows a retryable primary-load error instead of the empty library state', () => {
    expect(LIBRARY_SOURCE).toContain('setLoadError(error instanceof Error')
    expect(LIBRARY_SOURCE).toContain('loadError && coverLetters.length === 0')
    expect(LIBRARY_SOURCE).toContain('Cover letters could not be loaded')
    expect(LIBRARY_SOURCE).toContain('setReloadNonce((value) => value + 1)')
  })
})
