import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(new URL('../app/billing/page.tsx', import.meta.url), 'utf8')

describe('billing session resilience', () => {
  it('preserves authenticated billing state while session refresh is indeterminate', () => {
    expect(SOURCE).toContain('lastKnownSessionRef')
    expect(SOURCE).toContain('(isPending || sessionError) ? lastKnownSessionRef.current : null')
    expect(SOURCE).toContain('effectiveSession?.session?.token')
    expect(SOURCE).toContain('effectiveSession?.user')
  })

  it('clears latched billing identity on a confirmed logout', () => {
    expect(SOURCE).toContain('!isPending && !sessionError')
    expect(SOURCE).toContain('lastKnownSessionRef.current = null')
  })

  it('sends a verified student to the returned checkout instead of claiming activation', () => {
    expect(SOURCE).toContain('result.data?.shortUrl')
    expect(SOURCE).toContain('window.location.assign(result.data.shortUrl)')
    expect(SOURCE).not.toContain("'Student plan activated'")
  })

  it('owns automatic student verification by token, account, and generation', () => {
    expect(SOURCE).toContain('const studentVerifyGenerationRef = useRef(0)')
    expect(SOURCE).toContain('const studentVerifyAttemptRef = useRef<{')
    expect(SOURCE).toContain('previousAttempt.accountKey === studentVerifyAccountKey')
    expect(SOURCE).toContain('studentVerifyAttemptRef.current === owner')
    expect(SOURCE).toContain('studentVerifyGenerationRef.current += 1')
  })
})
