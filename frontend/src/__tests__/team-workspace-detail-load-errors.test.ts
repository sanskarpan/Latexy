import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const DETAIL_SOURCE = readFileSync(
  new URL('../app/workspaces/[workspaceId]/page.tsx', import.meta.url),
  'utf8',
)

describe('team-workspace detail failures', () => {
  it('renders recovery UI instead of returning a blank page', () => {
    expect(DETAIL_SOURCE).not.toContain('if (!ws) return null')
    expect(DETAIL_SOURCE).toContain('Team workspace could not be loaded')
    expect(DETAIL_SOURCE).toContain('setLoadError(error instanceof Error')
    expect(DETAIL_SOURCE).toContain('setReloadNonce((value) => value + 1)')
  })

  it('does not leave signed-out visitors on a permanent loading spinner', () => {
    expect(DETAIL_SOURCE).toContain('useRequireAuth()')
    expect(DETAIL_SOURCE).toContain("if (!session?.user) {\n      setLoading(false)")
    expect(DETAIL_SOURCE).toContain('if (!session?.user) return null')
  })
})
