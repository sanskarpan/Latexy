type TimerHandle = ReturnType<typeof setTimeout>

export interface AutoCompileSchedulerOptions {
  onDispatch: (content: string) => void | Promise<void>
  debounceMs?: number
  minIntervalMs?: number
  now?: () => number
  setTimeout?: (callback: () => void, delay: number) => TimerHandle
  clearTimeout?: (timer: TimerHandle) => void
  enabled?: boolean
  busy?: boolean
}

export interface AutoCompileScheduler {
  notifyContent: (content: string) => void
  setEnabled: (enabled: boolean) => void
  setBusy: (busy: boolean) => void
  setDocument: (documentKey: string | null) => void
  markCompiled: (content: string) => void
  dispose: () => void
}

/**
 * Keep editor changes local until a quiet period and a bounded dispatch cadence
 * both permit an automatic compile. Busy state never drops the newest buffer;
 * it only prevents dispatch until the caller reports idle again.
 */
export function createAutoCompileScheduler(options: AutoCompileSchedulerOptions): AutoCompileScheduler {
  const debounceMs = options.debounceMs ?? 5_000
  const minIntervalMs = options.minIntervalMs ?? 10_000
  const now = options.now ?? (() => Date.now())
  const scheduleTimeout = options.setTimeout ??
    ((callback: () => void, delay: number) => globalThis.setTimeout(callback, delay) as TimerHandle)
  const cancelTimeout = options.clearTimeout ?? globalThis.clearTimeout
  let enabled = options.enabled ?? true
  let busy = options.busy ?? false
  let disposed = false
  let documentKey: string | null = null
  let timer: TimerHandle | null = null
  let latestContent: string | null = null
  let pendingContent: string | null = null
  let lastCompiledContent: string | null = null
  let lastDispatchAt: number | null = null
  let dispatching = false
  let generation = 0
  let quietAt: number | null = null

  const clearTimer = () => {
    if (timer !== null) {
      cancelTimeout(timer)
      timer = null
    }
  }

  const schedule = () => {
    clearTimer()
    if (disposed || !enabled || busy || dispatching || pendingContent === null || quietAt === null) return

    const quietDelay = Math.max(0, quietAt - now())
    const cadenceDelay = lastDispatchAt === null
      ? 0
      : Math.max(0, lastDispatchAt + minIntervalMs - now())
    timer = scheduleTimeout(() => {
      timer = null
      dispatchIfReady()
    }, Math.max(quietDelay, cadenceDelay))
  }

  const dispatchIfReady = () => {
    if (disposed || !enabled || busy || dispatching || pendingContent === null || quietAt === null) return
    const currentTime = now()
    if (currentTime < quietAt ||
        (lastDispatchAt !== null && currentTime < lastDispatchAt + minIntervalMs)) {
      schedule()
      return
    }

    const content = pendingContent
    pendingContent = null
    quietAt = null
    if (content === lastCompiledContent) {
      schedule()
      return
    }
    lastCompiledContent = content
    lastDispatchAt = currentTime
    dispatching = true
    const dispatchGeneration = generation
    // A page callback may be async (and may throw synchronously). Convert both
    // paths to a settled promise so editor changes never become unhandled
    // rejections. Newer content remains queued and is released only after the
    // ten-second cadence, rather than hot-looping on a failed callback.
    let result: void | Promise<void>
    try {
      result = options.onDispatch(content)
    } catch {
      dispatching = false
      schedule()
      return
    }
    if (!result || typeof (result as Promise<void>).then !== 'function') {
      dispatching = false
      schedule()
      return
    }
    void Promise.resolve(result)
      .catch(() => undefined)
      .finally(() => {
        if (dispatchGeneration !== generation) return
        dispatching = false
        schedule()
      })
  }

  const notifyContent = (content: string) => {
    if (disposed || content === latestContent) return
    latestContent = content
    if (!content.trim()) {
      pendingContent = null
      quietAt = null
      clearTimer()
      return
    }
    if (content === lastCompiledContent) {
      pendingContent = null
      quietAt = null
      clearTimer()
      return
    }
    pendingContent = content
    quietAt = now() + debounceMs
    schedule()
  }

  const setEnabled = (nextEnabled: boolean) => {
    if (disposed || enabled === nextEnabled) return
    enabled = nextEnabled
    if (!enabled) {
      clearTimer()
      return
    }
    if (pendingContent !== null) quietAt = now() + debounceMs
    schedule()
  }

  const setBusy = (nextBusy: boolean) => {
    if (disposed || busy === nextBusy) return
    busy = nextBusy
    schedule()
  }

  const setDocument = (nextDocumentKey: string | null) => {
    if (disposed || documentKey === nextDocumentKey) return
    documentKey = nextDocumentKey
    generation += 1
    clearTimer()
    dispatching = false
    latestContent = null
    pendingContent = null
    lastCompiledContent = null
    lastDispatchAt = null
    quietAt = null
  }

  const markCompiled = (content: string) => {
    if (disposed) return
    lastCompiledContent = content
    if (pendingContent === content) {
      pendingContent = null
      quietAt = null
      clearTimer()
    }
  }

  const dispose = () => {
    if (disposed) return
    disposed = true
    clearTimer()
    latestContent = null
    pendingContent = null
    quietAt = null
  }

  return { notifyContent, setEnabled, setBusy, setDocument, markCompiled, dispose }
}
