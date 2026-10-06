import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const RECRUITER_SOURCE = readFileSync(
  new URL('../app/workspaces/[workspaceId]/recruiter/page.tsx', import.meta.url),
  'utf8',
).replace(/\r\n/g, '\n')

describe('recruiter-workspace loading failures', () => {
  it('does not leave signed-out visitors on a permanent loading spinner', () => {
    expect(RECRUITER_SOURCE).toContain('useRequireAuth()')
    expect(RECRUITER_SOURCE).toContain("if (!session?.user) {\n      setLoading(false)")
    expect(RECRUITER_SOURCE).toContain('if (!session?.user) return null')
  })

  it('renders recovery UI when primary workspace data fails', () => {
    expect(RECRUITER_SOURCE).toContain('setLoadError(error instanceof Error')
    expect(RECRUITER_SOURCE).toContain('Recruiter dashboard could not be loaded')
    expect(RECRUITER_SOURCE).toContain('setReloadNonce((value) => value + 1)')
  })
})
