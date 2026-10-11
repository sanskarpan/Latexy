import { afterEach, describe, expect, it, vi } from 'vitest'

type HookSlot = { current?: unknown; dependencies?: unknown[]; value?: unknown; cleanup?: (() => void) | void }

// Minimal hook-lifecycle harness: retain hook values, execute effect cleanups,
// and expose the render-before-effects window without claiming DOM coverage.
async function harness() {
  const slots: HookSlot[] = []
  let index = 0
  let effects: Array<() => void> = []
  const changed = (previous: unknown[] | undefined, next: unknown[]) => !previous || previous.length !== next.length || next.some((value, i) => !Object.is(value, previous[i]))
  vi.doMock('react', () => ({
    useRef: (current: unknown) => slots[index++] ??= { current },
    useMemo: (create: () => unknown, dependencies: unknown[]) => {
      const slot = slots[index++] ??= {}
      if (changed(slot.dependencies, dependencies)) { slot.value = create(); slot.dependencies = dependencies }
      return slot.value
    },
    useEffect: (effect: () => (() => void) | void, dependencies: unknown[]) => {
      const slot = slots[index++] ??= {}
      if (changed(slot.dependencies, dependencies)) {
        slot.dependencies = dependencies
        effects.push(() => { slot.cleanup?.(); slot.cleanup = effect() })
      }
    },
  }))
  const { usePreviewScheduler } = await import('@/hooks/usePreviewScheduler')
  return {
    useRender(identity: string, submit: (source: string) => Promise<string | null>) {
      index = 0
      return usePreviewScheduler({ identity, enabled: true, blocked: false, jobId: null, status: 'idle', submit })
    },
    flush() { const pending = effects; effects = []; pending.forEach(effect => effect()) },
    dispose() { slots.forEach(slot => slot.cleanup?.()) },
  }
}

afterEach(() => { vi.useRealTimers(); vi.resetModules(); vi.doUnmock('react') })

describe('preview scheduler account incarnation', () => {
  it('rejects callbacks and pending timers from the first A after A → B → A before effects run', async () => {
    vi.useFakeTimers()
    const h = await harness()
    const oldAutomatic = vi.fn().mockResolvedValue('old-auto')
    const oldManual = vi.fn().mockResolvedValue('old-manual')
    const currentAutomatic = vi.fn().mockResolvedValue('current-auto')
    const firstA = h.useRender('A', oldAutomatic); h.flush()
    firstA('old pending source', undefined, true)
    const b = h.useRender('B', currentAutomatic)
    const secondA = h.useRender('A', currentAutomatic)
    expect(secondA).not.toBe(firstA)
    await firstA.submitManual('old pending source', oldManual)
    await b.submitManual('B source', oldManual)
    firstA('stale callback', undefined, true)
    await vi.advanceTimersByTimeAsync(0)
    expect(oldManual).not.toHaveBeenCalled()
    expect(oldAutomatic).not.toHaveBeenCalled()
    expect(currentAutomatic).not.toHaveBeenCalled()
    h.flush()
    secondA('current source', undefined, true)
    await vi.advanceTimersByTimeAsync(0)
    expect(currentAutomatic).toHaveBeenCalledExactlyOnceWith('current source')
    h.dispose()
  })

  it('preserves a pending manual fence on ordinary same-account rerenders', async () => {
    const h = await harness()
    const automatic = vi.fn().mockResolvedValue('auto-job')
    let resolve!: (job: string) => void
    const manual = vi.fn(() => new Promise<string>(yes => { resolve = yes }))
    const first = h.useRender('A', automatic); h.flush()
    const pending = first.submitManual('source', manual)
    const same = h.useRender('A', automatic); h.flush()
    expect(same).toBe(first)
    await same.submitManual('source', manual)
    expect(manual).toHaveBeenCalledOnce()
    resolve('manual-job'); await pending
    h.dispose()
  })
})
