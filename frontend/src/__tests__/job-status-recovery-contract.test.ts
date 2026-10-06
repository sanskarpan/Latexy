import { describe, expect, it, vi } from 'vitest'

type Effect = () => void | (() => void)

interface HookHarness {
  react: Record<string, unknown>
  render: <T>(callback: () => T) => T
  flushEffects: () => void
  stateUpdates: () => number
  unmount: () => void
}

function createHookHarness(): HookHarness {
  type Slot = {
    kind: 'ref' | 'state' | 'memo' | 'effect'
    value?: unknown
    deps?: unknown[]
    cleanup?: () => void
  }
  type PendingEffect = { effect: Effect; slot: Slot }

  const slots: Slot[] = []
  const pending: PendingEffect[] = []
  let cursor = 0
  let stateUpdateCount = 0

  const sameDeps = (left: unknown[] | undefined, right: unknown[] | undefined) =>
    Boolean(left && right && left.length === right.length && left.every((value, index) => Object.is(value, right[index])))

  const next = (kind: Slot['kind'], value?: unknown): Slot => {
    const slot = slots[cursor]
    cursor += 1
    if (slot) return slot
    const created: Slot = { kind, value }
    slots.push(created)
    return created
  }

  const react = {
    useRef: <T>(initialValue: T) => next('ref', { current: initialValue }).value as { current: T },
    useState: <T>(initialValue: T) => {
      const slot = next('state', initialValue)
      return [slot.value as T, (value: T | ((previous: T) => T)) => {
        stateUpdateCount += 1
        slot.value = typeof value === 'function'
          ? (value as (previous: T) => T)(slot.value as T)
          : value
      }] as const
    },
    useCallback: <T extends (...args: never[]) => unknown>(callback: T, deps: unknown[]) => {
      const slot = next('memo', { callback, deps })
      const previous = slot.value as { callback: T; deps: unknown[] }
      if (!sameDeps(previous.deps, deps)) slot.value = { callback, deps }
      return (slot.value as { callback: T }).callback
    },
    useEffect: (effect: Effect, deps?: unknown[]) => {
      const slot = next('effect', undefined)
      const changed = !sameDeps(slot.deps, deps)
      if (changed) {
        slot.deps = deps
        pending.push({ effect, slot })
      }
    },
  }

  return {
    react,
    render: <T>(callback: () => T) => {
      cursor = 0
      return callback()
    },
    flushEffects: () => {
      const effects = pending.splice(0)
      for (const { effect, slot } of effects) {
        slot.cleanup?.()
        slot.cleanup = effect() ?? undefined
      }
    },
    stateUpdates: () => stateUpdateCount,
    unmount: () => {
      pending.splice(0)
      for (const slot of slots) {
        slot.cleanup?.()
        slot.cleanup = undefined
      }
    },
  }
}

async function setupHook() {
  vi.resetModules()
  vi.useFakeTimers()

  const harness = createHookHarness()
  const streamState = {
    status: 'idle' as 'idle' | 'queued' | 'processing' | 'completed' | 'failed',
    stage: '',
    percent: 0,
    message: '',
    pdfJobId: null as string | null,
    atsScore: null as number | null,
    atsDetails: null as Record<string, unknown> | null,
    changesMade: [],
    compilationTime: null,
    optimizationTime: null,
    tokensUsed: null,
    error: null as string | null,
  }
  const stateWaiters: Array<{
    resolve: (state: Record<string, unknown>) => void
    reject: (error: Error) => void
  }> = []
  const getJobState = vi.fn(() => new Promise<Record<string, unknown>>((resolve, reject) => stateWaiters.push({ resolve, reject })))
  const resultPayload = {
    success: true,
    job_id: 'job-1',
    pdf_job_id: 'pdf-1',
    ats_score: 88,
    ats_details: { category_scores: { skills: 90 }, recommendations: [], strengths: [], warnings: [] },
  }
  const resultWaiters: Array<(result: typeof resultPayload) => void> = []
  const getJobResult = vi.fn(() => new Promise<typeof resultPayload>((resolve) => resultWaiters.push(resolve)))
  const applySnapshot = vi.fn()

  vi.doMock('react', () => harness.react)
  vi.doMock('@/lib/api-client', () => ({ apiClient: { getJobState, getJobResult, cancelJob: vi.fn() } }))
  vi.doMock('@/hooks/useJobStream', () => ({
    useJobStream: () => ({
      state: streamState,
      cancel: vi.fn(),
      reset: vi.fn(),
      applySnapshot,
    }),
  }))

  const { useJobStatus } = await import('../hooks/useJobStatus')
  const resolveState = (state: Record<string, unknown>) => stateWaiters.shift()?.resolve(state)
  const rejectState = (error = new Error('network unavailable')) => stateWaiters.shift()?.reject(error)
  const resolveResult = () => resultWaiters.shift()?.(resultPayload)
  const cleanup = () => {
    harness.unmount()
    vi.doUnmock('react')
    vi.doUnmock('@/lib/api-client')
    vi.doUnmock('@/hooks/useJobStream')
    vi.restoreAllMocks()
    vi.useRealTimers()
    vi.resetModules()
  }

  return { harness, streamState, getJobState, getJobResult, applySnapshot, resolveState, rejectState, resolveResult, useJobStatus, cleanup }
}

