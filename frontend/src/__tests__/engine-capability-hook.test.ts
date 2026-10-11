import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EngineCapability } from '../lib/engine-capability'

const same = (a?: unknown[], b?: unknown[]) => Boolean(a && b && a.length === b.length && a.every((value, i) => Object.is(value, b[i])))
async function harness() {
  vi.resetModules()
  let index = 0; let token: string | null = null
  const slots: unknown[] = []
  const effects: Array<{ dependencies?: unknown[]; cleanup?: () => void }> = []
  const pending = new Map<number, () => void>()
  const calls: Array<{ signal: AbortSignal; resolve: (value: EngineCapability) => void; reject: (error: Error) => void }> = []
  vi.doMock('react', () => ({
    useRef: (initial: unknown) => { const at = index++; return slots[at] ??= { current: initial } },
    useState: (initial: unknown) => {
      const at = index++; if (!(at in slots)) slots[at] = initial
      return [slots[at], (value: unknown) => { slots[at] = typeof value === 'function' ? value(slots[at]) : value }]
    },
    useCallback: (callback: unknown, dependencies: unknown[]) => {
      const at = index++
      const previous = slots[at] as { callback: unknown; dependencies: unknown[] } | undefined
      if (!same(previous?.dependencies, dependencies)) slots[at] = { callback, dependencies }
      return (slots[at] as { callback: unknown }).callback
    },
    useEffect: (effect: () => void | (() => void), dependencies: unknown[]) => {
      const at = index++
      if (!same(effects[at]?.dependencies, dependencies)) pending.set(at, () => {
        effects[at]?.cleanup?.(); effects[at] = { dependencies, cleanup: effect() || undefined }
      })
    },
  }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: {
    getAuthToken: () => token,
    getEngineCapability: (signal: AbortSignal) => new Promise<EngineCapability>((resolve, reject) => calls.push({ signal, resolve, reject })),
  } }))
  const { useEngineCapability } = await import('../hooks/useEngineCapability')
  const useRender = (identity = 'anonymous', runEffects = true) => {
    index = 0
    const result = useEngineCapability(identity)
    if (runEffects) { const queued = [...pending.values()]; pending.clear(); queued.forEach(effect => effect()) }
    return result
  }
  return { render: useRender, calls, setToken: (next: string | null) => { token = next }, unmount: () => effects.forEach(effect => effect?.cleanup?.()) }
}
const settle = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() }
afterEach(() => { vi.doUnmock('react'); vi.doUnmock('@/lib/api-client'); vi.resetModules() })

describe('bounded engine capability checks', () => {
  it('checks once across edits/rerenders and keeps fallback active during a manual retry', async () => {
    const h = await harness()
    expect(h.render().status).toBe('loading')
    h.calls[0].resolve({ status: 'unsupported' }); await settle()
    for (let i = 0; i < 20; i++) expect(h.render().status).toBe('unsupported')
    expect(h.calls).toHaveLength(1)
    h.render().retry()
    expect(h.render().status).toBe('unsupported')
    expect(h.render().checking).toBe(true)
    expect(h.calls).toHaveLength(2)
    h.calls[1].resolve({ status: 'supported' }); await settle()
    expect(h.render()).toMatchObject({ status: 'supported', checking: false })
    h.unmount()
  })
  it.each(['authorization', 'unavailable'] as const)('does not retry or fall back on %s errors', async reason => {
    const h = await harness(); h.render()
    h.calls[0].resolve({ status: 'error', reason }); await settle()
    for (let i = 0; i < 20; i++) expect(h.render()).toMatchObject({ status: 'error', reason, checking: false, sourceFallback: false })
    expect(h.calls).toHaveLength(1)
    h.unmount()
  })
  it('keeps an established source fallback on retry failure without classifying denial as unsupported', async () => {
    const h = await harness(); h.render()
    h.calls[0].resolve({ status: 'unsupported' }); await settle()
    h.render().retry(); h.render()
    h.calls[1].resolve({ status: 'error', reason: 'authorization' }); await settle()
    expect(h.render()).toMatchObject({ status: 'error', reason: 'authorization', sourceFallback: true })
    h.render().retry(); h.render()
    h.calls[2].resolve({ status: 'supported' }); await settle()
    expect(h.render()).toMatchObject({ status: 'supported', sourceFallback: false })
    h.unmount()
  })
  it('allows explicit recovery from a network failure without looping', async () => {
    const h = await harness(); h.render()
    h.calls[0].reject(new Error('offline')); await settle()
    expect(h.render()).toMatchObject({ status: 'error', reason: 'unavailable', checking: false })
    h.render().retry(); h.render()
    h.calls[1].resolve({ status: 'supported' }); await settle()
    expect(h.render().status).toBe('supported')
    expect(h.calls).toHaveLength(2)
    h.unmount()
  })
  it('hides old results and rejects a late old-account response before effect cleanup', async () => {
    const h = await harness(); h.render('old-owner')
    h.setToken('new-token')
    expect(h.render('new-owner', false).status).toBe('loading')
    h.calls[0].resolve({ status: 'unsupported' }); await settle()
    expect(h.render('new-owner').status).toBe('loading')
    expect(h.calls[0].signal.aborted).toBe(true)
    h.calls[1].resolve({ status: 'supported' }); await settle()
    expect(h.render('new-owner').status).toBe('supported')
    h.unmount()
  })
  it('aborts on unmount and ignores an already-received response', async () => {
    const h = await harness(); h.render(); h.unmount()
    expect(h.calls[0].signal.aborted).toBe(true)
    h.calls[0].resolve({ status: 'supported' }); await settle()
    expect(h.render().status).toBe('loading')
  })
})
