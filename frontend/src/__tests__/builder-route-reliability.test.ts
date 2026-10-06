import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const NEW_BUILDER = readFileSync(
  new URL('../app/workspace/builder/new/page.tsx', import.meta.url),
  'utf8',
)
const EDIT_BUILDER = readFileSync(
  new URL('../app/workspace/builder/[resumeId]/page.tsx', import.meta.url),
  'utf8',
)

describe('guided builder route reliability', () => {
  it('guards both builder routes behind a confirmed session', () => {
    for (const route of [NEW_BUILDER, EDIT_BUILDER]) {
      expect(route).toContain('useRequireAuth()')
      expect(route).toContain('if (!session) return null')
    }
  })

  it('distinguishes builder load failures from valid empty data and supports retry', () => {
    expect(NEW_BUILDER).toContain('Builder could not be loaded')
    expect(NEW_BUILDER).toContain('No builder-compatible templates are currently available.')
    expect(NEW_BUILDER).toContain('setLoadAttempt(value => value + 1)')

    expect(EDIT_BUILDER).toContain('Builder resume could not be loaded')
    expect(EDIT_BUILDER).toContain('setLoadAttempt(value => value + 1)')
    expect(EDIT_BUILDER).not.toContain("router.push('/workspace')")
  })

  it('does not mark edits made during an in-flight autosave as persisted', () => {
    expect(EDIT_BUILDER).toContain('const revision = editRevision.current')
    expect(EDIT_BUILDER).toContain('if (revision === editRevision.current)')
    expect(EDIT_BUILDER).toContain('editRevision.current += 1')
    expect(EDIT_BUILDER).toContain('Save failed · Retry')
  })

  it('enforces title limits before builder writes', () => {
    expect(NEW_BUILDER).toContain('title.trim().length > 255')
    expect(NEW_BUILDER).toContain('maxLength={255}')
    expect(EDIT_BUILDER).toContain("!title.trim() || title.length > 255")
    expect(EDIT_BUILDER).toContain('maxLength={255}')
  })
})
