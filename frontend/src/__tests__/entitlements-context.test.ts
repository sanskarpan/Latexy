import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type Value = { features: Record<string, boolean>; can: (key: string) => boolean; loading: boolean; loaded: boolean; error: string | null; refresh: () => void }
type Session = { data: { user: { id: string } } | null; isPending: boolean; error: unknown }

async function harness() {
  vi.resetModules()
  let session: Session = { data: null, isPending: false, error: null }
  let index = 0
  const states: unknown[] = []
  const refs: Array<{ current: unknown }> = []
  let effects: Array<() => void | (() => void)> = []
  const listeners = new Map<string, () => void>()
  vi.stubGlobal('window', { setTimeout, clearTimeout, setInterval, clearInterval,
    addEventListener: (key: string, fn: () => void) => listeners.set(key, fn), removeEventListener: vi.fn() })
  vi.stubGlobal('document', { visibilityState: 'visible', addEventListener: vi.fn(), removeEventListener: vi.fn() })
  const getEntitlements = vi.fn()
  const refetchSession = vi.fn(async () => {})
  vi.doMock('react', () => ({
    createContext: (value: unknown) => ({ Provider: 'Provider', value }),
    useContext: (context: { value: unknown }) => context.value,
    useRef: (initial: unknown) => { const slot = index++; refs[slot] ??= { current: initial }; return refs[slot] },
    useMemo: (factory: () => unknown) => factory(),
    useCallback: (callback: unknown) => callback,
    useEffect: (effect: () => void | (() => void)) => { effects.push(effect) },
    useState: (initial: unknown) => {
      const slot = index++
      if (!(slot in states)) states[slot] = initial
      return [states[slot], (next: unknown) => { states[slot] = typeof next === 'function' ? (next as (value: unknown) => unknown)(states[slot]) : next }]
    },
  }))
  vi.doMock('react/jsx-runtime', () => ({ jsx: (type: unknown, props: unknown) => ({ type, props }) }))
  vi.doMock('react/jsx-dev-runtime', () => ({ jsxDEV: (type: unknown, props: unknown) => ({ type, props }) }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: { getEntitlements } }))
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => ({ ...session, refetch: refetchSession }) }))
  const { EntitlementsProvider } = await import('@/contexts/EntitlementsContext')
  return {
    getEntitlements,
    refetchSession,
    listen: () => effects[1](),
    expire: () => effects[2](),
    background: () => listeners.get('focus')?.(),
    session: (next: Session) => { session = next },
    render: () => {
      index = 0; effects = []
      return (EntitlementsProvider({ children: null }) as unknown as { props: { value: Value } }).props.value
    },
    fetch: () => effects[0]() as (() => void) | undefined,
  }
}

const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() }
beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  for (const moduleName of ['react', 'react/jsx-runtime', 'react/jsx-dev-runtime', '@/lib/api-client', '@/lib/auth-client']) vi.doUnmock(moduleName)
  vi.resetModules()
})