describe('useJobStatus REST recovery behavior', () => {
  it('does not complete from /state before the authoritative result arrives', async () => {
    const setup = await setupHook()
    try {
      const completions: Array<{ job_id: string; result?: Record<string, unknown> }> = []
      let hook = setup.harness.render(() => setup.useJobStatus('job-1', {
        onComplete: (payload) => completions.push(payload),
      }))
      setup.harness.flushEffects()
      setup.resolveState({ status: 'processing', stage: 'compile', percent: 50 })
      await Promise.resolve()

      void hook.refresh()
      setup.resolveState({ status: 'completed', stage: 'done', percent: 100 })
      await Promise.resolve()
      expect(completions).toHaveLength(0)

      setup.streamState.status = 'completed'
      setup.streamState.pdfJobId = 'pdf-1'
      setup.streamState.atsScore = 88
      setup.streamState.atsDetails = { category_scores: { skills: 90 } }
      hook = setup.harness.render(() => setup.useJobStatus('job-1', {
        onComplete: (payload) => completions.push(payload),
      }))
      setup.harness.flushEffects()

      expect(completions).toHaveLength(1)
      expect(completions[0]).toMatchObject({ job_id: 'pdf-1', result: { overall_score: 88 } })
    } finally {
      setup.cleanup()
    }
  })

  it('keeps a same-job stream terminal authoritative over late REST progress and failure', async () => {
    const setup = await setupHook()
    try {
      const completions: unknown[] = []
      const statuses: unknown[] = []
      const errors: string[] = []
      let hook = setup.harness.render(() => setup.useJobStatus('job-1', {
        onComplete: (payload) => completions.push(payload),
        onStatusChange: (status) => statuses.push(status),
        onError: (error) => errors.push(error),
      }))
      setup.harness.flushEffects()
      setup.resolveState({ status: 'processing', stage: 'compile', percent: 20 })
      await Promise.resolve()

      void hook.refresh() // deferred REST response
      setup.streamState.status = 'completed'
      setup.streamState.pdfJobId = 'pdf-1'
      setup.streamState.atsScore = 88
      hook = setup.harness.render(() => setup.useJobStatus('job-1', {
        onComplete: (payload) => completions.push(payload),
        onStatusChange: (status) => statuses.push(status),
        onError: (error) => errors.push(error),
      }))
      setup.harness.flushEffects()
      expect(completions).toHaveLength(1)

      // The old REST request resolves after the stream is already terminal.
      setup.resolveState({ status: 'processing', stage: 'late-progress', percent: 60 })
      await Promise.resolve()
      expect(statuses).not.toContainEqual(expect.objectContaining({ stage: 'late-progress' }))
      expect(errors).toEqual([])

      // A second late terminal response is also ignored without duplicating.
      void hook.refresh()
      setup.resolveState({ status: 'failed', stage: 'late-failure', percent: 60 })
      await Promise.resolve()
      expect(completions).toHaveLength(1)
      expect(errors).toEqual([])
    } finally {
      setup.cleanup()
    }
  })

  it('does not let a late A response complete the replacement B job', async () => {
    const setup = await setupHook()
    try {
      const aCompletions: unknown[] = []
      const bCompletions: unknown[] = []
      let hook = setup.harness.render(() => setup.useJobStatus('job-A', {
        onComplete: (payload) => aCompletions.push(payload),
      }))
      setup.harness.flushEffects()
      setup.resolveState({ status: 'processing', stage: 'compile', percent: 10 })
      await Promise.resolve()

      void hook.refresh()
      hook = setup.harness.render(() => setup.useJobStatus('job-B', {
        onComplete: (payload) => bCompletions.push(payload),
      }))
      setup.harness.flushEffects()

      setup.resolveState({ status: 'completed', stage: 'done', percent: 100 })
      await Promise.resolve()

      expect(aCompletions).toHaveLength(0)
      expect(bCompletions).toHaveLength(0)
    } finally {
      setup.cleanup()
    }
  })

  it('rejects old A after B while allowing a new A generation to complete', async () => {
    const setup = await setupHook()
    try {
      const oldA: unknown[] = []
      const newA: unknown[] = []
      let hook = setup.harness.render(() => setup.useJobStatus('job-A', {
        onComplete: (payload) => oldA.push(payload),
      }))
      setup.harness.flushEffects()
      setup.resolveState({ status: 'processing', stage: 'compile', percent: 10 })
      await Promise.resolve()

      void hook.refresh() // old A request remains deferred
      hook = setup.harness.render(() => setup.useJobStatus('job-B'))
      setup.harness.flushEffects()
      setup.resolveState({ status: 'completed', stage: 'old-A-terminal', percent: 100 })
      await Promise.resolve()
      expect(oldA).toEqual([])

      // Finish B's own in-flight request before returning to A.
      setup.resolveState({ status: 'processing', stage: 'compile', percent: 20 })
      await Promise.resolve()

      setup.streamState.status = 'completed'
      setup.streamState.pdfJobId = 'pdf-new-A'
      setup.streamState.atsScore = 95
      hook = setup.harness.render(() => setup.useJobStatus('job-A', {
        onComplete: (payload) => newA.push(payload),
      }))
      setup.harness.flushEffects()

      expect(oldA).toEqual([])
      expect(newA).toHaveLength(1)
      expect(newA[0]).toMatchObject({ job_id: 'pdf-new-A', result: { overall_score: 95 } })
    } finally {
      setup.cleanup()
    }
  })

  it('does not inherit A terminal polling markers across an uncommitted ABA render', async () => {
    const setup = await setupHook()
    try {
      const statuses: unknown[] = []
      let hook = setup.harness.render(() => setup.useJobStatus('job-A'))
      setup.harness.flushEffects()
      setup.resolveState({ status: 'completed', stage: 'done', percent: 100 })
      await Promise.resolve()

      // Commit A's terminal marker in the hook state, then render B and A
      // again before B's passive effects run. Generation-based markers must
      // still allow the new A fallback to process queued progress.
      setup.harness.render(() => setup.useJobStatus('job-A'))
      setup.harness.render(() => setup.useJobStatus('job-B'))
      hook = setup.harness.render(() => setup.useJobStatus('job-A', {
        onStatusChange: (status) => statuses.push(status),
      }))
      void hook.refresh()
      setup.harness.flushEffects()
      setup.resolveState({ status: 'queued', stage: 'new-A', percent: 0 })
      await Promise.resolve()

      expect(setup.applySnapshot).toHaveBeenCalledWith({ status: 'queued', percent: 0, stage: 'new-A' })
      expect(statuses).toContainEqual({ status: 'queued', percent: 0, stage: 'new-A' })
    } finally {
      setup.cleanup()
    }
  })

  it('does not apply delayed A progress to B after the identity changes', async () => {
    const setup = await setupHook()
    try {
      const aStatus: unknown[] = []
      const bStatus: unknown[] = []
      let hook = setup.harness.render(() => setup.useJobStatus('job-A', {
        onStatusChange: (status) => aStatus.push(status),
      }))
      setup.harness.flushEffects()
      setup.resolveState({ status: 'processing', stage: 'compile', percent: 10 })
      await Promise.resolve()

      void hook.refresh()
      const snapshotsBeforeA = setup.getJobState.mock.calls.length
      hook = setup.harness.render(() => setup.useJobStatus('job-B', {
        onStatusChange: (status) => bStatus.push(status),
      }))
      setup.harness.flushEffects()

      setup.resolveState({ status: 'processing', stage: 'stale-A', percent: 80 })
      await Promise.resolve()

      expect(aStatus).not.toContainEqual(expect.objectContaining({ stage: 'stale-A' }))
      expect(bStatus).not.toContainEqual(expect.objectContaining({ stage: 'stale-A' }))
      expect(setup.getJobState.mock.calls.length).toBeGreaterThan(snapshotsBeforeA)
    } finally {
      setup.cleanup()
    }
  })

  it('does not surface a delayed A failure through B callbacks', async () => {
    const setup = await setupHook()
    try {
      const aErrors: string[] = []
      const bErrors: string[] = []
      let hook = setup.harness.render(() => setup.useJobStatus('job-A', {
        onError: (error) => aErrors.push(error),
      }))
      setup.harness.flushEffects()
      setup.resolveState({ status: 'processing', stage: 'compile', percent: 10 })
      await Promise.resolve()

      void hook.refresh()
      hook = setup.harness.render(() => setup.useJobStatus('job-B', {
        onError: (error) => bErrors.push(error),
      }))
      setup.harness.flushEffects()
      setup.resolveState({ status: 'failed', stage: 'compile', percent: 10 })
      await Promise.resolve()

      expect(aErrors).toEqual([])
      expect(bErrors).toEqual([])
    } finally {
      setup.cleanup()
    }
  })

  it('ignores a rejected A refresh after switching to B', async () => {
    const setup = await setupHook()
    try {
      const errors: string[] = []
      let hook = setup.harness.render(() => setup.useJobStatus('job-A', {
        onError: (error) => errors.push(error),
      }))
      setup.harness.flushEffects()
      setup.resolveState({ status: 'processing', stage: 'compile', percent: 10 })
      await Promise.resolve()

      void hook.refresh()
      hook = setup.harness.render(() => setup.useJobStatus('job-B', {
        onError: (error) => errors.push(error),
      }))
      setup.harness.flushEffects()
      setup.rejectState()
      await Promise.resolve()

      expect(errors).toEqual([])
    } finally {
      setup.cleanup()
    }
  })

  it('preserves same-job queued progress through the REST fallback', async () => {
    const setup = await setupHook()
    try {
      const statuses: Array<{ status: string; percent: number; stage: string }> = []
      let hook = setup.harness.render(() => setup.useJobStatus('job-1', {
        onStatusChange: (status) => statuses.push(status),
      }))
      setup.harness.flushEffects()
      setup.resolveState({ status: 'processing', stage: 'compile', percent: 10 })
      await Promise.resolve()

      void hook.refresh()
      setup.resolveState({ status: 'queued', stage: 'waiting', percent: 0 })
      await Promise.resolve()

      expect(setup.applySnapshot).toHaveBeenCalledWith({ status: 'queued', percent: 0, stage: 'waiting' })
      expect(statuses).toContainEqual({ status: 'queued', percent: 0, stage: 'waiting' })
    } finally {
      setup.cleanup()
    }
  })

  it('invalidates in-flight work and clears polling timers on unmount', async () => {
    const setup = await setupHook()
    try {
      const completions: unknown[] = []
      const errors: string[] = []
      let hook = setup.harness.render(() => setup.useJobStatus('job-1', {
        onComplete: (payload) => completions.push(payload),
        onError: (error) => errors.push(error),
      }))
      setup.harness.flushEffects()
      void hook.refresh()

      setup.harness.unmount()
      expect(vi.getTimerCount()).toBe(0)

      // Both the initial poll and the explicit refresh resolve after unmount.
      setup.resolveState({ status: 'completed', stage: 'late', percent: 100 })
      setup.resolveState({ status: 'failed', stage: 'late', percent: 0 })
      await Promise.resolve()
      expect(completions).toEqual([])
      expect(errors).toEqual([])
    } finally {
      setup.cleanup()
    }
  })

  it('does not let an old stop timer mark B stopped before passive cleanup', async () => {
    const setup = await setupHook()
    const timeoutCallbacks: Array<() => void> = []
    const timeoutSpy = vi.spyOn(globalThis, 'setTimeout').mockImplementation((handler) => {
      if (typeof handler === 'function') timeoutCallbacks.push(handler)
      return 1 as unknown as ReturnType<typeof setTimeout>
    })
    try {
      setup.harness.render(() => setup.useJobStatus('job-A'))
      setup.harness.flushEffects()
      expect(timeoutCallbacks).toHaveLength(1)

      // Render B, then let A's timer fire before B's passive effects run.
      setup.harness.render(() => setup.useJobStatus('job-B'))
      const stateUpdatesBeforeTimer = setup.harness.stateUpdates()
      timeoutCallbacks[0]()
      expect(setup.harness.stateUpdates()).toBe(stateUpdatesBeforeTimer)
    } finally {
      timeoutSpy.mockRestore()
      setup.cleanup()
    }
  })

  it('preserves healthy stream completion and one-shot callback behavior', async () => {
    const setup = await setupHook()
    try {
      const completions: unknown[] = []
      setup.harness.render(() => setup.useJobStatus('job-1', {
        onComplete: (payload) => completions.push(payload),
      }))
      setup.harness.flushEffects()
      setup.resolveState({ status: 'processing', stage: 'compile', percent: 50 })
      await Promise.resolve()

      setup.streamState.status = 'completed'
      setup.streamState.pdfJobId = 'pdf-1'
      setup.streamState.atsScore = 88
      setup.harness.render(() => setup.useJobStatus('job-1', {
        onComplete: (payload) => completions.push(payload),
      }))
      setup.harness.flushEffects()
      setup.harness.render(() => setup.useJobStatus('job-1', {
        onComplete: (payload) => completions.push(payload),
      }))
      setup.harness.flushEffects()

      expect(completions).toHaveLength(1)
      expect(completions[0]).toMatchObject({ job_id: 'pdf-1', result: { overall_score: 88 } })
    } finally {
      setup.cleanup()
    }
  })
})
