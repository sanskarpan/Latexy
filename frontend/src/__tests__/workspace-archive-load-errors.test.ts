import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const WORKSPACE_SOURCE = readFileSync(
  new URL('../app/workspace/page.tsx', import.meta.url),
  'utf8',
)

describe('workspace archive load recovery', () => {
  it('does not render archive outages as an empty archive', () => {
    expect(WORKSPACE_SOURCE).toContain('setArchivedLoadError(')
    expect(WORKSPACE_SOURCE).toContain('archivedLoadError ?')
    expect(WORKSPACE_SOURCE).toContain('Archived resumes could not be loaded.')
    expect(WORKSPACE_SOURCE).toContain('Retry archive')
  })
})
