import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type Session = { data: { user: { id: string } } | null; isPending: boolean; error: unknown }
async function harness() {
  vi.resetModules()
  let session: Session = { data: { user: { id: 'a' } }, isPending: false, error: null }
  let index = 0
  const values: unknown[] = []
  let effects: Array<() => void | (() => void)> = []
  const getMe = vi.fn()
  vi.stubGlobal('window', { setTimeout, clearTimeout, setInterval, clearInterval, addEventListener: vi.fn(), removeEventListener: vi.fn() })
  vi.stubGlobal('document', { visibilityState: 'visible', addEventListener: vi.fn(), removeEventListener: vi.fn() })
  vi.doMock('react', () => ({
    useCallback: (fn: unknown) => fn,
    useRef: (initial: unknown) => { const slot = index++; if (!(slot in values)) values[slot] = { current: initial }; return values[slot] },
    useState: (initial: unknown) => { const slot = index++; if (!(slot in values)) values[slot] = initial; return [values[slot], (next: unknown) => { values[slot] = typeof next === 'function' ? (next as (v: unknown) => unknown)(values[slot]) : next }] },
    useEffect: (effect: () => void | (() => void)) => effects.push(effect),
  }))
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => session }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: { getMe } }))
  const { useAccountRole: readAccountRole } = await import('@/hooks/useAccountRole')
  return {
    getMe,
    session: (next: Session) => { session = next },
    render: () => { index = 0; effects = []; return readAccountRole() },
    fetch: () => effects[0]() as (() => void) | undefined,
    expire: () => effects[2](),
  }
}
const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() }
beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers(); vi.unstubAllGlobals()
  for (const name of ['react', '@/lib/auth-client', '@/lib/api-client']) vi.doUnmock(name)
  vi.resetModules()
})
describe('account-role UI authorization', () => {
  it('never shows admin navigation or controls for a newly switched account', async () => {
    const h = await harness(); h.getMe.mockResolvedValue({ id: 'a', role: 'admin' })
    h.render(); h.fetch(); await flush(); expect(h.render().role).toBe('admin')
    h.session({ data: { user: { id: 'b' } }, isPending: false, error: null })
    expect(h.render().role).toBeNull()
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: null })
    expect(h.render().role).toBeNull()
  })
  it('rejects stale or mismatched /me responses and session failures', async () => {
    const h = await harness(); let resolve!: (value: unknown) => void
    h.getMe.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
    h.render(); const cleanup = h.fetch(); cleanup?.()
    h.session({ data: { user: { id: 'b' } }, isPending: false, error: null })
    h.getMe.mockResolvedValue({ id: 'a', role: 'admin' }); h.render(); h.fetch(); await flush()
    resolve({ id: 'a', role: 'admin' }); await flush()
    expect(h.render().role).toBeNull(); expect(h.render().error).toBeTruthy()
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: new Error('offline') })
    expect(h.render().role).toBeNull()
  })
  it('updates on demotion and bounds a hanging refresh to eight seconds', async () => {
    const h = await harness(); h.getMe.mockResolvedValue({ id: 'a', role: 'admin' })
    h.render(); h.fetch(); await flush(); h.render().refresh()
    h.getMe.mockResolvedValue({ id: 'a', role: 'support' }); h.render(); h.fetch(); await flush()
    expect(h.render().role).toBe('support')
    h.render().refresh(); h.getMe.mockImplementation(() => new Promise(() => {})); h.render(); h.fetch()
    await vi.advanceTimersByTimeAsync(8000)
    expect(h.render().role).toBeNull(); expect(h.render().error).toContain('timed out')
  })
  it('expires cached role verification instead of granting while hidden indefinitely', async () => {
    const h = await harness(); h.getMe.mockResolvedValue({ id: 'a', role: 'admin' })
    h.render(); h.fetch(); await flush(); h.render(); h.expire()
    await vi.advanceTimersByTimeAsync(38000)
    expect(h.render().role).toBeNull(); expect(h.render().loading).toBe(false)
    expect(h.render().error).toContain('expired')
  })
})
