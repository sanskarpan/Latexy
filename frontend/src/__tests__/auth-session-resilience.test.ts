import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
const AUTH_SYNC = read('../components/AuthSync.tsx')
const AUTH_GUARD = read('../hooks/useRequireAuth.ts')
const HEADER = read('../components/GlobalHeader.tsx')

describe('session refresh resilience', () => {
  it('does not clear API or WebSocket authentication on an indeterminate session response', () => {
    expect(AUTH_SYNC).toContain('if (isPending || error) return')
    expect(AUTH_SYNC.indexOf('if (isPending || error) return'))
      .toBeLessThan(AUTH_SYNC.indexOf('apiClient.setAuthToken(token)'))
    expect(AUTH_SYNC).toContain('[session, isPending, error]')
  })

  it('keeps the last confirmed guarded session through pending and error states', () => {
    expect(AUTH_GUARD).toContain('lastKnownSessionRef')
    expect(AUTH_GUARD).toContain('(isPending || error) ? lastKnownSessionRef.current : null')
    expect(AUTH_GUARD).toContain('!isPending && !error')
    expect(AUTH_GUARD).toContain('session: effectiveSession')
  })

  it('clears the header identity only after a confirmed empty response', () => {
    expect(HEADER).toContain('!sessionPending && !sessionError')
    expect(HEADER).toContain('(sessionPending || sessionError) ? lastKnownSessionRef.current : null')
  })
})
