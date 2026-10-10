import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const MERGE_SOURCE = readFileSync(
  new URL('../app/workspace/merge/page.tsx', import.meta.url),
  'utf8',
)

describe('merge-resume selector failures', () => {
  it('uses complete pagination and separates outage from an empty account', () => {
    expect(MERGE_SOURCE).toContain('.listAllResumes()')
    expect(MERGE_SOURCE).toContain('loadError && resumes.length === 0')
    expect(MERGE_SOURCE).toContain('Resumes could not be loaded')
    expect(MERGE_SOURCE).toContain('setReloadNonce((value) => value + 1)')
  })

  it('terminates loading while the auth guard redirects a signed-out visitor', () => {
    expect(MERGE_SOURCE).toMatch(/if \(!session\) \{\s*setLoading\(false\)/)
    expect(MERGE_SOURCE).toContain('if (!session) return null')
  })
})
