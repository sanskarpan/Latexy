import { afterEach, describe, expect, it, vi } from 'vitest'

type VNode = { type: unknown; props: Record<string, unknown> }

type Harness = {
  render: () => VNode
  runEffect: () => () => void
  setSession: (session: unknown) => void
  setToken: (token: string | null) => void
  accept: ReturnType<typeof vi.fn>
  stateUpdates: unknown[]
}

async function loadTenantInviteHarness(): Promise<Harness> {
  vi.resetModules()
  let token: string | null = 'invite-a'
  let session: unknown = {
    user: { id: 'account-a', email: 'a@example.com' },
    session: { token: 'session-a' },
  }
  let hookIndex = 0
  let states: unknown[] = []
  let refs: Array<{ current: unknown }> = []
  let effects: Array<() => void | (() => void)> = []
  const stateUpdates: unknown[] = []
  const accept = vi.fn()

  vi.doMock('react', () => ({
    Suspense: 'Suspense',
    useEffect: (effect: () => void | (() => void)) => { effects.push(effect) },
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
        stateUpdates.push(states[index])
      }]
    },
  }))
  vi.doMock('react/jsx-runtime', () => ({
    jsx: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
    jsxs: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
  }))
  vi.doMock('next/link', () => ({ default: 'Link' }))
  vi.doMock('next/navigation', () => ({ useSearchParams: () => ({ get: () => token }) }))
  vi.doMock('@/hooks/useRequireAuth', () => ({ useRequireAuth: () => ({ session, isPending: false, error: null }) }))
  vi.doMock('@/components/SessionLoadError', () => ({ default: 'SessionLoadError' }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: { acceptTenantInvitation: accept } }))

  const page = (await import('../app/tenant-invite/page')).default() as VNode
  const content = page.props.children as VNode
  const render = () => {
    hookIndex = 0
    effects = []
    return (content.type as () => VNode)()
  }
  return {
    render,
    runEffect: () => {
      const effect = effects[0]
      if (!effect) throw new Error('tenant invite effect was not registered')
      return effect() as (() => void)
    },
    setSession: (next) => { session = next },
    setToken: (next) => { token = next },
    accept,
    stateUpdates,
  }
}

afterEach(() => {
  vi.doUnmock('react')
  vi.doUnmock('react/jsx-runtime')
  vi.doUnmock('next/link')
  vi.doUnmock('next/navigation')
  vi.doUnmock('@/hooks/useRequireAuth')
  vi.doUnmock('@/components/SessionLoadError')
  vi.doUnmock('@/lib/api-client')
  vi.resetModules()
})

describe('tenant invitation deferred responses', () => {
  it('does not apply an acceptance result after the signed-in account changes', async () => {
    const harness = await loadTenantInviteHarness()
    let resolveOld!: () => void
    harness.accept.mockReset()
    harness.accept.mockImplementation(() => new Promise<void>((resolve) => { resolveOld = resolve }))

    harness.render()
    const cleanup = harness.runEffect()
    const first = harness.render()
    await ((first.props.children as VNode).props.onClick as () => Promise<void>)()
    expect(harness.accept).toHaveBeenCalledWith('invite-a')

    harness.setSession({ user: { id: 'account-b' }, session: { token: 'session-b' } })
    cleanup()
    harness.render()
    const nextCleanup = harness.runEffect()
    resolveOld()
    await Promise.resolve()
    await Promise.resolve()
    const current = harness.render()
    expect(current.props.title).toBe('Review your invitation')
    expect(current.props.title).not.toBe('Invitation accepted')
    nextCleanup()
  })

  it('does not update state after unmount while acceptance is pending', async () => {
    const harness = await loadTenantInviteHarness()
    let resolveOld!: () => void
    harness.accept.mockImplementation(() => new Promise<void>((resolve) => { resolveOld = resolve }))
    harness.render()
    const cleanup = harness.runEffect()
    const first = harness.render()
    await ((first.props.children as VNode).props.onClick as () => Promise<void>)()
    const updatesBeforeUnmount = harness.stateUpdates.length
    cleanup()
    resolveOld()
    await Promise.resolve()
    await Promise.resolve()
    expect(harness.stateUpdates).toHaveLength(updatesBeforeUnmount)
  })
})
