import { afterEach, expect, it, vi } from 'vitest'

const source = '\\documentclass{article}' + ' resume '.repeat(40)
const response = (score: number) => ({ score, grade: 'B', sections_found: [], missing_sections: [], keyword_match_percent: null })
const same = (a?: unknown[], b?: unknown[]) => Boolean(a && b && a.length === b.length && a.every((value, i) => Object.is(value, b[i])))

async function harness() {
  vi.resetModules()
  vi.useFakeTimers()
  let index = 0
  const slots: unknown[] = []
  const pending: Array<() => void> = []
  const effects: Array<{ dependencies?: unknown[]; cleanup?: () => void }> = []
  const calls: Array<{ source: string; signal: AbortSignal; resolve: (value: ReturnType<typeof response>) => void }> = []
  vi.doMock('react', () => ({
    useRef: (initial: unknown) => {
      const at = index++
      slots[at] ??= { current: initial }
      return slots[at]
    },
    useState: (initial: unknown) => {
      const at = index++
      if (!(at in slots)) slots[at] = initial
      return [slots[at], (value: unknown) => { slots[at] = value }]
    },
    useCallback: (callback: unknown, dependencies: unknown[]) => {
      const at = index++
      const previous = slots[at] as { callback: unknown; dependencies: unknown[] } | undefined
      if (!same(previous?.dependencies, dependencies)) slots[at] = { callback, dependencies }
      return (slots[at] as { callback: unknown }).callback
    },
    useEffect: (effect: () => void | (() => void), dependencies?: unknown[]) => {
      const at = index++
      if (same(effects[at]?.dependencies, dependencies)) return
      pending.push(() => {
        effects[at]?.cleanup?.()
        effects[at] = { dependencies, cleanup: effect() || undefined }
      })
    },
  }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: {
    // Deliberately resolve even after abort, like a response already received
    // by the browser. Cancellation alone cannot provide stale-state safety.
    quickScoreATS: (content: string, _job: string | undefined, signal: AbortSignal) => new Promise<ReturnType<typeof response>>(resolve => {
      calls.push({ source: content, signal, resolve })
    }),
  } }))
  const { useQuickATSScore } = await import('../hooks/useQuickATSScore')
  const useRenderHook = (content = source, job?: string) => {
    index = 0
    const value = useQuickATSScore(content, job)
    pending.splice(0).forEach(effect => effect())
    return value
  }
  return { render: useRenderHook, calls, unmount: () => effects.forEach(effect => effect?.cleanup?.()) }
}

afterEach(() => { vi.useRealTimers(); vi.doUnmock('react'); vi.doUnmock('@/lib/api-client') })

it('starts the first score immediately and deduplicates concurrent and completed refetches', async () => {
  const h = await harness()
  let value = h.render()
  await vi.advanceTimersByTimeAsync(0)
  expect(h.calls).toHaveLength(1)
  const first = value.refetch()
  const second = value.refetch()
  expect(h.calls).toHaveLength(1)
  h.calls[0].resolve(response(82))
  await Promise.all([first, second])
  value = h.render()
  expect(value.score).toBe(82)
  await value.refetch()
  expect(h.calls).toHaveLength(1)
  h.unmount()
})

it('aborts obsolete input and ignores its late response while accepting the new score', async () => {
  const h = await harness()
  h.render()
  await vi.advanceTimersByTimeAsync(0)
  h.render(source + ' updated')
  expect(h.calls[0].signal.aborted).toBe(true)
  h.calls[0].resolve(response(10))
  await vi.advanceTimersByTimeAsync(0)
  expect(h.render(source + ' updated').score).toBeNull()
  await vi.advanceTimersByTimeAsync(2000)
  expect(h.calls).toHaveLength(2)
  expect(h.calls[1].source).toContain('updated')
  h.calls[1].resolve(response(90))
  await vi.advanceTimersByTimeAsync(0)
  expect(h.render(source + ' updated').score).toBe(90)
  h.unmount()
})

it('scores the latest typing burst within two seconds and treats job description changes as new input', async () => {
  const h = await harness()
  h.render()
  await vi.advanceTimersByTimeAsync(0)
  h.calls[0].resolve(response(70))
  await vi.advanceTimersByTimeAsync(0)
  h.render(source + ' one')
  await vi.advanceTimersByTimeAsync(300)
  h.render(source + ' two')
  await vi.advanceTimersByTimeAsync(1700)
  expect(h.calls).toHaveLength(2)
  expect(h.calls[1].source).toBe(source + ' two')
  h.calls[1].resolve(response(80))
  await vi.advanceTimersByTimeAsync(0)
  const tailored = h.render(source + ' two', 'Different target job')
  const request = tailored.refetch()
  expect(h.calls).toHaveLength(3)
  h.calls[2].resolve(response(65))
  await request
  expect(h.render(source + ' two', 'Different target job').score).toBe(65)
  h.unmount()
})

it('does not score tiny documents and aborts on unmount without starting a pending request', async () => {
  const h = await harness()
  await h.render('tiny').refetch()
  await vi.advanceTimersByTimeAsync(10000)
  expect(h.calls).toHaveLength(0)
  h.render()
  await vi.advanceTimersByTimeAsync(0)
  h.render(source + ' pending')
  h.unmount()
  expect(h.calls[0].signal.aborted).toBe(true)
  h.calls[0].resolve(response(99))
  await vi.advanceTimersByTimeAsync(10000)
  expect(h.calls).toHaveLength(1)
})

it('ignores a retained refetch callback after the document input changes', async () => {
  const h = await harness()
  h.render()
  await vi.advanceTimersByTimeAsync(0)
  h.calls[0].resolve(response(82))
  await vi.advanceTimersByTimeAsync(0)
  const old = h.render()
  h.render(source + ' new document')
  await old.refetch()
  expect(h.render(source + ' new document').score).toBeNull()
  expect(h.calls).toHaveLength(1)
  h.unmount()
})
