import { afterEach, describe, expect, it, vi } from 'vitest'

type VNode = { type: unknown; props: Record<string, unknown> }

type Props = {
  resumeId: string
  resumeTitle: string
  onClose: () => void
  onDone?: (forkId: string) => void
}

type Instance = {
  render: (nextProps?: Props) => VNode
  flushEffects: () => void
  unmount: () => void
}

function textContent(node: unknown): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (!node || typeof node !== 'object') return ''
  const candidate = node as VNode
  const children = candidate.props?.children
  return Array.isArray(children) ? children.map(textContent).join('') : textContent(children)
}

function findButton(node: unknown, label: string): VNode | null {
  if (!node || typeof node !== 'object') return null
  const candidate = node as VNode
  if (candidate.type === 'button' && textContent(candidate).includes(label)) return candidate
  const children = candidate.props?.children
  if (Array.isArray(children)) {
    for (const child of children) {
      const found = findButton(child, label)
      if (found) return found
    }
  } else {
    return findButton(children, label)
  }
  return null
}

function findByProp(node: unknown, prop: string, value: string): VNode | null {
  if (!node || typeof node !== 'object') return null
  const candidate = node as VNode
  if (candidate.props?.[prop] === value) return candidate
  const children = candidate.props?.children
  if (Array.isArray(children)) {
    for (const child of children) {
      const found = findByProp(child, prop, value)
      if (found) return found
    }
  } else {
    return findByProp(children, prop, value)
  }
  return null
}

async function loadHarness() {
  vi.resetModules()
  let activeInstance: InstanceState | null = null
  const streamStates = new Map<string, { status: string; error?: string }>()
  const grantedFeatures = new Set(['d04', 'd01', 'd18', 'c05', 'b01', 'c01'])
  const quickTailorResume = vi.fn()
  const cancel = vi.fn()
  const reset = vi.fn()
  vi.stubGlobal('document', {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })

  type InstanceState = {
    props: Props
    hookIndex: number
    states: unknown[]
    pendingEffects: Array<() => void | (() => void)>
    cleanups: Array<() => void>
  }

  vi.doMock('react', () => ({
    useCallback: (callback: unknown) => callback,
    useRef: (initial: unknown) => {
      if (!activeInstance) throw new Error('ref read outside render')
      const instance = activeInstance
      const index = instance.hookIndex++
      if (!(index in instance.states)) instance.states[index] = { current: initial }
      return instance.states[index]
    },
    useEffect: (effect: () => void | (() => void)) => {
      if (!activeInstance) throw new Error('effect registered outside render')
      activeInstance.pendingEffects.push(effect)
    },
    useState: (initial: unknown) => {
      if (!activeInstance) throw new Error('state read outside render')
      const instance = activeInstance
      const index = instance.hookIndex++
      if (!(index in instance.states)) instance.states[index] = initial
      return [instance.states[index], (value: unknown) => {
        instance.states[index] = typeof value === 'function'
          ? (value as (previous: unknown) => unknown)(instance.states[index])
          : value
      }]
    },
  }))
  vi.doMock('react/jsx-runtime', () => ({
    jsx: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
    jsxs: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
  }))
  vi.doMock('lucide-react', () => ({
    AlertCircle: 'AlertCircle',
    ArrowRight: 'ArrowRight',
    CheckCircle: 'CheckCircle',
    Loader2: 'Loader2',
    X: 'X',
    Zap: 'Zap',
  }))
  vi.doMock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
  vi.doMock('@/hooks/useJobStream', () => ({
    useJobStream: (jobId: string | null) => ({
      state: jobId ? (streamStates.get(jobId) ?? { status: 'queued' }) : { status: 'idle' },
      cancel,
      reset,
    }),
  }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: { quickTailorResume } }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({
    useEntitlements: () => ({ can: (feature: string) => grantedFeatures.has(feature) }),
  }))

  const QuickTailorModal = (await import('../components/QuickTailorModal')).default

  const createInstance = (initialProps: Props): Instance => {
    const instance: InstanceState = {
      props: initialProps,
      hookIndex: 0,
      states: [],
      pendingEffects: [],
      cleanups: [],
    }
    return {
      render(nextProps = instance.props) {
        instance.props = nextProps
        instance.hookIndex = 0
        instance.pendingEffects = []
        activeInstance = instance
        try {
          return QuickTailorModal(instance.props) as unknown as VNode
        } finally {
          activeInstance = null
        }
      },
      flushEffects() {
        const effects = instance.pendingEffects
        instance.pendingEffects = []
        for (const effect of effects) {
          const cleanup = effect()
          if (cleanup) instance.cleanups.push(cleanup)
        }
      },
      unmount() {
        while (instance.cleanups.length) instance.cleanups.pop()?.()
      },
    }
  }

  return { createInstance, quickTailorResume, streamStates, cancel, grantedFeatures }
}