describe('identity-scoped feature availability', () => {
  it('fetches anonymous controls and closes optional capabilities until loaded', async () => {
    const h = await harness(); h.getEntitlements.mockResolvedValue({ features: { d01: false, c06: true } })
    expect(h.render().can('c06')).toBe(false)
    h.fetch(); await flush()
    expect(h.getEntitlements).toHaveBeenCalledTimes(1)
    expect(h.render()).toMatchObject({ loading: false, loaded: true, error: null })
    expect(h.render().can('d01')).toBe(false)
    expect(h.render().can('c06')).toBe(true)
    expect(h.render().can('unregistered')).toBe(false)
  })
  it('invalidates old grants during render on account switch before effects run', async () => {
    const h = await harness(); h.getEntitlements.mockResolvedValue({ features: { d01: true } })
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: null })
    h.render(); h.fetch(); await flush(); expect(h.render().can('d01')).toBe(true)
    h.session({ data: { user: { id: 'b' } }, isPending: false, error: null })
    expect(h.render().can('d01')).toBe(false)
    expect(h.render().features).toEqual({})
  })
  it('requires fresh grants across an A to B to A transition', async () => {
    const h = await harness(); h.getEntitlements.mockResolvedValue({ features: { d01: true } })
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: null })
    h.render(); h.fetch(); await flush(); expect(h.render().can('d01')).toBe(true)
    h.session({ data: { user: { id: 'b' } }, isPending: false, error: null }); expect(h.render().can('d01')).toBe(false)
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: null }); expect(h.render().can('d01')).toBe(false)
  })
  it('ignores stale responses after sign-out and a new anonymous request', async () => {
    const h = await harness(); let resolveOld!: (data: unknown) => void
    h.getEntitlements.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: null }); h.render(); const cleanup = h.fetch()
    cleanup?.(); h.session({ data: null, isPending: false, error: null })
    h.getEntitlements.mockResolvedValue({ features: { d01: false } }); h.render(); h.fetch(); await flush()
    resolveOld({ features: { d01: true } }); await flush()
    expect(h.render().can('d01')).toBe(false)
  })
  it('fails closed on refresh errors and allows explicit retry', async () => {
    const h = await harness(); h.getEntitlements.mockResolvedValue({ features: { d01: true } })
    h.render(); h.fetch(); await flush(); const ready = h.render(); expect(ready.can('d01')).toBe(true)
    ready.refresh(); expect(h.render().can('d01')).toBe(false)
    h.getEntitlements.mockRejectedValue(new Error('offline')); h.fetch(); await flush()
    const failed = h.render(); expect(failed.loaded).toBe(false); expect(failed.error).toBe('offline')
    for (const key of ['d01', 'b01', 'c01', 'c05', 'compile', 'f10', 'f11', 'i01']) {
      expect(failed.can(key), `${key} must fail closed`).toBe(false)
    }
    expect(failed.can('c09')).toBe(true) // Existing PDF preview remains available.
    expect(failed.can('i04')).toBe(true) // Admin recovery remains available.
    h.getEntitlements.mockResolvedValue({ features: { d01: true } }); failed.refresh(); h.render(); h.fetch(); await flush()
    expect(h.render().can('d01')).toBe(true)
  })
  it('waits for session resolution and never grants from a failed session', async () => {
    const h = await harness(); h.session({ data: null, isPending: true, error: null }); h.render(); h.fetch()
    expect(h.getEntitlements).not.toHaveBeenCalled()
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: new Error('expired') })
    const value = h.render(); h.fetch(); expect(value.can('d01')).toBe(false); expect(value.error).toBeTruthy()
    expect(h.getEntitlements).not.toHaveBeenCalled()
  })
  it('retries session verification before fetching identity-scoped grants', async () => {
    const h = await harness()
    h.session({ data: null, isPending: false, error: new Error('session request failed') })
    const failed = h.render()
    h.fetch()
    expect(failed.error).toBe('Could not verify your session')
    expect(h.getEntitlements).not.toHaveBeenCalled()

    h.refetchSession.mockImplementationOnce(async () => {
      h.session({ data: { user: { id: 'recovered' } }, isPending: false, error: null })
    })
    h.getEntitlements.mockResolvedValue({ features: { c01: true } })
    failed.refresh()
    await flush()
    expect(h.refetchSession).toHaveBeenCalledTimes(1)
    expect(h.getEntitlements).not.toHaveBeenCalled()
    h.render(); h.fetch(); await flush()
    expect(h.render().can('c01')).toBe(true)
  })
  it('keeps prior grants invalid after repeated session retry failures', async () => {
    const h = await harness()
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: null })
    h.getEntitlements.mockResolvedValue({ features: { d01: true } })
    h.render(); h.fetch(); await flush()
    expect(h.render().can('d01')).toBe(true)

    h.session({ data: { user: { id: 'a' } }, isPending: false, error: new Error('session offline') })
    h.refetchSession.mockRejectedValue(new Error('still offline'))
    for (let attempt = 1; attempt <= 2; attempt++) {
      const failed = h.render()
      expect(failed.error).toBe('Could not verify your session')
      expect(failed.can('d01')).toBe(false)
      failed.refresh()
      await flush()
      h.render(); h.fetch()
      expect(h.refetchSession).toHaveBeenCalledTimes(attempt)
      expect(h.getEntitlements).toHaveBeenCalledTimes(1)
      expect(h.render().features).toEqual({})
    }
  })
  it('rejects a prior identity response during rapid session retries', async () => {
    const h = await harness()
    let resolveOld!: (data: unknown) => void
    h.getEntitlements.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: null })
    h.render(); const cleanupOld = h.fetch()

    h.session({ data: { user: { id: 'a' } }, isPending: false, error: new Error('session offline') })
    const retryCompletions: Array<() => void> = []
    h.refetchSession.mockImplementation(() => new Promise<void>(resolve => { retryCompletions.push(resolve) }))
    const failed = h.render()
    failed.refresh(); failed.refresh()
    expect(h.refetchSession).toHaveBeenCalledTimes(2)
    expect(h.render().can('d01')).toBe(false)
    h.fetch()
    expect(h.getEntitlements).toHaveBeenCalledTimes(1)

    cleanupOld?.()
    h.session({ data: { user: { id: 'b' } }, isPending: false, error: null })
    h.getEntitlements.mockResolvedValueOnce({ features: { d01: false } })
    h.render(); h.fetch(); await flush()
    resolveOld({ features: { d01: true } })
    retryCompletions.forEach(resolve => resolve())
    await flush()
    expect(h.render().can('d01')).toBe(false)
    expect(h.render().features).toMatchObject({ d01: false })
  })
})


describe('bounded non-destructive background refresh', () => {
  it('keeps the exact verified feature map through a pending same-identity refresh', async () => {
    const h = await harness(); h.getEntitlements.mockResolvedValue({ features: { d01: true } })
    h.render(); h.fetch(); await flush()
    const ready = h.render(); h.listen()
    h.getEntitlements.mockImplementation(() => new Promise(() => {}))
    h.background(); const refreshing = h.render(); h.fetch()
    expect(refreshing.features).toBe(ready.features)
    expect(refreshing.can('d01')).toBe(true)
    await vi.advanceTimersByTimeAsync(8000)
    expect(h.render().can('d01')).toBe(false)
    expect(h.render().error).toContain('timed out')
  })
  it('closes on a background denial or error rather than retaining stale grants', async () => {
    const h = await harness(); h.getEntitlements.mockResolvedValue({ features: { d01: true } })
    h.render(); h.fetch(); await flush(); h.render(); h.listen()
    h.getEntitlements.mockResolvedValue({ features: { d01: false } }); h.background(); h.render(); h.fetch(); await flush()
    expect(h.render().can('d01')).toBe(false)
    h.getEntitlements.mockRejectedValue(new Error('offline')); h.background(); h.render(); h.fetch(); await flush()
    expect(h.render().error).toBe('offline')
  })
  it('expires an old grant even when background polling is throttled', async () => {
    const h = await harness(); h.getEntitlements.mockResolvedValue({ features: { d01: true } })
    h.render(); h.fetch(); await flush(); h.render(); h.expire()
    await vi.advanceTimersByTimeAsync(38000)
    expect(h.render().can('d01')).toBe(false)
    expect(h.render().error).toContain('expired')
    for (const key of ['b01', 'c01', 'c05', 'compile']) expect(h.render().can(key)).toBe(false)
    expect(h.render().can('c09')).toBe(true)
  })
})
