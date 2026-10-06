import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = (relativePath: string) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

describe('authenticated secondary-panel recovery', () => {
  it('keeps version-history and collaborator outages distinct from empty data', () => {
    const history = source('../components/VersionHistoryPanel.tsx')
    const collaborators = source('../components/CollaboratorPanel.tsx')
    expect(history).toContain('loadError && entries.length === 0')
    expect(history).toContain('setRetryKey((key) => key + 1)')
    expect(collaborators).toContain('listError && collaborators.length === 0')
    expect(collaborators).toContain('onClick={() => void loadCollaborators()}')
  })

  it('binds snippet requests to the entered query and rejects stale responses', () => {
    const snippets = source('../components/SnippetMarketplace.tsx')
    expect(snippets).toContain('async (reset = false, requestedQuery = query)')
    expect(snippets).toContain('q: requestedQuery.trim() || undefined')
    expect(snippets).toContain('requestId !== requestIdRef.current')
    expect(snippets).toContain('void load(true, q)')
    expect(snippets).toContain('loadError && snippets.length === 0')
  })

  it('offers an explicit retry for share-analytics failures', () => {
    const share = source('../components/ShareResumeModal.tsx')
    expect(share).toContain('const loadAnalytics = useCallback')
    expect(share).toContain('onClick={() => void loadAnalytics()}')
    expect(share).toContain('role="alert"')
  })
})