afterEach(() => {
  vi.unstubAllGlobals()
  for (const moduleName of [
    'react',
    'react/jsx-runtime',
    'lucide-react',
    'next/navigation',
    '@/hooks/useJobStream',
    '@/lib/api-client',
    '@/contexts/EntitlementsContext',
  ]) vi.doUnmock(moduleName)
  vi.resetModules()
})

describe('Quick Tailor deferred lifecycle', () => {
  it('does not replay a closed owner A completion into a reopened owner B modal', async () => {
    const harness = await loadHarness()
    let resolveStart!: (value: { fork_id: string; job_id: string }) => void
    harness.quickTailorResume.mockImplementationOnce(
      () => new Promise((resolve) => { resolveStart = resolve }),
    )
    const onCloseA = vi.fn()
    const onDoneA = vi.fn()
    const ownerA = harness.createInstance({
      resumeId: 'resume-a', resumeTitle: 'Resume A', onClose: onCloseA, onDone: onDoneA,
    })
    const first = ownerA.render()
    ownerA.flushEffects()
    const description = findByProp(first, 'placeholder', 'Paste the full job description here...')
    expect(description).not.toBeNull()
    ;(description!.props.onChange as (event: { target: { value: string } }) => void)({ target: { value: 'A long enough job description' } })
    const start = findButton(ownerA.render(), 'Start Tailoring')
    expect(start).not.toBeNull()
    void (start!.props.onClick as () => Promise<void>)()
    expect(harness.quickTailorResume).toHaveBeenCalledWith('resume-a', expect.anything())

    const close = findByProp(first, 'aria-label', 'Close Quick Tailor')
    expect(close).not.toBeNull()
    ;(close!.props.onClick as () => void)()
    expect(onCloseA).toHaveBeenCalledTimes(1)
    ownerA.unmount()
    const onDoneB = vi.fn()
    const ownerB = harness.createInstance({
      resumeId: 'resume-b', resumeTitle: 'Resume B', onClose: vi.fn(), onDone: onDoneB,
    })
    ownerB.render()
    ownerB.flushEffects()

    resolveStart({ fork_id: 'fork-a', job_id: 'job-a' })
    await Promise.resolve()
    await Promise.resolve()
    harness.streamStates.set('job-a', { status: 'completed' })
    ownerB.render()
    ownerB.flushEffects()

    expect(onDoneA).not.toHaveBeenCalled()
    expect(onDoneB).not.toHaveBeenCalled()
    expect(harness.cancel).not.toHaveBeenCalled()
  })

  it('hides the new tailoring action when any required capability is off', async () => {
    const harness = await loadHarness()
    harness.grantedFeatures.delete('b01')
    const instance = harness.createInstance({
      resumeId: 'resume-a', resumeTitle: 'Resume A', onClose: vi.fn(),
    })
    const view = instance.render()
    expect(findButton(view, 'Start Tailoring')).toBeNull()
    expect(textContent(view)).toContain('one or more required features are turned off')
  })

  it('tracks already-admitted work if required access is revoked while submitting', async () => {
    const harness = await loadHarness()
    let resolveStart!: (value: { fork_id: string; job_id: string }) => void
    harness.quickTailorResume.mockImplementationOnce(
      () => new Promise((resolve) => { resolveStart = resolve }),
    )
    const instance = harness.createInstance({
      resumeId: 'resume-a', resumeTitle: 'Resume A', onClose: vi.fn(),
    })
    const initial = instance.render()
    const description = findByProp(initial, 'placeholder', 'Paste the full job description here...')
    expect(description).not.toBeNull()
    ;(description!.props.onChange as (event: { target: { value: string } }) => void)({ target: { value: 'A long enough job description' } })
    const submit = findButton(instance.render(), 'Start Tailoring')
    expect(submit).not.toBeNull()
    const submission = (submit!.props.onClick as () => Promise<void>)()
    harness.grantedFeatures.delete('d18')
    resolveStart({ fork_id: 'fork-a', job_id: 'job-a' })
    await submission

    const after = instance.render()
    expect(textContent(after)).toContain('This typically takes 30–90 seconds')
    harness.streamStates.set('job-a', { status: 'failed', error: 'Synthetic failure' })
    instance.render()
    instance.flushEffects()
    expect(textContent(instance.render())).toContain('Synthetic failure')
    expect(findButton(instance.render(), 'Try Again')).toBeNull()
  })
})
