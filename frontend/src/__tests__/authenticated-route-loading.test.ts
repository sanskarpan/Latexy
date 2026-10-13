import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { editorRecoveryLoadBoundary } from '@/hooks/useLatexGeneratorRecovery'

const source = (relativePath: string) =>
  readFileSync(new URL(relativePath, import.meta.url), 'utf8')

describe('authenticated workspace route loading', () => {
  it.each([
    ['editor', '../app/workspace/[resumeId]/edit/page.tsx', 'setIsLoading(false)', "if (editorLoadBoundary === 'empty') return null"],
    ['optimizer', '../app/workspace/[resumeId]/optimize/page.tsx', 'setIsLoading(false)', 'if (!session) return null'],
    ['new resume', '../app/workspace/new/page.tsx', 'setLoadingTemplates(false)', 'if (!session) return null'],
    ['career analysis', '../app/workspace/[resumeId]/career/page.tsx', 'setPastLoading(false)', 'if (!session) return null'],
  ])('%s uses the confirmed-session guard and terminates signed-out loading', (_name, path, loadingExit, renderGuard) => {
    const route = source(path)
    expect(route).toContain('useRequireAuth()')
    expect(route).toContain(loadingExit)
    expect(route).toContain(renderGuard)
  })

  it('the editor terminates confirmed signed-out loading without hiding owned offline source or PDF recovery', () => {
    const signedOut = { preserveRecovery: false, sourceStatus: 'error' as const, isLoading: false, resumeLoadError: null,
      hasSession: false, sessionError: null, offlineDraftLoaded: false, offlinePdfLoaded: false }
    expect(editorRecoveryLoadBoundary(signedOut)).toBe('empty')
    expect(editorRecoveryLoadBoundary({ ...signedOut, sourceStatus: 'ready', offlineDraftLoaded: true })).toBe('editor')
    expect(editorRecoveryLoadBoundary({ ...signedOut, sourceStatus: 'pdf-only', offlinePdfLoaded: true })).toBe('editor')
  })
})
