import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(new URL('../app/settings/page.tsx', import.meta.url), 'utf8')

describe('settings session resilience', () => {
  it('uses the shared confirmed-session semantics', () => {
    expect(SOURCE).toContain('useRequireAuth()')
    expect(SOURCE).not.toContain("from '@/lib/auth-client'")
  })

  it('does not present a transient session failure as a signed-out account', () => {
    expect(SOURCE).toContain('sessionError && !sessionData')
    expect(SOURCE).toContain('Settings could not verify your session')
    expect(SOURCE.indexOf('sessionError && !sessionData'))
      .toBeLessThan(SOURCE.indexOf('Sign in to manage settings'))
  })
})
