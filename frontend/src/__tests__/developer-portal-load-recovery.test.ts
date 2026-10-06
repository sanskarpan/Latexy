import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(new URL('../app/developer/page.tsx', import.meta.url), 'utf8')

describe('developer portal load recovery', () => {
  it('does not present failed key retrieval as a valid empty account', () => {
    expect(SOURCE).toContain('const [loadError, setLoadError]')
    expect(SOURCE).toContain("failures.push(keysResult.error || 'Failed to load developer keys')")
    expect(SOURCE).toContain('role="alert"')
    expect(SOURCE).toContain('onClick={() => void load()}')
  })

  it('terminates safely when session verification itself fails', () => {
    expect(SOURCE).toContain('error: sessionError')
    expect(SOURCE).toContain('sessionError && !session')
    expect(SOURCE).toContain('Developer portal could not verify your session')
    expect(SOURCE).toContain('if (!session) return null')
  })
})
