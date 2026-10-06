import { afterEach, describe, expect, it, vi } from 'vitest'

type VNode = { type: unknown; props: Record<string, unknown> }

type Harness = {
  render: () => VNode
  runStudentEffect: () => () => void
  runTeamEffect: () => () => void
  cleanupEffects: () => void
  setSession: (session: unknown) => void
  verify: ReturnType<typeof vi.fn>
  preview: ReturnType<typeof vi.fn>
  join: ReturnType<typeof vi.fn>
  assign: ReturnType<typeof vi.fn>
  successToast: ReturnType<typeof vi.fn>
}

function findButton(node: unknown, label: string): VNode | null {
  if (!node || typeof node !== 'object') return null
  const candidate = node as VNode
  if (candidate.type === 'button' && candidate.props.children === label) return candidate
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

async function loadBillingHarness(kind: 'student' | 'team'): Promise<Harness> {
  vi.resetModules()
  let studentToken: string | null = kind === 'student' ? 'student-token-a' : null
  let teamToken: string | null = kind === 'team' ? 'team-token-a' : null
  let session: unknown = {
    user: { id: 'account-a', email: 'a@example.com', name: 'A' },
    session: { token: 'session-a' },
  }
  let hookIndex = 0
  let states: unknown[] = []
  let refs: Array<{ current: unknown }> = []
  let effects: Array<() => void | (() => void)> = []
  const cleanups: Array<() => void> = []
  const verify = vi.fn()
  const preview = vi.fn().mockResolvedValue({ success: true, data: { success: true, message: 'Ready' } })
  const join = vi.fn()
  const assign = vi.fn()
  const successToast = vi.fn()

  vi.stubGlobal('window', { location: { origin: 'http://localhost:5180', assign } })
  vi.doMock('react', () => ({
    Suspense: 'Suspense',
    useCallback: (callback: unknown) => callback,
    useEffect: (effect: () => void | (() => void)) => { effects.push(effect) },
    useMemo: (factory: () => unknown) => factory(),
    useRef: (initial: unknown) => {
      const index = hookIndex++
      refs[index] ??= { current: initial }
      return refs[index]
    },
    useState: (initial: unknown) => {
      const index = hookIndex++
      if (!(index in states)) states[index] = initial
      return [states[index], (value: unknown) => {
        states[index] = typeof value === 'function'
          ? (value as (previous: unknown) => unknown)(states[index])
          : value
      }]
    },
  }))
  vi.doMock('react/jsx-runtime', () => ({
    jsx: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
    jsxs: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
  }))
  vi.doMock('next/link', () => ({ default: 'Link' }))
  vi.doMock('next/navigation', () => ({
    useRouter: () => ({ push: vi.fn() }),
    useSearchParams: () => ({ get: (key: string) => key === 'student_verify' ? studentToken : key === 'team_invite' ? teamToken : null }),
  }))
  vi.doMock('@/contexts/FeatureFlagsContext', () => ({
    useFeatureFlags: () => ({ billing: true, trial_limits: true, upgrade_ctas: true }),
  }))
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => ({ data: session, isPending: false, error: null }) }))
  vi.doMock('@/lib/api-client', () => ({
    apiClient: {
      getSubscriptionPlans: vi.fn().mockResolvedValue({ success: true, data: { plans: {}, billing: { available: true } } }),
      verifyStudentSubscription: verify,
      previewTeamSeat: preview,
      joinTeamSeat: join,
      getCurrentSubscription: vi.fn(),
    },
  }))
  vi.doMock('sonner', () => ({ toast: { success: successToast, error: vi.fn() } }))
  vi.doMock('@/components/billing/PricingCard', () => ({ default: 'PricingCard' }))
  vi.doMock('@/components/billing/SubscriptionManager', () => ({ default: 'SubscriptionManager' }))

  const page = (await import('../app/billing/page')).default() as VNode
  const content = page.props.children as VNode
  const render = () => {
    hookIndex = 0
    effects = []
    return (content.type as () => VNode)()
  }
  const runStudentEffect = () => {
    const effect = effects[2]
    if (!effect) throw new Error('student verification effect was not registered')
    const cleanup = effect()
    if (cleanup) cleanups.push(cleanup)
    return cleanup as () => void
  }
  const runTeamEffect = () => {
    const effect = effects[3]
    if (!effect) throw new Error('team invitation effect was not registered')
    const cleanup = effect()
    if (cleanup) cleanups.push(cleanup)
    return cleanup as () => void
  }
  return {
    render,
    runStudentEffect,
    runTeamEffect,
    cleanupEffects: () => { while (cleanups.length) cleanups.pop()?.() },
    setSession: (next) => { session = next },
    verify,
    preview,
    join,
    assign,
    successToast,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  for (const moduleName of [
    'react',
    'react/jsx-runtime',
    'next/link',
    'next/navigation',
    '@/contexts/FeatureFlagsContext',
    '@/lib/auth-client',
    '@/lib/api-client',
    'sonner',
    '@/components/billing/PricingCard',
    '@/components/billing/SubscriptionManager',
  ]) vi.doUnmock(moduleName)
  vi.resetModules()
})

