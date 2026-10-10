import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const WORKSPACES_SOURCE = readFileSync(
  new URL('../app/workspaces/page.tsx', import.meta.url),
  'utf8',
).replace(/\r\n/g, '\n')

describe('team-workspace load failures', () => {
  it('shows retry and suppresses the no-workspaces onboarding state', () => {
    expect(WORKSPACES_SOURCE).toContain('setLoadError(error instanceof Error')
    expect(WORKSPACES_SOURCE).toContain('Team workspaces could not be loaded')
    expect(WORKSPACES_SOURCE).toContain('loadError && workspaces.length === 0 ? null')
    expect(WORKSPACES_SOURCE).toContain('setReloadNonce((value) => value + 1)')
  })

  it('uses the confirmed-session guard and terminates loading when signed out', () => {
    expect(WORKSPACES_SOURCE).toContain('useRequireAuth()')
    expect(WORKSPACES_SOURCE).toMatch(/if \(!session\?\.user\) \{\s*setLoading\(false\)/)
  })
})
