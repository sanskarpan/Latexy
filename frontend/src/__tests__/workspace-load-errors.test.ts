import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const WORKSPACE_SOURCE = readFileSync(
  new URL('../app/workspace/page.tsx', import.meta.url),
  'utf8',
)

describe('workspace load failures', () => {
  it('stores primary API failures instead of silently rendering an empty account', () => {
    expect(WORKSPACE_SOURCE).toContain('setLoadError(error instanceof Error')
    expect(WORKSPACE_SOURCE).toContain('Workspace data could not be loaded')
    expect(WORKSPACE_SOURCE).toContain('role="alert"')
  })

  it('offers retry and does not show the create-first-resume state after an outage', () => {
    expect(WORKSPACE_SOURCE).toContain("onClick={() => { void fetchData() }}")
    expect(WORKSPACE_SOURCE).toContain('loadError && ownedResumes.length === 0')
    expect(WORKSPACE_SOURCE).toContain('hasCurrentWorkspaceData ? resumes : []')
    expect(WORKSPACE_SOURCE).not.toContain('loadError && resumes.length === 0')
    expect(WORKSPACE_SOURCE).toContain('Workspace unavailable')
  })
})