describe('billing deferred verification responses', () => {
  it('sends one automatic student verification request through Strict Mode replay', async () => {
    const harness = await loadBillingHarness('student')
    let resolveVerification!: (value: unknown) => void
    harness.verify.mockImplementation(() => new Promise((resolve) => { resolveVerification = resolve }))
    harness.render()
    const firstCleanup = harness.runStudentEffect()
    firstCleanup()
    harness.render()
    harness.runStudentEffect()
    expect(harness.verify).toHaveBeenCalledTimes(1)

    resolveVerification({ success: true, data: { message: 'Verified', shortUrl: 'https://checkout.example.test/order' } })
    await Promise.resolve()
    await Promise.resolve()
    expect(harness.successToast).toHaveBeenCalledTimes(1)
    expect(harness.assign).toHaveBeenCalledWith('https://checkout.example.test/order')
  })

  it('suppresses a stale redirect after the signed-in account changes', async () => {
    const harness = await loadBillingHarness('student')
    let resolveOld!: (value: unknown) => void
    harness.verify.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
    harness.verify.mockResolvedValue({ success: false, error: 'new account pending' })
    harness.render()
    const cleanupOld = harness.runStudentEffect()

    harness.setSession({ user: { id: 'account-b', email: 'b@example.com' }, session: { token: 'session-b' } })
    cleanupOld()
    harness.render()
    harness.runStudentEffect()
    resolveOld({ success: true, data: { message: 'Old verification', shortUrl: 'https://old.example.test' } })
    await Promise.resolve()
    await Promise.resolve()
    expect(harness.assign).not.toHaveBeenCalled()
    expect(harness.successToast).not.toHaveBeenCalled()
    harness.cleanupEffects()
  })

  it('does not apply a pending team acceptance after the signed-in account changes', async () => {
    const harness = await loadBillingHarness('team')
    let resolveOld!: (value: unknown) => void
    harness.join.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
    harness.join.mockResolvedValue({ success: false, error: 'new account pending' })

    harness.render()
    const cleanupOld = harness.runTeamEffect()
    await Promise.resolve()
    await Promise.resolve()
    const accept = findButton(harness.render(), 'Accept team invitation')
    expect(accept).not.toBeNull()
    void (accept?.props.onClick as () => Promise<void>)()
    expect(harness.join).toHaveBeenCalledWith('team-token-a')

    harness.setSession({ user: { id: 'account-b', email: 'b@example.com' }, session: { token: 'session-b' } })
    cleanupOld()
    harness.render()
    harness.runTeamEffect()
    resolveOld({ success: true, data: { message: 'Old account activated' } })
    await Promise.resolve()
    await Promise.resolve()
    expect(harness.successToast).not.toHaveBeenCalled()
    expect(findButton(harness.render(), 'Accept team invitation')).not.toBeNull()
  })

  it('does not toast or update a team invitation after unmount', async () => {
    const harness = await loadBillingHarness('team')
    let resolveOld!: (value: unknown) => void
    harness.join.mockImplementation(() => new Promise((resolve) => { resolveOld = resolve }))
    harness.render()
    const cleanup = harness.runTeamEffect()
    await Promise.resolve()
    await Promise.resolve()
    const accept = findButton(harness.render(), 'Accept team invitation')
    void (accept?.props.onClick as () => Promise<void>)()
    cleanup()
    resolveOld({ success: true, data: { message: 'Old account activated' } })
    await Promise.resolve()
    await Promise.resolve()
    expect(harness.successToast).not.toHaveBeenCalled()
  })
})
