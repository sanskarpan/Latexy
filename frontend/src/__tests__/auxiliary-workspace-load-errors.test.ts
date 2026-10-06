import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = (relativePath: string) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

describe('auxiliary workspace request recovery', () => {
  it('does not render failed interview-prep or macro loads as empty collections', () => {
    const interview = source('../components/InterviewPrepPanel.tsx')
    const macros = source('../components/MacroLibraryPanel.tsx')

    expect(interview).toContain('role="alert"')
    expect(interview).toContain('Failed to load interview-prep sessions')
    expect(interview).not.toContain('// silent')
    expect(macros).toContain('loadError ? (')
    expect(macros).toContain('onClick={() => void fetchMacros()}')
  })

  it('separates failed search from no results and rejects stale responses', () => {
    const search = source('../components/ProjectSearchModal.tsx')

    expect(search).toContain('requestId !== searchRequestRef.current')
    expect(search).toContain('const clearSearch = () => {')
    expect(search).toContain('onClick={clearSearch}')
    expect(search).toContain('!loading && searchError')
    expect(search).toContain('!loading && !searchError && query.trim().length >= 2')
    expect(search).toContain('onClick={() => void doSearch(query)}')
  })
})
