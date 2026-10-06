import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = (relativePath: string) =>
  readFileSync(new URL(relativePath, import.meta.url), 'utf8')

describe('authenticated workspace route loading', () => {
  it.each([
    ['editor', '../app/workspace/[resumeId]/edit/page.tsx', 'setIsLoading(false)', 'if (!sessionData && !offlineDraftLoaded && !offlinePdfLoaded) return null'],
    ['optimizer', '../app/workspace/[resumeId]/optimize/page.tsx', 'setIsLoading(false)', 'if (!session) return null'],
    ['new resume', '../app/workspace/new/page.tsx', 'setLoadingTemplates(false)', 'if (!session) return null'],
    ['career analysis', '../app/workspace/[resumeId]/career/page.tsx', 'setPastLoading(false)', 'if (!session) return null'],
  ])('%s uses the confirmed-session guard and terminates signed-out loading', (_name, path, loadingExit, renderGuard) => {
    const route = source(path)
    expect(route).toContain('useRequireAuth()')
    expect(route).toContain(loadingExit)
    expect(route).toContain(renderGuard)
  })
})
