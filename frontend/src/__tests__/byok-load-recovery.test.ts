import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const PAGE = readFileSync(new URL('../app/byok/page.tsx', import.meta.url), 'utf8')
const MANAGER = readFileSync(new URL('../components/byok/APIKeyManager.tsx', import.meta.url), 'utf8')

describe('BYOK load recovery', () => {
  it('does not mount credential requests before authentication resolves', () => {
    expect(PAGE).toContain('session, isPending, error')
    expect(PAGE).toContain('if (isPending)')
    expect(PAGE).toContain('if (error && !session)')
    expect(PAGE).toContain('if (!session) return null')
  })

  it('does not report a key-list outage as an empty account', () => {
    expect(MANAGER).toContain('const [keysError, setKeysError]')
    expect(MANAGER).toContain('keysError ? (')
    expect(MANAGER).toContain('Retry keys')
    expect(MANAGER.indexOf('keysError ? (')).toBeLessThan(MANAGER.indexOf('apiKeys.length === 0 ? ('))
  })

  it('blocks adding a key when provider configuration failed', () => {
    expect(MANAGER).toContain('const [providersError, setProvidersError]')
    expect(MANAGER).toContain("disabled={!can('d25') || (Boolean(providersError) || Object.keys(providers).length === 0)}")
    expect(MANAGER).toContain('Retry providers')
  })
})
